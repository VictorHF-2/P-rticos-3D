# -*- coding: utf-8 -*-
"""
ganchos.py
==========

Geometria dos ganchos das armaduras de tração (item 9.4.2.3).

A norma admite três tipos, e o que muda entre eles é o **ângulo da dobra** e a
**ponta reta** que tem de existir depois dela:

    9.4.2.3 Ganchos das armaduras de tração
    Os ganchos das extremidades das barras da armadura longitudinal de tração
    podem ser:
    a) semicirculares, com ponta reta de comprimento não inferior a 2 f;
    b) em ângulo de 45° (interno), com ponta reta de comprimento não inferior
       a 4 f;
    c) em ângulo reto, com ponta reta de comprimento não inferior a 8 f.

Este módulo é a **única** fonte dessa geometria: dele saem a altura que o
gancho ocupa na seção, o comprimento desenvolvido que entra no comprimento da
barra e a polilinha que o desenho traça. Cálculo e desenho lendo o mesmo lugar
é o que impede o desenho de mostrar um gancho que o cálculo não fez.

O raio da dobra vem da Tabela 9.1, através de :meth:`Aco.raio_dobramento_eixo`,
e **não** depende do tipo: o pino é o mesmo.

Uma consequência prática que só aparece quando as três geometrias convivem: o
gancho semicircular é o mais **baixo** dos três. Ele ocupa 2r de altura, contra
``r + 8 f`` do gancho a 90°. Numa Ø20 são 18 cm contra 25 cm -- é por isso que
ele é a saída em seção apertada.

O que a norma **não** faz é diferenciar o coeficiente α do item 9.4.2.5 por tipo
de gancho: lá está escrito "α = 0,7 para barras tracionadas com gancho, com
cobrimento no plano normal ao do gancho ≥ 3 f", sem distinção. O tipo mexe na
geometria da peça, não na redução do comprimento de ancoragem.
"""

from __future__ import annotations

import math

#: ângulo da dobra, em graus, e ponta reta mínima, em diâmetros (9.4.2.3)
TIPOS: dict[str, tuple[float, float]] = {
    "Semicircular": (180.0, 2.0),
    "45°": (135.0, 4.0),
    "Ângulo reto": (90.0, 8.0),
}

#: tipo adotado quando o projeto não escolhe -- o mais usual em viga
PADRAO = "Ângulo reto"

#: rótulo da ausência de gancho, para a droplist da tabela de resultados
SEM_GANCHO = "Sem gancho"

#: segmentos por 90° de arco no desenho
SEGMENTOS_POR_QUADRANTE = 8


#: os tipos oferecidos ao usuário, com a ausência de gancho na frente
OPCOES = (SEM_GANCHO,) + tuple(TIPOS)


def normalizar(tipo: str) -> str:
    """Devolve um tipo válido; texto desconhecido cai no padrão.

    ``SEM_GANCHO`` atravessa intacto: ele não é um tipo de gancho, é a decisão
    de não usar nenhum, e trocá-lo pelo padrão colocaria gancho onde o projeto
    pediu ancoragem reta.
    """
    if tipo == SEM_GANCHO:
        return SEM_GANCHO
    return tipo if tipo in TIPOS else PADRAO


def angulo(tipo: str) -> float:
    """Ângulo da dobra, em graus; zero quando não há gancho."""
    t = normalizar(tipo)
    return TIPOS[t][0] if t in TIPOS else 0.0


def ponta_reta(phi_mm: float, tipo: str) -> float:
    """Ponta reta mínima do gancho, cm (2 Ø, 4 Ø ou 8 Ø conforme o tipo)."""
    t = normalizar(tipo)
    return TIPOS[t][1] * phi_mm / 10.0 if t in TIPOS else 0.0


def ponta_para_altura(raio: float, phi_mm: float, tipo: str,
                      altura_minima: float) -> float:
    """Ponta reta, cm, que faz o gancho alcançar ``altura_minima``.

    Existe porque o piso construtivo da perna é um piso de **altura**, e
    altura de gancho não é um número que se arbitre: ela sai do raio e da
    ponta. Forçar a perna a 10 cm deixava o desenho com a geometria do tipo
    (3,8 cm num Ø6,3 semicircular) e o cálculo com 10, discordando entre si.
    O que se alonga é a ponta.

    No gancho semicircular a ponta corre **paralela** à barra: alongá-la
    aumenta a aderência e o comprimento, mas não a altura, que é sempre 2r.
    Nesse caso devolve a ponta mínima do tipo, e quem chama fica com a altura
    que a geometria dá.
    """
    minima = ponta_reta(phi_mm, tipo)
    seno = math.sin(math.radians(angulo(tipo)))
    if seno <= 1e-9:                      # ponta horizontal: não ganha altura
        return minima
    ja = altura(raio, phi_mm, tipo)
    if ja >= altura_minima - 1e-9:
        return minima
    return minima + (altura_minima - ja) / seno


def pontos(raio: float, phi_mm: float, tipo: str, sx: float, sy: float,
           segmentos_por_quadrante: int = SEGMENTOS_POR_QUADRANTE,
           ponta: float | None = None
           ) -> list[tuple[float, float]]:
    """Polilinha do gancho, em coordenadas locais a partir do vértice teórico.

    A origem é o vértice -- onde as duas retas se cruzariam num canto vivo. O
    eixo x corre ao longo da barra e ``sx`` diz para que lado segue o trecho
    reto a partir do vértice (+1 = para a direita, o caso do gancho na
    extremidade esquerda). ``sy`` é o lado para onde o gancho aponta.

    Devolve os pontos do início da dobra (tangência com o trecho reto) até a
    ponta, já com a ponta reta do tipo.
    """
    if normalizar(tipo) == SEM_GANCHO:
        return [(0.0, 0.0)]
    theta = math.radians(angulo(tipo))
    n = max(int(round(segmentos_por_quadrante * angulo(tipo) / 90.0)), 2)
    arco = [(sx * raio - sx * raio * math.sin(t),
             sy * raio - sy * raio * math.cos(t))
            for t in (k / n * theta for k in range(n + 1))]
    # a tangente ao fim do arco dá a direção da ponta reta
    dx, dy = -sx * math.cos(theta), sy * math.sin(theta)
    comp = ponta_reta(phi_mm, tipo) if ponta is None else ponta
    fim = arco[-1]
    arco.append((fim[0] + dx * comp, fim[1] + dy * comp))
    return arco


def altura(raio: float, phi_mm: float, tipo: str,
           ponta: float | None = None) -> float:
    """Altura que o gancho ocupa, cm, medida do eixo da barra à ponta.

    Sai da própria polilinha, e não de uma fórmula por tipo: assim não há como
    a altura e o desenho discordarem.
    """
    return max(abs(y) for _x, y in pontos(raio, phi_mm, tipo, 1.0, 1.0,
                                          ponta=ponta))


def avanco(raio: float, phi_mm: float, tipo: str) -> float:
    """Quanto o gancho avança **ao longo** da barra, cm, além do vértice.

    Zero no gancho a 90°, que sobe reto. No semicircular a ponta volta
    paralela à barra e avança; é espaço que o gancho ocupa no vão.
    """
    xs = [x for x, _y in pontos(raio, phi_mm, tipo, 1.0, 1.0)]
    return max(max(xs), 0.0)


def comprimento_desenvolvido(raio: float, phi_mm: float, tipo: str,
                             ponta: float | None = None) -> float:
    """Comprimento de aço do gancho, cm: o arco mais a ponta reta.

    É o que o gancho acrescenta ao comprimento da barra além do vértice
    teórico. Medir pela poligonal do desenho subestimaria o arco; aqui o arco
    entra pelo comprimento verdadeiro, ``r . θ``.
    """
    return raio * math.radians(angulo(tipo)) + (
        ponta_reta(phi_mm, tipo) if ponta is None else ponta)
