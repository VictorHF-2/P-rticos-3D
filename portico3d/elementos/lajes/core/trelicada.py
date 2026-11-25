# -*- coding: utf-8 -*-
"""
trelicada.py
Dimensionamento da laje treliçada unidirecional (vigota com armação
treliçada e enchimento intercalado), pela nervura, com continuidade e
armadura negativa.

A laje nervurada unidirecional se calcula **na direção das nervuras,
desprezadas a rigidez transversal e a torção** (14.7.7); cada nervura é uma
viga T contínua sobre os apoios. O roteiro é o do material de referência
(Estude Engenharia, partes 1 a 3, e Manual Técnico ArcelorMittal), estendido
à continuidade:

    1. geometria da nervura: ``bw``, ``bf`` (14.6.2.2) e peso próprio;
    2. esforços na viga contínua (equação dos três momentos, ``EI``
       constante), com **alternância da carga variável** para a envoltória e
       balanços nas pontas -- ELU com ``gamma_g``/``gamma_q`` do critério;
    3. flexão positiva (seção T) e negativa (compressão na nervura, de
       largura ``bw``, ou no **trecho maciço** quando ``bw`` não basta);
    4. cortante como laje (19.4.1) -- permitido com espaçamento até 65 cm
       (13.2.4.2-a);
    5. ancoragem no apoio (9.4.2), a mesma regra da laje maciça;
    6. flecha pela rigidez equivalente de Branson ponderada ao longo do vão
       (17.3.2.1.1, Figura 17.3) com a fluência do critério, e fissuração
       (17.3.3.2);
    7. detalhamento (posições) e quantitativo.

Unidades: cm e kN, exceto onde indicado (momentos em kN·m, cargas em kN/m por
nervura). Funções puras, sem Qt.

**O que é hipótese e não norma**, declarado para não parecer o contrário:

* a armadura adicional e a da treliça têm o mesmo cobrimento até o CG da
  armadura (é o que o material de referência faz);
* a altura útil usa o CG da armadura ponderado pela força de escoamento
  (idêntico ao da referência quando o aço é todo CA-60);
* o trecho maciço não altera o peso próprio nem a rigidez da análise;
* a flecha da ponta do balanço soma a rotação do apoio (vinda do vão
  vizinho) à curvatura do próprio balanço;
* as diagonais da treliça só entram como armadura transversal se a laje não
  fechar o cortante sem elas, e com o teto de tensão do 19.4.2.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np

from . import ancoragem, cisalhamento
from .flexao import armadura_distribuicao, momento_minimo
from .materiais import (Aco, Ambiente, Concreto, area_barra, massa_linear)
from .modelo import Config
from .trelicada_modelo import (ADICIONAIS, BITOLAS_MOLDADA,
                               GANCHO_ADICIONAL, NEGATIVAS, PASSO_TRELICA,
                               SEM_TRELICA, TRELICAS, ENCHIMENTOS,
                               LajeTrelicada)

#: Pontos por elemento na amostragem dos diagramas.
PONTOS = 81

#: Máximo de elementos (vãos + balanços) para enumerar todas as alternâncias
#: de carga variável; acima disso usa-se um conjunto reduzido.
MAX_ENUMERACAO = 9

#: Alcance máximo da armadura negativa de cada lado do apoio como fração do
#: vão vizinho -- teto só para o desenho não atravessar o vão inteiro.
ALFA_FLEXAO_TRACAO = 1.2     # alfa do momento de fissuração da seção T


def _kcm2(x_MPa: float) -> float:
    return x_MPa / 10.0


# ---------------------------------------------------------------------------
# Geometria da seção
# ---------------------------------------------------------------------------

@dataclass
class GeometriaT:
    """Seção T da nervura, cm."""

    bw: float
    bf: float
    capa: float
    h: float
    intereixo: float

    @property
    def area(self) -> float:
        return self.bf * self.capa + self.bw * (self.h - self.capa)

    @property
    def y_topo(self) -> float:
        """Distância do CG da seção bruta à fibra de topo, cm."""
        a1 = self.bf * self.capa
        a2 = self.bw * (self.h - self.capa)
        return (a1 * self.capa / 2.0
                + a2 * (self.capa + (self.h - self.capa) / 2.0)) / self.area

    @property
    def inercia(self) -> float:
        """Momento de inércia da seção bruta, cm⁴."""
        yt = self.y_topo
        hw = self.h - self.capa
        i1 = self.bf * self.capa ** 3 / 12.0 \
            + self.bf * self.capa * (yt - self.capa / 2.0) ** 2
        i2 = self.bw * hw ** 3 / 12.0 \
            + self.bw * hw * (self.capa + hw / 2.0 - yt) ** 2
        return i1 + i2


def largura_colaborante(bw: float, le: float, a: float,
                        intereixo: float) -> float:
    """``bf = bw + 2 b1`` com ``b1 <= 0,5 b2`` e ``b1 <= 0,1 a`` (14.6.2.2).

    ``b2`` é a distância entre as faces das nervuras (o ``Le`` do bloco) e
    ``a`` a distância entre pontos de momento nulo. Nunca passa do intereixo.
    """
    b1 = min(0.5 * le, 0.1 * a)
    return min(bw + 2.0 * b1, intereixo)


def _distancia_a(L: float, cont_esq: bool, cont_dir: bool) -> float:
    """Distância ``a`` entre pontos de momento nulo (14.6.2.2)."""
    if cont_esq and cont_dir:
        return 0.60 * L
    if cont_esq or cont_dir:
        return 0.75 * L
    return 1.00 * L


# ---------------------------------------------------------------------------
# Seção: flexão no ELU
# ---------------------------------------------------------------------------

def _bloco(td: float, bf: float, bw: float, hf: float, d: float,
           sigma: float) -> tuple[float, float]:
    """Altura ``y`` do bloco retangular e momento resistente (kN·cm) para a
    força de tração ``td`` (kN), seção T com mesa ``hf`` -- ou retangular
    quando ``bf == bw``. Equilíbrio de forças, aço em escoamento."""
    y = td / (sigma * bf)
    if y <= hf + 1e-12 or bf <= bw + 1e-12:
        return y, td * (d - y / 2.0)
    y = (td / sigma - (bf - bw) * hf) / bw
    mrd = sigma * ((bf - bw) * hf * (d - hf / 2.0) + bw * y * (d - y / 2.0))
    return y, mrd


def _forca_necessaria(md: float, bf: float, bw: float, hf: float, d: float,
                      sigma: float) -> tuple[float, float] | None:
    """Força de tração ``Td`` (kN) e altura do bloco ``y`` (cm) que resistem
    ao momento ``md`` (kN·cm). ``None`` quando nem aço infinito resiste."""
    if md <= 0.0:
        return 0.0, 0.0
    # retangular de largura bf
    disc = d * d - 2.0 * md / (sigma * bf)
    if disc >= 0.0:
        y = d - math.sqrt(disc)
        if y <= hf + 1e-12 or bf <= bw + 1e-12:
            return sigma * bf * y, y
    # T: mesa inteira comprimida mais a alma
    m_mesa = sigma * (bf - bw) * hf * (d - hf / 2.0)
    resto = md - m_mesa
    disc = d * d - 2.0 * resto / (sigma * bw)
    if disc < 0.0:
        return None
    y = d - math.sqrt(disc)
    return sigma * ((bf - bw) * hf + bw * y), y


@dataclass
class SecaoFlexao:
    """Resultado do dimensionamento à flexão de uma seção."""

    rotulo: str
    md: float = 0.0                 # kN·m
    b_comp: float = 0.0             # cm, largura comprimida
    d: float = 0.0                  # cm
    x: float = 0.0                  # cm
    x_d: float = 0.0
    x_d_limite: float = 0.45
    td_nec: float = 0.0             # kN
    As_nec: float = 0.0             # cm², referido ao aço de referência
    As_min: float = 0.0             # cm²
    md_min: float = 0.0             # kN·m
    As_adot: float = 0.0            # cm²
    td_adot: float = 0.0            # kN
    mrd: float = 0.0                # kN·m
    armadura: str = ""
    governa: str = ""
    erro: str = ""
    dominio: str = ""

    @property
    def atende(self) -> bool:
        return not self.erro and self.td_adot + 1e-9 >= self.td_nec \
            and self.x_d <= self.x_d_limite + 1e-9


# ---------------------------------------------------------------------------
# Estádio II e rigidez
# ---------------------------------------------------------------------------

def _xII(bf: float, bw: float, hf: float, d: float, ae_as: float) -> float:
    """Linha neutra no estádio II (cm), seção T comprimida no topo."""
    def q(x: float) -> float:
        if x <= hf:
            return bf * x * x / 2.0
        return bf * hf * (x - hf / 2.0) + bw * (x - hf) ** 2 / 2.0
    lo, hi = 0.0, d
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if q(mid) - ae_as * (d - mid) > 0.0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def _inercia_II(bf: float, bw: float, hf: float, d: float,
                ae_as: float) -> tuple[float, float]:
    """Momento de inércia do estádio II (cm⁴) e a linha neutra (cm)."""
    x = _xII(bf, bw, hf, d, ae_as)
    if x <= hf:
        i = bf * x ** 3 / 3.0
    else:
        i = bf * (x ** 3 - (x - hf) ** 3) / 3.0 + bw * (x - hf) ** 3 / 3.0
    return i + ae_as * (d - x) ** 2, x


def _estadio_I(geo: GeometriaT, as_: float, d_topo: float, ae: float,
               homogeneizada: bool) -> tuple[float, float]:
    """``(I, y_topo)`` do estádio I: seção bruta de concreto (17.3.2.1.1) ou,
    a pedido, homogeneizada com a armadura a ``d_topo`` do topo. ``y_topo``
    é a distância do CG da seção à fibra de topo, cm."""
    if not homogeneizada or as_ <= 0.0:
        return geo.inercia, geo.y_topo
    extra = (ae - 1.0) * as_
    a_h = geo.area + extra
    y_h = (geo.area * geo.y_topo + extra * d_topo) / a_h
    i_h = (geo.inercia + geo.area * (geo.y_topo - y_h) ** 2
           + extra * (d_topo - y_h) ** 2)
    return i_h, y_h


def _ieq(ma: float, mr: float, ic: float, iii: float) -> float:
    """Inércia equivalente de Branson (17.3.2.1.1), limitada a ``Ic``."""
    ma = abs(ma)
    if ma <= mr or ma <= 0.0:
        return ic
    r = (mr / ma) ** 3
    return min(ic, r * ic + (1.0 - r) * iii)


# ---------------------------------------------------------------------------
# Esforços: viga contínua com alternância da carga variável
# ---------------------------------------------------------------------------

@dataclass
class Elemento:
    """Um vão ou um balanço da faixa."""

    L: float                        # m
    w_perm: float                   # kN/m
    w_var: float                    # kN/m
    p_ponta: float = 0.0            # kN, só balanço
    balanco: str = ""               # "", "esq" ou "dir"
    carga_linear: float = 0.0


def _resolver(Ls: list[float], ws: list[float], m0: float,
              mn: float) -> np.ndarray:
    """Momentos negativos (hogging, positivos) nos apoios de uma viga
    contínua de vãos ``Ls`` com carga ``ws`` e momentos de ponta ``m0`` e
    ``mn`` já conhecidos (balanços) -- equação dos três momentos."""
    n = len(Ls)
    ms = np.zeros(n + 1)
    ms[0], ms[n] = m0, mn
    if n < 2:
        return ms
    a = np.zeros((n - 1, n - 1))
    b = np.zeros(n - 1)
    for j in range(1, n):
        i = j - 1
        a[i, i] = 2.0 * (Ls[j - 1] + Ls[j])
        if i > 0:
            a[i, i - 1] = Ls[j - 1]
        if i < n - 2:
            a[i, i + 1] = Ls[j]
        b[i] = (ws[j - 1] * Ls[j - 1] ** 3 + ws[j] * Ls[j] ** 3) / 4.0
        if j == 1:
            b[i] -= Ls[0] * m0
        if j == n - 1:
            b[i] -= Ls[n - 1] * mn
    ms[1:n] = np.linalg.solve(a, b)
    return ms


@dataclass
class Envoltoria:
    """Esforços de um conjunto de casos de carga sobre a faixa."""

    x: list = field(default_factory=list)       # por elemento, m
    m_max: list = field(default_factory=list)   # kN·m, sagging positivo
    m_min: list = field(default_factory=list)
    v_max: list = field(default_factory=list)   # kN, positivo p/ baixo
    v_min: list = field(default_factory=list)
    ms_max: list = field(default_factory=list)  # hogging nos apoios
    reacao_max: list = field(default_factory=list)


def _casos(elementos: list[Elemento], gamma_g: float, gamma_q: float,
           todos: bool) -> list[list[tuple[float, float]]]:
    """Casos de carga: para cada elemento, ``(w, p_ponta)`` já majorados."""
    m = len(elementos)
    if todos and m <= MAX_ENUMERACAO:
        padroes = list(itertools.product((0, 1), repeat=m))
    else:
        padroes = {tuple([1] * m), tuple([0] * m)}
        for k in range(m):
            padroes.add(tuple(1 if i == k else 0 for i in range(m)))
            padroes.add(tuple(0 if i == k else 1 for i in range(m)))
        padroes.add(tuple(i % 2 for i in range(m)))
        padroes.add(tuple((i + 1) % 2 for i in range(m)))
        padroes = sorted(padroes)
    balancos = [i for i, e in enumerate(elementos) if e.balanco]
    casos = []
    for pad in padroes:
        for favor in itertools.product((False, True), repeat=len(balancos)):
            ws = []
            for i, e in enumerate(elementos):
                fg = gamma_g
                if i in balancos and favor[balancos.index(i)]:
                    fg = 1.0            # permanente favorável ao vão vizinho
                w = fg * e.w_perm + gamma_q * e.w_var * pad[i]
                p = fg * e.p_ponta
                ws.append((w, p))
            casos.append(ws)
    return casos


def _esforcos_caso(elementos: list[Elemento], caso, delta: float):
    """Esforços de um caso: devolve, por elemento, ``(x, M, V)`` e os
    momentos de apoio (hogging, kN·m) já com a redistribuição ``delta``."""
    esq = elementos[0] if elementos[0].balanco == "esq" else None
    dir_ = elementos[-1] if elementos[-1].balanco == "dir" else None
    ini = 1 if esq is not None else 0
    fim = len(elementos) - 1 if dir_ is not None else len(elementos)
    principais = list(range(ini, fim))
    Ls = [elementos[i].L for i in principais]
    ws = [caso[i][0] for i in principais]

    def m_balanco(i: int) -> float:
        w, p = caso[i]
        L = elementos[i].L
        return w * L * L / 2.0 + p * L

    m0 = m_balanco(0) if esq is not None else 0.0
    mn = m_balanco(len(elementos) - 1) if dir_ is not None else 0.0
    ms = _resolver(Ls, ws, m0, mn)
    for j in range(1, len(Ls)):
        ms[j] *= delta
    saida = {}
    for k, i in enumerate(principais):
        L = Ls[k]
        w = ws[k]
        x = np.linspace(0.0, L, PONTOS)
        ml, mr = ms[k], ms[k + 1]
        m = w * x * (L - x) / 2.0 - (ml * (1.0 - x / L) + mr * x / L)
        vl = w * L / 2.0 + (ml - mr) / L
        v = vl - w * x
        saida[i] = (x, m, v)
    if esq is not None:
        w, p = caso[0]
        L = elementos[0].L
        s = np.linspace(0.0, L, PONTOS)            # da ponta para o apoio
        m = -(w * s * s / 2.0 + p * s)
        v = -(w * s + p)                           # cortante da esquerda
        saida[0] = (s, m, v)
    if dir_ is not None:
        i = len(elementos) - 1
        w, p = caso[i]
        L = elementos[i].L
        s = np.linspace(0.0, L, PONTOS)            # do apoio para a ponta
        m = -(w * (L - s) ** 2 / 2.0 + p * (L - s))
        v = w * (L - s) + p
        saida[i] = (s, m, v)
    return saida, ms, principais


def envoltoria(elementos: list[Elemento], gamma_g: float, gamma_q: float,
               delta: float, todos: bool = True) -> Envoltoria:
    """Envoltória ELU sobre as alternâncias de carga variável."""
    casos = _casos(elementos, gamma_g, gamma_q, todos)
    env = Envoltoria()
    n = len(elementos)
    env.m_max = [None] * n
    env.m_min = [None] * n
    env.v_max = [None] * n
    env.v_min = [None] * n
    env.x = [None] * n
    ms_all = None
    for caso in casos:
        saida, ms, _ = _esforcos_caso(elementos, caso, delta)
        for i, (x, m, v) in saida.items():
            if env.m_max[i] is None:
                env.x[i] = x
                env.m_max[i], env.m_min[i] = m.copy(), m.copy()
                env.v_max[i], env.v_min[i] = v.copy(), v.copy()
            else:
                env.m_max[i] = np.maximum(env.m_max[i], m)
                env.m_min[i] = np.minimum(env.m_min[i], m)
                env.v_max[i] = np.maximum(env.v_max[i], v)
                env.v_min[i] = np.minimum(env.v_min[i], v)
        ms_all = ms.copy() if ms_all is None else np.maximum(ms_all, ms)
    env.ms_max = list(ms_all) if ms_all is not None else []
    return env


def esforcos_servico(elementos: list[Elemento], fator_q: float):
    """Um único caso de serviço: permanente mais ``fator_q`` da variável em
    todos os elementos."""
    caso = [(e.w_perm + fator_q * e.w_var, e.p_ponta) for e in elementos]
    return _esforcos_caso(elementos, caso, 1.0)


# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------

@dataclass
class ResultadoVao:
    indice: int
    L: float
    bf: float = 0.0
    a_bf: float = 0.0
    md: float = 0.0                 # kN·m, positivo máximo da envoltória
    x_md: float = 0.0               # m, a partir do apoio esquerdo do vão
    md_engastado: float = 0.0       # kN·m, piso do 14.6.6.1-a
    flexao: SecaoFlexao | None = None
    n_adicional: int = 0
    phi_adicional: float = 0.0
    aco_adicional: str = ""
    camadas: list = field(default_factory=list)
    geo: GeometriaT | None = None
    # ELS
    ieq_vao: float = 0.0
    f_imediata: float = 0.0
    f_total: float = 0.0
    f_limite: float = 0.0
    estadio: str = ""
    wk: float = 0.0
    wk_limite: float = 0.0
    sigma_s: float = 0.0
    rot_esq: float = 0.0            # rad, no apoio esquerdo (serviço)
    rot_dir: float = 0.0
    embute_esq: float = -1.0        # cm de vigota dentro do apoio (-1: o
    embute_dir: float = -1.0        # padrão da laje, sem ancoragem a checar)
    atende_flecha: bool = True
    atende_fissuracao: bool = True


@dataclass
class ResultadoApoio:
    indice: int
    t: float
    md: float = 0.0                 # kN·m, hogging
    flexao: SecaoFlexao | None = None
    macico_necessario: float = 0.0  # cm de cada lado
    macico_adotado: float = 0.0
    n_negativa: int = 0
    phi_negativa: float = 0.0
    extensao_esq: float = 0.0       # cm, a partir do eixo do apoio
    extensao_dir: float = 0.0
    comprimento: float = 0.0        # cm
    lb_nec: float = 0.0
    redistribuido: bool = False

    @property
    def b_comprimida(self) -> float:
        return self.flexao.b_comp if self.flexao else 0.0


@dataclass
class ResultadoCortante:
    rotulo: str
    v_sd: float = 0.0               # kN, a d da face
    v_rd1: float = 0.0
    v_rd2: float = 0.0
    v_rd3: float = 0.0              # com as diagonais, se precisou
    bw: float = 0.0
    d: float = 0.0
    As1: float = 0.0
    rho1: float = 0.0
    k: float = 1.0
    usou_diagonais: bool = False
    usou_estribos: bool = False
    estribos: str = ""
    s_estribo: float = 0.0
    phi_estribo: float = 0.0
    criterio: str = ""
    atende: bool = True
    nota: str = ""


@dataclass
class ResultadoBalanco:
    lado: str
    L: float
    f_imediata: float = 0.0
    f_total: float = 0.0
    f_limite: float = 0.0
    contraflecha: float = 0.0
    atende: bool = True


@dataclass
class PosicaoTrel:
    numero: int
    descricao: str
    quantidade: int                 # peças no total (todas as nervuras)
    phi: float = 0.0
    aco: str = ""
    comprimento: float = 0.0        # cm, por peça
    massa: float = 0.0              # kg total
    observacao: str = ""


@dataclass
class ResultadoTrelicada:
    laje: LajeTrelicada
    geo: dict = field(default_factory=dict)
    cargas: dict = field(default_factory=dict)
    vaos: list = field(default_factory=list)
    apoios: list = field(default_factory=list)
    balancos: list = field(default_factory=list)
    cortantes: list = field(default_factory=list)
    ancoragens: list = field(default_factory=list)
    posicoes: list = field(default_factory=list)
    verificacoes: list = field(default_factory=list)   # linhas p/ tabela
    avisos: list = field(default_factory=list)         # (classe, texto)
    quantitativo: dict = field(default_factory=dict)
    env: Envoltoria | None = None
    elementos: list = field(default_factory=list)
    offsets: list = field(default_factory=list)        # x0 de cada elemento
    distribuicao: dict = field(default_factory=dict)
    reacoes: list = field(default_factory=list)

    @property
    def atende(self) -> bool:
        return not any(c == "erro" for c, _ in self.avisos)


# ---------------------------------------------------------------------------
# Peso próprio e elementos
# ---------------------------------------------------------------------------

def peso_proprio(lt: LajeTrelicada, concreto: Concreto) -> float:
    """Peso próprio por nervura, kN/m: concreto da capa e da nervura mais o
    enchimento (mesma expressão do material de referência, com o intereixo
    no lugar de ``bf`` -- iguais quando a mesa colaborante é o intereixo)."""
    gc = concreto.peso_especifico
    ge = ENCHIMENTOS.get(lt.enchimento, ENCHIMENTOS["EPS"])
    vol_c = lt.intereixo * lt.capa + lt.bw * lt.altura_enchimento       # cm²
    vol_e = lt.largura_bloco * lt.altura_enchimento                     # cm²
    return (vol_c * gc + vol_e * ge) / 1e4


def _elementos(lt: LajeTrelicada, concreto: Concreto) -> list[Elemento]:
    pp = peso_proprio(lt, concreto)
    inter = lt.intereixo / 100.0
    els: list[Elemento] = []

    def vao(v) -> Elemento:
        return Elemento(L=v.L / 100.0, w_perm=pp + v.g * inter
                        + v.carga_linear, w_var=v.q * inter,
                        carga_linear=v.carga_linear)

    def balanco(v, comp: float, parapeito: float, lado: str) -> Elemento:
        return Elemento(L=comp / 100.0, w_perm=pp + v.g * inter,
                        w_var=v.q * inter, p_ponta=parapeito * inter,
                        balanco=lado)

    if lt.balanco_esq > 0.0:
        els.append(balanco(lt.vaos[0], lt.balanco_esq, lt.parapeito_esq,
                           "esq"))
    els += [vao(v) for v in lt.vaos]
    if lt.balanco_dir > 0.0:
        els.append(balanco(lt.vaos[-1], lt.balanco_dir, lt.parapeito_dir,
                           "dir"))
    return els


def _geom_vao(lt: LajeTrelicada, i: int) -> tuple[GeometriaT, float]:
    n = len(lt.vaos)
    cont_esq = i > 0 or lt.balanco_esq > 0.0
    cont_dir = i < n - 1 or lt.balanco_dir > 0.0
    a = _distancia_a(lt.vaos[i].L, cont_esq, cont_dir)
    bf = largura_colaborante(lt.bw, lt.largura_bloco, a, lt.intereixo)
    return GeometriaT(bw=lt.bw, bf=bf, capa=lt.capa, h=lt.h,
                      intereixo=lt.intereixo), a


# ---------------------------------------------------------------------------
# Armadura: camadas e candidatos
# ---------------------------------------------------------------------------

@dataclass
class Camada:
    n: int
    phi: float            # mm
    aco: str
    y: float              # cm, do bordo tracionado ao CG da camada

    @property
    def area(self) -> float:
        return self.n * area_barra(self.phi)

    @property
    def fyd(self) -> float:
        return Aco(self.aco).fyd_kNcm2


def _d_e_td(camadas: list[Camada], h: float) -> tuple[float, float, float]:
    """``(d, Td, As)``: altura útil pelo CG ponderado pela força de
    escoamento, a força total de escoamento e a área total."""
    td = sum(c.area * c.fyd for c in camadas)
    as_ = sum(c.area for c in camadas)
    if td <= 0.0:
        return h, 0.0, 0.0
    d_linha = sum(c.area * c.fyd * c.y for c in camadas) / td
    return h - d_linha, td, as_


def _cap_camada(bw: float, phi: float, c: float, phi_est: float) -> int:
    """Quantas barras cabem numa camada da nervura de ``bw`` cm."""
    livre = bw - 2.0 * (c + phi_est / 10.0)
    s_min = max(2.0, phi / 10.0)
    cap = math.floor((livre + s_min) / (phi / 10.0 + s_min) + 1e-9)
    return max(cap, 1)


def _camadas_pos(n: int, phi: float, c: float, bw: float,
                 phi_est: float) -> list[Camada] | None:
    """Camadas de ``n`` barras na face inferior da nervura moldada; ``None``
    se nem em duas camadas cabem."""
    cap = _cap_camada(bw, phi, c, phi_est)
    y1 = c + phi_est / 10.0 + phi / 20.0
    if n <= cap:
        return [Camada(n, phi, "CA-50", y1)]
    if n <= 2 * cap:
        y2 = y1 + phi / 10.0 + max(2.0, phi / 10.0)
        return [Camada(cap, phi, "CA-50", y1),
                Camada(n - cap, phi, "CA-50", y2)]
    return None


def _estribos(concreto: Concreto, bw: float, d: float, h: float,
              v_sd: float, v_rd2: float, phi_min: float, s_fixo: float = 0.0
              ) -> dict:
    """Estribos verticais de 2 ramos da nervura como viga (modelo I,
    θ = 45°, 17.4.2.2): ``Vc = Vc0 = 0,6 fctd bw d`` e a armadura mínima
    ``0,2 fctm / fywk``. Espaçamento máximo 0,6 d e 30 cm (0,3 d e 20 cm
    se VSd > 0,67 VRd2, 18.3.3.2) e, **em laje nervurada, nunca mais que
    20 cm** (20.1). Devolve ``dict(phi, s, asw_s (cm²/m), ok, ...)``."""
    ft = concreto.fctd / 10.0
    vc = 0.6 * ft * bw * d
    vsw = max(v_sd - vc, 0.0)
    aco = Aco("CA-50")
    fywd = min(aco.fyd_kNcm2, 43.5)
    if h <= 35.0:
        fywd = min(fywd, cisalhamento.fywd_laje(h) / 10.0)
    asw_nec = vsw / (0.9 * d * fywd) if d > 0 else 0.0            # cm²/cm
    asw_min = 0.2 * concreto.fctm / aco.fyk * bw
    asw = max(asw_nec, asw_min)
    forte = v_sd > 0.67 * v_rd2
    s_max = math.floor(min(0.3 * d, 20.0) if forte
                       else min(0.6 * d, 30.0, 20.0))
    ok = True
    escolhido = None
    for phi in sorted({phi_min, 5.0, 6.3, 8.0}):
        if phi < phi_min - 1e-9:
            continue
        s = s_fixo if s_fixo > 0.0 else float(
            max(5, min(math.floor(2.0 * area_barra(phi) / asw), s_max)))
        asw_ad = 2.0 * area_barra(phi) / s
        if asw_ad + 1e-12 >= asw and s <= s_max + 1e-9:
            escolhido = (phi, s, asw_ad)
            break
    if escolhido is None:
        phi = phi_min
        s = float(max(5, min(math.floor(2.0 * area_barra(phi) / asw), s_max)))
        escolhido = (phi, s, 2.0 * area_barra(phi) / s)
        ok = False
    phi, s, asw_ad = escolhido
    return dict(phi=phi, s=s, asw_s=asw_ad * 100.0, vc=vc, vsw=vsw,
                asw_nec=asw_nec * 100.0, asw_min=asw_min * 100.0, ok=ok)


def _candidatos_moldada() -> list[tuple[int, float, str]]:
    c = [(n, phi, "CA-50") for phi in BITOLAS_MOLDADA for n in range(1, 9)]
    c.sort(key=lambda t: (t[0] * area_barra(t[1]), t[0]))
    return c


def _candidatos_adicional(moldada: bool = False
                          ) -> list[tuple[int, float, str]]:
    if moldada:
        return _candidatos_moldada()
    cands = [(0, 0.0, "CA-60")]
    for phi, aco in ADICIONAIS:
        for n in (1, 2, 3, 4):
            cands.append((n, phi, aco))
    cands.sort(key=lambda c: c[0] * area_barra(c[1]) * Aco(c[2]).fyd
               if c[0] else 0.0)
    return cands


def _candidatos_negativa() -> list[tuple[int, float]]:
    cands = [(n, phi) for phi in NEGATIVAS for n in (1, 2, 3, 4)]
    cands.sort(key=lambda c: c[0] * area_barra(c[1]))
    return cands


def _camadas_vao(lt: LajeTrelicada, n_ad: int, phi_ad: float, aco_ad: str,
                 c_inf: float) -> list[Camada]:
    if lt.moldada:
        cam = _camadas_pos(n_ad, phi_ad, c_inf, lt.bw, lt.phi_estribo)
        if cam is None:
            cap = _cap_camada(lt.bw, phi_ad, c_inf, lt.phi_estribo)
            cam = [Camada(cap, phi_ad, "CA-50",
                          c_inf + lt.phi_estribo / 10.0 + phi_ad / 20.0)]
        return cam
    phi_inf = TRELICAS[lt.trelica][3]
    cam = [Camada(2, phi_inf, "CA-60", c_inf + phi_inf / 20.0)]
    if n_ad > 0:
        cam.append(Camada(n_ad, phi_ad, aco_ad, c_inf + phi_ad / 20.0))
    return cam


# ---------------------------------------------------------------------------
# Flexão de uma seção
# ---------------------------------------------------------------------------

def _flexao(rotulo: str, md_kNm: float, bf: float, bw: float, hf: float,
            d: float, camadas: list[Camada], h: float, concreto: Concreto,
            aco_ref: Aco, md_min_kNm: float, x_d_limite: float
            ) -> SecaoFlexao:
    """Dimensiona/verifica uma seção T (ou retangular, com ``bf == bw``)."""
    sec = SecaoFlexao(rotulo=rotulo, md=md_kNm, b_comp=bf, d=d,
                      x_d_limite=x_d_limite, md_min=md_min_kNm)
    sigma = concreto.sigma_cd
    lam = concreto.lambda_
    proj = max(md_kNm, md_min_kNm)
    sec.governa = "mínima (17.3.5.2.1)" if md_min_kNm > md_kNm else "ELU"
    _, td, as_ = _d_e_td(camadas, h)
    sec.td_adot, sec.As_adot = td, as_
    r = _forca_necessaria(proj * 100.0, bf, bw, hf, d, sigma)
    if r is None:
        sec.erro = (f"o momento de {md_kNm:.2f} kN·m não cabe nesta seção "
                    f"(d = {d:.1f} cm): aumente a altura ou o fck")
        sec.td_nec = float("inf")
        return sec
    sec.td_nec, y = r
    sec.x = y / lam
    sec.x_d = sec.x / d if d > 0.0 else 0.0
    sec.As_nec = sec.td_nec / aco_ref.fyd_kNcm2
    sec.dominio = "2" if sec.x_d <= 0.259 else "3" if sec.x_d <= 0.628 \
        else "4"
    if td > 0.0:
        _, mrd = _bloco(td, bf, bw, hf, d, sigma)
        sec.mrd = mrd / 100.0
    if sec.x_d > x_d_limite + 1e-9:
        sec.erro = (f"x/d = {sec.x_d:.3f} passa do limite de "
                    f"{x_d_limite:.3f} (14.6.4.3): a seção não é dútil -- "
                    f"aumente a altura, o fck ou o trecho maciço")
    return sec


# ---------------------------------------------------------------------------
# ELS de um vão e do balanço
# ---------------------------------------------------------------------------

def _prop_negativa(lt: LajeTrelicada, ambiente: Ambiente, n_neg: int,
                   phi_neg: float, ae: float, fctm: float, b_comp: float
                   ) -> tuple[float, float, float]:
    """``(Ic, Mr, III)`` da seção sob momento negativo (tração na capa,
    compressão embaixo numa largura ``b_comp``), em cm⁴ e kN·cm."""
    geo = GeometriaT(bw=lt.bw, bf=lt.intereixo, capa=lt.capa, h=lt.h,
                     intereixo=lt.intereixo)
    c_sup = ambiente.cobrimento_superior(phi_neg)
    d_neg = lt.h - c_sup - phi_neg / 20.0
    as_ = n_neg * area_barra(phi_neg)
    ic, y_t = _estadio_I(geo, as_, lt.h - d_neg, ae, lt.inercia_homogeneizada)
    mr = ALFA_FLEXAO_TRACAO * fctm * ic / y_t
    iii, _ = _inercia_II(b_comp, b_comp, lt.h, d_neg, ae * as_)
    return ic, mr, iii


def _b_apoio(lt: LajeTrelicada, ra: ResultadoApoio) -> float:
    """Largura comprimida do apoio: a nervura, ou o intereixo se o trecho
    maciço adotado cobre o que o momento pede."""
    if ra.macico_adotado > 0.0 and ra.macico_adotado >= ra.macico_necessario:
        return lt.intereixo
    return lt.bw


def _zonas_vao(lt, i, k, camadas, geo, d_pos, ms_serv, apoios_res, neg_adot,
               ambiente, ae, fctm):
    """Rigidez equivalente nas zonas do vão (17.3.2.1.1, Figura 17.3):
    ``[(x0, x1, Ieq)]`` em cm, mais o momento de vão e o de fissuração."""
    L = lt.vaos[i].L
    _, _, as_pos = _d_e_td(camadas, lt.h)
    ic, y_top = _estadio_I(geo, as_pos, d_pos, ae,
                           lt.inercia_homogeneizada)
    mr_pos = ALFA_FLEXAO_TRACAO * fctm * ic / (lt.h - y_top)
    iii_pos, _ = _inercia_II(geo.bf, lt.bw, lt.capa, d_pos, ae * as_pos)
    _, m, _ = ms_serv[0][k]
    m_v = float(m.max()) * 100.0                          # kN·cm
    i_v = _ieq(m_v, mr_pos, ic, iii_pos)
    n = len(lt.vaos)
    a_esq = 0.15 * L if (i > 0 or lt.balanco_esq > 0.0) else 0.0
    a_dir = 0.15 * L if (i < n - 1 or lt.balanco_dir > 0.0) else 0.0

    def i_apoio(j: int) -> float:
        n_neg, phi_neg = neg_adot[j]
        ms = ms_serv[1][j] * 100.0
        icn, mrn, iiin = _prop_negativa(lt, ambiente, n_neg, phi_neg, ae,
                                        fctm, _b_apoio(lt, apoios_res[j]))
        return _ieq(ms, mrn, icn, iiin)

    i1 = i_apoio(i) if a_esq > 0.0 else i_v
    i2 = i_apoio(i + 1) if a_dir > 0.0 else i_v
    zonas = [(0.0, a_esq, i1), (a_esq, L - a_dir, i_v), (L - a_dir, L, i2)]
    return zonas, m_v, mr_pos


def _integra_vao(L_cm: float, m_kNcm: np.ndarray, zonas, ecs: float
                 ) -> tuple[float, float, float]:
    """Deflexão máxima do vão (cm, positiva para baixo) e as rotações nas
    pontas (rad, positiva quando a viga desce para a direita)."""
    x = np.linspace(0.0, L_cm, len(m_kNcm))
    ei = np.empty_like(x)
    for x0, x1, inercia in zonas:
        sel = (x >= x0 - 1e-9) & (x <= x1 + 1e-9)
        ei[sel] = ecs * inercia
    kappa = m_kNcm / ei
    dx = np.diff(x)
    th = np.concatenate([[0.0], np.cumsum(0.5 * (kappa[1:] + kappa[:-1])
                                          * dx)])
    i2 = np.concatenate([[0.0], np.cumsum(0.5 * (th[1:] + th[:-1]) * dx)])
    th0 = i2[-1] / L_cm
    y = th0 * x - i2
    return float(y.max()), float(th0), float(th0 - th[-1])


def _els_vao(lt, i, k, camadas, geo, d, neg_adot, ms_serv, mf_serv, concreto,
             ambiente, cfg, ecs, ae, fctm, apoios_res, rv: ResultadoVao
             ) -> bool:
    """Flecha e fissuração do vão; preenche ``rv`` e devolve ``True`` quando
    alguma das duas falha."""
    L = lt.vaos[i].L
    zonas, m_v, mr = _zonas_vao(lt, i, k, camadas, geo, d, ms_serv,
                                apoios_res, neg_adot, ambiente, ae, fctm)
    _, m, _ = ms_serv[0][k]
    y, th0, th_fim = _integra_vao(L, m * 100.0, zonas, ecs)
    rv.f_imediata = y
    rv.f_total = y * cfg.fator_fluencia
    rv.f_limite = L / cfg.divisor_flecha
    rv.ieq_vao = zonas[1][2]
    rv.rot_esq, rv.rot_dir = th0, th_fim
    rv.estadio = "II - fissurada" if m_v > mr else "I - não fissurada"
    cf = min(lt.contraflecha, L / 350.0)       # Tabela 13.3, nota b
    rv.atende_flecha = rv.f_total - cf <= rv.f_limite + 1e-9

    # fissuração: combinação frequente, tensão no estádio II (17.3.3.2)
    _, mfv, _ = mf_serv[0][k]
    mser = float(mfv.max()) * 100.0
    _, _, as_ = _d_e_td(camadas, lt.h)
    rv.wk_limite = ambiente.wk_limite
    rv.wk, rv.sigma_s = 0.0, 0.0
    if as_ > 0.0 and mser > mr:
        i2, x2 = _inercia_II(geo.bf, lt.bw, lt.capa, d, ae * as_)
        sig = ae * mser * (d - x2) / i2                    # kN/cm²
        rv.sigma_s = sig * 10.0                            # MPa
        for c in camadas:
            if c.n <= 0:
                continue
            eta1 = Aco(c.aco).eta_1
            acr = lt.bw * (c.y + 7.5 * c.phi / 10.0)       # cm²
            rho = as_ / acr
            f = c.phi / (12.5 * eta1) * rv.sigma_s / 210_000.0
            w1 = f * 3.0 * rv.sigma_s / concreto.fctm
            w2 = f * (4.0 / rho + 45.0)
            rv.wk = max(rv.wk, min(w1, w2))
    rv.atende_fissuracao = rv.wk <= rv.wk_limite + 1e-9
    return not (rv.atende_flecha and rv.atende_fissuracao)


def _flecha_balanco(lt, lado, comp, elementos, ms_serv, vaos_res, apoios_res,
                    neg_adot, ambiente, cfg, ecs, ae, fctm, ini
                    ) -> ResultadoBalanco:
    """Flecha da ponta do balanço: rotação do apoio (vinda do vão vizinho)
    vezes o comprimento, mais a curvatura do próprio balanço."""
    rb = ResultadoBalanco(lado=lado, L=comp)
    k = 0 if lado == "esq" else len(elementos) - 1
    j = 0 if lado == "esq" else len(lt.vaos)
    n_neg, phi_neg = neg_adot[j]
    icn, mrn, iiin = _prop_negativa(lt, ambiente, n_neg, phi_neg, ae, fctm,
                                    _b_apoio(lt, apoios_res[j]))
    s, m, _ = ms_serv[0][k]
    i_eq = _ieq(float(np.abs(m).max()) * 100.0, mrn, icn, iiin)
    kappa = m * 100.0 / (ecs * i_eq)                       # m < 0
    sc = s * 100.0
    if lado == "esq":                                      # s: ponta -> apoio
        kap = kappa[::-1]
        dist = (sc[-1] - sc)[::-1]
        rot = vaos_res[0].rot_esq
        sinal = -1.0
    else:                                                  # s: apoio -> ponta
        kap, dist = kappa, sc
        rot = vaos_res[-1].rot_dir
        sinal = 1.0
    dd = np.diff(dist)
    th = np.concatenate([[0.0], np.cumsum(0.5 * (kap[1:] + kap[:-1]) * dd)])
    i2 = np.concatenate([[0.0], np.cumsum(0.5 * (th[1:] + th[:-1]) * dd)])
    rb.f_imediata = float(sinal * rot * comp - i2[-1])
    rb.f_total = rb.f_imediata * cfg.fator_fluencia
    rb.f_limite = comp / cfg.divisor_flecha_balanco
    rb.contraflecha = min(lt.contraflecha, comp / 350.0)
    rb.atende = abs(rb.f_total) - rb.contraflecha <= rb.f_limite + 1e-9
    return rb


# ---------------------------------------------------------------------------
# Dimensionamento
# ---------------------------------------------------------------------------

def _projetar_apoios(lt, concreto, ambiente, env, elementos, ini, h, bw, inter,
                     fctk_sup, res, x_d_lim_base=0.45):
    """Flexão negativa em cada apoio e o trecho maciço que ela pede."""
    n = len(lt.vaos)
    sigma, lam = concreto.sigma_cd, concreto.lambda_
    aco_neg = Aco("CA-50")
    cands_neg = _candidatos_negativa()
    geo_ap = GeometriaT(bw=bw, bf=inter, capa=lt.capa, h=h, intereixo=inter)
    md_min_neg = 0.8 * (geo_ap.inercia / geo_ap.y_topo) * fctk_sup / 100.0
    neg_adot: list[tuple[int, float]] = []
    apoios: list[ResultadoApoio] = []
    for j in range(n + 1):
        ap = lt.apoios[j]
        ra = ResultadoApoio(indice=j, t=ap.t)
        ra.md = float(env.ms_max[j]) if env.ms_max else 0.0
        if ra.md <= 1e-9:
            ra.md = 0.0
            ra.flexao = SecaoFlexao(rotulo=f"Apoio {j + 1}",
                                    armadura="sem negativa",
                                    governa="sem momento negativo")
            neg_adot.append((0, 0.0))
            apoios.append(ra)
            continue
        redistribuido = 0 < j < n and lt.delta < 1.0 - 1e-9
        ra.redistribuido = redistribuido
        x_d_lim = min((lt.delta - 0.44) / 1.25, x_d_lim_base) \
            if redistribuido else x_d_lim_base
        lista = cands_neg if lt.automatica else \
            [(max(0, ap.n_negativa), ap.phi_negativa)]

        # capacidade com a largura da nervura -> precisa de maciço?
        phi_ref = lista[0][1] if lista[0][1] > 0.0 else 8.0
        d_ref = h - ambiente.cobrimento_superior(phi_ref) - phi_ref / 20.0
        y_lim = lam * x_d_lim * d_ref
        m_lim_bw = sigma * bw * y_lim * (d_ref - y_lim / 2.0) / 100.0
        if ra.md > m_lim_bw + 1e-9:
            alcance = 0.0
            for k, e in enumerate(elementos):
                if e.balanco == "esq":
                    dist = (e.L - env.x[k]) if j == 0 else None
                elif e.balanco == "dir":
                    dist = env.x[k] if j == n else None
                elif k - ini == j - 1:
                    dist = e.L - env.x[k]
                elif k - ini == j:
                    dist = env.x[k]
                else:
                    dist = None
                if dist is None:
                    continue
                excede = (-env.m_min[k]) > m_lim_bw + 1e-9
                if excede.any():
                    alcance = max(alcance, float(dist[excede].max()))
            ra.macico_necessario = math.ceil(alcance * 100.0 / 5.0) * 5.0 + 5.0
        if ra.macico_necessario > 0.0 and lt.macico_automatico:
            ra.macico_adotado = max(ap.macico, ra.macico_necessario)
        else:
            ra.macico_adotado = ap.macico
        b_comp = _b_apoio(lt, ra)

        escolhido = None
        for n_neg, phi_neg in lista:
            c_sup = ambiente.cobrimento_superior(phi_neg)
            d_neg = h - c_sup - phi_neg / 20.0
            camadas = [Camada(n_neg, phi_neg, "CA-50", c_sup + phi_neg / 20.0)]
            sec = _flexao(f"Apoio {j + 1}", ra.md, b_comp, b_comp, h, d_neg,
                          camadas, h, concreto, aco_neg, md_min_neg, x_d_lim)
            escolhido = (sec, n_neg, phi_neg)
            if sec.erro and "não cabe" in sec.erro:
                break
            if sec.td_adot + 1e-9 >= sec.td_nec and not sec.erro:
                break
            if not lt.automatica:
                break
        sec, n_neg, phi_neg = escolhido
        if sec.td_adot + 1e-9 < sec.td_nec and not sec.erro:
            sec.erro = (f"armadura adotada ({n_neg} Ø{phi_neg:g}, "
                        f"As = {sec.As_adot:.2f} cm²) menor que a "
                        f"necessária ({sec.As_nec:.2f} cm²)")
        if sec.erro and b_comp == bw and ra.macico_necessario > 0.0:
            sec.erro = (f"o momento negativo de {ra.md:.2f} kN·m passa da "
                        f"capacidade da nervura de {bw:g} cm "
                        f"({m_lim_bw:.2f} kN·m): faça trecho maciço de "
                        f"{ra.macico_necessario:.0f} cm de cada lado do "
                        f"apoio, ou use vigotas justapostas")
        sec.armadura = f"{n_neg} Ø{phi_neg:g} (CA-50)"
        ra.flexao = sec
        ra.n_negativa, ra.phi_negativa = n_neg, phi_neg
        neg_adot.append((n_neg, phi_neg))
        apoios.append(ra)
    res.apoios = apoios
    res.geo["md_min_neg"] = md_min_neg
    return neg_adot


def dimensionar_trelicada(lt: LajeTrelicada, concreto: Concreto,
                          ambiente: Ambiente, cfg: Config | None = None
                          ) -> ResultadoTrelicada:
    """Dimensiona e verifica a faixa treliçada inteira."""
    cfg = cfg or Config()
    res = ResultadoTrelicada(laje=lt)
    avisos = res.avisos
    n = len(lt.vaos)
    if n < 1:
        raise ValueError("A faixa treliçada precisa de ao menos um vão.")
    if lt.trelica not in TRELICAS:
        raise ValueError(f"Treliça desconhecida: {lt.trelica!r}")
    if not 0.75 <= lt.delta <= 1.0:
        raise ValueError("A redistribuição δ deve estar entre 0,75 e 1,00 "
                         "(14.6.4.3).")
    for v in lt.vaos:
        if v.L <= 0.0:
            raise ValueError("Todo vão precisa de comprimento positivo.")
    if lt.bw <= 0.0 or lt.largura_bloco <= 0.0 or lt.capa <= 0.0:
        raise ValueError("Base, bloco de enchimento e capa precisam ser "
                         "positivos.")

    h_tr, phi_sup, phi_diag, phi_inf, kg_m = TRELICAS[lt.trelica]
    h_tr_cm = h_tr / 10.0
    aco_tr = Aco("CA-50") if lt.moldada else Aco("CA-60")
    c_inf = lt.cobrimento if lt.cobrimento is not None \
        else ambiente.cobrimento_nominal
    h, bw, inter = lt.h, lt.bw, lt.intereixo
    ecs = concreto.Ecs / 10.0                              # kN/cm²
    ae = 210_000.0 / concreto.Ecs
    fctm = concreto.fctm / 10.0
    fctk_sup = concreto.fctk_sup / 10.0
    pp = peso_proprio(lt, concreto)
    res.geo = dict(bw=bw, intereixo=inter, h=h, capa=lt.capa,
                   he=lt.altura_enchimento, le=lt.largura_bloco,
                   h_trelica=h_tr_cm, pp=pp, c_inf=c_inf, ae=ae)

    # -- 13.2.4.2 e consistência da treliça ---------------------------------
    capa_min = max(lt.largura_bloco / 15.0, 4.0)
    if lt.capa < capa_min - 1e-9:
        avisos.append(("erro", f"capa de {lt.capa:g} cm menor que o mínimo "
                       f"de {capa_min:.1f} cm (13.2.4.2: 1/15 da distância "
                       f"entre faces das nervuras e no mínimo 4 cm)."))
    if bw < 5.0:
        avisos.append(("erro", f"nervura de {bw:g} cm: o mínimo é 5 cm "
                       f"(13.2.4.2)."))
    if inter > 110.0:
        avisos.append(("erro", f"intereixo de {inter:g} cm passa de 110 cm: "
                       f"a capa passa a ser laje maciça sobre grelha "
                       f"(13.2.4.2-c) -- fora do escopo desta verificação."))
    elif inter > 65.0:
        classe = "erro" if inter > 90.0 or bw <= 12.0 else "obs"
        avisos.append((classe, f"intereixo de {inter:g} cm (65 a 110 cm, "
                       f"13.2.4.2-b): exige a verificação da flexão da mesa "
                       f"e o cortante como viga -- o programa só faz o "
                       f"cortante como laje."))
    if not lt.moldada and h_tr_cm > h - 1.5 - phi_sup / 20.0 + 1e-9:
        avisos.append(("erro", f"a treliça de {h_tr_cm:g} cm não cabe na "
                       f"laje de {h:g} cm com cobrimento superior de 1,5 cm."))
    if not lt.moldada and h_tr_cm < lt.altura_enchimento - 2.0:
        avisos.append(("obs", f"a treliça ({h_tr_cm:g} cm) é bem mais baixa "
                       f"que o enchimento ({lt.altura_enchimento:g} cm): o "
                       f"fio superior fica longe da capa."))
    maior = max(v.L for v in lt.vaos)
    if maior > 400.0 and not lt.moldada:
        n_tr = 1 if maior <= 600.0 else 2
        avisos.append(("obs", f"vão acima de 4 m: prever {n_tr} nervura(s) "
                       f"transversal(is) de travamento (Manual ArcelorMittal, "
                       f"p. 34, citando a NBR 6118)."))

    # -- esforços -----------------------------------------------------------
    elementos = _elementos(lt, concreto)
    res.elementos = elementos
    ini = 1 if lt.balanco_esq > 0.0 else 0
    x0, offs = 0.0, []
    for e in elementos:
        offs.append(x0)
        x0 += e.L
    res.offsets = offs
    env = envoltoria(elementos, cfg.gamma_g, cfg.gamma_q, lt.delta)
    res.env = env
    inter_m = inter / 100.0
    res.cargas = dict(
        pp=pp, g=[v.g * inter_m for v in lt.vaos],
        q=[v.q * inter_m for v in lt.vaos],
        w_perm=[e.w_perm for e in elementos],
        w_var=[e.w_var for e in elementos],
        w_d=[cfg.gamma_g * e.w_perm + cfg.gamma_q * e.w_var
             for e in elementos])
    ms_serv = esforcos_servico(elementos, cfg.psi_2)
    mf_serv = esforcos_servico(elementos, cfg.psi_1)

    # -- apoios: flexão negativa ---------------------------------------------
    neg_adot = _projetar_apoios(lt, concreto, ambiente, env, elementos, ini,
                                h, bw, inter, fctk_sup, res)
    if any(r.macico_adotado > 0.0 for r in res.apoios):
        avisos.append(("obs", "trecho maciço junto ao apoio: o programa não "
                       "soma o peso a mais do concreto no lugar do "
                       "enchimento nem a rigidez dele na flecha."))

    # -- vãos: flexão positiva e ELS ------------------------------------------
    cands_pos = _candidatos_adicional(lt.moldada)
    for i, v in enumerate(lt.vaos):
        k = i + ini
        L = v.L / 100.0
        geo, a_bf = _geom_vao(lt, i)
        rv = ResultadoVao(indice=i, L=v.L, bf=geo.bf, a_bf=a_bf, geo=geo)
        mx = env.m_max[k]
        rv.md = float(mx.max())
        rv.x_md = float(env.x[k][mx.argmax()])
        w_tot = cfg.gamma_g * elementos[k].w_perm \
            + cfg.gamma_q * elementos[k].w_var
        if n >= 2 and lt.balanco_esq <= 0.0 and lt.balanco_dir <= 0.0:
            # 14.6.6.1-a: nunca menos que o engastamento perfeito nos
            # apoios internos
            if 0 < i < n - 1:
                rv.md_engastado = w_tot * L * L / 24.0
            else:
                rv.md_engastado = 9.0 * w_tot * L * L / 128.0
        proj = max(rv.md, rv.md_engastado)
        w0 = geo.inercia / (h - geo.y_topo)
        md_min = 0.8 * w0 * fctk_sup / 100.0
        lista = cands_pos if lt.automatica else [
            (max(0, v.n_adicional), v.phi_adicional, v.aco_adicional)]

        primeira, escolha = None, None
        for cand in lista:
            n_ad, phi_ad, aco_ad = cand
            camadas = _camadas_vao(lt, n_ad, phi_ad, aco_ad, c_inf)
            d, td, _ = _d_e_td(camadas, h)
            sec = _flexao(f"Vão {i + 1}", proj, geo.bf, bw, lt.capa, d,
                          camadas, h, concreto, aco_tr, md_min, 0.45)
            if lt.moldada:
                sec.armadura = f"{n_ad} Ø{phi_ad:g} ({aco_ad})"
                if len(camadas) > 1:
                    sec.armadura += f" em {len(camadas)} camadas"
            else:
                sec.armadura = f"2 Ø{phi_inf:g} (treliça)" + (
                    f" + {n_ad} Ø{phi_ad:g} ({aco_ad})" if n_ad else "")
            achado = (sec, cand, camadas)
            escolha = achado
            if not lt.automatica:
                break
            if sec.erro or sec.td_adot + 1e-9 < sec.td_nec:
                continue
            if primeira is None:
                primeira = achado
            tmp = ResultadoVao(indice=i, L=v.L)
            if not _els_vao(lt, i, k, camadas, geo, d, neg_adot, ms_serv,
                            mf_serv, concreto, ambiente, cfg, ecs, ae, fctm,
                            res.apoios, tmp):
                break
        else:
            if primeira is not None:
                escolha = primeira
        sec, cand, camadas = escolha
        rv.flexao, rv.camadas = sec, camadas
        rv.n_adicional, rv.phi_adicional, rv.aco_adicional = cand
        _els_vao(lt, i, k, camadas, geo, sec.d, neg_adot, ms_serv, mf_serv,
                 concreto, ambiente, cfg, ecs, ae, fctm, res.apoios, rv)
        res.vaos.append(rv)

    # -- balanços ---------------------------------------------------------------
    for lado, comp in (("esq", lt.balanco_esq), ("dir", lt.balanco_dir)):
        if comp > 0.0:
            res.balancos.append(_flecha_balanco(
                lt, lado, comp, elementos, ms_serv, res.vaos, res.apoios,
                neg_adot, ambiente, cfg, ecs, ae, fctm, ini))

    def largura_barras(n_b: int, phi: float) -> float:
        return n_b * phi / 10.0 + max(n_b - 1, 0) * max(phi / 10.0, 2.0)

    for rv in res.vaos:
        if not lt.moldada and rv.n_adicional > 0 and largura_barras(
                rv.n_adicional, rv.phi_adicional) > lt.base - 2.0 * c_inf:
            avisos.append(("obs", f"vão {rv.indice + 1}: {rv.n_adicional} "
                           f"Ø{rv.phi_adicional:g} não cabem numa camada na "
                           f"base de {lt.base:g} cm (espaço de "
                           f"{lt.base - 2.0 * c_inf:.1f} cm): use duas "
                           f"camadas ou vigotas justapostas."))
    for ra in res.apoios:
        if ra.n_negativa > 0 and largura_barras(
                ra.n_negativa, ra.phi_negativa) > lt.bw + 1e-9:
            avisos.append(("obs", f"apoio {ra.indice + 1}: {ra.n_negativa} "
                           f"Ø{ra.phi_negativa:g} não cabem sobre a nervura "
                           f"de {lt.bw:g} cm -- "
                           + ("espalhe a negativa na mesa ou faça trecho "
                              "maciço." if lt.moldada else
                              f"a negativa vai na região das vigotas "
                              f"(Manual, p. 37): espalhe-a sobre vigotas "
                              f"justapostas ou no trecho maciço.")))

    _cortante_e_ancoragem(res, lt, concreto, ambiente, env, elementos, ini,
                          c_inf, phi_inf, phi_diag, h_tr_cm)
    if lt.moldada:
        _mesa_unidirecional(res, lt, concreto, ambiente, cfg)
    _detalhar(res, lt, concreto, ambiente, cfg, env, elementos, ini, c_inf,
              kg_m)
    _montar_verificacoes(res, lt, cfg)
    return res


# ---------------------------------------------------------------------------
# Cortante e ancoragem
# ---------------------------------------------------------------------------

def _mesa_unidirecional(res, lt, concreto, ambiente, cfg) -> None:
    """Flexão da mesa da nervurada unidirecional: faixa transversal de 1 m
    entre duas nervuras, simplesmente apoiada nelas (13.2.4.2). Exigida de
    65 a 110 cm de intereixo; a armadura transversal da mesa é a maior entre
    a de distribuição, a da flexão e 1,5 cm²/m (Pinheiro e Razente, 2013,
    citados por Nepomuceno) quando exigida."""
    from .flexao import dimensionar_secao
    gc = concreto.peso_especifico
    inter = lt.intereixo
    p_d = max(cfg.gamma_g * (lt.capa / 100.0 * gc + v.g)
              + cfg.gamma_q * v.q for v in lt.vaos)
    a = inter / 100.0
    m = p_d * a * a / 8.0
    c_sup = ambiente.cobrimento_superior(5.0)
    d = lt.capa - c_sup - 0.25
    fl = dimensionar_secao(max(m, 1e-6), lt.capa, d, c_sup, concreto,
                           Aco("CA-50"), "positiva em cruz", "Mesa")
    exigida = inter > 65.0 + 1e-9
    candidatos = [(res.distribuicao["As_m"], res.distribuicao["motivo"]),
                  (fl.As, "flexão da mesa entre as nervuras")]
    if exigida:
        candidatos.append((1.5, "mínimo de 1,5 cm²/m na mesa (intereixo de "
                                "65 a 110 cm)"))
    as_m, motivo = max(candidatos, key=lambda t: t[0])
    res.distribuicao.update(As_m=as_m, mesa_m=m, mesa_As=fl.As,
                            mesa_exigida=exigida, mesa_erro=fl.erro,
                            motivo=motivo)


def _cortante_e_ancoragem(res, lt, concreto, ambiente, env, elementos, ini,
                          c_inf, phi_inf, phi_diag, h_tr_cm) -> None:
    n = len(lt.vaos)
    h, bw, inter = lt.h, lt.bw, lt.intereixo
    aco_tr = Aco("CA-60")
    reacoes = [0.0] * (n + 1)
    ult = len(elementos) - 1
    for j in range(n + 1):
        ra = res.apoios[j]
        t = ra.t
        esq = (ini + j - 1) if j >= 1 else (0 if lt.balanco_esq > 0.0
                                            else None)
        dir_ = (ini + j) if j < n else (ult if lt.balanco_dir > 0.0 else None)
        for k, lado in ((esq, "esq"), (dir_, "dir")):
            if k is None:
                continue
            e = elementos[k]
            L = e.L * 100.0
            x = env.x[k] * 100.0
            dist = (L - x) if lado == "esq" else x      # a partir do apoio
            v_abs = np.maximum(np.abs(env.v_max[k]), np.abs(env.v_min[k]))
            ordem = np.argsort(dist)
            dist, v_abs = dist[ordem], v_abs[ordem]
            hog = ra.md > 1e-9 and (0 < j < n or e.balanco != "")
            if hog:
                phi_n = ra.phi_negativa
                d = h - ambiente.cobrimento_superior(phi_n) - phi_n / 20.0
                as1 = ra.n_negativa * area_barra(phi_n)
                b_cis = inter if ra.macico_adotado >= t / 2.0 + d \
                    and ra.macico_adotado > 0.0 else bw
            else:
                rv = res.vaos[(j - 1) if lado == "esq" else j]
                d = rv.flexao.d
                as1 = rv.flexao.As_adot
                b_cis = bw
            v_sd = float(np.interp(t / 2.0 + d, dist, v_abs))
            v_face = float(np.interp(t / 2.0, dist, v_abs))
            reacoes[j] += float(np.interp(0.0, dist, v_abs))
            rc = ResultadoCortante(
                rotulo=(f"Apoio {j + 1}, "
                        f"{'balanço' if e.balanco else 'vão'} "
                        f"{'à esquerda' if lado == 'esq' else 'à direita'}"),
                v_sd=v_sd, bw=b_cis, d=d, As1=as1)
            rc.rho1 = min(as1 / (b_cis * d), 0.02) if d > 0 else 0.0
            rc.k = max(1.0, 1.6 - d / 100.0)
            rc.v_rd1 = cisalhamento.tau_rd(concreto) * rc.k \
                * (1.2 + 40.0 * rc.rho1) * b_cis * d
            rc.v_rd2 = 0.27 * concreto.alfa_v2 * concreto.fcd / 10.0 \
                * b_cis * d
            rc.atende = rc.v_sd <= rc.v_rd1 + 1e-9
            if lt.moldada:
                laje_ok = inter <= 65.0 + 1e-9 or (inter <= 90.0 + 1e-9
                                                   and bw > 12.0)
                rc.criterio = "laje (19.4.1)" if laje_ok else "viga (17.4.2)"
                if rc.v_sd > rc.v_rd2 + 1e-9:
                    rc.atende = False
                    rc.nota = ("a biela comprimida não resiste (VRd2): "
                               "aumente bw ou h")
                elif not laje_ok or not rc.atende:
                    est = _estribos(concreto, b_cis, d, h, rc.v_sd, rc.v_rd2,
                                    lt.phi_estribo, lt.s_estribo
                                    if not lt.automatica else 0.0)
                    rc.usou_estribos = True
                    rc.phi_estribo, rc.s_estribo = est["phi"], est["s"]
                    rc.estribos = f"estribos Ø{est['phi']:g} c/{est['s']:.0f}"
                    rc.v_rd3 = est["vc"] + est["asw_s"] / 100.0 * 0.9 * d \
                        * min(aco_tr.fyd_kNcm2, 43.5)
                    rc.atende = est["ok"] and rc.v_sd <= rc.v_rd2 + 1e-9
                    rc.nota = ("com estribos (modelo I, 17.4.2.2)"
                               if rc.atende else
                               "nem com estribos de 8 mm o cortante fecha: "
                               "aumente bw ou h")
                else:
                    rc.nota = "sem estribos (VSd ≤ VRd1)"
            elif not rc.atende:
                alfa = math.atan2(
                    h_tr_cm - (TRELICAS[lt.trelica][1] + phi_inf) / 20.0,
                    PASSO_TRELICA / 2.0)
                asw_s = 2.0 * area_barra(phi_diag) / PASSO_TRELICA  # cm²/cm
                fywd = min(aco_tr.fyd_kNcm2 * 10.0,
                           cisalhamento.fywd_laje(h)) / 10.0
                vc = 0.6 * concreto.fctd / 10.0 * b_cis * d
                vsw = asw_s * 0.9 * d * fywd * (math.sin(alfa)
                                                + math.cos(alfa))
                rc.v_rd3 = vc + vsw
                rc.usou_diagonais = True
                rc.atende = rc.v_sd <= min(rc.v_rd3, rc.v_rd2) + 1e-9
                rc.nota = ("conferido com as diagonais da treliça como "
                           "armadura transversal (Modelo I, 19.4.2)"
                           if rc.atende else
                           "nem com as diagonais da treliça o cortante "
                           "fecha: aumente a altura, faça trecho maciço ou "
                           "use vigotas justapostas")
            res.cortantes.append(rc)
            if not rc.atende:
                res.avisos.append(("erro", f"{rc.rotulo}: VSd = "
                                   f"{rc.v_sd:.2f} kN passa da resistência "
                                   f"({rc.v_rd1:.2f} kN sem armadura); "
                                   f"{rc.nota}."))
            # ancoragem da positiva do vão neste apoio
            if e.balanco:
                continue
            if (j == 0 and lt.balanco_esq > 0.0) or \
                    (j == n and lt.balanco_dir > 0.0):
                continue                        # a vigota segue pelo balanço
            rv = res.vaos[(j - 1) if lado == "esq" else j]
            _ancorar(res, lt, concreto, rv, j, lado, t,
                     cisalhamento.FATOR_DECALAGEM * v_face, c_inf, phi_inf)
    res.reacoes = reacoes

    as_prin = max([r.flexao.As_adot for r in res.vaos] + [0.0])
    dist_as, motivo = armadura_distribuicao(as_prin / (inter / 100.0),
                                            concreto, h)
    res.distribuicao = dict(As_m=max(dist_as, 0.6), motivo=motivo)


def _ancorar(res, lt, concreto, rv, j, lado, t, rst, c_inf, phi_inf) -> None:
    """Ancoragem das barras positivas do vão no apoio ``j``.

    O comprimento de vigota dentro do apoio é o que fecha ``lb,nec`` de
    todas as barras: no modo automático o programa adota o maior entre o
    informado e o necessário (arredondado para cima), até o que o apoio
    comporta; no manual vale o informado. Se o apoio não comporta, é erro."""
    n = len(lt.vaos)
    ext = (j == 0 and lado == "dir") or (j == n and lado == "esq")
    interno = 0 < j < n
    if ext:
        disponivel = max(t - c_inf, 0.0)
    elif lt.moldada:
        # as barras dos dois vãos se sobrepõem na largura do apoio
        disponivel = max(t - 2.0 * c_inf, 0.0)
    else:
        disponivel = max(t / 2.0 - c_inf, 0.0)
    grupos = [] if lt.moldada else [(2, phi_inf, "CA-60", 0.0)]
    if rv.n_adicional > 0:
        gancho = max(lt.h - 2.0 * c_inf, 0.0) if lt.moldada else \
            GANCHO_ADICIONAL.get(rv.phi_adicional, 0.0)
        grupos.append((rv.n_adicional, rv.phi_adicional, rv.aco_adicional,
                       gancho))
    td = sum(n_b * area_barra(p) * Aco(a).fyd_kNcm2 for n_b, p, a, _ in grupos)
    razao = min(1.0, rst / td) if td > 0.0 else 1.0

    def verificar(embute: float):
        saida = []
        for n_b, phi, aco_cat, gancho in grupos:
            as_ef = n_b * area_barra(phi)
            if interno:
                # 18.3.2.4.1: em apoio intermediário o comprimento pode ser
                # 10 Ø, se não houver possibilidade de momento positivo no
                # apoio -- aqui o momento do apoio é sempre negativo
                nec = 10.0 * phi / 10.0
                r = ancoragem.ResultadoAncoragem(
                    rotulo=f"vão {rv.indice + 1}, apoio {j + 1}", phi=phi,
                    lb=nec, lb_nec=nec, lb_min=nec, disponivel=embute,
                    atende=embute >= nec - 1e-9,
                    observacao=(f"apoio intermediário com momento sempre "
                                f"negativo: ancoragem de 10 Ø = {nec:.1f} cm "
                                f"(18.3.2.4.1); a vigota entra "
                                f"{embute:.1f} cm"))
            else:
                r = ancoragem.verificar_positiva(
                    f"vão {rv.indice + 1}, apoio {j + 1}", phi,
                    as_ef * razao, as_ef, embute, gancho, concreto,
                    Aco(aco_cat))
            saida.append((phi, aco_cat, r))
        return saida

    embute = min(lt.apoio_vigota, disponivel)
    if lt.automatica:
        folgado = verificar(disponivel)
        if all(r.atende for _, _, r in folgado):
            for k in range(0, int(disponivel) + 1):
                if all(r.atende for _, _, r in verificar(float(k))):
                    embute = max(embute, float(k))
                    break
            else:
                embute = disponivel
    if lado == "dir":
        rv.embute_esq = embute
    else:
        rv.embute_dir = embute
    for phi, aco_cat, r in verificar(embute):
        res.ancoragens.append((rv.indice, j, phi, aco_cat, r))
        if not r.atende:
            extra = "" if interno else (
                f". A vigota entra {embute:.0f} cm no apoio (cabem "
                f"{disponivel:.0f} cm com t = {t:g} cm)")
            res.avisos.append(("erro", f"vão {rv.indice + 1}, apoio "
                               f"{j + 1}, Ø{phi:g}: {r.observacao}{extra}. "
                               f"Alargue o apoio ou aumente a entrada da "
                               f"vigota."))


# ---------------------------------------------------------------------------
# Detalhamento e quantitativo
# ---------------------------------------------------------------------------

def _detalhar(res, lt, concreto, ambiente, cfg, env, elementos, ini, c_inf,
              kg_m) -> None:
    n = len(lt.vaos)
    inter = lt.intereixo
    n_ner = max(1, math.ceil(lt.largura_laje * 100.0 / inter - 1e-9))
    comp_total = lt.balanco_esq + sum(v.L for v in lt.vaos) + lt.balanco_dir
    pos: list[PosicaoTrel] = []
    num = 1
    for i, v in enumerate(lt.vaos):
        t_l, t_r = lt.apoios[i].t, lt.apoios[i + 1].t
        livre = v.L - t_l / 2.0 - t_r / 2.0
        rv0 = res.vaos[i]
        e_l = rv0.embute_esq if rv0.embute_esq >= 0 else             min(lt.apoio_vigota, t_l / 2.0)
        e_r = rv0.embute_dir if rv0.embute_dir >= 0 else             min(lt.apoio_vigota, t_r / 2.0)
        L_vig = livre + e_l + e_r
        if i == 0:
            L_vig += lt.balanco_esq
        if i == n - 1:
            L_vig += lt.balanco_dir
        if lt.moldada:
            rvm = res.vaos[i]
            L_b = L_vig - 2.0 * c_inf
            pos.append(PosicaoTrel(
                num, f"Positiva da nervura (vão {i + 1})",
                rvm.n_adicional * n_ner, rvm.phi_adicional,
                rvm.aco_adicional, L_b,
                rvm.n_adicional * n_ner * L_b / 100.0
                * massa_linear(rvm.phi_adicional),
                f"{rvm.n_adicional} Ø{rvm.phi_adicional:g} por nervura"
                + (f" em {len(rvm.camadas)} camadas"
                   if len(rvm.camadas) > 1 else "")))
            num += 1
            continue
        pos.append(PosicaoTrel(num, f"Vigota {lt.trelica} (vão {i + 1})",
                               n_ner, 0.0, "CA-60", L_vig,
                               n_ner * L_vig / 100.0 * kg_m,
                               "treliça pronta, com a base de concreto"))
        num += 1
        rv = res.vaos[i]
        if rv.n_adicional > 0:
            L_ad = L_vig - 2.0 * c_inf
            pos.append(PosicaoTrel(
                num, f"Adicional positiva (vão {i + 1})",
                rv.n_adicional * n_ner, rv.phi_adicional, rv.aco_adicional,
                L_ad, rv.n_adicional * n_ner * L_ad / 100.0
                * massa_linear(rv.phi_adicional),
                "dentro da base da vigota"))
            num += 1

    if lt.moldada:
        est = [rc for rc in res.cortantes if rc.usou_estribos]
        if est:
            phi_e = max(rc.phi_estribo for rc in est)
            s_e = min(rc.s_estribo for rc in est)
            per = 2.0 * ((lt.bw - 2.0 * c_inf) + (lt.h - 2.0 * c_inf)) + 10.0
            qtd = (math.ceil(comp_total / s_e) + 1) * n_ner
            pos.append(PosicaoTrel(
                num, "Estribos da nervura", qtd, phi_e, "CA-50", per,
                qtd * per / 100.0 * massa_linear(phi_e),
                f"Ø{phi_e:g} c/{s_e:.0f} ao longo de toda a nervura "
                f"(simplificação: o mais apertado de todos os apoios)"))
            num += 1

    md_corte = res.geo.get("md_min_neg", 0.0)

    def hogging_ate(k: int, a_partir_apoio: np.ndarray) -> float:
        """Distância, a partir do apoio, até onde o momento negativo da
        envoltória continua acima do corte -- contada do apoio para o vão e
        parando no primeiro ponto abaixo dele (o outro apoio do vão tem o
        próprio momento negativo e não conta aqui)."""
        ordem = np.argsort(a_partir_apoio)
        dist = a_partir_apoio[ordem]
        hog = (-env.m_min[k])[ordem]
        limite = max(md_corte, 1e-9)
        alcance = 0.0
        for d_i, m_i in zip(dist, hog):
            if m_i <= limite:
                break
            alcance = float(d_i)
        return alcance

    for j in range(n + 1):
        ra = res.apoios[j]
        if ra.md <= 1e-9:
            continue
        phi = ra.phi_negativa
        d = ra.flexao.d
        a_l = cisalhamento.FATOR_DECALAGEM * d
        razao = min(1.0, ra.flexao.td_nec / ra.flexao.td_adot) \
            if ra.flexao.td_adot > 0.0 else 1.0
        ra.lb_nec = max(ancoragem.lb(concreto, Aco("CA-50"), phi) * razao,
                        ancoragem.lb_minimo(concreto, Aco("CA-50"), phi))
        passo = max(a_l, ra.lb_nec)
        ext_esq = ext_dir = 0.0
        if j == 0:
            ext_esq = lt.balanco_esq - c_inf
        else:
            k = (j - 1) + ini
            L = elementos[k].L * 100.0
            ext_esq = min(hogging_ate(k, L - env.x[k] * 100.0) + passo, L)
        if j == n:
            ext_dir = lt.balanco_dir - c_inf
        else:
            k = j + ini
            L = elementos[k].L * 100.0
            ext_dir = min(hogging_ate(k, env.x[k] * 100.0) + passo, L)
        ra.extensao_esq, ra.extensao_dir = ext_esq, ext_dir
        ra.comprimento = ext_esq + ext_dir
        pos.append(PosicaoTrel(
            num, f"Negativa no apoio {j + 1}", ra.n_negativa * n_ner, phi,
            "CA-50", ra.comprimento,
            ra.n_negativa * n_ner * ra.comprimento / 100.0
            * massa_linear(phi),
            f"{ext_esq:.0f} cm à esquerda e {ext_dir:.0f} cm à direita do "
            f"eixo do apoio (Md,mín + max(1,5 d; lb,nec = "
            f"{ra.lb_nec:.0f} cm))"))
        num += 1

    as_d = res.distribuicao["As_m"]
    phi_d, s = 8.0, 7
    for phi_d in (5.0, 6.3, 8.0):
        s = min(math.floor(100.0 * area_barra(phi_d) / as_d),
                int(cfg.espacamento_maximo_distribuicao))
        if s >= 10:
            break
    s = max(int(s), 7)
    res.distribuicao.update(phi=phi_d, s=float(s),
                            As_adot=area_barra(phi_d) * 100.0 / s)
    n_t = math.ceil(comp_total / s) + 1
    n_l = math.ceil(lt.largura_laje * 100.0 / s) + 1
    for nome, qtd, comp_b in (
            ("Distribuição transversal na capa", n_t, lt.largura_laje * 100.0),
            ("Distribuição longitudinal na capa", n_l, comp_total)):
        pos.append(PosicaoTrel(
            num, nome, qtd, phi_d, "CA-60", comp_b,
            qtd * comp_b / 100.0 * massa_linear(phi_d),
            f"Ø{phi_d:g} c/{s}, no meio da "
            + ("mesa" if lt.moldada else
               "capa, sem amarrar no fio superior da treliça")))
        num += 1
    res.posicoes = pos
    area = comp_total / 100.0 * lt.largura_laje
    vol = ((inter * lt.capa + lt.bw * lt.altura_enchimento) / 1e4
           * (comp_total / 100.0) * n_ner)
    massa = sum(p.massa for p in pos)
    res.quantitativo = dict(
        n_nervuras=n_ner, area=area, volume_concreto=vol,
        concreto_L_m2=(inter * lt.capa + lt.bw * lt.altura_enchimento)
        / 1e4 / (inter / 100.0) * 1000.0,
        aco_kg=massa, aco_kg_m2=massa / area if area > 0 else 0.0,
        comprimento_total=comp_total,
        por_bitola=quantitativo_por_bitola(pos),
        trelicas=quantitativo_trelicas(pos, lt.trelica))


def quantitativo_por_bitola(posicoes: list) -> dict:
    """``{Ø: {comprimento (m), massa (kg), posicoes, emendas,
    massa_emendas}}`` das barras -- o formato do quantitativo das maciças,
    para o resumo do aço da prancha. As vigotas (Ø 0) ficam de fora, em
    :func:`quantitativo_trelicas`."""
    saida: dict = {}
    for p in posicoes:
        if p.phi <= 0.0:
            continue
        d = saida.setdefault(p.phi, {"comprimento": 0.0, "massa": 0.0,
                                     "posicoes": 0, "emendas": 0,
                                     "massa_emendas": 0.0})
        d["comprimento"] += p.quantidade * p.comprimento / 100.0
        d["massa"] += p.massa
        d["posicoes"] += 1
    return dict(sorted(saida.items()))


def quantitativo_trelicas(posicoes: list, designacao: str) -> dict:
    """``{designação: {comprimento (m), massa (kg), posicoes}}`` das vigotas
    treliçadas (as posições de Ø 0)."""
    saida: dict = {}
    for p in posicoes:
        if p.phi > 0.0:
            continue
        d = saida.setdefault(designacao, {"comprimento": 0.0, "massa": 0.0,
                                          "posicoes": 0})
        d["comprimento"] += p.quantidade * p.comprimento / 100.0
        d["massa"] += p.massa
        d["posicoes"] += 1
    return saida


# ---------------------------------------------------------------------------
# Verificações em forma de tabela
# ---------------------------------------------------------------------------

def _montar_verificacoes(res, lt, cfg) -> None:
    linhas = []

    def add(item, local, sol, rest, ok, ref):
        linhas.append([item, local, sol, rest, "OK" if ok else "NÃO OK", ref])

    for rv in res.vaos:
        f = rv.flexao
        add("Flexão positiva", f"vão {rv.indice + 1}",
            f"Md = {f.md:.2f} kN·m",
            f"MRd = {f.mrd:.2f} kN·m ({f.armadura})", f.atende,
            "17.2 / 14.6.4.3")
        add("Flecha total", f"vão {rv.indice + 1}", f"{rv.f_total:.2f} cm",
            f"{rv.f_limite:.2f} cm (L/{cfg.divisor_flecha})",
            rv.atende_flecha, "17.3.2 / Tab. 13.3")
        add("Fissuração", f"vão {rv.indice + 1}", f"wk = {rv.wk:.2f} mm",
            f"{rv.wk_limite:.2f} mm", rv.atende_fissuracao, "17.3.3.2")
    for ra in res.apoios:
        if ra.md <= 1e-9:
            continue
        f = ra.flexao
        add("Flexão negativa", f"apoio {ra.indice + 1}",
            f"Md = {ra.md:.2f} kN·m",
            f"MRd = {f.mrd:.2f} kN·m ({f.armadura})", f.atende,
            "17.2 / 14.6.4.3")
    for rb in res.balancos:
        add("Flecha do balanço",
            "esquerdo" if rb.lado == "esq" else "direito",
            f"{rb.f_total:.2f} cm",
            f"{rb.f_limite:.2f} cm (L/{cfg.divisor_flecha_balanco})",
            rb.atende, "Tab. 13.3")
    for rc in res.cortantes:
        add("Cortante", rc.rotulo, f"VSd = {rc.v_sd:.2f} kN",
            f"VRd1 = {rc.v_rd1:.2f} kN"
            + (f"; VRd3 = {rc.v_rd3:.2f} kN" if rc.usou_diagonais else "")
            + (f"; {rc.estribos}" if rc.usou_estribos else ""),
            rc.atende, "19.4.1 / 17.4.2" if lt.moldada else
            "19.4.1 / 19.4.2")
    for iv, j, phi, aco, r in res.ancoragens:
        add("Ancoragem", f"vão {iv + 1}, apoio {j + 1}, Ø{phi:g}",
            f"lb,nec = {r.lb_nec:.1f} cm",
            f"disponível {r.disponivel:.1f} cm"
            + (f" + gancho {r.ponta_gancho:.0f} cm" if r.com_gancho else ""),
            r.atende, "9.4.2")
    if lt.moldada and res.distribuicao.get("mesa_exigida"):
        d_ = res.distribuicao
        add("Flexão da mesa", f"entre nervuras, a = {lt.intereixo:g} cm",
            f"m = {d_['mesa_m']:.2f} kN·m/m",
            f"As,transv = {d_['As_m']:.2f} cm²/m", not d_["mesa_erro"],
            "13.2.4.2-b")
    res.verificacoes = linhas

    for rv in res.vaos:
        f = rv.flexao
        if not f.atende:
            res.avisos.append(("erro", f"Vão {rv.indice + 1}: "
                               f"{f.erro or 'armadura positiva insuficiente'}."))
        if not rv.atende_flecha:
            res.avisos.append(("erro", f"Vão {rv.indice + 1}: flecha total de "
                               f"{rv.f_total:.2f} cm passa de "
                               f"{rv.f_limite:.2f} cm -- aumente a altura ou "
                               f"adote contraflecha (até L/350, Tabela 13.3, "
                               f"nota b)."))
        if not rv.atende_fissuracao:
            res.avisos.append(("erro", f"Vão {rv.indice + 1}: wk = "
                               f"{rv.wk:.2f} mm passa de "
                               f"{rv.wk_limite:.2f} mm."))
    for ra in res.apoios:
        if ra.md > 1e-9 and not ra.flexao.atende:
            res.avisos.append(("erro", f"Apoio {ra.indice + 1}: "
                               f"{ra.flexao.erro or 'negativa insuficiente'}."))
    for rb in res.balancos:
        if not rb.atende:
            res.avisos.append(("erro", f"Balanço "
                               f"{'esquerdo' if rb.lado == 'esq' else 'direito'}"
                               f": flecha total de {rb.f_total:.2f} cm passa "
                               f"de {rb.f_limite:.2f} cm."))
    if lt.delta < 1.0 - 1e-9:
        res.avisos.append(("obs", f"redistribuição δ = {lt.delta:.2f} nos "
                           f"apoios internos (14.6.4.3): x/d limitado a "
                           f"{(lt.delta - 0.44) / 1.25:.3f} neles, e o "
                           f"momento positivo dos vãos já a considera."))
    if any(r.n_adicional == 0 for r in res.vaos):
        pass
