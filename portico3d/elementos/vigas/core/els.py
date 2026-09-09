# -*- coding: utf-8 -*-
"""
els.py
Verificações de serviço da NBR 6118: deformação excessiva (17.3.2) e
abertura de fissuras (17.3.3).

A flecha imediata é obtida com a rigidez equivalente de Branson (Fórmula
17.3.2.1.1), calculada tramo a tramo a partir do momento máximo da combinação
quase permanente; a flecha diferida vem do coeficiente alfa_f do item
17.3.2.1.2. A abertura de fissuras usa as duas expressões do item 17.3.3.2,
com a tensão da armadura no Estádio II.

Unidades: momentos em kN.m, comprimentos em cm, tensões em kN/cm².
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .materiais import Aco, Concreto
from .modelo import Secao
from . import avisos as av


# ---------------------------------------------------------------------------
# Estádio II
# ---------------------------------------------------------------------------

@dataclass
class EstadioII:
    """Posição da linha neutra e inércia da seção fissurada."""

    x: float                  # cm
    I: float                  # cm^4
    alpha_e: float


def estadio_ii(secao: Secao, alpha_e: float, As: float, d: float,
               As_linha: float = 0.0, d_linha: float = 0.0,
               face: str = "inferior") -> EstadioII:
    """Linha neutra e inércia no Estádio II puro (seção homogeneizada).

    ``face`` indica onde está a armadura tracionada: ``"inferior"`` para
    momento positivo e ``"superior"`` para momento negativo.
    """
    mesa_comprimida = (secao.tipo == "T" and face == "inferior") or \
                      (secao.tipo == "T invertida" and face == "superior")
    bf = secao.bf if mesa_comprimida else secao.bw
    hf = secao.hf if mesa_comprimida else 0.0
    b = bf if hf > 0.0 else secao.bw

    a1 = b / 2.0
    a2 = alpha_e * As + (alpha_e - 1.0) * As_linha
    a3 = -(alpha_e * As * d + (alpha_e - 1.0) * As_linha * d_linha)
    x = (-a2 + math.sqrt(a2 * a2 - 4.0 * a1 * a3)) / (2.0 * a1)

    if hf > 0.0 and x > hf:      # a linha neutra desce da mesa para a alma
        bw = secao.bw
        a1 = bw / 2.0
        a2 = (bf - bw) * hf + alpha_e * As + (alpha_e - 1.0) * As_linha
        a3 = -((bf - bw) * hf * hf / 2.0 + alpha_e * As * d
               + (alpha_e - 1.0) * As_linha * d_linha)
        x = (-a2 + math.sqrt(a2 * a2 - 4.0 * a1 * a3)) / (2.0 * a1)
        I = (bw * x ** 3 / 3.0 + (bf - bw) * hf ** 3 / 12.0
             + (bf - bw) * hf * (x - hf / 2.0) ** 2
             + alpha_e * As * (d - x) ** 2
             + (alpha_e - 1.0) * As_linha * (x - d_linha) ** 2)
    else:
        I = (b * x ** 3 / 3.0 + alpha_e * As * (d - x) ** 2
             + (alpha_e - 1.0) * As_linha * (x - d_linha) ** 2)
    return EstadioII(x=x, I=I, alpha_e=alpha_e)


# ---------------------------------------------------------------------------
# Rigidez equivalente
# ---------------------------------------------------------------------------

def momento_fissuracao(secao: Secao, concreto: Concreto, face: str,
                       estado: str = "deformacao") -> float:
    """Momento de fissuração, kN.m (item 17.3.1).

    ``estado`` = ``"deformacao"`` usa fct = fctm; ``"formacao"`` usa fctk,inf.

    O fator de forma do item 17.3.1 é 1,5 na seção retangular, 1,2 na T e
    duplo T e **1,3 na I e na T invertida** -- este último faltava.
    """
    alpha = {"retangular": 1.5, "T": 1.2, "T invertida": 1.3}.get(
        secao.tipo, 1.2)
    fct = concreto.fctm if estado == "deformacao" else concreto.fctk_inf
    fct /= 10.0                                    # kN/cm²
    yt = secao.y_cg if face == "inferior" else secao.h - secao.y_cg
    return alpha * fct * secao.inercia / yt / 100.0


def inercia_equivalente(secao: Secao, concreto: Concreto, Ma: float,
                        Mr: float, I_II: float) -> tuple[float, str]:
    """Inércia equivalente de Branson, cm^4 (Fórmula 17.3.2.1.1)."""
    Ic = secao.inercia
    if abs(Ma) < 1e-9 or abs(Mr) >= abs(Ma):
        return Ic, "seção não fissurada (Ma <= Mr)"
    r = (Mr / Ma) ** 3
    I_eq = min(r * Ic + (1.0 - r) * I_II, Ic)
    return I_eq, f"Branson com Mr/Ma = {Mr / Ma:.3f}"


def coeficiente_fluencia(t_meses: float, t0_meses: float) -> float:
    """Delta xi do item 17.3.2.1.2 entre t0 e t."""
    def xi(t: float) -> float:
        if t <= 0.0:
            return 0.0
        if t >= 70.0:
            return 2.0
        return 0.68 * (0.996 ** t) * t ** 0.32
    return xi(t_meses) - xi(t0_meses)


def alfa_f(t_meses: float, t0_meses: float, rho_linha: float) -> float:
    """Coeficiente de flecha diferida (17.3.2.1.2)."""
    return coeficiente_fluencia(t_meses, t0_meses) / (1.0 + 50.0 * rho_linha)


@dataclass
class ResultadoFlecha:
    """Flechas de um tramo e a comparação com os limites da Tabela 13.3."""

    tramo: int
    vao: float                # m, vão de referência (2L no balanço)
    balanco: bool
    I_bruta: float            # cm^4
    I_II: float               # cm^4
    I_eq: float               # cm^4
    Mr: float                 # kN.m
    Ma: float                 # kN.m
    origem_inercia: str
    alfa_f: float
    f_imediata: float         # cm, combinação quase permanente
    f_diferida: float         # cm
    f_total: float            # cm
    f_apos_alvenaria: float   # cm
    limite_visual: float      # cm
    limite_alvenaria: float   # cm
    ok_visual: bool
    ok_alvenaria: bool
    #: Tabela 13.3, demais linhas verificadas quando o critério está ligado
    f_variavel: float = 0.0        # cm, flecha só das ações variáveis
    limite_vibracao: float = 0.0   # cm; 0 = não verificado
    ok_vibracao: bool = True
    limite_piso_total: float = 0.0
    limite_piso_apos: float = 0.0
    ok_piso: bool = True
    parede: str = "alvenaria"
    avisos: list[str] = field(default_factory=list)

    @property
    def veredito(self) -> str:
        return "OK" if (self.ok_visual and self.ok_alvenaria
                        and self.ok_vibracao and self.ok_piso) else "NÃO OK"


def avaliar_flecha(tramo: int, vao_m: float, balanco: bool, secao: Secao,
                   concreto: Concreto, Ma: float, I_II: float,
                   f_imediata_cm: float, f_permanente_cm: float,
                   rho_linha: float, t: float, t0: float,
                   lim_visual: float, lim_alvenaria: float,
                   face: str = "inferior", parede: str = "alvenaria",
                   f_variavel_cm: float = 0.0,
                   lim_vibracao: float = 0.0,
                   lim_piso_total: float = 0.0,
                   lim_piso_apos: float = 0.0) -> ResultadoFlecha:
    """Compara as flechas de um tramo com os limites da Tabela 13.3.

    ``f_imediata_cm`` é a flecha elástica da combinação quase permanente já
    calculada com a inércia equivalente; ``f_permanente_cm`` é a parcela das
    ações permanentes, usada para estimar o deslocamento que ocorre depois da
    execução da alvenaria.

    Além da aceitabilidade visual e do que se apoia na viga, a tabela traz
    outras linhas que só se aplicam a certos usos e por isso entram como
    critério opcional: **vibrações sentidas no piso** (flecha das ações
    variáveis <= L/350) e **pavimentos que devem permanecer planos**
    (L/350 no total e L/600 no deslocamento posterior à construção do piso).
    """
    Mr = momento_fissuracao(secao, concreto, face)
    I_eq, origem = inercia_equivalente(secao, concreto, Ma, Mr, I_II)
    af = alfa_f(t, t0, rho_linha)
    f_dif = af * f_imediata_cm
    f_total = f_imediata_cm + f_dif
    f_apos = f_total - f_permanente_cm

    vao_ref = 2.0 * vao_m if balanco else vao_m
    lim_v = vao_ref * 100.0 / lim_visual
    # a Tabela 13.3 dá dois valores para o que se apoia na viga -- "L/500 e
    # 10 mm" na alvenaria, "L/250 e 25 mm" na divisória leve -- e os dois
    # valem; acima de certo vão é o absoluto que governa
    denom, absoluto, descricao_parede = PAREDE_APOIADA.get(
        parede, PAREDE_APOIADA["alvenaria"])
    if denom <= 0.0:
        lim_a = float("inf")
    else:
        if abs(denom - 500.0) < 1e-9:
            denom = lim_alvenaria        # respeita o critério do usuário
        lim_a = min(vao_ref * 100.0 / denom, absoluto)

    avisos: list[str] = []
    if f_total < 0.0:
        avisos.append(av.construtivo(
            "O deslocamento do tramo é para cima, imposto pela rotação do "
            "apoio; o valor é comparado em módulo."))
    if abs(f_total) > lim_v:
        avisos.append(av.erro(f"Flecha total {f_total:.2f} cm supera o limite de "
                      f"aceitabilidade visual L/{lim_visual:g} = {lim_v:.2f} cm "
                      f"(Tabela 13.3)."))
    if abs(f_apos) > lim_a:
        governa = (f"pelo limite absoluto de {absoluto:.1f} cm"
                   if vao_ref * 100.0 / denom > absoluto
                   else f"por L/{denom:g}")
        avisos.append(av.erro(
            f"Deslocamento após a construção de {descricao_parede}: "
            f"{f_apos:.2f} cm supera {lim_a:.2f} cm, governado {governa} "
            f"(a Tabela 13.3 exige L/{denom:g} e {absoluto:.1f} cm)."))

    # -- vibrações sentidas no piso ----------------------------------------
    lim_vib = vao_ref * 100.0 / lim_vibracao if lim_vibracao > 0 else 0.0
    ok_vib = lim_vib <= 0.0 or abs(f_variavel_cm) <= lim_vib
    if not ok_vib:
        avisos.append(av.erro(
            f"Vibrações sentidas no piso: a flecha das ações variáveis "
            f"{f_variavel_cm:.2f} cm supera L/{lim_vibracao:g} = "
            f"{lim_vib:.2f} cm (Tabela 13.3)."))

    # -- pavimentos que devem permanecer planos ----------------------------
    lim_pt = vao_ref * 100.0 / lim_piso_total if lim_piso_total > 0 else 0.0
    lim_pa = vao_ref * 100.0 / lim_piso_apos if lim_piso_apos > 0 else 0.0
    ok_piso = True
    if lim_pt > 0.0 and abs(f_total) > lim_pt:
        ok_piso = False
        avisos.append(av.erro(
            f"Pavimento que deve permanecer plano: flecha total "
            f"{f_total:.2f} cm supera L/{lim_piso_total:g} = {lim_pt:.2f} cm "
            f"(Tabela 13.3; a contraflecha isolada não pode gerar desvio "
            f"maior que L/350)."))
    if lim_pa > 0.0 and abs(f_apos) > lim_pa:
        ok_piso = False
        avisos.append(av.erro(
            f"Pavimento que deve permanecer plano: deslocamento após a "
            f"construção do piso {f_apos:.2f} cm supera "
            f"L/{lim_piso_apos:g} = {lim_pa:.2f} cm (Tabela 13.3)."))
    return ResultadoFlecha(
        tramo=tramo, vao=vao_m, balanco=balanco, I_bruta=secao.inercia,
        I_II=I_II, I_eq=I_eq, Mr=Mr, Ma=Ma, origem_inercia=origem, alfa_f=af,
        f_imediata=f_imediata_cm, f_diferida=f_dif, f_total=f_total,
        f_apos_alvenaria=f_apos, limite_visual=lim_v, limite_alvenaria=lim_a,
        f_variavel=f_variavel_cm, limite_vibracao=lim_vib, ok_vibracao=ok_vib,
        limite_piso_total=lim_pt, limite_piso_apos=lim_pa, ok_piso=ok_piso,
        parede=parede,
        ok_visual=abs(f_total) <= lim_v, ok_alvenaria=abs(f_apos) <= lim_a,
        avisos=avisos)


# ---------------------------------------------------------------------------
# Abertura de fissuras
# ---------------------------------------------------------------------------

@dataclass
class ResultadoFissuracao:
    """Abertura característica de fissuras de uma região."""

    regiao: str
    M_servico: float          # kN.m, combinação frequente
    x_II: float               # cm
    sigma_s: float            # kN/cm²
    phi: float                # mm
    Acri: float               # cm²
    rho_ri: float
    wk_1: float               # mm
    wk_2: float               # mm
    wk: float                 # mm
    wk_limite: float          # mm
    ok: bool
    fissurada: bool
    avisos: list[str] = field(default_factory=list)

    @property
    def veredito(self) -> str:
        return "OK" if self.ok else "NÃO OK"


#: distância máxima, em bitolas, do lado do retângulo de envolvimento ao eixo
#: da barra (17.3.3.2: "um retângulo cujos lados não distem mais de 7,5 f do
#: eixo da barra")
MEIA_ENVOLTORIA = 7.5


def envolvimento(secao: Secao, As: float, phi_mm: float, camadas: list[int],
                 av: float, y_1: float) -> tuple[float, float, float, float]:
    """Região de envolvimento da camada mais tracionada -- item 17.3.3.2.

    A norma manda tomar, "para cada elemento **ou grupo de elementos** das
    armaduras", um retângulo cujos lados não distem mais de 7,5 f do eixo da
    barra (Figura 17.4), e a taxa ``rho_ri`` da armadura *daquele grupo* em
    relação a *aquela* área. O grupo que controla é a **camada mais
    tracionada**: é a de maior tensão, e é a que fica na face onde a fissura
    aparece.

    Daí os três lados do retângulo:

    * para baixo, até a face tracionada -- o concreto acaba ali;
    * para cima, 7,5 f acima do eixo da camada, **ou** metade da distância
      eixo a eixo até a camada seguinte, o que for menor: passando desse meio,
      o envolvimento seria da camada de cima, que tem o seu próprio;
    * na largura, 15 f por barra da camada, limitado a ``bw``.

    Devolve ``(Acri, rho_ri, d_1, As_1)``, com ``d_1`` a altura útil da camada
    considerada -- é nela que se calcula ``sigma_si``, "a tensão de tração no
    centroide da armadura considerada".
    """
    n = sum(camadas) or 1
    n_1 = camadas[0] if camadas else n
    As_1 = As * n_1 / n
    phi_cm = phi_mm / 10.0
    passo = phi_cm + av                       # eixo a eixo entre camadas
    acima = MEIA_ENVOLTORIA * phi_cm
    if len(camadas) > 1:
        acima = min(acima, passo / 2.0)
    altura = min(y_1 + acima, secao.h)
    largura = min(secao.bw, n_1 * 2.0 * MEIA_ENVOLTORIA * phi_cm)
    Acri = altura * largura
    return Acri, (As_1 / Acri if Acri > 0 else 0.0), secao.h - y_1, As_1


def primeira_camada(y_cg: float, camadas: list[int], phi_mm: float,
                    av: float) -> float:
    """Distância do eixo da camada mais tracionada à face, cm.

    Sai do que o arranjo já sabe: as camadas estão em ``y_1 + i.passo`` e o
    centro de gravidade é a média ponderada, logo ``y_1`` se recupera dela sem
    precisar do cobrimento nem da bitola do estribo.
    """
    n = sum(camadas) or 1
    if len(camadas) <= 1:
        return y_cg
    passo = phi_mm / 10.0 + av
    momento = sum(i * c for i, c in enumerate(camadas)) / n
    return y_cg - passo * momento


def abertura_fissuras(secao: Secao, concreto: Concreto, aco: Aco,
                      M_servico: float, As: float, d: float, phi_mm: float,
                      n_barras: int, wk_limite: float, regiao: str = "",
                      As_linha: float = 0.0, d_linha: float = 0.0,
                      face: str = "inferior",
                      camadas: list[int] | None = None,
                      av_camadas: float = 2.0,
                      y_1: float | None = None) -> ResultadoFissuracao:
    """Abertura característica wk, mm, pelas duas expressões de 17.3.3.2.

    O estado da seção (``x``, ``I``) é do Estádio II com **toda** a armadura e
    o ``d`` do centro de gravidade; a tensão ``sigma_si`` e a taxa ``rho_ri``,
    porém, são da **camada mais tracionada**, que é o grupo de barras que
    controla a fissura da face. Ver `envolvimento`.
    """
    alpha_e = aco.Es / concreto.Ecs
    e2 = estadio_ii(secao, alpha_e, As, d, As_linha, d_linha, face)
    Mr = momento_fissuracao(secao, concreto, face, estado="formacao")
    fissurada = abs(M_servico) > Mr

    cams = list(camadas) if camadas else [max(n_barras, 1)]
    # com bitola única -- o caso do programa -- recuperar y_1 do centro de
    # gravidade é exato, porque o passo entre camadas é o mesmo; com camadas de
    # bitolas diferentes não é, e aí o chamador passa y_1
    y_cam1 = primeira_camada(secao.h - d, cams, phi_mm,
                             av_camadas) if y_1 is None else y_1
    Acri, rho_ri, d_1, _ = envolvimento(secao, As, phi_mm, cams, av_camadas,
                                        y_cam1)

    # tensão no centroide da armadura considerada, Estádio II
    sigma_s = (alpha_e * abs(M_servico) * 100.0 * (d_1 - e2.x) / e2.I
               if e2.I else 0.0)

    Esi = aco.Es / 10.0                              # kN/cm²
    fctm = concreto.fctm / 10.0                      # kN/cm²
    k = phi_mm / (12.5 * aco.eta_1)
    wk1 = k * sigma_s / Esi * 3.0 * sigma_s / fctm
    wk2 = k * sigma_s / Esi * (4.0 / rho_ri + 45.0) if rho_ri > 0 else float("inf")
    wk = min(wk1, wk2) if fissurada else 0.0

    avisos: list[str] = []
    if wk > wk_limite:
        avisos.append(av.erro(f"wk = {wk:.3f} mm supera o limite de {wk_limite:.2f} mm "
                      f"da Tabela 13.4; aumente o número de barras ou reduza "
                      f"a bitola."))
    return ResultadoFissuracao(
        regiao=regiao, M_servico=M_servico, x_II=e2.x, sigma_s=sigma_s,
        phi=phi_mm, Acri=Acri, rho_ri=rho_ri, wk_1=wk1, wk_2=wk2, wk=wk,
        wk_limite=wk_limite, ok=wk <= wk_limite, fissurada=fissurada,
        avisos=avisos)


#: Limites da Tabela 13.3 para o que se apoia na viga: (denominador do vão,
#: limite absoluto em cm, descrição).
PAREDE_APOIADA = {
    "alvenaria": (500.0, 1.0, "alvenaria, caixilhos e revestimentos"),
    "divisoria": (250.0, 2.5, "divisórias leves e caixilhos telescópicos"),
    "nenhuma": (0.0, 0.0, "nada apoiado na viga"),
}

#: deslocamento absoluto após a construção da parede, cm (Tabela 13.3)
DESLOCAMENTO_ABSOLUTO_PAREDE = 1.0

#: teto da armadura de pele, cm²/m por face (17.3.5.2.3)
PELE_MAXIMA = 5.0
#: espaçamento máximo da armadura de pele, cm (17.3.5.2.3 e 18.3.5)
PELE_ESPACAMENTO_MAXIMO = 20.0


def espacamento_pele(d: float) -> float:
    """Espaçamento máximo da armadura de pele, cm (18.3.5).

    O item 18.3.5 é mais restritivo que o 17.3.5.2.3: o afastamento entre as
    barras não pode passar de **d/3 nem de 20 cm**. Em viga de altura pouco
    acima de 60 cm é o d/3 que governa.
    """
    return min(PELE_ESPACAMENTO_MAXIMO, d / 3.0) if d > 0 else \
        PELE_ESPACAMENTO_MAXIMO


def armadura_pele(secao: Secao, aco: Aco) -> tuple[float, str]:
    """Armadura de pele exigida pelo item 17.3.5.2.3, cm²/m por face.

    O item traz um **teto**: "não sendo necessária uma armadura superior a
    5 cm²/m por face". Sem ele, uma alma de 80 cm pedia 8,0 cm²/m.
    """
    if secao.h <= 60.0:
        return 0.0, "Dispensada: h <= 60 cm (17.3.5.2.3)."
    a = 0.10 / 100.0 * secao.bw * 100.0            # 0,10 % de Ac,alma por face
    if a > PELE_MAXIMA:
        return PELE_MAXIMA, (
            f"0,10 % de Ac,alma daria {a:.1f} cm²/m por face; adotado o teto "
            f"de {PELE_MAXIMA:g} cm²/m do item 17.3.5.2.3, com espaçamento "
            f"não maior que {PELE_ESPACAMENTO_MAXIMO:g} cm.")
    return a, (f"0,10 % de Ac,alma por face, com espaçamento não maior que "
               f"{PELE_ESPACAMENTO_MAXIMO:g} cm (17.3.5.2.3).")
