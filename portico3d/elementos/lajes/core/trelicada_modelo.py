# -*- coding: utf-8 -*-
"""
trelicada_modelo.py
Dados de entrada da laje treliçada unidirecional: a geometria da nervura, a
treliça, as cargas e a sequência de vãos e apoios da faixa contínua.

Fica separado de ``modelo.py`` só para não criar import circular -- o
``Pavimento`` guarda a lista de faixas treliçadas, e o motor
(``trelicada.py``) precisa do ``Config`` que mora lá.

Convenções:
    comprimentos ... cm (os vãos também, eixo a eixo dos apoios);
    cargas ......... superficiais em kN/m², lineares em kN/m **por nervura**;
    uma "faixa" é uma nervura contínua, de apoio a apoio, com quantos vãos
    forem lançados -- as nervuras vizinhas são idênticas a ela.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Treliças eletrossoldadas padronizadas (NBR 14862; Manual Técnico de Lajes
#: Treliçadas, ArcelorMittal, p. 5): designação -> altura (mm), Ø do fio
#: superior, Ø da diagonal, Ø de cada fio inferior (mm) e massa linear
#: (kg/m). Os fios são CA-60 entalhado.
TRELICAS = {
    "TR 8644": (80, 6.0, 4.2, 4.2, 0.735),
    "TR 8645": (80, 6.0, 4.2, 5.0, 0.825),
    "TR 12645": (120, 6.0, 4.2, 5.0, 0.886),
    "TR 12646": (120, 6.0, 4.2, 6.0, 1.016),
    "TR 16745": (160, 7.0, 4.2, 5.0, 1.032),
    "TR 16746": (160, 7.0, 4.2, 6.0, 1.168),
    "TR 20745": (200, 7.0, 4.2, 5.0, 1.111),
    "TR 20756": (200, 7.0, 5.0, 6.0, 1.446),
    "TR 25856": (250, 8.0, 5.0, 6.0, 1.686),
    "TR 25858": (250, 8.0, 5.0, 8.0, 2.024),
    "TR 30856": (300, 8.0, 5.0, 6.0, 1.823),
    "TR 30858": (300, 8.0, 5.0, 8.0, 2.168),
}

#: "Treliça" da nervurada moldada no local: nenhuma. O motor da treliçada
#: trata a ausência como fio inferior de Ø0 e altura 0.
SEM_TRELICA = "Nenhuma"
TRELICAS[SEM_TRELICA] = (0, 0.0, 0.0, 0.0, 0.0)

#: Diâmetros da armadura longitudinal da nervura moldada no local, mm (CA-50).
BITOLAS_MOLDADA = (8.0, 10.0, 12.5, 16.0, 20.0, 25.0)

#: Passo da treliça, cm -- distância entre nós, sempre 20 cm (manual, p. 4).
PASSO_TRELICA = 20.0

#: Peso específico do enchimento, kN/m³ (manual, p. 22: EPS de 12 a 25 kgf/m³
#: e cerâmico de 600 kgf/m³ equivalentes; o exemplo do material usa 18).
ENCHIMENTOS = {"EPS": 0.18, "Cerâmico": 6.0, "Forma removível": 0.0}

#: Armaduras adicionais que o programa escolhe sozinho (manual, p. 22):
#: bitola em mm -> categoria do aço. Fios em CA-60, barras em CA-50.
ADICIONAIS = ((4.2, "CA-60"), (5.0, "CA-60"), (6.0, "CA-60"),
              (8.0, "CA-60"), (6.3, "CA-50"), (10.0, "CA-50"),
              (12.5, "CA-50"))

#: Comprimento vertical do gancho de ancoragem da armadura adicional, cm, por
#: bitola em mm (manual, p. 35).
GANCHO_ADICIONAL = {4.2: 5.0, 5.0: 6.0, 6.0: 8.0, 7.0: 9.0, 8.0: 10.0,
                    10.0: 12.0, 12.5: 14.0, 16.0: 18.0}

#: Bitolas de negativa que o programa pode escolher, mm (CA-50).
NEGATIVAS = (5.0, 6.3, 8.0, 10.0, 12.5, 16.0)


@dataclass
class VaoTrelicado:
    """Um vão da faixa, de eixo a eixo dos apoios."""

    L: float = 400.0                   # cm
    g: float = 1.0                     # kN/m², além do peso próprio
    q: float = 1.5                     # kN/m², variável
    carga_linear: float = 0.0          # kN/m por nervura (parede sobre ela)
    n_adicional: int = 1
    phi_adicional: float = 8.0         # mm
    aco_adicional: str = "CA-60"


@dataclass
class ApoioTrelicado:
    """Um apoio da faixa (viga ou parede sob a laje)."""

    t: float = 20.0                    # cm, largura do apoio
    macico: float = 0.0                # cm de trecho maciço, de cada lado
    n_negativa: int = 2
    phi_negativa: float = 8.0          # mm


@dataclass
class LajeTrelicada:
    """Uma faixa de laje treliçada unidirecional, contínua ou não."""

    nome: str = "T1"
    # -- seção da nervura ---------------------------------------------------
    base: float = 12.0                 # cm, largura da base da vigota
    apoio_enchimento: float = 1.5      # cm, de cada lado da base
    largura_bloco: float = 40.0        # cm, o Le do bloco de enchimento
    altura_enchimento: float = 12.0    # cm, He
    capa: float = 5.0                  # cm
    enchimento: str = "EPS"
    trelica: str = "TR 12646"
    apoio_vigota: float = 5.0          # cm de vigota dentro de cada apoio
    largura_laje: float = 4.0          # m, só para quantitativo
    # -- faixa --------------------------------------------------------------
    vaos: list = field(default_factory=lambda: [VaoTrelicado()])
    apoios: list = field(default_factory=lambda: [ApoioTrelicado(),
                                                  ApoioTrelicado()])
    balanco_esq: float = 0.0           # cm
    balanco_dir: float = 0.0           # cm
    parapeito_esq: float = 0.0         # kN/m ao longo da borda livre
    parapeito_dir: float = 0.0
    # -- critérios ----------------------------------------------------------
    delta: float = 1.0                 # redistribuição (14.6.4.3), >= 0,75
    automatica: bool = True            # o programa escolhe as armaduras
    macico_automatico: bool = True     # e o trecho maciço necessário
    contraflecha: float = 0.0          # cm
    cobrimento: float | None = None    # cm; None -> do ambiente
    #: Estádio I da flecha com a armadura homogeneizada, como faz o material
    #: de referência (Estude Engenharia, parte 3). A NBR 6118 (17.3.2.1.1)
    #: manda a seção **bruta** de concreto -- é o padrão, o mais conservador.
    inercia_homogeneizada: bool = False
    #: ``"trelicada"`` (vigota com treliça) ou ``"nervurada"`` (nervura
    #: moldada no local, armadura em barras e estribos). Na nervurada a
    #: ``trelica`` é ``SEM_TRELICA``, ``base`` = ``bw`` e a "adicional" de
    #: cada vão é a armadura longitudinal principal.
    sistema: str = "trelicada"
    #: estribo mínimo da nervurada, mm, e espaçamento (0 = o programa
    #: escolhe).
    phi_estribo: float = 5.0
    s_estribo: float = 0.0

    def __post_init__(self) -> None:
        if self.sistema == "nervurada":
            self.trelica = SEM_TRELICA
            self.apoio_enchimento = 0.0
        self.vaos = [x if isinstance(x, VaoTrelicado) else VaoTrelicado(**x)
                     for x in self.vaos]
        self.apoios = [x if isinstance(x, ApoioTrelicado)
                       else ApoioTrelicado(**x) for x in self.apoios]
        # a lista de apoios acompanha a de vãos: n vãos pedem n + 1 apoios
        while len(self.apoios) < len(self.vaos) + 1:
            self.apoios.append(ApoioTrelicado())
        del self.apoios[len(self.vaos) + 1:]

    # -- geometria derivada -------------------------------------------------
    @property
    def moldada(self) -> bool:
        """Nervura moldada no local (sem vigota nem treliça)."""
        return self.sistema == "nervurada"

    @property
    def bw(self) -> float:
        """Largura da nervura acima da base, cm."""
        return self.base - 2.0 * self.apoio_enchimento

    @property
    def intereixo(self) -> float:
        """Distância entre eixos de nervuras, cm."""
        return self.bw + self.largura_bloco

    @property
    def h(self) -> float:
        """Altura total da laje, cm."""
        return self.altura_enchimento + self.capa
