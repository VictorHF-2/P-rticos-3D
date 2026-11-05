# -*- coding: utf-8 -*-
"""
diafragma.py
A laje de cada pavimento como diafragma rígido no próprio plano.

A laje de concreto é muito rígida no plano dela e muito flexível fora dele.
O diafragma rígido é a idealização disso: os nós do pavimento passam a
transladar em X e Y e a girar em torno de Z **juntos**, como corpo rígido, e
continuam livres em Z e nos giros em X e Y — que é onde a laje é flexível e
onde a viga trabalha.

Por nó do pavimento, com (xc, yc) o centro de referência do diafragma:

    ux = Ux − Rz·(y − yc)
    uy = Uy + Rz·(x − xc)
    rz = Rz

Os três graus (Ux, Uy, Rz) são **do pavimento**, e não de nó nenhum: entram
no sistema como coordenadas novas, e os ux, uy, rz de cada nó deixam de ser
incógnitas. É restrição exata por transformação de coordenadas
(``D = T·r``), e não mola rígida: não há rigidez de penalidade para
desequilibrar o sistema, e o resultado não depende de um número arbitrário.

O que isso muda no resultado, e convém saber antes de olhar os números:

* **O vento se reparte pela rigidez.** Sem diafragma, cada prumada leva a
  carga aplicada nos seus nós; com ele, o pavimento obriga todas a se
  deslocar juntas, e a mais rígida leva mais.
* **Aparece a torção do pavimento.** Planta assimétrica gira, e o giro passa
  a ser um modo de vibração de verdade.
* **O normal das vigas no plano some.** As vigas ficam sem alongar: o
  diafragma absorve o que seria o esforço axial delas. É o que todo programa
  de edifício faz com diafragma rígido, e é conhecido.

Quem entra no diafragma: os nós da cota de uma laje que estão sobre o painel
— cantos, bordas ou interior (os nós da grelha, quando ela existe). O nó que
tem apoio em ux, uy ou rz fica fora, porque restrição de apoio e de
diafragma no mesmo grau seriam duas condições para uma incógnita; o caso
normal (base do prédio, sem laje) nem chega a isso.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .modelo import Modelo

TOLERANCIA = 1.0e-6

#: Os graus do nó que o diafragma prende: ux, uy e rz.
GRAUS_DO_DIAFRAGMA = (0, 1, 5)


@dataclass
class Diafragma:
    """Um pavimento rígido no plano: os nós que se movem juntos."""

    cota: float
    nos: list[str]
    centro: tuple[float, float]
    #: Nós do pavimento deixados de fora por terem apoio no plano.
    excluidos: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        texto = (f"diafragma em z = {self.cota:g} m: {len(self.nos)} nós, "
                 f"centro ({self.centro[0]:.3f}, {self.centro[1]:.3f})")
        if self.excluidos:
            texto += (f"; fora por terem apoio no plano: "
                      f"{', '.join(self.excluidos)}")
        return texto


def _retangulos_por_cota(modelo: Modelo) -> dict[float, list[tuple]]:
    """Os painéis de laje de cada cota, como (x0, x1, y0, y1)."""
    from .lajes import retangulo

    saida: dict[float, list[tuple]] = {}
    for laje in modelo.lajes.values():
        if laje.no_a not in modelo.nos or laje.no_c not in modelo.nos:
            continue
        x0, y0, x1, y1, z = retangulo(modelo, laje)
        saida.setdefault(round(z, 6), []).append((x0, x1, y0, y1))
    return saida


def diafragmas(modelo: Modelo) -> list[Diafragma]:
    """Os diafragmas do modelo, um por cota com laje.

    Vazio quando a opção está desligada — e é por aí que o cálculo sem
    diafragma continua idêntico ao de antes.
    """
    if not modelo.calculo.diafragma or not modelo.lajes:
        return []

    saida = []
    for cota, retangulos in sorted(_retangulos_por_cota(modelo).items()):
        nos, excluidos = [], []
        for nome, no in modelo.nos.items():
            if abs(no.z - cota) > TOLERANCIA:
                continue
            dentro = any(x0 - TOLERANCIA <= no.x <= x1 + TOLERANCIA
                         and y0 - TOLERANCIA <= no.y <= y1 + TOLERANCIA
                         for x0, x1, y0, y1 in retangulos)
            if not dentro:
                continue
            apoio = modelo.apoios.get(nome)
            if apoio is not None and any(apoio.restricoes[k]
                                         for k in GRAUS_DO_DIAFRAGMA):
                excluidos.append(nome)
                continue
            nos.append(nome)
        if len(nos) < 2:
            continue
        xc = sum(modelo.nos[n].x for n in nos) / len(nos)
        yc = sum(modelo.nos[n].y for n in nos) / len(nos)
        saida.append(Diafragma(cota, nos, (xc, yc), excluidos))
    return saida
