# -*- coding: utf-8 -*-
"""
aberturas_modelo.py
Dado de entrada de um furo ou abertura na alma da viga (NBR 6118:2026,
13.2.5 e 21.3) e a conferência da geometria -- o que é impossível de
construir é erro de entrada; os limites da norma (distância às faces,
dispensa, banzos, seção reduzida) são verificação, em :mod:`aberturas`.

Fica fora de ``modelo.py`` para que o modelo só ganhe o campo e a leitura, e
para que este módulo possa ser importado por ele sem import circular: aqui
nada importa o modelo, a viga entra por duck typing.

Convenções (as mesmas das cargas, ``modelo.py``): ``x_ini`` em **m**, do nó 0
da viga (o eixo do primeiro apoio, ou a ponta do balanço esquerdo); o resto
em cm.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from . import avisos as av

#: "horizontal" atravessa a largura (13.2.5.1); "vertical" atravessa a altura
#: (21.3.3).
TIPOS_ABERTURA = ("horizontal", "vertical")
FORMAS_ABERTURA = ("retangular", "circular")

#: De onde saem M_d e V_d de cálculo do furo: o máximo da envoltória ELU no
#: trecho que o furo ocupa (conservador, padrão) ou a envoltória na seção do
#: centro do furo.
CRITERIO_PIOR_TRECHO = "pior no trecho"
CRITERIO_CENTRO = "centro do furo"
CRITERIOS_ESFORCO_FURO = (CRITERIO_PIOR_TRECHO, CRITERIO_CENTRO)


@dataclass
class Abertura:
    """Furo ou abertura na alma da viga.

    ``x_ini`` em **m**, do nó 0 da viga ao início do furo (a mesma
    referência das cargas). O resto em cm:

    * horizontal (atravessa a largura bw): ``comprimento`` x ``altura`` se
      retangular, ou diâmetro ``altura`` se circular; ``topo`` é a
      distância da face superior da viga (no trecho do furo) ao topo do
      furo;
    * vertical (atravessa a altura h): sempre circular, diâmetro
      ``altura``; ``y`` é a distância da face lateral ao eixo do furo
      (0 = centrado na largura).

    ``criterio_esforcos`` diz de onde saem M_d e V_d do furo (ver
    :data:`CRITERIOS_ESFORCO_FURO`).
    """

    descricao: str = ""
    tipo: str = "horizontal"
    forma: str = "retangular"
    x_ini: float = 1.0
    comprimento: float = 30.0
    altura: float = 10.0
    topo: float = 20.0
    y: float = 0.0
    criterio_esforcos: str = CRITERIO_PIOR_TRECHO

    @property
    def vertical(self) -> bool:
        return self.tipo == "vertical"

    @property
    def circular(self) -> bool:
        return self.vertical or self.forma == "circular"

    @property
    def diametro(self) -> float:
        return self.altura

    @property
    def extensao(self) -> float:
        """Dimensão ao longo do vão, cm."""
        return self.altura if self.circular else self.comprimento

    @property
    def x_fim(self) -> float:
        """Fim do furo, m."""
        return self.x_ini + self.extensao / 100.0

    @property
    def x_centro(self) -> float:
        return self.x_ini + self.extensao / 200.0

    def y_eixo(self, b: float) -> float:
        """Eixo de um furo vertical na largura, cm da face."""
        return self.y if self.y > 1e-9 else b / 2.0

    def nome(self, i: int) -> str:
        return f"A{i + 1}" + (f" ({self.descricao})" if self.descricao else "")


def de_dict(d: dict) -> Abertura:
    """Abertura a partir do JSON, ignorando chaves desconhecidas."""
    nomes = {f.name for f in fields(Abertura)}
    return Abertura(**{k: v for k, v in (d or {}).items() if k in nomes})


def erros_da_abertura(viga, i: int) -> list[str]:
    """Erros de geometria da abertura ``i`` (texto puro, sem nível)."""
    a = viga.aberturas[i]
    nome = f"Abertura {a.nome(i)}"
    if a.tipo not in TIPOS_ABERTURA:
        return [f"{nome}: tipo “{a.tipo}” desconhecido."]
    if not a.vertical and a.forma not in FORMAS_ABERTURA:
        return [f"{nome}: forma “{a.forma}” desconhecida."]
    erros: list[str] = []
    if a.criterio_esforcos not in CRITERIOS_ESFORCO_FURO:
        erros.append(f"{nome}: critério de esforços "
                     f"“{a.criterio_esforcos}” desconhecido.")
    if a.altura <= 0 or (not a.circular and a.comprimento <= 0):
        return erros + [f"{nome}: as dimensões do furo devem ser positivas."]
    L = viga.comprimento
    if a.x_ini < -1e-9 or a.x_fim > L + 1e-9:
        return erros + [f"{nome}: o furo ({a.x_ini:g} a {a.x_fim:g} m) sai "
                        f"da viga (0 a {L:g} m)."]
    # sobre o pilar não há alma livre: o furo encostaria no apoio
    xs = viga.x_apoios
    for k, ap in enumerate(viga.apoios):
        if ap.tipo == "livre":
            continue
        e, d = xs[k] - ap.largura / 200.0, xs[k] + ap.largura / 200.0
        if a.x_ini < d - 1e-9 and a.x_fim > e + 1e-9:
            erros.append(f"{nome}: o furo ({a.x_ini:g} a {a.x_fim:g} m) "
                         f"invade o apoio {k + 1} (de {e:g} a {d:g} m).")
    # um furo, uma seção: atravessar uma mudança de seção não é coberto
    k0, k1 = viga.trecho_em(a.x_ini + 1e-6), viga.trecho_em(a.x_fim - 1e-6)
    if k0 != k1:
        return erros + [f"{nome}: o furo atravessa uma mudança de seção "
                        f"(trechos {k0 + 1} e {k1 + 1}) — caso não coberto; "
                        f"desloque o furo ou divida-o."]
    secao = viga.trechos[k0].secao
    b, h = secao.bw, secao.h
    if a.vertical:
        y = a.y_eixo(b)
        if a.diametro >= b:
            erros.append(f"{nome}: diâmetro {a.diametro:g} cm não cabe na "
                         f"largura bw = {b:g} cm.")
        elif y - a.diametro / 2 <= 0 or y + a.diametro / 2 >= b:
            erros.append(f"{nome}: o furo vertical (eixo a {y:g} cm da face) "
                         f"sai da largura da viga.")
        return erros
    if a.topo <= 0 or a.topo + a.altura >= h:
        erros.append(f"{nome}: o furo (topo a {a.topo:g} cm, altura "
                     f"{a.altura:g} cm) não fica dentro da altura h = {h:g} "
                     f"cm — encostar numa face é recorte, não furo.")
    elif secao.tipo == "T" and a.topo < secao.hf - 1e-9:
        erros.append(f"{nome}: o furo horizontal entra na mesa (topo a "
                     f"{a.topo:g} cm < hf = {secao.hf:g} cm) — atravessaria a "
                     f"mesa colaborante; caso não coberto.")
    elif secao.tipo == "T invertida" and \
            a.topo + a.altura > h - secao.hf + 1e-9:
        erros.append(f"{nome}: o furo horizontal entra na mesa inferior "
                     f"(hf = {secao.hf:g} cm) — caso não coberto.")
    return erros


def validar(viga) -> list[str]:
    """Erros de geometria de todas as aberturas, como avisos de erro."""
    erros: list[str] = []
    abertas = list(getattr(viga, "aberturas", []) or [])
    for i in range(len(abertas)):
        erros += erros_da_abertura(viga, i)
    ordem = sorted(range(len(abertas)), key=lambda k: abertas[k].x_ini)
    for k1, k2 in zip(ordem, ordem[1:]):
        a1, a2 = abertas[k1], abertas[k2]
        if a2.x_ini < a1.x_fim - 1e-9:
            if a1.vertical != a2.vertical:
                erros.append(f"Aberturas {a1.nome(k1)} e {a2.nome(k2)}: furo "
                             f"horizontal e vertical no mesmo trecho da viga "
                             f"— caso não coberto.")
            else:
                erros.append(f"Aberturas {a1.nome(k1)} e {a2.nome(k2)} ocupam "
                             f"o mesmo trecho da viga — informe uma abertura "
                             f"só, que envolva as duas (13.2.5).")
    return [av.erro(e) for e in erros]


def invalidas(viga) -> set[int]:
    """Índices das aberturas com geometria impossível (não calculadas)."""
    saida = {i for i in range(len(viga.aberturas))
             if erros_da_abertura(viga, i)}
    abertas = viga.aberturas
    for i, a in enumerate(abertas):
        for k, b in enumerate(abertas):
            if k != i and b.x_ini < a.x_fim - 1e-9 and a.x_ini < b.x_fim - 1e-9:
                saida.add(i)
    return saida
