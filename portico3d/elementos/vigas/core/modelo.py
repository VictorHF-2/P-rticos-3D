# -*- coding: utf-8 -*-
"""
modelo.py
Modelo de dados de entrada da viga: geometria, apoios, carregamentos,
materiais e opções de cálculo. Nada aqui calcula esforços -- é a descrição
do problema, consumida pelos módulos de análise e dimensionamento.

Convenções:
    x ......... coordenada global, em metros, medida a partir da extremidade
                esquerda da viga (nó 0).
    cargas .... positivas para baixo (gravidade).
    momentos .. positivos no sentido anti-horário.
    seções .... dimensões em centímetros.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict

from .materiais import Aco, Ambiente, Concreto
from . import avisos as av

# ---------------------------------------------------------------------------
# Seção transversal
# ---------------------------------------------------------------------------

TIPOS_SECAO = ("retangular", "T", "T invertida")

#: Largura mínima da alma, cm (13.2.2): 12 cm em viga, 15 cm em viga-parede.
LARGURA_MINIMA_VIGA = 12.0
LARGURA_MINIMA_VIGA_PAREDE = 15.0
#: Mínimo absoluto, admitido só em casos excepcionais (13.2.2).
LARGURA_MINIMA_ABSOLUTA = 10.0


@dataclass
class Secao:
    """Seção transversal da viga, em centímetros.

    Para a seção T, ``bf`` e ``hf`` descrevem a mesa colaborante superior;
    na T invertida a mesa fica na face inferior (tração).
    """

    bw: float = 20.0
    h: float = 50.0
    tipo: str = "retangular"
    bf: float = 0.0
    hf: float = 0.0

    def __post_init__(self) -> None:
        if self.tipo not in TIPOS_SECAO:
            raise ValueError(f"Tipo de seção desconhecido: {self.tipo!r}")
        if self.tipo == "retangular":
            self.bf = self.bw
            self.hf = 0.0
        elif self.bf < self.bw:
            raise ValueError("bf não pode ser menor que bw na seção T.")

    @property
    def area(self) -> float:
        """Área bruta de concreto, cm²."""
        if self.tipo == "retangular":
            return self.bw * self.h
        return self.bw * self.h + (self.bf - self.bw) * self.hf

    @property
    def perimetro_forma(self) -> float:
        """Perímetro que precisa de forma, cm — **o topo não conta**.

        Forma existe onde o concreto vazaria. A face superior é por onde se
        lança o concreto: ela não vaza, é acabada. Então formam-se o fundo e
        as laterais, e o desenvolvimento dá o mesmo para os três tipos de
        seção -- ``bf + 2h`` --, o que é menos coincidência do que parece:

        * **retangular**: fundo ``bw`` + laterais ``2h``. Como ``bf`` é
          forçado igual a ``bw`` no ``__post_init__``, a expressão fecha;
        * **T** (mesa em cima): fundo da alma ``bw`` + laterais da alma
          ``2(h - hf)`` + **fundo das abas** ``bf - bw`` + bordas da mesa
          ``2hf``. A projeção horizontal formada é ``bw + (bf - bw) = bf`` e a
          vertical é ``2(h - hf) + 2hf = 2h``;
        * **T invertida** (mesa embaixo): fundo da mesa ``bf`` + bordas da
          mesa ``2hf`` + laterais da alma ``2(h - hf)``. Aqui o **topo das
          abas** não é formado -- é superfície voltada para cima, acabada --,
          e a conta cai no mesmo lugar.

        Vale para a viga tomada como **elemento isolado**: nada é descontado
        por laje, viga transversal ou face contra concreto existente. Numa
        seção T de piso real a mesa costuma ser a laje, e aí essa parte da
        forma pertence à laje, não à viga -- o quantitativo declara a hipótese
        para quem lê não tomar o número por completo.
        """
        return self.bf + 2.0 * self.h

    @property
    def y_cg(self) -> float:
        """Distância do CG à fibra inferior, cm."""
        if self.tipo == "retangular":
            return self.h / 2.0
        alma = self.bw * self.h
        mesa = (self.bf - self.bw) * self.hf
        if self.tipo == "T":
            y_mesa = self.h - self.hf / 2.0
        else:
            y_mesa = self.hf / 2.0
        return (alma * self.h / 2.0 + mesa * y_mesa) / (alma + mesa)

    @property
    def inercia(self) -> float:
        """Momento de inércia da seção bruta em relação ao CG, cm^4."""
        if self.tipo == "retangular":
            return self.bw * self.h ** 3 / 12.0
        yg = self.y_cg
        alma = self.bw * self.h
        i_alma = self.bw * self.h ** 3 / 12.0 + alma * (self.h / 2.0 - yg) ** 2
        b_mesa = self.bf - self.bw
        mesa = b_mesa * self.hf
        y_mesa = self.h - self.hf / 2.0 if self.tipo == "T" else self.hf / 2.0
        i_mesa = b_mesa * self.hf ** 3 / 12.0 + mesa * (y_mesa - yg) ** 2
        return i_alma + i_mesa

    @property
    def w_inferior(self) -> float:
        """Módulo resistente da fibra inferior, cm³."""
        return self.inercia / self.y_cg

    @property
    def w_superior(self) -> float:
        return self.inercia / (self.h - self.y_cg)

    def peso_proprio(self, peso_especifico: float = 25.0) -> float:
        """Peso próprio, kN/m, para o peso específico dado em kN/m³."""
        return self.area / 1e4 * peso_especifico

    def descricao(self) -> str:
        if self.tipo == "retangular":
            return f"{self.bw:g}x{self.h:g} cm"
        return (f"{self.tipo} bw={self.bw:g} h={self.h:g} "
                f"bf={self.bf:g} hf={self.hf:g} cm")


# ---------------------------------------------------------------------------
# Tramos e apoios
# ---------------------------------------------------------------------------

TIPOS_APOIO = ("livre", "simples", "engaste", "mola")


@dataclass
class Apoio:
    """Apoio da viga.

    ``livre`` .... extremidade em balanço (nenhuma restrição);
    ``simples`` .. impede o deslocamento vertical;
    ``engaste`` .. impede deslocamento e rotação;
    ``mola`` ..... impede o deslocamento e restringe a rotação por ``k_mola``
                   (kN.m/rad), útil para representar a rigidez dos pilares.
    """

    tipo: str = "simples"
    largura: float = 20.0     # cm, largura do pilar de apoio
    k_mola: float = 0.0       # kN.m/rad
    nome: str = ""

    def __post_init__(self) -> None:
        if self.tipo not in TIPOS_APOIO:
            raise ValueError(f"Tipo de apoio desconhecido: {self.tipo!r}")


@dataclass
class Trecho:
    """Um trecho prismático da viga: pedaço de seção constante.

    Derivado, não editado: sai de :attr:`Viga.trechos`, que o monta a partir
    dos tramos e das mudanças de seção. Guardar isto seria manter duas verdades
    sobre a mesma geometria.
    """

    k: int                    # índice global do trecho
    tramo: int                # tramo a que pertence
    x_ini: float              # m, coordenada global de início
    x_fim: float              # m
    secao: "Secao" = field(default_factory=lambda: Secao())
    #: como este trecho se encosta no **anterior**; vazio quando as seções
    #: coincidem. Ver :mod:`vigas.core.alinhamento`
    alinhamento: str = ""

    @property
    def L(self) -> float:
        """Comprimento do trecho, m."""
        return self.x_fim - self.x_ini

    @property
    def x_meio(self) -> float:
        return (self.x_ini + self.x_fim) / 2.0


@dataclass
class MudancaSecao:
    """Uma mudança de seção **dentro** de um tramo.

    ``x`` é medido do apoio esquerdo do tramo, em metros, e tem de cair dentro
    dele (``0 < x < L``). A seção vale dali até a mudança seguinte, ou até o
    fim do tramo.

    O ``alinhamento`` é a mesma decisão que já existia entre tramos, e pelo
    mesmo motivo: dizer que a seção passa de 50 para 70 não diz por onde as
    duas se encostam, e são três detalhamentos diferentes. Aqui não há pilar
    para ocupar, então o degrau acontece exatamente em ``x``.
    """

    x: float = 0.0
    secao: Secao = field(default_factory=Secao)
    alinhamento: str = ""


@dataclass
class Tramo:
    """Trecho entre dois apoios consecutivos (ou balanço)."""

    L: float = 5.0            # m, vão teórico (entre eixos de apoio)
    secao: Secao = field(default_factory=Secao)
    nome: str = ""
    #: mudanças de seção dentro deste tramo, em ordem de x crescente. Vazio =
    #: tramo prismático, e :attr:`secao` vale do começo ao fim
    mudancas: list[MudancaSecao] = field(default_factory=list)
    #: como este tramo se encosta no **anterior**, quando a seção muda de um
    #: para o outro ("Topo", "Meio", "Fundo" pela altura; "Esquerda",
    #: "Centro", "Direita" pela largura; os dois separados por " / " quando
    #: altura e largura mudam juntas). Vazio quando as seções coincidem, e o
    #: campo não aceita entrada. Ver :mod:`vigas.core.alinhamento`
    alinhamento: str = ""


# ---------------------------------------------------------------------------
# Cargas
# ---------------------------------------------------------------------------

ACOES = ("g", "q")            # permanente / variável


@dataclass
class CargaDistribuida:
    """Carga linear, eventualmente trapezoidal, em kN/m (positiva p/ baixo)."""

    q1: float = 0.0
    q2: float | None = None   # None -> uniforme (q2 = q1)
    x_ini: float = 0.0        # m, coordenada global
    x_fim: float = 0.0
    acao: str = "g"
    descricao: str = ""

    def __post_init__(self) -> None:
        if self.q2 is None:
            self.q2 = self.q1
        if self.x_fim < self.x_ini:
            self.x_ini, self.x_fim = self.x_fim, self.x_ini
            self.q1, self.q2 = self.q2, self.q1

    def valor(self, x: float) -> float:
        if not (self.x_ini <= x <= self.x_fim) or self.x_fim <= self.x_ini:
            return 0.0
        t = (x - self.x_ini) / (self.x_fim - self.x_ini)
        return self.q1 + (self.q2 - self.q1) * t


@dataclass
class CargaConcentrada:
    """Força concentrada, kN, positiva para baixo."""

    P: float = 0.0
    x: float = 0.0
    acao: str = "g"
    descricao: str = ""
    #: 18.3.6 -- carga trazida por outra viga ou elemento que se apoia nesta
    #: (ou nela fica pendurado): exige armadura de suspensão
    indireta: bool = False
    #: "Define-se uma situação de viga pendurada quando a face inferior da viga
    #: apoiada está abaixo da face inferior da viga de apoio" (18.3.6). A conta
    #: é outra: 100 % do tirante para levar a força ao banzo comprimido, mais
    #: 50 % de reforço da região, e nada vai para a viga apoiada
    pendurada: bool = False


@dataclass
class MomentoAplicado:
    """Momento concentrado aplicado, kN.m, positivo anti-horário."""

    M: float = 0.0
    x: float = 0.0
    acao: str = "g"
    descricao: str = ""


@dataclass
class TorcorAplicado:
    """Torçor concentrado ou distribuído aplicado ao eixo da viga.

    ``T`` em kN.m quando concentrado (``x_fim`` nulo) ou em kN.m/m quando
    distribuído entre ``x`` e ``x_fim``.
    """

    T: float = 0.0
    x: float = 0.0
    x_fim: float | None = None
    acao: str = "g"
    descricao: str = ""


# ---------------------------------------------------------------------------
# Opções de cálculo
# ---------------------------------------------------------------------------

@dataclass
class Config:
    """Coeficientes, modelos e critérios adotados no dimensionamento."""

    # -- ações e combinações (NBR 8681 / NBR 6118, 11.7) --------------------
    gamma_g: float = 1.4
    gamma_g_fav: float = 1.0
    gamma_q: float = 1.4
    psi0: float = 0.5
    psi1: float = 0.4
    psi2: float = 0.3
    alternancia: bool = True      # padrões alternados de carga acidental

    # -- análise ------------------------------------------------------------
    peso_proprio: bool = True
    redistribuicao: float = 1.0   # delta (1,0 = análise elástica sem redistribuir)
    momento_face_apoio: bool = True   # reduz o momento negativo à face do pilar
    #: Engastamento parcial mínimo nos apoios extremos, como fração do momento
    #: do vão adjacente. Não é exigência da NBR 6118 -- é critério de projeto,
    #: usual quando a viga é monolítica com o pilar. 0 desliga.
    engastamento_minimo_extremidade: float = 0.0

    # -- cisalhamento (17.4.2) ---------------------------------------------
    modelo_cisalhamento: int = 1  # 1 (biela a 45°) ou 2 (biela variável)
    theta: float = 45.0           # graus, inclinação da biela no Modelo II
    alpha_estribo: float = 90.0   # graus, inclinação dos estribos
    reducao_apoio: bool = True    # 17.4.1.2.1: cargas próximas ao apoio

    # -- torção (17.5) ------------------------------------------------------
    #: Lançar um torçor já é o pedido para verificar a torção; desligar aqui é
    #: uma decisão explícita, cabível só na torção de compatibilidade (17.5.1.2)
    considerar_torcao: bool = True
    torcao_equilibrio: bool = True   # False = torção de compatibilidade

    # -- ELS (17.3) ---------------------------------------------------------
    verificar_els: bool = True
    #: 23.5 -- verificação de fadiga. Desligada por padrão: só se aplica a
    #: estruturas com ações cíclicas relevantes (23.5.1)
    verificar_fadiga: bool = False
    #: psi1 da combinação frequente de fadiga (23.5.2); 0 usa o psi1 geral
    psi1_fadiga: float = 0.0
    tempo_meses: float = 70.0     # t para a flecha diferida (17.3.2.1.2)
    t0_meses: float = 1.0         # idade da aplicação da carga de longa duração
    limite_flecha_visual: float = 250.0   # L/250 (Tabela 13.3)
    limite_flecha_alvenaria: float = 500.0  # L/500 após a execução da alvenaria
    #: Tabela 13.3 -- o que se apoia na viga define o limite do deslocamento
    #: posterior: "alvenaria" (L/500 e 10 mm), "divisoria" (L/250 e 25 mm) ou
    #: "nenhuma" (não verifica)
    parede_apoiada: str = "alvenaria"
    #: Tabela 13.3 -- vibrações sentidas no piso: flecha das cargas variáveis
    #: limitada a L/350. Critério opcional, por tipo de uso
    verificar_vibracao: bool = False
    limite_flecha_vibracao: float = 350.0
    #: Tabela 13.3 -- pavimentos que devem permanecer planos: L/350 no total e
    #: L/600 no deslocamento ocorrido após a construção do piso
    verificar_piso_plano: bool = False
    limite_piso_total: float = 350.0
    limite_piso_apos: float = 600.0

    # -- detalhamento -------------------------------------------------------
    phi_estribo: float = 5.0      # mm
    n_ramos: int = 2
    phi_longitudinal: float = 0.0     # 0 = o programa escolhe
    #: bitola imposta região por região, mm, chaveada pelo nome da região
    #: ("Vão 1", "Apoio 2"). Ausente ou 0 = o programa escolhe. É o que
    #: permite ao usuário trocar a bitola direto na tabela de resultados e ver
    #: o dimensionamento inteiro se refazer
    bitolas_flexao: dict = field(default_factory=dict)
    #: bitola imposta do estribo, mm, chaveada pelo índice do tramo **como
    #: texto** -- o JSON não guarda chave numérica
    bitolas_estribo: dict = field(default_factory=dict)
    #: uma única distribuição de estribos por tramo, a mais conservadora entre
    #: as faixas do escalonamento
    uniformizar_estribos: bool = False
    #: completar com grampos a ancoragem de extremidade que não cabe no apoio
    #: nem com gancho, em vez de reprovar o apoio
    usar_grampos: bool = True
    #: bitola do grampo de ancoragem, mm; se ela passar do teto
    #: (lb,disp/lanc)·Ø da armadura, o programa procura a mais fina que cabe
    phi_grampo: float = 6.3
    phi_max_longitudinal: float = 25.0
    phi_min_longitudinal: float = 8.0
    d_agregado: float = 1.9       # cm, dimensão máxima do agregado
    #: cm somados ao perímetro do estribo pelas pernas das dobras de
    #: amarração, além dos ganchos de 5 phi já contados (item 9.4.6.1)
    pernas_amarracao_estribo: float = 10.0
    #: 9.4.6.1 -- estribo fechado por gancho de 5 phi. Desligar significa
    #: fechamento por barra transversal soldada (9.4.6.2), sem o gancho
    gancho_estribo: bool = True
    #: 18.3.2.4.1 -- permite o gancho na ancoragem do apoio de extremidade.
    #: Desligado, a ancoragem tem de caber reta
    ancoragem_gancho: bool = True
    #: tipo de gancho das barras de tração (9.4.2.3): "Semicircular", "45°"
    #: ou "Ângulo reto". Muda a ponta reta (2 Ø, 4 Ø ou 8 Ø) e a geometria da
    #: dobra; ver :mod:`vigas.core.ganchos`
    tipo_gancho: str = "Ângulo reto"
    #: tipo de gancho imposto por região, chaveado pelo nome da região como
    #: texto -- vem da droplist da tabela de flexão
    ganchos_flexao: dict = field(default_factory=dict)
    #: tomar o α = 0,7 do item 9.4.2.5 quando há gancho. Desligado por padrão:
    #: o gancho fica como reserva de segurança e a ancoragem é dimensionada
    #: como reta, que é o critério de projeto adotado
    reduzir_ancoragem_com_gancho: bool = False
    #: 13.2.2 -- admite largura abaixo de 12 cm (mínimo absoluto de 10 cm),
    #: o que a norma só aceita em casos excepcionais
    largura_reduzida_excepcional: bool = False

    def validar(self) -> list[str]:
        avisos: list[str] = []
        if self.modelo_cisalhamento not in (1, 2):
            raise ValueError("O modelo de cisalhamento deve ser 1 ou 2.")
        if self.modelo_cisalhamento == 2 and not (30.0 <= self.theta <= 45.0):
            avisos.append(av.erro("O item 17.4.2.3 limita a biela do Modelo "
                                  "II a 30° <= theta <= 45°."))
        if not (45.0 <= self.alpha_estribo <= 90.0):
            avisos.append(av.erro(
                "O item 17.4.2 admite estribos entre 45° e 90°."))
        elif self.alpha_estribo < 89.9:
            # o cálculo trata o estribo inclinado (a treliça, a asw,mín pelo
            # sen alfa, o espaçamento e a decalagem), mas o **desenho** traça
            # o estribo sempre vertical. Cálculo e desenho discordando sem
            # aviso é pior que uma limitação: quem lê a prancha monta a 90°
            avisos.append(av.construtivo(
                f"Estribos inclinados a {self.alpha_estribo:g}°: o cálculo "
                f"considera a inclinação (treliça do item 17.4.2, armadura "
                f"mínima pelo sen α, espaçamento e decalagem), mas o desenho "
                f"ainda representa o estribo na vertical. O detalhamento dos "
                f"estribos deste projeto tem de ser feito manualmente: use as "
                f"áreas e os espaçamentos calculados e desenhe as peças com a "
                f"inclinação real."))
        if not (0.75 <= self.redistribuicao <= 1.0):
            avisos.append(av.erro("O item 14.6.4.3 limita a redistribuição "
                                  "a delta >= 0,75 em estruturas de nós "
                                  "fixos."))
        return avisos


# ---------------------------------------------------------------------------
# Viga
# ---------------------------------------------------------------------------

@dataclass
class Viga:
    """Descrição completa de uma viga contínua de concreto armado."""

    nome: str = "V1"
    tramos: list[Tramo] = field(default_factory=lambda: [Tramo()])
    apoios: list[Apoio] = field(default_factory=lambda: [Apoio(), Apoio()])
    distribuidas: list[CargaDistribuida] = field(default_factory=list)
    concentradas: list[CargaConcentrada] = field(default_factory=list)
    momentos: list[MomentoAplicado] = field(default_factory=list)
    torcores: list[TorcorAplicado] = field(default_factory=list)
    concreto: Concreto = field(default_factory=Concreto)
    aco: Aco = field(default_factory=Aco)
    #: aço da armadura **transversal** (estribos, grampos, costura). Separado
    #: porque as bitolas finas -- Ø5,0 e Ø4,2, as usuais de estribo -- só se
    #: produzem em CA-60, e a armadura mínima do item 17.4.1.1.1 é inversamente
    #: proporcional ao fywk **do aço transversal**. Com um aço só para tudo, o
    #: estribo Ø5 saía dimensionado como CA-50 e a armadura mínima vinha 20 %
    #: maior que o devido
    aco_estribo: Aco = field(default_factory=lambda: Aco("CA-60"))
    ambiente: Ambiente = field(default_factory=Ambiente)
    config: Config = field(default_factory=Config)
    projeto: str = ""
    #: texto livre do projetista, impresso na capa da memória de cálculo
    observacoes: str = ""

    # -- geometria ----------------------------------------------------------
    def __post_init__(self) -> None:
        if len(self.apoios) != len(self.tramos) + 1:
            raise ValueError(
                f"A viga tem {len(self.tramos)} tramo(s) e precisa de "
                f"{len(self.tramos) + 1} apoios; foram informados "
                f"{len(self.apoios)}.")

    @property
    def x_apoios(self) -> list[float]:
        """Coordenada global de cada apoio, m."""
        xs = [0.0]
        for t in self.tramos:
            xs.append(xs[-1] + t.L)
        return xs

    @property
    def comprimento(self) -> float:
        return sum(t.L for t in self.tramos)

    @property
    def x_inicio_fisico(self) -> float:
        """Extremidade esquerda real da viga, m (entra meio pilar no apoio)."""
        ap = self.apoios[0]
        return 0.0 if ap.tipo == "livre" else -ap.largura / 200.0

    @property
    def x_fim_fisico(self) -> float:
        """Extremidade direita real da viga, m."""
        ap = self.apoios[-1]
        L = self.comprimento
        return L if ap.tipo == "livre" else L + ap.largura / 200.0

    def tramo_em(self, x: float) -> int:
        """Índice do tramo que contém a coordenada global ``x``."""
        xs = self.x_apoios
        for i in range(len(self.tramos)):
            if xs[i] - 1e-9 <= x <= xs[i + 1] + 1e-9:
                return i
        return len(self.tramos) - 1

    @property
    def trechos(self) -> list["Trecho"]:
        """Os trechos prismáticos da viga, em ordem.

        **Trecho** e **tramo** são coisas diferentes, e a distinção é o coração
        da seção variável: o tramo é a unidade estrutural (entre apoios, é dele
        que se fala em "flecha do tramo 2"), o trecho é a unidade de
        **geometria** (um pedaço de seção constante). Numa viga prismática há um
        trecho por tramo e os dois índices coincidem; com uma mudança de seção
        no meio do vão, um tramo tem dois trechos.

        Tudo que pergunta "qual a seção aqui" pergunta pelo trecho. Tudo que
        pergunta "qual o vão, qual a flecha, qual o momento" pergunta pelo
        tramo. Misturar os dois é o que fazia o desenho estampar a seção do
        início do vão no fim dele.
        """
        saida: list[Trecho] = []
        xs = self.x_apoios
        for i, t in enumerate(self.tramos):
            cortes = sorted((m for m in t.mudancas if 1e-9 < m.x < t.L - 1e-9),
                            key=lambda m: m.x)
            a = xs[i]
            secao, alinhamento = t.secao, t.alinhamento
            for m in cortes:
                saida.append(Trecho(k=len(saida), tramo=i, x_ini=a,
                                    x_fim=xs[i] + m.x, secao=secao,
                                    alinhamento=alinhamento))
                a = xs[i] + m.x
                secao, alinhamento = m.secao, m.alinhamento
            saida.append(Trecho(k=len(saida), tramo=i, x_ini=a,
                                x_fim=xs[i + 1], secao=secao,
                                alinhamento=alinhamento))
        return saida

    def trecho_em(self, x: float) -> int:
        """Índice do trecho prismático que contém ``x``.

        Fora do vão teórico -- dentro dos pilares de extremidade, onde os
        estribos continuam --, devolve o trecho da ponta **daquele lado**.
        Devolver sempre o último punha a seção do fim da viga no começo dela:
        numa viga que vai de 20x60 a 20x85, os estribos em ``x = -0,12 m``
        saíam com o comprimento da seção de 85.
        """
        ts = self.trechos
        for t in ts:
            if t.x_ini - 1e-9 <= x <= t.x_fim + 1e-9:
                return t.k
        return ts[0].k if x < ts[0].x_ini else ts[-1].k

    def trechos_do_tramo(self, i: int) -> list["Trecho"]:
        """Os trechos prismáticos que compõem o tramo ``i``."""
        return [t for t in self.trechos if t.tramo == i]

    def secao_em(self, x: float) -> Secao:
        return self.trechos[self.trecho_em(x)].secao

    def tramo_de_apoio(self, k: int) -> int:
        """Tramo cuja seção governa a armadura negativa do apoio ``k``.

        Existe para que ninguém precise deduzi-lo. A armadura de um apoio nasce
        atribuída ao tramo da esquerda por convenção de numeração, mas é
        dimensionada com a seção que governa -- e quando as duas divergem, o
        desenho põe a barra no nível errado: numa junta 20x75 → 20x50 alinhada
        pelo topo, a armadura do apoio saía 21 cm abaixo do fundo da seção.
        """
        return self.trechos[self.trecho_de_apoio(k)].tramo

    def trecho_de_apoio(self, k: int) -> int:
        """Trecho cuja seção governa a armadura negativa do apoio ``k``.

        São candidatos os dois trechos que **encostam** no apoio -- o último do
        tramo da esquerda e o primeiro do da direita --, não os que começam
        cada tramo: com mudança de seção interna, o trecho que chega ao apoio
        pode ser outro.
        """
        candidatos = []
        if k - 1 >= 0:
            candidatos.append(self.trechos_do_tramo(k - 1)[-1].k)
        if k < len(self.tramos):
            candidatos.append(self.trechos_do_tramo(k)[0].k)
        return min(candidatos,
                   key=lambda j: (self.trechos[j].secao.h,
                                  self.trechos[j].secao.bw))

    def secao_de_apoio(self, k: int) -> Secao:
        """Seção que governa a armadura negativa do apoio ``k``.

        Num apoio entre seções diferentes a armadura negativa é uma só e tem de
        servir aos dois tramos, então governa a **menos favorável**: a de menor
        altura, porque é ela que dá o menor braço de alavanca, e no empate a de
        menor largura. Dimensionar pela seção da esquerda -- o que ``secao_em``
        devolve no eixo do apoio, por ser o primeiro tramo que contém aquele x
        -- seria contra a segurança sempre que o tramo da direita fosse o mais
        baixo.
        """
        return self.trechos[self.trecho_de_apoio(k)].secao

    @property
    def balanco_esquerdo(self) -> bool:
        return self.apoios[0].tipo == "livre"

    @property
    def balanco_direito(self) -> bool:
        return self.apoios[-1].tipo == "livre"

    def vao_livre(self, i: int) -> float:
        """Vão livre do tramo ``i``, m (entre faces dos apoios)."""
        t = self.tramos[i]
        c_esq = 0.0 if self.apoios[i].tipo == "livre" else \
            self.apoios[i].largura / 200.0
        c_dir = 0.0 if self.apoios[i + 1].tipo == "livre" else \
            self.apoios[i + 1].largura / 200.0
        return t.L - c_esq - c_dir

    def _conferir_mudancas(self, i: int, t: "Tramo") -> list[str]:
        """Confere as mudanças de seção dentro do tramo ``i``."""
        saida: list[str] = []
        vistos: list[float] = []
        for m in t.mudancas:
            if not (0.0 < m.x < t.L):
                saida.append(av.erro(
                    f"Tramo {i + 1}: mudança de seção em x = {m.x:g} m, fora "
                    f"do tramo (0 < x < {t.L:g} m). Mudança de seção **no** "
                    f"apoio é a seção do tramo seguinte, não uma mudança "
                    f"interna."))
                continue
            if any(abs(m.x - v) < 1e-6 for v in vistos):
                saida.append(av.erro(
                    f"Tramo {i + 1}: duas mudanças de seção em x = {m.x:g} m."))
            vistos.append(m.x)
        return saida

    def _conferir_mesa(self, i: int, t: "Tramo") -> list[str]:
        """Confere a largura colaborante declarada -- item 14.6.2.2.

        A norma dá ``bf = bw + b1 + b3``, com ``b1 <= min(0,1 a; 0,5 b2)`` e
        ``b3 <= min(0,1 a; b4)``, onde ``a`` é a distância entre pontos de
        momento nulo. Sem as lajes vizinhas o programa não conhece ``b2`` nem
        ``b4``, mas conhece ``a``: dos vínculos do tramo saem os valores da
        norma -- ``a = l`` no biapoiado, ``0,75 l`` com continuidade num lado,
        ``0,6 l`` com continuidade nos dois e ``2 l`` no balanço.

        Logo o **teto** ``bw + 2 . 0,1 a`` é conhecido, e é o que se verifica.
        O outro lado da restrição depende do espaçamento entre vigas e fica com
        o projetista; o aviso o diz, para ninguém tomar a conferência por
        completa.
        """
        if t.secao.tipo == "retangular" or t.secao.bf <= t.secao.bw + 1e-9:
            return []
        internos = sum(1 for k in (i, i + 1)
                       if 0 < k < len(self.apoios) - 1
                       and self.apoios[k].tipo != "livre")
        if (self.apoios[i].tipo == "livre"
                or self.apoios[i + 1].tipo == "livre"):
            fator, caso = 2.0, "em balanço"
        elif internos >= 2:
            fator, caso = 0.6, "contínuo nos dois apoios"
        elif internos == 1:
            fator, caso = 0.75, "contínuo num apoio"
        else:
            fator, caso = 1.0, "biapoiado"
        a_cm = fator * t.L * 100.0
        teto = t.secao.bw + 2.0 * 0.1 * a_cm
        if t.secao.bf > teto + 1e-6:
            return [av.erro(
                f"Tramo {i + 1}: largura colaborante bf = {t.secao.bf:g} cm "
                f"acima do teto do item 14.6.2.2. Com o tramo {caso}, "
                f"a = {fator:g}·l = {a_cm:.0f} cm, e bf <= bw + 2·0,1·a = "
                f"{teto:.0f} cm. Restam por conferir 0,5·b2 e b4, que dependem "
                f"do espaçamento entre as vigas e o programa não conhece.")]
        return []

    def _conferir_largura(self, i: int, t: "Tramo") -> list[str]:
        """Largura mínima da alma do tramo ``i`` (13.2.2).

        São 12 cm em viga e 15 cm em viga-parede. A norma admite reduzir
        "respeitando-se um mínimo absoluto de 10 cm em casos excepcionais",
        desde que fiquem garantidos o alojamento das armaduras -- que o
        programa verifica pelo item 18.3.2.2 -- e o lançamento e a vibração do
        concreto, que não se verifica em planilha. Por isso a redução é
        critério explícito, e não silêncio.
        """
        bw = t.secao.bw
        parede = self.eh_viga_parede(i)
        minimo = (LARGURA_MINIMA_VIGA_PAREDE if parede
                  else LARGURA_MINIMA_VIGA)
        tipo = "viga-parede" if parede else "viga"
        if bw >= minimo - 1e-9:
            return []
        if bw < LARGURA_MINIMA_ABSOLUTA - 1e-9:
            return [av.erro(
                f"Tramo {i + 1}: bw = {bw:g} cm abaixo do mínimo absoluto de "
                f"{LARGURA_MINIMA_ABSOLUTA:g} cm do item 13.2.2, que nem em "
                f"caso excepcional pode ser reduzido.")]
        if not self.config.largura_reduzida_excepcional:
            return [av.erro(
                f"Tramo {i + 1}: bw = {bw:g} cm abaixo dos {minimo:g} cm que "
                f"o item 13.2.2 exige em {tipo}. A norma só admite reduzir "
                f"até {LARGURA_MINIMA_ABSOLUTA:g} cm em casos excepcionais, "
                f"garantidos o alojamento das armaduras e o lançamento do "
                f"concreto; se for o caso, marque o critério de largura "
                f"reduzida.")]
        return [av.construtivo(
            f"Tramo {i + 1}: bw = {bw:g} cm, abaixo dos {minimo:g} cm do item "
            f"13.2.2, adotado como caso excepcional. Confira o lançamento e a "
            f"vibração do concreto (ABNT NBR 14931); o alojamento das "
            f"armaduras está verificado pelo item 18.3.2.2.")]

    def relacao_vao_altura(self, i: int) -> float:
        """Relação l/h do tramo ``i``, do item 22.4.1."""
        t = self.tramos[i]
        return t.L / (t.secao.h / 100.0) if t.secao.h > 0 else float("inf")

    def limite_viga_parede(self, i: int) -> float:
        """Relação l/h abaixo da qual o tramo ``i`` é viga-parede (22.4.1).

        O item dá 2 para viga biapoiada e 3 para viga contínua. Um tramo é
        contínuo quando a viga tem mais de um tramo ou quando um dos seus
        apoios é engaste.
        """
        continua = (len(self.tramos) > 1
                    or self.apoios[i].tipo == "engaste"
                    or self.apoios[i + 1].tipo == "engaste")
        return 3.0 if continua else 2.0

    def eh_viga_parede(self, i: int) -> bool:
        """Verdadeiro quando o tramo ``i`` cai na definição do item 22.4.1."""
        if self.apoios[i].tipo == "livre" or self.apoios[i + 1].tipo == "livre":
            return False                    # balanço não entra na definição
        return self.relacao_vao_altura(i) < self.limite_viga_parede(i)

    def vao_efetivo(self, i: int) -> float:
        """Vão efetivo do item 14.6.2.4: lef = l0 + a1 + a2."""
        t = self.tramos[i]
        livre = self.vao_livre(i)
        a = []
        for k in (i, i + 1):
            ap = self.apoios[k]
            if ap.tipo == "livre":
                a.append(0.0)
            else:
                a.append(min(ap.largura / 200.0, 0.3 * t.secao.h / 100.0))
        return livre + a[0] + a[1]

    # -- cargas -------------------------------------------------------------
    def cargas_peso_proprio(self) -> list[CargaDistribuida]:
        """Peso próprio de cada tramo como carga distribuída permanente."""
        if not self.config.peso_proprio:
            return []
        cargas = []
        xs = self.x_apoios
        for i, t in enumerate(self.tramos):
            g = t.secao.peso_proprio(self.concreto.peso_especifico)
            cargas.append(CargaDistribuida(
                q1=g, q2=g, x_ini=xs[i], x_fim=xs[i + 1],
                acao="g", descricao=f"Peso próprio do tramo {i + 1}"))
        return cargas

    def todas_distribuidas(self) -> list[CargaDistribuida]:
        return self.cargas_peso_proprio() + list(self.distribuidas)

    def carga_total(self, acao: str) -> float:
        """Resultante vertical, kN, das cargas de uma ação."""
        total = 0.0
        for c in self.todas_distribuidas():
            if c.acao == acao:
                total += (c.q1 + c.q2) / 2.0 * (c.x_fim - c.x_ini)
        for p in self.concentradas:
            if p.acao == acao:
                total += p.P
        return total

    # -- validação ----------------------------------------------------------
    def validar(self) -> list[str]:
        """Lista de avisos (não bloqueantes) e erros de consistência."""
        avisos = list(self.config.validar())
        for i, t in enumerate(self.tramos):
            avisos.extend(self._conferir_mudancas(i, t))
            avisos.extend(self._conferir_mesa(i, t))
        L = self.comprimento
        if L <= 0:
            raise ValueError("A viga precisa de pelo menos um tramo com L > 0.")

        fixos = [a for a in self.apoios if a.tipo != "livre"]
        if not fixos:
            raise ValueError("A viga não tem nenhum apoio.")
        if len(fixos) == 1 and fixos[0].tipo != "engaste":
            raise ValueError("Com um único apoio, ele precisa ser engaste.")

        for i, a in enumerate(self.apoios):
            if a.tipo == "livre" and 0 < i < len(self.apoios) - 1:
                raise ValueError(
                    f"O apoio {i + 1} é interno e não pode ser 'livre'.")

        for c in self.todas_distribuidas():
            if c.x_ini < -1e-9 or c.x_fim > L + 1e-9:
                rotulo = c.descricao or (f"{c.q1:g} kN/m de {c.x_ini:g} a "
                                         f"{c.x_fim:g} m")
                avisos.append(av.erro(f"Carga distribuída '{rotulo}' está "
                                      f"fora da viga (0 a {L:g} m)."))
        for p in self.concentradas:
            if p.x < -1e-9 or p.x > L + 1e-9:
                rotulo = p.descricao or f"{p.P:g} kN em {p.x:g} m"
                avisos.append(av.erro(f"Carga concentrada '{rotulo}' está "
                                      f"fora da viga (0 a {L:g} m)."))

        for i, t in enumerate(self.tramos):
            if t.secao.h <= 0 or t.secao.bw <= 0:
                raise ValueError(f"Seção inválida no tramo {i + 1}.")
            avisos += self._conferir_largura(i, t)
            if t.L / (t.secao.h / 100.0) > 25 and self.apoios[i].tipo != "livre":
                avisos.append(av.construtivo(f"Tramo {i + 1}: relação L/h = "
                              f"{t.L / (t.secao.h / 100.0):.0f} é elevada; "
                              f"verifique a flecha com atenção."))
        if self.concreto.fck < 20:
            avisos.append(av.erro(
                "O item 7.4.2 exige fck >= 20 MPa em concreto armado."))
        return avisos

    # -- persistência -------------------------------------------------------
    def para_dict(self) -> dict:
        d = asdict(self)
        d["_formato"] = "viga-nbr6118"
        d["_versao"] = 1
        return d

    @staticmethod
    def de_dict(d: dict) -> "Viga":
        return Viga(
            nome=d.get("nome", "V1"),
            projeto=d.get("projeto", ""),
            observacoes=d.get("observacoes", ""),
            tramos=[Tramo(L=t["L"], nome=t.get("nome", ""),
                          alinhamento=t.get("alinhamento", ""),
                          secao=Secao(**t["secao"]),
                          mudancas=[MudancaSecao(
                              x=m["x"], secao=Secao(**m["secao"]),
                              alinhamento=m.get("alinhamento", ""))
                              for m in t.get("mudancas", [])])
                    for t in d["tramos"]],
            apoios=[Apoio(**a) for a in d["apoios"]],
            distribuidas=[CargaDistribuida(**c) for c in d.get("distribuidas", [])],
            concentradas=[CargaConcentrada(**c) for c in d.get("concentradas", [])],
            momentos=[MomentoAplicado(**c) for c in d.get("momentos", [])],
            torcores=[TorcorAplicado(**c) for c in d.get("torcores", [])],
            concreto=Concreto(**d.get("concreto", {})),
            aco=Aco(**d.get("aco", {})),
            aco_estribo=Aco(**d.get("aco_estribo",
                                    {"categoria": "CA-60"})),
            ambiente=Ambiente(**d.get("ambiente", {})),
            config=Config(**d.get("config", {})),
        )

    def salvar(self, caminho: str) -> None:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(self.para_dict(), f, ensure_ascii=False, indent=2)

    @staticmethod
    def carregar(caminho: str) -> "Viga":
        with open(caminho, encoding="utf-8") as f:
            return Viga.de_dict(json.load(f))
