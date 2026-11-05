# -*- coding: utf-8 -*-
"""
nervurada_modelo.py
Dados de entrada da laje nervurada **bidirecional** moldada no local: um
painel retangular com nervuras nas duas direções, mesa comum e enchimento
removível (ou perdido).

A nervurada **unidirecional** não tem modelo próprio: é a faixa contínua do
``trelicada.py`` com ``sistema = "nervurada"`` -- a mesma viga T contínua, só
que sem vigota nem treliça (ver ``trelicada_modelo.LajeTrelicada``).

Convenções:
    comprimentos da seção ... cm;  vãos do painel ... m;
    cargas superficiais ..... kN/m²;
    ``x`` e ``y`` são os eixos do painel; a "direção x" é a das nervuras
    **paralelas a x** (que vencem o vão ``lx``) -- cada uma tem a seção T de
    largura colaborante tirada do espaçamento ``ey`` entre elas.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Peso específico do enchimento, kN/m³. A forma removível (cuba plástica ou
#: metálica) sai depois da pega e não pesa; EPS e cerâmico ficam na laje.
ENCHIMENTOS_NERVURADA = {"Forma removível": 0.0, "EPS": 0.18,
                         "Cerâmico": 6.0}

#: Vínculos possíveis dos quatro bordos do painel.
VINCULOS_BORDO = ("apoiado", "engastado")

#: Diâmetros da armadura longitudinal das nervuras, mm (CA-50).
BITOLAS_NERVURA = (8.0, 10.0, 12.5, 16.0, 20.0, 25.0)

#: Diâmetros de estribo, mm.
BITOLAS_ESTRIBO = (5.0, 6.3, 8.0)


@dataclass
class LajeNervuradaBi:
    """Um painel de laje nervurada bidirecional."""

    nome: str = "N1"
    # -- painel -------------------------------------------------------------
    lx: float = 6.48                   # m, vão teórico em x
    ly: float = 6.48                   # m, vão teórico em y
    #: x = 0, x = lx, y = 0, y = ly -- "apoiado" ou "engastado". O apoio é
    #: sempre viga de borda indeslocável (hipótese da grelha e das tabelas).
    bordos: list = field(default_factory=lambda: ["apoiado"] * 4)
    t_apoio: float = 20.0              # cm, largura da viga de borda
    # -- nervuras ------------------------------------------------------------
    ex: float = 108.0                  # cm, intereixo desejado (nervuras ∥ y)
    ey: float = 108.0                  # cm, intereixo desejado (nervuras ∥ x)
    bw: float = 8.0                    # cm, largura da nervura
    h: float = 20.0                    # cm, altura total
    hf: float = 7.0                    # cm, espessura da mesa
    enchimento: str = "Forma removível"
    # -- cargas ------------------------------------------------------------
    g2: float = 1.0                    # kN/m², piso e revestimento
    q: float = 2.0                     # kN/m², variável
    # -- análise -----------------------------------------------------------
    metodo: str = "ambos"              # "placa" | "grelha" | "ambos"
    #: fração da rigidez de flexão (fissuração) na análise do ELU.
    kf: float = 0.7
    #: fração da rigidez à torção elástica. A seção T de nervura e mesa
    #: monolítica não está fissurada à torção em serviço: o padrão é 1,0. A
    #: NBR 6118 (14.6.6.2) permite 15 % (e zero no ELU) -- é a opção mais
    #: conservadora nos momentos das nervuras.
    kt: float = 1.0
    # -- armadura ----------------------------------------------------------
    automatica: bool = True
    n_x: int = 2
    phi_x: float = 12.5
    n_y: int = 2
    phi_y: float = 12.5
    n_neg: int = 2                     # nervuras junto ao bordo engastado
    phi_neg: float = 10.0
    phi_estribo: float = 5.0
    s_estribo: float = 0.0             # cm; 0 -> escolhido pelo programa
    cobrimento: float | None = None    # cm; None -> do ambiente
    #: Uma só armadura por direção (a da nervura mais carregada), como é a
    #: prática; desligada, cada nervura leva a que o seu momento pede.
    armadura_unica: bool = True

    def __post_init__(self) -> None:
        self.bordos = [str(b) for b in self.bordos]
        while len(self.bordos) < 4:
            self.bordos.append("apoiado")
        del self.bordos[4:]

    # -- geometria derivada -------------------------------------------------
    @property
    def nx(self) -> int:
        """Nº de painéis da grelha em x (nervuras ∥ y espaçadas ex)."""
        return max(2, round(self.lx * 100.0 / self.ex))

    @property
    def ny(self) -> int:
        return max(2, round(self.ly * 100.0 / self.ey))

    @property
    def esp_x(self) -> float:
        """Intereixo real das nervuras ∥ y, cm (o painel é dividido em
        ``nx`` partes iguais)."""
        return self.lx * 100.0 / self.nx

    @property
    def esp_y(self) -> float:
        return self.ly * 100.0 / self.ny

    @property
    def hn(self) -> float:
        """Altura da nervura abaixo da mesa, cm."""
        return self.h - self.hf
