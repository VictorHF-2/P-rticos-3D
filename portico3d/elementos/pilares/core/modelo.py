# -*- coding: utf-8 -*-
"""
modelo.py
Modelo de dados de entrada do pilar: seção transversal, esforços de topo e
base, comprimentos equivalentes, vinculação, materiais e critérios de cálculo.
Nada aqui dimensiona -- é a descrição do problema, consumida pelos módulos de
esbeltez, segunda ordem e dimensionamento.

Convenções:
    x, y ...... eixos da seção; ``x`` horizontal e ``y`` vertical, origem no
                centro de gravidade da seção bruta.
    ``Mx`` .... momento que desloca a normal **na direção x**, flexionando a
                seção segundo a altura ``hx``; ``ex = Mx/N``. É a convenção da
                planilha de referência e da prática brasileira.
    Nd ........ positivo em **compressão**. Tração entra negativa.
    momentos .. kN·cm; forças em kN; dimensões em cm; comprimentos de
                flambagem em cm.

O escopo é o **lance isolado**: um trecho de pilar de seção e armadura
constantes, com os esforços de primeira ordem conhecidos no topo e na base.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, fields

from . import avisos as av
from . import geometria as geo
from .materiais import (AREA_MINIMA, COEFICIENTES_PONDERACAO,
                        DIMENSAO_MINIMA, DIMENSAO_MINIMA_ABSOLUTA,
                        FCK_MAXIMO, FCK_MINIMO_CAA, Aco,
                        Ambiente, Concreto, area_barra,
                        coeficiente_fluencia, coeficientes_ponderacao,
                        espessura_ficticia, gamma_n)
from .formato import num

# ---------------------------------------------------------------------------
# Formato dos arquivos
# ---------------------------------------------------------------------------

#: Marca gravada em todo arquivo do programa, para dizer o que ele é.
FORMATO_PILAR = "pilar-nbr6118"
FORMATO_PROJETO = "projeto-pilares-nbr6118"

#: Versão do formato. Sobe quando um arquivo novo deixa de poder ser lido por
#: uma revisão anterior -- e é o que permite recusar com uma frase clara, em
#: vez de estourar no meio da leitura.
VERSAO_FORMATO = 1

DESCRICAO_FORMATO = {
    FORMATO_PILAR: "um lance de pilar",
    FORMATO_PROJETO: "um projeto (vários lances)",
}


def conferir_formato(d, esperado: str, chaves: tuple[str, ...]) -> None:
    """Recusa um arquivo que não é o que se pediu para abrir.

    Todo arquivo gravado pelo programa leva ``_formato`` e ``_versao``. Sem
    esta conferência, abrir um projeto pela opção de pilar não dava erro: o
    ``de_dict`` não achava nenhuma das chaves que esperava, usava os valores
    padrão de todas elas e devolvia um pilar plausível -- com o nome do
    projeto e a geometria padrão -- que o usuário calcularia sem desconfiar.

    ``chaves`` são as chaves de conteúdo que identificam o formato nos
    arquivos anteriores à marca.
    """
    if not isinstance(d, dict):
        raise ValueError(
            "O arquivo não contém um objeto JSON: não é arquivo do Pilares.")
    marca = d.get("_formato")
    if marca is not None and marca != esperado:
        que_e = DESCRICAO_FORMATO.get(marca, marca)
        quero = DESCRICAO_FORMATO.get(esperado, esperado)
        raise ValueError(
            f"Este arquivo é {que_e}, e não {quero}. Abra-o pela opção "
            f"correspondente.")
    versao = d.get("_versao", 1)
    if isinstance(versao, int) and versao > VERSAO_FORMATO:
        raise ValueError(
            f"O arquivo está no formato versão {versao}, e esta revisão do "
            f"programa lê até a {VERSAO_FORMATO}. Foi gravado por uma versão "
            f"mais nova do Pilares.")
    if marca is None and not any(c in d for c in chaves):
        quero = DESCRICAO_FORMATO.get(esperado, esperado)
        raise ValueError(
            f"O arquivo não descreve {quero}: falta "
            f"{' e '.join(repr(c) for c in chaves)}.")


def campos_conhecidos(classe, d: dict, onde: str) -> dict:
    """Os campos de ``d`` que ``classe`` aceita; recusa se sobrar algum.

    Passar uma chave desconhecida ao construtor de um ``dataclass`` levanta
    ``TypeError`` de dentro do ``__init__``, com uma mensagem que não diz ao
    usuário qual arquivo nem qual bloco está errado. Aqui a recusa nomeia as
    duas coisas -- e recusar, em vez de ignorar em silêncio, é o que evita
    calcular com um critério que o arquivo pedia e o programa descartou.
    """
    campos = {f.name: f for f in fields(classe)}
    sobra = sorted(k for k in d if k not in campos)
    if sobra:
        raise ValueError(
            f"O bloco '{onde}' do arquivo traz campo(s) que este programa "
            f"não conhece: {', '.join(sobra)}.")
    return {nome: _converter(valor, campos[nome], onde)
            for nome, valor in d.items()}


#: Conversores por tipo declarado do campo. Com ``from __future__ import
#: annotations`` a anotação chega como texto, e é por ele que se decide.
_CONVERSOR = {"float": float, "int": int, "str": str}


def _converter(valor, campo, onde: str):
    """Converte o valor lido do arquivo para o tipo declarado do campo.

    Um ``hx`` que chegue como texto ia até o cálculo e estourava lá dentro,
    com uma mensagem sobre dividir ``str`` por ``float`` -- sem dizer qual
    campo do arquivo estava errado. Aqui a recusa é no ponto de leitura, e
    nomeia bloco e campo. Texto que é número ("35") é aceito e convertido:
    JSON gerado por outra ferramenta costuma sair assim.
    """
    tipo = str(getattr(campo, "type", "")).strip()
    if tipo == "bool":
        if isinstance(valor, bool):
            return valor
        raise ValueError(
            f"O campo '{campo.name}' do bloco '{onde}' deveria ser "
            f"verdadeiro ou falso; veio {valor!r}.")
    conversor = _CONVERSOR.get(tipo)
    if conversor is None or isinstance(valor, conversor):
        return valor
    if isinstance(valor, bool) or valor is None:
        raise ValueError(
            f"O campo '{campo.name}' do bloco '{onde}' deveria ser "
            f"{'um número' if tipo != 'str' else 'texto'}; veio {valor!r}.")
    if tipo == "int" and isinstance(valor, float) and not valor.is_integer():
        raise ValueError(
            f"O campo '{campo.name}' do bloco '{onde}' deveria ser inteiro; "
            f"veio {valor!r}, que o programa truncaria em silêncio.")
    try:
        return conversor(valor)
    except (TypeError, ValueError):
        raise ValueError(
            f"O campo '{campo.name}' do bloco '{onde}' deveria ser "
            f"{'um número' if tipo != 'str' else 'texto'}; veio "
            f"{valor!r}.") from None


# ---------------------------------------------------------------------------
# Seção transversal
# ---------------------------------------------------------------------------

TIPOS_SECAO = ("retangular", "circular", "circular vazada",
              "retangular vazada", "L", "T", "U")

#: Tipos em que os casos fechados de flexo-compressão da planilha de
#: referência valem. Nos demais quem dimensiona é o motor seccional.
TIPOS_COM_CASOS_FECHADOS = ("retangular",)


@dataclass
class SecaoPilar:
    """Seção transversal do pilar, em centímetros.

    ``hx`` e ``hy`` são sempre as dimensões da caixa envolvente -- na seção
    circular os dois valem o diâmetro. As seções L, T, U e a retangular
    vazada são descritas por essa caixa mais duas espessuras:

    ``e1``
        espessura das partes **verticais** (medida na direção x): a aba
        vertical do L, a alma do T, as duas almas do U, a parede esquerda e
        a direita da retangular vazada.
    ``e2``
        espessura das partes **horizontais** (medida na direção y): a aba
        horizontal do L, a mesa do T, a mesa do U, a parede de baixo e a de
        cima da retangular vazada.

    O L nasce com o canto no quadrante inferior esquerdo, o T com a mesa em
    cima e a alma centrada, e o U com a mesa embaixo e as almas nas laterais.
    A orientação é fixa: girar a peça é trabalho do lançamento, e permitir
    quatro variantes de cada uma multiplicaria os casos sem acrescentar
    geometria nova.

    A retangular vazada é o "caixão" -- um furo retangular centrado na caixa,
    com paredes ``e1`` (esquerda/direita) e ``e2`` (baixo/cima), e não tem
    orientação a decidir. A armadura, porém, segue o mesmo caminho das seções
    L, T e U -- distribuída pelo **contorno**, com o total de barras em
    ``n_barras`` -- e não a grelha ``nx``/``ny`` da retangular sólida: o
    grampo suplementar reto do item 18.2.4 atravessa o núcleo de concreto de
    lado a lado, e numa seção vazada não há núcleo para atravessar. Tratar a
    parede como um contorno, com o mesmo cálculo de proteção por vértice que
    já vale para o L, T e U, evita gerar um grampo que passaria pelo vazio.
    """

    tipo: str = "retangular"
    hx: float = 20.0
    hy: float = 50.0
    Di: float = 0.0              # diâmetro do furo, só na circular vazada
    e1: float = 0.0              # espessura das partes verticais (L, T, U)
    e2: float = 0.0              # espessura das partes horizontais (L, T, U)

    def __post_init__(self) -> None:
        if self.tipo not in TIPOS_SECAO:
            raise ValueError(f"Tipo de seção desconhecido: {self.tipo!r}")
        if self.tipo in ("circular", "circular vazada"):
            d = self.hx if self.hx > 0 else self.hy
            self.hx = self.hy = d
        if self.tipo != "circular vazada":
            self.Di = 0.0
        if self.tipo in ("retangular", "circular", "circular vazada"):
            self.e1 = self.e2 = 0.0

    # -- geometria ----------------------------------------------------------
    @property
    def diametro(self) -> float:
        """Diâmetro externo da seção circular, cm."""
        return self.hx

    def contornos(self) -> list[geo.Poligono]:
        """Contornos da seção, já centrados no CG da seção bruta.

        O primeiro é o externo; o segundo, quando existe, é o furo, percorrido
        no sentido inverso para que a área saia negativa.
        """
        brutos = self._contornos_brutos()
        p = geo.propriedades(brutos, hx=self.hx, hy=self.hy)
        return [geo.transladar(c, -p.cx, -p.cy) for c in brutos]

    def _contornos_brutos(self) -> list[geo.Poligono]:
        """Contornos com a origem no canto inferior esquerdo da caixa."""
        hx, hy = self.hx, self.hy
        if self.tipo == "retangular":
            return [geo.retangulo(hx, hy, hx / 2.0, hy / 2.0)]
        if self.tipo == "circular":
            return [geo.circulo(hx, hx / 2.0, hy / 2.0)]
        if self.tipo == "circular vazada":
            return [geo.circulo(hx, hx / 2.0, hy / 2.0),
                    geo.circulo(self.Di, hx / 2.0, hy / 2.0, horario=True)]
        e1, e2 = self.e1, self.e2
        if self.tipo == "retangular vazada":
            return [geo.retangulo(hx, hy, hx / 2.0, hy / 2.0),
                    geo.retangulo(hx - 2.0 * e1, hy - 2.0 * e2,
                                 hx / 2.0, hy / 2.0, horario=True)]
        if self.tipo == "L":
            return [[(0.0, 0.0), (hx, 0.0), (hx, e2), (e1, e2), (e1, hy),
                     (0.0, hy)]]
        if self.tipo == "T":
            a = (hx - e1) / 2.0
            return [[(a, 0.0), (a + e1, 0.0), (a + e1, hy - e2), (hx, hy - e2),
                     (hx, hy), (0.0, hy), (0.0, hy - e2), (a, hy - e2)]]
        # U: mesa embaixo, almas nas laterais
        return [[(0.0, 0.0), (hx, 0.0), (hx, hy), (hx - e1, hy),
                 (hx - e1, e2), (e1, e2), (e1, hy), (0.0, hy)]]

    def propriedades(self) -> geo.Propriedades:
        """Propriedades da seção bruta referidas ao CG."""
        return geo.propriedades(self.contornos(), hx=self.hx, hy=self.hy)

    @property
    def area(self) -> float:
        """Área bruta de concreto, cm²."""
        return self.propriedades().area

    def altura(self, direcao: str) -> float:
        """Altura da seção na direção pedida, cm."""
        return self.hx if direcao == "x" else self.hy

    @property
    def menor_dimensao(self) -> float:
        """Menor dimensão da caixa envolvente, cm -- a do item 13.2.3.

        Nas seções L, T, U e retangular vazada o que a norma limita é a
        **espessura da parte**, não a caixa: um U de 60x60 com almas de
        12 cm tem paredes de 12 cm, e é isso que precisa passar nos 19 cm.
        """
        if self.tipo in ("L", "T", "U", "retangular vazada"):
            return min(self.e1, self.e2)
        if self.tipo == "circular vazada":
            return (self.hx - self.Di) / 2.0
        return min(self.hx, self.hy)

    @property
    def perimetro_exposto(self) -> float:
        """Perímetro da seção em contato com a atmosfera, cm (item 8.2.11).

        É o ``u`` da espessura fictícia ``2Ac/u`` que entra na fluência. Num
        pilar de edifício as quatro faces estão expostas, e o que conta é o
        contorno **externo**: o vazio de uma seção circular vazada não entra,
        porque ele é fechado nas duas pontas pelas lajes e não troca umidade
        com o ambiente.
        """
        return geo.perimetro_poligono(self.contornos()[0])

    @property
    def maior_dimensao(self) -> float:
        return max(self.hx, self.hy)

    @property
    def eh_pilar_parede(self) -> bool:
        """Maior dimensão acima de cinco vezes a menor (itens 18.4 e 18.5)."""
        menor = min(self.hx, self.hy)
        return menor > 0 and self.maior_dimensao > 5.0 * menor

    @property
    def tem_casos_fechados(self) -> bool:
        """A seção admite o roteiro FC1-FC4 / FT1-FT4 da planilha."""
        return self.tipo in TIPOS_COM_CASOS_FECHADOS

    def descricao(self) -> str:
        if self.tipo == "retangular":
            return f"{num(self.hx)}x{num(self.hy)} cm"
        if self.tipo == "circular":
            return f"circular ø{num(self.hx)} cm"
        if self.tipo == "circular vazada":
            return f"circular ø{num(self.hx)} cm vazada ø{num(self.Di)} cm"
        if self.tipo == "retangular vazada":
            return (f"{num(self.hx)}x{num(self.hy)} cm vazada, "
                    f"parede e1={num(self.e1)} e2={num(self.e2)} cm")
        return (f"{self.tipo} {num(self.hx)}x{num(self.hy)} cm, "
                f"e1={num(self.e1)} e2={num(self.e2)} cm")

    def validar(self) -> list[str]:
        saida: list[str] = []
        if self.hx <= 0 or self.hy <= 0:
            raise ValueError("As dimensões da seção precisam ser positivas.")
        if self.tipo == "circular vazada":
            if self.Di <= 0 or self.Di >= self.hx:
                raise ValueError(
                    "O furo da seção vazada precisa de 0 < Di < D.")
        if self.tipo in ("L", "T", "U"):
            if self.e1 <= 0 or self.e2 <= 0:
                raise ValueError(
                    f"A seção {self.tipo} precisa das espessuras e1 e e2.")
            if self.e1 >= self.hx or self.e2 >= self.hy:
                raise ValueError(
                    f"Na seção {self.tipo}, e1 < hx e e2 < hy: com a espessura "
                    f"igual à caixa a peça vira um retângulo.")
            if self.tipo == "U" and 2.0 * self.e1 >= self.hx:
                raise ValueError(
                    "Na seção U as duas almas somadas ocupam a largura toda; "
                    "reduza e1 ou aumente hx.")
        if self.tipo == "retangular vazada":
            if self.e1 <= 0 or self.e2 <= 0:
                raise ValueError(
                    "A seção retangular vazada precisa das espessuras de "
                    "parede e1 e e2.")
            if 2.0 * self.e1 >= self.hx or 2.0 * self.e2 >= self.hy:
                raise ValueError(
                    "Na seção retangular vazada as duas paredes de cada "
                    "direção, somadas, não podem ocupar a caixa toda "
                    "(2 e1 < hx e 2 e2 < hy); reduza a espessura ou aumente "
                    "hx/hy.")
        menor = self.menor_dimensao
        if menor < DIMENSAO_MINIMA_ABSOLUTA - 1e-9:
            saida.append(av.erro(
                f"Menor dimensão da seção = {num(menor)} cm, abaixo dos "
                f"{num(DIMENSAO_MINIMA_ABSOLUTA)} cm que o item 13.2.3 fixa como "
                f"piso absoluto. Nenhum coeficiente adicional autoriza essa "
                f"seção."))
        elif menor < DIMENSAO_MINIMA - 1e-9:
            saida.append(av.construtivo(
                f"Menor dimensão da seção = {num(menor)} cm, entre 14 e 19 cm. O "
                f"item 13.2.3 admite, desde que os esforços sejam majorados "
                f"pelo coeficiente adicional γn = {num(gamma_n(menor), 2)} "
                f"(Tabela 13.1), o que o programa faz."))
        if self.area < AREA_MINIMA - 1e-6:
            saida.append(av.erro(
                f"Área da seção = {num(self.area, 0)} cm², abaixo dos "
                f"{num(AREA_MINIMA, 0)} cm² exigidos pelo item 13.2.3."))
        if self.eh_pilar_parede:
            saida.append(av.construtivo(
                f"Maior dimensão ({num(self.maior_dimensao)} cm) acima de cinco "
                f"vezes a menor ({num(min(self.hx, self.hy))} cm): a peça é "
                f"pilar-parede. O item 18.4 não se aplica ao detalhamento, e "
                f"valem as disposições do item 18.5."))
        return saida


# ---------------------------------------------------------------------------
# Esforços e vinculação do lance
# ---------------------------------------------------------------------------

#: Condições de vinculação que governam o alfa_b do item 15.8.2.
VINCULOS = {
    1: "Biapoiado sem cargas transversais",
    2: "Biapoiado com cargas transversais",
    3: "Em balanço",
}

#: Desaprumo de pilar isolado em balanço, rad (item 11.3.3.4.1).
THETA1_BALANCO = 1.0 / 200.0

#: Desaprumo mínimo para imperfeições locais em estrutura reticulada, rad
#: (item 11.3.3.4.1, ``theta1min``). A excentricidade da falta de
#: retilineidade do lance é ``theta1 . Hi / 2`` (Figura 11.2-b).
THETA1_LOCAL = 1.0 / 300.0
#: Teto do mesmo desaprumo, rad (item 11.3.3.4.1, ``theta1max``).
THETA1_MAXIMO_LOCAL = 1.0 / 200.0


@dataclass
class Esforcos:
    """Esforços de primeira ordem no topo e na base do lance.

    ``Nd`` é positivo em compressão. Os momentos são de **cálculo** quando
    ``Config.gamma_f`` vale 1,0 -- que é o caso usual, porque eles vêm da
    combinação última do modelo global. O sinal importa, e o que ele quer
    dizer na base depende de ``Config.convencao_momento_base``: na convenção
    "faces" (face tracionada, a do item 15.8.2), sinais opostos entre topo e
    base descrevem curvatura **reversa**; na "vetorial", é o mesmo sinal. É
    disso que sai o ``alfa_b``.
    """

    Nd: float = 0.0              # kN
    Mx_topo: float = 0.0         # kN·cm
    Mx_base: float = 0.0
    My_topo: float = 0.0
    My_base: float = 0.0
    #: Momento de primeira ordem no **meio do balanço**, kN·cm. Só é lido
    #: quando o vínculo da direção é "em balanço": é o ``MC`` de que o item
    #: 15.8.2 precisa para o alfa_b do balanço. Deixado em zero, o programa
    #: adota alfa_b = 1,0 e declara a omissão.
    Mx_meio: float = 0.0
    My_meio: float = 0.0
    #: Força cortante de cálculo em cada direção, kN. ``Vd_x`` é a que flete
    #: o pilar **na direção x** -- mesma convenção dos momentos. Zero (o
    #: padrão) quer dizer "sem cortante a verificar": o estribo então sai só
    #: dos critérios construtivos do item 18.4.3, que é o caso do pilar de
    #: edifício corrente. Informada, entra na verificação do item 17.4.
    Vd_x: float = 0.0
    Vd_y: float = 0.0

    def topo(self, direcao: str) -> float:
        return self.Mx_topo if direcao == "x" else self.My_topo

    def base(self, direcao: str) -> float:
        return self.Mx_base if direcao == "x" else self.My_base

    def meio(self, direcao: str) -> float:
        return self.Mx_meio if direcao == "x" else self.My_meio

    def Vd(self, direcao: str) -> float:
        return self.Vd_x if direcao == "x" else self.Vd_y


@dataclass
class Lance:
    """Geometria longitudinal do lance e vinculação em cada direção.

    O comprimento equivalente de flambagem pode ser **informado** ou
    **calculado**. Informado, ``le_x`` e ``le_y`` valem como estão -- é o
    caminho de quem já o tem apurado do modelo global. Calculado, o programa
    aplica o item 15.8.2 a partir de ``l`` e das alturas das vigas que travam
    o pilar em cada direção, e ``le_x``/``le_y`` ficam em zero.
    """

    #: cm; 0 = calcular pelo item 15.8.2 a partir de ``l`` e das vigas.
    le_x: float = 0.0
    le_y: float = 0.0
    #: cm, distância entre os **eixos** das vigas que vinculam o pilar --
    #: o ``l`` do item 15.8.2. Na prática, o pé-direito estrutural.
    l: float = 0.0  # noqa: E741 -- é o símbolo do próprio item 15.8.2
    comprimento: float = 0.0     # cm; 0 = adotar l, ou o maior dos le
    vinculo_x: int = 1
    vinculo_y: int = 1
    #: cm, altura das vigas que travam o pilar em cada direção. A viga que
    #: trava a direção x é a que está no plano xz -- a que "enxerga" a altura
    #: hx --, e ela não é a mesma que trava y. É por isso que o le sai
    #: diferente nas duas direções mesmo com o mesmo pé-direito.
    h_viga_topo_x: float = 0.0
    h_viga_base_x: float = 0.0
    h_viga_topo_y: float = 0.0
    h_viga_base_y: float = 0.0

    def __post_init__(self) -> None:
        for eixo in ("x", "y"):
            v = self.vinculo(eixo)
            if v not in VINCULOS:
                raise ValueError(f"Vínculo em {eixo} desconhecido: {v!r}")

    def le_informado(self, direcao: str) -> float:
        return self.le_x if direcao == "x" else self.le_y

    def viga_topo(self, direcao: str) -> float:
        return self.h_viga_topo_x if direcao == "x" else self.h_viga_topo_y

    def viga_base(self, direcao: str) -> float:
        return self.h_viga_base_x if direcao == "x" else self.h_viga_base_y

    def l0(self, direcao: str) -> float:
        """Distância entre as faces internas das vigas, cm (item 15.8.2).

        ``l`` é medido eixo a eixo; as faces internas distam dele meia altura
        de cada viga.
        """
        return self.l - (self.viga_topo(direcao)
                         + self.viga_base(direcao)) / 2.0

    def vinculo(self, direcao: str) -> int:
        return self.vinculo_x if direcao == "x" else self.vinculo_y

    @property
    def altura(self) -> float:
        """Comprimento do lance, cm.

        Sem ``l`` nem comprimento, sai do comprimento equivalente -- mas no
        balanço ``le = 2 l``, e tomar o le inteiro dobrava o desaprumo, a e_a
        da fluência, o L do método geral e a grade da varredura."""
        if self.comprimento > 0:
            return self.comprimento
        if self.l > 0:
            return self.l
        return max(le / 2.0 if vinculo == 3 else le
                   for le, vinculo in ((self.le_x, self.vinculo_x),
                                       (self.le_y, self.vinculo_y)))


# ---------------------------------------------------------------------------
# Armadura
# ---------------------------------------------------------------------------

MODOS_ARMADURA = ("automatico", "imposto", "barras")


@dataclass
class Armadura:
    """Arranjo das barras: escolhido pelo programa ou imposto pelo projetista.

    No modo automático o programa varre as bitolas e os arranjos possíveis e
    fica com o mais econômico que atenda a tudo. No modo imposto ele calcula o
    que foi pedido e diz se passa -- que é o que se quer quando a armadura já
    está definida por continuidade com o lance de baixo.
    """

    modo: str = "automatico"
    phi: float = 0.0             # bitola longitudinal, mm
    nx: int = 0                  # barras por face horizontal (cantos inclusos)
    ny: int = 0                  # barras por face vertical (cantos inclusos)
    n_barras: int = 0            # total, nas seções circulares e L/T/U
    #: Seções vazadas: barras de uma segunda camada junto ao furo (0 = só a
    #: camada externa), distribuídas no contorno interno, com bitola própria
    #: (0 = a mesma da externa). Valem nos modos Dimensionar e Verificar.
    n_barras_internas: int = 0
    phi_interna: float = 0.0     # mm
    phi_estribo: float = 0.0     # mm
    s_estribo: float = 0.0       # cm
    d_linha_x: float = 0.0       # cm; 0 = calcular do cobrimento
    d_linha_y: float = 0.0
    #: Modo ``barras``: lista explícita ``(x, y, ø)`` -- cm a partir do CG da
    #: seção bruta, mm --, para arranjos que a grelha nx/ny não descreve
    #: (assimétricos, bitolas misturadas). É o que o PCalc aceita.
    barras: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.modo not in MODOS_ARMADURA:
            raise ValueError(f"Modo de armadura desconhecido: {self.modo!r}")


# ---------------------------------------------------------------------------
# Critérios de cálculo
# ---------------------------------------------------------------------------

METODOS_2A_ORDEM = ("menor", "curvatura", "rigidez", "diagrama", "geral")
RIGIDEZES_METODO_GERAL = ("curva", "secante")
FLUENCIA_METODOS = ("ecc", "diagrama")
#: Métodos cuja 2ª ordem depende da armadura: calculados de novo para cada
#: arranjo candidato e para o arranjo final (a curvatura aproximada serve só
#: de estimativa de partida, antes de haver barras).
METODOS_COM_SECAO = ("diagrama", "geral")
METODOS_MOMENTO_MINIMO = ("envoltoria", "planilha")
METODOS_VERIFICACAO_ALTURA = ("3_pontos", "continua")
CONVENCOES_MOMENTO_BASE = ("faces", "vetorial")

#: Mínimo de pontos da varredura contínua: base, topo e um intermediário.
#: Com dois, a grade cai nos extremos e pula o pico de segunda ordem.
PONTOS_VARREDURA_MINIMO = 3


@dataclass
class Config:
    """Critérios de projeto que o programa aplica e declara na memória."""

    #: Qual método aproximado governa a segunda ordem local. ``menor`` adota
    #: o menor dos dois valores, que é o critério da planilha de referência:
    #: a norma admite qualquer um dos métodos, e nada obriga a escolher o
    #: mais desfavorável.
    metodo_2a_ordem: str = "menor"

    #: Expoente ``alfa`` da expressão de interação do item 17.2.5. Deixado em
    #: **zero**, o programa adota o que a norma admite para a seção: 1,2 na
    #: retangular e 1,0 nas demais. Só faz sentido impor um valor para
    #: **reduzi-lo** -- 1,0 numa seção retangular, a favor da segurança.
    expoente_interacao: float = 0.0

    #: Multiplicador dos esforços de entrada. Deixe 1,0 quando eles já forem
    #: de cálculo, que é o caso quando vêm da combinação última.
    gamma_f: float = 1.0

    #: Aplica o coeficiente adicional gamma_n do item 13.2.3 quando a menor
    #: dimensão fica entre 14 e 19 cm.
    aplicar_gamma_n: bool = True

    #: Aplica gamma_n1 = 1 + (lambda-140)/140 aos efeitos locais de 2ª ordem
    #: quando a esbeltez passa de 140 (item 15.8.1).
    aplicar_gamma_n1: bool = True

    #: Considera os efeitos locais de 2ª ordem mesmo com lambda <= lambda_1.
    #: Critério de projeto, a favor da segurança: o item 15.8.2 só os
    #: **dispensa** abaixo do limite, não os proíbe. Vale também para a
    #: envoltória mínima. Normal de tração continua sem 2ª ordem de pilar.
    sempre_2a_ordem: bool = False

    #: A expressão de interação do item 17.2.5 também reprova. A norma a
    #: oferece como aproximação ("pode ser adotada"); a envoltória de
    #: equilíbrio, calculada sempre, é a verificação exata. Desligado, só a
    #: envoltória decide e a expressão fica informativa -- é o critério do
    #: PCalc, e o que interessa em seção circular, onde alfa = 1 soma os dois
    #: momentos linearmente numa seção que resiste igual em toda direção.
    exigir_interacao_17_2_5: bool = True

    #: Modo compatível com o PCalc 1.4 (``pilares/compat_pcalc.py``): ""
    #: desligado, "parcial" (metodologia do PCalc, calibração da 2026) ou
    #: "total" (metodologia e calibração de 2014). Ferramenta de transição,
    #: para o uso em paralelo; não é verificação pela NBR 6118:2026.
    compat_pcalc: str = ""                                   # COMPAT-PCALC

    #: Coeficientes de ponderação das resistências (Tabela 12.1). Ligado, o
    #: programa impõe a ``gamma_c`` e ``gamma_s`` os valores da tabela para o
    #: tipo de combinação escolhido, com as duas ressalvas de 1,1 que a
    #: própria tabela traz.
    ponderacao_automatica: bool = True
    combinacao: str = "normais"
    execucao_desfavoravel: bool = False    # gamma_c x 1,1
    ca25_sem_controle: bool = False        # gamma_s x 1,1

    #: Considera a fluência pelo processo simplificado do item 15.8.4. A norma
    #: só a torna obrigatória acima de lambda = 90.
    considerar_fluencia: bool = False
    #: Coeficiente de fluência. Deixado em **zero**, sai da Tabela 8.1 por
    #: interpolação, a partir da umidade, da espessura fictícia ``2Ac/u`` --
    #: que o programa calcula da própria seção -- e da idade de carregamento.
    phi_fluencia: float = 0.0
    umidade_ambiente: float = 75.0   # %, entrada da Tabela 8.1
    idade_carregamento: float = 30.0  # dias, o t0 da Tabela 8.1
    Nsg_sobre_Nd: float = 0.7        # parcela quase permanente da normal
    #: Parcela quase permanente do momento de 1ª ordem, M_Sg/Md. Deixada em
    #: zero, vale a mesma da normal -- M_Sg/N_Sg = e1 de cálculo, o lado seguro.
    Msg_sobre_Md: float = 0.0
    #: Como a fluência entra quando ligada. ``ecc`` (padrão, o texto do item
    #: 15.8.4): a excentricidade ``e_cc`` soma-se a ``e1`` "como se fosse um
    #: efeito imediato" e a 2ª ordem é calculada em cima dela, em qualquer
    #: método. ``diagrama``: nos métodos com relação momento-curvatura
    #: (M, N, 1/r e método geral), as deformações ``eps_c2`` e ``eps_cu`` da
    #: curva de deformabilidade são multiplicadas por ``1 + phi_ef``, com
    #: ``phi_ef = phi . Nsg/Nd`` -- a forma do PCalc, que a norma não descreve
    #: e o programa declara como alternativa; nos métodos aproximados vale a
    #: ``e_cc``.
    fluencia_metodo: str = "ecc"

    #: Método geral (15.8.3.2): seções em que a barra é discretizada; a
    #: relação momento-curvatura de cada seção -- ``curva`` (a real, padrão)
    #: ou ``secante`` (a reta AB da Figura 15.1, rigidez constante, que a
    #: norma admite "a favor da segurança") --; e se as duas direções são
    #: resolvidas juntas (flexão oblíqua, padrão) ou uma de cada vez.
    metodo_geral_secoes: int = 11
    metodo_geral_rigidez: str = "curva"
    metodo_geral_acoplado: bool = True

    #: Combina os efeitos de segunda ordem das duas direções na seção
    #: intermediária, como pede o item 3.3.3.4 da apostila ("admite-se atuar
    #: concomitantemente os momentos Md,tot nas duas direções"). A planilha de
    #: referência não faz essa combinação; desligá-la reproduz a planilha.
    combinar_2a_ordem_biaxial: bool = True

    #: Como o momento mínimo (item 11.3.3.4.3) é verificado.
    #:
    #: ``envoltoria`` (padrão): o item 3.1 da apostila de referência pede uma
    #: verificação **isolada**, independente do momento real -- duas análises
    #: à flexão composta normal, uma por direção, com o momento mínimo de 1ª
    #: ordem (amplificado pela 2ª ordem quando a esbeltez pedir) confrontado
    #: com o momento resistente naquela direção apenas. Não entra na situação
    #: de cálculo do momento real: as duas verificações ficam separadas.
    #:
    #: ``planilha``: reproduz o critério mais simples da planilha de
    #: referência, que soma o efeito ao impor um piso ``max(|M|, M1d,min)``
    #: diretamente no momento de cada situação de cálculo. É mais simples de
    #: auditar à mão, mas infla o momento real sempre que ele fica abaixo do
    #: mínimo em alguma direção -- mesmo quando a outra direção, combinada,
    #: já bastaria para atender ao item 11.3.3.4.3.
    momento_minimo_metodo: str = "envoltoria"

    #: No método ``envoltoria``, confere a **elipse inteira** da envoltória
    #: mínima (Figuras 11.3 e 15.2 -- ``(Mx/Mxx)² + (My/Myy)² = 1``) contra a
    #: envoltória resistente, e não só os dois vértices -- que são as duas
    #: análises nas direções principais que a norma (15.3.2) admite. Num
    #: pilar de canto, onde os dois mínimos agem juntos, os pontos
    #: intermediários podem reprovar com os dois vértices aprovados. O PCalc
    #: confere a elipse inteira (98 pontos; ``CalculaFsMomentoMin``), e é o
    #: que este critério reproduz; desligado, ficam só os dois vértices.
    elipse_minima: bool = True
    #: Método "planilha": o piso do momento mínimo entra nas **duas**
    #: direções de toda situação (True, o critério que o programa sempre
    #: usou -- conservador) ou só na direção da situação, "numa direção de
    #: cada vez" (False, a leitura literal do 11.3.3.4.3).
    piso_minimo_bidirecional: bool = True

    #: Como a verificação final percorre a altura do lance.
    #:
    #: ``3_pontos`` (padrão): o critério do item 15.8.3.3.5 -- "pode ser
    #: realizada em apenas três seções: nas extremidades A e B e num ponto
    #: intermediário". É o que a planilha de referência e a apostila usam, e
    #: o que permite conferir a peça à mão.
    #:
    #: ``continua``: varre a altura inteira do lance em pontos igualmente
    #: espaçados, combinando em cada ``z`` o momento real de primeira ordem
    #: (interpolado linearmente entre topo e base, sem o alfa_b -- que é o
    #: artifício do critério dos três pontos para condensar o diagrama real
    #: numa constante equivalente, e deixa de ser necessário varrendo a
    #: altura inteira) com a segunda ordem senoidal do pilar-padrão, só na
    #: direção em que a esbeltez a exige. É o método que o PCalc usa: mais
    #: preciso dentro do mesmo modelo aproximado do pilar-padrão, mas não
    #: auditável à mão e, nos casos em que diverge dos três pontos, menos
    #: conservador -- nunca o contrário, nos casos comparados até aqui.
    verificacao_altura: str = "3_pontos"

    #: Número de pontos da varredura contínua (``verificacao_altura ==
    #: "continua"``), igualmente espaçados entre a base (z=0) e o topo.
    #:
    #: Onze, e não vinte e um: a varredura converge em segunda ordem
    #: no espaçamento, porque o que se procura é o máximo de uma função
    #: lisa de ``z`` (derivada nula no pico). Medido num caso montado
    #: de propósito para deslocar o pico do meio físico, o F.S. com 11
    #: pontos fica 0,05 % do valor obtido com 201 -- e custa um terço
    #: do tempo. Quem quiser a grade fina põe até 201 na aba de entrada.
    pontos_varredura_altura: int = 11

    #: Aplica a última regra do item 3.2 da apostila (item 15.8.2 da norma):
    #: "se o pilar apresentar momentos menores do que o momento mínimo [...]
    #: alfa_b deve ser tomado igual a 1". Ligado (padrão) é o que a
    #: referência manda e é o lado conservador -- alfa_b maior amplifica mais
    #: a segunda ordem. Desligado, ``alfa_b`` sai sempre da fórmula do
    #: diagrama (0,60+0,40 MB/MA, piso 0,40), que é o que o PCalc faz: é a
    #: última divergência conhecida contra ele, e desligar aqui serve para
    #: reproduzi-lo caso a caso.
    alfa_b_unitario_sob_minimo: bool = True

    #: Soma ao momento de base de um pilar **isolado em balanço** o desaprumo
    #: do item 11.3.3.4.1, que para esse caso fixa ``theta1 = 1/200``:
    #: ``Nd . theta1 . l``, nas direções em que o vínculo é de balanço. Pilar
    #: isolado não tem modelo global onde o desaprumo entraria -- é o
    #: único caso em que o programa não pode supor que ele já veio nos
    #: esforços. Desligar serve a quem já o incluiu na entrada (contá-lo duas
    #: vezes) ou a quem compara com ferramenta que não o aplica.
    desaprumo_balanco: bool = True

    #: O que o **sinal** do momento de base informado quer dizer. É a
    #: pergunta que decide a curvatura do lance, e com ela o ``alfa_b`` e a
    #: própria dispensa da 2ª ordem -- errar aqui não dá erro, dá outro
    #: pilar.
    #:
    #: ``faces`` (padrão): o sinal já expressa a **face tracionada**, como o
    #: item 15.8.2 pede para o ``MB``. Sinais opostos entre topo e base
    #: descrevem curvatura reversa.
    #:
    #: ``vetorial``: os momentos são vetores nodais, como saem de um modelo
    #: de pórtico e como a figura de convenção do PCalc os define. Aí é o
    #: **mesmo** sinal nas duas pontas que descreve curvatura reversa, e o
    #: programa inverte o momento de base ao convertê-lo para a convenção
    #: interna. Use esta opção para colar direto números do PCalc ou de
    #: análise de pórtico sem reinterpretar sinal a sinal.
    convencao_momento_base: str = "faces"

    #: Armadura simétrica nas duas direções. É o que a norma pressupõe nos
    #: métodos aproximados do pilar-padrão (itens 15.8.3.3.2 e 15.8.3.3.3),
    #: e por isso o padrão é ligado.
    armadura_simetrica: bool = True

    #: Confere o dimensionamento com o motor seccional por integração.
    #: (Mantido por compatibilidade com arquivos antigos; quem decide hoje é
    #: ``metodo_duas_camadas``.)
    conferir_com_motor_seccional: bool = True

    #: Roda também o roteiro dos casos fechados (FC1-FC4 / FT1-FT4, modelo de
    #: duas camadas, seção retangular), para memória e conferência com o
    #: motor seccional. **Desligado por padrão**: aprovação e reprovação são
    #: só do motor seccional, que integra a seção real com todas as barras.
    #: Ligado, o roteiro é informativo -- não filtra a busca nem reprova.
    metodo_duas_camadas: bool = False

    #: ELS-W: abertura de fissura limite, mm. 0 = Tabela 13.4 pela CAA
    #: (0,4 / 0,3 / 0,3 / 0,2 mm); maior que zero, imposta (item 13.4.3).
    wk_limite: float = 0.0
    #: Relação Es/Ec do estádio II no ELS-W (17.3.3.2 admite 15).
    alfa_e_servico: float = 15.0
    #: Obra de arte especial (NBR 7187): confere as dimensões mínimas de
    #: pilar de ponte dos itens 9.1.5 e 9.1.6.
    obra_ponte: bool = False
    #: Fadiga (6118, 23.5; 8681, Tabela 7): "" não verifica; "rodoviaria"
    #: (pilar ligado por aparelhos, psi1,fad = 0), "rodoviaria_monolitica"
    #: (pórtico/estaiada, psi1,fad informado), "ferroviaria" (1,0),
    #: "passarela" (0).
    fadiga_obra: str = ""
    #: psi1,fad imposto; 0 = Tabela 7 da NBR 8681.
    psi1_fadiga: float = 0.0

    #: Tolerância relativa aceita entre o método dos casos fechados e o motor
    #: seccional antes de o programa levantar a divergência.
    tolerancia_conferencia: float = 0.03

    #: Aceita a seção com dimensão entre 14 e 19 cm. Sem isso, o programa
    #: emite erro em vez de apenas majorar por gamma_n.
    dimensao_reduzida_aceita: bool = True

    #: Bitolas longitudinais que o modo automático pode usar.
    bitolas_permitidas: tuple[float, ...] = (10.0, 12.5, 16.0, 20.0, 25.0,
                                             32.0)

    #: Espaçamento de estribo arredondado para múltiplo deste passo, cm.
    passo_estribo: float = 1.0

    def validar(self) -> list[str]:
        saida: list[str] = []
        if self.fluencia_metodo not in FLUENCIA_METODOS:
            raise ValueError(f"Método de fluência desconhecido: "
                             f"{self.fluencia_metodo!r}")
        if self.metodo_geral_rigidez not in RIGIDEZES_METODO_GERAL:
            raise ValueError(f"Rigidez do método geral desconhecida: "
                             f"{self.metodo_geral_rigidez!r}")
        if self.metodo_geral_secoes < 3:
            raise ValueError("O método geral precisa de ao menos 3 seções.")
        if self.metodo_2a_ordem not in METODOS_2A_ORDEM:
            raise ValueError(
                f"Método de segunda ordem desconhecido: "
                f"{self.metodo_2a_ordem!r}")
        if self.combinacao not in COEFICIENTES_PONDERACAO:
            raise ValueError(f"Combinação desconhecida: {self.combinacao!r}")
        if self.momento_minimo_metodo not in METODOS_MOMENTO_MINIMO:
            raise ValueError(
                f"Método de momento mínimo desconhecido: "
                f"{self.momento_minimo_metodo!r}")
        if self.verificacao_altura not in METODOS_VERIFICACAO_ALTURA:
            raise ValueError(
                f"Método de verificação ao longo da altura desconhecido: "
                f"{self.verificacao_altura!r}")
        if self.convencao_momento_base not in CONVENCOES_MOMENTO_BASE:
            raise ValueError(
                f"Convenção de sinal do momento de base desconhecida: "
                f"{self.convencao_momento_base!r}")
        if self.pontos_varredura_altura < PONTOS_VARREDURA_MINIMO:
            saida.append(av.erro(
                f"pontos_varredura_altura = {self.pontos_varredura_altura}; "
                f"a varredura contínua precisa de pelo menos "
                f"{PONTOS_VARREDURA_MINIMO} pontos (base, topo e um "
                f"intermediário). O cálculo foi feito com "
                f"{PONTOS_VARREDURA_MINIMO} pontos, mas o lance fica reprovado "
                f"até o valor ser corrigido nos critérios."))
        if self.expoente_interacao and not 1.0 <= self.expoente_interacao <= 1.2:
            saida.append(av.erro(
                f"O expoente da expressão de interação (17.2.5) vale "
                f"{num(self.expoente_interacao)}; a norma admite 1,0 em qualquer "
                f"seção e 1,2 apenas em seção retangular."))
        if self.gamma_f < 1.0:
            saida.append(av.erro(
                f"γf = {num(self.gamma_f)} reduz os esforços de entrada."))
        return saida


# ---------------------------------------------------------------------------
# Pilar
# ---------------------------------------------------------------------------

@dataclass
class Combinacao:
    """Uma combinação de esforços adicional do lance (a principal é
    ``Pilar.esforcos``). Todas são verificadas com a mesma armadura; vale a
    pior -- como o seletor de combinações do PCalc."""

    nome: str = "Comb 2"
    esforcos: Esforcos = field(default_factory=Esforcos)


@dataclass
class Pilar:
    """Um lance de pilar, com tudo que o dimensionamento precisa saber."""

    nome: str = "P1"
    projeto: str = ""
    observacoes: str = ""
    secao: SecaoPilar = field(default_factory=SecaoPilar)
    esforcos: Esforcos = field(default_factory=Esforcos)
    lance: Lance = field(default_factory=Lance)
    armadura: Armadura = field(default_factory=Armadura)
    concreto: Concreto = field(default_factory=Concreto)
    aco: Aco = field(default_factory=Aco)
    aco_estribo: Aco = field(default_factory=lambda: Aco(categoria="CA-60"))
    ambiente: Ambiente = field(default_factory=Ambiente)
    config: Config = field(default_factory=Config)
    #: Nome da combinação principal (``esforcos``) nas saídas.
    nome_combinacao: str = "Comb 1"
    #: Combinações adicionais de esforços, verificadas com a mesma armadura.
    combinacoes: list[Combinacao] = field(default_factory=list)
    #: Esforços de **serviço** da combinação frequente (kN, kN·cm, sem
    #: ponderação), para o ELS-W. Zerados = ELS não verificado.
    esforcos_servico: Esforcos = field(default_factory=Esforcos)
    #: Fadiga (pilar de ponte): esforços **característicos** permanentes e da
    #: carga móvel com efeitos dinâmicos, nas posições de máximo e de mínimo
    #: (kN, kN·cm). A combinação é ``g + psi1,fad . q`` (6118, 23.5.2).
    esforcos_fadiga_g: Esforcos = field(default_factory=Esforcos)
    esforcos_fadiga_qmax: Esforcos = field(default_factory=Esforcos)
    esforcos_fadiga_qmin: Esforcos = field(default_factory=Esforcos)

    def __post_init__(self) -> None:
        """Impõe os coeficientes de ponderação da Tabela 12.1.

        É o único ponto do programa em que um dado de entrada é reescrito, e
        ele existe para que ``gamma_c`` e ``gamma_s`` não possam discordar do
        tipo de combinação declarado -- inclusive num arquivo editado à mão.
        Desligar ``ponderacao_automatica`` devolve o controle ao projetista.
        """
        if not self.config.ponderacao_automatica:
            return
        gc, gs = coeficientes_ponderacao(
            self.config.combinacao, self.config.execucao_desfavoravel,
            self.config.ca25_sem_controle)
        self.concreto.gamma_c = gc
        self.aco.gamma_s = gs
        self.aco_estribo.gamma_s = gs

    # -- critérios resolvidos ----------------------------------------------
    @property
    def alfa_interacao(self) -> float:
        """Expoente da expressão de interação do item 17.2.5, resolvido.

        Zero na configuração significa "o que a norma admite para esta
        seção": 1,2 na retangular, 1,0 nas demais. É a leitura literal do
        item, que diz "em geral pode ser adotado alfa = 1, a favor da
        segurança" e "no caso de seções retangulares pode-se adotar
        alfa = 1,2".
        """
        if self.config.expoente_interacao > 0:
            return self.config.expoente_interacao
        return 1.2 if self.secao.tipo == "retangular" else 1.0

    @property
    def alfa_automatico(self) -> bool:
        return self.config.expoente_interacao <= 0

    def le(self, direcao: str) -> float:
        """Comprimento equivalente de flambagem, cm (item 15.8.2).

        Informado, vale o informado. Calculado, o item dá, para o elemento
        vinculado nas duas extremidades, ``le = min(l0 + h; l)`` -- com ``h``
        medido **no plano da estrutura em estudo**, isto é, ``hx`` na direção
        x e ``hy`` na direção y. É essa dependência de ``h`` que faz o
        comprimento equivalente ser diferente nas duas direções mesmo num
        pilar de seção quadrada com o mesmo pé-direito.

        No **balanço** a expressão não se aplica -- ela pressupõe as duas
        extremidades vinculadas --, e vale o clássico ``le = 2 l``.
        """
        informado = self.lance.le_informado(direcao)
        if informado > 0:
            return informado
        if self.lance.l <= 0:
            return 0.0
        if self.lance.vinculo(direcao) == 3:
            return 2.0 * self.lance.l
        h = self.secao.altura(direcao)
        return min(self.lance.l0(direcao) + h, self.lance.l)

    def le_memoria(self, direcao: str) -> str:
        """Como o comprimento equivalente daquela direção foi obtido."""
        if self.lance.le_informado(direcao) > 0:
            return "informado pelo projetista"
        if self.lance.l <= 0:
            return "indefinido"
        if self.lance.vinculo(direcao) == 3:
            return f"balanço: le = 2 l = 2 x {num(self.lance.l)}"
        l0 = self.lance.l0(direcao)
        h = self.secao.altura(direcao)
        qual = "l0 + h" if l0 + h <= self.lance.l else "l"
        return (f"min(l0 + h; l) = min({num(l0)} + {num(h)}; {num(self.lance.l)}) "
                f"-> governa {qual}")

    @property
    def phi_fluencia(self) -> float:
        """Coeficiente de fluência resolvido (Tabela 8.1)."""
        if self.config.phi_fluencia > 0:
            return self.config.phi_fluencia
        return coeficiente_fluencia(
            self.concreto.fck, self.config.umidade_ambiente,
            self.espessura_ficticia, self.config.idade_carregamento)

    @property
    def espessura_ficticia(self) -> float:
        """Espessura fictícia ``2 Ac/u`` da seção, cm (item 8.2.11)."""
        return espessura_ficticia(self.secao.area,
                                  self.secao.perimetro_exposto)

    def cobrimento(self, phi_barra: float = 0.0,
                   phi_estribo: float = 0.0) -> float:
        """Cobrimento a adotar, cm, fechando o item 7.4.7 inteiro."""
        return self.ambiente.cobrimento_para(phi_barra, phi_estribo)

    # -- grandezas derivadas ------------------------------------------------
    @property
    def gamma_n(self) -> float:
        """Coeficiente adicional do item 13.2.3 aplicado a este pilar."""
        if not self.config.aplicar_gamma_n:
            return 1.0
        return gamma_n(self.secao.menor_dimensao)

    @property
    def fator_esforcos(self) -> float:
        """Multiplicador que leva o esforço de entrada ao de cálculo."""
        return self.config.gamma_f * self.gamma_n

    @property
    def Nd(self) -> float:
        """Força normal de cálculo, kN, já majorada."""
        return self.esforcos.Nd * self.fator_esforcos

    def momento_base(self, direcao: str) -> float:
        """Momento de base **na convenção interna**, kN·cm, sem ponderar.

        A convenção interna é a do ``MB`` do item 15.8.2: o sinal diz a face
        tracionada, e sinais opostos entre as duas pontas descrevem curvatura
        reversa. Quando a entrada está na convenção **vetorial** -- momentos
        nodais como saem de um modelo de pórtico, que é também a da figura de
        convenção do PCalc --, é o mesmo sinal nas duas pontas que descreve
        curvatura reversa, e converter é inverter o da base.

        Ponto único de conversão: tudo que lê o momento de base passa por
        aqui, de modo que a escolha do critério não precisa ser repetida em
        cada consumidor.
        """
        base = self.esforcos.base(direcao)
        if self.config.convencao_momento_base == "vetorial":
            base = -base
        extra = self.desaprumo_balanco(direcao)
        if extra:
            # Soma em módulo, no sentido do momento que já existe -- o caso
            # desfavorável --; sem momento de base, o sentido é indiferente.
            base += math.copysign(extra, base if base else 1.0)
        return base

    def desaprumo_balanco(self, direcao: str) -> float:
        """Momento de desaprumo na base de um pilar isolado em balanço,
        kN·cm, sem ponderar (item 11.3.3.4.1: ``theta1 = 1/200``).

        ``Nd . theta1 . l``, com ``l`` o comprimento do lance. Zero fora do
        balanço, ou com ``config.desaprumo_balanco`` desligado.
        """
        if (not self.config.desaprumo_balanco
                or self.lance.vinculo(direcao) != 3):
            return 0.0
        return abs(self.esforcos.Nd) * THETA1_BALANCO * self.lance.altura

    def M1d_A(self, direcao: str) -> float:
        """Maior momento de primeira ordem em módulo, kN·cm (item 15.8.2)."""
        return self.fator_esforcos * max(abs(self.esforcos.topo(direcao)),
                                         abs(self.momento_base(direcao)))

    def sinal_A(self, direcao: str) -> float:
        """Sentido físico do momento na extremidade A (a de maior módulo):
        +1 ou -1 no eixo da direção. ``M1d_A`` é tomado em módulo, como o item
        15.8.2 pede para o alfa_b; com armadura assimétrica o sentido do
        momento do meio importa, e é este."""
        topo = self.esforcos.topo(direcao)
        base = self.momento_base(direcao)
        M = topo if abs(topo) >= abs(base) else base
        return -1.0 if M < 0.0 else 1.0

    def M1d_B(self, direcao: str) -> float:
        """Momento no outro extremo, com sinal relativo a ``M1d_A``.

        O item 15.8.2 manda tomar ``MB`` positivo quando traciona a mesma face
        que ``MA`` e negativo em caso contrário -- e é o produto dos sinais
        dos dois momentos, já na convenção interna, que diz qual é o caso.
        """
        topo = self.esforcos.topo(direcao)
        base = self.momento_base(direcao)
        menor = min(abs(topo), abs(base))
        sinal = -1.0 if topo * base < 0.0 else 1.0
        return self.fator_esforcos * sinal * menor

    def area_aco(self) -> float:
        """Área total de armadura longitudinal do arranjo declarado, cm²."""
        a = self.armadura
        if a.modo == "barras":
            return sum(area_barra(b[2]) for b in a.barras)
        if a.phi <= 0:
            return 0.0
        return self.numero_de_barras() * area_barra(a.phi)

    def numero_de_barras(self) -> int:
        """Número de barras longitudinais do arranjo declarado."""
        a = self.armadura
        if a.modo == "barras":
            return len(a.barras)
        if self.secao.tipo == "retangular":
            if a.nx >= 2 and a.ny >= 2:
                return 2 * a.nx + 2 * a.ny - 4
            return a.n_barras
        return a.n_barras

    # -- validação ----------------------------------------------------------
    #: Item 14.4.1: elemento linear (barra) é o de comprimento que supera
    #: em pelo menos três vezes a maior dimensão da seção.
    FATOR_ELEMENTO_LINEAR = 3.0

    @property
    def eh_elemento_linear(self) -> bool:
        """O lance é elemento linear -- barra -- no sentido do item 14.4.1?

        Comprimento do lance contra a maior dimensão da caixa envolvente
        da seção (o diâmetro na circular). É a premissa de tudo o que o
        programa faz: seções planas, pilar-padrão, 2ª ordem de barra."""
        return (self.lance.altura
                >= self.FATOR_ELEMENTO_LINEAR * self.secao.maior_dimensao
                - 1e-9)

    def validar(self) -> list[str]:
        """Avisos e erros de consistência dos dados de entrada."""
        saida = list(self.config.validar())
        saida += self.secao.validar()
        if not self.eh_elemento_linear:
            # Aviso, como o PCalc (e como o pilar-parede, 18.4): a peça
            # curta não deixa de ser verificável à flexão composta, mas o
            # modelo de barra é premissa, e quem decide é o projetista.
            saida.append(av.construtivo(
                f"Comprimento do lance ({num(self.lance.altura)} cm) menor que "
                f"três vezes a maior dimensão da seção "
                f"({num(self.secao.maior_dimensao)} cm, 3 × = "
                f"{num(self.FATOR_ELEMENTO_LINEAR * self.secao.maior_dimensao)}"
                f" cm): a peça não é elemento linear (barra) no sentido do "
                f"item 14.4.1, e o modelo de pilar -- seções planas, "
                f"pilar-padrão, 2ª ordem de barra -- é premissa deste "
                f"cálculo. Peça curta (pescoço de bloco, consolo, apoio "
                f"curto) pede outro modelo, como bielas e tirantes (item "
                f"22)."))

        if self.esforcos.Nd == 0.0:
            saida.append(av.erro(
                "A força normal é nula. Um pilar sem normal é uma viga, e não "
                "é o que este programa calcula."))
        if self.esforcos.Nd < 0.0:
            # Aviso, não erro (decisão de 05/11/2026): o pilar tracionado é
            # dimensionado e verificado à flexo-tração pelo motor seccional,
            # e aprova se a seção resiste. O que muda é declarado: sem
            # compressão não há instabilidade nem 2ª ordem local.
            saida.append(av.construtivo(
                f"Normal de tração ({num(-self.esforcos.Nd)} kN): peça "
                f"flexo-tracionada. A seção é dimensionada e verificada à "
                f"flexo-tração pelo motor seccional; a 2ª ordem local não se "
                f"aplica (sem compressão não há instabilidade, Seção 15), e o "
                f"momento mínimo do item 11.3.3.4.3 é conferido do lado "
                f"seguro. Na cortante, Vc = 0 se a linha neutra sai da seção "
                f"(17.4.2.2-b), e a emenda é a de barra tracionada."))
        for eixo in ("x", "y"):
            if self.le(eixo) <= 0:
                raise ValueError(
                    f"O comprimento equivalente de flambagem em {eixo} não "
                    f"foi definido: informe le diretamente ou preencha a "
                    f"distância entre os eixos das vigas (l) para que o "
                    f"programa o calcule pelo item 15.8.2.")
            if (self.lance.le_informado(eixo) <= 0
                    and self.lance.l0(eixo) <= 0):
                saida.append(av.erro(
                    f"Direção {eixo}: as vigas de topo e base somam mais que "
                    f"a distância entre os eixos delas (l = "
                    f"{num(self.lance.l)} cm), e a distância livre l0 sai "
                    f"negativa. Confira as alturas informadas."))
        if (self.secao.menor_dimensao < DIMENSAO_MINIMA - 1e-9
                and not self.config.dimensao_reduzida_aceita):
            saida.append(av.erro(
                f"Menor dimensão de {num(self.secao.menor_dimensao)} cm abaixo "
                f"dos {num(DIMENSAO_MINIMA)} cm do item 13.2.3, e o critério que "
                f"aceita a seção reduzida está desligado."))
        if self.concreto.fck < 20:
            saida.append(av.erro(
                "O item 7.4.2 exige fck >= 20 MPa em concreto armado."))
        if self.concreto.fck > FCK_MAXIMO + 1e-9:
            saida.append(av.erro(
                f"fck = C{num(self.concreto.fck)} acima de C{num(FCK_MAXIMO)}: o "
                f"item 8.2.1 só cobre concretos até essa classe."))
        fck_min_caa = FCK_MINIMO_CAA[self.ambiente.caa]
        if self.concreto.fck < fck_min_caa - 1e-9:
            saida.append(av.erro(
                f"fck = C{num(self.concreto.fck)} abaixo de C{num(fck_min_caa)}, a "
                f"classe mínima que a Tabela 7.1 exige para concreto armado "
                f"em CAA {self.ambiente.caa}. É um piso de durabilidade, "
                f"distinto do piso estrutural absoluto do item 7.4.2 -- o "
                f"concreto pode ser estruturalmente suficiente e ainda "
                f"assim não ter a qualidade mínima para o ambiente."))
        if (self.config.expoente_interacao > 1.0
                and self.secao.tipo != "retangular"):
            saida.append(av.erro(
                f"O expoente {num(self.config.expoente_interacao)} da expressão "
                f"de interação (17.2.5) só é admitido em seção retangular, e "
                f"a seção é {self.secao.tipo}. Deixe o expoente em automático "
                f"ou adote α = 1,0."))
        if self.armadura.modo == "barras" and len(self.armadura.barras) < 4:
            saida.append(av.erro(
                "No modo de barras é preciso informar a lista das barras "
                "(x; y; ø) -- ao menos quatro (item 18.4.2.2)."))
        if (self.armadura.modo == "imposto" and self.armadura.phi <= 0):
            saida.append(av.erro(
                "No modo de armadura imposta é preciso informar a bitola "
                "longitudinal."))
        if self.secao.tipo in ("circular", "circular vazada"):
            if self.armadura.modo == "imposto" and self.armadura.n_barras < 6:
                saida.append(av.erro(
                    f"Seção circular com {self.armadura.n_barras} barras; o "
                    f"item 18.4.2.2 exige no mínimo seis distribuídas ao "
                    f"longo do perímetro."))
        if self.config.considerar_fluencia:
            u = self.config.umidade_ambiente
            if not 30.0 <= u <= 100.0:
                saida.append(av.erro(
                    f"Umidade média ambiente de {num(u)} %; a Tabela 8.1 é dada "
                    f"de 40 % a 90 %, e fora dessa faixa o valor é truncado "
                    f"no extremo."))
            if self.config.phi_fluencia <= 0:
                saida.append(av.construtivo(
                    f"Coeficiente de fluência φ = {num(self.phi_fluencia, 2)} "
                    f"obtido da Tabela 8.1 por interpolação, com umidade de "
                    f"{num(u)} %, espessura fictícia 2Ac/u = "
                    f"{num(self.espessura_ficticia, 1)} cm e carregamento aos "
                    f"{num(self.config.idade_carregamento)} dias."))
        if self.config.considerar_fluencia and not 0.0 <= self.config.Nsg_sobre_Nd <= 1.0:
            saida.append(av.erro(
                f"A parcela quase permanente da normal vale "
                f"{num(self.config.Nsg_sobre_Nd)}; ela é uma fração de Nd e tem "
                f"de ficar entre 0 e 1."))
        return saida

    # -- persistência -------------------------------------------------------
    def para_dict(self) -> dict:
        d = asdict(self)
        d["config"]["bitolas_permitidas"] = list(
            self.config.bitolas_permitidas)
        d["_formato"] = FORMATO_PILAR
        d["_versao"] = VERSAO_FORMATO
        return d

    @staticmethod
    def de_dict(d: dict) -> "Pilar":
        conferir_formato(d, FORMATO_PILAR, ("secao", "esforcos"))
        conhecidas = {f.name for f in fields(Pilar)} | {"_formato", "_versao"}
        sobra = sorted(k for k in d if k not in conhecidas)
        if sobra:
            raise ValueError(
                f"O arquivo traz campo(s) que este programa não conhece: "
                f"{', '.join(sobra)}.")
        cfg = campos_conhecidos(Config, d.get("config", {}), "config")
        if "bitolas_permitidas" in cfg:
            cfg["bitolas_permitidas"] = tuple(cfg["bitolas_permitidas"])
        bloco = {nome: campos_conhecidos(classe, d.get(nome, padrao), nome)
                 for nome, classe, padrao in (
                     ("secao", SecaoPilar, {}),
                     ("esforcos", Esforcos, {}),
                     ("lance", Lance, {}),
                     ("armadura", Armadura, {}),
                     ("concreto", Concreto, {}),
                     ("aco", Aco, {}),
                     ("aco_estribo", Aco, {"categoria": "CA-60"}),
                     ("ambiente", Ambiente, {}))}
        return Pilar(
            nome=d.get("nome", "P1"),
            projeto=d.get("projeto", ""),
            observacoes=d.get("observacoes", ""),
            secao=SecaoPilar(**bloco["secao"]),
            esforcos=Esforcos(**bloco["esforcos"]),
            lance=Lance(**bloco["lance"]),
            armadura=Armadura(**bloco["armadura"]),
            concreto=Concreto(**bloco["concreto"]),
            aco=Aco(**bloco["aco"]),
            aco_estribo=Aco(**bloco["aco_estribo"]),
            ambiente=Ambiente(**bloco["ambiente"]),
            config=Config(**cfg),
            nome_combinacao=d.get("nome_combinacao", "Comb 1"),
            combinacoes=[
                Combinacao(nome=c.get("nome", f"Comb {i + 2}"),
                           esforcos=Esforcos(**campos_conhecidos(
                               Esforcos, c.get("esforcos", {}),
                               f"combinacoes[{i}].esforcos")))
                for i, c in enumerate(d.get("combinacoes", []))],
            esforcos_servico=Esforcos(**campos_conhecidos(
                Esforcos, d.get("esforcos_servico", {}), "esforcos_servico")),
            **{nome: Esforcos(**campos_conhecidos(Esforcos, d.get(nome, {}),
                                                  nome))
               for nome in ("esforcos_fadiga_g", "esforcos_fadiga_qmax",
                            "esforcos_fadiga_qmin")},
        )

    def com_esforcos(self, esforcos: Esforcos, nome: str) -> "Pilar":
        """O mesmo lance com outra combinação de esforços e sem as
        adicionais -- o que cada combinação calcula."""
        from dataclasses import replace
        return replace(self, esforcos=esforcos, nome_combinacao=nome,
                       combinacoes=[])

    def todas_combinacoes(self) -> list[tuple[str, Esforcos]]:
        return ([(self.nome_combinacao, self.esforcos)]
                + [(c.nome, c.esforcos) for c in self.combinacoes])

    def salvar(self, caminho: str) -> None:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(self.para_dict(), f, ensure_ascii=False, indent=2)

    @staticmethod
    def carregar(caminho: str) -> "Pilar":
        with open(caminho, encoding="utf-8") as f:
            return Pilar.de_dict(json.load(f))
