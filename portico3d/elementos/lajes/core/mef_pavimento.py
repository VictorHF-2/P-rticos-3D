# -*- coding: utf-8 -*-
"""
mef_pavimento.py
Análise elástica do pavimento de lajes maciças por elementos finitos de placa
(``mef_placa.py``) e dimensionamento de Wood-Armer (``woodarmer.py``): o
**método alternativo** da R10 para os momentos de cálculo da laje armada em
cruz, ao lado do método das linhas de ruptura.

O que o método faz de diferente
-------------------------------
* **o pavimento é um modelo só.** As lajes são painéis de uma mesma malha;
  onde duas lajes dividem uma viga e a borda foi declarada de continuidade
  (engaste recíproco), os nós são **fundidos** -- a rotação é contínua e o
  momento negativo sai igual dos dois lados, sem compatibilização à parte
  nem grau de engastamento arbitrado (i = 1,5);
* **a viga é um apoio rígido** (``w = 0`` e rotação tangente nula). O
  engaste em elemento rígido (parede, viga de torção impedida) anula também a
  rotação normal. Não há pilares nem vigas deformáveis no modelo -- a mesma
  hipótese da laje apoiada em vigas que o programa sempre fez;
* **o momento volvente entra no cálculo.** Cada ponto da laje tem ``(Mx, My,
  Mxy)``; a armadura nas duas direções é dimensionada pelos momentos
  equivalentes de Wood-Armer, e o canto da laje apoiada, onde ``Mxy``
  é máximo, ganha armadura superior de canto.

Geometria e apoio
-----------------
O retângulo de cada painel é o da laje (vão livre) estendido, nos bordos
com apoio, de ``a_i = min(t_i/2 ; 0,3 h)`` -- o vão efetivo do item 14.7.2.2,
que é o que o método das charneiras também usa. Onde duas lajes dividem uma
viga, as duas bordas se encaixam na **linha de centro da viga** (média das
duas bordas estendidas); é a única acomodação que a malha única exige, e vale
poucos centímetros.

Hipóteses declaradas
--------------------
* **elástico, sem redistribuição**: o ELU é a análise elástica com a carga de
  cálculo. O limite de ``x/d`` da flexão passa a ser o de quem não redistribui
  momentos (0,45 até C50; 14.6.4.3), e não o ``x/d <= 0,25`` do regime
  rígido-plástico;
* **só a laje armada em cruz** recebe o resultado: a laje armada em uma
  direção (``b/a > 2``, balanço, apoio em dois bordos) fica com o método das
  faixas e entra na comparação; o MEF dela é calculado e mostrado;
* a armadura de cada direção é a do **pico** da laje (um valor por direção, e
  por bordo engastado: o máximo ao longo dele) -- conservador, como as
  tabelas;
* o momento negativo do bordo vem do **equilíbrio dos nós** (a reação de
  momento do apoio, ou a força interna do painel na viga contínua), e não da
  extrapolação dos pontos de Gauss, que subestima o engaste: numa placa
  quadrada engastada a extrapolação dava -23 % com elemento de 25 cm, a
  reação -1,4 %;
* as paredes entram como carga linear na posição lançada; a carga variável é
  uniforme na laje inteira -- a mesma simplificação do método das
  charneiras --, a menos que ``Config.mef_alternancia`` esteja ligada (R11):
  aí o pavimento é resolvido mais duas vezes com a sobrecarga em **xadrez**
  (as lajes pintadas em duas cores, como num tabuleiro, pelas bordas comuns;
  ``g`` em todas e ``q`` só nas de uma cor) e cada **positivo** fica com o
  maior dos três carregamentos. É o que Souza & Cunha (§3.4, eq. 3.21)
  pedem com q/g > 1,5: m = p'·m(contínua) + p''·m(apoiada), com p' = g +
  q/2 e p'' = q/2 -- a superposição que a malha faz sozinha. Negativos e
  cantos continuam da carga cheia (que os maximiza).
"""

from __future__ import annotations

import copy
import dataclasses
from dataclasses import dataclass, field

import numpy as np

from . import mef_placa as mp
from . import woodarmer as wa
from . import flexao as fx
from .modelo import Config, Laje, Pavimento, _continuidades_geometricas

#: Lado do painel (``mef_placa``) de cada face da planta.
LADO_DA_FACE = {"esquerda": "esq", "direita": "dir", "baixo": "baixo",
                "cima": "cima"}

#: Coeficiente de Poisson do concreto (8.2.9).
POISSON = 0.2


# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------

@dataclass
class CantoMEF:
    """Canto de uma laje, onde o volvente concentra a armadura superior."""

    laje: str
    bordos: tuple[int, int]
    x: float                        # m, posição do canto na planta
    y: float
    zona: float                     # m, lado do quadrado de canto
    m_topo: float = 0.0             # kN·m/m, Wood-Armer superior (máx.)
    m_base: float = 0.0             # kN·m/m, Wood-Armer inferior (máx.)
    mxy: float = 0.0                # kN·m/m, máx |Mxy| na zona
    exige: bool = True              # há armadura de canto a prever
    #: o canto é de laje apoiada: o vértice sai do pico de vão e de negativo
    na_zona: bool = False
    As: float = 0.0                 # cm²/m, em cada direção, face superior
    d: float = 0.0                  # cm, altura útil usada
    erro: str = ""
    massa: float = 0.0              # kg, estimativa (duas direções)

    @property
    def rotulo(self) -> str:
        return f"{self.laje}, bordos {self.bordos[0]} e {self.bordos[1]}"


@dataclass
class LajeMEF:
    """O que a análise por elementos finitos diz de uma laje."""

    nome: str
    em_cruz: bool
    #: positivos de Wood-Armer nas direções ``a`` e ``b`` (kN·m/m)
    ma: float = 0.0
    mb: float = 0.0
    #: os mesmos sem a parcela do volvente (máx. de Mx e My do centro)
    ma_sem_mxy: float = 0.0
    mb_sem_mxy: float = 0.0
    #: os adotados no dimensionamento, depois da redistribuição (R10)
    ma_adotado: float = 0.0
    mb_adotado: float = 0.0
    m_neg_adotado: dict = field(default_factory=dict)
    #: Wood-Armer superior normal ao bordo, máx. ao longo dele, só dos
    #: bordos com apoio -- o programa usa os dos engastados
    m_neg: dict = field(default_factory=dict)
    #: |momento normal| do equilíbrio, sem a parcela do volvente
    m_neg_sem_mxy: dict = field(default_factory=dict)
    mxy_max: float = 0.0
    cantos: list = field(default_factory=list)
    w_max: float = 0.0              # m, sob a carga de cálculo
    carga: float = 0.0              # kN, total aplicado
    p_d: float = 0.0                # kN/m², carga de cálculo na laje
    #: (R11) positivos da carga cheia, quando há alternância, e qual
    #: carregamento governou cada direção ("cheia", "xadrez 1", "xadrez 2")
    ma_cheia: float = 0.0
    mb_cheia: float = 0.0
    governa_a: str = "cheia"
    governa_b: str = "cheia"


@dataclass
class ResultadoMEF:
    resultado: mp.Resultado
    lajes: dict = field(default_factory=dict)
    paineis: list = field(default_factory=list)
    tamanho: float = 0.25
    k: float = 1.0
    mxyc: bool = False
    delta: float = 1.0
    zona_canto: float = 0.2
    avisos: list = field(default_factory=list)
    #: linhas da comparação com as linhas de ruptura (preenche
    #: ``aplicar``): ``(laje, item, charneiras, mef elástico, mef adotado,
    #: mef sem Mxy, em cruz)``
    comparativo: list = field(default_factory=list)
    #: volvente que o concreto resiste em cada laje (0 se desligado)
    mxyc_por_laje: dict = field(default_factory=dict)
    #: (R11) cor de cada laje no xadrez da sobrecarga (vazio sem alternância)
    cores: dict = field(default_factory=dict)

    @property
    def n_nos(self) -> int:
        return self.resultado.n_nos

    @property
    def n_elementos(self) -> int:
        return self.resultado.n_elementos

    def laje(self, nome: str) -> LajeMEF | None:
        return self.lajes.get(nome)


# ---------------------------------------------------------------------------
# Montagem dos painéis
# ---------------------------------------------------------------------------

def _a_i(bordo, h: float) -> float:
    """Acréscimo do apoio ao vão efetivo (14.7.2.2), m."""
    return min(bordo.t / 2.0, 0.3 * h) / 100.0


def _retangulos(macicas: list[Laje]) -> dict[str, list[float]]:
    """``nome -> [X0, X1, Y0, Y1]``: o vão efetivo de cada laje, com as
    bordas que dividem uma viga encaixadas na linha de centro dela."""
    ext: dict[str, list[float]] = {}
    for laje in macicas:
        x0, y0, x1, y1 = laje.retangulo
        r = {"X0": x0, "X1": x1, "Y0": y0, "Y1": y1}
        for face, chave, sinal in (("esquerda", "X0", -1.0),
                                   ("direita", "X1", 1.0),
                                   ("baixo", "Y0", -1.0),
                                   ("cima", "Y1", 1.0)):
            b = laje.bordos[laje.bordo_da_face(face) - 1]
            if b.vinculo != "livre":
                r[chave] += sinal * _a_i(b, laje.h)
        ext[laje.nome] = [r["X0"], r["X1"], r["Y0"], r["Y1"]]

    # bordas vizinhas formam um aglomerado, cuja coordenada é a média
    pai: dict = {}

    def achar(a):
        pai.setdefault(a, a)
        while pai[a] != a:
            pai[a] = pai[pai[a]]
            a = pai[a]
        return a

    def unir(a, b):
        ra, rb = achar(a), achar(b)
        if ra != rb:
            pai[rb] = ra

    chave_da_face = {"esquerda": "X0", "direita": "X1", "baixo": "Y0",
                     "cima": "Y1"}
    for i, la in enumerate(macicas):
        for lb in macicas[i + 1:]:
            for c in _continuidades_geometricas(la, lb, 0.40, 0.30):
                fa = la.face_do_bordo(c.bordo_a)
                fb = lb.face_do_bordo(c.bordo_b)
                unir((la.nome, chave_da_face[fa]),
                     (lb.nome, chave_da_face[fb]))
    indice = {"X0": 0, "X1": 1, "Y0": 2, "Y1": 3}
    grupos: dict = {}
    for (nome, chave) in list(pai):
        grupos.setdefault(achar((nome, chave)), []).append((nome, chave))
    for membros in grupos.values():
        media = float(np.mean([ext[n][indice[k]] for n, k in membros]))
        for n, k in membros:
            ext[n][indice[k]] = media

    # duas lajes que só se tocam num canto passam a se sobrepor por poucos
    # centímetros quando cada uma ganha o seu a_i: desfaz a extensão dos
    # lados que se enfrentam na dimensão de menor sobreposição
    limpo = {laje.nome: laje.retangulo for laje in macicas}
    for i, la in enumerate(macicas):
        for lb in macicas[i + 1:]:
            ea, eb = ext[la.nome], ext[lb.nome]
            dx = min(ea[1], eb[1]) - max(ea[0], eb[0])
            dy = min(ea[3], eb[3]) - max(ea[2], eb[2])
            if dx <= 1e-6 or dy <= 1e-6:
                continue
            ca, cb = limpo[la.nome], limpo[lb.nome]
            if dx <= dy:
                esq, dire = (la, lb) if ca[0] <= cb[0] else (lb, la)
                ext[esq.nome][1] = min(ext[esq.nome][1], limpo[esq.nome][2])
                ext[dire.nome][0] = max(ext[dire.nome][0],
                                        limpo[dire.nome][0])
            else:
                baixo, alto = (la, lb) if ca[1] <= cb[1] else (lb, la)
                ext[baixo.nome][3] = min(ext[baixo.nome][3],
                                         limpo[baixo.nome][3])
                ext[alto.nome][2] = max(ext[alto.nome][2],
                                        limpo[alto.nome][1])
    return ext


def _paineis(pav: Pavimento, macicas: list[Laje], cfg: Config
             ) -> tuple[list[mp.Painel], list[str]]:
    avisos: list[str] = []
    ext = _retangulos(macicas)
    E = pav.concreto.Ecs * 1000.0                       # MPa -> kN/m²
    paineis: list[mp.Painel] = []
    for laje in macicas:
        X0, X1, Y0, Y1 = ext[laje.nome]
        x0, y0, x1, y1 = laje.retangulo
        p = cfg.gamma_g * laje.g_superficial + cfg.gamma_q * laje.variavel
        bordos = {}
        for face, lado in LADO_DA_FACE.items():
            b = laje.bordos[laje.bordo_da_face(face) - 1]
            bordos[lado] = (b.vinculo, b.vizinha)
        lineares = []
        for par in laje.paredes:
            eixo = laje.direcao_global(par.direcao)    # onde a parede corre
            valor = cfg.gamma_g * par.carga
            if eixo == "Y":                            # x constante
                lo, larg = x0, x1 - x0
                coord = lo + (larg / 2.0 if par.posicao is None
                              else min(max(par.posicao, 0.0), larg))
                lineares.append(("x", coord, max(y0, Y0), min(y1, Y1),
                                 valor))
            else:
                lo, larg = y0, y1 - y0
                coord = lo + (larg / 2.0 if par.posicao is None
                              else min(max(par.posicao, 0.0), larg))
                lineares.append(("y", coord, max(x0, X0), min(x1, X1),
                                 valor))
        # cargas concentradas (R11): a área difundida até o plano médio
        concentradas = []
        for c in laje.cargas_concentradas:
            X, Y = laje.centro_da_carga(c)
            hx = (c.dx + laje.h) / 200.0
            hy = (c.dy + laje.h) / 200.0
            concentradas.append((
                max(X - hx, X0), min(X + hx, X1), max(Y - hy, Y0),
                min(Y + hy, Y1), cfg.gamma_g * c.g + cfg.gamma_q * c.q))
        paineis.append(mp.Painel(
            nome=laje.nome, x0=X0, y0=Y0, x1=X1, y1=Y1, h=laje.h / 100.0,
            E=E, nu=POISSON, p=p, bordos=bordos, lineares=lineares,
            concentradas=concentradas))
    # painéis que se sobrepõem depois do encaixe: erro de lançamento
    for i, a in enumerate(paineis):
        for b in paineis[i + 1:]:
            dx = min(a.x1, b.x1) - max(a.x0, b.x0)
            dy = min(a.y1, b.y1) - max(a.y0, b.y0)
            if dx > 1e-6 and dy > 1e-6:
                avisos.append(
                    f"As lajes {a.nome} e {b.nome} se sobrepõem na planta "
                    f"({dx:.2f} x {dy:.2f} m) depois de encaixar as bordas "
                    f"na linha de centro da viga: confira x, y e Lx, Ly.")
    return paineis, avisos


# ---------------------------------------------------------------------------
# Momentos ao longo de um bordo
# ---------------------------------------------------------------------------

_NOS_DO_LADO = {"esq": (0, 3), "dir": (1, 2), "baixo": (0, 1),
                "cima": (2, 3)}
_CANTOS_CEL = ((0, 0), (1, 0), (1, 1), (0, 1))


def _indice(linhas: np.ndarray, valor: float) -> int:
    return int(np.argmin(np.abs(linhas - valor)))


def momentos_de_borda(res: mp.Resultado, k: int, lado: str,
                      nodais: dict | None = None) -> list[dict]:
    """Momentos ao longo de um lado do painel ``k``, nó a nó.

    Cada item: ``s`` (m, ao longo do lado), ``m_hog`` (momento negativo
    normal ao lado, positivo = hogging, pelo **equilíbrio** do nó),
    ``mt`` (tangencial, sinal de vão), ``mxy``, e ``ponta`` (nó do canto).
    """
    nodais = nodais if nodais is not None else mp.momentos_nodais(res)
    p = res.paineis[k]
    gx, gy = res.x, res.y
    horizontal = lado in ("baixo", "cima")
    dof_normal = 2 if horizontal else 1
    sinal = -1.0 if lado in ("esq", "baixo") else 1.0
    if horizontal:
        j_borda = _indice(gy, p.y0 if lado == "baixo" else p.y1)
        i0, i1 = _indice(gx, p.x0), _indice(gx, p.x1)
        posicoes = [(i, j_borda) for i in range(i0, i1 + 1)]
        s = gx[i0:i1 + 1] - gx[i0]
    else:
        i_borda = _indice(gx, p.x0 if lado == "esq" else p.x1)
        j0, j1 = _indice(gy, p.y0), _indice(gy, p.y1)
        posicoes = [(i_borda, j) for j in range(j0, j1 + 1)]
        s = gy[j0:j1 + 1] - gy[j0]
    f: dict = {pos: 0.0 for pos in posicoes}
    idx_nos = _NOS_DO_LADO[lado]
    for (j, i), c in res.celulas.items():
        if c["painel"] != k:
            continue
        for n in idx_nos:
            di, dj = _CANTOS_CEL[n]
            pos = (i + di, j + dj)
            if pos in f:
                f[pos] += float(c["fe"][3 * n + dof_normal])
    saida = []
    for n, pos in enumerate(posicoes):
        meia_a = (s[n] - s[n - 1]) / 2.0 if n > 0 else 0.0
        meia_b = (s[n + 1] - s[n]) / 2.0 if n < len(s) - 1 else 0.0
        trib = meia_a + meia_b
        nod = nodais.get((pos[0], pos[1], k))
        if nod is None or trib <= 0.0:
            continue
        if horizontal:
            mt, mxy = float(nod[0]), float(nod[2])
        else:
            mt, mxy = float(nod[1]), float(nod[2])
        saida.append(dict(
            s=float(s[n]), m_hog=sinal * f[pos] / trib, mt=mt, mxy=mxy,
            ponta=(n == 0 or n == len(s) - 1)))
    return saida


# ---------------------------------------------------------------------------
# Análise
# ---------------------------------------------------------------------------

def _wa_celula(mc, k: float, mxyc: float) -> tuple[float, float, float,
                                                   float]:
    return wa.wood_armer(float(mc[0]), float(mc[1]), float(mc[2]), k, mxyc)


def _mxyc_do_ponto(laje: Laje, pav: Pavimento, usar: bool) -> float:
    if not usar:
        return 0.0
    d = laje.h - pav.ambiente.cobrimento_nominal - 0.5
    return wa.mxyc_nb1(laje.h, d, pav.concreto.fck)


#: Distância do canto, em metros, a que se amostra o momento do canto. É a
#: do centro do primeiro elemento da referência (Parsekian, 1996: elementos
#: de 0,18 m de lado). O volvente do canto de uma laje apoiada cresce até o
#: vértice e o valor do primeiro elemento depende do tamanho dele; amostrar
#: sempre à mesma distância, por interpolação dos centros, deixa o resultado
#: independente da malha -- que precisa ter elemento de até 0,20 m.
DISTANCIA_AMOSTRA_CANTO = 0.09


def _grade_do_painel(res: mp.Resultado, k: int):
    """``(xs, ys, M)``: centros das células do painel e o trio de momentos
    de cada uma, ``M[j, i]``."""
    celulas = [c for c in res.celulas.values() if c["painel"] == k]
    xs = np.array(sorted({round(c["xc"], 9) for c in celulas}))
    ys = np.array(sorted({round(c["yc"], 9) for c in celulas}))
    ix = {x: n for n, x in enumerate(xs)}
    iy = {y: n for n, y in enumerate(ys)}
    campo = np.zeros((len(ys), len(xs), 3))
    for c in celulas:
        campo[iy[round(c["yc"], 9)], ix[round(c["xc"], 9)]] = c["Mc"]
    return xs, ys, campo


def _amostrar(xs: np.ndarray, ys: np.ndarray, campo: np.ndarray, x: float,
              y: float) -> np.ndarray:
    """Interpolação bilinear entre os centros das células (linear também
    fora deles, perto da borda)."""
    def pesos(v: float, a: np.ndarray) -> tuple[int, int, float]:
        if len(a) == 1:
            return 0, 0, 0.0
        k = int(np.clip(np.searchsorted(a, v) - 1, 0, len(a) - 2))
        return k, k + 1, (v - a[k]) / (a[k + 1] - a[k])
    i0, i1, tx = pesos(x, xs)
    j0, j1, ty = pesos(y, ys)
    return ((1 - tx) * (1 - ty) * campo[j0, i0] + tx * (1 - ty) * campo[j0, i1]
            + (1 - tx) * ty * campo[j1, i0] + tx * ty * campo[j1, i1])


#: Cantos de cada lado do painel, na ordem em que o lado é percorrido:
#: ``lado -> (canto do início, canto do fim)``, com o canto escrito como
#: ``(lado horizontal, lado vertical)``.
_CANTOS_DO_LADO = {
    "esq": (("baixo", "esq"), ("cima", "esq")),
    "dir": (("baixo", "dir"), ("cima", "dir")),
    "baixo": (("baixo", "esq"), ("baixo", "dir")),
    "cima": (("cima", "esq"), ("cima", "dir")),
}


def cores_xadrez(macicas: list[Laje]) -> tuple[dict[str, int], bool]:
    """Pinta as lajes em duas cores pelas bordas comuns (busca em largura):
    vizinhas ficam de cores diferentes, como num tabuleiro. Devolve
    ``(cores, conflito)`` -- ``conflito`` quando um ciclo ímpar de
    vizinhança (três lajes que se tocam duas a duas) impede o xadrez
    perfeito; aí duas vizinhas ficam da mesma cor."""
    viz: dict[str, set] = {laje.nome: set() for laje in macicas}
    for i, la in enumerate(macicas):
        for lb in macicas[i + 1:]:
            if _continuidades_geometricas(la, lb, 0.40, 0.30):
                viz[la.nome].add(lb.nome)
                viz[lb.nome].add(la.nome)
    cores: dict[str, int] = {}
    conflito = False
    for laje in macicas:
        if laje.nome in cores:
            continue
        cores[laje.nome] = 0
        fila = [laje.nome]
        while fila:
            atual = fila.pop(0)
            for v in sorted(viz[atual]):
                if v not in cores:
                    cores[v] = 1 - cores[atual]
                    fila.append(v)
                elif cores[v] == cores[atual]:
                    conflito = True
    return cores, conflito


def analisar(pav: Pavimento, esforcos: dict, cfg: Config) -> ResultadoMEF:
    """Resolve o pavimento e extrai, de cada laje maciça, os momentos de
    Wood-Armer. Não altera ``esforcos`` -- ver :func:`aplicar`.

    Os **cantos** de laje apoiada (os dois bordos com apoio e não ambos
    engastados) saem do pico de vão: o volvente deles é máximo e cresce com
    o refino da malha, e a armadura de canto é quem o resiste. Por isso as
    células da zona de canto (``mef_zona_canto`` do menor vão) ficam fora do
    pico de vão, e o canto é dimensionado à parte, no momento amostrado a
    ``DISTANCIA_AMOSTRA_CANTO`` do vértice. O pico do negativo de cada
    bordo também deixa de fora as pontas, até a mesma zona.
    """
    macicas = pav.lajes_macicas
    paineis, avisos = _paineis(pav, macicas, cfg)
    res = mp.resolver(paineis, cfg.mef_elemento)
    nodais = mp.momentos_nodais(res)
    out = ResultadoMEF(resultado=res, paineis=paineis,
                       tamanho=cfg.mef_elemento, k=cfg.mef_k,
                       mxyc=cfg.mef_mxyc, delta=cfg.mef_delta,
                       zona_canto=cfg.mef_zona_canto,
                       avisos=avisos)
    if cfg.mef_elemento > 0.201:
        out.avisos.append(
            f"Elemento de {cfg.mef_elemento * 100:.0f} cm: acima de 20 cm o "
            f"momento do canto não é mais amostrado com fidelidade e os "
            f"negativos podem sair subestimados; use até 20 cm.")
    nomes = {p.nome: k for k, p in enumerate(paineis)}

    # -- alternância da sobrecarga (R11): dois xadrezes ----------------------
    casos = [("cheia", res)]
    if getattr(cfg, "mef_alternancia", False) and len(macicas) > 1 and \
            any(laje.variavel > 0.0 for laje in macicas):
        cores, conflito = cores_xadrez(macicas)
        out.cores = cores
        if len(set(cores.values())) > 1:
            por_nome = {laje.nome: laje for laje in macicas}
            for cor in (0, 1):
                alt = [dataclasses.replace(
                    p, p=cfg.gamma_g * por_nome[p.nome].g_superficial
                    + (cfg.gamma_q * por_nome[p.nome].variavel
                       if cores[p.nome] == cor else 0.0))
                    for p in paineis]
                casos.append((f"xadrez {cor + 1}",
                              mp.resolver(alt, cfg.mef_elemento)))
        if conflito:
            out.avisos.append(
                "Alternância da sobrecarga: a vizinhança das lajes tem um "
                "ciclo ímpar (três lajes que se tocam duas a duas) e o "
                "xadrez não é perfeito -- duas vizinhas ficaram carregadas "
                "juntas num dos casos.")

    for laje in macicas:
        k = nomes[laje.nome]
        pn = paineis[k]
        esf = esforcos.get(laje.nome)
        em_cruz = bool(esf is not None and esf.classificacao.em_cruz)
        mxyc = _mxyc_do_ponto(laje, pav, cfg.mef_mxyc)
        out.mxyc_por_laje[laje.nome] = mxyc
        eixo_a = laje.direcao_global("a")          # "X" ou "Y"
        lm = LajeMEF(nome=laje.nome, em_cruz=em_cruz, p_d=pn.p,
                     w_max=res.w_max.get(laje.nome, 0.0),
                     carga=res.carga_total.get(laje.nome, 0.0))
        xs, ys, campo = _grade_do_painel(res, k)
        lmin = min(pn.x1 - pn.x0, pn.y1 - pn.y0)
        zona = cfg.mef_zona_canto * lmin
        d_am = min(DISTANCIA_AMOSTRA_CANTO, lmin / 4.0)

        # -- cantos: a zona e o momento amostrado ------------------------------
        cantos = {}                  # (lado_h, lado_v) -> CantoMEF
        for (b_h, b_v, face_h, face_v, cx, cy) in _CANTOS(laje, pn):
            bh, bv = laje.bordos[b_h - 1], laje.bordos[b_v - 1]
            if bh.vinculo == "livre" or bv.vinculo == "livre":
                continue
            sx = cx + (d_am if face_v == "esquerda" else -d_am)
            sy = cy + (d_am if face_h == "baixo" else -d_am)
            mc = _amostrar(xs, ys, campo, sx, sy)
            ix, iy, tx, ty = _wa_celula(mc, cfg.mef_k, mxyc)
            ambos_engastados = bh.vinculo == "engastado" and \
                bv.vinculo == "engastado"
            canto = CantoMEF(
                laje=laje.nome, bordos=(b_h, b_v), x=cx, y=cy, zona=zona,
                m_topo=max(tx, ty), m_base=max(ix, iy),
                mxy=abs(float(mc[2])),
                exige=not ambos_engastados and max(tx, ty) > 0.0)
            canto.na_zona = not ambos_engastados
            cantos[(LADO_DA_FACE[face_h], LADO_DA_FACE[face_v])] = canto
            lm.cantos.append(canto)

        def na_zona_de_canto(xc: float, yc: float) -> bool:
            return any(c.na_zona and abs(xc - c.x) <= zona
                       and abs(yc - c.y) <= zona for c in cantos.values())

        # -- positivos: máximo de Wood-Armer inferior fora dos cantos, na
        # envoltória dos carregamentos (só a carga cheia sem alternância) ----
        gx_caso = gy_caso = "cheia"
        bx = by = mx_max = my_max = mxy_max = 0.0
        for nome_caso, r_caso in casos:
            cel_do_painel = [c for c in r_caso.celulas.values()
                             if c["painel"] == k]
            usadas = [c for c in cel_do_painel
                      if not na_zona_de_canto(c["xc"], c["yc"])] \
                or cel_do_painel
            for c in usadas:
                inf_x, inf_y, _sx, _sy = _wa_celula(c["Mc"], cfg.mef_k,
                                                    mxyc)
                if inf_x > bx + 1e-9:
                    bx, gx_caso = inf_x, nome_caso
                if inf_y > by + 1e-9:
                    by, gy_caso = inf_y, nome_caso
                mx_max = max(mx_max, float(c["Mc"][0]))
                my_max = max(my_max, float(c["Mc"][1]))
                if nome_caso == "cheia":
                    mxy_max = max(mxy_max, abs(float(c["Mc"][2])))
            if nome_caso == "cheia":
                cheia_x, cheia_y = bx, by
        lm.mxy_max = mxy_max
        if eixo_a == "X":
            lm.ma, lm.mb, lm.ma_sem_mxy, lm.mb_sem_mxy = bx, by, mx_max, \
                my_max
            lm.ma_cheia, lm.mb_cheia = cheia_x, cheia_y
            lm.governa_a, lm.governa_b = gx_caso, gy_caso
        else:
            lm.ma, lm.mb, lm.ma_sem_mxy, lm.mb_sem_mxy = by, bx, my_max, \
                mx_max
            lm.ma_cheia, lm.mb_cheia = cheia_y, cheia_x
            lm.governa_a, lm.governa_b = gy_caso, gx_caso

        # -- negativos: máximo ao longo de cada bordo com apoio, sem as pontas
        # que caem na zona de um canto -----------------------------------------
        for bordo in (1, 2, 3, 4):
            b = laje.bordos[bordo - 1]
            if b.vinculo == "livre":
                continue
            lado = LADO_DA_FACE[laje.face_do_bordo(bordo)]
            horizontal = lado in ("baixo", "cima")
            perfil = momentos_de_borda(res, k, lado, nodais)
            comp = perfil[-1]["s"] if perfil else 0.0
            # as pontas do bordo, até a zona de canto, ficam fora do pico: ali
            # o volvente e a reação concentram-se nos vértices e nas
            # junções de laje (singularidades que crescem com o refino), e o
            # pico do negativo -- no meio do bordo -- é que dimensiona a
            # armadura corrida
            lo, hi = (zona, comp - zona) if comp > 2.0 * zona else (0.0, comp)
            nos = [no for no in perfil
                   if not no["ponta"] and lo - 1e-9 <= no["s"] <= hi + 1e-9]
            if not nos:
                nos = [no for no in perfil if not no["ponta"]]
            topo = sem = 0.0
            for no in nos:
                m_hog = no["m_hog"]
                # normal e tangente na ordem (x, y) da planta
                mn, mt = -m_hog, no["mt"]
                mx_, my_ = (mt, mn) if horizontal else (mn, mt)
                _ix, _iy, sx, sy = wa.wood_armer(mx_, my_, no["mxy"],
                                                 cfg.mef_k, mxyc)
                topo = max(topo, sy if horizontal else sx)
                sem = max(sem, m_hog)
            lm.m_neg[bordo] = topo
            lm.m_neg_sem_mxy[bordo] = sem
        out.lajes[laje.nome] = lm
    return out


def dimensionar_cantos(out: ResultadoMEF, pav: Pavimento) -> None:
    """Armadura superior de canto: a flexão do momento superior de
    Wood-Armer do canto, nas duas direções, e uma estimativa de massa.

    As duas direções cruzam-se no canto, e a de baixo tem ``d`` menor por
    uma bitola: usa-se ``d`` da camada de cima menos 1 cm nas duas -- a
    favor da segurança. A massa estima as barras da zona nas duas
    direções (zona x zona, ``As`` por metro), sem ancoragem; é número de
    ordem de grandeza, e a armadura não é detalhada em barras.
    """
    cfg = pav.config
    for nome, lm in out.lajes.items():
        laje = pav.laje(nome)
        if laje is None:
            continue
        for c in lm.cantos:
            if not c.exige:
                continue
            c_sup = pav.ambiente.cobrimento_superior(
                cfg.bitola_minima_negativa)
            d = fx.altura_util(laje.h, c_sup, "superior") - 1.0
            f = fx.dimensionar_secao(c.m_topo, laje.h, d, c_sup,
                                     pav.concreto, pav.aco, "negativa",
                                     f"canto {c.rotulo}", True)
            c.As, c.d, c.erro = f.As, d, f.erro
            c.massa = 2.0 * f.As * 1e-4 * c.zona * c.zona * 7850.0


def _CANTOS(laje: Laje, pn: mp.Painel):
    """Os quatro cantos do painel: ``(bordo horizontal, bordo vertical,
    face, face, x, y)`` -- ``bordo horizontal`` é o que corre em x."""
    saida = []
    for fh, yy in (("baixo", pn.y0), ("cima", pn.y1)):
        for fv, xx in (("esquerda", pn.x0), ("direita", pn.x1)):
            saida.append((laje.bordo_da_face(fh), laje.bordo_da_face(fv),
                          fh, fv, xx, yy))
    return saida


def aplicar(pav: Pavimento, esforcos: dict, cfg: Config) -> ResultadoMEF:
    """Roda a análise e **substitui** os momentos de cálculo das lajes em
    cruz (``ma``, ``mb`` e ``m_neg`` dos bordos engastados) pelos de
    Wood-Armer. As demais lajes ficam com o método das faixas; o ELS segue
    pelas tabelas elásticas. Preenche ``comparativo`` com as linhas de
    ruptura de antes."""
    antes = {n: copy.deepcopy(e) for n, e in esforcos.items()}
    out = analisar(pav, esforcos, cfg)
    for nome, esf in esforcos.items():
        lm = out.lajes.get(nome)
        if lm is None:
            continue
        ant = antes[nome]
        if lm.em_cruz:
            laje = pav.laje(nome)
            delta = min(max(cfg.mef_delta, 0.75), 1.0)
            ma, mb = lm.ma, lm.mb
            neg = {b: lm.m_neg[b] for b in esf.m_neg if b in lm.m_neg}
            lm.ma_adotado, lm.mb_adotado = ma, mb
            if delta < 1.0:
                # redistribuição simplificada: cada negativo cai a delta de
                # seu valor e o positivo da faixa sobe ao equilíbrio,
                # (1 - delta) (m'1 + m'2) / 2
                for direcao, (b1, b2) in (("a", (2, 4)), ("b", (1, 3))):
                    soma = sum(neg.get(b, 0.0) for b in (b1, b2))
                    acrescimo = (1.0 - delta) * soma / 2.0
                    if direcao == "a":
                        ma += acrescimo
                    else:
                        mb += acrescimo
                neg = {b: m * delta for b, m in neg.items()}
            esf.ma, esf.mb = ma, mb
            lm.ma_adotado, lm.mb_adotado = ma, mb
            lm.m_neg_adotado = dict(neg)
            for bordo, valor in neg.items():
                esf.m_neg[bordo] = valor
            esf.metodo = "mef"
            esf.delta_mef = delta
            for direcao, gov, cheia, env in (
                    ("a", lm.governa_a, lm.ma_cheia, lm.ma),
                    ("b", lm.governa_b, lm.mb_cheia, lm.mb)):
                if out.cores and gov != "cheia" and cheia > 1e-9:
                    esf.avisos.append(
                        f"{nome}: o positivo da direção {direcao} veio da "
                        f"sobrecarga alternada ({gov}): {env:.2f} contra "
                        f"{cheia:.2f} kN·m/m da carga cheia "
                        f"(+{(env / cheia - 1) * 100:.0f} %).")
            esf.avisos.append(
                f"{nome}: momentos de cálculo por elementos finitos de "
                f"placa (elemento de {cfg.mef_elemento * 100:.0f} cm) e "
                f"Wood-Armer, com a carga de cálculo "
                f"{lm.p_d:.2f} kN/m²; "
                + ("sem redistribuição" if delta >= 1.0 else
                   f"com redistribuição δ = {delta:.2f}")
                + f" (x/d <= "
                f"{pav.concreto.x_sobre_d_limite_redistribuido(delta):.2f}"
                f", 14.6.4.3).")
        else:
            esf.avisos.append(
                f"{nome}: laje armada em uma direção -- mantido o método "
                f"das faixas; a análise por elementos finitos aparece só "
                f"na comparação.")
        ado_a = lm.ma_adotado if lm.em_cruz else lm.ma
        ado_b = lm.mb_adotado if lm.em_cruz else lm.mb
        out.comparativo.append((nome, "m_a (positivo, direção a)",
                                ant.ma, lm.ma, ado_a, lm.ma_sem_mxy,
                                lm.em_cruz))
        out.comparativo.append((nome, "m_b (positivo, direção b)",
                                ant.mb, lm.mb, ado_b, lm.mb_sem_mxy,
                                lm.em_cruz))
        for bordo in sorted(lm.m_neg):
            if pav.laje(nome).bordos[bordo - 1].vinculo != "engastado":
                continue
            out.comparativo.append((
                nome, f"m'{bordo} (negativo, bordo {bordo})",
                ant.m_neg.get(bordo, 0.0), lm.m_neg[bordo],
                lm.m_neg_adotado.get(bordo, lm.m_neg[bordo])
                if lm.em_cruz else lm.m_neg[bordo],
                lm.m_neg_sem_mxy.get(bordo, 0.0), lm.em_cruz))
    return out
