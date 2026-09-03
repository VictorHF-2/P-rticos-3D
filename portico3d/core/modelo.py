# -*- coding: utf-8 -*-
"""
modelo.py
Modelo de dados do pórtico espacial.

Unidades: consistentes, à escolha do usuário. Os exemplos e as conferências
usam kN e m — logo E em kN/m², forças em kN, momentos em kN·m.

Eixos globais: X e Y horizontais, Z vertical para cima.

Graus de liberdade por nó, sempre no sistema global e nesta ordem:

    0 ux    1 uy    2 uz    3 rx    4 ry    5 rz
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


class ErroDeModelo(Exception):
    """Modelo inconsistente: nome inexistente, barra de comprimento nulo,
    estrutura sem vinculação suficiente."""


# ---------------------------------------------------------------------------
# Materiais e seções
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Material:
    """``peso_especifico`` em kN/m³ — 25 para concreto armado, 78,5 para aço.

    O padrão é zero, e não um valor plausível: peso próprio só entra no modelo
    quando alguém pede, para que nenhuma carga apareça sem ter sido declarada.

    ``tipo``, ``fck`` e ``agregado`` guardam **como o material foi definido**,
    pelo mesmo motivo da seção: concreto declarado por classe continua sabendo
    que é concreto e qual a classe, de modo que reabrir o arquivo e trocar de
    C30 para C40 refaz o módulo sozinho. ``generico`` é o material cujo E foi
    informado direto — aço, madeira, ou concreto de módulo medido em ensaio.
    """

    nome: str
    E: float
    poisson: float = 0.2
    peso_especifico: float = 0.0
    tipo: str = "generico"
    fck: float = 0.0
    agregado: str = ""
    modulo: str = ""

    @property
    def G(self) -> float:
        return self.E / (2.0 * (1.0 + self.poisson))


@dataclass(frozen=True)
class Secao:
    """Propriedades nos eixos locais da barra.

    ``Iy`` governa a flexão no plano x–z, que é a da carga de gravidade nas
    barras horizontais; ``Iz`` governa a flexão no plano x–y.

    ``Asy`` e ``Asz`` são as áreas de cisalhamento para cortante nas direções
    local y e z. Valendo **zero**, que é o padrão, a barra é de
    Euler-Bernoulli: a deformação por cortante é ignorada, como se a rigidez
    ao cisalhamento fosse infinita. O padrão é esse, e não a área efetiva,
    porque a deformação por cortante só importa em peça baixa e alta — em viga
    esbelta ela some, e ligá-la por conta própria mudaria calados os resultados
    de todo modelo já feito.

    ``tipo``, ``b`` e ``h`` guardam **como a seção foi definida**, e não só o
    resultado: seção retangular declarada por lados continua sabendo que é
    retangular e quais são os lados. Sem isso, reabrir um modelo devolveria só
    os momentos de inércia, e mudar uma altura significaria recalcular tudo na
    mão. ``generica`` é para a seção cujas propriedades foram dadas direto.
    """

    nome: str
    A: float
    Iy: float
    Iz: float
    J: float
    Asy: float = 0.0
    Asz: float = 0.0
    tipo: str = "generica"
    b: float = 0.0
    h: float = 0.0

    @property
    def cortante(self) -> bool:
        return self.Asy > 0.0 or self.Asz > 0.0

    @staticmethod
    def criar(nome: str, tipo: str, b: float, h: float,
              cortante: bool = False) -> "Secao":
        """Fabrica a seção pelo tipo, que é o que a tabela da janela usa."""
        if tipo == "retangular":
            return Secao.retangular(nome, b, h, cortante)
        if tipo == "circular":
            return Secao.circular(nome, b, cortante)
        raise ErroDeModelo(
            f"seção '{nome}': tipo '{tipo}' não é calculável; use "
            "'retangular' ou 'circular', ou informe as propriedades")

    @staticmethod
    def retangular(nome: str, b: float, h: float,
                   cortante: bool = False) -> "Secao":
        """``b`` medido na direção local y e ``h`` na direção local z.

        A constante de torção usa a série de Saint-Venant truncada
        (J = β·a·c³, com ``a`` o lado maior e ``c`` o menor), que é a
        aproximação usual para seção retangular maciça.

        Com ``cortante``, a seção recebe as áreas de cisalhamento do retângulo
        maciço, 5/6 da área bruta nas duas direções.
        """
        if b <= 0.0 or h <= 0.0:
            raise ErroDeModelo(
                f"seção '{nome}': os lados têm de ser positivos")
        a, c = max(b, h), min(b, h)
        r = c / a
        beta = 1.0 / 3.0 - 0.21 * r * (1.0 - r ** 4 / 12.0)
        area = b * h
        cisalhante = 5.0 / 6.0 * area if cortante else 0.0
        return Secao(nome, area, b * h ** 3 / 12.0, h * b ** 3 / 12.0,
                     beta * a * c ** 3, cisalhante, cisalhante,
                     "retangular", b, h)

    @staticmethod
    def circular(nome: str, d: float, cortante: bool = False) -> "Secao":
        """Área de cisalhamento do círculo maciço: 9/10 da área bruta."""
        if d <= 0.0:
            raise ErroDeModelo(f"seção '{nome}': o diâmetro tem de ser positivo")
        i = math.pi * d ** 4 / 64.0
        area = math.pi * d * d / 4.0
        cisalhante = 0.9 * area if cortante else 0.0
        return Secao(nome, area, i, i, 2.0 * i, cisalhante, cisalhante,
                     "circular", d, d)


# ---------------------------------------------------------------------------
# Geometria
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class No:
    nome: str
    x: float
    y: float
    z: float


GDL_LOCAIS = ("u", "v", "w", "rx", "ry", "rz")
NOMES_GDL = ("ux", "uy", "uz", "rx", "ry", "rz")


@dataclass(frozen=True)
class Barra:
    """Barra de pórtico espacial entre dois nós.

    ``rotacao`` é o ângulo, em graus, de giro dos eixos locais y e z em torno
    do eixo local x. ``vetor_ref`` substitui o vetor de referência padrão
    quando a orientação da seção não é a convencional.

    ``liberacoes_i`` e ``liberacoes_j`` são os graus de liberdade **locais**
    soltos em cada extremidade, nomeados como em ``GDL_LOCAIS``. A rótula de
    viga metálica, que transmite força mas não momento de flexão, é
    ``("ry", "rz")``.

    ``offset_i`` e ``offset_j`` são os comprimentos dos **trechos rígidos** em
    cada ponta, medidos ao longo do eixo da barra. Servem para representar o
    que está dentro do nó viga-pilar: metade da largura do pilar não é vão de
    viga, e é ali que fica a diferença entre o momento no eixo do apoio e o
    momento na face, que é o de dimensionar.
    """

    nome: str
    no_i: str
    no_j: str
    material: str
    secao: str
    rotacao: float = 0.0
    vetor_ref: tuple[float, float, float] | None = None
    liberacoes_i: tuple[str, ...] = ()
    liberacoes_j: tuple[str, ...] = ()
    offset_i: float = 0.0
    offset_j: float = 0.0

    @property
    def graus_liberados(self) -> list[int]:
        """Índices, de 0 a 11, dos graus de liberdade locais soltos."""
        soltos = []
        for base, nomes in ((0, self.liberacoes_i), (6, self.liberacoes_j)):
            for nome in nomes:
                if nome not in GDL_LOCAIS:
                    raise ErroDeModelo(
                        f"barra '{self.nome}': liberação '{nome}' desconhecida; "
                        f"use um de {', '.join(GDL_LOCAIS)}")
                soltos.append(base + GDL_LOCAIS.index(nome))
        return soltos


@dataclass(frozen=True)
class Apoio:
    """Vinculação nodal. ``True`` significa deslocamento impedido."""

    no: str
    ux: bool = True
    uy: bool = True
    uz: bool = True
    rx: bool = True
    ry: bool = True
    rz: bool = True

    @property
    def restricoes(self) -> tuple[bool, ...]:
        return (self.ux, self.uy, self.uz, self.rx, self.ry, self.rz)

    @staticmethod
    def engaste(no: str) -> "Apoio":
        return Apoio(no)

    @staticmethod
    def rotula(no: str) -> "Apoio":
        return Apoio(no, True, True, True, False, False, False)


# ---------------------------------------------------------------------------
# Cargas
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CargaNodal:
    no: str
    fx: float = 0.0
    fy: float = 0.0
    fz: float = 0.0
    mx: float = 0.0
    my: float = 0.0
    mz: float = 0.0

    @property
    def vetor(self) -> np.ndarray:
        return np.array([self.fx, self.fy, self.fz,
                         self.mx, self.my, self.mz], float)


@dataclass(frozen=True)
class CargaDistribuida:
    """Carga por unidade de comprimento da barra, uniforme ou trapezoidal.

    ``sistema`` vale ``"local"`` ou ``"global"``. No sistema global, as
    componentes são projetadas nos eixos locais na montagem; a intensidade
    continua sendo por metro de barra, não por metro de projeção.

    ``inicio`` e ``fim`` delimitam o trecho carregado em posição **relativa**,
    de 0 a 1 ao longo da barra — relativa, e não em metros, para que a carga
    continue coerente se a geometria mudar. Os campos ``qx_fim``, ``qy_fim`` e
    ``qz_fim`` dão a intensidade na outra ponta do trecho; deixados em
    ``None``, a carga é uniforme.
    """

    barra: str
    qx: float = 0.0
    qy: float = 0.0
    qz: float = 0.0
    sistema: str = "local"
    inicio: float = 0.0
    fim: float = 1.0
    qx_fim: float | None = None
    qy_fim: float | None = None
    qz_fim: float | None = None

    @property
    def vetor_inicio(self) -> np.ndarray:
        return np.array([self.qx, self.qy, self.qz], float)

    @property
    def vetor_fim(self) -> np.ndarray:
        return np.array([self.qx if self.qx_fim is None else self.qx_fim,
                         self.qy if self.qy_fim is None else self.qy_fim,
                         self.qz if self.qz_fim is None else self.qz_fim],
                        float)

    @property
    def uniforme(self) -> bool:
        return bool(np.array_equal(self.vetor_inicio, self.vetor_fim))


@dataclass(frozen=True)
class Recalque:
    """Deslocamento imposto a um nó, nas direções em que ele tem apoio.

    O recalque é uma ação, e por isso mora no caso de carga e não no apoio:
    ele entra nas combinações com o seu próprio coeficiente, como qualquer
    outra ação indireta.
    """

    no: str
    ux: float = 0.0
    uy: float = 0.0
    uz: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0

    @property
    def vetor(self) -> np.ndarray:
        return np.array([self.ux, self.uy, self.uz,
                         self.rx, self.ry, self.rz], float)


@dataclass(frozen=True)
class Laje:
    """Painel de laje, definido pelos dois cantos de uma diagonal.

    A laje **não é elemento de cálculo** aqui: ela é um painel de carga. O
    programa calcula o peso próprio pela espessura, soma o revestimento e o
    acidental, e reparte tudo para as quatro vigas de contorno pelas áreas de
    influência a 45°. Quem dimensiona laje é o programa de Lajes; o que falta
    ao pórtico é a carga que ela entrega às vigas, e é isso que está aqui.

    Uma consequência disso que precisa estar clara: **a laje não trabalha como
    diafragma**. Ela não enrijece o pavimento no próprio plano, de modo que as
    prumadas resistem ao vento cada uma pela sua rigidez, sem a compatibilização
    horizontal que uma laje real impõe.
    """

    nome: str
    no_a: str
    no_c: str
    espessura: float = 0.0
    material: str = ""
    permanente: float = 0.0
    acidental: float = 0.0


@dataclass(frozen=True)
class Mola:
    """Apoio elástico: rigidez concentrada num nó, nos eixos globais."""

    no: str
    kx: float = 0.0
    ky: float = 0.0
    kz: float = 0.0
    krx: float = 0.0
    kry: float = 0.0
    krz: float = 0.0

    @property
    def vetor(self) -> np.ndarray:
        return np.array([self.kx, self.ky, self.kz,
                         self.krx, self.kry, self.krz], float)


@dataclass
class CasoDeCarga:
    """Um caso de carga e a sua classificação normativa.

    ``natureza`` é ``"permanente"`` ou ``"variavel"``; ``categoria`` é a linha
    da tabela de ψ da NBR 6118; ``grupo`` marca casos mutuamente excludentes,
    como as várias incidências de vento. A classificação mora aqui, e não em
    estrutura à parte, porque é o arquivo do modelo que precisa carregá-la
    para que outro programa consiga montar as combinações sozinho.
    """

    nome: str
    nodais: list[CargaNodal] = field(default_factory=list)
    distribuidas: list[CargaDistribuida] = field(default_factory=list)
    recalques: list[Recalque] = field(default_factory=list)
    natureza: str = "permanente"
    categoria: str = ""
    grupo: str = ""

    def nodal(self, no: str, fx: float = 0.0, fy: float = 0.0, fz: float = 0.0,
              mx: float = 0.0, my: float = 0.0, mz: float = 0.0) -> CargaNodal:
        carga = CargaNodal(no, fx, fy, fz, mx, my, mz)
        self.nodais.append(carga)
        return carga

    def distribuida(self, barra: str, qx: float = 0.0, qy: float = 0.0,
                    qz: float = 0.0, sistema: str = "local",
                    inicio: float = 0.0, fim: float = 1.0,
                    qx_fim: float | None = None, qy_fim: float | None = None,
                    qz_fim: float | None = None) -> CargaDistribuida:
        if sistema not in ("local", "global"):
            raise ErroDeModelo(
                f"sistema '{sistema}' inválido: use 'local' ou 'global'")
        if not 0.0 <= inicio < fim <= 1.0:
            raise ErroDeModelo(
                f"trecho [{inicio}, {fim}] inválido: use 0 ≤ início < fim ≤ 1")
        carga = CargaDistribuida(barra, qx, qy, qz, sistema, inicio, fim,
                                 qx_fim, qy_fim, qz_fim)
        self.distribuidas.append(carga)
        return carga

    def recalque(self, no: str, ux: float = 0.0, uy: float = 0.0,
                 uz: float = 0.0, rx: float = 0.0, ry: float = 0.0,
                 rz: float = 0.0) -> Recalque:
        r = Recalque(no, ux, uy, uz, rx, ry, rz)
        self.recalques.append(r)
        return r


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------

@dataclass
class Modelo:
    nome: str = "modelo"
    materiais: dict[str, Material] = field(default_factory=dict)
    secoes: dict[str, Secao] = field(default_factory=dict)
    nos: dict[str, No] = field(default_factory=dict)
    barras: dict[str, Barra] = field(default_factory=dict)
    apoios: dict[str, Apoio] = field(default_factory=dict)
    molas: dict[str, Mola] = field(default_factory=dict)
    lajes: dict[str, Laje] = field(default_factory=dict)
    casos: dict[str, CasoDeCarga] = field(default_factory=dict)

    # -- construção ---------------------------------------------------------

    def add_material(self, nome: str, E: float, poisson: float = 0.2,
                     peso_especifico: float = 0.0, tipo: str = "generico",
                     fck: float = 0.0, agregado: str = "",
                     modulo: str = "") -> Material:
        self.materiais[nome] = Material(nome, E, poisson, peso_especifico,
                                        tipo, fck, agregado, modulo)
        return self.materiais[nome]

    def add_secao(self, secao: Secao) -> Secao:
        self.secoes[secao.nome] = secao
        return secao

    def add_no(self, nome: str, x: float, y: float, z: float) -> No:
        if nome in self.nos:
            raise ErroDeModelo(f"nó '{nome}' já existe")
        self.nos[nome] = No(nome, x, y, z)
        return self.nos[nome]

    def add_barra(self, nome: str, no_i: str, no_j: str, material: str,
                  secao: str, rotacao: float = 0.0,
                  vetor_ref: tuple[float, float, float] | None = None,
                  liberacoes_i: tuple[str, ...] = (),
                  liberacoes_j: tuple[str, ...] = (),
                  offset_i: float = 0.0, offset_j: float = 0.0) -> Barra:
        if nome in self.barras:
            raise ErroDeModelo(f"barra '{nome}' já existe")
        self.barras[nome] = Barra(nome, no_i, no_j, material, secao,
                                  rotacao, vetor_ref, liberacoes_i,
                                  liberacoes_j, offset_i, offset_j)
        return self.barras[nome]

    def add_laje(self, nome: str, no_a: str, no_c: str, espessura: float = 0.0,
                 material: str = "", permanente: float = 0.0,
                 acidental: float = 0.0) -> Laje:
        if nome in self.lajes:
            raise ErroDeModelo(f"laje '{nome}' já existe")
        self.lajes[nome] = Laje(nome, no_a, no_c, espessura, material,
                                permanente, acidental)
        return self.lajes[nome]

    def add_mola(self, no: str, kx: float = 0.0, ky: float = 0.0,
                 kz: float = 0.0, krx: float = 0.0, kry: float = 0.0,
                 krz: float = 0.0) -> Mola:
        self.molas[no] = Mola(no, kx, ky, kz, krx, kry, krz)
        return self.molas[no]

    def apoiar(self, no: str, ux: bool = True, uy: bool = True, uz: bool = True,
               rx: bool = True, ry: bool = True, rz: bool = True) -> Apoio:
        self.apoios[no] = Apoio(no, ux, uy, uz, rx, ry, rz)
        return self.apoios[no]

    def add_caso(self, nome: str, natureza: str = "permanente",
                 categoria: str = "", grupo: str = "") -> CasoDeCarga:
        self.casos[nome] = CasoDeCarga(nome, natureza=natureza,
                                       categoria=categoria, grupo=grupo)
        return self.casos[nome]

    # -- consultas ----------------------------------------------------------

    @property
    def n_gdl(self) -> int:
        return 6 * len(self.nos)

    def indice(self, no: str) -> int:
        try:
            return list(self.nos).index(no)
        except ValueError:
            raise ErroDeModelo(f"nó '{no}' não existe") from None

    def gdl(self, no: str) -> list[int]:
        base = 6 * self.indice(no)
        return [base + k for k in range(6)]

    def ponto(self, no: str) -> np.ndarray:
        n = self.nos.get(no)
        if n is None:
            raise ErroDeModelo(f"nó '{no}' não existe")
        return np.array([n.x, n.y, n.z], float)

    def comprimento(self, barra: str) -> float:
        b = self.barras[barra]
        return float(np.linalg.norm(self.ponto(b.no_j) - self.ponto(b.no_i)))

    # -- verificação --------------------------------------------------------

    def validar(self) -> None:
        if not self.nos:
            raise ErroDeModelo("modelo sem nós")
        if not self.barras:
            raise ErroDeModelo("modelo sem barras")
        if not self.apoios and not self.molas:
            raise ErroDeModelo("modelo sem apoios nem molas")

        for b in self.barras.values():
            for no in (b.no_i, b.no_j):
                if no not in self.nos:
                    raise ErroDeModelo(
                        f"barra '{b.nome}' cita o nó '{no}', que não existe")
            if b.material not in self.materiais:
                raise ErroDeModelo(
                    f"barra '{b.nome}' cita o material '{b.material}', "
                    "que não existe")
            if b.secao not in self.secoes:
                raise ErroDeModelo(
                    f"barra '{b.nome}' cita a seção '{b.secao}', que não existe")
            L = self.comprimento(b.nome)
            if L <= 0.0:
                raise ErroDeModelo(f"barra '{b.nome}' tem comprimento nulo")
            if b.offset_i < 0.0 or b.offset_j < 0.0:
                raise ErroDeModelo(
                    f"barra '{b.nome}' tem trecho rígido negativo")
            if b.offset_i + b.offset_j >= L:
                raise ErroDeModelo(
                    f"barra '{b.nome}': os trechos rígidos somam "
                    f"{b.offset_i + b.offset_j:.4f} m e não sobra vão "
                    f"flexível no comprimento de {L:.4f} m")
            b.graus_liberados

        for no in self.apoios:
            if no not in self.nos:
                raise ErroDeModelo(f"apoio no nó '{no}', que não existe")

        for no in self.molas:
            if no not in self.nos:
                raise ErroDeModelo(f"mola no nó '{no}', que não existe")

        for laje in self.lajes.values():
            for no in (laje.no_a, laje.no_c):
                if no not in self.nos:
                    raise ErroDeModelo(
                        f"laje '{laje.nome}' cita o nó '{no}', que não existe")
            if laje.espessura > 0.0 and laje.material not in self.materiais:
                raise ErroDeModelo(
                    f"laje '{laje.nome}' tem espessura mas o material "
                    f"'{laje.material}' não existe; sem ele não há como pesar")

        for caso in self.casos.values():
            for c in caso.nodais:
                if c.no not in self.nos:
                    raise ErroDeModelo(
                        f"caso '{caso.nome}': carga no nó '{c.no}', "
                        "que não existe")
            for c in caso.distribuidas:
                if c.barra not in self.barras:
                    raise ErroDeModelo(
                        f"caso '{caso.nome}': carga na barra '{c.barra}', "
                        "que não existe")
            for r in caso.recalques:
                if r.no not in self.nos:
                    raise ErroDeModelo(
                        f"caso '{caso.nome}': recalque no nó '{r.no}', "
                        "que não existe")
                apoio = self.apoios.get(r.no)
                for k, valor in enumerate(r.vetor):
                    if valor != 0.0 and (apoio is None
                                         or not apoio.restricoes[k]):
                        raise ErroDeModelo(
                            f"caso '{caso.nome}': recalque de "
                            f"{NOMES_GDL[k]} no nó '{r.no}', que não tem apoio "
                            "nessa direção — deslocamento imposto só faz "
                            "sentido onde há vínculo")
