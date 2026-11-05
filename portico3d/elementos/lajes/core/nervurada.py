# -*- coding: utf-8 -*-
"""
nervurada.py
Dimensionamento da laje nervurada bidirecional moldada no local: painel
retangular com nervuras nas duas direções, mesa comum, enchimento removível.

Roteiro (Bocchi Jr., 1995, caps. 2 e 3; ABNT NBR 6118:2026, 13.2.4.2 e
14.7.7):

    1. geometria: o painel se divide em ``nx × ny`` partes iguais pelo
       intereixo pedido; a nervura é uma seção T com a largura colaborante do
       14.6.2.2; o peso próprio é o da mesa mais o das nervuras (sem o
       enchimento removível);
    2. esforços por **dois caminhos**, e adota-se o maior:

       * **placa** (14.7.7 permite tratar a nervurada como laje maciça
         quando 13.2.4.2 é cumprido) -- coeficientes elásticos das tabelas de
         placa do próprio programa, ``m = α p a²`` por metro, vezes o
         intereixo para ter o momento por nervura;
       * **grelha** -- o modelo recomendado por Bocchi: cada nervura é uma
         barra de rigidez ``E·I`` da seção T, com torção reduzida (14.6.6.2,
         15 %), as cargas nos nós (área de influência) e os apoios de borda
         indeslocáveis. Resolvido pelo método dos deslocamentos, com três
         graus de liberdade por nó (deslocamento vertical e duas rotações);

    3. flexão positiva (seção T) e negativa junto aos bordos engastados
       (compressão na nervura, de largura ``bw``);
    4. cortante da nervura: como laje (19.4.1) se o intereixo permite
       (13.2.4.2-a/b), senão como viga com estribos (17.4.2, modelo I);
    5. mesa: flexão como painel de laje maciça apoiado nas nervuras (só
       exigida de 65 a 110 cm), cortante da mesa e cisalhamento da ligação
       mesa-nervura (Bocchi, 3.3), com a armadura transversal que resulta;
    6. flecha: a grelha refeita com a rigidez equivalente de Branson
       (17.3.2.1.1) de cada direção, com a fluência do critério;
       fissuração pela 17.3.3.2;
    7. detalhamento e quantitativo.

Unidades: cm e kN, exceto onde indicado (momentos em kN·m por nervura).

**O que é hipótese e não norma**, declarado para não parecer o contrário:

* os bordos são vigas **indeslocáveis** (hipótese das tabelas e da grelha de
  Bocchi); a rigidez à torção das vigas de borda é desprezada, e as
  nervuras de borda não entram na grelha (são o próprio apoio);
* as cargas entram só nos nós internos, por área de influência -- a faixa
  de meio intereixo junto ao apoio vai direto para a viga;
* torção de compatibilidade não é dimensionada (14.6.6.2 a dispensa no ELU);
* a armadura é a mesma em todas as nervuras da direção (a da mais
  carregada), como é prática, salvo a opção em contrário;
* não há faixa maciça modelada no entorno dos bordos nem sobre pilares: o
  programa só diz quanto ela deveria ter onde o engaste esmaga a nervura;
* a verificação do cortante como laje usa as expressões do 19.4.1 com
  ``bw`` da nervura; a flexão da mesa usa a tabela de placa apoiada nas
  quatro nervuras (sem continuidade da mesa entre painéis).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import ancoragem, cisalhamento
from . import tabelas as tb
from .materiais import Aco, Ambiente, Concreto, area_barra, massa_linear
from .modelo import Config
from .nervurada_modelo import (BITOLAS_ESTRIBO, BITOLAS_NERVURA,
                               ENCHIMENTOS_NERVURADA, LajeNervuradaBi)
from .trelicada import (ALFA_FLEXAO_TRACAO, Camada, GeometriaT,
                        SecaoFlexao, _camadas_pos, _cap_camada, _d_e_td,
                        _estadio_I, _estribos, _flexao, _ieq, _inercia_II,
                        largura_colaborante)

CA50 = Aco("CA-50")


# ---------------------------------------------------------------------------
# Grelha plana (método dos deslocamentos)
# ---------------------------------------------------------------------------

@dataclass
class SolucaoGrelha:
    """Resultado de uma análise de grelha: por linha de nervura."""

    nx: int
    ny: int
    w: np.ndarray                    # (ny+1, nx+1), m, positivo para baixo
    mx: dict = field(default_factory=dict)   # j -> (nx+1) momentos, ∥ x
    my: dict = field(default_factory=dict)   # i -> (ny+1) momentos, ∥ y
    vx: dict = field(default_factory=dict)   # j -> (nx) cortantes (|V|)
    vy: dict = field(default_factory=dict)   # i -> (ny)
    u: np.ndarray | None = None              # deslocamentos (w, sx, sy) por nó


def _k_flexao(ei: float, L: float) -> np.ndarray:
    c = ei / L ** 3
    return c * np.array([[12.0, 6 * L, -12.0, 6 * L],
                         [6 * L, 4 * L ** 2, -6 * L, 2 * L ** 2],
                         [-12.0, -6 * L, 12.0, -6 * L],
                         [6 * L, 2 * L ** 2, -6 * L, 4 * L ** 2]])


def resolver_grelha(nx: int, ny: int, ax: float, ay: float, ei_x: float,
                    ei_y: float, gj_x: float, gj_y: float, p: float,
                    engaste: tuple[bool, bool, bool, bool]) -> SolucaoGrelha:
    """Grelha ortogonal de ``nx × ny`` painéis de ``ax × ay`` metros.

    As barras ∥ x ficam nas linhas ``j = 1 .. ny-1`` e as ∥ y nas colunas
    ``i = 1 .. nx-1``; os nós do contorno são os apoios (w = 0). ``engaste``
    = (x=0, x=lx, y=0, y=ly): rotação normal ao bordo impedida. ``p`` é a
    carga superficial, kN/m², distribuída aos nós pela área de influência.
    """
    nn = (nx + 1) * (ny + 1)
    idx = lambda i, j: j * (nx + 1) + i                      # noqa: E731
    K = np.zeros((3 * nn, 3 * nn))
    elems = []

    def add(dofs, ke):
        K[np.ix_(dofs, dofs)] += ke

    for j in range(1, ny):
        for i in range(nx):
            a, b = idx(i, j), idx(i + 1, j)
            add([3 * a, 3 * a + 1, 3 * b, 3 * b + 1], _k_flexao(ei_x, ax))
            add([3 * a + 2, 3 * b + 2],
                gj_x / ax * np.array([[1.0, -1.0], [-1.0, 1.0]]))
            elems.append(("x", j, i, a, b, ax, ei_x))
    for i in range(1, nx):
        for j in range(ny):
            a, b = idx(i, j), idx(i, j + 1)
            add([3 * a, 3 * a + 2, 3 * b, 3 * b + 2], _k_flexao(ei_y, ay))
            add([3 * a + 1, 3 * b + 1],
                gj_y / ay * np.array([[1.0, -1.0], [-1.0, 1.0]]))
            elems.append(("y", i, j, a, b, ay, ei_y))

    F = np.zeros(3 * nn)
    for j in range(1, ny):
        for i in range(1, nx):
            F[3 * idx(i, j)] = p * ax * ay
    fixos = set()
    ligado = np.zeros(nn, bool)
    for tipo, _l, _k, a, b, _L, _e in elems:
        ligado[a] = ligado[b] = True
    for j in range(ny + 1):
        for i in range(nx + 1):
            n = idx(i, j)
            if not ligado[n]:
                fixos.update((3 * n, 3 * n + 1, 3 * n + 2))
                continue
            borda = i in (0, nx) or j in (0, ny)
            if borda:
                fixos.add(3 * n)             # a viga de borda não desce
            # e, sendo uma linha rígida, não gira ao longo dela mesma
            if i in (0, nx):
                fixos.add(3 * n + 2)         # tangente ao bordo x = const
            if j in (0, ny):
                fixos.add(3 * n + 1)         # tangente ao bordo y = const
            if i == 0 and engaste[0] or i == nx and engaste[1]:
                fixos.add(3 * n + 1)
            if j == 0 and engaste[2] or j == ny and engaste[3]:
                fixos.add(3 * n + 2)
    livres = [d for d in range(3 * nn) if d not in fixos]
    Kl = K[np.ix_(livres, livres)]
    # torção nula deixaria a rotação do nó de borda sem rigidez: um resquício
    # numérico evita a matriz singular sem alterar os resultados
    Kl = Kl + np.eye(len(livres)) * 1e-9 * max(float(np.abs(K).max()), 1.0)
    u = np.zeros(3 * nn)
    u[livres] = np.linalg.solve(Kl, F[livres])

    sol = SolucaoGrelha(nx=nx, ny=ny, w=np.zeros((ny + 1, nx + 1)), u=u)
    for j in range(ny + 1):
        for i in range(nx + 1):
            sol.w[j, i] = u[3 * idx(i, j)]
    for j in range(1, ny):
        sol.mx[j] = np.zeros(nx + 1)
        sol.vx[j] = np.zeros(nx)
    for i in range(1, nx):
        sol.my[i] = np.zeros(ny + 1)
        sol.vy[i] = np.zeros(ny)
    extremos_x: dict = {}
    extremos_y: dict = {}
    for tipo, l, k, a, b, L, ei in elems:
        if tipo == "x":
            w1, t1, w2, t2 = u[3 * a], u[3 * a + 1], u[3 * b], u[3 * b + 1]
        else:
            w1, t1, w2, t2 = u[3 * a], u[3 * a + 2], u[3 * b], u[3 * b + 2]
        m1 = ei / L ** 2 * (6 * w1 + 4 * L * t1 - 6 * w2 + 2 * L * t2)
        m2 = -ei / L ** 2 * (6 * w1 + 2 * L * t1 - 6 * w2 + 4 * L * t2)
        v = (m1 - m2) / L             # sem carga no elemento: V = -dM/dx
        if tipo == "x":
            extremos_x[(l, k)] = (m1, m2)
            sol.vx[l][k] = v
        else:
            extremos_y[(l, k)] = (m1, m2)
            sol.vy[l][k] = v
    # No nó, o momento de flexão de uma barra não é contínuo: a diferença é
    # a torção da barra que cruza (equilíbrio de momentos do nó). Para o
    # dimensionamento vale, em cada nó, o maior dos dois lados.
    for j in range(1, ny):
        for i in range(nx + 1):
            c = []
            if i > 0:
                c.append(extremos_x[(j, i - 1)][1])
            if i < nx:
                c.append(extremos_x[(j, i)][0])
            sol.mx[j][i] = max(c, key=abs)
    for i in range(1, nx):
        for j in range(ny + 1):
            c = []
            if j > 0:
                c.append(extremos_y[(i, j - 1)][1])
            if j < ny:
                c.append(extremos_y[(i, j)][0])
            sol.my[i][j] = max(c, key=abs)
    return sol


# ---------------------------------------------------------------------------
# Placa equivalente (tabelas elásticas)
# ---------------------------------------------------------------------------

def _vinculos(l: LajeNervuradaBi) -> tuple[int, int, int, int]:
    cod = {"apoiado": tb.APOIADO, "engastado": tb.ENGASTADO}
    return tuple(cod[b] for b in l.bordos)          # type: ignore


def placa_momentos(l: LajeNervuradaBi, p: float) -> dict:
    """Momentos elásticos da placa equivalente, kN·m/m, nas direções x e y.

    Devolve ``mx``, ``my`` (positivos) e ``neg``: ``{bordo: |m'|}`` com
    bordo 0 a 3 = x=0, x=lx, y=0, y=ly. ``a`` é o menor vão.
    """
    v = _vinculos(l)                   # (x=0, x=lx, y=0, y=ly)
    if l.lx <= l.ly:
        a, b = l.lx, l.ly
        # bordos da tabela: 1 e 3 medem a (y=0, y=ly); 2 e 4 medem b
        tab = (v[2], v[0], v[3], v[1])
        a_em_x = True
    else:
        a, b = l.ly, l.lx
        tab = (v[0], v[2], v[1], v[3])
        a_em_x = False
    if b / a > 2.0 + 1e-9:
        raise ValueError(f"lx/ly = {max(l.lx, l.ly) / min(l.lx, l.ly):.2f} "
                         "passa de 2: a laje trabalha em uma direção (14.7.7 "
                         "remete ao item 13.2.4.1) -- use a nervurada "
                         "unidirecional")
    caso = tb.caso_de(tab)
    if caso is None:
        raise ValueError("vinculação sem tabela de placa")
    al = tb.alfa_elastico(caso, a / b)
    pa2 = p * a * a
    ma, mb = al["ma"] * pa2, al["mb"] * pa2
    neg_a = al.get("ma_", 0.0) * pa2          # bordos 2 e 4 (medem b)
    neg_b = al.get("mb_", 0.0) * pa2          # bordos 1 e 3 (medem a)
    neg = {}
    if a_em_x:
        # direção a = x: os bordos x=0 e x=lx são os 2 e 4
        mx, my = ma, mb
        neg[0] = neg[1] = neg_a if v[0] == tb.ENGASTADO else 0.0
        neg[2] = neg[3] = neg_b if v[2] == tb.ENGASTADO else 0.0
        neg[1] = neg_a if v[1] == tb.ENGASTADO else 0.0
        neg[3] = neg_b if v[3] == tb.ENGASTADO else 0.0
    else:
        mx, my = mb, ma
        neg[0] = neg_b if v[0] == tb.ENGASTADO else 0.0
        neg[1] = neg_b if v[1] == tb.ENGASTADO else 0.0
        neg[2] = neg_a if v[2] == tb.ENGASTADO else 0.0
        neg[3] = neg_a if v[3] == tb.ENGASTADO else 0.0
    return dict(mx=mx, my=my, neg=neg, caso=caso, a=a, b=b, alfas=al)


# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------

@dataclass
class ResultadoDirecao:
    """Nervuras de uma direção (``x``: paralelas a x, vencem ``lx``)."""

    direcao: str
    L: float                         # m, vão
    esp: float                       # cm, intereixo entre as nervuras
    n_nervuras: int
    geo: GeometriaT | None = None
    a_bf: float = 0.0
    md_placa: float = 0.0            # kN·m por nervura
    md_grelha: float = 0.0
    md: float = 0.0                  # adotado
    md_neg: dict = field(default_factory=dict)   # extremidade -> kN·m
    flexao: SecaoFlexao | None = None
    camadas: list = field(default_factory=list)
    n_barras: int = 0
    phi: float = 0.0
    neg: dict = field(default_factory=dict)      # extremidade -> SecaoFlexao
    n_neg: dict = field(default_factory=dict)
    maciço: dict = field(default_factory=dict)   # extremidade -> cm
    v_sd: float = 0.0
    v_rd1: float = 0.0
    v_rd2: float = 0.0
    criterio_cortante: str = ""
    estribos: str = ""
    phi_est: float = 0.0             # mm, estribo adotado (0 = sem)
    asw_s: float = 0.0               # cm²/m
    s_estribo: float = 0.0
    atende_cortante: bool = True
    ancoragens: list = field(default_factory=list)
    # ELS
    ieq: float = 0.0
    estadio: str = ""
    wk: float = 0.0
    wk_limite: float = 0.0
    atende_fissuracao: bool = True
    m_servico: float = 0.0
    por_nervura: list = field(default_factory=list)   # (md, As nec, As adot)
    cobertura_barras: str = ""


@dataclass
class ResultadoNervuradaBi:
    laje: LajeNervuradaBi
    geo: dict = field(default_factory=dict)
    cargas: dict = field(default_factory=dict)
    dirs: dict = field(default_factory=dict)     # "x" e "y"
    mesa: dict = field(default_factory=dict)
    grelha: SolucaoGrelha | None = None
    grelha_els: SolucaoGrelha | None = None
    placa: dict = field(default_factory=dict)
    flecha: dict = field(default_factory=dict)
    posicoes: list = field(default_factory=list)
    verificacoes: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    quantitativo: dict = field(default_factory=dict)

    @property
    def atende(self) -> bool:
        return not any(c == "erro" for c, _ in self.avisos)


@dataclass
class PosicaoNerv:
    numero: int
    descricao: str
    quantidade: int
    phi: float = 0.0
    aco: str = ""
    comprimento: float = 0.0
    massa: float = 0.0
    observacao: str = ""


# ---------------------------------------------------------------------------
# Geometria e cargas
# ---------------------------------------------------------------------------

def peso_proprio(l: LajeNervuradaBi, concreto: Concreto) -> dict:
    """Peso próprio, kN/m²: mesa, nervuras (descontado o cruzamento) e
    enchimento que permanece."""
    gc = concreto.peso_especifico
    ge = ENCHIMENTOS_NERVURADA.get(l.enchimento, 0.0)
    ex, ey, bw, hf, hn = l.esp_x, l.esp_y, l.bw, l.hf, l.hn
    mesa = hf / 100.0 * gc
    nerv = hn / 100.0 * gc * (bw / ex + bw / ey - bw * bw / (ex * ey))
    ench = ge * hn / 100.0 * (1.0 - bw / ex) * (1.0 - bw / ey)
    return dict(mesa=mesa, nervuras=nerv, enchimento=ench,
                total=mesa + nerv + ench)


def _a_direcao(l: LajeNervuradaBi, d: str) -> float:
    """Distância ``a`` entre pontos de momento nulo da nervura (14.6.2.2)."""
    i = (0, 1) if d == "x" else (2, 3)
    n_eng = sum(1 for k in i if l.bordos[k] == "engastado")
    L = l.lx if d == "x" else l.ly
    return {2: 0.6, 1: 0.75, 0: 1.0}[n_eng] * L * 100.0


def _geom(l: LajeNervuradaBi, d: str) -> tuple[GeometriaT, float]:
    esp = l.esp_y if d == "x" else l.esp_x
    a = _a_direcao(l, d)
    bf = largura_colaborante(l.bw, esp - l.bw, a, esp)
    return GeometriaT(bw=l.bw, bf=bf, capa=l.hf, h=l.h, intereixo=esp), a


# ---------------------------------------------------------------------------
# Armadura longitudinal: camadas e candidatos
# ---------------------------------------------------------------------------

def _candidatos(n_max: int = 8) -> list[tuple[int, float]]:
    c = [(n, phi) for phi in BITOLAS_NERVURA for n in range(1, n_max + 1)]
    c.sort(key=lambda t: (t[0] * area_barra(t[1]), t[0]))
    return c


# ---------------------------------------------------------------------------
# Dimensionamento
# ---------------------------------------------------------------------------

def _engaste(l: LajeNervuradaBi) -> tuple[bool, bool, bool, bool]:
    return tuple(b == "engastado" for b in l.bordos)     # type: ignore


def _rigidezes(l: LajeNervuradaBi, concreto: Concreto, kf_x: float,
               kf_y: float) -> tuple[float, float, float, float]:
    """(EI_x, EI_y, GJ_x, GJ_y) em kN·m², por nervura."""
    ecs = concreto.Ecs / 10.0                              # kN/cm²
    g = ecs / 2.4
    out = []
    for d, kf in (("x", kf_x), ("y", kf_y)):
        geo, _ = _geom(l, d)
        ei = kf * ecs * geo.inercia / 1e4                  # kN·m²
        j = (geo.bf * l.hf ** 3 / 3.0
             + (l.h - l.hf) * l.bw ** 3 / 3.0)             # cm⁴ (Σ b h³/3)
        gj = l.kt * g * j / 1e4
        out.append((ei, gj))
    return out[0][0], out[1][0], out[0][1], out[1][1]


def _momentos_grelha(l: LajeNervuradaBi, sol: SolucaoGrelha) -> dict:
    """Máximo positivo e negativo por direção e por linha de nervura."""
    saida = {"x": [], "y": []}
    for j in range(1, sol.ny):
        m = sol.mx[j]
        saida["x"].append(dict(linha=j, pos=float(m.max()),
                               neg0=float(-m[0]), neg1=float(-m[-1]),
                               v=float(max(abs(sol.vx[j][0]),
                                           abs(sol.vx[j][-1])))))
    for i in range(1, sol.nx):
        m = sol.my[i]
        saida["y"].append(dict(linha=i, pos=float(m.max()),
                               neg0=float(-m[0]), neg1=float(-m[-1]),
                               v=float(max(abs(sol.vy[i][0]),
                                           abs(sol.vy[i][-1])))))
    return saida


def dimensionar_nervurada(l: LajeNervuradaBi, concreto: Concreto,
                          ambiente: Ambiente, cfg: Config | None = None
                          ) -> ResultadoNervuradaBi:
    """Dimensiona e verifica o painel nervurado inteiro."""
    cfg = cfg or Config()
    res = ResultadoNervuradaBi(laje=l)
    avisos = res.avisos
    if l.lx <= 0.0 or l.ly <= 0.0:
        raise ValueError("Os vãos precisam ser positivos.")
    if l.bw <= 0.0 or l.hf <= 0.0 or l.h <= l.hf:
        raise ValueError("Nervura, mesa e altura precisam fechar "
                         "(h > hf > 0 e bw > 0).")
    if l.metodo not in ("placa", "grelha", "ambos"):
        raise ValueError(f"Método desconhecido: {l.metodo!r}")
    if any(b not in ("apoiado", "engastado") for b in l.bordos):
        raise ValueError("Cada bordo é apoiado ou engastado.")
    h, bw, hf = l.h, l.bw, l.hf
    ecs = concreto.Ecs / 10.0                               # kN/cm²
    ae = 210_000.0 / concreto.Ecs
    fctm = concreto.fctm / 10.0
    fctk_sup = concreto.fctk_sup / 10.0
    c = l.cobrimento if l.cobrimento is not None \
        else ambiente.cobrimento_nominal
    esp_max = max(l.esp_x, l.esp_y)

    # -- 13.2.4.2: limites da geometria -----------------------------------
    for d, esp in (("x", l.esp_y), ("y", l.esp_x)):
        lo = esp - bw
        hf_min = max(lo / 15.0, 4.0)
        if hf < hf_min - 1e-9:
            avisos.append(("erro", f"mesa de {hf:g} cm menor que o mínimo de "
                           f"{hf_min:.1f} cm (13.2.4.2: 1/15 da distância "
                           f"entre faces das nervuras e no mínimo 4 cm)."))
            break
    if bw < 5.0:
        avisos.append(("erro", f"nervura de {bw:g} cm: o mínimo é 5 cm "
                       f"(13.2.4.2)."))
    if esp_max > 110.0:
        avisos.append(("erro", f"intereixo de {esp_max:.0f} cm passa de 110 "
                       f"cm: a mesa passa a ser laje maciça apoiada na "
                       f"grelha de vigas (13.2.4.2-c) -- fora do escopo "
                       f"desta verificação."))
    elif esp_max > 65.0:
        avisos.append(("obs", f"intereixo de {esp_max:.0f} cm (65 a 110 cm, "
                       f"13.2.4.2-b): verificada a flexão da mesa e o "
                       f"cortante da nervura como viga"
                       + (" (como laje só até 90 cm e bw > 12 cm)."
                          if esp_max <= 90.0 else ".")))

    # -- cargas -----------------------------------------------------------
    pp = peso_proprio(l, concreto)
    g = pp["total"] + l.g2
    p_d = cfg.gamma_g * g + cfg.gamma_q * l.q
    p_qp = g + cfg.psi_2 * l.q
    p_freq = g + cfg.psi_1 * l.q
    res.cargas = dict(pp=pp, g=g, q=l.q, p_d=p_d, p_qp=p_qp, p_freq=p_freq,
                      gamma_g=cfg.gamma_g, gamma_q=cfg.gamma_q)
    res.geo = dict(nx=l.nx, ny=l.ny, esp_x=l.esp_x, esp_y=l.esp_y, bw=bw,
                   h=h, hf=hf, c=c, ae=ae)

    # -- esforços: placa e grelha -------------------------------------------
    eng = _engaste(l)
    placa = placa_momentos(l, p_d)
    res.placa = placa
    ei_x, ei_y, gj_x, gj_y = _rigidezes(l, concreto, l.kf, l.kf)
    ax, ay = l.esp_x / 100.0, l.esp_y / 100.0
    sol = resolver_grelha(l.nx, l.ny, ax, ay, ei_x, ei_y, gj_x, gj_y, p_d,
                          eng)
    res.grelha = sol
    mg = _momentos_grelha(l, sol)

    # momentos por nervura
    md_placa = {"x": placa["mx"] * l.esp_y / 100.0,
                "y": placa["my"] * l.esp_x / 100.0}
    neg_placa = {0: placa["neg"][0] * l.esp_y / 100.0,
                 1: placa["neg"][1] * l.esp_y / 100.0,
                 2: placa["neg"][2] * l.esp_x / 100.0,
                 3: placa["neg"][3] * l.esp_x / 100.0}

    dirs = {}
    for d in ("x", "y"):
        L = l.lx if d == "x" else l.ly
        esp = l.esp_y if d == "x" else l.esp_x
        n_nerv = (l.ny if d == "x" else l.nx) - 1
        geo, a_bf = _geom(l, d)
        rd = ResultadoDirecao(direcao=d, L=L, esp=esp, n_nervuras=n_nerv,
                              geo=geo, a_bf=a_bf)
        rd.md_placa = md_placa[d]
        rd.md_grelha = max(r["pos"] for r in mg[d])
        rd.md = {"placa": rd.md_placa, "grelha": rd.md_grelha,
                 "ambos": max(rd.md_placa, rd.md_grelha)}[l.metodo]
        ext = (0, 1) if d == "x" else (2, 3)
        for k in ext:
            if l.bordos[k] != "engastado":
                continue
            m_gr = max((r["neg0"] if k == ext[0] else r["neg1"])
                       for r in mg[d])
            rd.md_neg[k] = {"placa": neg_placa[k], "grelha": m_gr,
                            "ambos": max(neg_placa[k], m_gr)}[l.metodo]
        dirs[d] = rd
    res.dirs = dirs
    return _projetar(res, concreto, ambiente, cfg, mg)


def _projetar(res: ResultadoNervuradaBi, concreto: Concreto,
              ambiente: Ambiente, cfg: Config, mg: dict
              ) -> ResultadoNervuradaBi:
    l = res.laje
    avisos = res.avisos
    h, bw, hf = l.h, l.bw, l.hf
    c = res.geo["c"]
    ae = res.geo["ae"]
    fctm = concreto.fctm / 10.0
    fctk_sup = concreto.fctk_sup / 10.0
    ecs = concreto.Ecs / 10.0
    sigma = concreto.sigma_cd
    lam = concreto.lambda_

    cands = _candidatos()
    esp_max = max(l.esp_x, l.esp_y)

    # ---- flexão positiva: a menor armadura que cobre o ELU ---------------
    escolha_i = {}
    for d, rd in res.dirs.items():
        geo = rd.geo
        w0 = geo.inercia / (h - geo.y_topo)
        md_min = 0.8 * w0 * fctk_sup / 100.0
        rd.flexao = None
        i_ini = 0
        if l.automatica:
            for i, (n, phi) in enumerate(cands):
                cam = _camadas_pos(n, phi, c, bw, l.phi_estribo)
                if cam is None:
                    continue
                dd, td, _ = _d_e_td(cam, h)
                sec = _flexao(f"Nervuras {d}", rd.md, geo.bf, bw, hf, dd, cam,
                              h, concreto, CA50, md_min, 0.45)
                if not sec.erro and sec.td_adot + 1e-9 >= sec.td_nec:
                    i_ini = i
                    break
            else:
                i_ini = len(cands) - 1
        escolha_i[d] = i_ini

    def aplicar(d: str, i: int) -> None:
        rd = res.dirs[d]
        geo = rd.geo
        w0 = geo.inercia / (h - geo.y_topo)
        md_min = 0.8 * w0 * fctk_sup / 100.0
        if l.automatica:
            n, phi = cands[i]
        else:
            n = l.n_x if d == "x" else l.n_y
            phi = l.phi_x if d == "x" else l.phi_y
        cam = _camadas_pos(n, phi, c, bw, l.phi_estribo)
        forcado = False
        if cam is None:
            cap = _cap_camada(bw, phi, c, l.phi_estribo)
            cam = [Camada(cap, phi, "CA-50",
                          c + l.phi_estribo / 10.0 + phi / 20.0)]
            forcado = True
        dd, _td, _ = _d_e_td(cam, h)
        sec = _flexao(f"Nervuras {d}", rd.md, geo.bf, bw, hf, dd, cam, h,
                      concreto, CA50, md_min, 0.45)
        sec.armadura = f"{n} Ø{phi:g} (CA-50)"
        if forcado:
            sec.erro = (f"{n} Ø{phi:g} não cabem em duas camadas na nervura "
                        f"de {bw:g} cm")
        rd.flexao, rd.camadas, rd.n_barras, rd.phi = sec, cam, n, phi
        rd.cobertura_barras = (f"{len(cam)} camada(s)" if len(cam) > 1
                               else "1 camada")

    # ---- ELS: grelha refeita com a rigidez equivalente --------------------
    def els() -> None:
        # passo 0: rigidez bruta -> momentos de serviço por direção
        kf0 = 1.0
        ei0 = _rigidezes(l, concreto, kf0, kf0)
        sol0 = resolver_grelha(l.nx, l.ny, l.esp_x / 100.0, l.esp_y / 100.0,
                               ei0[0], ei0[1], ei0[2], ei0[3],
                               res.cargas["p_qp"], _engaste(l))
        m0 = _momentos_grelha(l, sol0)
        fatores = {}
        for d, rd in res.dirs.items():
            geo = rd.geo
            as_ = sum(cm.area for cm in rd.camadas)
            dd, _td, _ = _d_e_td(rd.camadas, h)
            ic, y_top = _estadio_I(geo, as_, h - dd, ae, False)
            mr = ALFA_FLEXAO_TRACAO * fctm * ic / (h - y_top)
            i2, _x = _inercia_II(geo.bf, bw, hf, dd, ae * as_)
            ma = max(r["pos"] for r in m0[d]) * 100.0          # kN·cm
            rd.m_servico = ma / 100.0
            rd.ieq = _ieq(ma, mr, ic, i2)
            rd.estadio = "II - fissurada" if ma > mr else "I - não fissurada"
            fatores[d] = rd.ieq / geo.inercia
        ei1 = _rigidezes(l, concreto, fatores["x"], fatores["y"])
        sol1 = resolver_grelha(l.nx, l.ny, l.esp_x / 100.0, l.esp_y / 100.0,
                               ei1[0], ei1[1], ei1[2], ei1[3],
                               res.cargas["p_qp"], _engaste(l))
        res.grelha_els = sol1
        w_imed = float(sol1.w.max())
        vao_menor = min(l.lx, l.ly)
        res.flecha = dict(
            imediata=w_imed * 100.0, total=w_imed * 100.0 * cfg.fator_fluencia,
            limite=vao_menor * 100.0 / cfg.divisor_flecha,
            vao=vao_menor)
        res.flecha["atende"] = res.flecha["total"] <= res.flecha["limite"] \
            + 1e-9
        # fissuração: combinação frequente, tensão no estádio II
        solf = resolver_grelha(l.nx, l.ny, l.esp_x / 100.0, l.esp_y / 100.0,
                               ei0[0], ei0[1], ei0[2], ei0[3],
                               res.cargas["p_freq"], _engaste(l))
        mf = _momentos_grelha(l, solf)
        for d, rd in res.dirs.items():
            geo = rd.geo
            as_ = sum(cm.area for cm in rd.camadas)
            dd, _td, _ = _d_e_td(rd.camadas, h)
            ic, y_top = _estadio_I(geo, as_, h - dd, ae, False)
            mr = ALFA_FLEXAO_TRACAO * fctm * ic / (h - y_top)
            mser = max(r["pos"] for r in mf[d]) * 100.0
            rd.wk_limite = ambiente.wk_limite
            rd.wk = 0.0
            if as_ > 0.0 and mser > mr:
                i2, x2 = _inercia_II(geo.bf, bw, hf, dd, ae * as_)
                sig = ae * mser * (dd - x2) / i2
                sig_mpa = sig * 10.0
                for cm in rd.camadas:
                    eta1 = CA50.eta_1
                    acr = bw * (cm.y + 7.5 * cm.phi / 10.0)
                    rho = as_ / acr
                    f = cm.phi / (12.5 * eta1) * sig_mpa / 210_000.0
                    w1 = f * 3.0 * sig_mpa / concreto.fctm
                    w2 = f * (4.0 / rho + 45.0)
                    rd.wk = max(rd.wk, min(w1, w2))
            rd.atende_fissuracao = rd.wk <= rd.wk_limite + 1e-9

    idx = dict(escolha_i)
    aplicar("x", idx["x"])
    aplicar("y", idx["y"])
    els()
    if l.automatica and (not res.flecha["atende"] or not all(
            rd.atende_fissuracao for rd in res.dirs.values())):
        # sobe a armadura das duas direções, candidata a candidata, até a
        # flecha e a fissuração caberem. Se a flecha não fechar nem com
        # aço de sobra -- é laje fina: o remédio é altura --, fica a menor
        # armadura que fecha a fissuração, e o erro da flecha aparece.
        k0 = max(idx["x"], idx["y"])
        so_fissuracao = None
        achou = None
        for k in range(k0, min(k0 + 80, len(cands))):
            aplicar("x", k)
            aplicar("y", k)
            if any(rd.flexao.erro and "não cabem" in rd.flexao.erro
                   for rd in res.dirs.values()):
                continue
            els()
            fis = all(rd.atende_fissuracao for rd in res.dirs.values())
            if fis and so_fissuracao is None:
                so_fissuracao = k
            if fis and res.flecha["atende"]:
                achou = k
                break
        k_final = achou if achou is not None else (
            so_fissuracao if so_fissuracao is not None else k0)
        idx = {"x": k_final, "y": k_final} if achou is not None or             so_fissuracao is not None else dict(escolha_i)
        aplicar("x", idx["x"])
        aplicar("y", idx["y"])
        els()

    # ---- armadura variável por nervura (informativa ou adotada) --------------
    for d, rd in res.dirs.items():
        geo = rd.geo
        w0 = geo.inercia / (h - geo.y_topo)
        md_min = 0.8 * w0 * fctk_sup / 100.0
        for r in mg[d]:
            nec = 0.0
            for i, (n, phi) in enumerate(cands):
                cam = _camadas_pos(n, phi, c, bw, l.phi_estribo)
                if cam is None:
                    continue
                dd, td, _ = _d_e_td(cam, h)
                sec = _flexao("", max(r["pos"], 0.0), geo.bf, bw, hf, dd, cam,
                              h, concreto, CA50, md_min, 0.45)
                if not sec.erro and sec.td_adot + 1e-9 >= sec.td_nec:
                    nec = sec.As_nec
                    n_ok, phi_ok = n, phi
                    break
            else:
                n_ok, phi_ok = 0, 0.0
            rd.por_nervura.append(dict(
                linha=r["linha"], md=r["pos"], As_nec=nec, n=n_ok,
                phi=phi_ok))

    _flexao_negativa(res, concreto, ambiente, mg)
    _cortante(res, concreto, ambiente, mg)
    _mesa(res, concreto, ambiente)
    _detalhar(res, concreto, ambiente, cfg, mg)
    _montar_verificacoes(res, cfg)
    return res


# ---------------------------------------------------------------------------
# Flexão negativa nos bordos engastados
# ---------------------------------------------------------------------------

def _flexao_negativa(res, concreto, ambiente, mg) -> None:
    l = res.laje
    h, bw, hf = l.h, l.bw, l.hf
    sigma, lam = concreto.sigma_cd, concreto.lambda_
    fctk_sup = concreto.fctk_sup / 10.0
    c_sup0 = ambiente.cobrimento_superior(l.phi_neg)
    for d, rd in res.dirs.items():
        for k, md in rd.md_neg.items():
            ext = (0, 1) if d == "x" else (2, 3)
            fim = "início" if k == ext[0] else "fim"
            cands = [(n, l.phi_neg) for n in range(1, 9)] if not l.automatica \
                else [(n, phi) for phi in BITOLAS_NERVURA
                      for n in range(1, 9)]
            if not l.automatica:
                cands = [(max(1, l.n_neg), l.phi_neg)]
            else:
                cands.sort(key=lambda t: t[0] * area_barra(t[1]))
            # no engaste a nervura comprime embaixo: seção retangular bw x h
            d_ref = h - ambiente.cobrimento_superior(8.0) - 0.4
            y_lim = lam * 0.45 * d_ref
            m_lim = sigma * bw * y_lim * (d_ref - y_lim / 2.0) / 100.0
            w0 = bw * h ** 2 / 6.0
            md_min = 0.8 * w0 * fctk_sup / 100.0
            escolhido = None
            for n, phi in cands:
                c_sup = ambiente.cobrimento_superior(phi)
                dd = h - c_sup - phi / 20.0
                cam = [Camada(n, phi, "CA-50", c_sup + phi / 20.0)]
                sec = _flexao(f"Engaste {d} ({fim})", md, bw, bw, h, dd, cam,
                              h, concreto, CA50, md_min, 0.45)
                escolhido = (sec, n, phi)
                if sec.erro and "não cabe" in sec.erro:
                    break
                if sec.td_adot + 1e-9 >= sec.td_nec and not sec.erro:
                    break
            sec, n, phi = escolhido
            if sec.td_adot + 1e-9 < sec.td_nec and not sec.erro:
                sec.erro = (f"armadura adotada ({n} Ø{phi:g}) menor que a "
                            f"necessária ({sec.As_nec:.2f} cm²)")
            sec.armadura = f"{n} Ø{phi:g} (CA-50)"
            rd.neg[k] = sec
            rd.n_neg[k] = (n, phi)
            if md > m_lim + 1e-9:
                # onde o momento da nervura passa da capacidade à compressão
                # (grelha: distribuição nodal; placa: triangular até L/4)
                L = rd.L * 100.0
                alc = 0.25 * L
                lin = [r for r in mg[d]]
                esp_nos = (res.laje.esp_x if d == "x" else res.laje.esp_y)
                if lin:
                    m_nos = max(lin, key=lambda r: r["neg0" if k == ext[0]
                                                    else "neg1"])
                    m0 = m_nos["neg0" if k == ext[0] else "neg1"]
                    if m0 > 1e-9:
                        # momento negativo decai ~linearmente até zero a 0,25 L
                        alc = 0.25 * L * (1.0 - m_lim / md) \
                            if md > m_lim else 0.0
                rd.maciço[k] = math.ceil(alc / 5.0) * 5.0 + 5.0
                if sec.erro == "":
                    sec.erro = (f"o momento negativo de {md:.2f} kN·m passa "
                                f"da capacidade à compressão da nervura de "
                                f"{bw:g} cm ({m_lim:.2f} kN·m): faça faixa "
                                f"maciça de ao menos {rd.maciço[k]:.0f} cm "
                                f"junto ao bordo (ou laje dupla)")
            if not sec.erro:
                pass


# ---------------------------------------------------------------------------
# Cortante da nervura
# ---------------------------------------------------------------------------

def _cortante(res, concreto, ambiente, mg) -> None:
    l = res.laje
    h, bw = l.h, l.bw
    ft = concreto.fctd / 10.0
    for d, rd in res.dirs.items():
        esp = rd.esp
        v_gr = max(r["v"] for r in mg[d])
        rd.v_sd = v_gr
        sec = rd.flexao
        dd = sec.d
        as1 = sec.As_adot
        rho1 = min(as1 / (bw * dd), 0.02) if dd > 0 else 0.0
        k = max(1.0, 1.6 - dd / 100.0)
        rd.v_rd1 = cisalhamento.tau_rd(concreto) * k * (1.2 + 40.0 * rho1) \
            * bw * dd
        rd.v_rd2 = 0.27 * concreto.alfa_v2 * concreto.fcd / 10.0 * bw * dd
        laje_ok = esp <= 65.0 + 1e-9 or (esp <= 90.0 + 1e-9 and bw > 12.0)
        rd.criterio_cortante = "laje (19.4.1)" if laje_ok else "viga (17.4.2)"
        precisa = (not laje_ok) or rd.v_sd > rd.v_rd1 + 1e-9
        rd.atende_cortante = True
        if rd.v_sd > rd.v_rd2 + 1e-9:
            rd.atende_cortante = False
            rd.estribos = "biela comprimida esmagada"
            continue
        if not precisa:
            rd.estribos = "sem estribos"
            continue
        # modelo I, θ = 45° (17.4.2.2)
        est = _estribos(concreto, bw, dd, h, rd.v_sd, rd.v_rd2,
                        l.phi_estribo,
                        l.s_estribo if not l.automatica else 0.0)
        rd.s_estribo = est["s"]
        rd.asw_s = est["asw_s"]
        rd.phi_est = est["phi"]
        rd.estribos = f"estribos Ø{est['phi']:g} c/{est['s']:.0f}"
        rd.atende_cortante = est["ok"]
        if bw < 8.0 and rd.v_sd > rd.v_rd1:
            res.avisos.append(("obs", f"direção {d}: estribos em nervura de "
                               f"{bw:g} cm -- difícil de executar; considere "
                               f"nervura de 8 cm ou mais."))


# ---------------------------------------------------------------------------
# Mesa
# ---------------------------------------------------------------------------

def _mesa(res, concreto, ambiente) -> None:
    """Flexão e cortante da mesa e cisalhamento da ligação mesa-nervura."""
    from .flexao import dimensionar_secao

    l = res.laje
    hf, bw = l.hf, l.bw
    esp_max = max(l.esp_x, l.esp_y)
    gc = concreto.peso_especifico
    gamma_g, gamma_q = res.cargas["gamma_g"], res.cargas["gamma_q"]
    # carga sobre o painel da mesa: o peso das nervuras não entra (elas são
    # o apoio)
    g_mesa = hf / 100.0 * gc + l.g2
    p_mesa = gamma_g * g_mesa + gamma_q * l.q
    a_ax = min(l.esp_x, l.esp_y) / 100.0       # m, menor lado do painel
    b_ax = max(l.esp_x, l.esp_y) / 100.0
    al = tb.alfa_elastico(1, max(0.5, a_ax / b_ax))   # quatro lados apoiados
    m_mesa = al["ma"] * p_mesa * a_ax ** 2     # kN·m/m
    # reações pelas áreas de influência a 45°
    v_curto = p_mesa * a_ax / 4.0
    v_longo = p_mesa * a_ax / 2.0 * (1.0 - a_ax / (2.0 * b_ax))
    v_mesa = max(v_curto, v_longo)
    c_sup = ambiente.cobrimento_superior(5.0)
    d_mesa = hf - c_sup - 0.25
    fl = dimensionar_secao(max(m_mesa, 1e-6), hf, d_mesa, c_sup, concreto,
                           CA50, "positiva em cruz", "Mesa")
    as_mesa = fl.As
    rho1 = min(as_mesa / (100.0 * d_mesa), 0.02) if d_mesa > 0 else 0.0
    k = max(1.0, 1.6 - d_mesa / 100.0)
    v_rd1 = cisalhamento.tau_rd(concreto) * k * (1.2 + 40.0 * rho1) * 100.0 \
        * max(d_mesa, 0.0)
    exigida = esp_max > 65.0 + 1e-9
    mesa = dict(p=p_mesa, m=m_mesa, v=v_mesa, d=d_mesa,
                As_calc=fl.As_calculada, As_min=fl.As_minima, As_mesa=as_mesa,
                v_rd1=v_rd1, exigida=exigida, ligacao={},
                lim_hf=max((esp_max - bw) / 15.0, 4.0), erro=fl.erro)
    # ligação mesa-nervura (Bocchi, 3.3.1): τ = Vd / (z hf) · 0,5 (1 − bw/bf),
    # com a cortante de cálculo que a grelha já entrega majorada
    for d, rd in res.dirs.items():
        geo = rd.geo
        z = 0.9 * rd.flexao.d
        vd = rd.v_sd
        frac = 0.5 * (1.0 - bw / geo.bf)
        tau = vd / (z * hf) * frac                          # kN/cm²
        a_st = vd / (z * CA50.fyd_kNcm2) * frac * 100.0      # cm²/m
        lim = 0.25 * concreto.fcd / 10.0
        mesa["ligacao"][d] = dict(tau=tau * 10.0, a_st=a_st, lim=lim * 10.0,
                                  ok=tau <= lim + 1e-9)
    ast = max(v["a_st"] for v in mesa["ligacao"].values())
    # 1,5 cm²/m na mesa, de 65 a 110 cm de intereixo (Pinheiro e Razente,
    # 2013, citados por Nepomuceno), e nunca menos que a flexão e a ligação
    a_trans = max(as_mesa, ast, 1.5 if exigida else 0.0)
    mesa["As_malha"] = a_trans
    for phi in (4.2, 5.0, 6.3, 8.0):
        s = min(math.floor(100.0 * area_barra(phi) / a_trans), 20)
        if s >= 10:
            break
    mesa["phi"], mesa["s"] = phi, float(max(s, 7))
    mesa["As_adot"] = 100.0 * area_barra(phi) / mesa["s"]
    res.mesa = mesa


# ---------------------------------------------------------------------------
# Detalhamento e quantitativo
# ---------------------------------------------------------------------------

def _detalhar(res, concreto, ambiente, cfg, mg) -> None:
    l = res.laje
    h, bw, hf = l.h, l.bw, l.hf
    c = res.geo["c"]
    pos: list[PosicaoNerv] = []
    num = 1
    t = l.t_apoio
    for d, rd in res.dirs.items():
        L_cm = rd.L * 100.0
        sec = rd.flexao
        n_ner = rd.n_nervuras
        # ancoragem das positivas em cada extremidade
        extremos = (0, 1) if d == "x" else (2, 3)
        embute = []
        for k in extremos:
            disp = max(t - c, 0.0)
            td = sum(cm.area * cm.fyd for cm in rd.camadas)
            rst = cisalhamento.FATOR_DECALAGEM * rd.v_sd
            razao = min(1.0, rst / td) if td > 0 else 1.0
            gancho = max(h - 2.0 * c, 0.0)
            for cm in rd.camadas:
                if cm.n <= 0:
                    continue
                r = ancoragem.verificar_positiva(
                    f"direção {d}, bordo {k + 1}, Ø{cm.phi:g}", cm.phi,
                    cm.area * razao, cm.area, disp, gancho, concreto, CA50)
                rd.ancoragens.append((k, cm.phi, r))
                if not r.atende:
                    res.avisos.append(("erro", f"direção {d}, bordo {k + 1}, "
                                       f"Ø{cm.phi:g}: {r.observacao}. "
                                       f"Alargue a viga de apoio."))
            embute.append(disp)
        comp = L_cm - t + sum(embute)
        pos.append(PosicaoNerv(
            num, f"Positiva das nervuras ∥ {d}", rd.n_barras * n_ner,
            rd.phi, "CA-50", comp,
            rd.n_barras * n_ner * comp / 100.0 * massa_linear(rd.phi),
            f"{n_ner} nervuras × {rd.n_barras} Ø{rd.phi:g}; "
            f"{rd.cobertura_barras}"))
        num += 1
        # negativas nos bordos engastados
        for k, sn in rd.neg.items():
            n_b, phi_b = rd.n_neg[k]
            lb_n = ancoragem.lb(concreto, CA50, phi_b)
            alc = max(rd.maciço.get(k, 0.0), 0.25 * L_cm * 0.5)
            comp_n = min(alc + max(1.5 * sn.d, lb_n), 0.5 * L_cm)
            pos.append(PosicaoNerv(
                num, f"Negativa no bordo {k + 1}", n_b * n_ner, phi_b,
                "CA-50", comp_n + (t - c),
                n_b * n_ner * (comp_n + t - c) / 100.0 * massa_linear(phi_b),
                f"{comp_n:.0f} cm no vão, mais o apoio"))
            num += 1
        if rd.estribos.startswith("estribos"):
            phi_e = rd.phi_est
            per = 2.0 * ((bw - 2.0 * c) + (h - 2.0 * c)) + 10.0
            qtd = (math.ceil(L_cm / rd.s_estribo) + 1) * n_ner
            pos.append(PosicaoNerv(
                num, f"Estribos das nervuras ∥ {d}", qtd, phi_e, "CA-50",
                per, qtd * per / 100.0 * massa_linear(phi_e),
                f"Ø{phi_e:g} c/{rd.s_estribo:.0f} ao longo de toda a nervura"))
            num += 1
    m = res.mesa
    for sentido, comp_b, vao in (("em x", l.ly * 100.0, l.lx * 100.0),
                                 ("em y", l.lx * 100.0, l.ly * 100.0)):
        qtd = math.ceil(vao / m["s"]) + 1
        pos.append(PosicaoNerv(
            num, f"Malha da mesa {sentido}", qtd, m["phi"], "CA-60",
            comp_b - 2.0 * c,
            qtd * (comp_b - 2.0 * c) / 100.0 * massa_linear(m["phi"]),
            f"Ø{m['phi']:g} c/{m['s']:.0f} no meio da mesa"))
        num += 1
    res.posicoes = pos
    lx, ly = l.lx, l.ly
    nx, ny = l.nx, l.ny
    hn = l.hn / 100.0
    vol_mesa = hf / 100.0 * lx * ly
    vol_ner = bw / 100.0 * hn * ((ny - 1) * lx + (nx - 1) * ly) \
        - (nx - 1) * (ny - 1) * (bw / 100.0) ** 2 * hn
    massa = sum(p.massa for p in pos)
    area = lx * ly
    res.quantitativo = dict(
        area=area, volume_concreto=vol_mesa + vol_ner,
        concreto_L_m2=(vol_mesa + vol_ner) / area * 1000.0,
        aco_kg=massa, aco_kg_m2=massa / area,
        n_nervuras_x=ny - 1, n_nervuras_y=nx - 1,
        peso_proprio=res.cargas["pp"]["total"])


# ---------------------------------------------------------------------------
# Verificações em tabela
# ---------------------------------------------------------------------------

def _montar_verificacoes(res, cfg) -> None:
    l = res.laje
    linhas = []
    av = res.avisos

    def add(item, local, sol, rest, ok, ref):
        linhas.append([item, local, sol, rest, "OK" if ok else "NÃO OK", ref])

    for d, rd in res.dirs.items():
        f = rd.flexao
        add("Flexão positiva", f"nervuras ∥ {d}", f"Md = {rd.md:.2f} kN·m",
            f"MRd = {f.mrd:.2f} kN·m ({f.armadura})", f.atende,
            "17.2 / 14.6.4.3")
        if not f.atende:
            av.append(("erro", f"Nervuras ∥ {d}: "
                       f"{f.erro or 'armadura positiva insuficiente'}."))
        for k, sn in rd.neg.items():
            add("Flexão negativa", f"bordo {k + 1}",
                f"Md = {rd.md_neg[k]:.2f} kN·m",
                f"MRd = {sn.mrd:.2f} kN·m ({sn.armadura})", sn.atende,
                "17.2")
            if not sn.atende:
                av.append(("erro", f"Bordo {k + 1}: "
                           f"{sn.erro or 'negativa insuficiente'}."))
        add("Cortante da nervura", f"∥ {d}, {rd.criterio_cortante}",
            f"VSd = {rd.v_sd:.2f} kN",
            f"VRd1 = {rd.v_rd1:.2f} kN; {rd.estribos}",
            rd.atende_cortante, "19.4.1 / 17.4.2")
        if not rd.atende_cortante:
            av.append(("erro", f"Nervuras ∥ {d}: cortante não fecha "
                       f"({rd.estribos}); VSd = {rd.v_sd:.2f} kN, VRd2 = "
                       f"{rd.v_rd2:.2f} kN -- aumente bw ou h."))
        add("Fissuração", f"nervuras ∥ {d}", f"wk = {rd.wk:.2f} mm",
            f"{rd.wk_limite:.2f} mm", rd.atende_fissuracao, "17.3.3.2")
        if not rd.atende_fissuracao:
            av.append(("erro", f"Nervuras ∥ {d}: wk = {rd.wk:.2f} mm passa "
                       f"de {rd.wk_limite:.2f} mm."))
        for k, phi, r in rd.ancoragens:
            add("Ancoragem", f"∥ {d}, bordo {k + 1}, Ø{phi:g}",
                f"lb,nec = {r.lb_nec:.1f} cm",
                f"disponível {r.disponivel:.1f} cm"
                + (f" + gancho {r.ponta_gancho:.0f} cm"
                   if r.com_gancho else ""), r.atende, "9.4.2")
    fl = res.flecha
    add("Flecha total", "centro do painel", f"{fl['total']:.2f} cm",
        f"{fl['limite']:.2f} cm (L/{cfg.divisor_flecha})", fl["atende"],
        "17.3.2 / Tab. 13.3")
    if not fl["atende"]:
        av.append(("erro", f"Flecha total de {fl['total']:.2f} cm passa de "
                   f"{fl['limite']:.2f} cm -- aumente a altura ou a mesa."))
    m = res.mesa
    if m["exigida"]:
        add("Flexão da mesa", f"painel {l.esp_x:.0f} × {l.esp_y:.0f}",
            f"m = {m['m']:.2f} kN·m/m",
            f"As = {m['As_adot']:.2f} cm²/m (Ø{m['phi']:g} c/{m['s']:.0f})",
            True, "13.2.4.2-b")
    add("Cortante da mesa", "no painel", f"VSd = {m['v']:.2f} kN/m",
        f"VRd1 = {m['v_rd1']:.2f} kN/m", m["v"] <= m["v_rd1"] + 1e-9,
        "19.4.1")
    if m["v"] > m["v_rd1"] + 1e-9:
        av.append(("erro", "Cortante da mesa passa de VRd1 -- aumente a mesa."))
    for d, lg in m["ligacao"].items():
        add("Cisalhamento mesa-nervura", f"∥ {d}",
            f"τ = {lg['tau']:.2f} MPa", f"≤ {lg['lim']:.2f} MPa "
            f"(Ast = {lg['a_st']:.2f} cm²/m)", lg["ok"], "Bocchi 3.3")
        if not lg["ok"]:
            av.append(("erro", f"Ligação mesa-nervura ∥ {d}: τ = "
                       f"{lg['tau']:.2f} MPa passa de {lg['lim']:.2f} MPa."))
    res.verificacoes = linhas
    for d, rd in res.dirs.items():
        for k, mac in rd.maciço.items():
            av.append(("obs", f"bordo {k + 1}: faixa maciça de {mac:.0f} cm "
                       f"junto ao engaste (o programa não a modela na "
                       f"grelha)."))
    av.append(("obs", f"esforços por {l.metodo}: placa (tabelas, 14.7.7) e "
               f"grelha (rigidez à torção {l.kt * 100:.0f} % da elástica, "
               f"flexão {l.kf * 100:.0f} %)."))
    if l.armadura_unica:
        av.append(("obs", "uma só armadura por direção, a da nervura mais "
                   "carregada; a tabela por nervura mostra o que cada uma "
                   "pediria."))
