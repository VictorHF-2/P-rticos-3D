# -*- coding: utf-8 -*-
"""
principais.py
Esbeltez e segunda ordem local nos **eixos principais de inércia**, para a
seção sem eixo de simetria (produto de inércia ``Ixy`` não nulo -- entre as
seções aceitas, a L).

Por que existe
--------------
O programa faz toda a análise nas direções x e y da entrada, que é onde
estão os momentos e os comprimentos equivalentes. Na seção com ``Ixy = 0``
x e y já são os eixos principais. Na L não são: a flambagem se dá segundo os
eixos principais, e o raio de giração mínimo fica bem abaixo de ``ix`` e
``iy`` -- numa L de 60x60 com abas de 20 cm, 12,1 cm contra 17,0 cm, e o
lambda real é 41 % maior que o calculado em x/y. Os itens 15.8.2 (dispensa da
2ª ordem), 15.8.1 e 15.8.3 (limites de 90, 140 e 200), 15.8.4 (fluência
obrigatória acima de 90) e 15.8.3.3.5 ("nas duas direções principais")
falam da esbeltez nas direções principais.

O que este módulo faz
---------------------
* Direções principais ``u1`` (maior inércia) e ``u2`` (menor), raio de
  giração, altura da seção medida ao longo de cada uma (``h`` da
  excentricidade mínima e da curvatura), comprimento equivalente e lambda.
* Os momentos de 1ª ordem de topo e de base projetados em cada direção
  principal, ``M_p = Mx ux + My uy`` (os momentos são vetores de
  excentricidade, ``M = N e``, na convenção interna em que o sinal diz a face
  tracionada), e com eles ``M1d,A``, ``M1d,B``, ``alfa_b``, ``lambda_1`` e a
  decisão do 15.8.2 em cada direção principal.
* A 2ª ordem local de cada direção principal pelos métodos do pilar-padrão
  (curvatura, rigidez, M-N-1/r com o ``(EI)sec`` da flexão na própria
  direção principal), projetada de volta em x e y como **vetor**:
  ``e2 = sum s_p e2_p u_p``, com ``s_p`` o sentido da excentricidade de 1ª
  ordem do meio ao longo de ``u_p``.
* As semi-elipses do momento mínimo nas direções principais (11.3.3.4.3 e
  Figura 11.3: "nas suas direções principais").

O método geral (15.8.3.2) não passa por aqui: ele resolve a seção real em
``(N, Mx, My)``, com o acoplamento que o ``Ixy`` provoca, e só precisa saber
se a 2ª ordem entra -- a decisão vem daqui.

Comprimento equivalente: a entrada dá ``le_x`` e ``le_y``. Iguais, valem para
qualquer direção. Diferentes, cada direção principal toma o **maior** dos
dois -- não há regra na norma para interpolar, e o maior é o lado seguro --,
com aviso. O vínculo segue a mesma regra (balanço em qualquer das duas vale
para as duas).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import avisos as av
from .formato import num
from .modelo import Pilar


@dataclass
class DirecaoPrincipal:
    """Uma direção principal: geometria, esbeltez e 1ª ordem projetada."""

    indice: int                  # 1 (maior inércia) ou 2 (menor)
    phi: float                   # rad, direção da excentricidade, a partir de x
    I: float                     # cm⁴
    i: float                     # cm, raio de giração
    h: float                     # cm, altura da seção ao longo da direção
    le: float                    # cm
    lam: float
    vinculo: int
    M1d_A: float = 0.0           # kN·cm, maior momento de extremidade (módulo)
    M1d_B: float = 0.0           # kN·cm, com sinal relativo a M1d,A
    sinal_A: float = 1.0
    e1: float = 0.0              # cm, M1d,A/Nd
    e1_min: float = 0.0          # cm
    M1d_min: float = 0.0         # kN·cm
    alfa_b: float = 1.0
    motivo_alfa_b: str = ""
    lam_1: float = 35.0
    considerar_2a_ordem: bool = False
    gamma_n1: float = 1.0
    #: preenchidos pela 2ª ordem (``segunda_ordem``)
    sentido: float = 1.0         # s_p: sentido da 2ª ordem ao longo de u_p
    e2: float = 0.0              # cm, já com gamma_n1 e a fluência
    e_cc: float = 0.0            # cm
    EI_sec: float = 0.0          # kN·cm², quando pelo M-N-1/r
    metodo: str = ""

    @property
    def ux(self) -> float:
        return math.cos(self.phi)

    @property
    def uy(self) -> float:
        return math.sin(self.phi)

    @property
    def rotulo(self) -> str:
        return f"{self.indice} ({num(math.degrees(self.phi), 1)}°)"


@dataclass
class EixosPrincipais:
    """As duas direções principais de uma seção sem simetria."""

    I1: float
    I2: float
    phi1: float                  # rad
    Ix: float
    Iy: float
    Ixy: float
    direcoes: list[DirecaoPrincipal] = field(default_factory=list)
    le_iguais: bool = True
    avisos: list[str] = field(default_factory=list)

    @property
    def lam_max(self) -> float:
        return max(d.lam for d in self.direcoes)

    def exige_2a_ordem(self, direcao: str) -> bool:
        """Alguma direção principal pede 2ª ordem com componente em
        ``direcao`` (x ou y)?"""
        for d in self.direcoes:
            comp = d.ux if direcao == "x" else d.uy
            if d.considerar_2a_ordem and abs(comp) > 1e-9:
                return True
        return False

    def e2_vetor(self) -> tuple[float, float]:
        """``sum s_p e2_p u_p``, cm, nas componentes x e y."""
        ex = sum(d.sentido * d.e2 * d.ux for d in self.direcoes)
        ey = sum(d.sentido * d.e2 * d.uy for d in self.direcoes)
        return ex, ey


def _altura_na_direcao(pilar: Pilar, phi: float) -> float:
    c, s = math.cos(phi), math.sin(phi)
    us = [x * c + y * s for pol in pilar.secao.contornos() for x, y in pol]
    return max(us) - min(us) if us else 0.0


def _projetado(pilar: Pilar, phi: float) -> tuple[float, float, float]:
    """``(topo, base, meio)`` projetados na direção ``phi``, kN·cm, na
    convenção interna (sem ``fator_esforcos``)."""
    c, s = math.cos(phi), math.sin(phi)
    e = pilar.esforcos
    topo = e.topo("x") * c + e.topo("y") * s
    base = pilar.momento_base("x") * c + pilar.momento_base("y") * s
    meio = e.meio("x") * c + e.meio("y") * s
    return topo, base, meio


def analisar(pilar: Pilar) -> EixosPrincipais | None:
    """Esbeltez e 1ª ordem nas direções principais; ``None`` se x e y já
    são principais (seção com eixo de simetria)."""
    from . import esbeltez as esb_mod     # evita importação circular

    prop = pilar.secao.propriedades()
    if prop.simetrica:
        return None
    I1, I2, phi1 = prop.principais()
    ep = EixosPrincipais(I1=I1, I2=I2, phi1=phi1, Ix=prop.Ix, Iy=prop.Iy,
                         Ixy=prop.Ixy)
    le_x, le_y = pilar.le("x"), pilar.le("y")
    ep.le_iguais = abs(le_x - le_y) <= 1e-6 * max(le_x, le_y, 1.0)
    le = max(le_x, le_y)
    vx, vy = pilar.lance.vinculo("x"), pilar.lance.vinculo("y")
    vinculo = vx if vx == vy else (3 if 3 in (vx, vy) else max(vx, vy))
    if not ep.le_iguais:
        ep.avisos.append(av.construtivo(
            f"Seção {pilar.secao.tipo} sem eixo de simetria: a esbeltez é "
            f"verificada nos eixos principais de inércia, que não coincidem "
            f"com x e y. Com le,x = {num(le_x, 0)} cm diferente de le,y = "
            f"{num(le_y, 0)} cm, as duas direções principais tomaram o maior "
            f"({num(le, 0)} cm), que é o lado seguro."))
    Nd = pilar.Nd
    f = pilar.fator_esforcos
    cfg = pilar.config
    for k, (I, phi) in enumerate(((I1, phi1), (I2, phi1 + math.pi / 2.0)),
                                 start=1):
        i = math.sqrt(I / prop.area) if prop.area > 0 else 0.0
        h = _altura_na_direcao(pilar, phi)
        lam = le / i if i > 0 else float("inf")
        topo, base, meio = _projetado(pilar, phi)
        M_A = f * max(abs(topo), abs(base))
        M_B = f * (-1.0 if topo * base < 0.0 else 1.0) * min(abs(topo),
                                                              abs(base))
        M = topo if abs(topo) >= abs(base) else base
        e1 = M_A / Nd if abs(Nd) > 1e-9 else 0.0
        e1_min = esb_mod.excentricidade_minima(h)
        M1d_min = abs(Nd) * e1_min
        ab, motivo, _ = esb_mod.alfa_b(vinculo, M_A, M_B, M1d_min, f * meio,
                                       cfg.alfa_b_unitario_sob_minimo)
        lam_1, _ = esb_mod.esbeltez_limite(abs(e1), h, ab)
        g1 = esb_mod.gamma_n1(lam) if cfg.aplicar_gamma_n1 else 1.0
        considerar = Nd > 0.0 and (lam > lam_1 or cfg.sempre_2a_ordem)
        ep.direcoes.append(DirecaoPrincipal(
            indice=k, phi=phi, I=I, i=i, h=h, le=le, lam=lam,
            vinculo=vinculo, M1d_A=M_A, M1d_B=M_B,
            sinal_A=-1.0 if M < 0.0 else 1.0, e1=e1, e1_min=e1_min,
            M1d_min=M1d_min, alfa_b=ab, motivo_alfa_b=motivo, lam_1=lam_1,
            considerar_2a_ordem=considerar, gamma_n1=g1))
    return ep


def sentidos_da_2a_ordem(ep: EixosPrincipais, ex_meio: float,
                         ey_meio: float) -> None:
    """``s_p`` de cada direção: o sentido da excentricidade de 1ª ordem do
    meio ao longo de ``u_p`` -- a deformada acompanha o momento. Sem
    componente (momento ortogonal ou nulo), o sentido de ``M1d,A`` naquela
    direção."""
    for d in ep.direcoes:
        comp = ex_meio * d.ux + ey_meio * d.uy
        d.sentido = (1.0 if comp > 1e-12 else -1.0 if comp < -1e-12
                     else d.sinal_A)
