# -*- coding: utf-8 -*-
"""
concreto.py
Módulo de elasticidade do concreto pela classe — ABNT NBR 6118:2026, 8.2.8.

Ninguém deveria digitar 26.838.000 kN/m² num campo de módulo. Informa-se a
classe, e o módulo sai da norma:

    E_ci = α_E · 5600 · √f_ck                        para f_ck ≤ 50 MPa
    E_ci = 21,5·10³ · α_E · (f_ck/10 + 1,25)^(1/3)   para f_ck > 50 MPa
    E_cs = α_i · E_ci,   com  α_i = 0,8 + 0,2·(f_ck/80) ≤ 1,0

O ``α_E`` vem do agregado graúdo (8.2.8) e mexe no módulo em até 70 % entre o
arenito e o basalto — é a variável que mais pesa aqui, e por isso ela é
explícita em vez de embutida.

## Três coisas que a leitura da edição 2026 mostrou

**A tabela de valores estimados por classe não existe mais.** A edição de 2014
trazia uma tabela de E_ci, E_cs e α_i de C20 a C90; em 2026 ela foi removida, e
a numeração 8.1 passou para a tabela de retração e fluência. Não há, portanto,
tabela normativa contra a qual conferir estes números — eles saem das
fórmulas, e as conferências deste programa atacam as fórmulas por outro lado
(ver ``validacao.py``).

**O E_ci deixou de ser autorizado na análise global.** O parágrafo de 2014 que
permitia usar o módulo tangente inicial no cálculo de esforços solicitantes
não consta de 8.2.8 nesta edição; ali o E_ci sobra para perdas de protensão e
para idades inferiores a 28 dias. Quem manda na análise é o 14.5.2 — "devendo,
em princípio, ser considerado o módulo de elasticidade secante E_cs" — e o
14.6.4.1. Daí o padrão deste módulo ser o secante.

**O G do concreto fecha sozinho.** O item 8.2.9 dá ``G_c = E_cs/2,4``, e o
mesmo item fixa ν = 0,2. Como o programa calcula ``G = E/(2(1+ν))``, com ν=0,2
isso dá exatamente ``E/2,4``: as duas definições coincidem sem ajuste, e não é
preciso um campo separado para o módulo transversal.
"""

from __future__ import annotations

import math

from .modelo import ErroDeModelo, Material

MPA_PARA_KN_M2 = 1000.0

# 8.2.8 — α_E por agregado graúdo
ALFA_E = {
    "basalto e diabásio": 1.2,
    "granito e gnaisse": 1.0,
    "calcário": 0.9,
    "arenito": 0.7,
}
AGREGADO_PADRAO = "granito e gnaisse"

# 8.2.1 — abaixo de C20 a norma não admite concreto com armadura passiva.
FCK_MINIMO_ARMADO = 20.0

# 8.2.2 — massa específica; aqui em peso específico, kN/m³
PESO_ESPECIFICO_ARMADO = 25.0
PESO_ESPECIFICO_SIMPLES = 24.0

# 8.2.9
POISSON = 0.2

CLASSES = ("C20", "C25", "C30", "C35", "C40", "C45", "C50",
           "C55", "C60", "C70", "C80", "C90")


def fck_da_classe(classe: str) -> float:
    """Lê 'C30' como 30 MPa. Aceita também o número puro."""
    texto = str(classe).strip().upper().replace(",", ".")
    if not texto:
        raise ErroDeModelo("a classe do concreto não foi informada")
    if texto.startswith("C"):
        texto = texto[1:]
    try:
        fck = float(texto)
    except ValueError:
        raise ErroDeModelo(
            f"'{classe}' não é uma classe de concreto; use C20, C30, C45…"
        ) from None
    if fck <= 0.0:
        raise ErroDeModelo(f"classe '{classe}': o fck tem de ser positivo")
    return fck


def alfa_e(agregado: str | None) -> float:
    if not agregado:
        return ALFA_E[AGREGADO_PADRAO]
    chave = str(agregado).strip().lower()
    if chave not in ALFA_E:
        raise ErroDeModelo(
            f"agregado '{agregado}' não está no item 8.2.8; use um de: "
            + ", ".join(ALFA_E))
    return ALFA_E[chave]


def modulo_inicial(fck: float, agregado: str | None = None) -> float:
    """E_ci em MPa — 8.2.8.

    A fronteira entre as duas expressões é ``f_ck = 50 MPa``. Vale notar que
    elas quase se encontram ali: 39 598 MPa pela primeira e 39 603 pela
    segunda, 0,013 % de diferença. Essa quase continuidade é conferida no
    autoteste, e serve de prova de que os dois ramos foram transcritos certos
    — coeficiente errado em qualquer um deles abriria um degrau visível.
    """
    a = alfa_e(agregado)
    if fck <= 50.0:
        return a * 5600.0 * math.sqrt(fck)
    return 21.5e3 * a * (fck / 10.0 + 1.25) ** (1.0 / 3.0)


def alfa_i(fck: float) -> float:
    """α_i = 0,8 + 0,2·(f_ck/80), limitado a 1,0 — 8.2.8.

    O limite passa a valer exatamente em C80, e não antes.
    """
    return min(0.8 + 0.2 * fck / 80.0, 1.0)


def modulo_secante(fck: float, agregado: str | None = None) -> float:
    """E_cs em MPa — o módulo que a análise estrutural usa (14.5.2)."""
    return alfa_i(fck) * modulo_inicial(fck, agregado)


def concreto(nome: str, fck: float, agregado: str | None = None,
             modulo: str = "Ecs", peso_especifico: float | None = None
             ) -> Material:
    """Material de concreto a partir da classe, com o E já em kN/m².

    ``modulo`` escolhe entre o secante e o inicial. O padrão é o secante,
    porque é ele que o item 14.5.2 manda usar na análise; o inicial fica
    disponível para quem precise dele em outra conta.
    """
    if fck <= 0.0:
        raise ErroDeModelo(f"concreto '{nome}': o fck tem de ser positivo")

    if modulo == "Ecs":
        em_mpa = modulo_secante(fck, agregado)
    elif modulo == "Eci":
        em_mpa = modulo_inicial(fck, agregado)
    else:
        raise ErroDeModelo(
            f"concreto '{nome}': módulo '{modulo}' desconhecido; use "
            "'Ecs' ou 'Eci'")

    peso = (PESO_ESPECIFICO_ARMADO if peso_especifico is None
            else peso_especifico)
    return Material(nome, em_mpa * MPA_PARA_KN_M2, POISSON, peso,
                    "concreto", fck, agregado or AGREGADO_PADRAO, modulo)


def abaixo_do_minimo(fck: float) -> bool:
    """8.2.1: a classe C20 é o piso para concreto com armadura passiva."""
    return fck < FCK_MINIMO_ARMADO
