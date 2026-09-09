# -*- coding: utf-8 -*-
"""
cisalhamento.py
Força cortante no pilar -- item 17.4 da ABNT NBR 6118:2026, modelo de
cálculo I.

Por que um programa de pilares precisa disto, se o estribo de pilar sai dos
critérios construtivos do item 18.4.3? Porque a própria norma diz **quando**
esses critérios bastam. O item 17.4.1.1.2-c) dispensa a armadura transversal
mínima de cisalhamento nos "pilares e elementos lineares de fundação
submetidos predominantemente à compressão" que atendam, simultaneamente, na
combinação mais desfavorável em ELU e com a seção em estádio I:

* em nenhum ponto ser ultrapassada a tensão ``fctk``;
* ``VSd <= Vc``, com ``Vc`` do item 17.4.2.2.

Ou seja: o estribo construtivo basta **enquanto essas duas condições valem**.
Um pilar de pórtico com viga de transição, um pilar-parede com vento, um
tramo curto entre vigas altas -- nesses a cortante não é desprezível, as
condições caem, e aí o item 17.4 vale como vale para uma viga. Este módulo
verifica isso e diz qual das duas situações é a do lance.

Modelo I (item 17.4.2.2), bielas a 45°, com ``Vc`` constante:

    VRd2 = 0,27 alfa_v2 fcd bw d,      alfa_v2 = 1 - fck/250
    VRd3 = Vc + Vsw
    Vsw  = (Asw/s) 0,9 d fywd (sen a + cos a)      -- estribo vertical: a = 90°
    Vc   = Vc0 (1 + M0/MSd,max) <= 2 Vc0           -- flexo-compressão
    Vc0  = 0,6 fctd bw d,              fctd = fctk,inf/gamma_c

e o espaçamento máximo do item 18.3.3.2:

    Vd <= 0,67 VRd2  ->  s <= 0,6 d <= 30 cm
    Vd >  0,67 VRd2  ->  s <= 0,3 d <= 20 cm

O que **não** está aqui, e é declarado na memória: o modelo II (bielas de
inclinação variável, item 17.4.2.3), que só faria diferença para aproveitar
melhor uma seção já muito solicitada; a torção (item 17.5); e a interação
cortante-torção. Modelo I é o mais conservador dos dois.

Convenção das direções, a mesma do resto do programa: ``Vd_x`` é a cortante
que flete o pilar **na direção x** -- a altura útil corre ao longo de ``x`` e
a largura ``bw`` é medida em ``y``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import avisos as av
from . import geometria as geo
from .materiais import Aco, Concreto

#: Tensão máxima admitida na armadura transversal, MPa (item 17.4.2.2).
FYWD_MAXIMO = 435.0

#: Divisor aplicado a ``Nd`` quando a normal de serviço não é informada, para
#: obter a normal com ``gamma_f = 1,0`` que o item 17.4.2.2 exige no cálculo
#: de ``M0``. Errar aqui erra para o lado seguro: normal menor, ``M0`` menor,
#: ``Vc`` menor.
GAMMA_F_PADRAO = 1.4

#: Número de ramos do estribo que cruzam o plano de cisalhamento. Dois, os do
#: estribo fechado externo. Os grampos suplementares do item 18.2.4 também
#: cruzam, mas não são contados: eles existem para travar barra contra
#: flambagem, podem ser peças abertas, e deixá-los fora é conservador.
RAMOS = 2


@dataclass
class Cisalhamento:
    """Verificação à força cortante numa direção, pelo modelo I."""

    direcao: str
    Vd: float = 0.0              # kN, cortante solicitante de cálculo
    bw: float = 0.0              # cm
    d: float = 0.0               # cm, altura útil na direção
    VRd2: float = 0.0            # kN, ruína da biela comprimida
    Vc0: float = 0.0             # kN
    Vc: float = 0.0              # kN, com o acréscimo da flexo-compressão
    Vsw: float = 0.0             # kN, parcela dos estribos
    M0: float = 0.0              # kN·cm
    MSd_max: float = 0.0         # kN·cm
    Asw_s: float = 0.0           # cm²/cm
    s: float = 0.0               # cm, espaçamento adotado
    s_maximo: float = 0.0        # cm, limite do item 18.3.3.2
    s_necessario: float = 0.0    # cm, o que 17.4 exigiria (0 = dispensado)
    tracao_estadio_1: float = 0.0  # MPa, tração na borda, seção em estádio I
    fctk: float = 0.0            # MPa
    avisos: list[str] = field(default_factory=list)

    @property
    def VRd3(self) -> float:
        return self.Vc + self.Vsw

    @property
    def razao_biela(self) -> float:
        """``VSd/VRd2`` -- <= 1 aprova (ruína da diagonal comprimida)."""
        return self.Vd / self.VRd2 if self.VRd2 > 0 else 0.0

    @property
    def razao_tracao(self) -> float:
        """``VSd/VRd3`` -- <= 1 aprova (ruína por tração diagonal)."""
        return self.Vd / self.VRd3 if self.VRd3 > 0 else 0.0

    @property
    def dispensa_minima(self) -> bool:
        """Verdadeiro quando o item 17.4.1.1.2-c) dispensa a armadura mínima.

        As duas condições da alínea, juntas: a seção não fissura (estádio I,
        tração até ``fctk``) e a cortante cabe em ``Vc``.
        """
        return (self.Vd <= self.Vc + 1e-9
                and self.tracao_estadio_1 <= self.fctk + 1e-9)

    @property
    def ok(self) -> bool:
        return (self.razao_biela <= 1.0 + 1e-6
                and self.razao_tracao <= 1.0 + 1e-6
                and (self.s <= self.s_maximo + 1e-9 or self.s_maximo <= 0.0))


# ---------------------------------------------------------------------------
# Fórmulas do item 17.4.2.2, em números puros
# ---------------------------------------------------------------------------

def alfa_v2(concreto: Concreto) -> float:
    """``alfa_v2 = 1 - fck/250``, com ``fck`` em MPa."""
    return 1.0 - concreto.fck / 250.0


def VRd2(concreto: Concreto, bw: float, d: float) -> float:
    """Cortante resistente da biela comprimida, kN (modelo I)."""
    fcd = concreto.fcd / 10.0                     # MPa -> kN/cm²
    return 0.27 * alfa_v2(concreto) * fcd * bw * d


def Vc0(concreto: Concreto, bw: float, d: float) -> float:
    """Parcela complementar na flexão simples, kN."""
    return 0.6 * (concreto.fctd / 10.0) * bw * d


def fywd(aco: Aco) -> float:
    """Tensão de cálculo do estribo, kN/cm², limitada a 435 MPa."""
    return min(aco.fyd, FYWD_MAXIMO) / 10.0


def Vsw(Asw_s: float, d: float, aco: Aco, alfa_graus: float = 90.0) -> float:
    """``Vsw = (Asw/s) 0,9 d fywd (sen a + cos a)``, kN."""
    a = math.radians(alfa_graus)
    return Asw_s * 0.9 * d * fywd(aco) * (math.sin(a) + math.cos(a))


def espacamento_maximo(Vd: float, vrd2: float, d: float) -> tuple[float, str]:
    """Espaçamento máximo do item 18.3.3.2, cm, e o limite que governou."""
    if vrd2 > 0 and Vd > 0.67 * vrd2:
        return min(0.3 * d, 20.0), "0,3 d <= 20 cm (Vd > 0,67 VRd2)"
    return min(0.6 * d, 30.0), "0,6 d <= 30 cm (Vd <= 0,67 VRd2)"


def espacamento_necessario(Vd: float, vc: float, Asw: float, d: float,
                           aco: Aco) -> float:
    """Espaçamento que faz ``Vc + Vsw = Vd``, cm. ``inf`` se ``Vd <= Vc``."""
    falta = Vd - vc
    if falta <= 0.0:
        return float("inf")
    return Asw * 0.9 * d * fywd(aco) / falta


# ---------------------------------------------------------------------------
# Geometria: bw e d na direção
# ---------------------------------------------------------------------------

def largura_minima(contornos: list[geo.Poligono], direcao: str,
                   cortes: int = 40, faixa: tuple[float, float] | None = None
                   ) -> float:
    """Menor largura da seção ao longo da altura útil, cm (``bw``).

    A largura é medida **perpendicularmente** à direção da flexão: para
    ``Vd_x`` a altura útil corre em ``x`` e ``bw`` é a extensão em ``y``.

    Medida pela área: um corte fino de espessura ``dx`` tem área igual a
    ``dx`` vezes a soma das larguras de material naquela posição. É essa soma
    -- e não a extensão da caixa envolvente -- que resiste à biela: num U, o
    vão entre as almas não conta, e a divisão pela espessura já o exclui,
    porque o recorte é exato.

    ``faixa`` limita a medição a um intervalo de ``u``, e o item 17.4.2.2 pede
    exatamente isso: "a menor largura da seção **compreendida ao longo da
    altura útil d**". Sem esse limite, uma seção circular daria a largura da
    quina extrema -- que tende a zero e não resiste a nada. Quem chama passa
    o intervalo entre as barras extremas da direção, que é onde a alma
    trabalha.
    """
    if not contornos:
        return 0.0
    eixo = 0 if direcao == "x" else 1
    cos_t, sin_t = (1.0, 0.0) if eixo == 0 else (0.0, 1.0)
    us = [p[eixo] for pol in contornos for p in pol]
    u0, u1 = min(us), max(us)
    if faixa is not None:
        a, b = min(faixa), max(faixa)
        u0, u1 = max(u0, a), min(u1, b)
    if u1 - u0 < 1e-9:
        return 0.0
    passo = (u1 - u0) / cortes
    menor = float("inf")
    for i in range(cortes):
        a = u0 + i * passo
        area = 0.0
        for pol in contornos:
            p = geo.recortar_semiplano(pol, cos_t, sin_t, a, True)
            p = geo.recortar_semiplano(p, cos_t, sin_t, a + passo, False)
            if len(p) >= 3:
                area += abs(geo.area_poligono(p))
        if area > 1e-9:
            menor = min(menor, area / passo)
    return 0.0 if menor == float("inf") else menor


def faixa_das_barras(barras, direcao: str) -> tuple[float, float] | None:
    """Intervalo de ``u`` entre as barras extremas da direção, cm.

    É a faixa em que a alma de fato trabalha, e a que o item 17.4.2.2 manda
    usar para medir ``bw`` ("ao longo da altura útil d").
    """
    if not barras:
        return None
    eixo = 0 if direcao == "x" else 1
    us = [(b.x if eixo == 0 else b.y) for b in barras]
    return min(us), max(us)


def altura_util(barras, contornos: list[geo.Poligono], direcao: str) -> float:
    """Altura útil ``d``, cm: da borda comprimida ao centroide da tração.

    Usa a posição real das barras -- não ``0,9 h`` nem uma camada média. Como
    o pilar inverte o sinal do momento, os dois sentidos são medidos e fica o
    **menor** ``d``, que é o pior caso.
    """
    eixo = 0 if direcao == "x" else 1
    coords = [p[eixo] for pol in contornos for p in pol]
    if not coords or not barras:
        return 0.0
    u_min, u_max = min(coords), max(coords)
    meio = (u_min + u_max) / 2.0
    saida = []
    for borda, lado in ((u_max, "menor"), (u_min, "maior")):
        alvo = [b for b in barras
                if ((b.x if eixo == 0 else b.y) < meio) == (lado == "menor")]
        if not alvo:
            continue
        centro = sum((b.x if eixo == 0 else b.y) for b in alvo) / len(alvo)
        saida.append(abs(borda - centro))
    return min(saida) if saida else 0.0


# ---------------------------------------------------------------------------
# Verificação
# ---------------------------------------------------------------------------

def verificar(pilar, arr, est, secao_discreta,
              momentos: dict[str, float] | None = None
              ) -> dict[str, Cisalhamento]:
    """Verifica as duas direções ao item 17.4, modelo I.

    ``momentos`` traz ``MSd,max`` em kN·cm por direção -- o momento de
    cálculo máximo na seção, já com a segunda ordem, que é quem entra na
    razão ``M0/MSd,max``. Sem ele, o momento de primeira ordem serve de
    aproximação (e é a favor da segurança: momento menor, ``Vc`` maior --
    por isso quem chama deve passar o momento total).
    """
    secao = pilar.secao
    contornos = secao.contornos()
    props = secao_discreta.propriedades
    Ac = props.area
    aco_t = pilar.aco_estribo
    Asw = RAMOS * (math.pi * (est.phi / 10.0) ** 2 / 4.0) if est else 0.0
    s = est.s if est else 0.0
    N_servico = abs(pilar.Nd) / GAMMA_F_PADRAO

    saida: dict[str, Cisalhamento] = {}
    for direcao in ("x", "y"):
        Vd = abs(pilar.esforcos.Vd(direcao)) * pilar.fator_esforcos
        bw = largura_minima(
            contornos, direcao,
            faixa=faixa_das_barras(secao_discreta.barras, direcao))
        d = altura_util(secao_discreta.barras, contornos, direcao)
        c = Cisalhamento(direcao=direcao, Vd=Vd, bw=bw, d=d, s=s,
                         fctk=pilar.concreto.fctk_inf)
        if bw <= 0.0 or d <= 0.0:
            c.avisos.append(av.erro(
                f"Direção {direcao}: não foi possível medir bw e d para a "
                f"verificação à força cortante."))
            saida[direcao] = c
            continue

        c.VRd2 = VRd2(pilar.concreto, bw, d)
        c.Vc0 = Vc0(pilar.concreto, bw, d)

        # W1: módulo resistente da fibra mais tracionada na direção.
        h = props.hx if direcao == "x" else props.hy
        I = props.Ix if direcao == "x" else props.Iy
        W1 = I / (h / 2.0) if h > 0 else 0.0
        c.MSd_max = abs((momentos or {}).get(direcao, 0.0))
        if c.MSd_max <= 0.0:
            c.MSd_max = abs(pilar.momento_base(direcao)) * pilar.fator_esforcos
        c.M0 = (N_servico / Ac) * W1 if Ac > 0 else 0.0

        if pilar.Nd > 0.0 and c.MSd_max > 1e-9:
            fator = min(1.0 + c.M0 / c.MSd_max, 2.0)
        elif pilar.Nd > 0.0:
            fator = 2.0            # compressão sem momento: o teto do 17.4.2.2
        else:
            fator = 1.0            # flexo-tração: Vc = Vc0 (linha neutra na seção)
        c.Vc = c.Vc0 * fator

        c.Asw_s = Asw / s if s > 0 else 0.0
        c.Vsw = Vsw(c.Asw_s, d, aco_t)
        nec = espacamento_necessario(Vd, c.Vc, Asw, d, aco_t)
        c.s_necessario = 0.0 if nec == float("inf") else nec

        tensao = (c.MSd_max / W1 if W1 > 0 else 0.0) - abs(pilar.Nd) / Ac
        c.tracao_estadio_1 = max(tensao, 0.0) * 10.0     # kN/cm² -> MPa

        if Vd <= 1e-9:
            # Sem cortante, o limite do item 18.3.3.2 não se aplica: quem
            # manda no espaçamento é o critério construtivo de pilar
            # (18.4.3), que a rotina de estribos já cumpriu.
            c.avisos.append(av.construtivo(
                f"Direção {direcao}: cortante de cálculo não informada. A "
                f"verificação do item 17.4 não se aplica, e o estribo sai só "
                f"dos critérios construtivos do item 18.4.3."))
            saida[direcao] = c
            continue

        # O teto do item 18.3.3.2 é do estribo que **resiste** à cortante:
        # enquanto a alínea c) do 17.4.1.1.2 dispensa a armadura de
        # cisalhamento, quem manda no espaçamento é o critério construtivo de
        # pilar (18.4.3), e este limite não se aplica.
        motivo = ""
        if not c.dispensa_minima:
            c.s_maximo, motivo = espacamento_maximo(Vd, c.VRd2, d)

        if secao.tipo != "retangular":
            c.avisos.append(av.construtivo(
                f"Direção {direcao}: o modelo I do item 17.4.2.2 é escrito "
                f"para elemento com alma de largura definida. Nesta seção "
                f"{secao.tipo}, bw = {bw:.1f} cm foi medido como a **menor** "
                f"largura de material entre as barras extremas da direção, e "
                f"d = {d:.1f} cm pela posição real das barras. A extensão do "
                f"modelo a esta seção é decisão do programa, não da norma."))

        if c.razao_biela > 1.0 + 1e-6:
            c.avisos.append(av.erro(
                f"Direção {direcao}: VSd = {Vd:.1f} kN passa de VRd2 = "
                f"{c.VRd2:.1f} kN -- ruína da diagonal comprimida de concreto "
                f"(item 17.4.2.2-a). Nem armadura resolve: é preciso aumentar "
                f"a seção ou a classe do concreto."))
        if c.razao_tracao > 1.0 + 1e-6:
            c.avisos.append(av.erro(
                f"Direção {direcao}: VSd = {Vd:.1f} kN passa de VRd3 = Vc + "
                f"Vsw = {c.Vc:.1f} + {c.Vsw:.1f} = {c.VRd3:.1f} kN (item "
                f"17.4.2.2-b). O espaçamento de estribos precisa cair para "
                f"{c.s_necessario:.1f} cm."))
        if s > c.s_maximo + 1e-9:
            c.avisos.append(av.erro(
                f"Direção {direcao}: espaçamento de estribos de {s:g} cm "
                f"acima do máximo de {c.s_maximo:.1f} cm do item 18.3.3.2 "
                f"({motivo}), que passa a valer porque há cortante a "
                f"resistir."))
        if c.dispensa_minima:
            c.avisos.append(av.construtivo(
                f"Direção {direcao}: VSd = {Vd:.1f} kN <= Vc = {c.Vc:.1f} kN "
                f"e a tração na borda em estádio I ({c.tracao_estadio_1:.2f} "
                f"MPa) não passa de fctk ({c.fctk:.2f} MPa) -- o item "
                f"17.4.1.1.2-c) dispensa a armadura transversal mínima de "
                f"cisalhamento, e o estribo construtivo do 18.4.3 basta."))
        else:
            c.avisos.append(av.construtivo(
                f"Direção {direcao}: o item 17.4.1.1.2-c) **não** dispensa a "
                f"armadura de cisalhamento (VSd = {Vd:.1f} kN, Vc = "
                f"{c.Vc:.1f} kN, tração em estádio I = "
                f"{c.tracao_estadio_1:.2f} MPa contra fctk = {c.fctk:.2f} "
                f"MPa); o estribo foi verificado pelo item 17.4.2.2."))
            c.avisos.append(av.construtivo(
                f"Direção {direcao}: M0 = {c.M0 / 100.0:.1f} kN·m calculado "
                f"com a normal de serviço estimada em Nd/{GAMMA_F_PADRAO:g} = "
                f"{N_servico:.0f} kN, como o item 17.4.2.2 pede (gamma_f = "
                f"1,0 na tensão de compressão)."))
        saida[direcao] = c
    return saida
