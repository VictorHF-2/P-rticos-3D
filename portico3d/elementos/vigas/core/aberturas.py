# -*- coding: utf-8 -*-
"""
aberturas.py
Furos e aberturas na alma da viga (NBR 6118:2026, 13.2.5 e 21.3), lidos
sobre o :class:`ResultadoViga` do motor -- nada aqui altera o
dimensionamento da viga. O que é novo (barras dos banzos, estribos dos
banzos, suspensão, pele interrompida) entra como **posições novas**, e o que
o furo tira da viga (estribos dentro da abertura e na faixa da suspensão,
barras de pele cortadas) entra como **ajuste da contagem** das posições do
motor. Portado do Vigas Pré-Moldadas (``core/aberturas.py``, validado contra
o exercício de aberturas do prof. Fabricio Bolina, UFRGS), trocando o
referencial da peça pré-moldada (ponta do dente, dentes Gerber) pelo deste
programa: x em m a partir do nó 0 da viga, viga contínua com vários tramos e
seção por trecho.

Dois tipos:

* **horizontal** (atravessa a largura, 13.2.5.1), retangular ou circular:
  distância às faces >= max(5 cm, 2c); as quatro condições de dispensa
  a)--d) uma a uma; se não dispensado, o roteiro de Bolina: a viga vira um
  quadro de dois banzos no trecho do furo,

      N_c = N_t = M_d / z           z = d - λx/2 da região de flexão
      V_c = 0,80 V_d                V_t = 0,20 V_d
      M_c = V_c · L/2               M_t = V_t · L/2

  cada banzo dimensionado à flexo-compressão (o comprimido) ou à
  flexo-tração (o tracionado) por equilíbrio da seção retangular com
  armadura simétrica (bloco retangular λx, α_c·η_c·f_cd, 17.2.2), os
  estribos de cada banzo pelo Modelo I (17.4.2.2), compatibilizados no
  menor espaçamento, a suspensão V_c/f_yd em h/4 dos dois lados e a
  ancoragem das barras novas a partir do fim da suspensão (9.4.2.4).
  Numa viga contínua o trecho do furo pode ter momento dos dois sinais na
  envoltória (alternância de carga): os dois casos são calculados, e cada
  banzo fica com a armadura e o estribo do caso pior;
* **vertical** (atravessa a altura, 21.3.3), circular: diâmetro <= b/3,
  distância às faces laterais, conjunto alinhado com espaçamento >=
  max(5 cm, φ) e estribo em cada intervalo, e a seção reduzida (b − φ) à
  flexão e ao cisalhamento.

Unidades: cm, kN, kN·cm internamente; M de entrada e saída em kN·m; x ao
longo da viga em m (dados) e em cm (geometria do furo, ``x0``/``x1``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from . import avisos as av
from . import detalhamento as det
from . import ganchos as gk
from .aberturas_modelo import (CRITERIO_CENTRO, CRITERIO_PIOR_TRECHO,
                               invalidas)
from .ancoragem import boa_aderencia, fbd as _fbd
from .materiais import area_barra, interpola_rho_min
from .modelo import Secao

#: Repartição do cortante entre os banzos (Bolina): o comprimido leva 80 %.
FRACAO_V_COMPRIMIDO = 0.80

#: Módulo de elasticidade do aço, kN/cm² (8.3.5).
ES = 21000.0

#: Alongamento limite do aço no ELU (domínios 1 e 2).
EPS_SU = 0.010

#: Bitolas para as barras novas dos banzos, mm.
BITOLAS_BANZO = (8.0, 10.0, 12.5, 16.0, 20.0, 25.0)

#: Lados de 13.2.5.1 b) para a dispensa.
LADO_MAX_RETANGULAR = 12.0
DIAMETRO_MAX_CIRCULAR = 12.5

#: Momento do sinal secundário abaixo desta fração do principal não abre um
#: segundo caso de banzos (ruído da envoltória).
FRACAO_SEGUNDO_CASO = 0.01

#: Segmentos para aproximar o círculo nos desenhos.
SEGMENTOS_CIRCULO = 40


# ---------------------------------------------------------------------------
# Funções de cálculo puras (o autoteste chama estas com os números do
# gabarito)
# ---------------------------------------------------------------------------

def braco_alavanca(Md_kNm: float, b: float, d: float, sigma_cd: float,
                   lam: float = 0.8) -> tuple[float, float]:
    """(x, z) da flexão simples da seção bruta, cm: bloco retangular de
    altura λx e tensão ``sigma_cd`` (kN/cm²), z = d − λx/2."""
    Md = abs(Md_kNm) * 100.0
    disc = d * d - 2.0 * Md / (b * sigma_cd)
    if disc < 0:
        raise ValueError("momento acima da capacidade da seção bruta")
    y = d - math.sqrt(disc)
    return y / lam, d - y / 2.0


def esforcos_banzos(M_kNm: float, V_kN: float, z: float,
                    L: float) -> dict:
    """Esforços nos banzos (Bolina): N = M/z, V_c = 0,8 V, V_t = 0,2 V,
    M = V·L/2. ``z`` e ``L`` em cm; momentos de saída em kN·m."""
    N = abs(M_kNm) * 100.0 / z
    Vc = FRACAO_V_COMPRIMIDO * abs(V_kN)
    Vt = (1.0 - FRACAO_V_COMPRIMIDO) * abs(V_kN)
    return {"N": N, "Vc": Vc, "Vt": Vt, "Mc": Vc * L / 2.0 / 100.0,
            "Mt": Vt * L / 2.0 / 100.0}


def _perfil(t: float, h: float, dl: float, eps_cu: float, eps_c2: float):
    """Deformação no topo e na base (compressão positiva) do perfil
    último de parâmetro ``t`` em [0, 5], crescente em N: domínio 1, 2,
    3-4, 4a e 5."""
    y2 = h - dl
    if t <= 1.0:          # domínio 1: aço de baixo a -10 ‰
        et, es = -EPS_SU * (1.0 - t), -EPS_SU
        eb = et + (es - et) * h / y2
    elif t <= 2.0:        # domínio 2
        et, es = eps_cu * (t - 1.0), -EPS_SU
        eb = et + (es - et) * h / y2
    elif t <= 3.0:        # domínios 3 e 4
        et, es = eps_cu, -EPS_SU * (3.0 - t)
        eb = et + (es - et) * h / y2
    elif t <= 4.0:        # domínio 4a: base de (aço a zero) a zero
        et = eps_cu
        eb0 = et - et * h / y2
        eb = eb0 * (4.0 - t)
    else:                 # domínio 5, polo C
        yc = h * (1.0 - eps_c2 / eps_cu)
        eb = eps_c2 * (t - 4.0)
        et = eps_c2 + (eps_c2 - eb) * yc / (h - yc)
    return et, eb


def _esforcos_internos(t, As_face, b, h, dl, conc, fyd):
    """(N, M) resistentes, kN e kN·cm (M em torno do meio da altura,
    positivo comprimindo o topo)."""
    et, eb = _perfil(t, h, dl, conc.eps_cu, conc.eps_c2)

    def eps(y):
        return et + (eb - et) * y / h

    if et <= 0.0 and eb <= 0.0:
        bloco = 0.0
    elif eb >= 0.0:
        bloco = h
    else:
        x = h * et / (et - eb)
        bloco = min(conc.lambda_ * x, h)
    Fc = conc.sigma_cd * b * bloco
    s1 = max(-fyd, min(fyd, ES * eps(dl)))
    s2 = max(-fyd, min(fyd, ES * eps(h - dl)))
    N = Fc + As_face * (s1 + s2)
    M = Fc * (h / 2.0 - bloco / 2.0) + As_face * (s1 - s2) * (h / 2.0 - dl)
    return N, M


def momento_resistente(N_kN: float, As_face: float, b: float, h: float,
                       dl: float, conc, aco) -> float | None:
    """M_Rd, kN·m, da seção b x h com ``As_face`` em cada face (a ``dl`` da
    face), sob a força normal ``N_kN`` (compressão positiva). ``None``
    quando a seção não equilibra N."""
    fyd = aco.fyd_kNcm2
    n0, _ = _esforcos_internos(0.0, As_face, b, h, dl, conc, fyd)
    n5, _ = _esforcos_internos(5.0, As_face, b, h, dl, conc, fyd)
    if not n0 - 1e-9 <= N_kN <= n5 + 1e-9:
        return None
    a, c = 0.0, 5.0
    for _ in range(80):
        m = (a + c) / 2.0
        if _esforcos_internos(m, As_face, b, h, dl, conc, fyd)[0] < N_kN:
            a = m
        else:
            c = m
    return _esforcos_internos((a + c) / 2.0, As_face, b, h, dl, conc,
                              fyd)[1] / 100.0


def armadura_simetrica(N_kN: float, M_kNm: float, b: float, h: float,
                       dl: float, conc, aco) -> float | None:
    """Armadura total (as duas faces), cm², da seção retangular com
    armadura simétrica sob (N, M) -- por equilíbrio e compatibilidade, o
    que o ábaco de flexo-compressão/tração faz graficamente. ``None`` se
    nem 4 % de A_c resolve."""
    M = abs(M_kNm)

    def atende(as_face):
        mr = momento_resistente(N_kN, as_face, b, h, dl, conc, aco)
        return mr is not None and mr >= M - 1e-9

    if atende(0.0):
        return 0.0
    hi = 0.02 * b * h
    if not atende(hi):
        return None
    lo = 0.0
    for _ in range(60):
        m = (lo + hi) / 2.0
        if atende(m):
            hi = m
        else:
            lo = m
    return 2.0 * hi


def arredondar_espacamento(s: float) -> float:
    """Espaçamento de obra, cm: múltiplo de 2,5 cm a partir de 10 cm
    (16,2 -> 15, 10,2 -> 10, como no gabarito), centímetro inteiro abaixo,
    nunca menos que 5 cm."""
    if s >= 10.0 - 1e-9:
        return math.floor(s / 2.5 + 1e-9) * 2.5
    return max(5.0, math.floor(s + 1e-9))


def estribos_banzo(V_kN: float, b: float, d: float, conc, aco_estribo,
                   phi_t: float, n_ramos: int = 2,
                   vc_nulo: bool = False) -> dict:
    """Modelo I (17.4.2.2) num banzo b x h de altura útil d. ``vc_nulo``:
    banzo tracionado com a linha neutra fora da seção (V_c = 0)."""
    fcd = conc.fcd / 10.0
    VRd2 = 0.27 * conc.alfa_v2 * fcd * b * d
    Vc0 = 0.6 * conc.fctd_kNcm2 * b * d
    Vc = 0.0 if vc_nulo else Vc0
    fywd = min(aco_estribo.fyd_kNcm2, 43.5)
    asw = max(V_kN - Vc, 0.0) / (0.9 * d * fywd) * 100.0       # cm²/m
    asw_min = 0.2 * conc.fctm / aco_estribo.fyk * b * 100.0
    asw_nec = max(asw, asw_min)
    razao = V_kN / VRd2 if VRd2 > 0 else 9.9
    s_max = min(0.6 * d, 30.0) if razao <= 0.67 else min(0.3 * d, 20.0)
    s_area = n_ramos * area_barra(phi_t) / asw_nec * 100.0
    s = arredondar_espacamento(min(s_area, s_max))
    return {"VRd2": VRd2, "Vc0": Vc0, "Vc": Vc, "asw": asw,
            "asw_min": asw_min, "asw_nec": asw_nec, "razao": razao,
            "s_max": s_max, "s_area": s_area, "s": s,
            "biela_ok": V_kN <= VRd2 + 1e-9, "phi": phi_t,
            "n_ramos": n_ramos}


def suspensao(V_kN: float, aco_estribo, phi_t: float,
              n_ramos: int = 2) -> dict:
    """Suspensão de cada lado da abertura: A = V_c / f_yd, em estribos
    de ``n_ramos`` ramos (no mínimo 2 estribos)."""
    fywd = min(aco_estribo.fyd_kNcm2, 43.5)
    A = abs(V_kN) / fywd
    n = max(2, int(math.ceil(A / (n_ramos * area_barra(phi_t)) - 1e-9)))
    return {"A": A, "n": n, "phi": phi_t, "n_ramos": n_ramos,
            "A_ef": n * n_ramos * area_barra(phi_t)}


def ancoragem_basica(phi: float, conc, aco, boa: bool = True) -> dict:
    """l_b = (φ/4)·f_yd/f_bd >= 25 φ (9.4.2.4), f_bd = η1·η2·η3·f_ctd;
    adotado arredondado para cima em múltiplos de 5 cm."""
    f = _fbd(conc, aco, phi, boa)
    lb = max(phi / 40.0 * aco.fyd_kNcm2 / f, 2.5 * phi)
    return {"phi": phi, "boa": boa, "eta2": 1.0 if boa else 0.7,
            "fbd": f * 10.0, "lb": lb,
            "lb_adot": math.ceil(lb / 5.0 - 1e-9) * 5.0}


def escolher_barras(A: float, n: int, b: float, cob: float, phi_t: float,
                    d_agregado: float, ocupadas: int = 0
                    ) -> tuple[int, float]:
    """(n, φ) de barras novas para a área ``A``: ``n`` barras (>= 2) da
    menor bitola que dá conta e cabe na camada com as ``ocupadas``."""
    n = max(2, n)
    secao = Secao(bw=b, h=100.0, tipo="retangular")
    for k in (n, n + 1, n + 2):
        for phi in BITOLAS_BANZO:
            if k * area_barra(phi) >= A - 1e-9 and det.barras_por_camada(
                    secao, phi, cob, phi_t, d_agregado) >= k + ocupadas:
                return k, phi
    phi = BITOLAS_BANZO[-1]
    return max(n, int(math.ceil(A / area_barra(phi)))), phi


# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------

@dataclass
class Linha:
    """Uma linha da tabela da abertura."""

    grandeza: str
    valor: str
    unidade: str = ""
    limite: str = ""
    ok: bool | None = None          # None = informativa
    referencia: str = ""


@dataclass
class Banzo:
    nome: str                       # "superior" / "inferior"
    comprimido: bool
    h: float
    b: float
    d_linha: float
    d: float
    N: float                        # kN (compressão positiva)
    M: float                        # kN·m
    V: float                        # kN
    As_calc: float
    As_min: float
    criterio_min: str
    As_face: float
    #: face do banzo junto à face da viga: (n, φ, A) existentes e (n, φ)
    #: novas
    face_viga_exist: tuple[int, float, float]
    face_viga_nova: tuple[int, float] | None
    #: face do banzo junto ao furo: barras novas
    face_furo: tuple[int, float]
    estribos: dict
    ln_fora: bool
    ancoragem_furo: dict | None = None
    ancoragem_viga: dict | None = None
    #: sinal do momento do caso que gerou este banzo
    caso: str = ""


@dataclass
class ResultadoAbertura:
    indice: int
    abertura: object
    nome: str
    #: "dispensa", "banzos", "bielas", "vertical" ou "inválida"
    modelo: str
    linhas: list[Linha] = field(default_factory=list)
    esforcos: dict = field(default_factory=dict)
    banzos: list[Banzo] = field(default_factory=list)
    #: os banzos de cada caso de momento (um só, ou M > 0 e M < 0)
    casos: list[list[Banzo]] = field(default_factory=list)
    s_compatibilizado: float = 0.0
    suspensao: dict | None = None
    posicoes: list = field(default_factory=list)
    #: tudo o que se desenha deste furo (cm; z negativo a partir do topo)
    tracados: list[dict] = field(default_factory=list)
    #: estribos da viga (x em cm) retirados / deslocados
    estribos_retirados: list[float] = field(default_factory=list)
    estribos_deslocados: list[tuple[float, float]] = field(
        default_factory=list)
    #: pele cortada: (número da posição, altura da face inferior, x0, x1) cm
    cortes_pele: list[tuple[int, float, float, float]] = field(
        default_factory=list)
    #: bordas externas dos grupos de suspensão: (x cm, sentido -1 para a
    #: esquerda / +1 para a direita, espaçamento do grupo)
    bordas_suspensao: list[tuple[float, int, float]] = field(
        default_factory=list)
    avisos: list[str] = field(default_factory=list)
    #: a viga tem torção no trecho do furo (limites não ajustados)
    com_torcao: bool = False
    # geometria (cm): x ao longo da viga, z a partir do topo (negativo)
    x0: float = 0.0
    x1: float = 0.0
    z0: float = 0.0
    z1: float = 0.0
    #: seção do trecho do furo
    b: float = 0.0
    h: float = 0.0
    trecho: int = 0

    @property
    def ok(self) -> bool:
        return all(l.ok is not False for l in self.linhas)

    @property
    def dispensada(self) -> bool:
        return self.modelo == "dispensa"


@dataclass
class ResultadoAberturas:
    lista: list[ResultadoAbertura] = field(default_factory=list)
    #: número da posição da viga -> (barras a menos, motivo, {índice da
    #: faixa: estribos a menos})
    ajustes: dict = field(default_factory=dict)
    #: trechos de pele com gancho, de todas as aberturas juntas
    posicoes_pele: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(a.ok for a in self.lista)

    @property
    def posicoes(self) -> list:
        return [p for a in self.lista for p in a.posicoes] + \
            list(self.posicoes_pele)

    @property
    def estribos_retirados(self) -> list[float]:
        xs: list[float] = []
        for a in self.lista:
            xs += [x for x in a.estribos_retirados
                   if not any(abs(x - q) < 1e-6 for q in xs)]
        return xs

    @property
    def estribos_deslocados(self) -> dict:
        return {x0: x1 for a in self.lista
                for x0, x1 in a.estribos_deslocados}


# ---------------------------------------------------------------------------
# Leitura do resultado da viga
# ---------------------------------------------------------------------------

def _n(v: float, casas: int = 2) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def esforcos_no_furo(env, x_ini: float, x_fim: float,
                     criterio: str) -> dict:
    """M_d (com sinal) e V_d da envoltória ELU no furo, conforme o
    critério: o máximo em [x_ini, x_fim] ou a seção do centro. Devolve
    também o maior momento positivo (``M_pos``) e o mais negativo
    (``M_neg``) do trecho, para a viga contínua com alternância."""
    x = np.asarray(env.x, float)

    def em(arr, xx):
        return float(np.interp(xx, x, np.asarray(arr, float)))

    if criterio == CRITERIO_CENTRO:
        xc = (x_ini + x_fim) / 2.0
        mp, mn = em(env.M_max, xc), em(env.M_min, xc)
        V = max(abs(em(env.V_max, xc)), abs(em(env.V_min, xc)))
        M = mp if abs(mp) >= abs(mn) else mn
        return {"criterio": CRITERIO_CENTRO, "x_M": xc, "x_V": xc,
                "M": M, "V": V, "trecho": (x_ini, x_fim),
                "M_pos": max(mp, 0.0), "M_neg": min(mn, 0.0)}
    dentro = (x >= x_ini - 1e-9) & (x <= x_fim + 1e-9)
    xs = np.concatenate([[x_ini, x_fim], x[dentro]])
    mp = np.array([em(env.M_max, xx) for xx in xs])
    mn = np.array([em(env.M_min, xx) for xx in xs])
    vv = np.array([max(abs(em(env.V_max, xx)), abs(em(env.V_min, xx)))
                   for xx in xs])
    xv = xs.copy()
    # descontinuidade de V numa carga concentrada dentro do trecho
    for k in np.where(dentro)[0]:
        vv = np.append(vv, max(abs(env.V_max[k]), abs(env.V_min[k])))
        xv = np.append(xv, x[k])
    ip, im, iv = int(np.argmax(mp)), int(np.argmin(mn)), int(np.argmax(vv))
    if mp[ip] >= -mn[im]:
        M, xM = float(mp[ip]), float(xs[ip])
    else:
        M, xM = float(mn[im]), float(xs[im])
    return {"criterio": CRITERIO_PIOR_TRECHO, "x_M": xM,
            "x_V": float(xv[iv]), "M": M, "V": float(vv[iv]),
            "trecho": (x_ini, x_fim), "M_pos": max(float(mp[ip]), 0.0),
            "M_neg": min(float(mn[im]), 0.0)}


def casos_de_momento(e: dict) -> list[float]:
    """Os momentos de cálculo a verificar no furo: o principal e, numa
    viga contínua com alternância, o de sinal contrário quando passa de
    :data:`FRACAO_SEGUNDO_CASO` do principal."""
    principal = e["M"]
    casos = [principal] if abs(principal) > 1e-6 else []
    outro = e["M_neg"] if principal >= 0 else e["M_pos"]
    if abs(outro) > max(FRACAO_SEGUNDO_CASO * abs(principal), 1e-6):
        casos.append(outro)
    return casos


def _regiao(rv, x: float, positivo: bool):
    face = "inferior" if positivo else "superior"
    candidatas = [r for r in rv.regioes if r.face == face
                  and r.x_ini - 1e-9 <= x <= r.x_fim + 1e-9]
    nao_constr = [r for r in candidatas if not r.construtiva]
    return (nao_constr or candidatas or [None])[0]


def _barras_face(rv, face: str, x0: float, x1: float):
    """Barras longitudinais da viga numa face que cobrem o trecho [x0, x1]
    (m): (n, área, φ máx, posições)."""
    ps = [p for p in rv.posicoes if p.tipo in ("longitudinal", "porta")
          and p.face == face and p.camada == 1
          and p.x_ini <= x0 + 1e-6 and p.x_fim >= x1 - 1e-6]
    n = sum(p.n for p in ps)
    A = sum(p.n * area_barra(p.phi) for p in ps)
    phi = max((p.phi for p in ps), default=0.0)
    return n, A, phi, ps


def _zona_em(rv, x: float):
    for z in rv.zonas_estribo:
        if z.x_ini - 1e-6 <= x <= z.x_fim + 1e-6:
            return z
    return min(rv.zonas_estribo,
               key=lambda z: min(abs(z.x_ini - x), abs(z.x_fim - x)),
               default=None)


def laterais_barras(rv, x: float) -> list[tuple[float, float, str]]:
    """(y, φ, rótulo) das barras longitudinais em x (m), na largura: barras
    igualmente espaçadas entre os cantos do estribo, por face e camada."""
    viga = rv.viga
    cob = viga.ambiente.cobrimento_nominal
    zona = _zona_em(rv, x)
    phi_t = zona.phi if zona else viga.config.phi_estribo
    b = viga.secao_em(x).bw
    grupos: dict = {}
    for p in rv.posicoes:
        if p.tipo in ("longitudinal", "porta") and \
                p.x_ini - 1e-9 <= x <= p.x_fim + 1e-9:
            grupos.setdefault((p.face, p.camada), []).append(p)
    saida = []
    for (face, camada), ps in grupos.items():
        n = sum(max(p.n, 1) for p in ps)
        phi = max(p.phi for p in ps)
        r = cob + phi_t / 10.0 + phi / 20.0
        ys = [b / 2.0] if n == 1 else [r + (b - 2 * r) * k / (n - 1)
                                        for k in range(n)]
        rot = "/".join(f"N{p.numero}" for p in ps)
        saida += [(y, phi, f"{rot} ({face})") for y in ys]
    return saida


def _numero_da_zona(rv, zona) -> tuple[int | None, int]:
    """(número da posição de estribo, índice da faixa) que desenha a
    ``zona`` -- a mesma procura de ``geometria._posicao_da_faixa``."""
    for p in rv.posicoes:
        if p.tipo != "estribo" or p.papel == "mesa":
            continue
        for k, (a, b, esp, _q) in enumerate(
                p.faixas or [(p.x_ini, p.x_fim, p.s, p.n)]):
            if (a - 1e-6 <= zona.x_ini and zona.x_fim <= b + 1e-6
                    and abs(esp - zona.s) < 1e-9):
                return p.numero, k
    return None, -1


def estribos_viga(rv) -> list[tuple[float, int | None, int]]:
    """(x em cm, número da posição, índice da faixa) de cada estribo da
    viga -- a mesma conta que a elevação usa para desenhá-los."""
    xs: list[tuple[float, int | None, int]] = []
    for z in rv.zonas_estribo:
        n = max(2, z.n_estribos)
        a, b = z.x_ini * 100.0, z.x_fim * 100.0
        passo = (b - a) / max(n - 1, 1)
        numero, faixa = _numero_da_zona(rv, z)
        for k in range(n):
            x = a + k * passo
            if not any(abs(x - q) < 1e-6 for q, _n_, _f in xs):
                xs.append((x, numero, faixa))
    return sorted(xs, key=lambda t: t[0])


def alturas_pele(p, h: float, cob: float) -> list[float]:
    """Alturas (cm da face inferior) das barras de pele de uma posição --
    a mesma regra do desenho da seção (faixa vazia = alma inteira)."""
    n = p.n // max(p.n_faces, 1)
    a, b = p.faixa_altura
    if not any(p.faixa_altura):
        a, b = cob + 10.0, h - cob - 10.0
    if n <= 1:
        return [(a + b) / 2.0]
    return [a + (b - a) * k / (n - 1) for k in range(n)]


# ---------------------------------------------------------------------------
# Cálculo
# ---------------------------------------------------------------------------

class _Contexto:
    """O que todas as aberturas leem da viga calculada."""

    def __init__(self, rv):
        self.rv = rv
        viga = rv.viga
        self.viga = viga
        self.conc = viga.concreto
        self.aco = viga.aco
        self.aco_t = viga.aco_estribo
        self.cfg = viga.config
        self.cob = viga.ambiente.cobrimento_nominal
        self.env = rv.envoltoria
        self.dx = 0.0
        # extremidades físicas: as barras novas ancoram até elas, passando
        # sobre os apoios internos como qualquer barra da viga
        self.x_eng_e = viga.x_inicio_fisico * 100.0
        self.x_eng_d = viga.x_fim_fisico * 100.0
        xs = viga.x_apoios
        #: (face esquerda, face direita, índice) de cada apoio, cm
        self.faces_apoio = [(xs[k] * 100.0 - ap.largura / 2.0,
                             xs[k] * 100.0 + ap.largura / 2.0, k)
                            for k, ap in enumerate(viga.apoios)
                            if ap.tipo != "livre"]
        self.estribos = estribos_viga(rv)
        self.xs_estribos = [x for x, _n_, _f in self.estribos]
        self.pele_pos = [p for p in rv.posicoes if p.tipo == "pele"]
        self.proximo = max((p.numero for p in rv.posicoes), default=0) + 1
        self.dist_min_face = max(5.0, 2.0 * self.cob)

    def preparar(self, a) -> None:
        """A seção, o estribo e os limites do trecho da abertura ``a``."""
        viga = self.viga
        xc = a.x_centro
        self.trecho = viga.trecho_em(xc)
        self.secao = viga.trechos[self.trecho].secao
        self.b, self.h = self.secao.bw, self.secao.h
        self.tramo = viga.tramo_em(xc)
        zona = _zona_em(self.rv, xc)
        self.phi_t = zona.phi if zona else self.cfg.phi_estribo
        self.n_ramos = zona.n_ramos if zona else self.cfg.n_ramos
        from .dimensionar import _comprimento_estribo
        self.comp_estribo_viga = _comprimento_estribo(
            self.secao, self.cob, self.phi_t,
            self.cfg.pernas_amarracao_estribo, self.n_ramos,
            self.cfg.gancho_estribo)
        # a suspensão e a armadura do quadro têm de caber entre as faces dos
        # apoios vizinhos (ou a ponta do balanço)
        x0, x1 = a.x_ini * 100.0, a.x_fim * 100.0
        esq = [d for e, d, _k in self.faces_apoio if d <= x0 + 1e-6]
        dir_ = [e for e, d, _k in self.faces_apoio if e >= x1 - 1e-6]
        self.lim_e = max(esq) if esq else self.x_eng_e + self.cob
        self.lim_d = min(dir_) if dir_ else self.x_eng_d - self.cob
        dists = [x0 - d for e, d, _k in self.faces_apoio if d <= x0 + 1e-6]
        dists += [e - x1 for e, d, _k in self.faces_apoio if e >= x1 - 1e-6]
        self.dist_apoio = min(dists) if dists else float("inf")

    def numero(self) -> int:
        k = self.proximo
        self.proximo += 1
        return k

    def x_cm(self, x_m: float) -> float:
        return x_m * 100.0 + self.dx

    def torcao_no_trecho(self, a) -> bool:
        tramo = self.viga.tramo_em(a.x_centro)
        return any(abs(getattr(t, "Tsd", 0.0)) > 1e-6
                   and self.viga.tramo_em(t.x) == tramo
                   for t in self.rv.torcoes)


def calcular(rv) -> ResultadoAberturas:
    """Todas as aberturas da viga calculada ``rv`` (``ResultadoViga``)."""
    saida = ResultadoAberturas()
    viga = rv.viga
    aberturas = list(viga.aberturas)
    if not aberturas:
        return saida
    ctx = _Contexto(rv)
    ruins = invalidas(viga)
    for i, a in enumerate(aberturas):
        if i in ruins:
            r = ResultadoAbertura(indice=i, abertura=a, nome=f"A{i + 1}",
                                  modelo="inválida")
            r.x0, r.x1 = ctx.x_cm(a.x_ini), ctx.x_cm(a.x_fim)
            r.linhas.append(Linha(
                "Geometria do furo", "inválida", "",
                "ver os erros de entrada", False, "NBR 6118, 13.2.5"))
        else:
            ctx.preparar(a)
            r = (_vertical if a.vertical else _horizontal)(ctx, i, a,
                                                           aberturas)
            r.com_torcao = ctx.torcao_no_trecho(a)
            if r.com_torcao:
                r.avisos.append(
                    f"{r.nome}: a viga tem torção no tramo do furo — os "
                    f"limites dos itens 13.2.5 e 21.3.3 devem ser "
                    f"ajustados (21.3.3), o que o programa não faz; "
                    f"conferir à parte.")
        saida.lista.append(r)
    # o estribo da viga colado no grupo de suspensão (mais perto que o
    # passo do próprio grupo) também sai, se o vão que sobra não passar
    # de s_máx -- senão os dois ficam lado a lado, sem papel distinto
    for r in saida.lista:
        for x_b, sentido, passo in r.bordas_suspensao:
            x = _vizinho_colado(ctx, saida, x_b, sentido, passo)
            if x is not None:
                r.estribos_retirados.append(x)
                for l in r.linhas:
                    if l.grandeza == "Estribos da seção bruta retirados":
                        l.valor += " + 1 colado ao grupo"
    # ajustes das posições de estribo da viga
    por_x = {round(x, 6): (num, fx) for x, num, fx in ctx.estribos}
    for x in saida.estribos_retirados:
        num, fx = por_x.get(round(x, 6), (None, -1))
        if num is None:
            continue
        menos, motivo, faixas = saida.ajustes.get(num, (0, "", {}))
        faixas[fx] = faixas.get(fx, 0) + 1
        saida.ajustes[num] = (menos + 1, motivo, faixas)
    for num, (menos, _m, faixas) in list(saida.ajustes.items()):
        saida.ajustes[num] = (
            menos, f"{menos} estribo(s) retirado(s) nas aberturas "
                   f"(substituídos pelos estribos dos banzos e pela "
                   f"suspensão)", faixas)
    _pele_global(ctx, saida)
    return saida


# -- horizontal ---------------------------------------------------------------

def _distancias_faces(ctx, a, linhas: list[Linha]) -> None:
    lim = ctx.dist_min_face
    ref = "NBR 6118, 13.2.5.1"
    dt = a.topo
    db = ctx.h - a.topo - a.altura
    for nome, v in (("Distância do furo à face superior", dt),
                    ("Distância do furo à face inferior", db)):
        linhas.append(Linha(nome, _n(v, 1), "cm",
                            f"≥ max(5 cm; 2c = {_n(2 * ctx.cob, 1)}) = "
                            f"{_n(lim, 1)}", v >= lim - 1e-9, ref))


def _corta_barras(ctx, a, x0m, x1m) -> list[str]:
    """Barras longitudinais principais/superiores que o furo horizontal
    cortaria ou deixaria sem cobrimento (13.2.5.1 d)."""
    problemas = []
    for face in ("inferior", "superior"):
        for p in ctx.rv.posicoes:
            if p.tipo not in ("longitudinal", "porta") or p.face != face:
                continue
            if p.x_fim < x0m - 1e-9 or p.x_ini > x1m + 1e-9:
                continue
            prof = ctx.cob + ctx.phi_t / 10.0 + p.phi / 20.0 + \
                (p.camada - 1) * (p.phi / 10.0 + 2.0)
            borda = prof + p.phi / 20.0 + ctx.cob    # até onde não pode furar
            if face == "superior" and a.topo < borda - 1e-9:
                problemas.append(f"N{p.numero} ({face})")
            if face == "inferior" and ctx.h - a.topo - a.altura < \
                    borda - 1e-9:
                problemas.append(f"N{p.numero} ({face})")
    return sorted(set(problemas))


def _pele_cortada(ctx, a, r: ResultadoAbertura,
                  faixa_banzo: bool = False) -> None:
    """Barras de pele que o furo corta: viram trechos com gancho.

    Cortada é a que passa a menos de um cobrimento do furo e, com o modelo
    de banzos, também a que cairia na camada das barras novas junto ao furo
    (cobrimento + estribo + 2 cm). A pele vai até o cobrimento do furo (de
    ``x0 - c`` a ``x1 + c``) e termina ali com gancho."""
    y_fundo = ctx.h - a.topo - a.altura          # da face inferior
    y_topo = ctx.h - a.topo
    for p in ctx.pele_pos:
        if p.x_fim * 100.0 < r.x0 - 1e-6 or p.x_ini * 100.0 > r.x1 + 1e-6:
            continue
        folga = ctx.cob + p.phi / 20.0
        larga = ctx.cob + ctx.phi_t / 10.0 + 2.0 + p.phi / 20.0
        for y in alturas_pele(p, ctx.h, ctx.cob):
            if (y_fundo - folga < y < y_topo + folga) or (
                    faixa_banzo and y_fundo - larga < y < y_topo + larga):
                r.cortes_pele.append((p.numero, y, r.x0 - ctx.cob,
                                      r.x1 + ctx.cob))


def _deslocar_estribos(ctx, r: ResultadoAbertura, x0: float,
                       x1: float) -> None:
    """Estribos que cairiam no furo vão para a borda mais próxima."""
    folga = ctx.cob + ctx.phi_t / 20.0
    for x in ctx.xs_estribos:
        if x0 - folga < x < x1 + folga:
            novo = x0 - folga if x - x0 < x1 - x else x1 + folga
            r.estribos_deslocados.append((x, novo))


def _forma_txt(a) -> str:
    return (f"circular ø {_n(a.diametro, 1)} cm" if a.circular else
            f"retangular {_n(a.comprimento, 1)} x {_n(a.altura, 1)} cm")


def _horizontal(ctx, i, a, todas) -> ResultadoAbertura:
    nome = f"A{i + 1}"
    r = ResultadoAbertura(indice=i, abertura=a, nome=nome, modelo="banzos",
                          b=ctx.b, h=ctx.h, trecho=ctx.trecho)
    r.x0, r.x1 = ctx.x_cm(a.x_ini), ctx.x_cm(a.x_fim)
    r.z0, r.z1 = -a.topo, -(a.topo + a.altura)
    L = a.extensao
    linhas = r.linhas
    linhas.append(Linha("Tipo", f"horizontal (atravessa a largura), "
                        f"{_forma_txt(a)}", "", "", None,
                        "NBR 6118, 13.2.5.1"))
    linhas.append(Linha("Posição (do nó 0 da viga) / tramo",
                        f"{_n(a.x_ini, 2)} a {_n(a.x_fim, 2)} / tramo "
                        f"{ctx.tramo + 1}", "m",
                        f"seção bw x h = {_n(ctx.b, 0)} x {_n(ctx.h, 0)} cm"))
    linhas.append(Linha("Banzo superior / inferior",
                        f"{_n(a.topo, 1)} / {_n(ctx.h - a.topo - a.altura, 1)}",
                        "cm"))
    _distancias_faces(ctx, a, linhas)

    # -- esforços --------------------------------------------------------
    e = esforcos_no_furo(ctx.env, a.x_ini, a.x_fim, a.criterio_esforcos)
    r.esforcos = e
    _linhas_esforcos(e, linhas)
    casos = casos_de_momento(e)
    xc = a.x_centro

    # -- dispensa a)-d) ---------------------------------------------------
    dist_apoio = ctx.dist_apoio
    tracao = bool(casos)
    txt_ln = []
    for M in casos:
        positivo = M >= 0.0
        reg = _regiao(ctx.rv, xc, positivo)
        if reg is None:
            tracao = False
            txt_ln.append("sem região de flexão")
            continue
        x_ln = reg.flexao.x
        if positivo:
            ok_t = a.topo >= x_ln - 1e-9
            txt_ln.append(f"M > 0: topo do furo {_n(a.topo, 1)} cm ≥ x = "
                          f"{_n(x_ln, 2)} cm")
        else:
            ok_t = a.topo + a.altura <= ctx.h - x_ln + 1e-9
            txt_ln.append(f"M < 0: fundo do furo {_n(a.topo + a.altura, 1)}"
                          f" cm ≤ h − x = {_n(ctx.h - x_ln, 2)} cm")
        tracao = tracao and ok_t
    lado = (f"{_n(a.diametro, 1)}" if a.circular else
            f"{_n(a.comprimento, 1)} x {_n(a.altura, 1)}")
    if a.circular:
        cond_b = a.diametro <= min(DIAMETRO_MAX_CIRCULAR, ctx.h / 3) + 1e-9
        lim_b = f"ø ≤ 12,5 cm e ≤ h/3 = {_n(ctx.h / 3, 1)}"
    else:
        lim_b = f"≤ 12 x 12 cm e ≤ h/3 = {_n(ctx.h / 3, 1)}"
        cond_b = max(a.comprimento, a.altura) <= min(
            LADO_MAX_RETANGULAR, ctx.h / 3) + 1e-9
    horizontais = [(k, b_) for k, b_ in enumerate(todas)
                   if k != i and not b_.vertical]

    def _gap(b_):
        return max(ctx.x_cm(b_.x_ini) - r.x1, r.x0 - ctx.x_cm(b_.x_fim))

    # c) fala de furos "no mesmo tramo"
    gaps = [_gap(b_) for _k, b_ in horizontais
            if ctx.viga.tramo_em(b_.x_centro) == ctx.tramo]
    gap = min(gaps) if gaps else float("inf")
    gaps_todos = [_gap(b_) for _k, b_ in horizontais]
    gap_todos = min(gaps_todos) if gaps_todos else float("inf")
    cond_c = gap >= 2 * ctx.h - 1e-9
    cortadas = _corta_barras(ctx, a, a.x_ini, a.x_fim)
    cond_d = not cortadas
    cond_a = tracao and dist_apoio >= 2 * ctx.h - 1e-9
    linhas.append(Linha(
        "a) furo na zona de tração", "sim" if tracao else "não", "",
        ("; ".join(txt_ln) + " (LN do ELU da região)") if txt_ln
        else "sem momento: indefinida", None, "NBR 6118, 13.2.5.1 a)"))
    linhas.append(Linha(
        "a) distância à face do apoio mais próximo",
        _n(dist_apoio, 1) if dist_apoio < 1e8 else "—", "cm",
        f"≥ 2h = {_n(2 * ctx.h, 0)}", None, "NBR 6118, 13.2.5.1 a)"))
    linhas.append(Linha("b) dimensão do furo", lado, "cm", lim_b, None,
                        "NBR 6118, 13.2.5.1 b)"))
    linhas.append(Linha(
        "c) distância entre faces de furos no tramo",
        "único furo no tramo" if not gaps else _n(gap, 1), "cm",
        f"≥ 2h = {_n(2 * ctx.h, 0)}", None, "NBR 6118, 13.2.5.1 c)"))
    linhas.append(Linha(
        "d) cobrimento e não seccionamento das armaduras",
        "atende" if cond_d else "corta " + ", ".join(cortadas), "",
        "barras longitudinais intactas (pele: ver abaixo)",
        True if cond_d else False, "NBR 6118, 13.2.5.1 d); Seção 7"))
    dispensa = cond_a and cond_b and cond_c and cond_d
    linhas.append(Linha(
        "Dispensa da verificação (a, b, c e d simultâneas)",
        "dispensada" if dispensa else
        "não dispensada: " + ", ".join(
            k for k, ok in (("a", cond_a), ("b", cond_b), ("c", cond_c),
                            ("d", cond_d)) if not ok),
        "", "", None, "NBR 6118, 13.2.5.1"))

    if dispensa:
        _pele_cortada(ctx, a, r)
        r.modelo = "dispensa"
        _deslocar_estribos(ctx, r, r.x0, r.x1)
        if r.estribos_deslocados:
            linhas.append(Linha(
                "Estribos da viga deslocados para fora do furo",
                str(len(r.estribos_deslocados)), "",
                "mesma quantidade, junto às bordas", None,
                "NBR 6118, 13.2.5.1 d)"))
        return r

    # -- validade do modelo de banzos -------------------------------------
    h_sup, h_inf = a.topo, ctx.h - a.topo - a.altura
    dl_est = ctx.cob + ctx.phi_t / 10.0 + 0.5
    zona_s = ctx.h / 4.0
    motivos = []
    if min(h_sup, h_inf) < 3.0 * dl_est - 1e-9:
        motivos.append(f"banzo de {_n(min(h_sup, h_inf), 1)} cm menor que "
                       f"3 d' = {_n(3 * dl_est, 1)} cm")
    if r.x0 - zona_s < ctx.lim_e - 1e-9 or r.x1 + zona_s > ctx.lim_d + 1e-9:
        motivos.append("a suspensão de h/4 não cabe entre o furo e a face "
                       "do apoio (furo colado no apoio)")
    if gaps_todos and gap_todos < 2.0 * zona_s - 1e-9:
        motivos.append(f"furo vizinho a {_n(gap_todos, 1)} cm < h/2: as "
                       f"suspensões se sobrepõem — trate o conjunto como "
                       f"abertura única (13.2.5)")
    principal = casos[0] if casos else 0.0
    if not casos or _regiao(ctx.rv, xc, principal >= 0.0) is None:
        motivos.append("sem região de flexão para o braço de alavanca")
    if not cond_d:
        motivos.append("o furo secciona a armadura longitudinal")
    if motivos:
        r.modelo = "bielas"
        linhas.append(Linha(
            "Modelo de banzos (Vierendeel) aplicável?",
            "não: " + "; ".join(motivos), "",
            "verificar por bielas e tirantes", False,
            "NBR 6118, 21.3.1 e Seção 22"))
        _pele_cortada(ctx, a, r)
        r.avisos.append(f"{nome}: fora do modelo de banzos — " +
                        "; ".join(motivos) + ". A verificação deve ser "
                        "feita por bielas e tirantes (21.3.1, Seção 22).")
        return r
    if a.circular:
        linhas.append(Linha(
            "Furo circular no modelo de banzos",
            f"quadrado circunscrito {_n(L, 1)} x {_n(a.altura, 1)}", "cm",
            "", None, "critério do programa"))
    if ctx.secao.tipo != "retangular":
        linhas.append(Linha(
            "Seção com mesa", "banzos com a largura da alma bw", "",
            "mesa desprezada nos banzos — a favor da segurança", None,
            "critério do programa"))

    # -- banzos, caso a caso ----------------------------------------------------
    n_inf_ex, A_inf, phi_inf, _ = _barras_face(ctx.rv, "inferior", a.x_ini,
                                               a.x_fim)
    n_sup_ex, A_sup, phi_sup, _ = _barras_face(ctx.rv, "superior", a.x_ini,
                                               a.x_fim)
    existentes = {"superior": (n_sup_ex, A_sup, phi_sup),
                  "inferior": (n_inf_ex, A_inf, phi_inf)}
    n_ref = max(2, n_inf_ex if principal >= 0 else n_sup_ex)
    for M in casos:
        positivo = M >= 0.0
        rotulo = "M > 0" if positivo else "M < 0"
        if len(casos) > 1:
            linhas.append(Linha(
                f"Caso {rotulo} (envoltória com os dois sinais no furo)",
                f"M_d = {_n(M)}", "kN·m", "cada banzo fica com o caso pior",
                None, "NBR 6118, 14.6.7"))
        reg = _regiao(ctx.rv, xc, positivo)
        if reg is not None:
            fl = reg.flexao
            lam = ctx.conc.lambda_
            z = fl.d - lam * fl.x / 2.0
            txt_z = f"d = {_n(fl.d, 2)}, x = {_n(fl.x, 2)} ({reg.nome})"
        else:
            d_est = ctx.h - ctx.cob - ctx.phi_t / 10.0 - 1.0
            try:
                x_b, z = braco_alavanca(M, ctx.b, d_est, ctx.conc.sigma_cd,
                                        ctx.conc.lambda_)
            except ValueError:
                x_b, z = float("nan"), 0.9 * d_est
            txt_z = (f"seção bruta, d ≈ {_n(d_est, 2)}, x = {_n(x_b, 2)} "
                     f"(sem região de flexão deste sinal)")
        eb = esforcos_banzos(M, e["V"], z, L)
        linhas.append(Linha("Braço de alavanca z = d − λx/2",
                            _n(z, 2), "cm", txt_z, None,
                            "Bolina; NBR 6118, 17.2.2"))
        linhas.append(Linha("N_c = N_t = M_d/z", _n(eb["N"]), "kN"))
        linhas.append(Linha("V_c = 0,80 V_d / V_t = 0,20 V_d",
                            f"{_n(eb['Vc'])} / {_n(eb['Vt'])}", "kN", "",
                            None, "Bolina"))
        linhas.append(Linha("M_c = V_c·L/2 / M_t = V_t·L/2",
                            f"{_n(eb['Mc'])} / {_n(eb['Mt'])}", "kN·m",
                            f"L = {_n(L, 1)} cm", None, "Bolina"))
        banzos = []
        for nome_b, hb, comprimido in (("superior", h_sup, positivo),
                                       ("inferior", h_inf, not positivo)):
            bz = _banzo(ctx, nome_b, hb, comprimido, eb, existentes[nome_b],
                        n_ref, rotulo)
            banzos.append(bz)
            _linhas_banzo(ctx, bz, linhas, not math.isnan(bz.As_calc))
        r.casos.append(banzos)
    # cada banzo fica com a armadura do caso pior
    r.banzos = []
    for k in range(2):
        cands = [c[k] for c in r.casos]
        r.banzos.append(max(cands, key=lambda bz: (
            bz.face_furo[0] * area_barra(bz.face_furo[1]), bz.As_face)))
    s_comp = min(bz.estribos["s"] for c in r.casos for bz in c)
    r.s_compatibilizado = s_comp
    linhas.append(Linha("Estribos dos banzos compatibilizados",
                        f"ø {_n(ctx.phi_t, 1)} c/{_n(s_comp, 1)}", "cm",
                        "menor espaçamento dos banzos"
                        + (" e dos dois casos" if len(r.casos) > 1 else ""),
                        None, "Bolina"))

    # -- suspensão ----------------------------------------------------------
    Vc = FRACAO_V_COMPRIMIDO * abs(e["V"])
    sus = suspensao(Vc, ctx.aco_t, ctx.phi_t, ctx.n_ramos)
    r.suspensao = sus
    linhas.append(Linha("Suspensão A_susp = V_c/f_yd (cada lado)",
                        _n(sus["A"], 3), "cm²", f"distribuída em h/4 = "
                        f"{_n(zona_s, 1)} cm", None, "Bolina"))
    # um só grupo de estribos em h/4 de cada lado: os da viga que caem ali
    # saem, e a suspensão soma a parcela de cisalhamento que eles levavam
    asw_viga = _asw_viga_no_trecho(ctx, r.x0 - zona_s, r.x1 + zona_s)
    A_viga = asw_viga / 100.0 * zona_s
    A_zona = sus["A"] + A_viga
    a1 = sus["n_ramos"] * area_barra(sus["phi"])
    sus["A_viga"] = A_viga
    sus["A_total"] = A_zona
    sus["n"] = max(2, int(math.ceil(A_zona / a1 - 1e-9)))
    sus["A_ef"] = sus["n"] * a1
    linhas.append(Linha("Estribos da viga em h/4 (unificados à suspensão)",
                        _n(A_viga, 3), "cm²",
                        f"(A_sw/s)_viga = {_n(asw_viga)} cm²/m × h/4", None,
                        "NBR 6118, 17.4.2.2"))
    linhas.append(Linha("Suspensão adotada (cada lado)",
                        f"{sus['n']} estribos ø {_n(sus['phi'], 1)} "
                        f"({sus['n_ramos']} ramos)", "",
                        f"A_ef = {_n(sus['A_ef'], 3)} ≥ A_susp + A_viga = "
                        f"{_n(A_zona, 3)}",
                        sus["A_ef"] >= A_zona - 1e-9, "Bolina"))

    # -- estribos retirados e posições --------------------------------------
    passo_s = (zona_s - ctx.cob) / max(sus["n"] - 1, 1)
    r.bordas_suspensao = [(r.x0 - zona_s, -1, passo_s),
                          (r.x1 + zona_s, +1, passo_s)]
    n_furo = n_susp = 0
    for x in ctx.xs_estribos:
        if r.x0 - 1e-6 <= x <= r.x1 + 1e-6:
            r.estribos_retirados.append(x)
            n_furo += 1
        elif r.x0 - zona_s - 1e-6 <= x <= r.x1 + zona_s + 1e-6:
            r.estribos_retirados.append(x)
            n_susp += 1
    linhas.append(Linha("Estribos da seção bruta retirados",
                        f"{n_furo} no furo + {n_susp} em h/4", "",
                        "substituídos pelos estribos dos banzos e pela "
                        "suspensão", None, "Bolina"))
    _ancoragens_e_posicoes(ctx, r, a, r.banzos, s_comp, sus, zona_s, linhas)
    _pele_cortada(ctx, a, r, faixa_banzo=True)
    return r


def _banzo(ctx, nome_b, hb, comprimido, eb, existente, n_ref,
           rotulo) -> Banzo:
    """Um banzo do quadro: armadura simétrica por equilíbrio, mínima,
    barras novas e estribos."""
    N = eb["N"] if comprimido else -eb["N"]
    V = eb["Vc"] if comprimido else eb["Vt"]
    M = eb["Mc"] if comprimido else eb["Mt"]
    n_ex, A_ex, phi_ex = existente
    phi_novo = 10.0
    for _passo in range(3):
        dl = ctx.cob + ctx.phi_t / 10.0 + max(phi_novo, phi_ex) / 20.0
        As = armadura_simetrica(N, M, ctx.b, hb, dl, ctx.conc, ctx.aco)
        Ac = ctx.b * hb
        if comprimido:
            As_min = max(0.15 * abs(N) / ctx.aco.fyd_kNcm2, 0.004 * Ac)
            crit = "0,15 N/f_yd ≥ 0,4 % A_c (17.3.5.3.1)"
        else:
            As_min = interpola_rho_min(ctx.conc.fck) / 100.0 * Ac
            crit = "ρ_mín A_c (Tabela 17.3)"
        As_face = max(As if As is not None else 0.0, As_min) / 2.0
        n_f, phi_f = escolher_barras(As_face, n_ref, ctx.b, ctx.cob,
                                     ctx.phi_t, ctx.cfg.d_agregado)
        if abs(phi_f - phi_novo) < 1e-9:
            break
        phi_novo = phi_f
    nova_viga = None
    if A_ex < As_face - 1e-9:
        nova_viga = escolher_barras(As_face - A_ex, 2, ctx.b, ctx.cob,
                                    ctx.phi_t, ctx.cfg.d_agregado,
                                    ocupadas=n_ex)
    e_ex = abs(M) * 100.0 / abs(N) if abs(N) > 1e-9 else 1e9
    ln_fora = (not comprimido) and e_ex <= hb / 2.0 - dl + 1e-9
    d_b = hb - dl
    est = estribos_banzo(V, ctx.b, d_b, ctx.conc, ctx.aco_t, ctx.phi_t,
                         ctx.n_ramos, vc_nulo=ln_fora)
    return Banzo(nome=nome_b, comprimido=comprimido, h=hb, b=ctx.b,
                 d_linha=dl, d=d_b, N=N, M=M, V=V,
                 As_calc=As if As is not None else float("nan"),
                 As_min=As_min, criterio_min=crit, As_face=As_face,
                 face_viga_exist=(n_ex, phi_ex, A_ex),
                 face_viga_nova=nova_viga, face_furo=(n_f, phi_f),
                 estribos=est, ln_fora=ln_fora, caso=rotulo)


def _vizinho_colado(ctx, saida, x_borda: float, sentido: int,
                    passo: float) -> float | None:
    """Estribo da viga do lado de fora de um grupo de suspensão (borda em
    ``x_borda``, cm) que ficou mais perto dele que o ``passo`` do grupo:
    sai, se o vão até o próximo estribo da viga não passar de s_máx.
    Devolve o x retirado (ou ``None``)."""
    retirados = saida.estribos_retirados
    fora = sorted((x for x in ctx.xs_estribos
                   if (x - x_borda) * sentido > 1e-6
                   and not any(abs(x - q) < 1e-6 for q in retirados)),
                  key=lambda x: abs(x - x_borda))
    if not fora or abs(fora[0] - x_borda) >= passo - 1e-6:
        return None
    s_max = min((c.s_max for c in ctx.rv.cortantes), default=30.0)
    seguinte = abs(fora[1] - x_borda) if len(fora) > 1 else 0.0
    return fora[0] if seguinte <= s_max + 1e-6 else None


def _asw_viga_no_trecho(ctx, xa: float, xb: float) -> float:
    """Maior A_sw/s necessário (cm²/m) das faixas de estribo da viga que
    tocam o trecho [xa, xb] (cm)."""
    asw = 0.0
    for z in ctx.rv.zonas_estribo:
        a, b = z.x_ini * 100.0 + ctx.dx, z.x_fim * 100.0 + ctx.dx
        if b >= xa - 1e-6 and a <= xb + 1e-6:
            asw = max(asw, z.asw_req)
    return asw


def _linhas_esforcos(e: dict, linhas: list[Linha]) -> None:
    if e["criterio"] == CRITERIO_CENTRO:
        onde = f"seção do centro x = {_n(e['x_M'], 3)} m"
    else:
        x0, x1 = e["trecho"]
        onde = (f"pior no trecho {_n(x0, 2)}–{_n(x1, 2)} m (M em x = "
                f"{_n(e['x_M'], 3)}, V em x = {_n(e['x_V'], 3)})")
    linhas.append(Linha("Critério dos esforços de cálculo", e["criterio"],
                        "", onde, None, "envoltória ELU do motor da viga"))
    linhas.append(Linha("M_d / V_d no furo",
                        f"{_n(e['M'])} / {_n(e['V'])}", "kN·m / kN",
                        f"M_d,máx = {_n(e['M_pos'])}, M_d,mín = "
                        f"{_n(e['M_neg'])}"))


def _linhas_banzo(ctx, bz: Banzo, linhas: list[Linha], resolveu: bool):
    tipo = "flexo-compressão" if bz.comprimido else "flexo-tração"
    t = f"Banzo {bz.nome} ({tipo})"
    linhas.append(Linha(t, f"b x h = {_n(bz.b, 0)} x {_n(bz.h, 1)}", "cm",
                        f"d' = {_n(bz.d_linha, 2)}, d = {_n(bz.d, 2)}",
                        None, "Bolina"))
    nu = abs(bz.N) / (bz.b * bz.h * ctx.conc.fcd / 10.0)
    mu = abs(bz.M) * 100.0 / (bz.b * bz.h * bz.h * ctx.conc.fcd / 10.0)
    linhas.append(Linha("   N / M / V", f"{_n(abs(bz.N))} / {_n(abs(bz.M))}"
                        f" / {_n(bz.V)}", "kN / kN·m / kN",
                        f"ν = {_n(nu, 3)}, μ = {_n(mu, 3)}"))
    linhas.append(Linha(
        "   A_s por equilíbrio (simétrica, total)",
        _n(bz.As_calc, 3) if resolveu else "não resolve (> 4 % A_c)",
        "cm²", "bloco λx, α_c·η_c·f_cd, compatibilidade",
        None if resolveu else False, "NBR 6118, 17.2.2"))
    linhas.append(Linha("   A_s,mín", _n(bz.As_min, 3), "cm²",
                        bz.criterio_min, None, "NBR 6118"))
    n_ex, phi_ex, A_ex = bz.face_viga_exist
    txt_ex = (f"{n_ex} ø {_n(phi_ex, 1)} existentes ({_n(A_ex, 2)} cm²)"
              if n_ex else "nenhuma barra existente")
    if bz.face_viga_nova:
        k, phi = bz.face_viga_nova
        txt_ex += f" + {k} ø {_n(phi, 1)} novas"
    A_viga = A_ex + (bz.face_viga_nova[0] * area_barra(bz.face_viga_nova[1])
                     if bz.face_viga_nova else 0.0)
    linhas.append(Linha("   face junto à face da viga", txt_ex, "",
                        f"A_s,ef = {_n(A_viga, 2)} ≥ {_n(bz.As_face, 2)}",
                        A_viga >= bz.As_face - 1e-9, "aproveita a viga"))
    k, phi = bz.face_furo
    A_f = k * area_barra(phi)
    linhas.append(Linha("   face junto ao furo", f"{k} ø {_n(phi, 1)} novas",
                        "", f"A_s,ef = {_n(A_f, 2)} ≥ {_n(bz.As_face, 2)}",
                        A_f >= bz.As_face - 1e-9, "Bolina"))
    es = bz.estribos
    linhas.append(Linha("   V_Rd2 = 0,27 α_v2 f_cd b d", _n(es["VRd2"]), "kN",
                        f"≥ V = {_n(bz.V)}", es["biela_ok"],
                        "NBR 6118, 17.4.2.2"))
    vc_txt = ("V_c = 0 (tracionado, LN fora da seção)" if bz.ln_fora
              else f"V_c = V_c0 = {_n(es['Vc0'])} kN")
    linhas.append(Linha("   A_sw/s calc. / mínima",
                        f"{_n(es['asw'])} / {_n(es['asw_min'])}", "cm²/m",
                        vc_txt, None, "NBR 6118, 17.4.2.2 e 17.4.1.1.1"))
    linhas.append(Linha("   s máx / s adotado (antes de compatibilizar)",
                        f"{_n(es['s_max'], 1)} / {_n(es['s'], 1)}", "cm",
                        f"V/V_Rd2 = {_n(es['razao'], 3)}", None,
                        "NBR 6118, 18.3.3.2"))


def _ancoragens_e_posicoes(ctx, r, a, banzos, s_comp, sus, zona_s, linhas):
    """Comprimentos e ancoragens das barras novas, estribos dos banzos e
    suspensão como posições da tabela de ferros."""
    for bz in banzos:
        # profundidade das barras novas (cm do topo) para a aderência
        if bz.nome == "superior":
            prof_furo = a.topo - bz.d_linha
            prof_viga = bz.d_linha
        else:
            prof_furo = a.topo + a.altura + bz.d_linha
            prof_viga = ctx.h - bz.d_linha
        itens = [("furo", bz.face_furo, prof_furo)]
        if bz.face_viga_nova:
            itens.append(("viga", bz.face_viga_nova, prof_viga))
        for onde, (k, phi), prof in itens:
            boa = boa_aderencia("alma", ctx.h, ctx.h - prof)
            anc = ancoragem_basica(phi, ctx.conc, ctx.aco, boa)
            if onde == "furo":
                bz.ancoragem_furo = anc
            else:
                bz.ancoragem_viga = anc
            x_a = r.x0 - zona_s - anc["lb_adot"]
            x_b = r.x1 + zona_s + anc["lb_adot"]
            disp_e = r.x0 - zona_s - (ctx.x_eng_e + ctx.cob)
            disp_d = (ctx.x_eng_d - ctx.cob) - (r.x1 + zona_s)
            x_a = max(x_a, ctx.x_eng_e + ctx.cob)
            x_b = min(x_b, ctx.x_eng_d - ctx.cob)
            ok = min(disp_e, disp_d) >= anc["lb_adot"] - 1e-9
            situacao = "boa" if boa else "má"
            linhas.append(Linha(
                f"   ancoragem {k} ø {_n(phi, 1)} (banzo {bz.nome}, "
                f"face {'do furo' if onde == 'furo' else 'da viga'})",
                f"l_b = {_n(anc['lb'], 1)} → {_n(anc['lb_adot'], 0)}", "cm",
                f"{situacao} aderência (η2 = {_n(anc['eta2'], 1)}); "
                f"disponível {_n(min(disp_e, disp_d), 0)} cm",
                ok, "NBR 6118, 9.3.1 e 9.4.2.4"))
            numero = ctx.numero()
            r.posicoes.append(det.Posicao(
                numero=numero, tipo="banzo", n=k, phi=phi,
                face="superior" if bz.nome == "superior" else "inferior",
                x_ini=(x_a - ctx.dx) / 100.0, x_fim=(x_b - ctx.dx) / 100.0,
                comprimento=x_b - x_a, tramo=ctx.tramo, trecho=ctx.trecho,
                papel="banzo",
                descricao=(f"{r.nome}: banzo {bz.nome}, face "
                           f"{'junto ao furo' if onde == 'furo' else 'da viga'}"
                           f" — ancorada a partir do fim da suspensão")))
            r.tracados.append({
                "tipo": "barra", "papel": "banzo", "phi": phi, "n": k,
                "face": bz.nome, "z": -prof, "x0": x_a, "x1": x_b,
                "numero": numero,
                "rotulo": f"{k} N{numero} Ø{phi:g} banzo {bz.nome} "
                          f"C={x_b - x_a:.0f}"})
    # estribos dos banzos
    e0 = ctx.cob
    n_est = int(math.ceil((a.extensao - 2 * e0) / s_comp - 1e-9)) + 1
    xs = [r.x0 + e0 + k * (a.extensao - 2 * e0) / max(n_est - 1, 1)
          for k in range(n_est)]
    for bz in banzos:
        secao = Secao(bw=ctx.b, h=bz.h, tipo="retangular")
        from .dimensionar import _comprimento_estribo
        comp = _comprimento_estribo(secao, ctx.cob, ctx.phi_t,
                                    ctx.cfg.pernas_amarracao_estribo,
                                    ctx.n_ramos, ctx.cfg.gancho_estribo)
        if bz.nome == "superior":
            y_a, y_b = ctx.h - a.topo, ctx.h          # da face inferior
            z_a, z_b = -ctx.cob, -a.topo + ctx.cob
        else:
            y_a, y_b = 0.0, ctx.h - a.topo - a.altura
            z_a, z_b = -(a.topo + a.altura) - ctx.cob, -ctx.h + ctx.cob
        xa_m, xb_m = (xs[0] - ctx.dx) / 100.0, (xs[-1] - ctx.dx) / 100.0
        numero = ctx.numero()
        r.posicoes.append(det.Posicao(
            numero=numero, tipo="estribo", n=n_est, phi=ctx.phi_t,
            face="alma", x_ini=xa_m, x_fim=xb_m, comprimento=comp, s=s_comp,
            descricao=(f"{r.nome}: estribos do banzo {bz.nome} "
                       f"({ctx.n_ramos} ramos, b x h = {_n(ctx.b, 0)} x "
                       f"{_n(bz.h, 1)} cm)"),
            n_ramos_efetivo=ctx.n_ramos, papel="banzo",
            faixa_altura=(y_a, y_b), tramo=ctx.tramo, trecho=ctx.trecho,
            faixas=[(xa_m, xb_m, s_comp, n_est)]))
        r.tracados.append({
            "tipo": "estribos", "papel": "banzo", "phi": ctx.phi_t,
            "xs": xs, "z0": z_b, "z1": z_a, "numero": numero,
            "rotulo": f"{n_est} N{numero} c/{s_comp:g} (banzo {bz.nome})"})
    linhas.append(Linha("Estribos de cada banzo", f"{n_est} ø "
                        f"{_n(ctx.phi_t, 1)} c/{_n(s_comp, 1)}", "",
                        f"no comprimento do furo, {_n(e0, 1)} cm das bordas",
                        None, "Bolina"))
    # suspensão: n estribos em h/4 de cada lado, colados no furo
    n = sus["n"]
    esq = [r.x0 - ctx.cob - k / max(n - 1, 1) * (zona_s - ctx.cob)
           for k in range(n)]
    dir_ = [r.x1 + ctx.cob + k / max(n - 1, 1) * (zona_s - ctx.cob)
            for k in range(n)]
    xs_s = sorted(esq + dir_)
    passo = round((zona_s - ctx.cob) / max(n - 1, 1), 1)
    numero = ctx.numero()
    r.posicoes.append(det.Posicao(
        numero=numero, tipo="suspensao", n=2 * n, phi=sus["phi"],
        face="alma", x_ini=(xs_s[0] - ctx.dx) / 100.0,
        x_fim=(xs_s[-1] - ctx.dx) / 100.0, comprimento=ctx.comp_estribo_viga,
        s=passo, papel="furo", tramo=ctx.tramo, trecho=ctx.trecho,
        descricao=(f"{r.nome}: suspensão do furo, {n} estribos em h/4 = "
                   f"{_n(zona_s, 1)} cm de cada lado (Bolina)"),
        n_ramos_efetivo=ctx.n_ramos,
        faixas=[(min(esq) / 100.0, max(esq) / 100.0, passo, n),
                (min(dir_) / 100.0, max(dir_) / 100.0, passo, n)]))
    r.tracados.append({
        "tipo": "estribos", "papel": "suspensao", "phi": sus["phi"],
        "xs": xs_s, "z0": -ctx.h + ctx.cob, "z1": -ctx.cob,
        "numero": numero,
        "rotulo": f"{2 * n} N{numero} suspensão ({n} + {n} em h/4)"})


# -- pele ---------------------------------------------------------------------

def _pele_global(ctx, saida: ResultadoAberturas) -> None:
    """Trechos de pele com gancho a 90° nos cortes de **todas** as
    aberturas: cada barra cortada vira os trechos entre os cortes, e as
    barras de mesma geometria das duas faces formam uma posição."""
    cortes: dict = {}
    for r in saida.lista:
        for num, y, xa, xb in r.cortes_pele:
            cortes.setdefault(num, {}).setdefault(round(y, 3), []).append(
                (xa, xb, r))
    if not cortes:
        return
    pos = {p.numero: p for p in ctx.pele_pos}
    trechos_por_furo: dict = {}
    for num, por_y in cortes.items():
        p = pos[num]
        phi = p.phi
        raio = ctx.aco.raio_dobramento_eixo(phi)
        gancho = gk.comprimento_desenvolvido(raio, phi, gk.PADRAO)
        x_ini, x_fim = p.x_ini * 100.0, p.x_fim * 100.0
        grupos: dict = {}
        for y, ivs in por_y.items():
            ivs = sorted(ivs, key=lambda t: t[0])
            pontos = [(x_ini, None)]
            for xa, xb, r in ivs:
                pontos.append((xa, r))
                pontos.append((xb, r))
            pontos.append((x_fim, None))
            for (a, ra), (b, rb) in zip(pontos[::2], pontos[1::2]):
                if b - a <= 1e-6:
                    continue
                chave = (round(a, 3), round(b, 3))
                grupos.setdefault(chave, {"ys": [], "furos": (ra, rb)})
                grupos[chave]["ys"].append(y)
                for rr in (ra, rb):
                    if rr is not None:
                        trechos_por_furo.setdefault(rr.indice, []).append(
                            (b - a, phi, y))
        for (a, b), g in grupos.items():
            ra, rb = g["furos"]
            n_ganchos = (ra is not None) + (rb is not None)
            ys = g["ys"]
            nomes = "/".join(dict.fromkeys(
                x.nome for x in (ra, rb) if x is not None))
            saida.posicoes_pele.append(det.Posicao(
                numero=ctx.numero(), tipo="pele",
                n=len(ys) * max(p.n_faces, 1), n_faces=p.n_faces or 2,
                phi=phi, face="alma", x_ini=a / 100.0, x_fim=b / 100.0,
                comprimento=(b - a) + n_ganchos * gancho,
                faixa_altura=(min(ys), max(ys)), tramo=p.tramo,
                descricao=(f"{nomes}: pele N{num} interrompida no furo, "
                           f"trecho de {a / 100.0:.2f} a {b / 100.0:.2f} m, "
                           f"gancho a 90° no corte")))
        k = len(por_y) * max(p.n_faces, 1)
        menos, motivo, faixas = saida.ajustes.get(num, (0, "", {}))
        saida.ajustes[num] = (menos + k, f"{k} barra(s) de pele "
                              f"interrompida(s) nas aberturas (trocadas "
                              f"pelos trechos com gancho)", faixas)
    # a linha da ancoragem da pele em cada furo
    for r in saida.lista:
        trechos = trechos_por_furo.get(r.indice, [])
        if not trechos:
            continue
        phi = max(t[1] for t in trechos)
        boa = all(boa_aderencia("alma", r.h, t[2]) for t in trechos)
        anc = ancoragem_basica(phi, ctx.conc, ctx.aco, boa)
        lb_gancho = 0.7 * anc["lb"]
        menor = min(t[0] for t in trechos)
        n_face = len({round(c[1], 3) for c in r.cortes_pele})
        r.linhas.append(Linha(
            "Pele interrompida (barras que o furo ou o banzo cortam)",
            f"{n_face} por face, ø {_n(phi, 1)}", "",
            "ancorada com gancho a 90° de cada lado", None,
            "Bolina; NBR 6118, 9.4.2.3"))
        r.linhas.append(Linha(
            "   l_b da pele / com gancho (0,7 l_b)",
            f"{_n(anc['lb'], 1)} / {_n(lb_gancho, 1)}", "cm",
            f"menor trecho reto {_n(menor, 0)} cm",
            menor >= lb_gancho - 1e-9,
            f"NBR 6118, 9.4.2.4/9.4.2.5 ({'boa' if boa else 'má'} aderência)"))


# -- vertical -----------------------------------------------------------------

def _vertical(ctx, i, a, todas) -> ResultadoAbertura:
    nome = f"A{i + 1}"
    r = ResultadoAbertura(indice=i, abertura=a, nome=nome, modelo="vertical",
                          b=ctx.b, h=ctx.h, trecho=ctx.trecho)
    r.x0, r.x1 = ctx.x_cm(a.x_ini), ctx.x_cm(a.x_fim)
    r.z0, r.z1 = 0.0, -ctx.h
    D = a.diametro
    y = a.y_eixo(ctx.b)
    linhas = r.linhas
    ref = "NBR 6118, 21.3.3"
    linhas.append(Linha("Tipo", f"vertical (atravessa a altura), circular ø "
                        f"{_n(D, 1)} cm", "", "", None, ref))
    linhas.append(Linha("Posição (do nó 0 da viga) / tramo",
                        f"{_n(a.x_ini, 2)} a {_n(a.x_fim, 2)} / tramo "
                        f"{ctx.tramo + 1}", "m",
                        f"eixo a {_n(y, 1)} cm da face lateral"))
    linhas.append(Linha("Diâmetro", _n(D, 1), "cm",
                        f"≤ b/3 = {_n(ctx.b / 3, 2)}",
                        D <= ctx.b / 3 + 1e-9, ref))
    lim = ctx.dist_min_face
    for lado_, v in (("esquerda", y - D / 2), ("direita", ctx.b - y - D / 2)):
        linhas.append(Linha(f"Distância à face lateral ({lado_})", _n(v, 1),
                            "cm", f"≥ max(5 cm; 2c) = {_n(lim, 1)}",
                            v >= lim - 1e-9, ref))
    # barras longitudinais
    cortadas = []
    for yb, phi, rot in laterais_barras(ctx.rv, a.x_centro):
        if abs(yb - y) < D / 2 + phi / 20.0 + ctx.cob - 1e-9:
            cortadas.append(rot)
    linhas.append(Linha("Barras longitudinais fora do furo (com cobrimento)",
                        "atende" if not cortadas else
                        "corta " + ", ".join(sorted(set(cortadas))), "",
                        "desloque o furo (y) ou redistribua as barras",
                        not cortadas, "NBR 6118, 21.3.3 e Seção 7"))
    # conjunto
    verticais = sorted((ctx.x_cm(b_.x_ini), ctx.x_cm(b_.x_fim), b_, k)
                       for k, b_ in enumerate(todas) if b_.vertical)
    _deslocar_estribos(ctx, r, r.x0, r.x1)
    desloc = dict(r.estribos_deslocados)
    xs_final = [desloc.get(x, x) for x in ctx.xs_estribos]
    for x0, x1, b_, k in verticais:
        if k == i or x0 < r.x1 - 1e-9 or x0 - r.x1 > 2 * ctx.h:
            continue
        gap = x0 - r.x1
        lim_g = max(5.0, D, b_.diametro)
        linhas.append(Linha(f"Distância livre até A{k + 1}", _n(gap, 1), "cm",
                            f"≥ max(5 cm; ø) = {_n(lim_g, 1)}",
                            gap >= lim_g - 1e-9, ref))
        alinhado = abs(b_.y_eixo(ctx.b) - y) < 0.5
        linhas.append(Linha(f"Alinhamento com A{k + 1}",
                            "alinhados" if alinhado else "desalinhados", "",
                            "furos do conjunto alinhados", alinhado, ref))
        tem = any(r.x1 + 1e-6 < xx < x0 - 1e-6 for xx in xs_final)
        linhas.append(Linha(f"Estribo no intervalo até A{k + 1}",
                            "sim" if tem else "não", "",
                            "pelo menos um estribo por intervalo", tem, ref))
        break
    # seção reduzida
    e = esforcos_no_furo(ctx.env, a.x_ini, a.x_fim, a.criterio_esforcos)
    r.esforcos = e
    _linhas_esforcos(e, linhas)
    br = ctx.b - D
    sc = ctx.conc.sigma_cd
    lam = ctx.conc.lambda_
    d_ref = None
    for M in casos_de_momento(e) or [0.0]:
        positivo = M >= 0
        reg = _regiao(ctx.rv, a.x_centro, positivo)
        face = "inferior" if positivo else "superior"
        n_t, A_t, phi_tr, _ = _barras_face(ctx.rv, face, a.x_ini, a.x_fim)
        d = reg.flexao.d if reg is not None else \
            ctx.h - ctx.cob - ctx.phi_t / 10.0 - 1.0
        d_ref = d if d_ref is None else min(d_ref, d)
        x = A_t * ctx.aco.fyd_kNcm2 / (sc * lam * br) if br > 0 else 9e9
        MRd = A_t * ctx.aco.fyd_kNcm2 * (d - lam * x / 2.0) / 100.0
        x_lim = reg.flexao.x_lim_d if reg is not None else 0.45
        rot = "" if len(casos_de_momento(e)) < 2 else \
            (" (M > 0)" if positivo else " (M < 0)")
        linhas.append(Linha(f"Seção reduzida b − ø{rot}", _n(br, 1), "cm",
                            f"A_s tracionada ({face}) {n_t} barras = "
                            f"{_n(A_t, 2)} cm²", None, ref))
        linhas.append(Linha(f"Flexão: M_Rd da seção reduzida{rot}", _n(MRd),
                            "kN·m", f"≥ |M_d| = {_n(abs(M))}",
                            MRd >= abs(M) - 1e-9, "NBR 6118, 17.2.2"))
        linhas.append(Linha(f"   x/d da seção reduzida{rot}", _n(x / d, 3),
                            "", f"≤ {_n(x_lim, 2)}", x / d <= x_lim + 1e-9,
                            "NBR 6118, 14.6.4.3"))
    d = d_ref
    VRd2 = 0.27 * ctx.conc.alfa_v2 * ctx.conc.fcd / 10.0 * br * d
    Vc0 = 0.6 * ctx.conc.fctd_kNcm2 * br * d
    zona = _zona_em(ctx.rv, a.x_centro)
    asw = zona.asw_ef if zona else 0.0
    fywd = min(ctx.aco_t.fyd_kNcm2, 43.5)
    Vsw = asw / 100.0 * 0.9 * d * fywd
    linhas.append(Linha("Cisalhamento: V_Rd2 (b − ø)", _n(VRd2), "kN",
                        f"≥ V_d = {_n(e['V'])}", e["V"] <= VRd2 + 1e-9,
                        "NBR 6118, 17.4.2.2"))
    linhas.append(Linha("Cisalhamento: V_Rd3 = V_c + V_sw (b − ø)",
                        _n(Vc0 + Vsw), "kN",
                        f"≥ V_d = {_n(e['V'])} (A_sw/s = {_n(asw)} cm²/m)",
                        e["V"] <= Vc0 + Vsw + 1e-9, "NBR 6118, 17.4.2.2"))
    if r.estribos_deslocados:
        linhas.append(Linha("Estribos da viga deslocados para fora do furo",
                            str(len(r.estribos_deslocados)), "",
                            "mesma quantidade, junto às bordas", None, ref))
    return r


# ---------------------------------------------------------------------------
# Integração com o resultado da viga
# ---------------------------------------------------------------------------

def posicoes_viga(rv, res_ab: ResultadoAberturas | None) -> list:
    """As posições do motor com a contagem ajustada pelas aberturas
    (estribos retirados, pele interrompida) mais as posições novas. Sem
    abertura, é a lista do motor, intacta."""
    if res_ab is None or not res_ab.lista:
        return list(rv.posicoes)
    saida = []
    for p in rv.posicoes:
        if p.numero in res_ab.ajustes:
            menos, motivo, faixas = res_ab.ajustes[p.numero]
            q = replace(p, n=max(p.n - menos, 0),
                        descricao=f"{p.descricao} — {motivo}")
            if q.faixas:
                q.faixas = [(a, b, s, max(n - faixas.get(k, 0), 0))
                            for k, (a, b, s, n) in enumerate(q.faixas)]
            saida.append(q)
        else:
            saida.append(p)
    return saida + res_ab.posicoes


def avisos(res_ab: ResultadoAberturas) -> list[str]:
    """Avisos classificados do resultado das aberturas."""
    saida: list[str] = []
    for r in res_ab.lista:
        reprovadas = [l.grandeza.strip() for l in r.linhas if l.ok is False]
        if r.modelo == "bielas":
            saida += [av.erro(t) for t in r.avisos
                      if "bielas e tirantes" in t]
        elif reprovadas:
            saida.append(av.erro(
                f"Abertura {r.abertura.nome(r.indice)}: verificação não "
                f"atendida (13.2.5/21.3) — " + "; ".join(reprovadas)))
        elif r.modelo == "dispensa":
            saida.append(av.construtivo(
                f"Abertura {r.abertura.nome(r.indice)}: dispensada da "
                f"verificação (13.2.5.1, condições a a d atendidas)"
                + (f"; {len(r.estribos_deslocados)} estribo(s) deslocado(s) "
                   f"para as bordas do furo" if r.estribos_deslocados
                   else "") + "."))
        elif r.modelo == "banzos":
            saida.append(av.construtivo(
                f"Abertura {r.abertura.nome(r.indice)}: verificada pelo "
                f"modelo de banzos (Bolina) — {len(r.posicoes)} posições "
                f"novas (barras e estribos dos banzos, suspensão); "
                f"{len(r.estribos_retirados)} estribo(s) da viga "
                f"retirado(s)."))
        saida += [av.construtivo(t) for t in r.avisos
                  if "bielas e tirantes" not in t]
    return saida


def aplicar(res) -> None:
    """Calcula as aberturas sobre o resultado ``res`` da viga e o completa:
    ``res.aberturas``, a lista de posições ajustada, o quantitativo e os
    avisos. Sem abertura não toca em nada."""
    viga = res.viga
    if not getattr(viga, "aberturas", None):
        return
    from .dimensionar import _quantitativo
    res_ab = calcular(res)
    res.aberturas = res_ab
    res.posicoes = posicoes_viga(res, res_ab)
    res.quantitativo = _quantitativo(viga, res.posicoes)
    res.avisos = list(res.avisos) + avisos(res_ab)
