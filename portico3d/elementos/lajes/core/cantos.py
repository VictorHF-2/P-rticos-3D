# -*- coding: utf-8 -*-
"""
cantos.py
Armadura superior de canto das lajes em cruz calculadas pelas linhas de
ruptura (R11).

Por que existe
--------------
O mecanismo de charneiras da laje apoiada supõe que o canto fica **preso**:
as charneiras positivas correm até o vértice. Sem armadura superior, o canto
levanta e a ruptura bifurca antes de chegar ao vértice (Fig. 5.9 de Souza &
Cunha) -- a carga de ruptura cai pelo fator

    k = 1 / [1 - 0,45 (1 - γ/π)²],        k = 1,13 no canto reto,

ou seja, o momento das charneiras fica 13 % contra a segurança. A saída do
livro (§5.9) é dar ao canto uma armadura superior que resista a

    m' = m · cot²(γ/2)                     (= m no canto reto)

numa faixa de comprimento, a partir do vértice,

    ℓ = √(6m/p) · [1/sen(γ/2) - 1]         (= 0,414 √(6m/p) a 90°).

A NB-1/78 pedia o mesmo por regra prática: metade da maior armadura
positiva, nas duas direções, até 0,2 do menor vão, nos cantos em que os dois
bordos são apoiados. Adota-se aqui o **momento do livro** (m' = m, o maior
dos dois positivos de cálculo, que cobre a regra da NB-1 com folga) e a
**maior das duas zonas**. Num canto com bordo engastado a charneira negativa
já segura o canto e nada é exigido (livro e NB-1 concordam).

A NBR 6118:2026 não trata do assunto; é armadura de boa prática, ligada por
padrão em ``Config.armadura_canto``. Com o método ``mef`` (R10) o canto sai
do volvente da própria malha (``mef_pavimento``) e este módulo não roda.

Como sai a armadura
-------------------
Flexão da faixa de 1 m na face superior, com ``d`` da camada de cima menos
1 cm (as duas direções se cruzam no canto -- a favor da segurança, como no
MEF), detalhada com a mesma escolha de bitola das negativas. A massa é
estimativa: as duas direções sobre o quadrado da zona, mais um comprimento
de ancoragem reto de 10φ para dentro da laje, sem ganchos.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import detalhamento as det
from . import flexao as fx

#: Fração do menor vão da zona de canto da NB-1/78.
FRACAO_ZONA_NB1 = 0.2


@dataclass
class CantoCharneira:
    """Canto de laje em cruz com os dois bordos apoiados."""

    laje: str
    bordos: tuple[int, int]
    x: float                        # m, vértice na planta
    y: float
    m_vao: float = 0.0              # kN·m/m, maior positivo de cálculo
    p_d: float = 0.0                # kN/m², carga de cálculo
    zona_charneira: float = 0.0     # m, 0,414 √(6m/p)
    zona_nb1: float = 0.0           # m, 0,2 do menor vão efetivo
    zona: float = 0.0               # m, a adotada (a maior)
    m_topo: float = 0.0             # kN·m/m, m' = m cot²(45°) = m
    As: float = 0.0                 # cm²/m, cada direção, face superior
    d: float = 0.0                  # cm
    phi: float = 0.0                # mm
    espacamento: float = 0.0        # cm
    As_efetiva: float = 0.0         # cm²/m
    massa: float = 0.0              # kg, estimativa (duas direções)
    erro: str = ""

    @property
    def rotulo(self) -> str:
        return f"{self.laje}, bordos {self.bordos[0]} e {self.bordos[1]}"

    @property
    def armadura(self) -> str:
        if self.erro:
            return self.erro
        return (f"Ø{self.phi:g} c/ {self.espacamento:g} em x e em y "
                f"({self.As:.2f} cm²/m)")


#: Os quatro cantos pelos bordos que se encontram neles.
PARES_DE_CANTO = ((1, 2), (2, 3), (3, 4), (4, 1))


def fator_bifurcacao(gama: float = math.pi / 2.0) -> float:
    """Fator k da Fig. 5.9 de Souza & Cunha: quanto o momento das
    charneiras fica abaixo do real quando o canto de ângulo ``gama`` (rad)
    pode levantar (canto reto: 1,13)."""
    return 1.0 / (1.0 - 0.45 * (1.0 - gama / math.pi) ** 2)


def zona_charneira(m: float, p: float, gama: float = math.pi / 2.0
                   ) -> float:
    """ℓ = √(6m/p)·[1/sen(γ/2) - 1], m (kN·m/m), p (kN/m²) -> m."""
    if m <= 0.0 or p <= 0.0:
        return 0.0
    return math.sqrt(6.0 * m / p) * (1.0 / math.sin(gama / 2.0) - 1.0)


def _vertice(laje, b1: int, b2: int) -> tuple[float, float]:
    s1 = laje.segmento_do_bordo(b1)
    s2 = laje.segmento_do_bordo(b2)
    for p in ((s1[0], s1[1]), (s1[2], s1[3])):
        for q in ((s2[0], s2[1]), (s2[2], s2[3])):
            if abs(p[0] - q[0]) < 1e-9 and abs(p[1] - q[1]) < 1e-9:
                return p
    return s1[0], s1[1]


def cantos_da_laje(laje, esf) -> list[CantoCharneira]:
    """Os cantos de bordos apoiado + apoiado da laje em cruz (sem
    dimensionar)."""
    saida: list[CantoCharneira] = []
    if not esf.classificacao.em_cruz:
        return saida
    m = max(esf.ma, esf.mb)
    for b1, b2 in PARES_DE_CANTO:
        if laje.bordos[b1 - 1].vinculo != "apoiado" or \
                laje.bordos[b2 - 1].vinculo != "apoiado":
            continue
        x, y = _vertice(laje, b1, b2)
        c = CantoCharneira(laje=laje.nome, bordos=(b1, b2), x=x, y=y,
                           m_vao=m, p_d=esf.p_d)
        c.zona_charneira = zona_charneira(m, esf.p_d)
        c.zona_nb1 = FRACAO_ZONA_NB1 * min(laje.a_ef, laje.b_ef)
        c.zona = max(c.zona_charneira, c.zona_nb1)
        c.m_topo = m                       # cot²(45°) = 1
        saida.append(c)
    return saida


def dimensionar(res, pav) -> list[CantoCharneira]:
    """Cantos de todas as maciças em cruz do resultado, dimensionados."""
    cfg = pav.config
    saida: list[CantoCharneira] = []
    for rl in res.lajes:
        laje, esf = rl.laje, rl.esforcos
        if esf is None:
            continue
        for c in cantos_da_laje(laje, esf):
            c_sup = pav.ambiente.cobrimento_superior(
                cfg.bitola_minima_negativa)
            c.d = fx.altura_util(laje.h, c_sup, "superior") - 1.0
            f = fx.dimensionar_secao(c.m_topo, laje.h, c.d, c_sup,
                                     pav.concreto, pav.aco, "negativa",
                                     f"canto {c.rotulo}")
            c.As, c.erro = f.As, f.erro
            if not c.erro:
                esc = det.escolher(f.As, laje.h, "superior", cfg, True,
                                   cfg.bitolas_impostas.get(
                                       f"{laje.nome}|canto "
                                       f"{c.bordos[0]}-{c.bordos[1]}"))
                if esc.erro:
                    c.erro = esc.erro
                else:
                    c.phi, c.espacamento = esc.phi, esc.espacamento
                    c.As_efetiva = esc.As_efetiva
            As = c.As_efetiva or c.As
            ancoragem = 10.0 * c.phi / 1000.0          # m
            c.massa = (2.0 * As * 1e-4 * c.zona * (c.zona + ancoragem)
                       * 7850.0)
            saida.append(c)
    return saida
