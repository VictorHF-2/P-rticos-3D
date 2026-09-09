# -*- coding: utf-8 -*-
"""
grampos.py
==========

Grampos de ancoragem nas extremidades, quando o apoio não dá comprimento.

Num apoio de extremidade estreito o comprimento reto disponível -- da face do
pilar até a ponta da barra, descontado o cobrimento -- pode não chegar para o
lb,nec exigido pelo item 18.3.2.4.1, e o gancho de extremidade sozinho também
não resolve. A saída construtiva é o **grampo**: uma barra em U, de bitola fina,
que abraça a armadura longitudinal no apoio e leva para dentro da viga a parcela
de força que o trecho reto não conseguiu desenvolver.

O método reproduzido aqui é o das abas *Ancoragem Positiva Extremidade* e
*Ancoragem Negaitiva Extremidade* da planilha de referência da Ecoplan, e a
sequência é curta:

1. o trecho reto disponível ancora a fração ``(lb,disp - Ø_grampo) / lanc`` da
   força; o grampo assume o resto;
2. a bitola do grampo tem teto: ``Ø_grampo,máx = (lb,disp / lanc) · Ø_barra``.
   Passar dele significa que nem o grampo salva a ancoragem, e o apoio precisa
   crescer ou a bitola da armadura precisa cair;
3. cada grampo conta com **duas pernas**, e por isso a área de um grampo é o
   dobro da área da sua bitola;
4. ``lb1`` é o comprimento do grampo medido **da face do pilar até a ponta**,
   e vale o lb básico (em diâmetros) aplicado à bitola do grampo.

Duas coisas que a planilha faz e este módulo **não** faz, porque divergem do que
o programa apura em outro lugar -- e adotá-las caladas seria trocar um critério
verificado por outro sem dizer:

* na aba positiva, quando o cobrimento lateral é maior ou igual a 7 cm e há
  gancho, a planilha **abandona o lb,nec** e deixa a ancoragem governada só
  pelos pisos geométricos (r + 5,5 Ø e 6 cm). O programa mantém
  ``máx(lb,nec, r + 5,5 Ø, 60 mm)``, que é a leitura literal do 18.3.2.4.1;
* a planilha calcula ``fct,m`` acima de C50 por ``2,12·ln(1 + 0,11·fck)``, forma
  que a norma não traz -- o programa usa ``2,12·ln[1 + 0,1(fck + 8)]``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import ancoragem as anc
from . import avisos as av
from .materiais import Aco, Concreto, area_barra

#: bitolas comerciais usadas em grampo, mm
BITOLAS_GRAMPO = (5.0, 6.3, 8.0, 10.0, 12.5)

#: bitola de grampo adotada por padrão, mm
PHI_PADRAO = 6.3

#: pernas de um grampo: ele é um U, e as duas pernas resistem
PERNAS = 2


@dataclass
class Grampos:
    """Grampos de ancoragem de um apoio de extremidade."""

    phi: float                # mm, bitola adotada
    phi_max: float            # mm, teto de (lb,disp/lanc).Ø_barra
    fracao: float             # parcela da força que o trecho reto não ancora
    Fsd: float                # kN a ancorar pelos grampos
    As: float                 # cm² de grampo
    n: int                    # número de grampos
    lb1: float                # cm, da face do pilar à ponta do grampo
    lb_disp: float            # cm, trecho reto disponível
    lanc: float               # cm, ancoragem exigida da armadura
    ok: bool                  # a bitola adotada cabe no teto?
    face: str = "inferior"
    apoio: int = 0
    avisos: list[str] = field(default_factory=list)

    @property
    def comprimento_total(self) -> float:
        """Comprimento de aço de todos os grampos do apoio, m."""
        return self.n * PERNAS * self.lb1 / 100.0


def dimensionar(concreto: Concreto, aco: Aco, phi_barra: float,
                As_calc: float, lb_disp: float, lanc: float,
                face: str = "inferior", h_cm: float = 0.0,
                phi_grampo: float = PHI_PADRAO) -> Grampos:
    """Grampos para completar a ancoragem de um apoio de extremidade.

    ``lanc`` é a ancoragem exigida da armadura longitudinal (já com os pisos do
    18.3.2.4.1) e ``lb_disp`` é o trecho reto que o apoio oferece. Quando o
    segundo cobre o primeiro não há grampo a dimensionar, e a função devolve
    ``n = 0`` -- quem chama não precisa decidir isso de fora.
    """
    avisos: list[str] = []
    phi_max = (lb_disp / lanc * phi_barra) if lanc > 1e-9 else 0.0

    # a fração que o trecho reto ancora desconta a bitola do grampo: a dobra
    # dele ocupa esse espaço, e lb1 é medido da face do pilar à ponta do grampo
    reto_util = max(lb_disp - phi_grampo / 10.0, 0.0)
    fracao = 1.0 - reto_util / lanc if lanc > 1e-9 else 1.0
    fracao = min(max(fracao, 0.0), 1.0)

    fyd = aco.fyd_kNcm2
    Fsd = As_calc * fyd * fracao
    As = Fsd / fyd
    area_grampo = PERNAS * area_barra(phi_grampo)
    n = int(math.ceil(As / area_grampo - 1e-9)) if As > 1e-9 else 0

    # lb1 é o lb básico em diâmetros aplicado à bitola do grampo
    boa = anc.boa_aderencia(face, h_cm)
    fbd = anc.fbd(concreto, aco, phi_grampo, boa)
    lb_phi = max(fyd / (4.0 * fbd), 25.0)
    lb1 = lb_phi * phi_grampo / 10.0

    ok = phi_grampo <= phi_max + 1e-9
    if n and not ok:
        avisos.append(av.erro(
            f"Grampo Ø{phi_grampo:g} acima do teto de "
            f"Ø{phi_max:.1f} mm = (lb,disp/lanc)·Ø{phi_barra:g}: com o trecho "
            f"reto que este apoio oferece, nem o grampo ancora a armadura. "
            f"Alargue o apoio ou reduza a bitola da armadura."))
    elif n:
        avisos.append(av.construtivo(
            f"Ancoragem completada por {n} grampo(s) Ø{phi_grampo:g} c/ "
            f"lb1 = {lb1:.0f} cm, medido da face do pilar à ponta do grampo. "
            f"O trecho reto de {lb_disp:.1f} cm ancora "
            f"{(1.0 - fracao) * 100:.0f}% da força; os grampos assumem os "
            f"{fracao * 100:.0f}% restantes ({Fsd:.1f} kN, {As:.2f} cm²)."))
    return Grampos(phi=phi_grampo, phi_max=phi_max, fracao=fracao, Fsd=Fsd,
                   As=As, n=n, lb1=lb1, lb_disp=lb_disp, lanc=lanc,
                   ok=ok or not n, face=face, avisos=avisos)


def menor_bitola_que_cabe(concreto: Concreto, aco: Aco, phi_barra: float,
                          As_calc: float, lb_disp: float, lanc: float,
                          face: str = "inferior",
                          h_cm: float = 0.0) -> Grampos | None:
    """A bitola comercial mais fina que resolve, ou ``None`` se nenhuma resolve.

    Grampo grosso não é melhor: a bitola tem teto, e passar do teto significa
    que a ancoragem não fecha. Varrer de baixo para cima devolve a solução mais
    leve que ainda cabe.
    """
    for phi in BITOLAS_GRAMPO:
        g = dimensionar(concreto, aco, phi_barra, As_calc, lb_disp, lanc,
                        face, h_cm, phi)
        if g.ok:
            return g
    return None
