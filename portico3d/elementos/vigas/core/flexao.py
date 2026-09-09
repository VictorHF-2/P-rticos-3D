# -*- coding: utf-8 -*-
"""
flexao.py
Dimensionamento à flexão simples no ELU pelo diagrama retangular equivalente
(NBR 6118, 17.2.2), para seções retangulares e em T, com armadura simples ou
dupla.

As expressões reproduzem, termo a termo, a "Calculadora de Seção Transversal"
usada como referência de validação: a linha neutra vem da equação do segundo
grau em ``y``; a armadura dupla entra quando Md ultrapassa o momento máximo
associado a x_lim; e a tensão da armadura comprimida é apresentada nas duas
convenções (com e sem desconto da área de concreto deslocada).

Unidades: forças em kN, comprimentos em cm, momentos em kN.cm na entrada
interna e kN.m na interface pública.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .materiais import Aco, Concreto, interpola_rho_min
from .modelo import Secao
from . import avisos as av

ES_KNCM2 = 21_000.0        # módulo de elasticidade do aço, kN/cm²


# ---------------------------------------------------------------------------
# Limites de ductilidade
# ---------------------------------------------------------------------------

def x_lim_rel(concreto: Concreto, aco: Aco, delta: float = 1.0) -> tuple[float, str]:
    """Relação x/d limite e a origem do limite adotado.

    Concorrem o limite de ductilidade do item 14.6.4.3 (0,45 até C50 e 0,35
    acima), o limite do domínio 3/4 (início do escoamento) e, quando há
    redistribuição, o limite do mesmo item -- ``(delta - 0,44)/1,25`` até C50 e
    ``(delta - 0,56)/1,25`` acima, que é mais restritivo.
    """
    x34 = concreto.eps_cu / (concreto.eps_cu + aco.eps_yd)
    x_duc = 0.45 if concreto.fck <= 50.0 else 0.35
    limites = [(x34, "domínio 3/4 (início do escoamento)"),
               (x_duc, "ductilidade 14.6.4.3")]
    if delta < 1.0:
        base = 0.44 if concreto.fck <= 50.0 else 0.56
        limites.append(((delta - base) / 1.25,
                        f"redistribuição delta = {delta:g}, "
                        f"(delta - {base:g})/1,25 (14.6.4.3)"))
    valor, origem = min(limites, key=lambda t: t[0])
    return valor, origem


#: taxa mínima absoluta de armadura de tração (17.3.5.2.1), fração de Ac
RHO_MIN_ABSOLUTA = 0.0015


def armadura_minima(secao: Secao, concreto: Concreto, aco: Aco,
                    d: float, face: str = "inferior") -> tuple[float, str]:
    """Armadura mínima de tração, cm², e a via pela qual foi obtida.

    O item 17.3.5.2.1 manda dimensionar a seção para
    ``Md,min = 0,8 · W0 · fctk,sup``, respeitada a taxa absoluta de 0,15 % de
    Ac, e admite **como alternativa** as taxas da Tabela 17.3 -- que a própria
    tabela restringe a **vigas de seção retangular**. Por isso a seção
    retangular usa a tabela (é o caminho consagrado e mais simples) e as
    demais formas usam o momento mínimo, sempre com o piso de 0,15 %.
    """
    piso = RHO_MIN_ABSOLUTA * secao.area
    if secao.tipo == "retangular":
        return (max(interpola_rho_min(concreto.fck) / 100.0 * secao.area,
                    piso),
                "Tabela 17.3 (seção retangular), com o piso de 0,15 % de Ac")
    w0 = secao.w_inferior if face == "inferior" else secao.w_superior
    Md_min = 0.8 * w0 * concreto.fctk_sup / 10.0          # kN.cm
    As = _as_armadura_simples(secao, concreto, aco, Md_min, d, face)
    return (max(As, piso),
            f"Md,min = 0,8·W0·fctk,sup = {Md_min / 100.0:.2f} kN.m "
            f"(17.3.5.2.1), com o piso de 0,15 % de Ac")


def _as_armadura_simples(secao: Secao, concreto: Concreto, aco: Aco,
                         Md_kNcm: float, d: float, face: str) -> float:
    """Armadura tracionada para um momento pequeno, sem armadura dupla."""
    sig = concreto.sigma_cd
    mesa_comprimida = (secao.tipo == "T" and face == "inferior") or \
                      (secao.tipo == "T invertida" and face == "superior")
    b = secao.bf if (mesa_comprimida and secao.hf > 0.0) else secao.bw
    rad = d * d - 2.0 * Md_kNcm / (b * sig)
    if rad < 0.0:
        return 0.0
    y = d - math.sqrt(rad)
    if mesa_comprimida and secao.hf > 0.0 and y > secao.hf:
        Nc = (secao.bw * y + (secao.bf - secao.bw) * secao.hf) * sig
    else:
        Nc = b * y * sig
    return Nc / aco.fyd_kNcm2


def dominio(x_d: float, concreto: Concreto, aco: Aco) -> str:
    """Domínio de deformação correspondente a x/d (item 17.2.2)."""
    x23 = concreto.eps_cu / (concreto.eps_cu + 10.0e-3)
    x34 = concreto.eps_cu / (concreto.eps_cu + aco.eps_yd)
    if x_d <= 1e-9:
        return "1 (tração)"
    if x_d < x23:
        return "2"
    if x_d < x34:
        return "3"
    if x_d <= 1.0:
        return "4"
    return "4a/5"


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class ResultadoFlexao:
    """Saída do dimensionamento à flexão de uma seção."""

    Md: float                 # kN.m (valor absoluto usado no cálculo)
    face: str                 # 'inferior' (M positivo) ou 'superior'
    d: float                  # cm
    d_linha: float            # cm
    y: float                  # cm, altura do bloco comprimido
    x: float                  # cm, linha neutra
    x_d: float
    x_lim_d: float
    origem_limite: str
    dominio: str
    As: float                 # cm², armadura tracionada
    As_linha: float           # cm², armadura comprimida (convenção adotada)
    As_linha_sigma2: float    # cm², sem descontar o concreto deslocado
    As_linha_sigma2_liq: float  # cm², descontando o concreto deslocado
    sigma2: float             # kN/cm²
    sigma2_liq: float         # kN/cm²
    eps_2: float
    As_min: float             # cm²
    As_max: float             # cm²
    Md_max: float             # kN.m, momento máximo com armadura simples
    armadura_dupla: bool
    sigma_cd: float           # kN/cm²
    avisos: list[str] = field(default_factory=list)
    memoria: dict = field(default_factory=dict)

    @property
    def As_adotado(self) -> float:
        """Armadura tracionada de projeto, respeitando As,min."""
        return max(self.As, self.As_min)

    @property
    def taxa(self) -> float:
        return self.As_adotado


# ---------------------------------------------------------------------------
# Dimensionamento
# ---------------------------------------------------------------------------

def dimensionar(secao: Secao, concreto: Concreto, aco: Aco, M_kNm: float,
                d_linha: float, h_menos_d: float, delta: float = 1.0,
                convencao_sigma2: str = "liquida") -> ResultadoFlexao:
    """Dimensiona a seção para o momento ``M_kNm`` (sinal define a face).

    ``d_linha`` é a distância do centro da armadura comprimida à face mais
    próxima e ``h_menos_d`` a distância do centro da armadura tracionada à
    face tracionada, ambos em cm.

    ``convencao_sigma2`` seleciona a armadura comprimida apresentada como
    resultado: ``"liquida"`` desconta a área de concreto deslocada pelas
    barras (prática brasileira) e ``"bruta"`` não desconta.
    """
    Md = abs(M_kNm) * 100.0                      # kN.cm
    face = "inferior" if M_kNm >= 0 else "superior"
    h = secao.h
    d = h - h_menos_d
    if d <= d_linha:
        raise ValueError("Altura útil incompatível com o cobrimento adotado.")

    sig = concreto.sigma_cd
    fyd = aco.fyd_kNcm2
    lam = concreto.lambda_

    # largura efetivamente comprimida
    mesa_comprimida = (secao.tipo == "T" and face == "inferior") or \
                      (secao.tipo == "T invertida" and face == "superior")
    b_mesa = secao.bf if mesa_comprimida else secao.bw
    hf = secao.hf if mesa_comprimida else 0.0

    x_lim_d_, origem = x_lim_rel(concreto, aco, delta)
    x_max = x_lim_d_ * d
    y_max = lam * x_max

    # momentos de referência
    if mesa_comprimida and hf > 0.0:
        M_abas = (secao.bf - secao.bw) * hf * sig * (d - hf / 2.0)
        M_mesa = secao.bf * hf * sig * (d - hf / 2.0)
        if y_max <= hf:
            Md_max = secao.bf * y_max * sig * (d - y_max / 2.0)
        else:
            Md_max = secao.bw * y_max * sig * (d - y_max / 2.0) + M_abas
    else:
        M_abas = M_mesa = 0.0
        Md_max = b_mesa * y_max * sig * (d - y_max / 2.0)

    avisos: list[str] = []
    dupla = Md > Md_max + 1e-9

    # -- linha neutra -------------------------------------------------------
    if dupla:
        y = y_max
    elif mesa_comprimida and hf > 0.0 and Md > M_mesa:
        rad = d * d - 2.0 * (Md - M_abas) / (secao.bw * sig)
        y = d - math.sqrt(max(rad, 0.0))
    else:
        b = b_mesa
        rad = d * d - 2.0 * Md / (b * sig)
        if rad < 0.0:
            raise ValueError(
                "A seção não resiste ao momento nem com armadura dupla: "
                "aumente as dimensões ou o fck.")
        y = d - math.sqrt(rad)

    x = y / lam

    # -- armadura comprimida ------------------------------------------------
    if dupla:
        eps2 = concreto.eps_cu / y * (y - lam * d_linha)
        s2 = math.copysign(fyd, eps2) if abs(eps2) > aco.eps_yd \
            else ES_KNCM2 * eps2
        s2_liq = s2 - sig if d_linha <= y else s2
        dM = Md - Md_max
        if abs(s2) < 1e-6:
            raise ValueError("A armadura comprimida não é mobilizada: "
                             "aumente a altura da seção.")
        As_linha_s2 = dM / (d - d_linha) / s2
        As_linha_s2l = dM / (d - d_linha) / s2_liq if abs(s2_liq) > 1e-6 \
            else float("inf")
        if s2_liq <= 0.0:
            avisos.append(av.erro(
                "A tensão líquida da armadura comprimida resultou não positiva; "
                "a seção é muito esbelta para armadura dupla."))
        As_linha = As_linha_s2l if convencao_sigma2 == "liquida" else As_linha_s2
        # o braço da parcela adicional independe da convenção
        Nc = _forca_concreto(secao, sig, y, b_mesa, hf, mesa_comprimida)
        As = (Nc + dM / (d - d_linha)) / fyd
        avisos.append(av.construtivo(
            "Armadura dupla: Md supera o momento máximo com armadura simples "
            f"({Md_max / 100.0:.2f} kN.m)."))
    else:
        eps2 = 0.0
        s2 = s2_liq = 0.0
        As_linha = As_linha_s2 = As_linha_s2l = 0.0
        Nc = _forca_concreto(secao, sig, y, b_mesa, hf, mesa_comprimida)
        As = Nc / fyd

    # -- armaduras limite ---------------------------------------------------
    As_min, via_as_min = armadura_minima(secao, concreto, aco, d, face)
    As_max = 0.04 * secao.area
    if As + As_linha > As_max:
        avisos.append(av.erro(f"A soma As + A's excede 4 % de Ac = {As_max:.2f} cm² "
                      f"(item 17.3.5.2.4)."))
    if As < As_min:
        avisos.append(av.construtivo(f"As calculada ({As:.2f} cm²) é inferior à mínima "
                      f"({As_min:.2f} cm²); prevalece As,min (17.3.5.2.1)."))

    x_d = x / d
    memoria = {
        "Md (kN.m)": Md / 100.0,
        "d (cm)": d,
        "d' (cm)": d_linha,
        "alfa_c.eta_c.fcd (kN/cm²)": sig,
        "lambda": lam,
        "x_lim/d": x_lim_d_,
        "origem do limite": origem,
        "y_max (cm)": y_max,
        "Md,max (kN.m)": Md_max / 100.0,
        "y (cm)": y,
        "x (cm)": x,
        "x/d": x_d,
        "domínio": dominio(x_d, concreto, aco),
        "Nc (kN)": Nc,
        "fyd (kN/cm²)": fyd,
        "As (cm²)": As,
        "As,min (cm²)": As_min,
        "As,min obtida por": via_as_min,
        "domínio limite": origem,
        "As,max (cm²)": As_max,
    }
    if mesa_comprimida and hf > 0.0:
        memoria["M,mesa (kN.m)"] = M_mesa / 100.0
        memoria["M,abas (kN.m)"] = M_abas / 100.0
        memoria["seção trabalha como"] = "retangular (y <= hf)" if y <= hf \
            else "T (y > hf)"
    if dupla:
        memoria.update({
            "eps'_s": eps2,
            "sigma'_s (kN/cm²)": s2,
            "sigma'_s líquida (kN/cm²)": s2_liq,
            "A's com sigma'_s (cm²)": As_linha_s2,
            "A's com sigma'_s líquida (cm²)": As_linha_s2l,
        })

    return ResultadoFlexao(
        Md=abs(M_kNm), face=face, d=d, d_linha=d_linha, y=y, x=x, x_d=x_d,
        x_lim_d=x_lim_d_, origem_limite=origem,
        dominio=dominio(x_d, concreto, aco), As=As, As_linha=As_linha,
        As_linha_sigma2=As_linha_s2, As_linha_sigma2_liq=As_linha_s2l,
        sigma2=s2, sigma2_liq=s2_liq, eps_2=eps2, As_min=As_min,
        As_max=As_max, Md_max=Md_max / 100.0, armadura_dupla=dupla,
        sigma_cd=sig, avisos=avisos, memoria=memoria)


def _forca_concreto(secao: Secao, sig: float, y: float, b_mesa: float,
                    hf: float, mesa_comprimida: bool) -> float:
    """Resultante de compressão do concreto, kN."""
    if mesa_comprimida and hf > 0.0 and y > hf:
        return (secao.bw * y + (secao.bf - secao.bw) * hf) * sig
    b = b_mesa if (mesa_comprimida and hf > 0.0) else secao.bw
    if not mesa_comprimida:
        b = secao.bw
    return b * y * sig


# ---------------------------------------------------------------------------
# Verificação (momento resistente de uma armadura já definida)
# ---------------------------------------------------------------------------

def momento_minimo(secao: Secao, concreto: Concreto, aco: Aco, d: float,
                   face: str = "inferior") -> float:
    """Momento, kN.m, que a armadura **mínima** da face já resiste.

    Abaixo dele o dimensionamento não pede armadura acima da mínima: o
    escalonamento não tem o que cortar e a armadura é a construtiva da face.
    É a fronteira útil de leitura do diagrama de momentos.
    """
    As_min, _ = armadura_minima(secao, concreto, aco, d, face)
    return momento_resistente(secao, concreto, aco, As_min, d, face=face)


def momento_resistente(secao: Secao, concreto: Concreto, aco: Aco,
                       As: float, d: float, As_linha: float = 0.0,
                       d_linha: float = 0.0, face: str = "inferior") -> float:
    """Momento resistente, kN.m, de uma seção com armadura conhecida.

    Usa o mesmo bloco retangular do dimensionamento e resolve o equilíbrio
    iterativamente, já que a tensão da armadura comprimida depende de x.
    """
    if As <= 0.0:
        return 0.0
    sig = concreto.sigma_cd
    fyd = aco.fyd_kNcm2
    lam = concreto.lambda_
    mesa_comprimida = (secao.tipo == "T" and face == "inferior") or \
                      (secao.tipo == "T invertida" and face == "superior")
    bf = secao.bf if mesa_comprimida else secao.bw
    hf = secao.hf if mesa_comprimida else 0.0

    y = 0.0
    for _ in range(60):
        s2 = 0.0
        if As_linha > 0.0 and y > 0.0:
            eps2 = concreto.eps_cu / y * (y - lam * d_linha)
            s2 = math.copysign(fyd, eps2) if abs(eps2) > aco.eps_yd \
                else ES_KNCM2 * eps2
            if d_linha <= y:
                s2 -= sig
        alvo = As * fyd - As_linha * s2
        if hf > 0.0 and alvo > bf * hf * sig:
            y_novo = (alvo - (bf - secao.bw) * hf * sig) / (secao.bw * sig)
        else:
            y_novo = alvo / (bf * sig)
        y_novo = max(min(y_novo, secao.h), 0.0)
        if abs(y_novo - y) < 1e-8:
            y = y_novo
            break
        y = y_novo

    if hf > 0.0 and y > hf:
        Mc = (secao.bw * y * sig * (d - y / 2.0)
              + (bf - secao.bw) * hf * sig * (d - hf / 2.0))
    else:
        b = bf if hf > 0.0 else secao.bw
        Mc = b * y * sig * (d - y / 2.0)
    if As_linha > 0.0:
        eps2 = concreto.eps_cu / y * (y - lam * d_linha) if y > 0 else 0.0
        s2 = math.copysign(fyd, eps2) if abs(eps2) > aco.eps_yd \
            else ES_KNCM2 * eps2
        if d_linha <= y:
            s2 -= sig
        Mc += As_linha * s2 * (d - d_linha)
    return Mc / 100.0
