# -*- coding: utf-8 -*-
"""
incendio.py
Verificação do pilar em situação de incêndio pela ABNT NBR 15200:2024.

Métodos implementados (8.2 a 8.3 da norma; qualquer um deles basta):

* **uma face exposta** -- Tabela 12 (8.2.4): ``b_min`` e ``c1`` em função do
  TRRF;
* **mais de uma face exposta** --
  - **método analítico** (8.3.2): ``TRF = 120 ((R_mu + R_a + R_l + R_b +
    R_n)/120)^1,8 >= TRRF``, dentro dos limites de aplicação (As/Ac <= 4 %,
    25 <= c1 <= 80 mm, b' >= 190 mm, e <= 0,15 b, l_ef,fi <= 6 m);
  - **método tabular geral** (Anexo E, Tabelas E.1 a E.9): ``b_min / c1`` em
    função de omega, e_max, lambda_fi e nu_fi.

Só seção retangular ou circular (é o que a norma cobre). Nas demais o item é
declarado não verificado.

Solicitações em incêndio (8.1)
------------------------------
Com as ações características informadas, a combinação excepcional
``1,2 Fgk + sum 0,7 psi2 Fqk`` (:func:`acoes.incendio`). Sem elas,
``Sd,fi = 0,70 Sd`` -- a alternativa da norma, que vale "tomando-se apenas as
combinações de ações que não incluem o vento" --, com o fator nos critérios.

``mu_fi = N_Sd,fi / N_Rd``, com ``N_Rd`` a normal resistente de cálculo do
pilar à temperatura ambiente, com a 2ª ordem: o programa toma ``N_Rd = Nd``
-- o pilar aprovado resiste pelo menos a ``Nd``, então ``N_Rd >= Nd`` e o
``mu_fi`` adotado é um teto, o lado seguro. Um ``mu_fi`` informado nos
critérios substitui esse.

Interpolação
------------
O Anexo E (E.3) permite interpolar linearmente nas tabelas. O programa não
interpola: arredonda cada entrada para o lado seguro -- omega para a tabela
de baixo, ``e`` para a categoria de cima, lambda_fi e nu_fi para a linha e a
coluna de cima. Fora das tabelas (omega < 0,1, nu_fi > 0,7, lambda_fi > 80,
``e`` acima da última categoria) o método não se aplica.

Pressupostos declarados
-----------------------
Os dois métodos de pilar valem para estruturas de nós fixos, ou em que os
efeitos globais de 2ª ordem à temperatura ambiente não passem de 30 %
(gamma_z <= 1,30); o programa não conhece a estrutura e declara isso. O
revestimento não entra em ``c1`` (é a favor da segurança).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import avisos as av
from .esbeltez import excentricidade_minima
from .formato import num
from .tabelas_15200 import TABELA_12, TABELAS_E

TRRF_VALIDOS = (30, 60, 90, 120, 180)
COLUNAS_NU = (0.15, 0.3, 0.5, 0.7)
LINHAS_LAMBDA = (30, 40, 50, 60, 70, 80)
OMEGAS = (0.1, 0.5, 1.0)
CATEGORIAS_E = ("10mm", "0,25b", "0,5b")


@dataclass
class MetodoIncendio:
    nome: str
    aplicavel: bool = True
    ok: bool = False
    motivo: str = ""             # por que não se aplica, ou o que faltou
    detalhe: str = ""            # a conta, para a memória


@dataclass
class VerificacaoIncendio:
    aplicavel: bool = False
    trrf: int = 0
    faces: str = "mais"
    b: float = 0.0               # mm, menor dimensão
    h: float = 0.0               # mm, maior dimensão
    c1: float = 0.0              # mm, eixo da barra até a face
    N_fi: float = 0.0            # kN, N0Sd,fi
    e_fi: float = 0.0            # mm, excentricidade de 1ª ordem em incêndio
    origem_sd: str = ""
    mu_fi: float = 0.0
    lef_fi: float = 0.0          # m
    lam_fi: float = 0.0
    omega: float = 0.0
    nu_fi: float = 0.0
    metodos: list[MetodoIncendio] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return any(m.aplicavel and m.ok for m in self.metodos)


def _c1(arranjo, contornos, circular: bool, D: float) -> float:
    """Menor distância do eixo de uma barra à face externa, mm."""
    if not arranjo or not arranjo.barras:
        return 0.0
    if circular:
        R = D / 2.0
        return 10.0 * min(R - math.hypot(b.x, b.y) for b in arranjo.barras)
    xs = [x for x, _ in contornos[0]]
    ys = [y for _, y in contornos[0]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return 10.0 * min(min(b.x - x0, x1 - b.x, b.y - y0, y1 - b.y)
                      for b in arranjo.barras)


def _solicitacoes(pilar) -> tuple[float, float, float, str]:
    """``(N0Sd,fi kN, e_x cm, e_y cm, origem)``: 1ª ordem em incêndio."""
    cfg = pilar.config
    if pilar.acoes:
        from . import acoes
        e, texto = acoes.incendio(pilar.acoes)
        N = e.Nd
        Mx = max(abs(e.Mx_topo), abs(e.Mx_base))
        My = max(abs(e.My_topo), abs(e.My_base))
        origem = f"combinação excepcional de incêndio: {texto} (8.1)"
    else:
        f = cfg.incendio_fator_sd
        N = f * pilar.Nd
        Mx = f * pilar.M1d_A("x")
        My = f * pilar.M1d_A("y")
        origem = (f"Sd,fi = {num(f, 2)}·Sd (8.1), sobre a combinação de "
                  f"cálculo {pilar.nome_combinacao}")
    ex = Mx / N if N > 1e-9 else 0.0
    ey = My / N if N > 1e-9 else 0.0
    return N, ex, ey, origem


def _limite_e(categoria: str, b: float) -> float:
    """``e_max`` da categoria, mm, para a menor dimensão ``b`` (mm)."""
    if categoria == "10mm":
        return 10.0 if b <= 400.0 else 0.025 * b
    if categoria == "0,25b":
        return 0.25 * b if b <= 400.0 else 100.0
    return 0.5 * b if b <= 400.0 else 200.0


def _b_exigido(celula, c1: float) -> float:
    """Largura exigida por uma célula para o ``c1`` dado, mm: a menor ``b``
    entre as alternativas cujo ``c1`` cabe; infinito na célula 'a' ou se
    nenhuma alternativa cabe."""
    if celula is None:
        return math.inf
    bs = [b for b, c in celula if c <= c1 + 1e-6]
    return min(bs) if bs else math.inf


def _vizinhos(valor: float, grade: tuple) -> list[tuple[float, float]]:
    """Os dois pontos da grade em volta de ``valor`` com os pesos da
    interpolação linear; abaixo do primeiro, o primeiro (lado seguro nas
    três entradas: menos esbeltez, menos normal, mais armadura que a
    tabela); ``[]`` acima do último."""
    if valor <= grade[0] + 1e-12:
        return [(grade[0], 1.0)]
    for a, b in zip(grade, grade[1:]):
        if valor <= b + 1e-12:
            t = (valor - a) / (b - a)
            return [(a, 1.0 - t), (b, t)]
    return []


def _anexo_e(v: VerificacaoIncendio, As_Ac: float) -> MetodoIncendio:
    """Tabelas E.1 a E.9 com a interpolação linear do E.3 em omega, nu_fi e
    lambda_fi sobre a largura exigida para o ``c1`` da seção; ``e`` vai para
    a categoria de ``e_max`` de cima."""
    m = MetodoIncendio("Método tabular geral (Anexo E)")
    if v.omega < OMEGAS[0] - 1e-9:
        m.aplicavel = False
        m.motivo = (f"ω = {num(v.omega, 3)} < 0,1, abaixo da primeira tabela "
                    f"(E.1); o anexo não se aplica")
        return m
    # acima de ω = 1,0, a tabela de 1,0 (mais armadura que ela: lado seguro)
    pesos_w = _vizinhos(min(v.omega, OMEGAS[-1]), OMEGAS)
    cats = [c for c in CATEGORIAS_E if v.e_fi <= _limite_e(c, v.b) + 1e-9]
    if not cats:
        m.aplicavel = False
        m.motivo = (f"e = {num(v.e_fi, 1)} mm acima do e_max da última "
                    f"categoria ({num(_limite_e('0,5b', v.b), 0)} mm)")
        return m
    cat = cats[0]
    pesos_l = _vizinhos(v.lam_fi, LINHAS_LAMBDA)
    if not pesos_l:
        m.aplicavel = False
        m.motivo = f"λfi = {num(v.lam_fi, 1)} > 80, fora das tabelas"
        return m
    pesos_n = _vizinhos(v.nu_fi, COLUNAS_NU)
    if not pesos_n:
        m.aplicavel = False
        m.motivo = f"νfi = {num(v.nu_fi, 3)} > 0,7, fora das tabelas"
        return m
    b_req = 0.0
    cantos = []
    for w, pw in pesos_w:
        for lam, pl in pesos_l:
            for nu, pn in pesos_n:
                cel = TABELAS_E[(w, cat)][(v.trrf, int(lam))][
                    COLUNAS_NU.index(nu)]
                br = _b_exigido(cel, v.c1)
                peso = pw * pl * pn
                if peso > 1e-12:
                    cantos.append((w, int(lam), nu, cel, br))
                    b_req = math.inf if math.isinf(br) else b_req + peso * br
    nums = sorted({1 + 3 * OMEGAS.index(w) + CATEGORIAS_E.index(cat)
                   for w, _ in pesos_w})
    entrada = (f"Tabela(s) E.{'/E.'.join(str(n) for n in nums)} (e_max = "
               f"{num(_limite_e(cat, v.b), 0)} mm), TRRF {v.trrf}, "
               f"ω = {num(v.omega, 3)}, λfi = {num(v.lam_fi, 1)}, "
               f"νfi = {num(v.nu_fi, 3)}, c1 = {num(v.c1, 0)} mm; células: "
               + "; ".join(
                   f"ω {num(w, 1)}/λ {lam}/ν {num(nu, 2)} = "
                   + ("a" if cel is None else
                      ":".join(f"{b}/{c}" for b, c in cel))
                   for w, lam, nu, cel, _ in cantos))
    if math.isinf(b_req):
        m.ok = False
        m.detalhe = entrada
        m.motivo = ("uma das células da interpolação pede largura acima de "
                    "600 mm (nota a) ou c1 maior que o da seção")
        return m
    m.ok = v.b >= b_req - 1e-6
    m.detalhe = (entrada + f" → bmín interpolada = {num(b_req, 0)} mm; a "
                 f"seção tem b = {num(v.b, 0)} mm")
    if not m.ok:
        m.motivo = f"b = {num(v.b, 0)} mm < bmín = {num(b_req, 0)} mm"
    if As_Ac >= 0.02 and v.trrf >= 90:
        v.avisos.append(av.construtivo(
            "Incêndio (Anexo E, E.2): com As >= 2 % Ac e TRRF >= 90 min, a "
            "armadura tem de ficar distribuída uniformemente ao longo dos "
            "lados da seção."))
    return m


def _analitico(v: VerificacaoIncendio, n_barras: int, As_Ac: float,
               b_linha: float) -> MetodoIncendio:
    m = MetodoIncendio("Método analítico (8.3.2)")
    fora = []
    if As_Ac > 0.04 + 1e-9:
        fora.append(f"As/Ac = {num(As_Ac * 100, 2)} % > 4 %")
    if not 25.0 - 1e-9 <= v.c1 <= 80.0 + 1e-9:
        fora.append(f"c1 = {num(v.c1, 0)} mm fora de 25 a 80 mm")
    if b_linha < 190.0 - 1e-9:
        fora.append(f"b' = {num(b_linha, 0)} mm < 190 mm")
    if v.e_fi > 0.15 * v.b + 1e-9:
        fora.append(f"e = {num(v.e_fi, 1)} mm > 0,15 b = {num(0.15 * v.b, 1)} mm")
    if v.lef_fi > 6.0 + 1e-9:
        fora.append(f"ℓef,fi = {num(v.lef_fi, 2)} m > 6 m")
    R_mu = 83.0 * (1.0 - v.mu_fi)
    R_a = 1.60 * (v.c1 - 30.0)
    R_l = 9.60 * (5.0 - v.lef_fi)
    R_b = 0.09 * b_linha if b_linha <= 450.0 else 40.5
    R_n = 0.0 if n_barras <= 4 else 12.0
    soma = R_mu + R_a + R_l + R_b + R_n
    trf = 120.0 * (max(soma, 0.0) / 120.0) ** 1.8
    m.detalhe = (f"Rμ = 83 (1 − {num(v.mu_fi, 3)}) = {num(R_mu, 1)}; Ra = "
                 f"1,60 ({num(v.c1, 0)} − 30) = {num(R_a, 1)}; Rℓ = 9,60 (5 − "
                 f"{num(v.lef_fi, 2)}) = {num(R_l, 1)}; Rb = "
                 + (f"0,09·{num(b_linha, 0)}" if b_linha <= 450.0 else "40,5")
                 + f" = {num(R_b, 1)}; Rn = {num(R_n, 0)} ({n_barras} barras); "
                 f"TRF = 120 ({num(soma, 1)}/120)^1,8 = {num(trf, 0)} min")
    if fora:
        m.aplicavel = False
        m.motivo = "fora dos limites de aplicação: " + "; ".join(fora)
        return m
    m.ok = trf >= v.trrf - 1e-9
    if not m.ok:
        m.motivo = f"TRF = {num(trf, 0)} min < TRRF = {v.trrf} min"
    return m


def verificar(pilar, res) -> VerificacaoIncendio:
    cfg = pilar.config
    v = VerificacaoIncendio()
    if not cfg.incendio:
        return v
    v.aplicavel = True
    v.trrf = int(cfg.trrf)
    v.faces = cfg.incendio_faces
    sec = pilar.secao
    if v.trrf not in TRRF_VALIDOS:
        v.avisos.append(av.erro(
            f"Incêndio: TRRF = {v.trrf} min não é um dos valores das "
            f"tabelas da NBR 15200 (30, 60, 90, 120, 180)."))
        v.aplicavel = False
        return v
    circular = sec.tipo == "circular"
    if sec.tipo not in ("retangular", "circular"):
        v.aplicavel = False
        v.avisos.append(av.construtivo(
            f"Incêndio (NBR 15200): os métodos simplificados de pilar "
            f"(Tabela 12, 8.3.2 e Anexo E) cobrem seção retangular ou "
            f"circular; a seção {sec.tipo} fica sem verificação -- método "
            f"avançado (8.4) ou experimental (8.5)."))
        return v
    a = res.arranjo
    if a is None or not a.barras:
        v.aplicavel = False
        return v
    dims = (sec.hx, sec.hx) if circular else sorted((sec.hx, sec.hy))
    v.b, v.h = 10.0 * dims[0], 10.0 * dims[1]
    v.c1 = _c1(a, sec.contornos(), circular, sec.hx)
    N, ex, ey, v.origem_sd = _solicitacoes(pilar)
    v.N_fi = N
    if N <= 0.0:
        v.aplicavel = False
        v.avisos.append(av.construtivo(
            "Incêndio: a normal em incêndio não é de compressão; os métodos "
            "de pilar da NBR 15200 não se aplicam (tirante: 8.2.5)."))
        return v
    # excentricidade de 1ª ordem, com o mínimo da 6118 (E.2), a maior das
    # duas direções -- as tabelas a comparam com a menor dimensão
    e_min = {d: excentricidade_minima(sec.altura(d)) for d in ("x", "y")}
    v.e_fi = 10.0 * max(max(ex, e_min["x"]), max(ey, e_min["y"]))
    v.mu_fi = (cfg.incendio_mu_fi if cfg.incendio_mu_fi > 0.0
               else min(N / pilar.Nd, 1.0) if pilar.Nd > 0 else 1.0)
    v.lef_fi = cfg.incendio_lef_fator * max(pilar.le("x"), pilar.le("y")) / 100.0
    prop = sec.propriedades()
    i_min = math.sqrt(min(prop.Ix, prop.Iy) / prop.area)
    v.lam_fi = v.lef_fi * 100.0 / i_min
    Ac, As = prop.area, a.As
    fcd = pilar.concreto.fcd_kNcm2
    fyd = pilar.aco.fyd_kNcm2
    v.omega = As * fyd / (Ac * fcd)
    v.nu_fi = N / (0.70 * (Ac * fcd + As * fyd))
    As_Ac = As / Ac
    if v.faces == "uma":
        bmin, c1min = TABELA_12[v.trrf]
        m = MetodoIncendio("Tabela 12 — uma face exposta (8.2.4)")
        m.ok = v.b >= bmin - 1e-6 and v.c1 >= c1min - 1e-6
        m.detalhe = (f"TRRF {v.trrf}: bmín/c1 = {bmin}/{c1min} mm; a seção "
                     f"tem {num(v.b, 0)}/{num(v.c1, 0)} mm")
        if not m.ok:
            m.motivo = f"b/c1 abaixo de {bmin}/{c1min} mm"
        v.metodos.append(m)
    else:
        # b' = 2 Ac/(b + h) para h <= 1,5 b; 1,2 b além (Ac: cm² -> mm²)
        b_linha = (2.0 * Ac * 100.0 / (v.b + v.h) if v.h <= 1.5 * v.b
                   else 1.2 * v.b)
        v.metodos.append(_analitico(v, len(a.barras), As_Ac, b_linha))
        v.metodos.append(_anexo_e(v, As_Ac))
    aplicaveis = [m for m in v.metodos if m.aplicavel]
    if not aplicaveis:
        v.avisos.append(av.erro(
            f"Incêndio (NBR 15200, TRRF {v.trrf} min): nenhum método "
            f"simplificado se aplica -- "
            + "; ".join(f"{m.nome}: {m.motivo}" for m in v.metodos)
            + ". É preciso o método avançado (8.4) ou o experimental (8.5)."))
    elif not v.ok:
        v.avisos.append(av.erro(
            f"Incêndio (NBR 15200, TRRF {v.trrf} min): não atende -- "
            + "; ".join(f"{m.nome}: {m.motivo}" for m in aplicaveis)
            + ". Aumente a seção ou o cobrimento (c1)."))
    v.avisos.append(av.construtivo(
        "Incêndio: os métodos de pilar da NBR 15200 (8.3.2 e Anexo E) valem "
        "para estrutura de nós fixos, ou com efeitos globais de 2ª ordem "
        "até 30 % dos de 1ª ordem (γz <= 1,30) -- confira na estrutura. "
        f"μfi = {num(v.mu_fi, 3)} com NRd tomado igual a Nd (o lado seguro), "
        "e o revestimento fora de c1."))
    return v
