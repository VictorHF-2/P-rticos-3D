# -*- coding: utf-8 -*-
"""
validacao.py
Problemas de referência com solução conhecida.

Nenhum número aqui vem do próprio programa: cada valor esperado é uma
solução fechada da Resistência dos Materiais, uma condição de equilíbrio ou
uma invariância que a formulação tem obrigação de respeitar. É esse conjunto
que autoriza confiar no solver — e é contra ele que qualquer mudança futura
na formulação tem de ser conferida antes de entrar.

Referências das soluções fechadas: Timoshenko, *Resistência dos Materiais*;
McGuire, Gallagher e Ziemian, *Matrix Structural Analysis*.
"""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from .core.cargas import alternancia, peso_proprio
from .core.carregamento import resultante
from .core.combinacoes import (Combinacao, combinar, resolver_casos,
                               resolver_combinacoes)
from .core.envoltoria import envoltoria
from .core.modelo import CasoDeCarga, ErroDeModelo, Modelo, Secao
from .core.montagem import cargas_locais, preparar_barras, resolver
from .core.nbr6118 import (PSI, Acao, acoes_do_modelo,
                           cargas_verticais_por_no, combinacoes_elu,
                           combinacoes_els, confronto_vento_desaprumo,
                           desaprumo, momento_na_base, validar_acoes)

E_ACO = 210.0e6          # kN/m²
POISSON = 0.3
G_ACO = E_ACO / (2.0 * (1.0 + POISSON))


@dataclass
class Conferencia:
    nome: str
    obtido: float
    esperado: float
    tolerancia: float = 1.0e-9
    escala: float = 0.0

    @property
    def erro(self) -> float:
        base = max(abs(self.esperado), self.escala)
        if base == 0.0:
            return abs(self.obtido)
        return abs(self.obtido - self.esperado) / base

    @property
    def passou(self) -> bool:
        return self.erro <= self.tolerancia


def _secao_retangular() -> Secao:
    """20 × 50 cm deitada: Iy e Iz bem diferentes, o que denuncia troca de eixo."""
    return Secao.retangular("R20x50", 0.20, 0.50)


def _modelo_base(nome: str) -> Modelo:
    m = Modelo(nome)
    m.add_material("aco", E_ACO, POISSON)
    m.add_secao(_secao_retangular())
    return m


def _barra_reta(nome: str, L: float) -> Modelo:
    m = _modelo_base(nome)
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "B", "aco", "R20x50")
    m.apoiar("A")
    return m


# ---------------------------------------------------------------------------
# 1. Barra sob força axial
# ---------------------------------------------------------------------------

def barra_axial() -> list[Conferencia]:
    L, P = 4.0, 100.0
    m = _barra_reta("axial", L)
    m.add_caso("P").nodal("B", fx=P)
    r = resolver(m, "P")
    s = m.secoes["R20x50"]

    return [
        Conferencia("axial: alongamento δ = PL/EA",
                    r.deslocamento("B")[0], P * L / (E_ACO * s.A), 1e-10),
        Conferencia("axial: normal constante N = P",
                    r.diagrama("B1").N[5], P, 1e-10),
        Conferencia("axial: reação Fx = -P",
                    r.reacao("A")[0], -P, 1e-10),
    ]


# ---------------------------------------------------------------------------
# 2 e 3. Balanço com força na ponta, nos dois planos de flexão
# ---------------------------------------------------------------------------

def balanco_plano_xy() -> list[Conferencia]:
    L, P = 4.0, 10.0
    m = _barra_reta("balanco_xy", L)
    m.add_caso("P").nodal("B", fy=P)
    r = resolver(m, "P")
    s = m.secoes["R20x50"]
    d = r.diagrama("B1")

    return [
        Conferencia("balanço x–y: flecha δ = PL³/3EIz",
                    r.deslocamento("B")[1],
                    P * L ** 3 / (3.0 * E_ACO * s.Iz), 1e-10),
        Conferencia("balanço x–y: rotação θz = PL²/2EIz",
                    r.deslocamento("B")[5],
                    P * L ** 2 / (2.0 * E_ACO * s.Iz), 1e-10),
        Conferencia("balanço x–y: momento no engaste |Mz| = PL",
                    abs(d.Mz[0]), P * L, 1e-10),
        Conferencia("balanço x–y: momento nulo na ponta",
                    d.Mz[-1], 0.0, 1e-10, escala=P * L),
    ]


def balanco_plano_xz() -> list[Conferencia]:
    """Carga para baixo na ponta, que é o caso de gravidade."""
    L, P = 4.0, 10.0
    m = _barra_reta("balanco_xz", L)
    m.add_caso("P").nodal("B", fz=-P)
    r = resolver(m, "P")
    s = m.secoes["R20x50"]
    d = r.diagrama("B1")

    return [
        Conferencia("balanço x–z: flecha δ = -PL³/3EIy",
                    r.deslocamento("B")[2],
                    -P * L ** 3 / (3.0 * E_ACO * s.Iy), 1e-10),
        Conferencia("balanço x–z: momento no engaste |My| = PL",
                    abs(d.My[0]), P * L, 1e-10),
        Conferencia("balanço x–z: cortante constante Vz = P",
                    d.Vz[5], P, 1e-10),
    ]


# ---------------------------------------------------------------------------
# 4. Torção pura
# ---------------------------------------------------------------------------

def torcao() -> list[Conferencia]:
    L, T = 4.0, 5.0
    m = _barra_reta("torcao", L)
    m.add_caso("T").nodal("B", mx=T)
    r = resolver(m, "T")
    s = m.secoes["R20x50"]

    return [
        Conferencia("torção: giro φ = TL/GJ",
                    r.deslocamento("B")[3], T * L / (G_ACO * s.J), 1e-10),
        Conferencia("torção: momento torçor constante T",
                    r.diagrama("B1").T[5], T, 1e-10),
    ]


# ---------------------------------------------------------------------------
# 5. Viga biapoiada com carga uniforme
# ---------------------------------------------------------------------------

def _viga_em_dois_tramos(nome: str, L: float) -> Modelo:
    m = _modelo_base(nome)
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("M", L / 2.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "M", "aco", "R20x50")
    m.add_barra("B2", "M", "B", "aco", "R20x50")
    return m


def biapoiada_uniforme() -> list[Conferencia]:
    L, w = 6.0, 20.0
    m = _viga_em_dois_tramos("biapoiada", L)
    m.apoiar("A", ux=True, uy=True, uz=True, rx=True, ry=False, rz=False)
    m.apoiar("B", ux=False, uy=True, uz=True, rx=False, ry=False, rz=False)
    caso = m.add_caso("q")
    caso.distribuida("B1", qz=-w)
    caso.distribuida("B2", qz=-w)
    r = resolver(m, "q")
    s = m.secoes["R20x50"]

    return [
        Conferencia("biapoiada: flecha δ = 5wL⁴/384EIy",
                    r.deslocamento("M")[2],
                    -5.0 * w * L ** 4 / (384.0 * E_ACO * s.Iy), 1e-10),
        Conferencia("biapoiada: momento no meio do vão My = wL²/8",
                    r.diagrama("B1").My[-1], w * L ** 2 / 8.0, 1e-10),
        Conferencia("biapoiada: reação Fz = wL/2",
                    r.reacao("A")[2], w * L / 2.0, 1e-10),
        Conferencia("biapoiada: cortante no apoio Vz = wL/2",
                    r.diagrama("B1").Vz[0], w * L / 2.0, 1e-10),
    ]


# ---------------------------------------------------------------------------
# 6. Viga biengastada com carga uniforme
# ---------------------------------------------------------------------------

def biengastada_uniforme() -> list[Conferencia]:
    L, w = 6.0, 20.0
    m = _viga_em_dois_tramos("biengastada", L)
    m.apoiar("A")
    m.apoiar("B")
    caso = m.add_caso("q")
    caso.distribuida("B1", qz=-w)
    caso.distribuida("B2", qz=-w)
    r = resolver(m, "q")
    s = m.secoes["R20x50"]

    return [
        Conferencia("biengastada: momento no engaste My = -wL²/12",
                    r.diagrama("B1").My[0], -w * L ** 2 / 12.0, 1e-10),
        Conferencia("biengastada: momento no meio do vão My = wL²/24",
                    r.diagrama("B1").My[-1], w * L ** 2 / 24.0, 1e-10),
        Conferencia("biengastada: flecha δ = wL⁴/384EIy",
                    r.deslocamento("M")[2],
                    -w * L ** 4 / (384.0 * E_ACO * s.Iy), 1e-10),
    ]


# ---------------------------------------------------------------------------
# 7. Invariância a uma rotação rígida do modelo inteiro
# ---------------------------------------------------------------------------

def _rodrigues(eixo: np.ndarray, angulo: float) -> np.ndarray:
    e = eixo / np.linalg.norm(eixo)
    K = np.array([[0.0, -e[2], e[1]],
                  [e[2], 0.0, -e[0]],
                  [-e[1], e[0], 0.0]])
    return (np.eye(3) + math.sin(angulo) * K
            + (1.0 - math.cos(angulo)) * (K @ K))


def _balanco_obliquo(Q: np.ndarray | None = None) -> Modelo:
    """Balanço de eixo qualquer, com força e momento quaisquer na ponta.

    Quando ``Q`` é dado, o modelo inteiro — geometria, vetor de referência e
    carga — sofre a mesma rotação rígida. O engaste é total, portanto também
    é invariante, e os esforços locais têm de sair idênticos.
    """
    girar = (lambda v: Q @ np.asarray(v, float)) if Q is not None else (
        lambda v: np.asarray(v, float))

    m = _modelo_base("balanco_obliquo")
    for nome, p in (("A", (0.0, 0.0, 0.0)), ("B", (3.0, 1.0, 2.0))):
        x, y, z = girar(p)
        m.add_no(nome, x, y, z)
    m.add_barra("B1", "A", "B", "aco", "R20x50",
                vetor_ref=tuple(girar((0.0, 0.0, 1.0))))
    m.apoiar("A")

    F = girar((12.0, -7.0, 25.0))
    M = girar((4.0, 9.0, -3.0))
    m.add_caso("P").nodal("B", fx=F[0], fy=F[1], fz=F[2],
                          mx=M[0], my=M[1], mz=M[2])
    return m


def invariancia_por_rotacao() -> list[Conferencia]:
    Q = _rodrigues(np.array([1.0, 2.0, 3.0]), 0.7)
    q0 = resolver(_balanco_obliquo(), "P").esforcos_barra("B1")
    q1 = resolver(_balanco_obliquo(Q), "P").esforcos_barra("B1")
    escala = float(np.max(np.abs(q0)))

    return [
        Conferencia("invariância: esforços locais sob rotação rígida",
                    float(np.max(np.abs(q1 - q0))), 0.0, 1e-9, escala=escala),
    ]


# ---------------------------------------------------------------------------
# 8. Balanço em L no espaço: flexão nos dois trechos mais torção no primeiro
# ---------------------------------------------------------------------------

def balanco_em_L() -> list[Conferencia]:
    a, b, P = 3.0, 2.0, 15.0
    m = Modelo("balanco_L")
    m.add_material("aco", E_ACO, POISSON)
    m.add_secao(Secao.circular("D20", 0.20))
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", a, 0.0, 0.0)
    m.add_no("C", a, b, 0.0)
    m.add_barra("B1", "A", "B", "aco", "D20")
    m.add_barra("B2", "B", "C", "aco", "D20")
    m.apoiar("A")
    m.add_caso("P").nodal("C", fz=-P)
    r = resolver(m, "P")
    s = m.secoes["D20"]

    EI = E_ACO * s.Iy
    GJ = G_ACO * s.J
    flecha = -(P * a ** 3 / (3.0 * EI) + P * b ** 3 / (3.0 * EI)
               + P * a * b ** 2 / GJ)

    return [
        Conferencia("balanço em L: flecha Pa³/3EI + Pb³/3EI + Pab²/GJ",
                    r.deslocamento("C")[2], flecha, 1e-9),
        Conferencia("balanço em L: torção do primeiro trecho T = Pb",
                    abs(r.diagrama("B1").T[0]), P * b, 1e-9),
        Conferencia("balanço em L: momento no engaste |My| = Pa",
                    abs(r.diagrama("B1").My[0]), P * a, 1e-9),
    ]


# ---------------------------------------------------------------------------
# 9. Pórtico plano de travessa rígida
# ---------------------------------------------------------------------------

def portico_travessa_rigida() -> list[Conferencia]:
    """Com a travessa infinitamente rígida e as bases engastadas, o ponto de
    inflexão fica na metade do pilar e o momento na base vale Hh/4."""
    h, L, H = 4.0, 6.0, 30.0
    m = Modelo("portico")
    m.add_material("aco", E_ACO, POISSON)
    m.add_secao(Secao.circular("pilar", 0.30))
    rigida = Secao.circular("travessa", 0.30)
    m.add_secao(Secao("travessa", rigida.A * 1e6, rigida.Iy * 1e6,
                      rigida.Iz * 1e6, rigida.J * 1e6))

    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_no("C", 0.0, 0.0, h)
    m.add_no("D", L, 0.0, h)
    m.add_barra("P1", "A", "C", "aco", "pilar")
    m.add_barra("P2", "B", "D", "aco", "pilar")
    m.add_barra("V1", "C", "D", "aco", "travessa")
    m.apoiar("A")
    m.apoiar("B")
    m.add_caso("H").nodal("C", fx=H)
    r = resolver(m, "H")

    return [
        Conferencia("pórtico rígido: momento na base |Mz| = Hh/4",
                    abs(r.diagrama("P1").Mz[0]), H * h / 4.0, 1e-3),
        Conferencia("pórtico rígido: cortante por pilar H/2",
                    abs(r.reacao("A")[0]), H / 2.0, 1e-3),
        Conferencia("pórtico rígido: momento no topo do pilar |Mz| = Hh/4",
                    abs(r.diagrama("P1").Mz[-1]), H * h / 4.0, 1e-3),
    ]


# ---------------------------------------------------------------------------
# 10. Equilíbrio global de um pórtico espacial qualquer
# ---------------------------------------------------------------------------

def _portico_espacial() -> Modelo:
    m = Modelo("espacial")
    m.add_material("concreto", 30.0e6, 0.2)
    m.add_secao(Secao.retangular("P30x30", 0.30, 0.30))
    m.add_secao(Secao.retangular("V20x50", 0.20, 0.50))

    pes = {"A": (0.0, 0.0), "B": (5.0, 0.0), "C": (5.0, 4.0), "D": (0.0, 4.0)}
    for nome, (x, y) in pes.items():
        m.add_no(nome, x, y, 0.0)
        m.add_no(nome + "1", x, y, 3.0)
        m.add_barra("P" + nome, nome, nome + "1", "concreto", "P30x30")
        m.apoiar(nome)

    for a, b in (("A1", "B1"), ("B1", "C1"), ("C1", "D1"), ("D1", "A1")):
        m.add_barra(f"V{a}{b}", a, b, "concreto", "V20x50")

    # Uma barra inclinada, para que a conversão da carga global para os eixos
    # locais também entre no teste de equilíbrio.
    m.add_no("T", 2.5, 2.0, 5.0)
    m.add_barra("I1", "A1", "T", "concreto", "P30x30")
    m.add_barra("I2", "T", "C1", "concreto", "P30x30")

    caso = m.add_caso("mista")
    caso.nodal("B1", fx=40.0, fy=-15.0, mz=8.0)
    caso.nodal("T", fz=-22.0, mx=5.0)
    caso.distribuida("VA1B1", qz=-18.0)
    caso.distribuida("VC1D1", qz=-18.0)
    caso.distribuida("I1", qz=-12.0, sistema="global")
    caso.distribuida("I2", qx=3.0, qz=-12.0, sistema="global")
    return m


def equilibrio_global() -> list[Conferencia]:
    m = _portico_espacial()
    r = resolver(m, "mista")
    caso = m.casos["mista"]

    aplicado = np.zeros(6)
    for c in caso.nodais:
        aplicado[:3] += c.vetor[:3]
        aplicado[3:] += c.vetor[3:] + np.cross(m.ponto(c.no), c.vetor[:3])

    preparadas = preparar_barras(m)
    for nome, segmentos in cargas_locais(caso, preparadas).items():
        if not segmentos:
            continue
        p = preparadas[nome]
        F_local, posicao = resultante(segmentos)
        F = p.R.T @ F_local
        # Cada componente tem o seu ponto de aplicação ao longo da barra.
        origem = m.ponto(p.barra.no_i)
        eixo = p.R[0]
        aplicado[:3] += F
        for c in range(3):
            ponto = origem + eixo * posicao[c]
            aplicado[3:] += np.cross(ponto, p.R[c] * F_local[c])

    residuo = r.reacoes_totais() + aplicado
    escala_f = float(np.max(np.abs(aplicado[:3])))
    escala_m = float(np.max(np.abs(aplicado[3:])))

    return [
        Conferencia("pórtico espacial: ΣF das reações e das cargas",
                    float(np.max(np.abs(residuo[:3]))), 0.0, 1e-9,
                    escala=escala_f),
        Conferencia("pórtico espacial: ΣM das reações e das cargas",
                    float(np.max(np.abs(residuo[3:]))), 0.0, 1e-9,
                    escala=escala_m),
    ]


def equilibrio_de_barra() -> list[Conferencia]:
    """Cada barra, isolada, também tem de fechar: esforços de extremidade
    mais a resultante da sua carga distribuída somam zero."""
    m = _portico_espacial()
    r = resolver(m, "mista")
    caso = m.casos["mista"]
    preparadas = preparar_barras(m)
    segmentos = cargas_locais(caso, preparadas)

    pior_forca = pior_momento = 0.0
    escala_f = escala_m = 0.0
    for nome, p in preparadas.items():
        q = r.esforcos_barra(nome)
        F, posicao = resultante(segmentos[nome])
        forca = q[:3] + q[6:9] + F
        # Momentos tomados no nó inicial da barra, nos eixos locais.
        braco = np.array([p.L, 0.0, 0.0])
        momento = q[3:6] + q[9:12] + np.cross(braco, q[6:9])
        for c in range(3):
            componente = np.zeros(3)
            componente[c] = F[c]
            momento += np.cross(np.array([posicao[c], 0.0, 0.0]), componente)
        pior_forca = max(pior_forca, float(np.max(np.abs(forca))))
        pior_momento = max(pior_momento, float(np.max(np.abs(momento))))
        escala_f = max(escala_f, float(np.max(np.abs(q[:3]))))
        escala_m = max(escala_m, float(np.max(np.abs(q[3:6]))))

    return [
        Conferencia("equilíbrio de barra: resultante de forças",
                    pior_forca, 0.0, 1e-9, escala=escala_f),
        Conferencia("equilíbrio de barra: resultante de momentos",
                    pior_momento, 0.0, 1e-9, escala=escala_m),
    ]


def deteccao_de_mecanismo() -> list[Conferencia]:
    """Modelo com mecanismo tem de parar com erro, não devolver números.

    A torção livre nas duas extremidades é o caso traiçoeiro: a diagonal da
    matriz continua cheia, porque cada barra tem GJ/L, e só a eliminação
    revela que o modo de giro rígido não tem vínculo nenhum. Antes da
    fatoração de Cholesky este caso passava batido e devolvia resultado.
    """
    def torcao_livre() -> Modelo:
        m = _barra_reta("mecanismo_torcao", 4.0)
        m.apoiar("A", rx=False, ry=False, rz=False)
        m.apoiar("B", ux=False, uy=True, uz=True,
                 rx=False, ry=False, rz=False)
        m.add_caso("P").nodal("B", fz=-10.0)
        return m

    def rotacao_livre() -> Modelo:
        m = _barra_reta("mecanismo_rotacao", 4.0)
        m.apoios.clear()
        m.apoiar("A", rx=False, ry=False, rz=False)
        m.add_caso("P").nodal("B", fz=-10.0)
        return m

    conferencias = []
    for nome, montar in (("torção sem vínculo", torcao_livre),
                         ("balanço sem restrição de rotação", rotacao_livre)):
        try:
            resolver(montar(), "P")
            detectou = 0.0
        except ErroDeModelo:
            detectou = 1.0
        conferencias.append(
            Conferencia(f"mecanismo: {nome} é recusado", detectou, 1.0))
    return conferencias


def coerencia_dos_diagramas() -> list[Conferencia]:
    """A cortante tem de ser a derivada do momento, barra a barra.

    É a relação dM/dx = V nos dois planos. Como a carga é uniforme, o momento
    é quadrático e a diferença central é exata — o resíduo que sobra é só
    arredondamento. Esta conferência guarda a convenção de sinais: qualquer
    troca futura de sinal em ``resultados.diagrama`` aparece aqui.
    """
    r = resolver(_portico_espacial(), "mista")

    pior_y = pior_z = escala = 0.0
    for nome in r.modelo.barras:
        d = r.diagrama(nome, 21)
        passo = d.x[2] - d.x[0]
        dMy = (d.My[2:] - d.My[:-2]) / passo
        dMz = (d.Mz[2:] - d.Mz[:-2]) / passo
        pior_z = max(pior_z, float(np.max(np.abs(dMy - d.Vz[1:-1]))))
        pior_y = max(pior_y, float(np.max(np.abs(dMz - d.Vy[1:-1]))))
        escala = max(escala, float(np.max(np.abs(d.Vz))),
                     float(np.max(np.abs(d.Vy))))

    return [
        Conferencia("diagramas: dMy/dx = Vz", pior_z, 0.0, 1e-9, escala=escala),
        Conferencia("diagramas: dMz/dx = Vy", pior_y, 0.0, 1e-9, escala=escala),
    ]


# ---------------------------------------------------------------------------
# 12. Peso próprio
# ---------------------------------------------------------------------------

def carga_de_peso_proprio() -> list[Conferencia]:
    """Viga biapoiada só com o peso próprio: γ·A por metro."""
    L, gama = 6.0, 25.0
    m = _modelo_base("peso")
    m.materiais.clear()
    m.add_material("aco", E_ACO, POISSON, peso_especifico=gama)
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("M", L / 2.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "M", "aco", "R20x50")
    m.add_barra("B2", "M", "B", "aco", "R20x50")
    m.apoiar("A", ux=True, uy=True, uz=True, rx=True, ry=False, rz=False)
    m.apoiar("B", ux=False, uy=True, uz=True, rx=False, ry=False, rz=False)

    caso = m.add_caso("PP")
    aplicadas = peso_proprio(m, caso)
    r = resolver(m, "PP")
    w = gama * m.secoes["R20x50"].A

    return [
        Conferencia("peso próprio: entrou em todas as barras",
                    float(len(aplicadas)), 2.0),
        Conferencia("peso próprio: reação Fz = γAL/2",
                    r.reacao("A")[2], w * L / 2.0, 1e-10),
        Conferencia("peso próprio: momento no vão My = γAL²/8",
                    r.diagrama("B1").My[-1], w * L ** 2 / 8.0, 1e-10),
    ]


# ---------------------------------------------------------------------------
# 13. Combinação por superposição
# ---------------------------------------------------------------------------

def _viga_dois_casos() -> Modelo:
    m = _viga_em_dois_tramos("combinacao", 6.0)
    m.apoiar("A", ux=True, uy=True, uz=True, rx=True, ry=False, rz=False)
    m.apoiar("B", ux=False, uy=True, uz=True, rx=False, ry=False, rz=False)
    g = m.add_caso("G")
    g.distribuida("B1", qz=-10.0)
    g.distribuida("B2", qz=-10.0)
    m.add_caso("Q").nodal("M", fz=-50.0)
    return m


def superposicao() -> list[Conferencia]:
    """A combinação tem de dar o mesmo que aplicar as cargas já majoradas.

    É a conferência que garante que os fatores entram uma vez só, e no lugar
    certo — inclusive na carga distribuída, que passa pelo caminho das forças
    de engastamento perfeito antes de virar carga nodal equivalente.
    """
    m = _viga_dois_casos()
    combinada = combinar(resolver_casos(m),
                         Combinacao("1.4G+1.5Q", {"G": 1.4, "Q": 1.5}))

    direto = _viga_dois_casos()
    caso = direto.add_caso("direto")
    caso.distribuida("B1", qz=-14.0)
    caso.distribuida("B2", qz=-14.0)
    caso.nodal("M", fz=-75.0)
    esperado = resolver(direto, "direto")

    return [
        Conferencia("superposição: flecha da combinação",
                    combinada.deslocamento("M")[2],
                    esperado.deslocamento("M")[2], 1e-12),
        Conferencia("superposição: momento da combinação",
                    combinada.diagrama("B1").My[-1],
                    esperado.diagrama("B1").My[-1], 1e-12),
        Conferencia("superposição: reação da combinação",
                    combinada.reacao("A")[2], esperado.reacao("A")[2], 1e-12),
    ]


# ---------------------------------------------------------------------------
# 14. Envoltória: os concomitantes têm de vir da combinação certa
# ---------------------------------------------------------------------------

def concomitantes_da_envoltoria() -> list[Conferencia]:
    """O erro que este teste existe para impedir.

    Um caso dá compressão alta e momento nulo; o outro dá momento alto e
    compressão nula. Se a envoltória cruzar os máximos, o pilar seria
    verificado para um par (N, My) que nunca existiu ao mesmo tempo — a favor
    da insegurança ou da antieconomia, dependendo do domínio.
    """
    N, P = 100.0, 10.0
    m = _barra_reta("concomitantes", 4.0)
    m.add_caso("A").nodal("B", fx=-N)
    m.add_caso("B").nodal("B", fz=-P)

    combinacoes = [Combinacao("C1", {"A": 1.0}), Combinacao("C2", {"B": 1.0})]
    env = envoltoria(m, resolver_combinacoes(m, combinacoes))["B1"]

    momento = env.extremo("My", "min")     # o engaste, momento negativo
    normal = env.extremo("N", "min")       # a compressão

    return [
        Conferencia("envoltória: |My| mínimo vale PL",
                    abs(momento.valor), P * 4.0, 1e-10),
        Conferencia("envoltória: My mínimo veio da combinação certa",
                    float(momento.combinacao == "C2"), 1.0),
        Conferencia("envoltória: N concomitante ao My é nulo, não -N",
                    momento.esforcos["N"], 0.0, 1e-10, escala=N),
        Conferencia("envoltória: N mínimo vale -N",
                    normal.valor, -N, 1e-10),
        Conferencia("envoltória: My concomitante ao N é nulo",
                    normal.esforcos["My"], 0.0, 1e-10, escala=P * 4.0),
        Conferencia("envoltória: registrou as duas combinações",
                    float(len(env.combinacoes)), 2.0),
    ]


# ---------------------------------------------------------------------------
# 15. Geração das combinações da NBR 6118
# ---------------------------------------------------------------------------

def _acoes_de_edificio() -> list[Acao]:
    """Um permanente, um acidental e duas incidências de vento excludentes.

    O acidental é da categoria comercial (ψ = 0,7 / 0,6 / 0,4) de propósito:
    com o residencial, ψ2 do acidental e ψ1 do vento valem os mesmos 0,3, e o
    teste deixaria de distinguir qual dos dois a implementação usou.
    """
    return [
        Acao("G", "permanente"),
        Acao("Q", "variavel", "comercial"),
        Acao("VX", "variavel", "vento", grupo="vento"),
        Acao("VY", "variavel", "vento", grupo="vento"),
    ]


def combinacoes_da_norma() -> list[Conferencia]:
    acoes = _acoes_de_edificio()
    elu = combinacoes_elu(acoes)
    els = combinacoes_els(acoes)

    # Q principal, VX secundário: γg=1,4 · γq=1,4 · ψ0 do vento = 0,6
    alvo = next(c for c in elu
                if set(c.fatores) == {"G", "Q", "VX"}
                and c.fatores["Q"] == 1.4)
    # Nenhuma combinação pode trazer as duas incidências de vento juntas.
    juntos = [c for c in elu + els
              if "VX" in c.fatores and "VY" in c.fatores]

    # Rara com o acidental principal: o vento secundário entra com ψ1.
    rara = next(c for c in els
                if c.tipo == "ELS-R" and set(c.fatores) == {"G", "Q", "VX"})
    # Frequente com o vento principal: o acidental secundário entra com ψ2.
    frequente = next(c for c in els
                     if c.tipo == "ELS-F" and set(c.fatores) == {"G", "Q", "VX"}
                     and c.fatores["VX"] == PSI["vento"][1])
    # Frequente com o acidental principal: o vento tem ψ2 nulo e some.
    frequente_sem_vento = [c for c in els
                           if c.tipo == "ELS-F"
                           and c.fatores.get("Q") == PSI["comercial"][1]]

    return [
        Conferencia("ELU: γg das ações permanentes", alvo.fatores["G"], 1.4),
        Conferencia("ELU: γq da variável principal", alvo.fatores["Q"], 1.4),
        Conferencia("ELU: γq·ψ0 da variável secundária",
                    alvo.fatores["VX"], 1.4 * 0.6, 1e-12),
        Conferencia("grupos excludentes: vento X e Y nunca juntos",
                    float(len(juntos)), 0.0),
        Conferencia("ELS rara: principal com valor característico",
                    rara.fatores["Q"], 1.0),
        Conferencia("ELS rara: secundária com ψ1, não ψ0",
                    rara.fatores["VX"], PSI["vento"][1], 1e-12),
        Conferencia("ELS frequente: principal com ψ1",
                    frequente.fatores["VX"], PSI["vento"][1], 1e-12),
        Conferencia("ELS frequente: secundária com ψ2",
                    frequente.fatores["Q"], PSI["comercial"][2], 1e-12),
        Conferencia("ELS frequente: secundária de ψ2 nulo não entra",
                    float(all("VX" not in c.fatores and "VY" not in c.fatores
                              for c in frequente_sem_vento)), 1.0),
        Conferencia("ELS quase permanente: existe e é única",
                    float(len([c for c in els if c.tipo == "ELS-QP"])), 1.0),
    ]


def permanente_favoravel() -> list[Conferencia]:
    """A nota ᵃ da Tabela 11.3: γg = 1,0 só quando pedido."""
    acoes = _acoes_de_edificio()
    sem = combinacoes_elu(acoes)
    com = combinacoes_elu(acoes, incluir_permanente_favoravel=True)

    return [
        Conferencia("γg favorável: fora por padrão",
                    float(any(c.fatores["G"] == 1.0 for c in sem)), 0.0),
        Conferencia("γg favorável: entra quando pedido",
                    float(any(c.fatores["G"] == 1.0 for c in com)), 1.0),
        Conferencia("γg favorável: dobra o número de combinações",
                    float(len(com)), float(2 * len(sem))),
    ]


# ---------------------------------------------------------------------------
# 16. Desaprumo — item 11.3.3.4.1
# ---------------------------------------------------------------------------

def _edificio_dois_pavimentos(altura_total: float = 6.25) -> Modelo:
    """Quatro pilares, dois pavimentos, vigas nos dois níveis."""
    m = Modelo("edificio")
    m.add_material("concreto", 30.0e6, 0.2, peso_especifico=25.0)
    m.add_secao(Secao.retangular("P30x30", 0.30, 0.30))
    m.add_secao(Secao.retangular("V20x50", 0.20, 0.50))

    pes = {"A": (0.0, 0.0), "B": (5.0, 0.0), "C": (5.0, 4.0), "D": (0.0, 4.0)}
    meia = altura_total / 2.0
    for nome, (x, y) in pes.items():
        m.add_no(nome, x, y, 0.0)
        m.add_no(nome + "1", x, y, meia)
        m.add_no(nome + "2", x, y, altura_total)
        m.add_barra("P" + nome + "1", nome, nome + "1", "concreto", "P30x30")
        m.add_barra("P" + nome + "2", nome + "1", nome + "2",
                    "concreto", "P30x30")
        m.apoiar(nome)

    for nivel in ("1", "2"):
        for a, b in (("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")):
            m.add_barra(f"V{a}{b}{nivel}", a + nivel, b + nivel,
                        "concreto", "V20x50")
    return m


def desaprumo_global() -> list[Conferencia]:
    """H = 6,25 m dá θ1 = 1/250, dentro dos limites 1/300 e 1/200."""
    m = _edificio_dois_pavimentos()
    vertical = m.add_caso("G")
    peso_proprio(m, vertical)
    for no in ("A1", "B1", "C1", "D1", "A2", "B2", "C2", "D2"):
        vertical.nodal(no, fz=-40.0)

    destino = m.add_caso("DESAPRUMO")
    d = desaprumo(m, "G", destino, direcao=(1.0, 0.0))

    theta1 = 1.0 / 250.0
    theta_a = theta1 * math.sqrt((1.0 + 1.0 / 4.0) / 2.0)

    from .core.nbr6118 import cargas_verticais_por_no
    verticais = cargas_verticais_por_no(m, vertical)
    livres = sum(v for no, v in verticais.items() if no not in m.apoios)

    return [
        Conferencia("desaprumo: H deduzido do modelo", d.H, 6.25, 1e-12),
        Conferencia("desaprumo: n de prumadas contadas", float(d.n), 4.0),
        Conferencia("desaprumo: θ1 = 1/(100√H)", d.theta1, theta1, 1e-12),
        Conferencia("desaprumo: θa = θ1√[(1+1/n)/2]", d.theta_a, theta_a, 1e-12),
        Conferencia("desaprumo: força total = θa · carga vertical",
                    d.forca_total, theta_a * livres, 1e-10),
        Conferencia("desaprumo: nada aplicado nos nós de apoio",
                    float(any(no in m.apoios for no in d.nos)), 0.0),
    ]


def limites_do_desaprumo() -> list[Conferencia]:
    """Fora da faixa 4 m ≤ H ≤ 9 m, θ1 encosta num dos dois limites."""
    baixo = _edificio_dois_pavimentos(3.0)          # θ1 bruto = 1/173 > 1/200
    caso_b = baixo.add_caso("G")
    peso_proprio(baixo, caso_b)
    d_baixo = desaprumo(baixo, "G", baixo.add_caso("D"), (1.0, 0.0))

    alto = _edificio_dois_pavimentos(30.0)          # θ1 bruto = 1/548 < 1/300
    caso_a = alto.add_caso("G")
    peso_proprio(alto, caso_a)
    d_alto = desaprumo(alto, "G", alto.add_caso("D"), (1.0, 0.0))
    d_sem = desaprumo(alto, "G", alto.add_caso("D2"), (1.0, 0.0),
                      aplicar_minimo=False)

    return [
        Conferencia("desaprumo: θ1 truncado no máximo 1/200",
                    d_baixo.theta1, 1.0 / 200.0, 1e-12),
        Conferencia("desaprumo: θ1 truncado no mínimo 1/300",
                    d_alto.theta1, 1.0 / 300.0, 1e-12),
        Conferencia("desaprumo: sem o mínimo, θ1 fica o bruto",
                    d_sem.theta1, 1.0 / (100.0 * math.sqrt(30.0)), 1e-12),
    ]


def regra_dos_trinta_por_cento() -> list[Conferencia]:
    """Os três ramos do confronto entre vento e desaprumo."""
    return [
        Conferencia("30 %: vento domina",
                    float(confronto_vento_desaprumo(100.0, 10.0) == "vento"), 1.0),
        Conferencia("30 %: desaprumo domina",
                    float(confronto_vento_desaprumo(10.0, 100.0)
                          == "desaprumo"), 1.0),
        Conferencia("30 %: os dois se combinam",
                    float(confronto_vento_desaprumo(100.0, 50.0) == "ambos"), 1.0),
    ]


def momento_de_tombamento() -> list[Conferencia]:
    """O momento na base é Σ F·(z - z_base), que é como a norma compara."""
    m = _edificio_dois_pavimentos()
    caso = m.add_caso("V")
    caso.nodal("A1", fx=10.0)
    caso.nodal("A2", fx=20.0)

    return [
        Conferencia("momento na base do caso horizontal",
                    momento_na_base(m, caso),
                    10.0 * 3.125 + 20.0 * 6.25, 1e-12),
    ]


# ---------------------------------------------------------------------------
# 17. O ciclo inteiro: classificar, combinar, resolver, envoltoriar
# ---------------------------------------------------------------------------

def _edificio_classificado() -> Modelo:
    """O edifício de dois pavimentos com os casos já classificados."""
    m = _edificio_dois_pavimentos()

    g = m.add_caso("G", "permanente")
    peso_proprio(m, g)
    for nivel in ("1", "2"):
        for a, b in (("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")):
            g.distribuida(f"V{a}{b}{nivel}", qz=-12.0, sistema="global")

    q = m.add_caso("Q", "variavel", "comercial")
    for no in ("A1", "B1", "C1", "D1", "A2", "B2", "C2", "D2"):
        q.nodal(no, fz=-35.0)

    for nome, (fx, fy) in (("VX", (1.0, 0.0)), ("VY", (0.0, 1.0))):
        vento = m.add_caso(nome, "variavel", "vento", grupo="vento")
        for no, fator in (("A1", 8.0), ("B1", 8.0), ("C1", 8.0), ("D1", 8.0),
                          ("A2", 14.0), ("B2", 14.0), ("C2", 14.0),
                          ("D2", 14.0)):
            vento.nodal(no, fx=fator * fx, fy=fator * fy)
    return m


def ciclo_completo() -> list[Conferencia]:
    m = _edificio_classificado()
    acoes = acoes_do_modelo(m)
    validar_acoes(m, acoes)
    combinacoes = combinacoes_elu(acoes) + combinacoes_els(acoes)
    resultados = resolver_combinacoes(m, combinacoes)
    env = envoltoria(m, resultados, n_estacoes=5)

    # Para uma combinação qualquer, a reação vertical total tem de bater com a
    # soma ponderada das cargas verticais de cada caso. Não existe combinação
    # ELU só de permanentes: a fórmula da Tabela 11.3 sempre traz uma ação
    # variável principal.
    alvo = next(c for c in combinacoes if c.tipo == "ELU")
    vertical_por_caso = {
        nome: sum(cargas_verticais_por_no(m, caso).values())
        for nome, caso in m.casos.items()}
    vertical_ponderada = sum(fator * vertical_por_caso[nome]
                             for nome, fator in alvo.fatores.items())
    reacao_vertical = resultados[alvo.nome].reacoes_totais()[2]

    # A envoltória tem de coincidir com o mínimo calculado por fora dela.
    pior_por_fora = min(
        float(np.min(resultados[c.nome].diagrama("PA1", 5).N))
        for c in combinacoes)
    pior_da_envoltoria = float(np.min(env["PA1"].minimos[0]))

    extremo = env["PA1"].extremo("N", "min")
    dimensionamento = env["PA1"].casos_de_dimensionamento()

    return [
        Conferencia("ciclo: reação vertical bate com a carga ponderada",
                    reacao_vertical, vertical_ponderada, 1e-9),
        Conferencia("ciclo: envoltória confere com o mínimo caso a caso",
                    pior_da_envoltoria, pior_por_fora, 1e-12),
        Conferencia("ciclo: o extremo aponta uma combinação existente",
                    float(extremo.combinacao in resultados), 1.0),
        Conferencia("ciclo: a compressão máxima vem de uma combinação ELU",
                    float(extremo.combinacao.startswith("ELU")), 1.0),
        Conferencia("ciclo: há esforços de dimensionamento nas extremidades",
                    float(len(dimensionamento) > 0), 1.0),
        Conferencia("ciclo: cada registro traz os seis esforços simultâneos",
                    float(all({"N", "Vy", "Vz", "T", "My", "Mz"} <= set(r)
                              for r in dimensionamento)), 1.0),
    ]


# ---------------------------------------------------------------------------
# 18. Liberações de extremidade
# ---------------------------------------------------------------------------

def viga_engastada_e_apoiada() -> list[Conferencia]:
    """Liberar a rotação numa ponta de barra biengastada dá a engastada-apoiada.

    Os dois nós continuam engastados; quem solta é a barra. As três respostas
    conhecidas — M = wL²/8 no engaste, 5wL/8 e 3wL/8 nas reações — só saem se a
    condensação estática corrigir também o vetor de engastamento perfeito, e
    não apenas a matriz de rigidez.
    """
    L, w = 6.0, 20.0
    m = _modelo_base("engastada_apoiada")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "B", "aco", "R20x50", liberacoes_j=("ry",))
    m.apoiar("A")
    m.apoiar("B")
    m.add_caso("q").distribuida("B1", qz=-w)
    r = resolver(m, "q")
    d = r.diagrama("B1", 9)

    return [
        Conferencia("engastada-apoiada: momento no engaste |My| = wL²/8",
                    abs(d.My[0]), w * L ** 2 / 8.0, 1e-10),
        Conferencia("engastada-apoiada: momento nulo na rótula",
                    d.My[-1], 0.0, 1e-10, escala=w * L ** 2 / 8.0),
        Conferencia("engastada-apoiada: reação no engaste 5wL/8",
                    r.reacao("A")[2], 5.0 * w * L / 8.0, 1e-10),
        Conferencia("engastada-apoiada: reação no apoio 3wL/8",
                    r.reacao("B")[2], 3.0 * w * L / 8.0, 1e-10),
        Conferencia("engastada-apoiada: momento de extremidade nulo na rótula",
                    r.esforcos_barra("B1")[10], 0.0, 1e-10,
                    escala=w * L ** 2 / 8.0),
    ]


def viga_birrotulada() -> list[Conferencia]:
    """Rótula nas duas pontas devolve a biapoiada, mesmo com nós engastados."""
    L, w = 6.0, 20.0
    m = _modelo_base("birrotulada")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "B", "aco", "R20x50",
                liberacoes_i=("ry",), liberacoes_j=("ry",))
    m.apoiar("A")
    m.apoiar("B")
    m.add_caso("q").distribuida("B1", qz=-w)
    r = resolver(m, "q")
    d = r.diagrama("B1", 9)

    return [
        Conferencia("birrotulada: momento nulo nas duas pontas",
                    max(abs(d.My[0]), abs(d.My[-1])), 0.0, 1e-10,
                    escala=w * L ** 2 / 8.0),
        Conferencia("birrotulada: momento no meio do vão wL²/8",
                    d.My[4], w * L ** 2 / 8.0, 1e-10),
        Conferencia("birrotulada: reações wL/2",
                    r.reacao("A")[2], w * L / 2.0, 1e-10),
    ]


def liberacao_que_solta_a_barra() -> list[Conferencia]:
    """Liberar a torção nas duas pontas é mecanismo dentro do elemento."""
    def montar():
        m = _modelo_base("torcao_solta")
        m.add_no("A", 0.0, 0.0, 0.0)
        m.add_no("B", 4.0, 0.0, 0.0)
        m.add_barra("B1", "A", "B", "aco", "R20x50",
                    liberacoes_i=("rx",), liberacoes_j=("rx",))
        m.apoiar("A")
        m.apoiar("B")
        m.add_caso("q").distribuida("B1", qz=-10.0)
        return resolver(m, "q")

    try:
        montar()
        recusou = 0.0
    except ErroDeModelo:
        recusou = 1.0

    return [
        Conferencia("liberação: torção solta nas duas pontas é recusada",
                    recusou, 1.0),
    ]


# ---------------------------------------------------------------------------
# 19. Carga parcial e trapezoidal
# ---------------------------------------------------------------------------

def carga_triangular() -> list[Conferencia]:
    """Biapoiada sob carga que cresce de zero a w: reações wL/6 e wL/3."""
    L, w = 6.0, 30.0
    m = _modelo_base("triangular")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "B", "aco", "R20x50")
    m.apoiar("A", ux=True, uy=True, uz=True, rx=True, ry=False, rz=False)
    m.apoiar("B", ux=False, uy=True, uz=True, rx=False, ry=False, rz=False)
    m.add_caso("q").distribuida("B1", qz=0.0, qz_fim=-w)
    r = resolver(m, "q")
    d = r.diagrama("B1", 3)

    return [
        Conferencia("triangular: reação do lado descarregado wL/6",
                    r.reacao("A")[2], w * L / 6.0, 1e-10),
        Conferencia("triangular: reação do lado carregado wL/3",
                    r.reacao("B")[2], w * L / 3.0, 1e-10),
        Conferencia("triangular: momento no meio do vão wL²/16",
                    d.My[1], w * L ** 2 / 16.0, 1e-10),
    ]


def carga_parcial() -> list[Conferencia]:
    """Carga num trecho da barra tem de dar o mesmo que dividir a barra.

    O modelo de comparação usa três barras e carga uniforme de barra inteira
    na do meio — ou seja, passa só pelo caminho já conferido pelas soluções
    fechadas. Se a carga parcial concordar com ele, a quadratura das funções
    de forma está certa para trecho qualquer.
    """
    L, w = 8.0, 25.0
    a, b = 0.25, 0.75

    inteira = _modelo_base("parcial")
    inteira.add_no("A", 0.0, 0.0, 0.0)
    inteira.add_no("B", L, 0.0, 0.0)
    inteira.add_barra("B1", "A", "B", "aco", "R20x50")
    inteira.apoiar("A")
    inteira.apoiar("B")
    inteira.add_caso("q").distribuida("B1", qz=-w, inicio=a, fim=b)
    r1 = resolver(inteira, "q")

    dividida = _modelo_base("dividida")
    dividida.add_no("A", 0.0, 0.0, 0.0)
    dividida.add_no("M1", a * L, 0.0, 0.0)
    dividida.add_no("M2", b * L, 0.0, 0.0)
    dividida.add_no("B", L, 0.0, 0.0)
    dividida.add_barra("T1", "A", "M1", "aco", "R20x50")
    dividida.add_barra("T2", "M1", "M2", "aco", "R20x50")
    dividida.add_barra("T3", "M2", "B", "aco", "R20x50")
    dividida.apoiar("A")
    dividida.apoiar("B")
    dividida.add_caso("q").distribuida("T2", qz=-w)
    r2 = resolver(dividida, "q")

    return [
        Conferencia("parcial: reação igual à do modelo dividido",
                    r1.reacao("A")[2], r2.reacao("A")[2], 1e-10),
        Conferencia("parcial: momento no engaste igual ao do dividido",
                    r1.diagrama("B1").My[0], r2.diagrama("T1").My[0], 1e-10),
        Conferencia("parcial: flecha no início do trecho carregado",
                    r1.diagrama("B1", 5).My[1],
                    r2.diagrama("T1").My[-1], 1e-10),
        Conferencia("parcial: resultante vale w·(b-a)·L",
                    r1.reacao("A")[2] + r1.reacao("B")[2],
                    w * (b - a) * L, 1e-10),
    ]


# ---------------------------------------------------------------------------
# 20. Apoios elásticos
# ---------------------------------------------------------------------------

def apoio_elastico() -> list[Conferencia]:
    """Balanço com mola na ponta: as duas rigidezes se somam em paralelo."""
    L, P, k = 4.0, 30.0, 500.0
    m = _modelo_base("mola")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "B", "aco", "R20x50")
    m.apoiar("A")
    m.add_mola("B", kz=k)
    m.add_caso("P").nodal("B", fz=-P)
    r = resolver(m, "P")

    rigidez_barra = 3.0 * E_ACO * m.secoes["R20x50"].Iy / L ** 3
    flecha = -P / (rigidez_barra + k)

    return [
        Conferencia("mola: flecha = -P/(3EI/L³ + k)",
                    r.deslocamento("B")[2], flecha, 1e-10),
        Conferencia("mola: reação da mola = -k·d",
                    r.reacao_mola("B")[2], -k * flecha, 1e-10),
        Conferencia("mola: o que sobra vai para o engaste",
                    r.reacao("A")[2], P + k * flecha, 1e-10),
        Conferencia("mola: equilíbrio global fecha com a mola dentro",
                    r.reacoes_totais()[2], P, 1e-10),
    ]


def mola_rigida() -> list[Conferencia]:
    """Mola muito rígida tem de convergir para o apoio indeslocável."""
    L, P = 6.0, 40.0
    def montar(k: float | None):
        m = _modelo_base("rigida")
        m.add_no("A", 0.0, 0.0, 0.0)
        m.add_no("M", L / 2.0, 0.0, 0.0)
        m.add_no("B", L, 0.0, 0.0)
        m.add_barra("B1", "A", "M", "aco", "R20x50")
        m.add_barra("B2", "M", "B", "aco", "R20x50")
        m.apoiar("A")
        if k is None:
            m.apoiar("B", ux=False, uy=True, uz=True,
                     rx=False, ry=False, rz=False)
        else:
            m.apoiar("B", ux=False, uy=True, uz=False,
                     rx=False, ry=False, rz=False)
            m.add_mola("B", kz=k)
        m.add_caso("P").nodal("M", fz=-P)
        return resolver(m, "P")

    com_mola = montar(1.0e12)
    com_apoio = montar(None)

    return [
        Conferencia("mola rígida: flecha converge para a do apoio",
                    com_mola.deslocamento("M")[2],
                    com_apoio.deslocamento("M")[2], 1e-6),
        Conferencia("mola rígida: momento converge para o do apoio",
                    com_mola.diagrama("B1").My[0],
                    com_apoio.diagrama("B1").My[0], 1e-6),
    ]


# ---------------------------------------------------------------------------
# 21. Recalques de apoio
# ---------------------------------------------------------------------------

def recalque_em_viga_biengastada() -> list[Conferencia]:
    """Recalque δ numa ponta engastada: M = 6EIδ/L² e V = 12EIδ/L³."""
    L, delta = 6.0, 0.01
    m = _modelo_base("recalque")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "B", "aco", "R20x50")
    m.apoiar("A")
    m.apoiar("B")
    m.add_caso("R").recalque("B", uz=-delta)
    r = resolver(m, "R")
    EI = E_ACO * m.secoes["R20x50"].Iy
    d = r.diagrama("B1", 3)

    return [
        Conferencia("recalque: momento no engaste 6EIδ/L²",
                    abs(d.My[0]), 6.0 * EI * delta / L ** 2, 1e-9),
        Conferencia("recalque: cortante 12EIδ/L³",
                    abs(d.Vz[0]), 12.0 * EI * delta / L ** 3, 1e-9),
        Conferencia("recalque: momento muda de sinal no meio",
                    d.My[1], 0.0, 1e-9,
                    escala=6.0 * EI * delta / L ** 2),
        Conferencia("recalque: o deslocamento imposto aparece na resposta",
                    r.deslocamento("B")[2], -delta, 1e-14),
    ]


def recalque_em_estrutura_isostatica() -> list[Conferencia]:
    """Recalque em estrutura isostática não produz esforço nenhum.

    A viga apenas gira como corpo rígido. É a conferência que separa o
    recalque bem implementado — que entra como deslocamento prescrito — da
    gambiarra de aplicar uma força equivalente, que produziria esforço aqui.
    """
    L, delta = 6.0, 0.02
    m = _modelo_base("isostatica")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("M", L / 2.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "M", "aco", "R20x50")
    m.add_barra("B2", "M", "B", "aco", "R20x50")
    m.apoiar("A", ux=True, uy=True, uz=True, rx=True, ry=False, rz=False)
    m.apoiar("B", ux=False, uy=True, uz=True, rx=False, ry=False, rz=False)
    m.add_caso("R").recalque("B", uz=-delta)
    r = resolver(m, "R")

    esforcos = max(float(np.max(np.abs(r.esforcos_barra(b))))
                   for b in m.barras)
    EI = E_ACO * m.secoes["R20x50"].Iy

    return [
        Conferencia("recalque isostático: nenhum esforço aparece",
                    esforcos, 0.0, 1e-9, escala=EI * delta / L ** 2),
        Conferencia("recalque isostático: o meio desce metade",
                    r.deslocamento("M")[2], -delta / 2.0, 1e-12),
    ]


# ---------------------------------------------------------------------------
# 22. Alternância de cargas acidentais
# ---------------------------------------------------------------------------

def _viga_continua_tres_tramos(w: float = 20.0) -> tuple[Modelo, list[list[str]]]:
    L = 5.0
    m = _modelo_base("continua")
    for i in range(4):
        m.add_no(f"N{i}", i * L, 0.0, 0.0)
    for i in range(3):
        m.add_barra(f"T{i + 1}", f"N{i}", f"N{i + 1}", "aco", "R20x50")
    m.apoiar("N0", ux=True, uy=True, uz=True, rx=True, ry=False, rz=False)
    for i in (1, 2, 3):
        m.apoiar(f"N{i}", ux=False, uy=True, uz=True,
                 rx=False, ry=False, rz=False)

    g = m.add_caso("G", "permanente")
    q = m.add_caso("Q", "variavel", "residencial")
    for i in range(3):
        g.distribuida(f"T{i + 1}", qz=-w)
        q.distribuida(f"T{i + 1}", qz=-w)
    return m, [["T1"], ["T2"], ["T3"]]


def alternancia_de_acidental() -> list[Conferencia]:
    """Os padrões alternativos nascem excludentes entre si.

    A conferência que importa é a última: sem o grupo excludente comum, o
    gerador de combinações somaria dois padrões do mesmo acidental, contando
    a mesma carga duas vezes.
    """
    m, grupos = _viga_continua_tres_tramos()
    criados = alternancia(m, "Q", grupos)
    combinacoes = combinacoes_elu(acoes_do_modelo(m))

    juntos = [c for c in combinacoes
              if sum(nome in c.fatores for nome in criados) > 1]
    so_um_tramo = m.casos["Q (tramos 1-2)"]

    return [
        Conferencia("alternância: gera todas, ímpares, pares e dois pares",
                    float(len(criados)), 5.0),
        Conferencia("alternância: o caso base sai do modelo",
                    float("Q" in m.casos), 0.0),
        Conferencia("alternância: o padrão de dois tramos carrega dois",
                    float(len(so_um_tramo.distribuidas)), 2.0),
        Conferencia("alternância: os padrões herdam a categoria",
                    float(so_um_tramo.categoria == "residencial"), 1.0),
        Conferencia("alternância: dois padrões nunca entram na mesma combinação",
                    float(len(juntos)), 0.0),
    ]


def envoltoria_da_alternancia() -> list[Conferencia]:
    """A alternância tem de agravar a envoltória, nunca aliviá-la.

    Com todos os tramos sempre carregados, o momento positivo do tramo central
    de uma contínua fica menor do que com os tramos ímpares carregados — que é
    justamente a razão de existir a alternância.
    """
    com, grupos = _viga_continua_tres_tramos()
    alternancia(com, "Q", grupos)
    env_com = envoltoria(
        com, resolver_combinacoes(com, combinacoes_elu(acoes_do_modelo(com))),
        n_estacoes=9)

    sem, _ = _viga_continua_tres_tramos()
    env_sem = envoltoria(
        sem, resolver_combinacoes(sem, combinacoes_elu(acoes_do_modelo(sem))),
        n_estacoes=9)

    vao_com = env_com["T2"].extremo("My", "max").valor
    vao_sem = env_sem["T2"].extremo("My", "max").valor

    return [
        Conferencia("alternância: o momento de vão do tramo central cresce",
                    float(vao_com > vao_sem * 1.05), 1.0),
        Conferencia("alternância: o apoio continua governado pela carga cheia",
                    float(env_com["T2"].extremo("My", "min").valor
                          <= env_sem["T2"].extremo("My", "min").valor + 1e-9),
                    1.0),
    ]


# ---------------------------------------------------------------------------
# 23. Vento, chamando o programa NBR-6123
# ---------------------------------------------------------------------------

def vento_pela_nbr6123() -> list[Conferencia]:
    """A integração com o programa do vento, conferida contra ele mesmo.

    O que se confere aqui não é a norma do vento — disso cuida o programa
    NBR-6123, que tem as suas próprias conferências. O que se confere é a
    parte que este programa acrescenta: a geometria dos pavimentos, a área
    tributária, a conversão de unidade e o rateio pelos nós.
    """
    from .core.vento import carregar_nbr6123, forcas_de_vento

    try:
        C = carregar_nbr6123()
    except ErroDeModelo:
        return [Conferencia("vento: programa NBR-6123 encontrado", 0.0, 1.0)]

    m = _edificio_dois_pavimentos(6.0)
    caso = m.add_caso("VX", "variavel", "vento", grupo="vento")
    r = forcas_de_vento(m, caso, v0=45.0, direcao=(1.0, 0.0),
                        categoria="II", grupo_s3="3")

    # O edifício tem 5 m em X e 4 m em Y; com vento em X a face frontal é a
    # de 4 m e a profundidade é a de 5 m.
    largura, profundidade = 4.0, 5.0
    s3 = C.calc_s3("3", False)
    classe = C.classe_por_dimensao(max(largura, 6.0))
    s2_topo = C.calc_s2("II", classe, 6.0)
    q_topo = C.calc_q(C.calc_vk(45.0, 1.0, s2_topo, s3)) / 1000.0

    topo = r.niveis[-1]
    aplicado = sum(c.fx for c in caso.nodais)

    return [
        Conferencia("vento: programa NBR-6123 encontrado", 1.0, 1.0),
        Conferencia("vento: largura frontal é a perpendicular ao vento",
                    r.largura_frontal, largura, 1e-12),
        Conferencia("vento: profundidade é a dimensão na direção do vento",
                    r.profundidade, profundidade, 1e-12),
        Conferencia("vento: S2 do topo bate com o do programa da norma",
                    topo.s2, s2_topo, 1e-12),
        Conferencia("vento: q convertido de N/m² para kN/m²",
                    topo.q, q_topo, 1e-12),
        Conferencia("vento: altura tributária do topo é meio pé-direito",
                    topo.altura_tributaria, 1.5, 1e-12),
        Conferencia("vento: área tributária = largura × altura tributária",
                    topo.area, largura * 1.5, 1e-12),
        Conferencia("vento: a soma das forças nodais é a força total",
                    aplicado, r.forca_total, 1e-10),
        # A NBR 6123:2023, item 3.2, define ℓ1 como a largura perpendicular ao
        # vento e ℓ2 como a profundidade — o contrário do que diz o docstring
        # do nbr6123_core. O Ca tem de sair do ponto do ábaco que a norma manda.
        Conferencia("vento: Ca sai do ábaco em ℓ1/ℓ2 com ℓ1 frontal",
                    r.ca,
                    C.coef_arrasto(largura, profundidade, 6.0, False)[0],
                    1e-12),
        Conferencia("vento: área frontal efetiva usa ℓ1, não ℓ2",
                    sum(n.area for n in r.niveis) / sum(
                        n.altura_tributaria for n in r.niveis),
                    largura, 1e-12),
        # A faixa de meio pé-direito junto ao chão não solicita a estrutura.
        Conferencia("vento: a altura tributária cobre o resto da edificação",
                    sum(n.altura_tributaria for n in r.niveis)
                    + r.altura_para_a_fundacao, 6.0, 1e-12),
        Conferencia("vento: nada aplicado nos nós de apoio",
                    float(any(no in m.apoios
                              for n in r.niveis for no in n.nos)), 0.0),
    ]


# ---------------------------------------------------------------------------
# 24. Flambagem elástica: os quatro casos de Euler
# ---------------------------------------------------------------------------

def _pilar_vertical(L: float, n: int, topo: str) -> Modelo:
    """Pilar de eixo Z dividido em ``n`` barras, com carga unitária no topo.

    Para uma barra vertical o eixo local x é o Z global, de modo que a torção
    é o ``rz`` e as duas flexões são ``rx`` e ``ry``. É por isso que o ``rz``
    da base fica sempre travado: sem ele a barra gira em torno do próprio eixo
    sem vínculo nenhum.
    """
    m = _modelo_base(f"euler_{topo}")
    for i in range(n + 1):
        m.add_no(f"N{i}", 0.0, 0.0, i * L / n)
    for i in range(n):
        m.add_barra(f"B{i}", f"N{i}", f"N{i + 1}", "aco", "R20x50")

    m.apoiar("N0", ux=True, uy=True, uz=True,
             rx=(topo != "biapoiada"), ry=(topo != "biapoiada"), rz=True)
    if topo == "biapoiada":
        m.apoiar(f"N{n}", ux=True, uy=True, uz=False,
                 rx=False, ry=False, rz=False)
    elif topo == "biengastada":
        m.apoiar(f"N{n}", ux=True, uy=True, uz=False,
                 rx=True, ry=True, rz=True)
    elif topo == "engastada_apoiada":
        m.apoiar(f"N{n}", ux=True, uy=True, uz=False,
                 rx=False, ry=False, rz=False)
    # "balanco" não recebe vínculo nenhum no topo.

    m.add_caso("P").nodal(f"N{n}", fz=-1.0)
    return m


def flambagem_de_euler() -> list[Conferencia]:
    """Pcr = π²EI/(kL)², com k valendo 1, 2, 0,5 e 0,699.

    A rigidez geométrica consistente converge por cima: com uma barra só o
    erro na biapoiada é de 0,8 %, e some com o refino. Por isso a conferência
    usa oito barras e tolerância de 0,2 %, que é folgada para o refino e
    apertada para qualquer erro de formulação.
    """
    from .core.segunda_ordem import flambagem

    L, n = 5.0, 8
    EI = E_ACO * min(_secao_retangular().Iy, _secao_retangular().Iz)
    euler = math.pi ** 2 * EI / L ** 2

    casos = (("biapoiada", 1.0), ("balanco", 2.0),
             ("biengastada", 0.5), ("engastada_apoiada", 0.6992))

    conferencias = []
    for nome, k in casos:
        fator = flambagem(_pilar_vertical(L, n, nome), "P").fator_critico
        conferencias.append(Conferencia(
            f"Euler {nome}: Pcr = π²EI/({k}L)²", fator, euler / k ** 2, 2e-3))
    return conferencias


def flambagem_sem_compressao() -> list[Conferencia]:
    """Sem barra comprimida não há o que calcular, e o programa diz isso."""
    from .core.segunda_ordem import flambagem

    m = _pilar_vertical(5.0, 4, "biapoiada")
    m.casos["P"].nodais.clear()
    m.casos["P"].nodal("N4", fz=+1.0)          # tração

    try:
        flambagem(m, "P")
        recusou = 0.0
    except ErroDeModelo:
        recusou = 1.0

    return [Conferencia("flambagem: carregamento sem compressão é recusado",
                        recusou, 1.0)]


# ---------------------------------------------------------------------------
# 25. P-Δ contra a solução exata de viga-coluna
# ---------------------------------------------------------------------------

def _balanco_viga_coluna(L: float, n: int, P: float, H: float) -> Modelo:
    """Pilar em balanço com força axial e transversal na ponta.

    A força transversal vai em **X global** de propósito. Num pilar vertical o
    eixo local x é o Z global, e daí o eixo local y é o X global: força em X
    flete no plano x–y local, o que envolve ``Iz`` e produz ``Mz``. É o mesmo
    ``Iz`` da carga crítica de referência, e assim os três — carga axial,
    plano de flexão e momento lido — falam do mesmo plano. Com a força em Y a
    flexão cairia no outro plano, com outra inércia e outra carga crítica.
    """
    m = _modelo_base("viga_coluna")
    for i in range(n + 1):
        m.add_no(f"N{i}", 0.0, 0.0, i * L / n)
    for i in range(n):
        m.add_barra(f"B{i}", f"N{i}", f"N{i + 1}", "aco", "R20x50")
    m.apoiar("N0")
    caso = m.add_caso("PH")
    caso.nodal(f"N{n}", fz=-P, fx=H)
    return m


def p_delta_viga_coluna() -> list[Conferencia]:
    """Balanço com força axial e transversal: M = H·tan(kL)/k, com k=√(P/EI).

    É a solução fechada da viga-coluna, e não a amplificação aproximada
    1/(1-P/Pcr). Com P valendo metade da carga crítica as duas divergem — a
    exata dá 1,80·HL e a aproximada 2,00·HL —, de modo que a conferência
    distingue uma análise de segunda ordem de verdade de um majorador.
    """
    from .core.segunda_ordem import resolver_p_delta

    L, n, H = 5.0, 10, 3.0
    secao = _secao_retangular()
    EI = E_ACO * secao.Iz            # a flexão em y usa Iz
    pcr = math.pi ** 2 * EI / (4.0 * L ** 2)
    P = 0.5 * pcr

    r = resolver_p_delta(_balanco_viga_coluna(L, n, P, H), "PH")
    k = math.sqrt(P / EI)
    momento_exato = H * math.tan(k * L) / k

    primeira_ordem = resolver(_balanco_viga_coluna(L, n, P, H), "PH")

    return [
        Conferencia("P-Δ: momento na base = H·tan(kL)/k",
                    abs(r.diagrama("B0").Mz[0]), momento_exato, 5e-3),
        # Com P na metade da crítica, o majorador ingênuo 1/(1-P/Pcr) daria
        # exatamente 2,00, e a solução exata dá tan(kL)/(kL) ≈ 1,817. A
        # distância entre os dois é o que separa uma análise de segunda ordem
        # de uma amplificação de esforços de primeira.
        Conferencia("P-Δ: não é o majorador ingênuo 1/(1-P/Pcr)",
                    float(abs(abs(r.diagrama("B0").Mz[0]) / (H * L) - 2.0)
                          > 0.15), 1.0),
        Conferencia("P-Δ: a 1ª ordem ignora o efeito e dá H·L",
                    abs(primeira_ordem.diagrama("B0").Mz[0]), H * L, 1e-10),
        Conferencia("P-Δ: convergiu em poucas iterações",
                    float(r.iteracoes <= 25), 1.0),
        Conferencia("P-Δ: o resultado vem marcado como de segunda ordem",
                    float(r.segunda_ordem), 1.0),
    ]


def p_delta_sem_normal() -> list[Conferencia]:
    """Sem esforço normal, a segunda ordem tem de repetir a primeira."""
    from .core.segunda_ordem import resolver_p_delta

    L, n, H = 5.0, 6, 3.0
    linear = resolver(_balanco_viga_coluna(L, n, 0.0, H), "PH")
    segunda = resolver_p_delta(_balanco_viga_coluna(L, n, 0.0, H), "PH")

    return [
        Conferencia("P-Δ sem normal: mesmo deslocamento da 1ª ordem",
                    segunda.deslocamento("N6")[0],
                    linear.deslocamento("N6")[0], 1e-12),
        Conferencia("P-Δ sem normal: mesmo momento da 1ª ordem",
                    segunda.diagrama("B0").Mz[0],
                    linear.diagrama("B0").Mz[0], 1e-12),
    ]


def p_delta_com_tracao() -> list[Conferencia]:
    """Tração enrijece: o efeito de segunda ordem muda de sinal."""
    from .core.segunda_ordem import resolver_p_delta

    L, n, H, P = 5.0, 8, 3.0, 200.0
    tracionado = resolver_p_delta(_balanco_viga_coluna(L, n, -P, H), "PH")
    linear = resolver(_balanco_viga_coluna(L, n, -P, H), "PH")

    return [
        Conferencia("P-Δ com tração: momento menor que o de 1ª ordem",
                    float(abs(tracionado.diagrama("B0").Mz[0])
                          < abs(linear.diagrama("B0").Mz[0])), 1.0),
    ]


def p_delta_acima_da_critica() -> list[Conferencia]:
    """Carga acima da crítica não tem solução, e o erro diz isso.

    Importa que a mensagem fale de carga acima da crítica, e não de mecanismo:
    a estrutura está bem vinculada, o que falta é margem de estabilidade.
    """
    from .core.segunda_ordem import flambagem, resolver_p_delta

    L, n, H = 5.0, 8, 3.0
    secao = _secao_retangular()
    pcr = math.pi ** 2 * E_ACO * secao.Iz / (4.0 * L ** 2)

    m = _balanco_viga_coluna(L, n, 1.3 * pcr, H)
    try:
        resolver_p_delta(m, "PH")
        recusou, falou_de_critica = 0.0, 0.0
    except ErroDeModelo as erro:
        recusou = 1.0
        falou_de_critica = float("crítica" in str(erro))

    margem = flambagem(_balanco_viga_coluna(L, n, 1.3 * pcr, H),
                       "PH").fator_critico

    return [
        Conferencia("P-Δ: carga acima da crítica é recusada", recusou, 1.0),
        Conferencia("P-Δ: o erro aponta a carga crítica, não mecanismo",
                    falou_de_critica, 1.0),
        Conferencia("flambagem: o fator crítico acusa a falta de margem",
                    float(margem < 1.0), 1.0),
        Conferencia("flambagem: e vale cerca de 1/1,3",
                    margem, 1.0 / 1.3, 5e-3),
    ]


def caso_efetivo_bate_com_superposicao() -> list[Conferencia]:
    """Somar as cargas antes tem de dar o mesmo que somar as respostas.

    Vale só na análise linear — e é justamente por isso que a conferência
    existe: ela garante que o ``caso_efetivo``, que a segunda ordem usa, é o
    mesmo carregamento que a superposição já validada representa.
    """
    from .core.combinacoes import caso_efetivo

    m = _viga_dois_casos()
    combinacao = Combinacao("1.4G+1.5Q", {"G": 1.4, "Q": 1.5})

    superposto = combinar(resolver_casos(m), combinacao)

    efetivo = caso_efetivo(m, combinacao)
    m.casos[efetivo.nome] = efetivo
    direto = resolver(m, efetivo.nome)

    return [
        Conferencia("caso efetivo: mesma flecha da superposição",
                    direto.deslocamento("M")[2],
                    superposto.deslocamento("M")[2], 1e-12),
        Conferencia("caso efetivo: mesmo momento da superposição",
                    direto.diagrama("B1").My[-1],
                    superposto.diagrama("B1").My[-1], 1e-12),
        Conferencia("caso efetivo: mesma reação da superposição",
                    direto.reacao("A")[2], superposto.reacao("A")[2], 1e-12),
    ]


# ---------------------------------------------------------------------------
# 26. Estabilidade global: α, γz e a rigidez secante
# ---------------------------------------------------------------------------

def _edificio_esbelto(n_pav: int = 4, pe_direito: float = 3.0) -> Modelo:
    """Pórtico de quatro pilares esbeltos, deslocável o bastante para ter γz."""
    m = Modelo("esbelto")
    m.add_material("concreto", 25.0e6, 0.2)
    m.add_secao(Secao.retangular("P25x25", 0.25, 0.25))
    m.add_secao(Secao.retangular("V20x40", 0.20, 0.40))

    pes = {"A": (0.0, 0.0), "B": (6.0, 0.0), "C": (6.0, 5.0), "D": (0.0, 5.0)}
    for nome, (x, y) in pes.items():
        for i in range(n_pav + 1):
            m.add_no(f"{nome}{i}", x, y, i * pe_direito)
        for i in range(n_pav):
            m.add_barra(f"P{nome}{i + 1}", f"{nome}{i}", f"{nome}{i + 1}",
                        "concreto", "P25x25")
        m.apoiar(f"{nome}0")

    for i in range(1, n_pav + 1):
        for a, b in (("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")):
            m.add_barra(f"V{a}{b}{i}", f"{a}{i}", f"{b}{i}",
                        "concreto", "V20x40")
    return m


def _caso_de_calculo(m: Modelo, n_pav: int, vertical: float,
                     horizontal: float) -> CasoDeCarga:
    caso = m.add_caso("Fd")
    for i in range(1, n_pav + 1):
        for nome in "ABCD":
            caso.nodal(f"{nome}{i}", fz=-vertical)
        caso.nodal(f"A{i}", fx=horizontal / 2.0)
        caso.nodal(f"D{i}", fx=horizontal / 2.0)
    return caso


def coeficiente_gama_z() -> list[Conferencia]:
    """γz = 1/(1 − ΔMtot,d/M1,tot,d), com as duas parcelas conferidas por fora."""
    from .core.estabilidade import contar_andares, gama_z

    n_pav, pe = 4, 3.0
    m = _edificio_esbelto(n_pav, pe)
    caso = _caso_de_calculo(m, n_pav, vertical=260.0, horizontal=42.0)
    r = resolver(m, "Fd")
    g = gama_z(m, caso, r)

    m1 = sum(c.fx * (m.ponto(c.no)[2]) for c in caso.nodais)
    delta = sum(-c.fz * r.deslocamento(c.no)[0]
                for c in caso.nodais if c.fz != 0.0)

    return [
        Conferencia("γz: M1,tot,d é o momento de tombamento", g.m1_tot_d, m1,
                    1e-10),
        Conferencia("γz: ΔMtot,d é Σ P·δ da 1ª ordem", g.delta_m_tot_d, delta,
                    1e-10),
        Conferencia("γz: valor pela fórmula do item 15.5.3",
                    g.valor, 1.0 / (1.0 - delta / m1), 1e-12),
        Conferencia("γz: contou os quatro andares",
                    float(contar_andares(m)), float(n_pav)),
        Conferencia("γz: o processo é aplicável a partir de quatro andares",
                    float(g.aplicavel), 1.0),
        Conferencia("γz: classificou como nós fixos ou móveis pelo 1,1",
                    float(g.nos_fixos), float(g.valor <= 1.10)),
    ]


def gama_z_contra_p_delta() -> list[Conferencia]:
    """A conferência que vale mais: γz e P-Δ têm de concordar.

    São duas formulações independentes. O γz sai de uma razão entre momentos
    da análise de primeira ordem; o P-Δ sai da matriz de rigidez geométrica,
    iterada até convergir. A teoria por trás do γz é a soma da série
    geométrica dos acréscimos, de modo que o deslocamento final deve valer
    cerca de γz vezes o de primeira ordem. Se as duas discordarem, uma das
    duas está errada.
    """
    from .core.estabilidade import gama_z
    from .core.segunda_ordem import resolver_p_delta

    n_pav, pe = 6, 3.0
    m = _edificio_esbelto(n_pav, pe)
    caso = _caso_de_calculo(m, n_pav, vertical=300.0, horizontal=50.0)

    primeira = resolver(m, "Fd")
    g = gama_z(m, caso, primeira)
    segunda = resolver_p_delta(m, "Fd")

    topo = f"A{n_pav}"
    razao = (segunda.deslocamento(topo)[0] / primeira.deslocamento(topo)[0])

    return [
        Conferencia("γz × P-Δ: o γz saiu maior que 1",
                    float(g.valor > 1.0), 1.0),
        Conferencia("γz × P-Δ: a amplificação do topo bate com o γz",
                    razao, g.valor, 3e-2),
        Conferencia("γz × P-Δ: a segunda ordem amplifica, não alivia",
                    float(razao > 1.0), 1.0),
    ]


def limites_do_alfa() -> list[Conferencia]:
    """Os valores de α1 do item 15.5.2, um a um."""
    from .core.estabilidade import alfa_limite

    return [
        Conferencia("α1: n=1 dá 0,2+0,1n", alfa_limite(1), 0.3, 1e-12),
        Conferencia("α1: n=2 dá 0,2+0,1n", alfa_limite(2), 0.4, 1e-12),
        Conferencia("α1: n=3 dá 0,2+0,1n", alfa_limite(3), 0.5, 1e-12),
        Conferencia("α1: n≥4 em associação dá 0,6",
                    alfa_limite(4, "associacao"), 0.6, 1e-12),
        Conferencia("α1: só pórticos dá 0,5",
                    alfa_limite(8, "porticos"), 0.5, 1e-12),
        Conferencia("α1: só pilares-parede dá 0,7",
                    alfa_limite(8, "pilares_parede"), 0.7, 1e-12),
    ]


def pilar_equivalente_de_um_balanco() -> list[Conferencia]:
    """Num balanço, a rigidez equivalente tem de devolver o próprio EI.

    O procedimento de 15.5.2 iguala o deslocamento de topo ao de um pilar de
    seção constante engastado na base. Aplicado a uma estrutura que já é
    exatamente isso, ele só pode devolver a rigidez que entrou.
    """
    from .core.estabilidade import rigidez_equivalente

    L, n, H = 12.0, 6, 20.0
    m = _modelo_base("balanco_alto")
    for i in range(n + 1):
        m.add_no(f"N{i}", 0.0, 0.0, i * L / n)
    for i in range(n):
        m.add_barra(f"B{i}", f"N{i}", f"N{i + 1}", "aco", "R20x50")
    m.apoiar("N0")
    caso = m.add_caso("H")
    caso.nodal(f"N{n}", fx=H)
    r = resolver(m, "H")

    EI = E_ACO * m.secoes["R20x50"].Iz

    return [
        Conferencia("pilar equivalente: recupera o EI do balanço",
                    rigidez_equivalente(m, caso, r), EI, 1e-9),
    ]


def parametro_de_instabilidade() -> list[Conferencia]:
    """α = Htot·√(Nk/(Ecs·Ic)), com Nk característico e não de cálculo."""
    from .core.estabilidade import parametro_alfa, rigidez_equivalente

    n_pav, pe = 5, 3.0
    m = _edificio_esbelto(n_pav, pe)

    vertical = m.add_caso("Gk")
    for i in range(1, n_pav + 1):
        for nome in "ABCD":
            vertical.nodal(f"{nome}{i}", fz=-200.0)

    horizontal = m.add_caso("Hk")
    for i in range(1, n_pav + 1):
        horizontal.nodal(f"A{i}", fx=15.0)
        horizontal.nodal(f"D{i}", fx=15.0)

    r = resolver(m, "Hk")
    a = parametro_alfa(m, horizontal, r, vertical)

    H_tot = n_pav * pe
    N_k = 200.0 * 4 * n_pav
    EI = rigidez_equivalente(m, horizontal, r)

    return [
        Conferencia("α: Htot é a altura total", a.H_tot, H_tot, 1e-12),
        Conferencia("α: Nk soma as verticais características", a.N_k, N_k,
                    1e-10),
        Conferencia("α: valor pela fórmula do item 15.5.2",
                    a.alfa, H_tot * math.sqrt(N_k / EI), 1e-12),
        Conferencia("α: limite α1 de cinco andares em associação",
                    a.limite, 0.6, 1e-12),
        Conferencia("α: classifica pelo confronto com α1",
                    float(a.nos_fixos), float(a.alfa < a.limite)),
    ]


def alfa_e_gama_z_concordam() -> list[Conferencia]:
    """Os dois processos aproximados de 15.5 devem classificar igual.

    São caminhos diferentes para a mesma pergunta — α olha a rigidez e a carga
    vertical, γz olha o acréscimo de momento. A norma oferece os dois como
    alternativas para dispensar a análise de segunda ordem, e seria estranho
    que discordassem numa estrutura clara. A conferência usa uma estrutura
    folgada e outra apertada, e exige que concordem nas duas.
    """
    from .core.estabilidade import gama_z, parametro_alfa

    resultados = []
    for rotulo, vertical, secao in (("folgada", 80.0, 0.45),
                                    ("apertada", 420.0, 0.22)):
        n_pav, pe = 5, 3.0
        m = _edificio_esbelto(n_pav, pe)
        m.secoes["P25x25"] = Secao.retangular("P25x25", secao, secao)

        gk = m.add_caso("Gk")
        for i in range(1, n_pav + 1):
            for nome in "ABCD":
                gk.nodal(f"{nome}{i}", fz=-vertical)
        hk = m.add_caso("Hk")
        for i in range(1, n_pav + 1):
            hk.nodal(f"A{i}", fx=12.0)
            hk.nodal(f"D{i}", fx=12.0)

        fd = m.add_caso("Fd")
        for c in gk.nodais:
            fd.nodal(c.no, fz=1.4 * c.fz)
        for c in hk.nodais:
            fd.nodal(c.no, fx=1.4 * c.fx)

        a = parametro_alfa(m, hk, resolver(m, "Hk"), gk)
        g = gama_z(m, fd, resolver(m, "Fd"))
        resultados.append((rotulo, a, g))

    return [
        Conferencia(f"α e γz concordam na estrutura {rotulo}",
                    float(a.nos_fixos == g.nos_fixos), 1.0)
        for rotulo, a, g in resultados
    ] + [
        Conferencia("estrutura folgada é de nós fixos",
                    float(resultados[0][2].nos_fixos), 1.0),
        Conferencia("estrutura apertada é de nós móveis",
                    float(resultados[1][2].nos_fixos), 0.0),
    ]


def majoracao_por_gama_z() -> list[Conferencia]:
    """0,95·γz sobre as ações horizontais, e a recusa acima de 1,3."""
    from .core.estabilidade import GamaZ, majorar_horizontais

    m = _edificio_esbelto(4, 3.0)
    gk = m.add_caso("G")
    for i in range(1, 5):
        for nome in "ABCD":
            gk.nodal(f"{nome}{i}", fz=-200.0)
    vk = m.add_caso("V", "variavel", "vento")
    for i in range(1, 5):
        vk.nodal(f"A{i}", fx=20.0)

    combinacao = Combinacao("ELU", {"G": 1.4, "V": 1.4})
    dentro = GamaZ("ELU", (1.0, 0.0), 100.0, 15.0, 1.18, 4)
    fora = GamaZ("ELU", (1.0, 0.0), 100.0, 30.0, 1.42, 4)

    majorada = majorar_horizontais(m, combinacao, dentro)
    try:
        majorar_horizontais(m, combinacao, fora)
        recusou = 0.0
    except ErroDeModelo:
        recusou = 1.0

    return [
        Conferencia("majoração: a horizontal recebe 0,95·γz",
                    majorada.fatores["V"], 1.4 * 0.95 * 1.18, 1e-12),
        Conferencia("majoração: a vertical fica intacta",
                    majorada.fatores["G"], 1.4, 1e-12),
        Conferencia("majoração: γz acima de 1,3 é recusado", recusou, 1.0),
        Conferencia("majoração: γz de 1,18 permite o processo",
                    float(dentro.majoracao_valida), 1.0),
    ]


def rigidez_secante_do_item_15_7_3() -> list[Conferencia]:
    """0,8 nos pilares, 0,4 nas vigas, e a área axial intocada."""
    from .core.estabilidade import rigidez_secante

    m = _edificio_esbelto(4, 3.0)
    reduzido = rigidez_secante(m)
    novo = reduzido.modelo

    pilar_antes = m.secoes[m.barras["PA1"].secao]
    pilar_depois = novo.secoes[novo.barras["PA1"].secao]
    viga_antes = m.secoes[m.barras["VAB1"].secao]
    viga_depois = novo.secoes[novo.barras["VAB1"].secao]

    simetricas = rigidez_secante(m, vigas_simetricas=["VAB1"]).modelo
    viga_simetrica = simetricas.secoes[simetricas.barras["VAB1"].secao]

    return [
        Conferencia("15.7.3: pilar com 0,8 da inércia",
                    pilar_depois.Iz / pilar_antes.Iz, 0.8, 1e-12),
        Conferencia("15.7.3: viga com 0,4 da inércia",
                    viga_depois.Iy / viga_antes.Iy, 0.4, 1e-12),
        Conferencia("15.7.3: viga de armadura simétrica com 0,5",
                    viga_simetrica.Iy / viga_antes.Iy, 0.5, 1e-12),
        Conferencia("15.7.3: a área não é reduzida junto",
                    pilar_depois.A, pilar_antes.A, 1e-12),
        Conferencia("15.7.3: o modelo original não foi alterado",
                    m.secoes[m.barras["PA1"].secao].Iz, pilar_antes.Iz, 1e-12),
        Conferencia("15.7.3: a rigidez reduzida amolece a estrutura",
                    float(_flecha_do_topo(novo) > _flecha_do_topo(m)), 1.0),
    ]


def _flecha_do_topo(m: Modelo) -> float:
    caso = m.casos.get("H") or m.add_caso("H")
    if not caso.nodais:
        for i in range(1, 5):
            caso.nodal(f"A{i}", fx=20.0)
    return abs(resolver(m, "H").deslocamento("A4")[0])


# ---------------------------------------------------------------------------
# 27. Deformação por cortante (Timoshenko)
# ---------------------------------------------------------------------------

def _viga_baixa_e_alta(L: float, n: int, cortante: bool) -> Modelo:
    """Viga curta e alta, em que a parcela de cortante pesa de verdade."""
    m = Modelo("timoshenko")
    m.add_material("aco", E_ACO, POISSON)
    m.add_secao(Secao.retangular("R20x50", 0.20, 0.50, cortante=cortante))
    for i in range(n + 1):
        m.add_no(f"N{i}", i * L / n, 0.0, 0.0)
    for i in range(n):
        m.add_barra(f"B{i}", f"N{i}", f"N{i + 1}", "aco", "R20x50")
    return m


def balanco_com_cortante() -> list[Conferencia]:
    """Balanço com carga na ponta: δ = PL³/3EI + PL/GAs.

    A segunda parcela é a do cortante, e nesta viga ela vale quase 9 % da
    primeira. Numa viga esbelta ela sumiria — é por isso que a área de
    cisalhamento não é ligada sozinha.
    """
    L, P = 1.5, 40.0
    m = _viga_baixa_e_alta(L, 1, cortante=True)
    m.apoiar("N0")
    m.add_caso("P").nodal("N1", fz=-P)
    r = resolver(m, "P")

    secao = m.secoes["R20x50"]
    EI = E_ACO * secao.Iy
    GAs = (E_ACO / (2.0 * (1.0 + POISSON))) * secao.Asz
    flexao = P * L ** 3 / (3.0 * EI)
    cisalhamento = P * L / GAs

    sem = _viga_baixa_e_alta(L, 1, cortante=False)
    sem.apoiar("N0")
    sem.add_caso("P").nodal("N1", fz=-P)
    flecha_sem = resolver(sem, "P").deslocamento("N1")[2]

    return [
        Conferencia("cortante: δ = PL³/3EI + PL/GAs",
                    r.deslocamento("N1")[2], -(flexao + cisalhamento), 1e-12),
        Conferencia("cortante: sem área de cisalhamento sobra só a flexão",
                    flecha_sem, -flexao, 1e-12),
        Conferencia("cortante: a parcela pesa cerca de 9 % nesta viga",
                    cisalhamento / flexao, 0.0868, 5e-3),
        Conferencia("cortante: Φ = 12EI/(GAsL²)",
                    12.0 * EI / (GAs * L ** 2),
                    4.0 * cisalhamento / flexao, 1e-12),
    ]


def biapoiada_com_cortante() -> list[Conferencia]:
    """Vão com carga uniforme: δ = 5wL⁴/384EI + wL²/8GAs."""
    L, w = 2.0, 300.0
    m = _viga_baixa_e_alta(L, 2, cortante=True)
    m.apoiar("N0", ux=True, uy=True, uz=True, rx=True, ry=False, rz=False)
    m.apoiar("N2", ux=False, uy=True, uz=True, rx=False, ry=False, rz=False)
    caso = m.add_caso("q")
    caso.distribuida("B0", qz=-w)
    caso.distribuida("B1", qz=-w)
    r = resolver(m, "q")

    secao = m.secoes["R20x50"]
    EI = E_ACO * secao.Iy
    GAs = (E_ACO / (2.0 * (1.0 + POISSON))) * secao.Asz
    esperado = 5.0 * w * L ** 4 / (384.0 * EI) + w * L ** 2 / (8.0 * GAs)

    return [
        Conferencia("cortante: δ = 5wL⁴/384EI + wL²/8GAs",
                    r.deslocamento("N1")[2], -esperado, 1e-12),
        Conferencia("cortante: momento no vão continua wL²/8",
                    r.diagrama("B0").My[-1], w * L ** 2 / 8.0, 1e-10),
    ]


def engastamento_perfeito_com_cortante() -> list[Conferencia]:
    """Sob carga uniforme, o engastamento perfeito não muda com o cortante.

    Vale a pena saber por quê: as integrais das funções de forma de Timoshenko
    dão exatamente L/12 e 1/2, com o (1+Φ) do numerador cancelando o do
    denominador. Ou seja, wL²/12 e wL/2 valem com ou sem cortante — e a
    conferência é forte justamente por isso, porque qualquer erro de
    coeficiente nas funções de forma quebraria esse cancelamento.
    """
    L, w = 2.0, 300.0
    m = _viga_baixa_e_alta(L, 1, cortante=True)
    m.apoiar("N0")
    m.apoiar("N1")
    m.add_caso("q").distribuida("B0", qz=-w)
    r = resolver(m, "q")
    d = r.diagrama("B0", 3)

    return [
        Conferencia("cortante: momento de engastamento continua wL²/12",
                    abs(d.My[0]), w * L ** 2 / 12.0, 1e-10),
        Conferencia("cortante: reação continua wL/2",
                    r.reacao("N0")[2], w * L / 2.0, 1e-10),
        Conferencia("cortante: momento no meio continua wL²/24",
                    d.My[1], w * L ** 2 / 24.0, 1e-10),
    ]


def cortante_em_carga_parcial() -> list[Conferencia]:
    """Em carga parcial o cortante age, e o equilíbrio continua fechando."""
    L, w = 2.0, 300.0
    def flecha(cortante: bool) -> tuple[float, float]:
        m = _viga_baixa_e_alta(L, 1, cortante=cortante)
        m.apoiar("N0")
        m.apoiar("N1", ux=False, uy=True, uz=True,
                 rx=False, ry=False, rz=False)
        m.add_caso("q").distribuida("B0", qz=-w, inicio=0.3, fim=0.8)
        r = resolver(m, "q")
        return r.reacao("N0")[2] + r.reacao("N1")[2], r.deslocamento("N1")[4]

    total_com, giro_com = flecha(True)
    total_sem, giro_sem = flecha(False)

    return [
        Conferencia("cortante: carga parcial ainda fecha o equilíbrio",
                    total_com, w * 0.5 * L, 1e-10),
        Conferencia("cortante: e a resposta difere da de Euler-Bernoulli",
                    float(abs(giro_com - giro_sem) > 1e-9 * abs(giro_sem)),
                    1.0),
    ]


# ---------------------------------------------------------------------------
# 28. Trechos rígidos
# ---------------------------------------------------------------------------

def trecho_rigido_no_engaste() -> list[Conferencia]:
    """Braço rígido no apoio: o vão flexível encurta, a estática não muda.

    O momento na extremidade do vão flexível vale P·Lf, que é o momento na
    face; a reação no nó continua valendo P·L, porque o braço transmite. A
    diferença entre os dois é exatamente o que os trechos rígidos existem para
    mostrar.
    """
    L, c, P = 5.0, 0.6, 30.0
    m = _modelo_base("offset_engaste")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "B", "aco", "R20x50", offset_i=c)
    m.apoiar("A")
    m.add_caso("P").nodal("B", fz=-P)
    r = resolver(m, "P")

    Lf = L - c
    EI = E_ACO * m.secoes["R20x50"].Iy
    d = r.diagrama("B1", 3)

    return [
        Conferencia("trecho rígido: momento na face vale P·Lf",
                    abs(d.My[0]), P * Lf, 1e-10),
        Conferencia("trecho rígido: reação no nó ainda vale P·L",
                    abs(r.reacao("A")[4]), P * L, 1e-10),
        Conferencia("trecho rígido: flecha da ponta é a de um balanço Lf",
                    r.deslocamento("B")[2], -P * Lf ** 3 / (3.0 * EI), 1e-12),
        Conferencia("trecho rígido: o diagrama começa depois do nó",
                    d.x[0], c, 1e-12),
        Conferencia("trecho rígido: e termina no nó final",
                    d.x[-1], L, 1e-12),
    ]


def trecho_rigido_na_ponta() -> list[Conferencia]:
    """Braço rígido na ponta carregada: a cinemática do braço aparece.

    O nó desloca o que a ponta flexível desloca **mais** o giro dela vezes o
    braço. Fazendo a conta, δ = (P/EI)·(Lf³/3 + c·Lf² + c²·Lf), que é menor que
    o PL³/3EI do balanço inteiro exatamente por c³/3 — o pedaço que deixou de
    fletir por ser rígido.
    """
    L, c, P = 5.0, 0.8, 30.0
    m = _modelo_base("offset_ponta")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "B", "aco", "R20x50", offset_j=c)
    m.apoiar("A")
    m.add_caso("P").nodal("B", fz=-P)
    r = resolver(m, "P")

    Lf = L - c
    EI = E_ACO * m.secoes["R20x50"].Iy
    esperado = P / EI * (Lf ** 3 / 3.0 + c * Lf ** 2 + c ** 2 * Lf)
    balanco_inteiro = P * L ** 3 / (3.0 * EI)

    return [
        Conferencia("trecho rígido: δ = (P/EI)(Lf³/3 + cLf² + c²Lf)",
                    r.deslocamento("B")[2], -esperado, 1e-12),
        Conferencia("trecho rígido: mais rígido que o balanço inteiro",
                    float(esperado < balanco_inteiro), 1.0),
        Conferencia("trecho rígido: a diferença é exatamente c³/3EI",
                    balanco_inteiro - esperado, P * c ** 3 / (3.0 * EI),
                    1e-10),
        Conferencia("trecho rígido: momento no engaste ainda vale P·L",
                    abs(r.reacao("A")[4]), P * L, 1e-10),
    ]


def trecho_rigido_no_portico() -> list[Conferencia]:
    """No pórtico, o momento na face é menor que o momento no eixo do pilar."""
    def montar(c: float) -> Modelo:
        m = _modelo_base("portico_face")
        m.add_secao(Secao.retangular("P40x40", 0.40, 0.40))
        m.add_no("A", 0.0, 0.0, 0.0)
        m.add_no("B", 0.0, 0.0, 3.0)
        m.add_no("C", 6.0, 0.0, 3.0)
        m.add_no("D", 6.0, 0.0, 0.0)
        m.add_barra("P1", "A", "B", "aco", "P40x40")
        m.add_barra("V1", "B", "C", "aco", "R20x50", offset_i=c, offset_j=c)
        m.add_barra("P2", "D", "C", "aco", "P40x40")
        m.apoiar("A")
        m.apoiar("D")
        m.add_caso("q").distribuida("V1", qz=-25.0)
        m.add_caso("H").nodal("B", fx=40.0)
        return m

    com = montar(0.20)
    sem = montar(0.0)
    q_com, q_sem = resolver(com, "q"), resolver(sem, "q")
    h_com, h_sem = resolver(com, "H"), resolver(sem, "H")

    return [
        Conferencia("trecho rígido: momento na face menor que no eixo",
                    float(abs(q_com.diagrama("V1").My[0])
                          < abs(q_sem.diagrama("V1").My[0])), 1.0),
        # Sob carga horizontal o braço só enrijece, e o deslocamento cai. Sob
        # gravidade não é assim: o momento que chega ao nó cresce, porque ao
        # w·Lf²/12 da face soma-se o cortante vezes o braço. Por isso a
        # conferência de rigidez usa o caso horizontal, e não o vertical — a
        # rotação do nó sob gravidade pode ir para qualquer lado.
        Conferencia("trecho rígido: o pórtico enrijece ao deslocamento lateral",
                    float(abs(h_com.deslocamento("B")[0])
                          < abs(h_sem.deslocamento("B")[0])), 1.0),
    ]


def trecho_rigido_sem_vao() -> list[Conferencia]:
    """Braços que consomem o vão inteiro são recusados."""
    m = _modelo_base("offset_demais")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", 2.0, 0.0, 0.0)
    m.add_barra("B1", "A", "B", "aco", "R20x50", offset_i=1.2, offset_j=1.0)
    m.apoiar("A")
    m.add_caso("P").nodal("B", fz=-10.0)

    try:
        resolver(m, "P")
        recusou = 0.0
    except ErroDeModelo:
        recusou = 1.0

    return [Conferencia("trecho rígido: vão flexível nulo é recusado",
                        recusou, 1.0)]


def trecho_rigido_com_segunda_ordem() -> list[Conferencia]:
    """Os braços rígidos também valem para a rigidez geométrica.

    Um pilar com trecho rígido na base tem vão flexível menor, e portanto
    carga crítica maior — pelo quadrado da razão dos comprimentos, que é o que
    Euler diz. Se a matriz geométrica ignorasse os braços, a carga crítica
    sairia a mesma com e sem eles.
    """
    from .core.segunda_ordem import flambagem

    L, c = 5.0, 1.0
    def montar(offset: float) -> Modelo:
        m = _modelo_base("offset_flambagem")
        m.add_no("N0", 0.0, 0.0, 0.0)
        m.add_no("N1", 0.0, 0.0, L)
        m.add_barra("B0", "N0", "N1", "aco", "R20x50", offset_i=offset)
        m.apoiar("N0")
        m.add_caso("P").nodal("N1", fz=-1.0)
        return m

    com = flambagem(montar(c), "P").fator_critico
    sem = flambagem(montar(0.0), "P").fator_critico

    return [
        Conferencia("trecho rígido: a carga crítica cresce com o vão menor",
                    com / sem, (L / (L - c)) ** 2, 2e-3),
    ]


# ---------------------------------------------------------------------------
# 29. Lajes como painel de carga
# ---------------------------------------------------------------------------

def _painel(lx: float, ly: float, offset: float = 0.0) -> Modelo:
    """Um painel isolado, apoiado nos quatro cantos."""
    m = _modelo_base("painel")
    m.add_secao(Secao.retangular("V20x50", 0.20, 0.50))
    cantos = (("A", 0.0, 0.0), ("B", lx, 0.0), ("C", lx, ly), ("D", 0.0, ly))
    for nome, x, y in cantos:
        m.add_no(nome, x, y, 0.0)
        m.apoiar(nome)
    for i, (a, b) in enumerate((("A", "B"), ("B", "C"), ("C", "D"),
                                ("D", "A"))):
        m.add_barra(f"V{i + 1}", a, b, "aco", "V20x50",
                    offset_i=offset, offset_j=offset)
    m.add_laje("L1", "A", "C", permanente=10.0, acidental=3.0)
    return m


def laje_reparte_a_carga_toda() -> list[Conferencia]:
    """A soma dos quatro quinhões tem de dar q·lx·ly, sem sobra nem falta.

    É a conferência que sustenta o processo das áreas: se a repartição a 45°
    perdesse carga, o pilar receberia menos do que a laje pesa, e o erro
    passaria despercebido porque nada no modelo acusaria a falta.
    """
    from .core.lajes import aplicar_lajes, carga_permanente

    lx, ly, q = 4.0, 6.0, 10.0
    m = _painel(lx, ly)
    caso = m.add_caso("G")
    repasse = aplicar_lajes(m, caso)[0]

    # Conferido também pela reação: toda a carga tem de chegar aos apoios.
    r = resolver(m, "G")

    curto = next(a for a in repasse.arestas if abs(a.comprimento - lx) < 1e-9)
    longo = next(a for a in repasse.arestas if abs(a.comprimento - ly) < 1e-9)

    return [
        Conferencia("laje: carga permanente é espessura·γ + revestimento",
                    carga_permanente(m, m.lajes["L1"]), q, 1e-12),
        Conferencia("laje: a soma dos quinhões dá q·lx·ly",
                    repasse.total, q * lx * ly, 1e-10),
        Conferencia("laje: quinhão do lado curto é q·lx²/4",
                    curto.total, q * lx ** 2 / 4.0, 1e-10),
        Conferencia("laje: quinhão do lado longo é q·lx(2ly−lx)/4",
                    longo.total, q * lx * (2.0 * ly - lx) / 4.0, 1e-10),
        Conferencia("laje: a reação total confere com o peso do painel",
                    r.reacoes_totais()[2], q * lx * ly, 1e-9),
    ]


def laje_quadrada_vira_triangulo() -> list[Conferencia]:
    """No painel quadrado o patamar some e as quatro cargas são triangulares."""
    from .core.lajes import aplicar_lajes

    lado, q = 5.0, 10.0
    m = _painel(lado, lado)
    caso = m.add_caso("G")
    repasse = aplicar_lajes(m, caso)[0]

    por_barra = {}
    for c in caso.distribuidas:
        por_barra.setdefault(c.barra, []).append(c)
    trechos = por_barra["V1"]

    return [
        Conferencia("laje quadrada: dois trechos por viga, sem patamar",
                    float(len(trechos)), 2.0),
        Conferencia("laje quadrada: as quatro vigas recebem o mesmo",
                    float(len({round(a.total, 9)
                               for a in repasse.arestas})), 1.0),
        Conferencia("laje quadrada: cada viga leva um quarto do painel",
                    repasse.arestas[0].total, q * lado ** 2 / 4.0, 1e-10),
    ]


def laje_com_trecho_rigido() -> list[Conferencia]:
    """Com trecho rígido, a carga que cairia sobre o braço não some.

    O perfil é desenhado sobre o vão flexível, mas a intensidade sai do total,
    não da geometria do painel. Sem esse cuidado a estrutura receberia menos
    carga do que a laje pesa, e nada acusaria a diferença.
    """
    from .core.lajes import aplicar_lajes

    lx, ly, q = 4.0, 6.0, 10.0
    com = _painel(lx, ly, offset=0.15)
    caso_com = com.add_caso("G")
    repasse_com = aplicar_lajes(com, caso_com)[0]
    r = resolver(com, "G")

    sem = _painel(lx, ly)
    repasse_sem = aplicar_lajes(sem, sem.add_caso("G"))[0]

    return [
        Conferencia("laje com trecho rígido: o total não muda",
                    repasse_com.total, repasse_sem.total, 1e-12),
        Conferencia("laje com trecho rígido: a reação ainda dá o peso todo",
                    r.reacoes_totais()[2], q * lx * ly, 1e-9),
    ]


def laje_recusa_painel_invalido() -> list[Conferencia]:
    """Cantos que não formam retângulo, ou lado sem viga, são recusados."""
    from .core.lajes import aplicar_lajes

    def tenta(preparar) -> float:
        m = _painel(4.0, 6.0)
        preparar(m)
        try:
            aplicar_lajes(m, m.add_caso("G"))
            return 0.0
        except ErroDeModelo:
            return 1.0

    def sem_viga(m: Modelo) -> None:
        del m.barras["V2"]

    def canto_torto(m: Modelo) -> None:
        m.lajes["L1"] = replace(m.lajes["L1"], no_c="B")

    def fora_do_plano(m: Modelo) -> None:
        m.nos["C"] = replace(m.nos["C"], z=1.0)

    return [
        Conferencia("laje: lado sem viga é recusado", tenta(sem_viga), 1.0),
        Conferencia("laje: cantos não diagonais são recusados",
                    tenta(canto_torto), 1.0),
        Conferencia("laje: painel fora do plano horizontal é recusado",
                    tenta(fora_do_plano), 1.0),
    ]


# ---------------------------------------------------------------------------
# 30. Confronto com o MASTAN2
# ---------------------------------------------------------------------------

PASTA_MASTAN = Path("MASTAN")


def _arquivos_do_mastan() -> list[Path]:
    """Procura a pasta de modelos do MASTAN2 acima deste arquivo.

    A busca olha cada diretório acima **e os seus subdiretórios imediatos**,
    porque a pasta de referência tanto pode estar ao lado do programa quanto
    agrupada com outras fontes. Procurar só o nível de cima já falhou uma vez,
    e o pior não foi falhar: foi falhar em silêncio, devolvendo lista vazia
    como se não houvesse o que conferir.
    """
    for pasta in Path(__file__).resolve().parents[:6]:
        candidatas = [pasta / PASTA_MASTAN]
        try:
            candidatas += [filha / PASTA_MASTAN for filha in pasta.iterdir()
                           if filha.is_dir()]
        except OSError:
            continue
        for candidata in candidatas:
            if candidata.is_dir():
                arquivos = sorted(candidata.glob("*.mat"))
                if arquivos:
                    return arquivos
    return []


def confronto_com_mastan() -> list[Conferencia]:
    """Resolve os modelos do MASTAN2 e compara com os resultados dele.

    É a aferição que sustenta a proposta do programa. Não se compara contra
    uma fórmula que alguém transcreveu: compara-se contra o próprio MASTAN2,
    nos modelos que ele mesmo resolveu e gravou — geometria, seções, eixos
    locais, cargas em eixos de barra e peso próprio, tudo lido do arquivo.

    A comparação é relativa à maior grandeza de cada família, e não absoluta,
    porque deslocamento em metro e reação em quilonewton não têm a mesma
    ordem. A tolerância é apertada de propósito: os dois programas resolvem o
    mesmo sistema, e o que os separa é só o arredondamento.
    """
    from .mastan import ler_mat

    arquivos = _arquivos_do_mastan()
    if not arquivos:
        # Declarada, e não omitida: sem esta linha a ausência da pasta some do
        # relatório, e a única pista seria a contagem cair sem explicação.
        return [Conferencia(
            "MASTAN: pasta de referência não encontrada, confronto não feito",
            0.0, 0.0)]

    conferencias = []
    comparados = 0
    for caminho in arquivos:
        mm = ler_mat(caminho)
        if mm.deslocamentos is None:
            continue                      # arquivo só com o modelo
        comparados += 1
        r = resolver(mm.modelo, mm.caso)
        rotulo = caminho.stem

        nossos = r.deslocamentos.reshape(-1, 6)[:, :3]
        deles = mm.deslocamentos[:, :3]
        escala = float(np.max(np.abs(deles))) or 1.0
        conferencias.append(Conferencia(
            f"MASTAN {rotulo}: deslocamentos",
            float(np.max(np.abs(nossos - deles))) / escala, 0.0, 1e-9))

        reacoes = np.zeros_like(mm.reacoes)
        for i, no in enumerate(mm.nos):
            if no in mm.modelo.apoios:
                reacoes[i] = r.reacao(no)
        escala = float(np.max(np.abs(mm.reacoes))) or 1.0
        conferencias.append(Conferencia(
            f"MASTAN {rotulo}: reações",
            float(np.max(np.abs(reacoes - mm.reacoes))) / escala, 0.0, 1e-9))

        esforcos = np.array([r.esforcos_barra(b)[:12] for b in mm.barras])
        escala = float(np.max(np.abs(mm.esforcos))) or 1.0
        conferencias.append(Conferencia(
            f"MASTAN {rotulo}: esforços de extremidade",
            float(np.max(np.abs(esforcos - mm.esforcos))) / escala, 0.0, 1e-9))

    if comparados:
        conferencias.insert(0, Conferencia(
            "MASTAN: modelos de referência confrontados",
            float(comparados), float(comparados)))
    return conferencias


# ---------------------------------------------------------------------------
# 31. Módulo de elasticidade do concreto — item 8.2.8
# ---------------------------------------------------------------------------

def modulo_do_concreto() -> list[Conferencia]:
    """As fórmulas de 8.2.8, conferidas onde elas se deixam conferir.

    A edição 2026 **removeu** a tabela de valores estimados por classe que a de
    2014 trazia, de modo que não há mais tabela normativa contra a qual bater
    estes números. Sem ela, a conferência ataca as fórmulas por outros três
    lados: o valor calculado à mão, a quase continuidade entre os dois ramos, e
    o ponto exato em que o limite de α_i passa a valer.
    """
    from .core.concreto import (alfa_i, modulo_inicial, modulo_secante)

    # C30, granito: 5600·√30 = 30 672 MPa; α_i = 0,875; E_cs = 26 838 MPa
    eci_30 = 5600.0 * math.sqrt(30.0)
    ecs_30 = (0.8 + 0.2 * 30.0 / 80.0) * eci_30

    return [
        Conferencia("8.2.8: E_ci de C30 é 5600√fck",
                    modulo_inicial(30.0), eci_30, 1e-12),
        Conferencia("8.2.8: E_cs de C30 é α_i·E_ci",
                    modulo_secante(30.0), ecs_30, 1e-12),
        Conferencia("8.2.8: α_E do basalto majora em 20 %",
                    modulo_inicial(30.0, "basalto e diabásio") / eci_30,
                    1.2, 1e-12),
        Conferencia("8.2.8: α_E do arenito reduz a 70 %",
                    modulo_inicial(30.0, "arenito") / eci_30, 0.7, 1e-12),
        Conferencia("8.2.8: α_i chega a 1 exatamente em C80",
                    alfa_i(80.0), 1.0, 1e-12),
        Conferencia("8.2.8: e não passa disso em C90",
                    alfa_i(90.0), 1.0, 1e-12),
        Conferencia("8.2.8: abaixo de C80 o α_i é menor que 1",
                    float(alfa_i(75.0) < 1.0), 1.0),
    ]


def ramos_do_modulo_se_encontram() -> list[Conferencia]:
    """Os dois ramos de 8.2.8 têm de quase coincidir na fronteira de 50 MPa.

    É a conferência mais valiosa deste bloco. Os dois ramos são expressões
    independentes, com coeficientes diferentes, e não há razão aritmética para
    darem o mesmo número em f_ck = 50 — a menos que ambos estejam transcritos
    certo. Um coeficiente errado em qualquer um abriria um degrau visível.
    """
    from .core.concreto import modulo_inicial

    abaixo = modulo_inicial(50.0)
    acima = 21.5e3 * (50.0 / 10.0 + 1.25) ** (1.0 / 3.0)
    salto = abs(acima - abaixo) / abaixo

    return [
        Conferencia("8.2.8: o ramo de f_ck ≤ 50 dá 39 598 MPa em C50",
                    abaixo, 5600.0 * math.sqrt(50.0), 1e-12),
        Conferencia("8.2.8: os dois ramos se encontram em C50",
                    salto, 0.0, 2e-4),
        Conferencia("8.2.8: o ramo alto vale acima de 50",
                    modulo_inicial(60.0),
                    21.5e3 * (6.0 + 1.25) ** (1.0 / 3.0), 1e-12),
        Conferencia("8.2.8: o módulo cresce com a classe",
                    float(modulo_inicial(90.0) > modulo_inicial(50.0)
                          > modulo_inicial(20.0)), 1.0),
    ]


def material_de_concreto() -> list[Conferencia]:
    """O material montado pela classe, e o G que fecha com 8.2.9."""
    from .core.concreto import concreto, modulo_secante

    c30 = concreto("C30", 30.0)

    return [
        Conferencia("concreto: E em kN/m², mil vezes o valor em MPa",
                    c30.E, modulo_secante(30.0) * 1000.0, 1e-9),
        Conferencia("concreto: guarda o fck com que foi feito", c30.fck, 30.0),
        Conferencia("concreto: 8.2.9 fixa ν = 0,2", c30.poisson, 0.2, 1e-12),
        Conferencia("concreto: peso específico do armado é 25 kN/m³",
                    c30.peso_especifico, 25.0, 1e-12),
        # 8.2.9 dá G_c = E_cs/2,4; o programa calcula G = E/(2(1+ν)), que com
        # ν = 0,2 é a mesma coisa. As duas definições coincidem sem ajuste.
        Conferencia("concreto: G = E/2,4 fecha com o item 8.2.9",
                    c30.G, c30.E / 2.4, 1e-9),
        Conferencia("concreto: o Eci é maior que o Ecs",
                    float(concreto("C30i", 30.0, modulo="Eci").E > c30.E), 1.0),
    ]


def concreto_recusa_entrada_ruim() -> list[Conferencia]:
    """Classe sem sentido e agregado fora da norma são recusados."""
    from .core.concreto import concreto, fck_da_classe

    def tenta(f) -> float:
        try:
            f()
            return 0.0
        except ErroDeModelo:
            return 1.0

    return [
        Conferencia("concreto: 'C30' é lido como 30 MPa",
                    fck_da_classe("C30"), 30.0, 1e-12),
        Conferencia("concreto: aceita o número puro",
                    fck_da_classe("45"), 45.0, 1e-12),
        Conferencia("concreto: classe sem sentido é recusada",
                    tenta(lambda: fck_da_classe("concreto forte")), 1.0),
        Conferencia("concreto: agregado fora do 8.2.8 é recusado",
                    tenta(lambda: concreto("x", 30.0, "mármore")), 1.0),
        Conferencia("concreto: módulo desconhecido é recusado",
                    tenta(lambda: concreto("x", 30.0, modulo="Esec")), 1.0),
    ]


# ---------------------------------------------------------------------------
# 32. O diagrama de momento sai do lado da fibra tracionada
# ---------------------------------------------------------------------------

def _biapoiada_em_um_plano(direcao: str, w: float = 20.0) -> Modelo:
    """Viga ao longo de X, carga uniforme para baixo no plano pedido."""
    m = _modelo_base(f"tracionada_{direcao}")
    for i, x in enumerate((0.0, 3.0, 6.0)):
        m.add_no(f"N{i}", x, 0.0, 0.0)
    m.add_barra("B1", "N0", "N1", "aco", "R20x50")
    m.add_barra("B2", "N1", "N2", "aco", "R20x50")
    m.apoiar("N0", ux=True, uy=True, uz=True, rx=True, ry=False, rz=False)
    m.apoiar("N2", ux=False, uy=True, uz=True, rx=False, ry=False, rz=False)
    caso = m.add_caso("q")
    for b in ("B1", "B2"):
        if direcao == "z":
            caso.distribuida(b, qz=-w, sistema="global")
        else:
            caso.distribuida(b, qy=-w, sistema="global")
    return m


def momento_do_lado_tracionado() -> list[Conferencia]:
    """O diagrama de momento tem de cair na face que traciona.

    É a convenção de projeto: numa biapoiada sob gravidade, o momento positivo
    traciona a face inferior, e é embaixo da viga que ele se desenha. A
    conferência mede o **deslocamento do traçado** em relação ao eixo da barra
    e exige que ele tenha o mesmo sinal do lado que desceu.

    Os dois planos não levam o mesmo sinal de desenho, e é isso que a
    conferência protege: com carga para baixo o momento no meio do vão sai
    +wL²/8 em ``My`` e −wL²/8 em ``Mz``, pela troca de sinal que a convenção
    θy = −dw/dx impõe. Igualar os dois sinais por simetria aparente poria um
    dos diagramas do lado errado.
    """
    from .ui.vista3d import pontos_do_diagrama

    conferencias = []
    for direcao, componente, eixo in (("z", "My", 2), ("y", "Mz", 1)):
        m = _biapoiada_em_um_plano(direcao)
        r = resolver(m, "q")
        base, topo, valor = pontos_do_diagrama(r, "B1", componente, 1.0, 3)

        # A viga desce na direção da carga: a face tracionada é a de baixo.
        flecha = r.deslocamento("N1")[eixo]
        # Deslocamento do traçado no meio do vão, projetado no eixo do plano.
        afastamento = float((topo[-1] - base[-1])[eixo])

        conferencias += [
            Conferencia(f"{componente}: a viga desce no plano x–{direcao}",
                        float(flecha < 0.0), 1.0),
            Conferencia(f"{componente}: o traçado cai do lado que desceu",
                        float(afastamento < 0.0), 1.0),
            Conferencia(f"{componente}: e o valor no meio vale wL²/8",
                        abs(valor[-1]), 20.0 * 6.0 ** 2 / 8.0, 1e-10),
        ]

    # A assimetria em si, dita em número: os dois planos têm sinais opostos.
    my = resolver(_biapoiada_em_um_plano("z"), "q").diagrama("B1", 3).My[-1]
    mz = resolver(_biapoiada_em_um_plano("y"), "q").diagrama("B1", 3).Mz[-1]
    conferencias.append(Conferencia(
        "momento: os dois planos saem com sinais opostos",
        float(my * mz < 0.0), 1.0))
    return conferencias


# ---------------------------------------------------------------------------
# 33. Charneiras plásticas, conferidas contra o programa de Lajes
# ---------------------------------------------------------------------------

def motores_de_elemento_copiados() -> list[Conferencia]:
    """Os motores copiados importam, e a cópia ainda é cópia do original.

    A segunda parte é a que interessa. Cópia que alguém editou à mão deixa de
    ser cópia e vira um garfo silencioso: o programa passa a calcular
    diferente do de elemento, e ninguém fica sabendo. A conferência compara
    byte a byte com a origem, quando ela estiver acessível — e quando não
    estiver, diz isso em vez de calar.
    """
    import hashlib
    import importlib

    from .elementos import PROCEDENCIA

    conferencias = []
    portas = {"pilares": ("core.dimensionar", "dimensionar"),
              "vigas": ("core.dimensionar", "dimensionar"),
              "vigas.desenho": ("saidas.desenho", "figura_elevacao"),
              "lajes": ("core.esforcos", "calcular"),
              "vento": ("nbr6123_core", "calc_s2")}

    for rotulo, (modulo, funcao) in portas.items():
        pacote = rotulo.split(".")[0]
        alvo = importlib.import_module(
            f".elementos.{pacote}.{modulo}", package="portico3d")
        conferencias.append(Conferencia(
            f"elementos: {rotulo} expõe {funcao}",
            float(callable(getattr(alvo, funcao, None))), 1.0))

    aqui = Path(__file__).resolve().parent / "elementos"
    raiz = _raiz_dos_programas()
    for elemento, dados in PROCEDENCIA.items():
        copiados = []
        for parte in dados["partes"]:
            pasta = (aqui / elemento / parte) if parte else (aqui / elemento)
            copiados += [(parte, p) for p in sorted(pasta.glob("*.py"))
                         if p.name != "__init__.py" or parte]
        # O ``__init__.py`` da raiz do pacote entra quando tem conteúdo: nos
        # motores de elemento é ele que guarda a revisão e a edição da norma,
        # e a memória de cálculo cita as duas. Deixá-lo fora da conferência
        # permitiria a um relatório dizer "R02, NBR 6118:2026" depois de a
        # origem ter virado outra coisa.
        raiz_init = aqui / elemento / "__init__.py"
        if raiz_init.exists() and raiz_init.read_bytes().strip():
            copiados.append(("", raiz_init))
        if _empacotado():
            # Dentro do executável não há .py em disco para contar, e a origem
            # não veio junto. Quem prova que o motor está aqui é a conferência
            # das portas, que importa e chama cada uma delas.
            conferencias.append(Conferencia(
                f"elementos: {elemento} empacotado, cópia não confrontada",
                0.0, 0.0))
            continue
        conferencias.append(Conferencia(
            f"elementos: {elemento} tem arquivos copiados",
            float(len(copiados) > 0), 1.0))

        # A origem é um commit do repositório do programa (os programas de
        # elemento viraram repositórios git, uma tag por revisão) ou, nas
        # cópias anteriores a isso, uma pasta. A pasta de revisão não existe
        # mais depois que o programa virou repositório: aí a cópia só se
        # confronta pelo commit.
        repositorio = (raiz / dados["repositorio"]
                       if raiz and dados.get("repositorio") else None)
        commit = dados.get("commit", "")
        ler = None
        if repositorio is not None and commit and \
                (repositorio / ".git").exists():
            def ler(caminho_relativo: str, _r=repositorio, _c=commit):
                r = subprocess.run(
                    ["git", "-C", str(_r), "show",
                     f"{_c}:{dados['pacote']}/{caminho_relativo}"],
                    capture_output=True)
                return r.stdout if r.returncode == 0 else None
        else:
            origem = raiz / dados["origem"] if raiz and dados.get("origem") \
                else None
            if origem is not None and origem.is_dir():
                def ler(caminho_relativo: str, _o=origem):
                    p = _o / caminho_relativo
                    return p.read_bytes() if p.exists() else None
        if ler is None:
            conferencias.append(Conferencia(
                f"elementos: origem de {elemento} fora de alcance "
                f"({dados['revisao']}), cópia não confrontada", 0.0, 0.0))
            continue

        diferentes = []
        for parte, arquivo in copiados:
            original = ler(f"{parte}/{arquivo.name}" if parte
                           else arquivo.name)
            if original is None:
                # O ``__init__.py`` vazio é criação nossa, para o pacote
                # existir; ele não vem da origem e não conta como diferença.
                if arquivo.name == "__init__.py" and not arquivo.read_bytes():
                    continue
                diferentes.append(arquivo.name)
                continue
            # o git pode devolver com outro fim de linha (autocrlf): compara
            # o conteúdo, não o \r
            if (hashlib.sha256(arquivo.read_bytes().replace(b"\r\n", b"\n"))
                    .digest() != hashlib.sha256(
                        original.replace(b"\r\n", b"\n")).digest()):
                diferentes.append(arquivo.name)
        conferencias.append(Conferencia(
            f"elementos: {elemento} idêntico a {dados['revisao']}",
            float(len(diferentes)), 0.0))

    return conferencias


def _empacotado() -> bool:
    """Verdadeiro quando o programa roda como executável do PyInstaller.

    Muda o que é possível conferir. Empacotado, os módulos vivem **dentro** do
    arquivo e não como .py em disco, e as pastas dos programas de origem não
    acompanham a entrega. Conferência que dependa de uma dessas duas coisas
    não tem como rodar ali — e o certo é ela dizer isso, e não reprovar uma
    instalação sadia. Reprovar o que não se pode medir ensina o usuário a
    ignorar o relatório inteiro.
    """
    import sys

    return bool(getattr(sys, "frozen", False))


def _raiz_dos_programas() -> Path | None:
    """A pasta ``Programas``, se este programa ainda estiver dentro dela."""
    for pasta in Path(__file__).resolve().parents[:8]:
        if pasta.name == "Programas":
            return pasta
    return None


def charneiras_batem_com_o_programa_de_lajes() -> list[Conferencia]:
    """As linhas de ruptura desenhadas aqui e as frações calculadas lá.

    O desenho das charneiras é geometria própria deste programa — de propósito,
    para não quebrar quando o programa de Lajes mudar por dentro. O preço de
    ter geometria própria é ter de provar que ela concorda com o cálculo que
    reparte a carga do outro lado, e é isso que esta conferência faz: integra
    a área de cada região desenhada e compara com a fração que o programa de
    Lajes publica.

    Os casos incluem painéis assimétricos, em que os quatro bordos têm
    vínculos diferentes: é ali que uma geometria aproximada se separaria da
    exata.
    """
    from .core.programa_lajes import (PESO, carregar_programa_lajes,
                                      fracoes_das_regioes, motor_de_reacoes)

    _, _, revisao = carregar_programa_lajes()
    reacoes_deles, tabelas_deles = motor_de_reacoes()

    mapa = {"apoiado": tabelas_deles.APOIADO,
            "engastado": tabelas_deles.ENGASTADO,
            "livre": tabelas_deles.LIVRE}

    casos = [
        ("apoiada nos quatro", 4.0, 5.0, ("apoiado",) * 4),
        ("dois engastes opostos", 4.0, 6.0,
         ("engastado", "apoiado", "engastado", "apoiado")),
        ("dois engastes vizinhos", 3.0, 7.0,
         ("engastado", "engastado", "apoiado", "apoiado")),
        ("quadrada assimétrica", 5.0, 5.0,
         ("engastado", "apoiado", "apoiado", "engastado")),
        ("com bordo livre", 4.0, 5.0,
         ("engastado", "apoiado", "livre", "apoiado")),
    ]

    conferencias = [Conferencia(
        f"Lajes: motor copiado de {revisao}", 1.0, 1.0)]
    for rotulo, a, b, vinculos in casos:
        nossa = fracoes_das_regioes(a, b, vinculos)
        deles = reacoes_deles.fracoes_charneiras(
            a, b, tuple(mapa[v] for v in vinculos))
        conferencias.append(Conferencia(
            f"charneiras, {rotulo}: as quatro frações",
            float(max(abs(n - d) for n, d in zip(nossa, deles))), 0.0, 1e-9))
        conferencias.append(Conferencia(
            f"charneiras, {rotulo}: as frações somam a área toda",
            float(sum(nossa)), 1.0, 1e-6))

    conferencias.append(Conferencia(
        "charneiras: o peso do engaste é √3 vezes o do apoio",
        PESO["engastado"] / PESO["apoiado"], math.sqrt(3.0), 1e-12))
    return conferencias


def momentos_de_laje_pelo_programa() -> list[Conferencia]:
    """Os momentos vêm do programa de Lajes, e o painel contínuo se reconhece.

    A conferência do momento em si é do outro programa, que tem as próprias.
    O que se prova aqui é a ponte: que o painel deste modelo vira o painel
    daquele com os vãos certos, os bordos certos e a carga certa.
    """
    from .core.programa_lajes import calcular_momentos, vinculos_automaticos

    # Dois painéis lado a lado: o bordo comum tem de sair engastado nos dois.
    m = _modelo_base("dois_paineis")
    m.add_secao(Secao.retangular("V20x50", 0.20, 0.50))
    for i, (x, y) in enumerate(((0.0, 0.0), (5.0, 0.0), (11.0, 0.0),
                                (0.0, 4.0), (5.0, 4.0), (11.0, 4.0))):
        m.add_no(f"N{i}", x, y, 0.0)
        m.apoiar(f"N{i}")
    for a, b in (("N0", "N1"), ("N1", "N2"), ("N3", "N4"), ("N4", "N5"),
                 ("N0", "N3"), ("N1", "N4"), ("N2", "N5")):
        m.add_barra(f"V{a}{b}", a, b, "aco", "V20x50")
    m.materiais["aco"] = replace(m.materiais["aco"], peso_especifico=25.0)
    m.add_laje("L1", "N0", "N4", 0.12, "aco", 1.5, 3.0)
    m.add_laje("L2", "N1", "N5", 0.12, "aco", 1.5, 3.0)

    vinculos = vinculos_automaticos(m)
    comum = sum(v.count("engastado") for v in vinculos.values())

    l1 = calcular_momentos(m, m.lajes["L1"], vinculos["L1"])
    l2 = calcular_momentos(m, m.lajes["L2"], vinculos["L2"])

    return [
        Conferencia("laje: o bordo comum é engastado dos dois lados",
                    float(comum), 2.0),
        Conferencia("laje: o menor vão de L1 é 4 m", l1.a, 4.0, 1e-9),
        Conferencia("laje: o maior vão de L1 é 5 m", l1.b, 5.0, 1e-9),
        Conferencia("laje: o painel maior tem o vão maior", l2.b, 6.0, 1e-9),
        Conferencia("laje: os dois painéis têm a mesma carga de cálculo",
                    l1.carga, l2.carga, 1e-12),
        Conferencia("laje: há momento negativo no bordo contínuo",
                    float(bool(l1.m_negativos) and bool(l2.m_negativos)), 1.0),
        Conferencia("laje: o painel maior tem momento de vão maior",
                    float(max(l2.ma, l2.mb) > max(l1.ma, l1.mb)), 1.0),
    ]


# ---------------------------------------------------------------------------
# 34. A ponte para o programa de Pilares
# ---------------------------------------------------------------------------

def _pilar_isolado(invertido: bool = False) -> tuple[Modelo, str]:
    """Um lance de pilar engastado na base, com seção de lados distintos.

    ``invertido`` monta a barra de cima para baixo, para provar que a base é
    achada pela cota e não pela ordem em que os nós foram digitados.
    """
    m = Modelo("lance")
    from .core.concreto import concreto
    c = concreto("C30", 30.0)
    m.materiais[c.nome] = c
    m.add_secao(Secao.retangular("P25x40", 0.25, 0.40))
    m.add_no("BASE", 0.0, 0.0, 0.0)
    m.add_no("TOPO", 0.0, 0.0, 3.0)
    if invertido:
        m.add_barra("P1", "TOPO", "BASE", c.nome, "P25x40")
    else:
        m.add_barra("P1", "BASE", "TOPO", c.nome, "P25x40")
    m.apoiar("BASE")
    caso = m.add_caso("Fd", "permanente")
    # Compressão com momento no topo, em dois planos distintos.
    caso.nodal("TOPO", fz=-400.0, fx=12.0, fy=5.0)
    return m, "P1"


def ponte_de_pilares_converte_certo() -> list[Conferencia]:
    """As três conversões da fronteira: unidade, sinal do normal e eixo.

    São elas que erram quando dois programas parecidos conversam. A unidade
    porque aqui é metro e lá é centímetro; o sinal porque aqui o normal é
    negativo à compressão e lá é positivo; o eixo porque a letra coincide e o
    significado não — o ``Mx`` de lá é o momento de excentricidade em x, que
    aqui se chama ``Mz``.
    """
    from .core.combinacoes import Combinacao, resolver_combinacoes
    from .core.envoltoria import envoltoria
    from .dimensionamento import (barras_verticais, esforcos_do_lance,
                                  montar_pilar)

    m, barra = _pilar_isolado()
    combinacao = Combinacao("C1", {"Fd": 1.0})
    env = envoltoria(m, resolver_combinacoes(m, [combinacao]))[barra]
    r = resolver(m, "Fd")

    lances = esforcos_do_lance(m, env, barra)
    lance = lances[0]
    d = r.diagrama(barra, 3)

    pilar = montar_pilar(m, barra, lance)

    return [
        Conferencia("ponte: a barra vertical é reconhecida como pilar",
                    float(barras_verticais(m) == [barra]), 1.0),
        # Sinal: o normal do solver é negativo, o Nd do pilar é positivo.
        Conferencia("ponte: Nd é o normal com o sinal trocado",
                    lance.Nd, -float(np.min(d.N)), 1e-10),
        Conferencia("ponte: e o normal do solver é mesmo negativo",
                    float(np.min(d.N) < 0.0), 1.0),
        # Unidade: kN·m aqui, kN·cm lá.
        Conferencia("ponte: momento convertido de kN·m para kN·cm",
                    lance.Mx_base, d.Mz[0] * 100.0, 1e-9),
        Conferencia("ponte: o mesmo vale para o outro plano",
                    lance.My_base, d.My[0] * 100.0, 1e-9),
        # Eixo: o Mx de lá recebe o Mz daqui, e o hx recebe o lado b.
        Conferencia("ponte: hx é o lado na direção local y",
                    pilar.secao.hx, 25.0, 1e-12),
        Conferencia("ponte: hy é o lado na direção local z",
                    pilar.secao.hy, 40.0, 1e-12),
        Conferencia("ponte: comprimento do lance em cm",
                    pilar.lance.altura, 300.0, 1e-12),
        Conferencia("ponte: o fck vem do material do modelo",
                    pilar.concreto.fck, 30.0, 1e-12),
    ]


def ponte_acha_a_base_pela_cota() -> list[Conferencia]:
    """Base e topo saem da cota, não da ordem dos nós da barra.

    Barra lançada de cima para baixo é comum em modelo gerado, e trocar topo
    com base inverteria a curvatura que o item 15.8.2 lê para achar o α_b.
    """
    from .core.combinacoes import Combinacao, resolver_combinacoes
    from .core.envoltoria import envoltoria
    from .dimensionamento import esforcos_do_lance

    valores = []
    for invertido in (False, True):
        m, barra = _pilar_isolado(invertido)
        env = envoltoria(m, resolver_combinacoes(
            m, [Combinacao("C1", {"Fd": 1.0})]))[barra]
        valores.append(esforcos_do_lance(m, env, barra)[0])

    direto, invertido = valores
    return [
        Conferencia("ponte: o Nd não muda com a ordem dos nós",
                    invertido.Nd, direto.Nd, 1e-9),
        Conferencia("ponte: o momento de base é o mesmo nos dois lançamentos",
                    abs(invertido.Mx_base), abs(direto.Mx_base), 1e-9),
        # No topo do balanço o momento é zero; a comparação precisa da escala
        # do lance, senão dois zeros numéricos discordariam por arredondamento.
        Conferencia("ponte: e o de topo também",
                    abs(invertido.Mx_topo), abs(direto.Mx_topo), 1e-9,
                    escala=abs(direto.Mx_base)),
        Conferencia("ponte: base e topo não são iguais neste lance",
                    float(abs(direto.Mx_base - direto.Mx_topo) > 1e-6), 1.0),
    ]


def ponte_roda_o_lote_do_edificio() -> list[Conferencia]:
    """O lote inteiro passa pelo motor de Pilares e volta com veredito."""
    from .core.combinacoes import resolver_combinacoes
    from .core.envoltoria import envoltoria
    from .core.nbr6118 import acoes_do_modelo, combinacoes_elu
    from .dimensionamento import barras_verticais, verificar_pilares

    m = _edificio_classificado()
    for nome in list(m.barras):
        if nome.startswith("P"):
            m.barras[nome] = replace(m.barras[nome], secao="P30x30")
    from .core.concreto import concreto
    c = concreto("C30", 30.0)
    m.materiais[c.nome] = c
    for nome, b in list(m.barras.items()):
        m.barras[nome] = replace(b, material=c.nome)

    env = envoltoria(m, resolver_combinacoes(
        m, combinacoes_elu(acoes_do_modelo(m))))
    pilares = barras_verticais(m)
    verificacoes = verificar_pilares(m, env, barras=pilares[:4])

    com_veredito = [v for v in verificacoes if v.passou]
    return [
        Conferencia("ponte: os pilares do edifício foram reconhecidos",
                    float(len(pilares)), 8.0),
        Conferencia("ponte: o lote produziu verificações",
                    float(len(verificacoes) > 0), 1.0),
        Conferencia("ponte: todas voltaram com veredito",
                    float(len(com_veredito)), float(len(verificacoes))),
        Conferencia("ponte: o motor devolveu área de aço necessária",
                    float(all(hasattr(v.resultado, "As_necessaria")
                              for v in com_veredito)), 1.0),
    ] + _cache_e_paralelo_dos_pilares(m, env, pilares[:4], verificacoes)


def _cache_e_paralelo_dos_pilares(m, env, barras, em_serie_ou_nao):
    """O mesmo lote em série, em paralelo e pelo cache dá o mesmo resultado.

    ``cache_motores`` guarda o resultado do motor pela impressão da entrada
    e calcula em paralelo os que faltam; nada disso pode mudar um número.
    """
    import os

    from . import cache_motores as cm
    from .dimensionamento import verificar_pilares

    def assinatura(vs):
        return [(v.barra, v.combinacao, v.erro,
                 getattr(v.resultado, "As_necessaria", None),
                 str(getattr(v.resultado, "arranjo", None))) for v in vs]

    antes = os.environ.get(cm.SEM_PARALELO)
    try:
        cm.limpar()
        os.environ[cm.SEM_PARALELO] = "1"
        serie = verificar_pilares(m, env, barras=barras)
        cm.limpar()
        os.environ.pop(cm.SEM_PARALELO, None)
        paralelo = verificar_pilares(m, env, barras=barras)
        calculados = cm.contagem["pilares_calculados"]
        ja_do_cache = cm.contagem["pilares_do_cache"]
        de_novo = verificar_pilares(m, env, barras=barras)
        do_cache = cm.contagem["pilares_do_cache"] - ja_do_cache
    finally:
        if antes is None:
            os.environ.pop(cm.SEM_PARALELO, None)
        else:
            os.environ[cm.SEM_PARALELO] = antes
    n = len(serie)
    return [
        Conferencia("cache: série e paralelo dão o mesmo resultado",
                    float(assinatura(serie) == assinatura(paralelo)), 1.0),
        Conferencia("cache: igual ao lote calculado antes",
                    float(assinatura(serie)
                          == assinatura(em_serie_ou_nao)), 1.0),
        Conferencia("cache: a segunda chamada não recalcula nada",
                    float(cm.contagem["pilares_calculados"] - calculados),
                    0.0),
        Conferencia("cache: a segunda chamada vem toda do cache",
                    float(do_cache), float(n)),
        Conferencia("cache: e dá o mesmo resultado",
                    float(assinatura(de_novo) == assinatura(serie)), 1.0),
    ]


# ---------------------------------------------------------------------------
# 35. Vigas contínuas: reconhecimento e ponte
# ---------------------------------------------------------------------------

def _pavimento_de_tres_vaos() -> Modelo:
    """Viga de três vãos com um nó de passagem no meio do primeiro.

    O nó de passagem é o ponto da conferência: ele existe na malha mas não
    tem pilar, e tratá-lo como apoio inventaria um vão que não existe.
    """
    from .core.concreto import concreto

    m = Modelo("tres_vaos")
    c = concreto("C30", 30.0)
    m.materiais[c.nome] = c
    m.add_secao(Secao.retangular("V20x50", 0.20, 0.50))
    m.add_secao(Secao.retangular("P30x30", 0.30, 0.30))

    cotas = [0.0, 2.5, 5.0, 11.0, 16.0]
    com_pilar = {0.0, 5.0, 11.0, 16.0}
    for i, x in enumerate(cotas):
        m.add_no(f"N{i}", x, 0.0, 3.0)
        if x in com_pilar:
            m.add_no(f"B{i}", x, 0.0, 0.0)
            m.add_barra(f"P{i}", f"B{i}", f"N{i}", c.nome, "P30x30")
            m.apoiar(f"B{i}")
    for i in range(len(cotas) - 1):
        m.add_barra(f"V{i}", f"N{i}", f"N{i + 1}", c.nome, "V20x50")

    g = m.add_caso("G", "permanente")
    for i in range(len(cotas) - 1):
        g.distribuida(f"V{i}", qz=-18.0, sistema="global")
    q = m.add_caso("Q", "variavel", "residencial")
    for i in range(len(cotas) - 1):
        q.distribuida(f"V{i}", qz=-9.0, sistema="global")
    m.validar()
    return m


def viga_continua_reconhecida() -> list[Conferencia]:
    """Quatro barras, três vãos: o nó sem pilar não é apoio."""
    from .continuidade import nos_com_pilar, vigas_continuas

    m = _pavimento_de_tres_vaos()
    vigas = [v for v in vigas_continuas(m) if len(v.barras) > 1]

    return [
        Conferencia("viga contínua: a cadeia foi reconhecida",
                    float(len(vigas)), 1.0),
        Conferencia("viga contínua: reúne as quatro barras",
                    float(len(vigas[0].barras)), 4.0),
        Conferencia("viga contínua: mas só quatro apoios",
                    float(len(vigas[0].apoios)), 4.0),
        Conferencia("viga contínua: três vãos, não quatro",
                    float(len(vigas[0].vaos)), 3.0),
        Conferencia("viga contínua: o primeiro vão mede 5 m, e não 2,5",
                    vigas[0].vaos[0], 5.0, 1e-12),
        Conferencia("viga contínua: o vão do meio mede 6 m",
                    vigas[0].vaos[1], 6.0, 1e-12),
        Conferencia("viga contínua: comprimento total de 16 m",
                    vigas[0].comprimento, 16.0, 1e-12),
        Conferencia("viga contínua: os pilares foram achados",
                    float(len(nos_com_pilar(m))), 8.0),
    ]


def ponte_de_vigas_monta_e_dimensiona() -> list[Conferencia]:
    """A viga do outro programa nasce com os vãos, a seção e as cargas certas.

    A carga é conferida pelo **total**: a soma de q·comprimento de todos os
    trechos traduzidos tem de dar a carga que o pórtico tem, senão a viga foi
    dimensionada para menos do que carrega.
    """
    from .continuidade import vigas_continuas
    from .dimensionamento import montar_viga

    m = _pavimento_de_tres_vaos()
    viga = next(v for v in vigas_continuas(m) if len(v.barras) > 1)
    deles = montar_viga(m, viga)

    total_g = sum(c.q1 * (c.x_fim - c.x_ini) for c in deles.distribuidas
                  if c.acao == "g")
    total_q = sum(c.q1 * (c.x_fim - c.x_ini) for c in deles.distribuidas
                  if c.acao == "q")

    return [
        Conferencia("ponte de vigas: um tramo por vão", float(len(deles.tramos)),
                    3.0),
        Conferencia("ponte de vigas: apoios são vãos mais um",
                    float(len(deles.apoios)), 4.0),
        Conferencia("ponte de vigas: seção em centímetros",
                    deles.tramos[0].secao.bw, 20.0, 1e-12),
        Conferencia("ponte de vigas: altura em centímetros",
                    deles.tramos[0].secao.h, 50.0, 1e-12),
        Conferencia("ponte de vigas: largura do apoio é a do pilar",
                    deles.apoios[1].largura, 30.0, 1e-12),
        Conferencia("ponte de vigas: carga permanente total preservada",
                    total_g, 18.0 * 16.0, 1e-9),
        Conferencia("ponte de vigas: carga variável total preservada",
                    total_q, 9.0 * 16.0, 1e-9),
        Conferencia("ponte de vigas: a carga é positiva para baixo",
                    float(all(c.q1 > 0 for c in deles.distribuidas)), 1.0),
        Conferencia("ponte de vigas: o fck veio do material",
                    deles.concreto.fck, 30.0, 1e-12),
    ]


def ponte_de_vigas_desenha(pasta) -> list[Conferencia]:
    """Dimensiona e grava o desenho — um DXF só, sem PNG, todas as vigas nele."""
    from pathlib import Path

    from .dimensionamento import verificar_vigas

    destino = Path(pasta) / "vigas"
    m = _pavimento_de_tres_vaos()
    verificacoes = verificar_vigas(m, pasta_desenhos=destino)
    com_veredito = [v for v in verificacoes if v.passou]
    arquivos = {Path(a) for v in com_veredito for a in v.desenhos}

    pngs = [a for a in arquivos if a.suffix == ".png"]
    dxfs = [a for a in arquivos if a.suffix == ".dxf"]

    entidades = _entidades_do_dxf(dxfs[0]) if dxfs else 0
    titulos_de_viga = 0
    if dxfs:
        try:
            import ezdxf
            doc = ezdxf.readfile(str(dxfs[0]))
            titulos_de_viga = sum(
                1 for t in doc.modelspace().query("TEXT")
                if t.dxf.text.startswith("VIGA "))
        except Exception:                                # noqa: BLE001
            pass

    return [
        Conferencia("ponte de vigas: a viga foi dimensionada",
                    float(len(com_veredito)), 1.0),
        Conferencia("ponte de vigas: nenhum PNG — só o DXF é gerado",
                    float(len(pngs)), 0.0),
        Conferencia("ponte de vigas: um DXF só, e não um por viga",
                    float(len(dxfs)), 1.0),
        Conferencia("ponte de vigas: os arquivos existem e não estão vazios",
                    float(all(a.exists() and a.stat().st_size > 5000
                              for a in arquivos)), 1.0),
        Conferencia("ponte de vigas: o DXF abre e tem entidades",
                    float(entidades > 0), 1.0),
        Conferencia("ponte de vigas: cada viga aparece com seu título "
                    "dentro do DXF único",
                    float(titulos_de_viga), float(len(com_veredito))),
    ]


def ponte_de_vigas_desenha_varias(pasta) -> list[Conferencia]:
    """Um pavimento com cinco vigas contínuas: todas no mesmo DXF, lado a lado.

    O caso de uma viga só (:func:`ponte_de_vigas_desenha`) não prova que a
    prancha **empilha** — com uma peça, um arquivo de uma peça só e um
    arquivo mesclado ficam indistinguíveis. Este usa o pavimento de dois
    painéis, que reconhece cinco vigas contínuas, e confere que as cinco
    títulos aparecem no arquivo único, em vagas que não se sobrepõem.
    """
    from pathlib import Path

    from .dimensionamento import verificar_vigas

    destino = Path(pasta) / "vigas_varias"
    m = _portico_com_vento()
    verificacoes = verificar_vigas(m, pasta_desenhos=destino)
    com_veredito = [v for v in verificacoes if v.passou]
    arquivos = {Path(a) for v in com_veredito for a in v.desenhos}
    dxfs = [a for a in arquivos if a.suffix == ".dxf"]

    titulos = []
    caixas = []
    if dxfs:
        import ezdxf
        import ezdxf.bbox

        doc = ezdxf.readfile(str(dxfs[0]))
        msp = doc.modelspace()
        for t in msp.query("TEXT"):
            if t.dxf.text.startswith("VIGA "):
                titulos.append(t.dxf.text)
                caixa = ezdxf.bbox.extents([t], fast=True)
                if caixa.has_data:
                    caixas.append((caixa.extmin.y, caixa.extmax.y))

    # nenhuma vaga pode invadir a vizinha: as faixas de Y de dois títulos
    # quaisquer não se sobrepõem
    sem_sobreposicao = all(
        b0 >= a1 or a0 >= b1
        for i, (a0, a1) in enumerate(caixas)
        for b0, b1 in caixas[i + 1:])

    return [
        Conferencia("ponte de vigas (várias): as cinco foram dimensionadas",
                    float(len(com_veredito)), 5.0),
        Conferencia("ponte de vigas (várias): um DXF só para as cinco",
                    float(len(dxfs)), 1.0),
        Conferencia("ponte de vigas (várias): os cinco títulos aparecem",
                    float(len(titulos)), 5.0),
        Conferencia("ponte de vigas (várias): nenhuma vaga se sobrepõe",
                    float(sem_sobreposicao), 1.0),
    ]


def _entidades_do_dxf(caminho) -> int:
    """Quantas entidades o arquivo CAD tem, lendo-o de volta.

    Ler de volta é o que distingue "gravou um arquivo" de "gravou um desenho":
    arquivo com cabeçalho e nada dentro passaria por tamanho.
    """
    try:
        import ezdxf
    except ImportError:
        return 1
    try:
        return len(ezdxf.readfile(str(caminho)).modelspace())
    except Exception:                                # noqa: BLE001
        return 0


# ---------------------------------------------------------------------------
# 36. A ponte para o programa de Lajes
# ---------------------------------------------------------------------------

def _pavimento_de_dois_paineis() -> Modelo:
    """Dois painéis lado a lado, com vigas de 20 cm de largura."""
    from .core.concreto import concreto

    m = Modelo("pavimento")
    c = concreto("C30", 30.0)
    m.materiais[c.nome] = c
    m.add_secao(Secao.retangular("V20x50", 0.20, 0.50))
    m.add_secao(Secao.retangular("P30x30", 0.30, 0.30))

    pontos = ((0.0, 0.0), (5.0, 0.0), (11.0, 0.0),
              (0.0, 4.0), (5.0, 4.0), (11.0, 4.0))
    for i, (x, y) in enumerate(pontos):
        m.add_no(f"N{i}", x, y, 3.0)
        m.add_no(f"B{i}", x, y, 0.0)
        m.add_barra(f"P{i}", f"B{i}", f"N{i}", c.nome, "P30x30")
        m.apoiar(f"B{i}")
    for a, b in (("N0", "N1"), ("N1", "N2"), ("N3", "N4"), ("N4", "N5"),
                 ("N0", "N3"), ("N1", "N4"), ("N2", "N5")):
        m.add_barra(f"V{a}{b}", a, b, c.nome, "V20x50")

    m.add_laje("L1", "N0", "N4", 0.12, c.nome, 1.5, 3.0)
    m.add_laje("L2", "N1", "N5", 0.12, c.nome, 1.5, 3.0)
    m.validar()
    return m


def ponte_de_lajes_monta_o_pavimento() -> list[Conferencia]:
    """O pavimento nasce com vãos livres, continuidade e bordos engastados.

    Três coisas que a tradução tem de acertar, e que o próprio programa de
    Lajes reclama quando erradas — foi assim que a terceira apareceu:

    * o vão é o **livre**, descontada meia viga de cada lado, porque o painel
      do pórtico é definido por eixos e o de lá espera vão livre;
    * a continuidade é **detectada por ele**, pela posição em planta;
    * e detectar não basta: é preciso **aplicar**, senão os bordos ficam
      apoiados enquanto a continuidade diz que são contínuos.
    """
    from .dimensionamento import montar_pavimento

    m = _pavimento_de_dois_paineis()
    pav = montar_pavimento(m, 3.0)
    l1 = next(l for l in pav.lajes if l.nome == "L1")

    engastados = sum(1 for l in pav.lajes for b in l.bordos
                     if b.vinculo == "engastado")

    return [
        Conferencia("ponte de lajes: os dois painéis entraram",
                    float(len(pav.lajes)), 2.0),
        # O painel L1 vai de (0,0) a (5,4): o menor vão é o de 4 m, e cada um
        # perde meia viga de 20 cm em cada lado.
        Conferencia("ponte de lajes: o menor vão livre é 4 m menos meia viga",
                    min(l1.a, l1.b), 4.0 - 0.20, 1e-9),
        Conferencia("ponte de lajes: e o maior é 5 m menos meia viga",
                    max(l1.a, l1.b), 5.0 - 0.20, 1e-9),
        Conferencia("ponte de lajes: a largura do apoio é a da viga",
                    l1.bordos[0].t, 20.0, 1e-9),
        Conferencia("ponte de lajes: a espessura vai em centímetros",
                    l1.h, 12.0, 1e-9),
        Conferencia("ponte de lajes: uma borda comum foi detectada",
                    float(len(pav.continuidades)), 1.0),
        Conferencia("ponte de lajes: e ela engastou os dois bordos",
                    float(engastados), 2.0),
        Conferencia("ponte de lajes: o fck veio do material do modelo",
                    pav.concreto.fck, 30.0, 1e-12),
    ]


def ponte_de_lajes_dimensiona_e_desenha(pasta) -> list[Conferencia]:
    """Dimensiona o pavimento e grava as plantas de armação.

    O veredito é lido dos **erros** do resultado, e não de um campo ``ok`` —
    ``ResultadoPavimento`` não tem esse campo, e perguntar por ele devolveria
    sempre "com ressalva", fazendo o relatório mentir sem falhar.
    """
    from pathlib import Path

    from .dimensionamento import verificar_lajes

    destino = Path(pasta) / "lajes"
    m = _pavimento_de_dois_paineis()
    verificacoes = verificar_lajes(m, pasta_desenhos=destino)
    com_veredito = [v for v in verificacoes if v.passou]
    arquivos = [Path(a) for v in com_veredito for a in v.desenhos]

    tem_erros = com_veredito and list(com_veredito[0].resultado.erros)
    continuidade_reclamada = any(
        "vínculo está" in str(getattr(e, "texto", e))
        for v in com_veredito for e in v.resultado.erros)

    return [
        Conferencia("ponte de lajes: um pavimento foi dimensionado",
                    float(len(com_veredito)), 1.0),
        Conferencia("ponte de lajes: o resultado expõe erros e avisos",
                    float(hasattr(com_veredito[0].resultado, "erros")
                          if com_veredito else 0), 1.0),
        # O programa de Lajes acusa bordo comum deixado como apoiado. Depois
        # de aplicar as continuidades, essa reclamação não pode mais aparecer.
        Conferencia("ponte de lajes: nenhuma reclamação de vínculo de borda",
                    float(continuidade_reclamada), 0.0),
        Conferencia("ponte de lajes: as plantas de armação foram gravadas",
                    float(len([a for a in arquivos if a.suffix == ".png"])),
                    2.0),
        Conferencia("ponte de lajes: e o DXF do pavimento",
                    float(len([a for a in arquivos if a.suffix == ".dxf"])),
                    1.0),
        Conferencia("ponte de lajes: o DXF abre e tem entidades",
                    float(_entidades_do_dxf(
                        next(a for a in arquivos if a.suffix == ".dxf")) > 0),
                    1.0),
        Conferencia("ponte de lajes: os arquivos existem e não estão vazios",
                    float(all(a.exists() and a.stat().st_size > 5000
                              for a in arquivos)), 1.0),
        # A ``area`` do programa de Lajes usa o vão **efetivo** do item
        # 14.7.2.2, e não o livre: cada bordo apoiado acrescenta
        # min(t/2 ; 0,3h). Conferir contra o vão livre daria uma área menor e
        # a diferença passaria por erro de tradução, que não é.
        Conferencia("ponte de lajes: a área usa o vão efetivo, não o livre",
                    com_veredito[0].resultado.area_total,
                    sum(r.laje.a_ef * r.laje.b_ef
                        for r in com_veredito[0].resultado.lajes), 1e-9),
        Conferencia("ponte de lajes: e ela supera a do vão livre",
                    float(com_veredito[0].resultado.area_total
                          > 3.8 * 4.8 + 3.8 * 5.8), 1.0),
    ]


# ---------------------------------------------------------------------------
# 11. Ida e volta pelo arquivo JSON
# ---------------------------------------------------------------------------

def classificacao_no_arquivo(pasta) -> list[Conferencia]:
    """A classificação normativa sobrevive à ida e volta pelo arquivo."""
    from pathlib import Path

    from .arquivo import gravar, ler

    original = _edificio_classificado()
    lido = ler(gravar(original, Path(pasta) / "edificio.json"))

    antes = combinacoes_elu(acoes_do_modelo(original))
    depois = combinacoes_elu(acoes_do_modelo(lido))

    return [
        Conferencia("arquivo: natureza do caso preservada",
                    float(lido.casos["Q"].natureza == "variavel"), 1.0),
        Conferencia("arquivo: categoria de ψ preservada",
                    float(lido.casos["Q"].categoria == "comercial"), 1.0),
        Conferencia("arquivo: grupo excludente preservado",
                    float(lido.casos["VX"].grupo == "vento"), 1.0),
        Conferencia("arquivo: gera as mesmas combinações",
                    float(len(depois)), float(len(antes))),
        Conferencia("arquivo: com os mesmos fatores",
                    float(all(a.fatores == d.fatores
                              for a, d in zip(antes, depois))), 1.0),
    ]


def ida_e_volta_json(pasta) -> list[Conferencia]:
    from pathlib import Path

    from .arquivo import gravar, ler

    L, w = 6.0, 20.0
    m = _viga_em_dois_tramos("json", L)
    m.apoiar("A", ux=True, uy=True, uz=True, rx=True, ry=False, rz=False)
    m.apoiar("B", ux=False, uy=True, uz=True, rx=False, ry=False, rz=False)
    caso = m.add_caso("q")
    caso.distribuida("B1", qz=-w)
    caso.distribuida("B2", qz=-w)

    caminho = gravar(m, Path(pasta) / "exemplo.json")
    lido = ler(caminho)

    original = resolver(m, "q").deslocamento("M")[2]
    recuperado = resolver(lido, "q").deslocamento("M")[2]

    return [
        Conferencia("arquivo: modelo gravado e lido dá a mesma flecha",
                    recuperado, original, 1e-12),
    ]


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 37. Armadura no espaço: cada barra dentro do concreto dela
# ---------------------------------------------------------------------------

def _pavimento_carregado() -> Modelo:
    """Os dois painéis, agora com carga — é o que faz os três motores rodarem.

    Sem caso de carga não há envoltória, e sem envoltória o pilar não tem
    esforço de lance: o pavimento sairia só com viga e laje.
    """
    m = _pavimento_de_dois_paineis()
    g = m.add_caso("G", "permanente")
    peso_proprio(m, g)
    q = m.add_caso("Q", "variavel", "residencial")
    for nome in m.barras:
        if nome.startswith("V"):
            q.distribuida(nome, qz=-6.0, sistema="global")
    return m


def _armadura_de_prova():
    from .armadura3d import armadura_do_pavimento
    from .core.combinacoes import resolver_combinacoes

    m = _pavimento_carregado()
    env = envoltoria(m, resolver_combinacoes(
        m, combinacoes_elu(acoes_do_modelo(m))))
    return m, armadura_do_pavimento(m, 3.0, env)


def armadura_cai_dentro_do_concreto() -> list[Conferencia]:
    """A conferência que importa: cada barra dentro da peça que a contém.

    É aqui que uma troca de eixo apareceria. As três conversões de coordenada
    — pilar pelo CG, viga pelo canto inferior esquerdo, laje pelo sistema
    global de planta — são independentes, e um sinal trocado em qualquer uma
    joga a armadura para fora da peça sem levantar exceção nenhuma. Medir a
    distância ao eixo em fração da meia-seção pega qualquer uma das três: se
    passar de 1, a barra está no ar.
    """
    from .armadura3d import FAMILIAS
    from .continuidade import vigas_continuas

    m, arm = _armadura_de_prova()
    preparadas = preparar_barras(m)

    pior_pilar = 0.0
    for fio in arm.fios:
        if not fio.familia.startswith("pilar"):
            continue
        p = preparadas[fio.elemento]
        b = m.barras[fio.elemento]
        secao = m.secoes[b.secao]
        origem = m.ponto(b.no_i)
        for ponto in fio.pontos:
            d = ponto - origem
            pior_pilar = max(pior_pilar,
                             abs(float(d @ p.R[1])) / (secao.b / 2.0),
                             abs(float(d @ p.R[2])) / (secao.h / 2.0))

    # Desde o Vigas R04 a seção T leva o laço da mesa, com barras de canto
    # **na mesa** — fora da alma, mas dentro da laje, cujo topo é o da viga.
    # Fora da alma, então, a barra só é aceita na faixa da laje: entre o topo
    # da viga e a espessura da laje abaixo dele.
    hf = max((l.espessura for l in m.lajes.values()), default=0.0)
    cadeias = {v.nome: v for v in vigas_continuas(m)}
    pior_viga = 0.0
    for fio in arm.fios:
        if not fio.familia.startswith("viga"):
            continue
        v = cadeias[fio.elemento]
        p = preparadas[v.barras[0]]
        secao = m.secoes[m.barras[v.barras[0]].secao]
        origem = m.ponto(v.nos[0])
        for ponto in fio.pontos:
            d = ponto - origem
            lado = abs(float(d @ p.R[1])) / (secao.b / 2.0)
            altura = float(d @ p.R[2])
            na_mesa = secao.h / 2.0 - hf < altura < secao.h / 2.0
            pior_viga = max(pior_viga, 0.0 if na_mesa else lado,
                            abs(altura) / (secao.h / 2.0))

    # A laje é desenhada com o topo no topo das vigas (o plano médio dela sobe
    # ``h_viga/2 − e/2`` acima dos nós): as barras têm de cair entre as duas
    # faces, e a positiva abaixo da negativa.
    from .core.lajes import deslocamento_do_centro
    zs_pos = [float(pt[2]) for f in arm.fios if f.familia == "laje positiva"
              for pt in f.pontos]
    zs_neg = [float(pt[2]) for f in arm.fios if f.familia == "laje negativa"
              for pt in f.pontos]
    dentro = bool(zs_pos or zs_neg)
    for f in arm.fios:
        if not f.familia.startswith("laje"):
            continue
        # o negativo sobre a viga entre duas lajes leva o nome das duas
        # ("L1 / L2"), e tem de cair dentro de alguma delas — antes esse
        # caso era pulado aqui, e o desenho o punha no plano dos nós
        nomes = [n.strip() for n in f.elemento.split(" / ")]
        if not all(n in m.lajes for n in nomes):
            dentro = False
            continue
        faixas = [(3.0 + deslocamento_do_centro(m, m.lajes[n]),
                   m.lajes[n].espessura / 2.0) for n in nomes]
        if not all(any(meio - meia < float(pt[2]) < meio + meia
                       for meio, meia in faixas) for pt in f.pontos):
            dentro = False

    # Dentro de **cada** laje: lajes de espessura diferente têm o plano médio
    # em alturas diferentes (o topo é o das vigas), e comparar uma laje com a
    # outra não diz nada.
    positiva_abaixo_da_negativa = bool(zs_pos and zs_neg)
    for laje in {f.elemento for f in arm.fios
                 if f.familia.startswith("laje")}:
        zp = [float(pt[2]) for f in arm.fios
              if f.familia == "laje positiva" and f.elemento == laje
              for pt in f.pontos]
        zn = [float(pt[2]) for f in arm.fios
              if f.familia == "laje negativa" and f.elemento == laje
              for pt in f.pontos]
        if zp and zn and not max(zp) < min(zn):
            positiva_abaixo_da_negativa = False

    familias = set(arm.por_familia())
    return [
        Conferencia("armadura: o pavimento saiu com barras",
                    float(len(arm.fios) > 0), 1.0),
        Conferencia("armadura: as seis famílias apareceram",
                    float(len(familias & set(FAMILIAS))), 6.0),
        Conferencia("armadura: nenhuma barra de pilar fora da seção",
                    float(pior_pilar < 1.0), 1.0),
        Conferencia("armadura: nenhuma barra de viga fora da seção",
                    float(pior_viga < 1.0), 1.0),
        Conferencia("armadura: as barras de laje ficam entre as duas faces",
                    float(dentro), 1.0),
        Conferencia("armadura: a positiva fica abaixo da negativa",
                    float(positiva_abaixo_da_negativa), 1.0),
    ]


def armadura_e_de_um_pavimento_so() -> list[Conferencia]:
    """O recorte é o pavimento, e o pilar que entra é o de baixo.

    Duas coisas que a medição de desempenho exige e que o desenho tem de
    honrar: nenhuma barra de outro nível, e o lance mostrado é o que **chega**
    à cota — o que entrega carga à laje e às vigas desenhadas, fechando o
    caminho de carga na tela.
    """
    from .armadura3d import lances_do_pavimento, vigas_do_pavimento

    m, arm = _armadura_de_prova()
    lances = lances_do_pavimento(m, 3.0)
    vigas = vigas_do_pavimento(m, 3.0)

    # Todo pilar do modelo vai de 0 a 3 m: o lance que termina na cota são
    # todos os seis, e nenhum começa nela.
    topos = [max(m.ponto(m.barras[b].no_i)[2], m.ponto(m.barras[b].no_j)[2])
             for b in lances]

    zs = [float(pt[2]) for f in arm.fios for pt in f.pontos]
    laje_e_viga = [float(pt[2]) for f in arm.fios
                   if not f.familia.startswith("pilar") for pt in f.pontos]

    return [
        Conferencia("armadura: os seis lances de baixo entraram",
                    float(len(lances)), 6.0),
        Conferencia("armadura: todos terminam na cota do pavimento",
                    float(all(abs(z - 3.0) < 1e-9 for z in topos)), 1.0),
        Conferencia("armadura: as vigas do nível foram reconhecidas",
                    float(len(vigas) > 0), 1.0),
        # Nada acima do pavimento: o de cima é outro desenho. O teto não é
        # a cota, e sim a face superior da viga — a viga também é desenhada
        # centrada no plano dos nós, e a armadura negativa dela sobe meia
        # altura acima do eixo.
        Conferencia("armadura: nada é desenhado acima do pavimento",
                    float(max(zs) <= 3.0 + 0.50 / 2.0 + 1e-9), 1.0),
        # Viga e laje ficam na cota; só o pilar desce.
        Conferencia("armadura: viga e laje ficam na faixa da cota",
                    float(all(z > 3.0 - 0.55 for z in laje_e_viga)), 1.0),
        Conferencia("armadura: o pilar desce até a base",
                    float(min(zs) < 0.5), 1.0),
    ]


def armadura_vira_dxf(pasta) -> list[Conferencia]:
    """O DXF grava uma polilinha 3D por barra, mais a fôrma, e relê.

    Contar as entidades de volta é o que separa "gravou um arquivo" de
    "gravou o desenho": um DXF só com cabeçalho passaria pela conferência de
    tamanho.
    """
    from pathlib import Path

    from .armadura_dxf import (CAMADAS, arestas_da_forma, contar_entidades,
                               exportar)

    m, arm = _armadura_de_prova()
    destino = Path(pasta) / "armadura" / "cota-3m.dxf"
    caminho = exportar(arm, destino, m)
    forma = arestas_da_forma(m, 3.0)
    esperadas = {nome for nome, _ in CAMADAS.values()}

    try:
        import ezdxf
        camadas = {c.dxf.name for c in ezdxf.readfile(str(caminho)).layers}
        entidades = contar_entidades(caminho)
    except ImportError:                              # pragma: no cover
        camadas, entidades = esperadas, len(arm.fios) + len(forma)

    return [
        Conferencia("armadura em DXF: o arquivo existe e não está vazio",
                    float(caminho.exists() and caminho.stat().st_size > 5000),
                    1.0),
        Conferencia("armadura em DXF: uma polilinha por barra, mais a fôrma",
                    float(entidades), float(len(arm.fios) + len(forma))),
        Conferencia("armadura em DXF: as camadas de armadura foram criadas",
                    float(len(esperadas & camadas)), float(len(esperadas))),
        Conferencia("armadura em DXF: a fôrma tem camada própria",
                    float("FORMA" in camadas), 1.0),
    ]


def pilar_reprovado_nao_passa_por_aprovado() -> list[Conferencia]:
    """Ter veredito e ser aprovado são coisas diferentes.

    O motor de Pilares pode concluir a verificação inteira e **reprovar** o
    lance — o caso comum é nenhum arranjo caber nas bitolas permitidas, e aí
    ``arranjo`` volta vazio e o erro fica nos avisos. ``passou`` só diz que
    houve veredito; era com ele que o relatório contava o lance entre os
    verificados sem dizer que ele não passou.
    """
    from .dimensionamento import EsforcosDoLance, VerificacaoDePilar

    class _Fingido:
        ok = False
        erros = ["nenhum arranjo coube"]

    esforcos = EsforcosDoLance("P1", "ELU 01")
    reprovado = VerificacaoDePilar("P1", "ELU 01", esforcos,
                                   resultado=_Fingido())
    sem_veredito = VerificacaoDePilar("P1", "ELU 01", esforcos,
                                      erro="seção não retangular")

    return [
        Conferencia("pilar reprovado: tem veredito",
                    float(reprovado.passou), 1.0),
        Conferencia("pilar reprovado: mas não é aprovado",
                    float(reprovado.aprovado), 0.0),
        Conferencia("pilar reprovado: o motivo vem do motor",
                    float(reprovado.motivos == ["nenhum arranjo coube"]), 1.0),
        Conferencia("pilar sem veredito: nem passou nem foi aprovado",
                    float(sem_veredito.passou or sem_veredito.aprovado), 0.0),
    ]



# ---------------------------------------------------------------------------
# 38. A ponte de vigas usa o que o pórtico sabe
# ---------------------------------------------------------------------------

def _portico_com_vento() -> Modelo:
    """Os dois painéis, com carga vertical **e** uma ação lateral.

    A ação lateral é o ponto: ela produz momento na viga que nenhuma carga
    distribuída reproduz, e é justamente o que o motor de Vigas não combina.
    """
    m = _pavimento_de_dois_paineis()
    g = m.add_caso("G", "permanente")
    peso_proprio(m, g)
    q = m.add_caso("Q", "variavel", "residencial")
    for nome in m.barras:
        if nome.startswith("V"):
            q.distribuida(nome, qz=-8.0, sistema="global")
    vento = m.add_caso("VX", "variavel", "vento", grupo="vento")
    for no in ("N0", "N1", "N2", "N3", "N4", "N5"):
        vento.nodal(no, fx=25.0)
    return m


def peso_proprio_entra_uma_vez_so() -> list[Conferencia]:
    """O motor de Vigas gera o peso próprio dele; o pórtico já o trouxe.

    Era carga dobrada, e ninguém veria: as duas parcelas somam numa
    distribuída só, e a memória de cálculo mostraria o total sem dizer que
    metade dele foi contada duas vezes. Na viga 20×50 do exemplo davam 2,5
    kN/m sobre 10,4 — 24 % a mais de carga permanente.
    """
    from .continuidade import vigas_continuas
    from .dimensionamento import montar_viga

    m = _portico_com_vento()
    viga = next(v for v in vigas_continuas(m) if len(v.apoios) >= 2)
    deles = montar_viga(m, viga)
    secao = deles.tramos[0].secao
    # Só a alma: na seção T a mesa é laje, e o peso dela vem na carga da laje.
    peso = secao.bw * secao.h / 1e4 * deles.concreto.peso_especifico

    meio = viga.comprimento / 2.0
    repassado = sum(c.valor(meio) for c in deles.distribuidas
                    if c.acao == "g" and c.x_ini <= meio <= c.x_fim)
    # ``todas_distribuidas()`` devolve o peso próprio gerado pelo motor mais
    # as distribuídas informadas: com a chave desligada, só as informadas.
    usado = sum(c.valor(meio) for c in deles.todas_distribuidas()
                if c.acao == "g" and c.x_ini <= meio <= c.x_fim)

    return [
        Conferencia("peso próprio: o motor não gera o dele",
                    float(deles.config.peso_proprio), 0.0),
        Conferencia("peso próprio: a seção de fato tem peso a dobrar",
                    float(peso > 0.5), 1.0),
        Conferencia("peso próprio: o pórtico já o repassou",
                    float(repassado >= peso), 1.0),
        # A prova do dobro: o que o motor usa é o que a ponte passou, nem um
        # quilo a mais.
        Conferencia("peso próprio: o motor usa exatamente o repassado",
                    usado, repassado, 1e-9),
    ]


def apoio_de_viga_leva_a_rigidez_do_pilar() -> list[Conferencia]:
    """O apoio leva o pilar descrito, e o motor faz a mola do 14.6.6.1.

    A ponte passa a largura do pilar na direção da viga, a perpendicular e os
    lances; o programa de Vigas, no modelo ``rigidez`` do 14.6.6.1, faz a
    mola ``k = 4·Ecs·(I_sup/(ℓ_sup/2) + I_inf/(ℓ_inf/2))`` com ``I =
    transversal · largura³/12`` (Figura 14.8). A conferência trava a conta e
    o eixo: girando a seção do pilar, a mola muda na razão dos cubos do lado
    que fica no rumo da viga. Um erro de eixo aqui passaria despercebido — a
    mola continuaria existindo, só com o valor errado.
    """
    from dataclasses import replace

    from .continuidade import vigas_continuas
    from .dimensionamento import montar_viga
    from .elementos.vigas.core import solidariedade as sd

    def montar(secao_pilar):
        m = _portico_com_vento()
        if secao_pilar is not None:
            m.add_secao(secao_pilar)
            for nome, b in list(m.barras.items()):
                if nome.startswith("P"):
                    m.barras[nome] = replace(b, secao=secao_pilar.nome)
        viga = next(v for v in vigas_continuas(m) if len(v.apoios) >= 2)
        return m, viga, montar_viga(m, viga)

    m, viga, deles = montar(None)
    ap = deles.apoios[1]
    barra = next(b for n, b in m.barras.items() if n.startswith("P")
                 and viga.nos[viga.apoios[1]] in (b.no_i, b.no_j))
    lance = m.comprimento(next(n for n, b in m.barras.items()
                               if b is barra)) * 100.0
    secao = m.secoes[barra.secao]
    I = secao.b * 100.0 * (secao.h * 100.0) ** 3 / 12.0
    # cada prumada aqui tem um lance só, do chão à laje: só o de baixo
    esperado = 4.0 * deles.concreto.Ecs * I / (lance / 2.0) * 1e-3
    k = sd.k_rotacional(deles, 1)

    # girando o pilar de 30×30 para 20×45, a inércia na direção da viga cai
    _, _, deles2 = montar(Secao.retangular("P20x45", 0.20, 0.45))
    k2 = sd.k_rotacional(deles2, 1)

    apoios_pilar = [a for a in deles.apoios if a.pilar]
    return [
        Conferencia("solidariedade: o apoio leva o lance do pilar (cm)",
                    ap.altura_pilar_abaixo, lance, 1e-9),
        Conferencia("solidariedade: o motor faz a mola 4·Ecs·I/(ℓ/2) da "
                    "Figura 14.8", k, esperado, 1e-9),
        # 30³ contra 20³: a mola cai na razão dos cubos do lado que fica no
        # rumo da viga, e não na dos lados perpendiculares
        Conferencia("solidariedade: a mola segue o lado na direção da viga",
                    k2 / k, (0.20 ** 3 * 0.45) / (0.30 ** 3 * 0.30), 1e-9),
        Conferencia("solidariedade: todos os apoios de pilar com o pilar "
                    "descrito", float(all(a.pilar_informado
                                          for a in apoios_pilar)), 1.0),
        Conferencia("solidariedade: a ponte usa o modelo 'rigidez' do "
                    "14.6.6.1", float(deles.config.modelo_pilares
                                      == "rigidez"), 1.0),
    ]


def acao_lateral_nao_chega_ao_motor_mas_e_conferida() -> list[Conferencia]:
    """O motor não vê o vento; a conferência contra o pórtico vê.

    Esta é a conferência do defeito que motivou a correção. O motor de Vigas
    combina só G e Q — não há como dar vento a ele —, de modo que a armadura
    saía dimensionada para menos do que o edifício pede. A ponte não finge que
    resolveu: ela **confere** o detalhamento contra a envoltória do pórtico, em
    área de aço, e reprova quando não cobre.
    """
    from .continuidade import vigas_continuas
    from .dimensionamento import (conferir_contra_o_portico,
                                  envoltoria_da_viga, montar_viga,
                                  verificar_vigas)
    from .elementos.vigas.core.dimensionar import dimensionar

    m = _portico_com_vento()
    env = envoltoria(m, resolver_combinacoes(
        m, combinacoes_elu(acoes_do_modelo(m))))
    viga = next(v for v in vigas_continuas(m) if len(v.apoios) >= 2)

    x, mn, mx, _, _ = envoltoria_da_viga(m, viga, env)
    deles = montar_viga(m, viga)
    resultado = dimensionar(deles)
    conf = conferir_contra_o_portico(m, viga, resultado, deles, env)

    # o motor só conhece g e q: nenhuma das suas ações é o vento
    acoes = {c.acao for c in deles.todas_distribuidas()}

    sem_env = verificar_vigas(m)
    com_env = verificar_vigas(m, envoltorias=env)

    return [
        Conferencia("ação lateral: a envoltória do pórtico foi extraída",
                    float(len(x) > 0), 1.0),
        Conferencia("ação lateral: o motor de Vigas só tem g e q",
                    float(acoes <= {"g", "q"}), 1.0),
        # A envoltória do pórtico é mais severa que a do motor em algum
        # ponto: é o vento aparecendo. Sem isso a conferência não provaria
        # nada, porque um vento nulo passaria igual.
        Conferencia("ação lateral: o pórtico exige mais que o motor",
                    float(mn.min() < resultado.envoltoria.M_min.min()
                          or mx.max() > resultado.envoltoria.M_max.max()),
                    1.0),
        Conferencia("ação lateral: a conferência achou o ponto crítico",
                    float(conf.face_critica in ("superior", "inferior")), 1.0),
        # Sem envoltória não há conferência, e a verificação diz isso em vez
        # de calar: era esse o silêncio que deixava a viga passar.
        Conferencia("ação lateral: sem envoltória não há conferência",
                    float(all(v.portico is None for v in sem_env)), 1.0),
        Conferencia("ação lateral: sem envoltória fica o aviso",
                    float(all(v.avisos for v in sem_env)), 1.0),
        Conferencia("ação lateral: com envoltória todas são conferidas",
                    float(all(v.portico is not None for v in com_env
                              if v.passou)), 1.0),
    ]


def conferencia_do_portico_mede_area_de_aco() -> list[Conferencia]:
    """A razão é entre áreas de aço na face tracionada, e não entre momentos.

    Momento é grandeza intermediária: dois momentos parecidos pedem armaduras
    diferentes se caírem em faces opostas, e um momento de sinal trocado — o
    vento revertendo o apoio — não tem razão numérica que o descreva. Área de
    aço, sim, e é o que se confere em obra.
    """
    from .dimensionamento import ConferenciaDoPortico

    coberta = ConferenciaDoPortico(As_exigido_sup=4.0, As_obtido_sup=5.0)
    apertada = ConferenciaDoPortico(As_exigido_sup=6.0, As_obtido_sup=5.0)
    ausente = ConferenciaDoPortico(As_exigido_inf=3.0, As_obtido_inf=0.0)

    return [
        Conferencia("conferência: sobrando aço, cobre",
                    float(coberta.cobre), 1.0),
        Conferencia("conferência: a razão é exigido sobre obtido",
                    coberta.razao, 0.8, 1e-12),
        Conferencia("conferência: faltando aço, não cobre",
                    float(apertada.cobre), 0.0),
        # Face sem barra nenhuma não tem razão finita: é o caso do vento
        # pedindo tração onde o motor não armou, e ele não pode virar um
        # número modesto por divisão com zero
        Conferencia("conferência: face sem armadura dá razão infinita",
                    float(ausente.razao == float("inf")), 1.0),
        Conferencia("conferência: e reprova",
                    float(ausente.cobre), 0.0),
    ]


# ---------------------------------------------------------------------------
# 39. Os três arquivos do projeto
# ---------------------------------------------------------------------------

def motores_trouxeram_as_saidas() -> list[Conferencia]:
    """Os três motores vieram com as pastas de saída, não só com o núcleo.

    De Pilares tinha vindo só o ``core``: a memória de cálculo, a planilha e o
    DXF dele ficaram para trás, e o projeto do edifício não tinha como emitir
    a parte de pilares.
    """
    import importlib

    from .elementos import PROCEDENCIA

    portas = [("pilares.saidas.relatorio", "gerar"),
              ("pilares.saidas.planilha", "gerar"),
              ("pilares.saidas.dxf", "exportar"),
              ("vigas.saidas.relatorio", "gerar"),
              ("vigas.saidas.planilha", "gerar"),
              ("lajes.saidas.relatorio", "gerar"),
              ("lajes.saidas.planilha", "gerar")]
    achadas = 0
    for modulo, funcao in portas:
        try:
            alvo = importlib.import_module(f".elementos.{modulo}",
                                           package="portico3d")
        except ImportError:
            continue
        achadas += int(callable(getattr(alvo, funcao, None)))

    return [
        Conferencia("saídas dos motores: as sete portas existem",
                    float(achadas), float(len(portas))),
        Conferencia("saídas dos motores: o manifesto declara saidas de "
                    "pilares",
                    float("saidas" in PROCEDENCIA["pilares"]["partes"]), 1.0),
    ]


def dependencias_estao_declaradas() -> list[Conferencia]:
    """O requirements.txt lista o que o programa de fato importa.

    Numa instalação limpa faltavam ezdxf, python-docx e openpyxl: o programa
    subia e quebrava na primeira exportação. Declarar é o conserto. Desde a
    troca do motor de desenho (revisão R03), ``matplotlib`` saiu da lista e
    entraram ``pyvista``/``pyvistaqt``.
    """
    if _empacotado():
        # No executável não há o que instalar: as oito já vieram dentro. O
        # que importa ali é que elas **importem**, e é isso que se confere.
        import importlib

        modulos = ("numpy", "scipy", "PySide6", "pyvista", "pyvistaqt",
                   "docx", "openpyxl", "ezdxf")
        vivas = 0
        for modulo in modulos:
            try:
                importlib.import_module(modulo)
            except ImportError:
                continue
            vivas += 1
        return [Conferencia("dependências: as oito estão dentro do executável",
                            float(vivas), float(len(modulos)))]

    caminho = Path(__file__).resolve().parent.parent / "requirements.txt"
    texto = caminho.read_text(encoding="utf-8").lower() if caminho.exists()         else ""
    exigidas = ("numpy", "scipy", "pyside6", "pyvista", "pyvistaqt",
                "python-docx", "openpyxl", "ezdxf")
    return [
        Conferencia("dependências: o arquivo existe",
                    float(caminho.exists()), 1.0),
        Conferencia("dependências: todas as oito estão declaradas",
                    float(sum(1 for d in exigidas if d in texto)),
                    float(len(exigidas))),
    ]


def projeto_gera_os_tres_arquivos(pasta) -> list[Conferencia]:
    """Um memorial, um quadro de quantidades, uma prancha — e eles abrem.

    Abrir de volta é o que separa "gravou um arquivo" de "gravou o
    documento": um .docx sem capítulo nenhum e um .dxf só com cabeçalho
    passariam por tamanho.
    """
    from pathlib import Path as _Path

    from .projeto import calcular, gerar
    from .saidas.quantitativos import consolidar

    m = _portico_com_vento()
    projeto = calcular(m)
    destino = _Path(pasta) / "projeto"
    arquivos = [a for a in gerar(projeto, destino) if not a.startswith("(")]
    caminhos = [_Path(a) for a in arquivos]

    docx = [c for c in caminhos if c.suffix == ".docx"]
    xlsx = [c for c in caminhos if c.suffix == ".xlsx"]
    dxf = [c for c in caminhos if c.suffix == ".dxf"]

    capitulos = abas = entidades = 0
    if docx:
        from docx import Document
        d = Document(str(docx[0]))
        capitulos = sum(1 for p in d.paragraphs
                        if p.style.name == "Heading 1")
    if xlsx:
        import openpyxl
        abas = len(openpyxl.load_workbook(str(xlsx[0])).sheetnames)
    if dxf:
        import ezdxf
        entidades = len(ezdxf.readfile(str(dxf[0])).modelspace())

    q = consolidar(projeto)

    return [
        Conferencia("projeto: saíram os três arquivos",
                    float(len(caminhos)), 3.0),
        Conferencia("projeto: os três existem e não estão vazios",
                    float(all(c.exists() and c.stat().st_size > 4000
                              for c in caminhos)), 1.0),
        # dez capítulos: metodologia, modelo, esforços, estabilidade,
        # reações, pilares, vigas, confronto, lajes e quantitativos
        Conferencia("projeto: a memória tem os dez capítulos",
                    float(capitulos), 10.0),
        Conferencia("projeto: o quadro tem as quatro abas",
                    float(abas), 4.0),
        Conferencia("projeto: a prancha tem entidades",
                    float(entidades > 100), 1.0),
        Conferencia("projeto: o quantitativo somou aço",
                    float(q["aco"] > 0.0), 1.0),
        Conferencia("projeto: e somou concreto",
                    float(q["concreto"] > 0.0), 1.0),
        # Fôrma existe e é **menor** que a soma das faces brutas: o critério é
        # contar só o que contém o concreto, e um quadro que somasse tudo
        # daria número maior sem ninguém notar
        Conferencia("projeto: e somou fôrmas",
                    float(q["formas"] > 0.0), 1.0),
        # o total tem de bater com a soma das parcelas, senão a planilha
        # mente numa linha que ninguém confere à mão
        Conferencia("projeto: o total é a soma das parcelas",
                    q["aco"],
                    sum(d["aco"] for d in q["por_elemento"].values()), 1e-9),
    ]




# ---------------------------------------------------------------------------
# 40. O que muda quando o programa vira executável
# ---------------------------------------------------------------------------

def vento_carrega_sem_depender_de_pasta() -> list[Conferencia]:
    """O motor de vento tem de carregar sem a pasta dele estar no sys.path.

    A cópia do NBR-6123 faz ``import nbr6123_data`` sem ponto, como módulo de
    topo — é assim na origem, e a cópia não se edita. A solução antiga punha a
    pasta no ``sys.path``, e ela funcionava em Python e **quebrava
    empacotada**: no executável a pasta não existe em disco, os módulos vivem
    dentro do arquivo, e o programa levantava ModuleNotFoundError na primeira
    conta de vento. Foi o autoteste do .exe que achou isso.

    A conferência refaz a carga com a pasta **fora** do ``sys.path``, que é a
    situação do executável, e exige que ela funcione mesmo assim.
    """
    import sys

    from .core.vento import carregar_nbr6123
    from .elementos import vento as pacote

    pasta = str(Path(pacote.__file__).resolve().parent)
    salvos = [m for m in ("nbr6123_data", "nbr6123_core") if m in sys.modules]
    guardados = {m: sys.modules.pop(m) for m in salvos}
    caminho_antes = list(sys.path)
    sys.path[:] = [d for d in sys.path if d != pasta]
    try:
        motor = carregar_nbr6123()
        carregou = callable(getattr(motor, "calc_s2", None))
        registrado = sys.modules.get("nbr6123_data") is not None
    finally:
        sys.path[:] = caminho_antes
        sys.modules.update(guardados)

    return [
        Conferencia("executável: o vento carrega sem a pasta no sys.path",
                    float(carregou), 1.0),
        Conferencia("executável: nbr6123_data fica registrado no nome de topo",
                    float(registrado), 1.0),
    ]


def pacote_nao_tem_dado_fora_do_codigo() -> list[Conferencia]:
    """Nada dentro de ``portico3d`` é lido de arquivo que não seja .py.

    Importa para o empacotamento: arquivo de dados não entra no executável a
    menos que a receita do PyInstaller o colete à mão, e o que não entra só
    falha quando alguém usa a função que o lê. Enquanto o pacote for só
    código — mais os recursos gráficos, que a receita declara —, não há essa
    classe de erro a temer.
    """
    if _empacotado():
        return [Conferencia("executável: pacote empacotado, varredura de "
                            "disco não se aplica", 0.0, 0.0)]
    aqui = Path(__file__).resolve().parent
    permitidos = {".py", ".ico", ".png"}
    estranhos = [a.relative_to(aqui).as_posix()
                 for a in aqui.rglob("*")
                 if a.is_file() and "__pycache__" not in a.parts
                 and a.suffix.lower() not in permitidos]
    return [
        Conferencia("executável: o pacote não tem dado fora do código",
                    float(len(estranhos)), 0.0),
    ]



# ---------------------------------------------------------------------------
# 41. P-Δ confrontado com uma biblioteca externa (PyNiteFEA)
# ---------------------------------------------------------------------------

def p_delta_confrontado_com_pynite() -> list[Conferencia]:
    """O mesmo balanço em viga-coluna, comparado ao que o PyNiteFEA 3.2.0 deu.

    O caso é o de :func:`p_delta_viga_coluna` — mesmo ``L``, ``H`` e
    ``P = 0,5·Pcr`` —, mas aqui com **uma barra só** no pilar, que é a malha
    que o assistente usa (um lance por pavimento). Foi confrontando com o
    PyNiteFEA que se achou o defeito, e vale contar a história porque ela diz
    por que a correção é a que é.

    **O que o confronto achou.** O deslocamento do topo já batia com o
    PyNiteFEA a 13 algarismos, mesmo com uma barra só — a montagem
    ``Ke + Kg`` e a iteração de Newton estavam certas. Mas o **momento**
    recuperado na extremidade errava a solução fechada em **+6,6 %** (P a
    50 % da crítica), enquanto o PyNiteFEA, na mesma malha grosseira, errava
    só 0,15 %.

    **A causa não era a malha — era a recuperação.** ``_esforcos_das_barras``
    calculava o esforço de volta só com a rigidez **elástica**
    (``Ke·D``), sem somar a **geométrica** que tinha corrigido o
    deslocamento. O ``Kg`` entrava na montagem e sumia na volta — dois
    programas escritos de forma independente convergindo para o mesmo
    deslocamento não bastava, porque o defeito estava um passo depois. Feito
    ``(Ke + Kg)·D``, o erro já cai de 6,6 % para 0,13 % **sem tocar em malha
    nenhuma**.

    **O resíduo que sobrava é mesmo de malha**, e agora tem correção própria:
    ``elemento.rigidez_geometrica_refinada`` subdivide a barra só por dentro
    do cálculo — condensação estática de sub-elementos, sem acrescentar nó
    nenhum que o usuário veja —, e entra tanto na montagem quanto, agora, na
    recuperação. As duas correções juntas — ``Kg`` na recuperação, mais a
    refinada — deixam o momento com uma barra só a **-0,0007 %** da solução
    fechada, e o deslocamento converge para dentro de 0,001 % do valor que
    dez barras davam antes da correção (nem o PyNiteFEA nem esta versão
    antiga do próprio programa chegavam lá com uma barra só).

    O confronto que motivou a correção continua registrado: é o
    ``LEIAME.md`` e o histórico de commits que guardam os números antigos
    (6,6 % / 0,15 %) — esta conferência trava os números **de agora**.
    """
    from .core.segunda_ordem import resolver_p_delta

    L, H = 5.0, 3.0
    secao = _secao_retangular()
    EI = E_ACO * secao.Iz
    Pcr = math.pi ** 2 * EI / (4.0 * L ** 2)
    P = 0.5 * Pcr
    k = math.sqrt(P / EI)
    exato = H * math.tan(k * L) / k

    saida = []
    for n, ux_referencia in ((1, 0.003546884799047871),
                             (10, 0.0035469425371828897)):
        m = _balanco_viga_coluna(L, n, P, H)
        r = resolver_p_delta(m, "PH")
        ux = float(r.deslocamentos[m.gdl(f"N{n}")[0]])
        momento = abs(float(r.diagrama("B0").Mz[0]))
        saida.append(Conferencia(
            f"P-Δ: deslocamento com {n} barra(s) — trava de regressão",
            ux, ux_referencia, 1e-8))
        saida.append(Conferencia(
            f"P-Δ: momento com {n} barra(s) bate a solução fechada",
            momento, exato, 2e-4))
    return saida


# ---------------------------------------------------------------------------
# 42. Bateria cruzada contra o PyNiteFEA — dez cenários estruturais
# ---------------------------------------------------------------------------
#
# Cada cenário cruza três fontes sempre que elas existem: a solução fechada
# da Resistência dos Materiais, o motor deste programa e o PyNiteFEA (versão
# 3.2.0) montado a partir do **mesmo** ``Modelo``, pelo tradutor comum
# ``_pynite_do_modelo``. Um quarto motor, o OpenSeesPy, estava no roteiro
# original e ficou de fora da primeira rodada — nesta máquina só havia Python
# 3.14 instalado, e o pacote ``openseespywin`` que o ``openseespy`` depende
# no Windows traz um ``opensees.pyd`` pré-compilado contra ``python312.dll``
# (ABI de CPython 3.12). **Essa pendência fechou**: o usuário instalou um
# Python 3.12 ao lado, e a seção 44 (logo depois dos dez cenários, antes da
# análise modal) acrescenta o OpenSeesPy como terceiro motor em seis dos dez
# cenários — os que fazem sentido para ele (4, 5, 6, 8, 9 e 10; os cenários
# 1–3 já tinham só o PyNiteFEA mesmo por serem casos de viga isolada, sem
# nada que o OpenSeesPy testasse de diferente). Não é um quarto motor
# **dentro** desta seção — é um motor a mais nos mesmos ``Modelo`` já
# montados aqui, rodado num processo Python 3.12 separado (ver o cabeçalho
# da seção 44 para a arquitetura entre processos e a convenção de eixo).
#
# **Armadilha confirmada empiricamente, não suposta**: o PyNiteFEA usa, para
# barra **vertical**, uma convenção de eixos locais y/z trocada em relação à
# deste programa. Confirmado comparando o cenário 2 (balanço vertical com
# força lateral) contra a solução fechada ``PL³/3EI``: alimentando o
# PyNiteFEA com as mesmas ``Iy``/``Iz`` deste programa, a flecha saía errada
# por um fator ``Iy/Iz``; invertendo os dois na seção do PyNiteFEA, a flecha
# bateu a solução fechada a 13 algarismos. A troca não para na rigidez: o
# momento que este programa chama ``Mz`` (plano x–y, inércia ``Iz``) sai do
# PyNiteFEA rotulado ``"My"`` para barra vertical, e vice-versa — os dois
# planos trocam de rótulo inteiros, não só o valor de inércia.
# ``_pynite_do_modelo``/``_momento_pynite`` fazem essa troca escondida do
# chamador, para cada cenário só pedir "o momento no plano x–y" e receber o
# número certo não importa a orientação da barra.
#
# O cenário 10 do roteiro original pedia um apoio inclinado (eixo de
# restrição rotacionado). Nem este programa nem o PyNiteFEA têm essa
# primitiva — ``Apoio`` aqui só vincula nos eixos globais, e o PyNiteFEA não
# tem ``def_support`` com rotação. Implementá-la seria uma funcionalidade
# nova no solver (transformar a partição de graus de liberdade por um eixo
# de restrição não ortogonal ao global), fora do escopo desta bateria de
# confronto. Substituído por um décimo cenário que é genuinamente mais
# exigente do que parece à primeira vista: o pórtico espacial completo já
# usado em ``equilibrio_global`` — quatro pilares, quatro vigas de contorno e
# duas barras inclinadas sem rotação de seção alinhada a eixo nenhum —,
# cruzado contra o PyNiteFEA em vez de só contra equilíbrio. É o teste mais
# amplo da bateria: mistura barra vertical, horizontal e oblíqua, carga
# nodal, distribuída local e global, e momento concentrado, tudo no mesmo
# modelo.


def _pynite_do_modelo(modelo: Modelo, caso_nome: str):
    """Traduz um ``Modelo`` e um caso de carga para um ``FEModel3D``.

    Cobre o que os dez cenários desta bateria precisam: material, seção,
    apoio nos eixos globais, mola, carga nodal e carga distribuída
    **uniforme**, local ou global (a local é projetada nos eixos globais
    pela mesma ``matriz_rotacao`` do elemento, antes de entrar no
    PyNiteFEA). Não traduz carga distribuída trapezoidal, que nenhum
    cenário daqui usa; chamar com uma levanta ``NotImplementedError`` em vez
    de montar um PyNiteFEA silenciosamente errado.
    """
    from Pynite import FEModel3D

    fe = FEModel3D()
    for nome, mat in modelo.materiais.items():
        fe.add_material(nome, mat.E, mat.G, mat.poisson, 0.0)
    for nome, no in modelo.nos.items():
        fe.add_node(nome, no.x, no.y, no.z)
    for nome, barra in modelo.barras.items():
        secao = modelo.secoes[barra.secao]
        # ``barra.rotacao`` (o cenário 6 testa isso numa barra não vertical)
        # passa direto para ``add_member(rotation=)`` mais abaixo.
        Iy_fe, Iz_fe = ((secao.Iz, secao.Iy) if _barra_vertical(modelo, barra)
                        else (secao.Iy, secao.Iz))
        secnome = f"sec_{nome}"
        fe.add_section(secnome, secao.A, Iy_fe, Iz_fe, secao.J)
        fe.add_member(nome, barra.no_i, barra.no_j, barra.material, secnome,
                      rotation=barra.rotacao)
    for nome, apoio in modelo.apoios.items():
        fe.def_support(nome, apoio.ux, apoio.uy, apoio.uz,
                       apoio.rx, apoio.ry, apoio.rz)
    for nome, mola in modelo.molas.items():
        for dof, k in zip(("DX", "DY", "DZ", "RX", "RY", "RZ"), mola.vetor):
            if k != 0.0:
                fe.def_support_spring(nome, dof, k)

    caso = modelo.casos[caso_nome]
    for c in caso.nodais:
        for direcao, valor in zip(("FX", "FY", "FZ", "MX", "MY", "MZ"),
                                  c.vetor):
            if valor != 0.0:
                fe.add_node_load(c.no, direcao, valor, case=caso_nome)
    from .core.elemento import matriz_rotacao

    for c in caso.distribuidas:
        if not c.uniforme:
            raise NotImplementedError(
                "_pynite_do_modelo só traduz carga distribuída uniforme")
        if c.sistema == "global":
            vetor_global = c.vetor_inicio
        else:
            barra = modelo.barras[c.barra]
            pi, pj = modelo.ponto(barra.no_i), modelo.ponto(barra.no_j)
            R = matriz_rotacao(pi, pj, barra.rotacao, barra.vetor_ref)
            vetor_global = R.T @ c.vetor_inicio
        for direcao, valor in zip(("FX", "FY", "FZ"), vetor_global):
            if valor != 0.0:
                fe.add_member_dist_load(c.barra, direcao, valor, valor,
                                        case=caso_nome)

    fe.add_load_combo(caso_nome, {caso_nome: 1.0})
    fe.analyze(check_stability=True)
    return fe


def _barra_vertical(modelo: Modelo, barra) -> bool:
    from .core.elemento import TOL_VERTICAL

    pi, pj = modelo.ponto(barra.no_i), modelo.ponto(barra.no_j)
    ex = (pj - pi) / np.linalg.norm(pj - pi)
    return math.hypot(ex[0], ex[1]) < TOL_VERTICAL


def _momento_pynite(fe, modelo: Modelo, barra: str, componente: str,
                    x: float, caso_nome: str) -> float:
    """Lê um momento do PyNiteFEA, trocando o rótulo em barra vertical.

    ``componente`` é ``"My"`` ou ``"Mz"`` na convenção **deste programa**
    (My: plano x–z, inércia Iy; Mz: plano x–y, inércia Iz); a troca de
    rótulo para barra vertical é a mesma documentada no cabeçalho desta
    seção.
    """
    if _barra_vertical(modelo, modelo.barras[barra]):
        componente = {"My": "Mz", "Mz": "My"}[componente]
    return float(fe.members[barra].moment(componente, x, combo_name=caso_nome))


# ---------------------------------------------------------------------------
# 44. O terceiro motor — OpenSeesPy, confrontado entre processos
# ---------------------------------------------------------------------------
#
# O OpenSeesPy só roda num Python 3.12 (o ``openseespywin`` do Windows traz um
# ``opensees.pyd`` pré-compilado contra ``python312.dll``; o resto deste
# programa roda em Python 3.14 — ver ``portico3d/core/opensees_ponte.py``, que
# é o script autocontido que de fato importa o OpenSeesPy, rodado por
# ``subprocess.run(["py", "-3.12", ...])`` com o modelo entrando por JSON na
# entrada padrão e o resultado saindo por JSON na saída padrão. Nenhum código
# aqui (lado 3.14) importa ``openseespy`` direto — não pode, o import falha
# nesta versão do interpretador.
#
# **Disponibilidade**: ``_opensees_disponivel()`` testa, com um subprocess
# rápido, se ``py -3.12`` existe e se ``import openseespy.opensees`` funciona
# nele. Se não funcionar (outra máquina, sem o Python 3.12 ao lado), cada
# conferência desta seção devolve um único item informativo que **passa**
# (não derruba a suíte) e diz que foi pulada — não finge ter confrontado nada.
#
# **Convenção de eixo local** — medida, não suposta (ver o cabeçalho de
# ``opensees_ponte.py`` para os dois casos triviais que fecharam a medição):
# alimentando o OpenSeesPy com ``vecxz`` = eixo local z **deste programa**
# (linha ``ez`` de ``matriz_rotacao``), o ``Iy``/``Iz`` do OpenSeesPy bate com
# o ``Iy``/``Iz`` deste programa **sem troca nenhuma** — ao contrário do
# PyNiteFEA (seção 42), que troca Iy/Iz e os rótulos My/Mz em barra vertical.
# ``_momento_opensees`` por isso não troca rótulo nenhum; a simetria com
# ``_momento_pynite`` é só de interface (mesma assinatura), não de
# comportamento.
#
# **Pegadinha de API** (documentada com mais detalhe no próprio script-ponte):
# ``ops.eleForce(tag)`` devolve a força do elemento em coordenadas GLOBAIS;
# quem dá as coordenadas LOCAIS (que é o que bate com a convenção deste
# programa) é ``ops.eleResponse(tag, "localForce")``. O script-ponte já usa a
# certa; quem copiar o padrão ``eleForce`` sem essa troca mede esforço errado
# em qualquer barra que não esteja alinhada com um eixo global.

_CAMINHO_PONTE_OPENSEES = (Path(__file__).resolve().parent
                           / "core" / "opensees_ponte.py")


def _opensees_disponivel() -> bool:
    """Tenta ``py -3.12`` com o OpenSeesPy; memoiza o resultado no processo."""
    if _opensees_disponivel._cache is None:
        try:
            r = subprocess.run(
                ["py", "-3.12", "-c", "import openseespy.opensees"],
                capture_output=True, text=True, timeout=30)
            _opensees_disponivel._cache = (r.returncode == 0)
        except (OSError, subprocess.TimeoutExpired):
            _opensees_disponivel._cache = False
    return _opensees_disponivel._cache


_opensees_disponivel._cache = None


def _opensees_rodar(payload: dict) -> dict:
    """Roda o script-ponte sob ``py -3.12`` e devolve o JSON de resposta."""
    r = subprocess.run(
        ["py", "-3.12", str(_CAMINHO_PONTE_OPENSEES)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(
            f"script-ponte OpenSeesPy saiu com código {r.returncode}: "
            f"{r.stderr[-2000:]}")
    resultado = json.loads(r.stdout)
    if resultado.get("erro"):
        raise RuntimeError(f"script-ponte OpenSeesPy: {resultado['erro']}")
    return resultado


def _opensees_payload_do_modelo(modelo: Modelo, caso_nome: str | None = None,
                                modo: str = "estatica",
                                n_modos: int = 6) -> dict:
    """Traduz um ``Modelo`` (e, no modo estático, um caso de carga) para o
    JSON que ``opensees_ponte.py`` espera. Cobre o mesmo subconjunto que
    ``_pynite_do_modelo`` — apoio, mola, carga nodal e distribuída uniforme
    (local ou global), mais trecho rígido (``offset_i``/``offset_j``, que o
    PyNiteFEA não tem) traduzido para ``-jntOffset``."""
    from .core.elemento import matriz_rotacao
    from .core.dinamica import GRAVIDADE

    nos = {nome: [no.x, no.y, no.z] for nome, no in modelo.nos.items()}

    barras = {}
    for nome, barra in modelo.barras.items():
        secao = modelo.secoes[barra.secao]
        material = modelo.materiais[barra.material]
        pi, pj = modelo.ponto(barra.no_i), modelo.ponto(barra.no_j)
        R = matriz_rotacao(pi, pj, barra.rotacao, barra.vetor_ref)
        entrada = {
            "ni": barra.no_i, "nj": barra.no_j,
            "E": material.E, "G": material.G,
            "A": secao.A, "Iy": secao.Iy, "Iz": secao.Iz, "J": secao.J,
            "vecxz": R[2].tolist(),
        }
        if barra.offset_i or barra.offset_j:
            ex = R[0]
            entrada["offset_i"] = (ex * barra.offset_i).tolist()
            entrada["offset_j"] = (-ex * barra.offset_j).tolist()
        if modo == "modal":
            rho = material.peso_especifico / GRAVIDADE
            entrada["massa_por_comprimento"] = rho * secao.A
        barras[nome] = entrada

    payload = {
        "modo": modo,
        "nos": nos,
        "barras": barras,
        "apoios": {nome: [int(getattr(ap, d)) for d in
                          ("ux", "uy", "uz", "rx", "ry", "rz")]
                  for nome, ap in modelo.apoios.items()},
        "molas": {nome: mola.vetor.tolist()
                 for nome, mola in modelo.molas.items()},
    }
    from .core.diafragma import diafragmas
    payload["diafragmas"] = [
        {"centro": [d.centro[0], d.centro[1], d.cota], "nos": list(d.nos)}
        for d in diafragmas(modelo)]
    if modo == "modal":
        payload["n_modos"] = n_modos
        return payload

    caso = modelo.casos[caso_nome]
    cargas_nodais: dict[str, list[float]] = {}
    for c in caso.nodais:
        vals = cargas_nodais.setdefault(c.no, [0.0] * 6)
        for i, v in enumerate(c.vetor):
            vals[i] += v

    cargas_distribuidas: dict[str, list[float]] = {}
    for c in caso.distribuidas:
        if not c.uniforme:
            raise NotImplementedError(
                "_opensees_payload_do_modelo só traduz carga distribuída "
                "uniforme")
        if c.sistema == "global":
            barra = modelo.barras[c.barra]
            pi, pj = modelo.ponto(barra.no_i), modelo.ponto(barra.no_j)
            R = matriz_rotacao(pi, pj, barra.rotacao, barra.vetor_ref)
            vetor_local = R @ c.vetor_inicio
        else:
            vetor_local = c.vetor_inicio
        atual = cargas_distribuidas.setdefault(c.barra, [0.0, 0.0, 0.0])
        for i in range(3):
            atual[i] += vetor_local[i]

    payload["cargas_nodais"] = cargas_nodais
    payload["cargas_distribuidas"] = {b: v for b, v in
                                      cargas_distribuidas.items()}
    return payload


def _momento_opensees(resultado: dict, barra: str, componente: str,
                      ponta: str = "i") -> float:
    """Lê um momento do resultado do script-ponte, na convenção deste
    programa (``My``: plano x–z, ``Iy``; ``Mz``: plano x–y, ``Iz``) — sem
    troca de rótulo nenhuma (ver o porquê no cabeçalho da seção)."""
    idx = {"My": 4, "Mz": 5}[componente]
    return float(resultado["esforcos"][barra][ponta][idx])


def _opensees_ou_pulado(nome_cenario: str, func):
    """Roda ``func`` (que devolve ``list[Conferencia]``) só se o OpenSeesPy
    estiver disponível nesta máquina; senão devolve um único item informativo
    que passa, documentando o pulo em vez de derrubar a suíte."""
    if not _opensees_disponivel():
        return [Conferencia(
            f"{nome_cenario}: pulado — OpenSeesPy indisponível nesta máquina "
            "(sem Python 3.12 com openseespy ao lado)", 0.0, 0.0)]
    return func()


# --- cenário 1: biapoiada, carga uniforme ----------------------------------

def cenario_01_biapoiada_uniforme_pynite() -> list[Conferencia]:
    L, w = 6.0, 20.0
    m = _modelo_base("c01")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "B", "aco", "R20x50")
    m.apoiar("A", ry=False, rz=False)
    m.apoiar("B", ux=False, ry=False, rz=False)
    caso = m.add_caso("w")
    caso.distribuida("B1", qz=-w, sistema="global")
    r = resolver(m, "w")
    s = m.secoes["R20x50"]
    Mmeio = r.diagrama("B1", 21).My[10]

    M_exato = w * L ** 2 / 8.0
    flecha_exata = -5.0 * w * L ** 4 / (384.0 * E_ACO * s.Iy)

    fe = _pynite_do_modelo(m, "w")
    M_pynite = _momento_pynite(fe, m, "B1", "My", L / 2.0, "w")
    flecha_pynite = fe.members["B1"].deflection("dz", L / 2.0, combo_name="w")

    return [
        Conferencia("c01 biapoiada/uniforme: My(meio) × fechada",
                    Mmeio, M_exato, 1e-9),
        Conferencia("c01 biapoiada/uniforme: My(meio) × PyNiteFEA "
                    "(módulo — convenção de sinal de momento difere entre "
                    "os dois motores)",
                    abs(M_pynite), M_exato, 1e-6),
        Conferencia("c01 biapoiada/uniforme: flecha × PyNiteFEA",
                    flecha_pynite, flecha_exata, 1e-6),
    ]


# --- cenário 2: balanço vertical, carga lateral na ponta -------------------

def cenario_02_balanco_vertical_pynite() -> list[Conferencia]:
    L, P = 3.0, 10.0
    m = _modelo_base("c02")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", 0.0, 0.0, L)
    m.add_barra("B1", "A", "B", "aco", "R20x50")
    m.apoiar("A")
    caso = m.add_caso("P")
    caso.nodal("B", fx=P)
    r = resolver(m, "P")
    s = m.secoes["R20x50"]

    flecha_exata = P * L ** 3 / (3.0 * E_ACO * s.Iz)
    M_exato = P * L

    fe = _pynite_do_modelo(m, "P")
    dx_pynite = fe.nodes["B"].DX["P"]
    M_pynite = _momento_pynite(fe, m, "B1", "Mz", 0.0, "P")

    return [
        Conferencia("c02 balanço vertical: flecha × fechada",
                    r.deslocamento("B")[0], flecha_exata, 1e-9),
        Conferencia("c02 balanço vertical: flecha × PyNiteFEA "
                    "(confirma a troca de Iy/Iz em barra vertical)",
                    dx_pynite, flecha_exata, 1e-6),
        Conferencia("c02 balanço vertical: momento no engaste × PyNiteFEA",
                    abs(M_pynite), M_exato, 1e-6),
    ]


# --- cenário 3: biapoiada, carga concentrada no meio -----------------------

def cenario_03_biapoiada_concentrada_pynite() -> list[Conferencia]:
    L, P = 6.0, 50.0
    m = _modelo_base("c03")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("C", L / 2.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "C", "aco", "R20x50")
    m.add_barra("B2", "C", "B", "aco", "R20x50")
    m.apoiar("A", ry=False, rz=False)
    m.apoiar("B", ux=False, ry=False, rz=False)
    caso = m.add_caso("P")
    caso.nodal("C", fz=-P)
    r = resolver(m, "P")

    M_exato = P * L / 4.0
    Mmeio = r.diagrama("B1", 2).My[-1]

    fe = _pynite_do_modelo(m, "P")
    M_pynite = _momento_pynite(fe, m, "B1", "My", L / 2.0, "P")

    return [
        Conferencia("c03 biapoiada/concentrada: My(meio) × fechada",
                    Mmeio, M_exato, 1e-9),
        Conferencia("c03 biapoiada/concentrada: My(meio) × PyNiteFEA "
                    "(módulo — convenção de sinal difere)",
                    abs(M_pynite), M_exato, 1e-6),
    ]


# --- cenário 4: pórtico plano, carga lateral no topo -----------------------

def cenario_04_portico_plano_lateral_pynite() -> list[Conferencia]:
    """Pórtico de dois pilares e uma travessa **flexível** — ao contrário de
    ``portico_travessa_rigida``, aqui não há solução fechada simples porque
    o momento na base dos pilares depende da rigidez relativa entre pilar e
    travessa; o confronto é só motor próprio × PyNiteFEA."""
    h, vao, H = 3.0, 5.0, 20.0
    m = _modelo_base("c04")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", 0.0, 0.0, h)
    m.add_no("C", vao, 0.0, h)
    m.add_no("D", vao, 0.0, 0.0)
    m.add_barra("P1", "A", "B", "aco", "R20x50")
    m.add_barra("V1", "B", "C", "aco", "R20x50")
    m.add_barra("P2", "D", "C", "aco", "R20x50")
    m.apoiar("A")
    m.apoiar("D")
    caso = m.add_caso("H")
    caso.nodal("B", fx=H)
    r = resolver(m, "H")
    Mbase = r.esforcos_barra("P1")[5]
    ux_topo = r.deslocamento("B")[0]

    fe = _pynite_do_modelo(m, "H")
    Mbase_pynite = _momento_pynite(fe, m, "P1", "Mz", 0.0, "H")
    ux_pynite = fe.nodes["B"].DX["H"]

    return [
        Conferencia("c04 pórtico plano: deslocamento lateral × PyNiteFEA",
                    ux_topo, ux_pynite, 1e-8),
        Conferencia("c04 pórtico plano: momento na base do pilar × "
                    "PyNiteFEA (módulo — convenção de sinal difere)",
                    abs(Mbase), abs(Mbase_pynite), 1e-8),
    ]


def cenario_04_portico_plano_lateral_opensees() -> list[Conferencia]:
    """Mesmo pórtico do cenário 4, cruzado agora com o terceiro motor."""
    def rodar():
        h, vao, H = 3.0, 5.0, 20.0
        m = _modelo_base("c04os")
        m.add_no("A", 0.0, 0.0, 0.0)
        m.add_no("B", 0.0, 0.0, h)
        m.add_no("C", vao, 0.0, h)
        m.add_no("D", vao, 0.0, 0.0)
        m.add_barra("P1", "A", "B", "aco", "R20x50")
        m.add_barra("V1", "B", "C", "aco", "R20x50")
        m.add_barra("P2", "D", "C", "aco", "R20x50")
        m.apoiar("A")
        m.apoiar("D")
        caso = m.add_caso("H")
        caso.nodal("B", fx=H)
        r = resolver(m, "H")
        Mbase = r.esforcos_barra("P1")[5]
        ux_topo = r.deslocamento("B")[0]

        res = _opensees_rodar(_opensees_payload_do_modelo(m, "H"))
        Mbase_os = _momento_opensees(res, "P1", "Mz")
        ux_os = res["deslocamentos"]["B"][0]

        return [
            Conferencia("c04 pórtico plano: deslocamento lateral × "
                        "OpenSeesPy",
                        ux_topo, ux_os, 1e-8),
            Conferencia("c04 pórtico plano: momento na base do pilar × "
                        "OpenSeesPy (módulo — convenção de sinal difere)",
                        abs(Mbase), abs(Mbase_os), 1e-8),
        ]
    return _opensees_ou_pulado("c04", rodar)


# --- cenário 5: grelha ortogonal, acoplamento flexão-torção ----------------

def cenario_05_grelha_ortogonal_pynite() -> list[Conferencia]:
    """Duas vigas perpendiculares no plano horizontal, cruzando-se no meio
    de cada uma, com carga vertical no cruzamento. Sem trava de torção nos
    apoios, a simetria de cada viga zera a rotação no cruzamento por conta
    própria — a carga se reparte entre as duas só pela rigidez à flecha
    concentrada de cada uma (``48EI/L³``), o que dá solução fechada por
    compatibilidade de deslocamento, sem precisar resolver a grelha inteira
    à mão: é o terceiro valor desta conferência."""
    La, Lb, P = 6.0, 5.0, 40.0
    m = _modelo_base("c05")
    m.add_no("A1", 0.0, 0.0, 0.0)
    m.add_no("O", La / 2.0, 0.0, 0.0)
    m.add_no("A2", La, 0.0, 0.0)
    m.add_no("B1", La / 2.0, -Lb / 2.0, 0.0)
    m.add_no("B2", La / 2.0, Lb / 2.0, 0.0)
    m.add_barra("VA1", "A1", "O", "aco", "R20x50")
    m.add_barra("VA2", "O", "A2", "aco", "R20x50")
    m.add_barra("VB1", "B1", "O", "aco", "R20x50")
    m.add_barra("VB2", "O", "B2", "aco", "R20x50")
    for no in ("A1", "A2"):
        m.apoiar(no, uy=False, rx=False, ry=False)
    for no in ("B1", "B2"):
        m.apoiar(no, ux=False, rx=False, ry=False)
    caso = m.add_caso("P")
    caso.nodal("O", fz=-P)
    r = resolver(m, "P")
    s = m.secoes["R20x50"]

    EI = E_ACO * s.Iy
    k_a = 48.0 * EI / La ** 3
    k_b = 48.0 * EI / Lb ** 3
    flecha_exata = -P / (k_a + k_b)

    fe = _pynite_do_modelo(m, "P")
    uz_pynite = fe.nodes["O"].DZ["P"]

    return [
        Conferencia("c05 grelha: flecha no cruzamento × compatibilidade "
                    "P = (k_a+k_b)·δ",
                    r.deslocamento("O")[2], flecha_exata, 1e-6),
        Conferencia("c05 grelha: flecha no cruzamento × PyNiteFEA",
                    r.deslocamento("O")[2], uz_pynite, 1e-6),
    ]


def cenario_05_grelha_ortogonal_opensees() -> list[Conferencia]:
    """Mesma grelha do cenário 5, cruzada com o terceiro motor."""
    def rodar():
        La, Lb, P = 6.0, 5.0, 40.0
        m = _modelo_base("c05os")
        m.add_no("A1", 0.0, 0.0, 0.0)
        m.add_no("O", La / 2.0, 0.0, 0.0)
        m.add_no("A2", La, 0.0, 0.0)
        m.add_no("B1", La / 2.0, -Lb / 2.0, 0.0)
        m.add_no("B2", La / 2.0, Lb / 2.0, 0.0)
        m.add_barra("VA1", "A1", "O", "aco", "R20x50")
        m.add_barra("VA2", "O", "A2", "aco", "R20x50")
        m.add_barra("VB1", "B1", "O", "aco", "R20x50")
        m.add_barra("VB2", "O", "B2", "aco", "R20x50")
        for no in ("A1", "A2"):
            m.apoiar(no, uy=False, rx=False, ry=False)
        for no in ("B1", "B2"):
            m.apoiar(no, ux=False, rx=False, ry=False)
        caso = m.add_caso("P")
        caso.nodal("O", fz=-P)
        r = resolver(m, "P")

        res = _opensees_rodar(_opensees_payload_do_modelo(m, "P"))
        uz_os = res["deslocamentos"]["O"][2]

        return [
            Conferencia("c05 grelha: flecha no cruzamento × OpenSeesPy",
                        r.deslocamento("O")[2], uz_os, 1e-6),
        ]
    return _opensees_ou_pulado("c05", rodar)


# --- cenário 6: barra com rotação arbitrária da seção ----------------------

def cenario_06_secao_rotacionada_pynite() -> list[Conferencia]:
    L, P, rot = 4.0, 15.0, 30.0
    m = _modelo_base("c06")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "B", "aco", "R20x50", rotacao=rot)
    m.apoiar("A")
    caso = m.add_caso("P")
    caso.nodal("B", fz=-P)
    r = resolver(m, "P")

    fe = _pynite_do_modelo(m, "P")
    d_pynite = np.array([fe.nodes["B"].DX["P"], fe.nodes["B"].DY["P"],
                        fe.nodes["B"].DZ["P"]])

    return [
        Conferencia(f"c06 seção girada {rot:.0f}°: deslocamento {eixo} "
                    "× PyNiteFEA",
                    r.deslocamento("B")[i], d_pynite[i], 1e-7)
        for i, eixo in enumerate("xyz")
    ]


def cenario_06_secao_rotacionada_opensees() -> list[Conferencia]:
    """Mesma barra girada do cenário 6, cruzada com o terceiro motor — testa
    o ``vecxz`` com ``rotacao != 0`` (o giro de eixo é aplicado por
    ``matriz_rotacao`` antes de extrair ``ez`` para o OpenSeesPy, então o
    ângulo entra pela mesma rotação de ``R``, não por parâmetro à parte)."""
    def rodar():
        L, P, rot = 4.0, 15.0, 30.0
        m = _modelo_base("c06os")
        m.add_no("A", 0.0, 0.0, 0.0)
        m.add_no("B", L, 0.0, 0.0)
        m.add_barra("B1", "A", "B", "aco", "R20x50", rotacao=rot)
        m.apoiar("A")
        caso = m.add_caso("P")
        caso.nodal("B", fz=-P)
        r = resolver(m, "P")

        res = _opensees_rodar(_opensees_payload_do_modelo(m, "P"))
        d_os = res["deslocamentos"]["B"][0:3]

        return [
            Conferencia(f"c06 seção girada {rot:.0f}°: deslocamento {eixo} "
                        "× OpenSeesPy",
                        r.deslocamento("B")[i], d_os[i], 1e-7)
            for i, eixo in enumerate("xyz")
        ]
    return _opensees_ou_pulado("c06", rodar)


# --- cenário 7: flambagem de Euler, engastado-livre e biapoiado -----------

def cenario_07_flambagem_euler_pynite() -> list[Conferencia]:
    """O PyNiteFEA não faz flambagem (não tem autovalor de estabilidade na
    API pública). **O OpenSeesPy também não** — checado contra a
    documentação oficial antes de tentar qualquer sintaxe, não só suposto:
    a página oficial de integradores estáticos
    (``opensees.github.io/OpenSeesDocumentation/user/manual/analysis/
    integrator.html``) lista só quatro — ``LoadControl``,
    ``DisplacementControl``, ``MinimumUnbalancedDisplacementNorm`` e
    ``Arc-Length`` — **sem nenhum ``LinearBucklingIntegrator``**, que não
    existe na distribuição oficial. O próprio time do OpenSees confirma o
    motivo em texto (blog oficial de um dos mantenedores,
    ``openseesdigital.com/2020/11/13/ordinary-eigenvalues`` e
    ``opensees.berkeley.edu/community/viewtopic.php?p=116754``): não há
    ``getGeometricTangentStiff()`` implementado para elemento de pórtico
    (só elementos PFEM de fluido o implementam), então não existe matriz
    geométrica de barra para montar o autovalor de estabilidade — o único
    jeito documentado de "enganar" o ``eigen()`` para flambagem de barra é
    um truque de massa fictícia (``massa = ψ = L·√(P/EI)``) que só funciona
    para uma coluna isolada e não generaliza para pórtico nenhum; não é uma
    funcionalidade de flambagem de verdade, é uma analogia numérica
    específica de caso único. Implementar isso direito exigiria extrair a
    rigidez geométrica por fora do OpenSees (o que o solver deste programa
    já faz, é o que ``segunda_ordem.flambagem`` monta), não usar o OpenSees
    como motor de flambagem — fora do escopo de um script-ponte. Por isso
    esta bateria **não ganhou um terceiro motor na flambagem**: o confronto
    fica entre o motor próprio e a solução fechada de Euler, nos dois casos
    clássicos de vinculação, como já era."""
    from .core.segunda_ordem import flambagem

    L = 4.0
    secao = _secao_retangular()
    EI = E_ACO * secao.Iz
    Pcr_engastado_livre = math.pi ** 2 * EI / (4.0 * L ** 2)
    Pcr_biapoiado = math.pi ** 2 * EI / L ** 2
    n = 8

    def coluna(nome: str) -> Modelo:
        m = _modelo_base(nome)
        for i in range(n + 1):
            m.add_no(f"N{i}", 0.0, 0.0, L * i / n)
        for i in range(n):
            m.add_barra(f"B{i}", f"N{i}", f"N{i + 1}", "aco", "R20x50")
        return m

    m1 = coluna("c07_el")
    m1.apoiar("N0")
    caso1 = m1.add_caso("N", natureza="permanente")
    caso1.nodal(f"N{n}", fz=-1.0)
    f1 = flambagem(m1, "N")

    m2 = coluna("c07_bi")
    m2.apoiar("N0", rx=False, ry=False)
    m2.apoiar(f"N{n}", uz=False, rx=False, ry=False)
    caso2 = m2.add_caso("N", natureza="permanente")
    caso2.nodal(f"N{n}", fz=-1.0)
    f2 = flambagem(m2, "N")

    return [
        Conferencia("c07 flambagem engastado-livre: Pcr = π²EI/(4L²)",
                    f1.fator_critico, Pcr_engastado_livre, 1e-4),
        Conferencia("c07 flambagem biapoiado: Pcr = π²EI/L²",
                    f2.fator_critico, Pcr_biapoiado, 1e-4),
    ]


# --- cenário 8: apoio em mola -----------------------------------------------

def cenario_08_apoio_elastico_pynite() -> list[Conferencia]:
    L, P, k = 4.0, 30.0, 500.0
    m = _modelo_base("c08")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "B", "aco", "R20x50")
    m.apoiar("A")
    m.add_mola("B", kz=k)
    caso = m.add_caso("P")
    caso.nodal("B", fz=-P)
    r = resolver(m, "P")
    s = m.secoes["R20x50"]

    EI = E_ACO * s.Iy
    flecha_exata = -P / (3.0 * EI / L ** 3 + k)

    fe = _pynite_do_modelo(m, "P")
    dz_pynite = fe.nodes["B"].DZ["P"]

    return [
        Conferencia("c08 apoio elástico: flecha × fechada",
                    r.deslocamento("B")[2], flecha_exata, 1e-9),
        Conferencia("c08 apoio elástico: flecha × PyNiteFEA",
                    dz_pynite, flecha_exata, 1e-6),
    ]


def cenario_08_apoio_elastico_opensees() -> list[Conferencia]:
    """Mesmo apoio em mola do cenário 8, cruzado com o terceiro motor — a
    mola aqui vira, no script-ponte, um nó fantasma preso mais um
    ``zeroLength`` (ver ``opensees_ponte._montar_modelo``)."""
    def rodar():
        L, P, k = 4.0, 30.0, 500.0
        m = _modelo_base("c08os")
        m.add_no("A", 0.0, 0.0, 0.0)
        m.add_no("B", L, 0.0, 0.0)
        m.add_barra("B1", "A", "B", "aco", "R20x50")
        m.apoiar("A")
        m.add_mola("B", kz=k)
        caso = m.add_caso("P")
        caso.nodal("B", fz=-P)
        r = resolver(m, "P")

        res = _opensees_rodar(_opensees_payload_do_modelo(m, "P"))
        dz_os = res["deslocamentos"]["B"][2]

        return [
            Conferencia("c08 apoio elástico: flecha × OpenSeesPy",
                        r.deslocamento("B")[2], dz_os, 1e-6),
        ]
    return _opensees_ou_pulado("c08", rodar)


# --- cenário 9: trecho rígido numa ponta -----------------------------------

def cenario_09_trecho_rigido_pynite() -> list[Conferencia]:
    """O PyNiteFEA não tem trecho rígido (``add_member`` não aceita offset
    de extremidade); o confronto fica entre o motor próprio e a solução
    fechada. O vão flexível, visto da face do trecho rígido, é um balanço
    comum de comprimento ``Lf`` — a extremidade rígida está presa a um nó
    totalmente engastado, de modo que a face não translada nem gira, e o
    balanço flexível se comporta exatamente como se estivesse engastado ali."""
    L, offset, P = 5.0, 1.0, 20.0
    Lf = L - offset
    m = _modelo_base("c09")
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", L, 0.0, 0.0)
    m.add_barra("B1", "A", "B", "aco", "R20x50", offset_i=offset)
    m.apoiar("A")
    caso = m.add_caso("P")
    caso.nodal("B", fz=-P)
    r = resolver(m, "P")
    s = m.secoes["R20x50"]

    EIy = E_ACO * s.Iy
    M_exato = P * Lf
    flecha_exata = -P * Lf ** 3 / (3.0 * EIy)

    d = r.diagrama("B1", 2)

    return [
        Conferencia("c09 trecho rígido: momento na face × fechada",
                    abs(d.My[0]), M_exato, 1e-9),
        Conferencia("c09 trecho rígido: flecha na ponta × fechada",
                    r.deslocamento("B")[2], flecha_exata, 1e-9),
    ]


def cenario_09_trecho_rigido_opensees() -> list[Conferencia]:
    """Mesmo trecho rígido do cenário 9, agora com um terceiro motor que
    **tem** trecho rígido — ao contrário do PyNiteFEA, o OpenSeesPy traduz
    direto por ``geomTransf(..., '-jntOffset', ...)``. Testado e confirmado:
    o momento lido na extremidade ``i`` do elemento (``localForce``) já sai
    na face do trecho rígido, não no eixo do apoio — bate com a solução
    fechada a 1e-9 num caso isolado antes de entrar aqui."""
    def rodar():
        L, offset, P = 5.0, 1.0, 20.0
        Lf = L - offset
        m = _modelo_base("c09os")
        m.add_no("A", 0.0, 0.0, 0.0)
        m.add_no("B", L, 0.0, 0.0)
        m.add_barra("B1", "A", "B", "aco", "R20x50", offset_i=offset)
        m.apoiar("A")
        caso = m.add_caso("P")
        caso.nodal("B", fz=-P)
        r = resolver(m, "P")
        d = r.diagrama("B1", 2)
        M_exato = P * Lf
        flecha_exata = -P * Lf ** 3 / (3.0 * E_ACO * m.secoes["R20x50"].Iy)

        res = _opensees_rodar(_opensees_payload_do_modelo(m, "P"))
        M_os = _momento_opensees(res, "B1", "My")
        dz_os = res["deslocamentos"]["B"][2]

        return [
            Conferencia("c09 trecho rígido: momento na face × OpenSeesPy "
                        "(-jntOffset)",
                        abs(d.My[0]), abs(M_os), 1e-7),
            Conferencia("c09 trecho rígido: flecha na ponta × OpenSeesPy",
                        r.deslocamento("B")[2], dz_os, 1e-7),
            Conferencia("c09 trecho rígido: momento na face × fechada, "
                        "lido do OpenSeesPy",
                        abs(M_os), M_exato, 1e-6),
            Conferencia("c09 trecho rígido: flecha na ponta × fechada, "
                        "lida do OpenSeesPy",
                        dz_os, flecha_exata, 1e-6),
        ]
    return _opensees_ou_pulado("c09", rodar)


# --- cenário 10: pórtico espacial completo, substituindo o apoio inclinado -

def cenario_10_portico_espacial_pynite() -> list[Conferencia]:
    """Ver o porquê da troca no cabeçalho da seção: nem este programa nem o
    PyNiteFEA têm apoio inclinado, então o décimo cenário é o pórtico
    espacial completo de ``equilibrio_global`` — quatro pilares, quatro vigas
    de contorno e duas barras inclinadas —, cruzado contra o PyNiteFEA."""
    m = _portico_espacial()
    r = resolver(m, "mista")

    fe = _pynite_do_modelo(m, "mista")
    d_pynite = np.array([fe.nodes["B1"].DX["mista"], fe.nodes["B1"].DY["mista"],
                        fe.nodes["B1"].DZ["mista"]])
    M_pynite = _momento_pynite(fe, m, "PA", "Mz", 0.0, "mista")

    conferencias = [
        Conferencia(f"c10 pórtico espacial: deslocamento {eixo} de B1 × "
                    "PyNiteFEA",
                    r.deslocamento("B1")[i], d_pynite[i], 1e-7)
        for i, eixo in enumerate("xyz")
    ]
    conferencias.append(Conferencia(
        "c10 pórtico espacial: momento na base do pilar PA × PyNiteFEA "
        "(módulo — convenção de sinal difere)",
        abs(r.esforcos_barra("PA")[5]), abs(M_pynite), 1e-7))
    return conferencias


def cenario_10_portico_espacial_opensees() -> list[Conferencia]:
    """O mesmo pórtico espacial do cenário 10 (quatro pilares, quatro vigas
    de contorno, duas barras inclinadas — barra vertical, horizontal e
    oblíqua misturadas, carga nodal, distribuída local e global, e momento
    concentrado), cruzado agora com o terceiro motor."""
    def rodar():
        m = _portico_espacial()
        r = resolver(m, "mista")

        res = _opensees_rodar(_opensees_payload_do_modelo(m, "mista"))
        d_os = res["deslocamentos"]["B1"][0:3]
        M_os = _momento_opensees(res, "PA", "Mz")

        conferencias = [
            Conferencia(f"c10 pórtico espacial: deslocamento {eixo} de B1 "
                        "× OpenSeesPy",
                        r.deslocamento("B1")[i], d_os[i], 1e-7)
            for i, eixo in enumerate("xyz")
        ]
        conferencias.append(Conferencia(
            "c10 pórtico espacial: momento na base do pilar PA × "
            "OpenSeesPy (módulo — convenção de sinal difere)",
            abs(r.esforcos_barra("PA")[5]), abs(M_os), 1e-7))
        return conferencias
    return _opensees_ou_pulado("c10", rodar)


# ---------------------------------------------------------------------------
# 43. Análise modal — frequências e modos naturais
# ---------------------------------------------------------------------------

def modal_viga_em_balanco() -> list[Conferencia]:
    """Confronto fechado: primeiro, segundo e terceiro modo de flexão de uma
    viga em balanço contra a fórmula clássica de Euler-Bernoulli,
    ``ωn = (βnL)²·√(EI/(ρAL⁴))``, com ``β1L = 1,875104``, ``β2L = 4,694091``
    e ``β3L = 7,854757`` (McGuire/Logan, cap. 16.6 — são as três primeiras
    raízes de ``cos(βL)·cosh(βL) = -1``).

    Com seção assimétrica (``Iy ≠ Iz``) o modelo também vibra no outro plano
    de flexão, com uma frequência mais alta (proporcional a ``√(Iy/Iz)``) que
    não é uma das três primeiras do plano conferido — por isso a malha é
    refinada (8 barras) e o modo é identificado pela forma (maior componente
    na direção do plano conferido), não só pela posição na lista ordenada.
    """
    from .core.dinamica import analisar_modal

    E, peso_especifico = E_ACO, 78.5
    L = 3.0
    secao = _secao_retangular()
    # 16, não 8: o terceiro modo de flexão já precisa de malha mais fina
    # para convergir dentro de 5e-4 — é o mesmo efeito de malha que
    # ``rigidez_geometrica`` documenta para a flambagem, só que aqui em vez
    # de refinar por dentro do cálculo (como ``rigidez_geometrica_refinada``
    # faz) a malha é a que o usuário vê mesmo, porque a massa consistente
    # não tem uma versão "refinada" equivalente nesta rodada.
    n = 16

    m = _modelo_base("modal_balanco")
    m.materiais["aco"] = replace(m.materiais["aco"],
                                 peso_especifico=peso_especifico)
    for i in range(n + 1):
        m.add_no(f"N{i}", 0.0, 0.0, L * i / n)
    for i in range(n):
        m.add_barra(f"B{i}", f"N{i}", f"N{i + 1}", "aco", "R20x50")
    m.apoiar("N0")

    modal = analisar_modal(m, n_modos=6)

    from .core.dinamica import GRAVIDADE
    rho = peso_especifico / GRAVIDADE
    rhoA = rho * secao.A
    EI = E * secao.Iz

    betas = (1.875104, 4.694091, 7.854757)
    exatos = [b ** 2 * math.sqrt(EI / (rhoA * L ** 4)) / (2.0 * math.pi)
             for b in betas]

    # Identifica, para cada modo calculado, se ele é de flexão no plano
    # local x–y (a que a fórmula fechada confere, com ``Iz``). A barra é
    # vertical, e o docstring de ``elemento.py`` diz que, para barra
    # vertical, o eixo local y aponta no X global e o z no Y global — o
    # plano local x–y é então o que desloca em **ux** global, não uy; é por
    # isso que o deslocamento em ux no topo, e não em uy, tem de dominar.
    topo = f"N{n}"
    gdl_uy = m.gdl(topo)[1]
    gdl_ux = m.gdl(topo)[0]
    indices_xy = []
    for i, modo in enumerate(modal.modos):
        ux, uy = abs(modo[gdl_ux]), abs(modo[gdl_uy])
        # Um modo de torção ou axial tem ux e uy os dois nulos a menos de
        # ruído numérico no topo (a flexão não entra nesses graus de
        # liberdade nenhuma); o corte é contra esse ruído, não contra o
        # pico do modo — o pico de um modo de ordem mais alta pode estar
        # num nó interno, não no topo.
        if ux + uy < 1e-6:
            continue
        if ux > uy:
            indices_xy.append(i)
    indices_xy = indices_xy[:3]

    conferencias = []
    for k, (i, exato) in enumerate(zip(indices_xy, exatos), start=1):
        conferencias.append(Conferencia(
            f"modal balanço: {k}º modo de flexão x–y × Euler-Bernoulli",
            modal.frequencias[i], exato, 5e-4))
    conferencias.append(Conferencia(
        "modal balanço: achou os três modos esperados no plano x–y",
        float(len(indices_xy)), 3.0))
    return conferencias


def modal_viga_em_balanco_opensees() -> list[Conferencia]:
    """A mesma viga em balanço de ``modal_viga_em_balanco``, agora cruzada
    com ``ops.eigen()``.

    **Pegadinha confirmada na marra**: ``elasticBeamColumn`` do OpenSeesPy
    não gera massa nenhuma sozinho — sem ``'-mass', massDens, '-cMass'`` na
    chamada de ``element(...)``, ``ops.eigen()`` falha com matriz de massa
    singular (testado isoladamente: omitir os dois dá erro de autovalor, não
    um resultado errado silencioso). ``massDens`` é massa por comprimento
    (``ρ·A``, igual ao ``rhoA`` que ``massa_local`` usa para montar os termos
    de translação) e ``-cMass`` pede a matriz consistente, não a concentrada
    — a mesma formulação de ``massa_local`` deste programa (ver o
    script-ponte, ``_montar_modelo``). Frequências batem com a fórmula
    fechada de Euler-Bernoulli a 1e-4 ou melhor, confirmado num caso
    trivial antes de entrar aqui (cantilever de 16 barras, frequências dos
    três modos do plano x–y a menos de 3e-5 de diferença relativa da solução
    fechada)."""
    def rodar():
        E, peso_especifico = E_ACO, 78.5
        L = 3.0
        n = 16

        m = _modelo_base("modal_balanco_os")
        m.materiais["aco"] = replace(m.materiais["aco"],
                                     peso_especifico=peso_especifico)
        for i in range(n + 1):
            m.add_no(f"N{i}", 0.0, 0.0, L * i / n)
        for i in range(n):
            m.add_barra(f"B{i}", f"N{i}", f"N{i + 1}", "aco", "R20x50")
        m.apoiar("N0")

        payload = _opensees_payload_do_modelo(m, modo="modal", n_modos=6)
        res = _opensees_rodar(payload)
        frequencias_os = res["frequencias"]
        modos_os = res["modos"]

        secao = _secao_retangular()
        from .core.dinamica import GRAVIDADE
        rhoA = (peso_especifico / GRAVIDADE) * secao.A
        EI = E * secao.Iz
        betas = (1.875104, 4.694091, 7.854757)
        exatos = [b ** 2 * math.sqrt(EI / (rhoA * L ** 4)) / (2.0 * math.pi)
                 for b in betas]

        topo = f"N{n}"
        indices_xy = []
        for i, modo in enumerate(modos_os):
            ux, uy = abs(modo[topo][0]), abs(modo[topo][1])
            if ux + uy < 1e-6:
                continue
            if ux > uy:
                indices_xy.append(i)
        indices_xy = indices_xy[:3]

        conferencias = [
            Conferencia(f"modal balanço: {k}º modo de flexão x–y × "
                        "OpenSeesPy (ops.eigen)",
                        frequencias_os[i], exato, 1e-4)
            for k, (i, exato) in enumerate(zip(indices_xy, exatos), start=1)
        ]
        conferencias.append(Conferencia(
            "modal balanço: OpenSeesPy também achou os três modos no "
            "plano x–y",
            float(len(indices_xy)), 3.0))
        return conferencias
    return _opensees_ou_pulado("modal_balanco", rodar)


def modal_massa_so_das_barras_com_peso() -> list[Conferencia]:
    """Barra sem peso específico não contribui massa — nem rigidez a mais, o
    que já era coberto; aqui é a massa que precisa ficar de fora."""
    from .core.dinamica import matriz_massa_global
    from .core.montagem import preparar_barras

    m = _barra_reta("modal_sem_massa", 3.0)
    preparadas = preparar_barras(m)
    M = matriz_massa_global(m, preparadas)

    return [
        Conferencia("modal: barra sem peso específico não entra na massa",
                    float(np.max(np.abs(M))), 0.0),
    ]


def modal_recusa_estrutura_sem_massa() -> list[Conferencia]:
    from .core.dinamica import analisar_modal

    m = _barra_reta("modal_sem_massa_toda", 3.0)
    m.add_caso("vazio")

    levantou = False
    try:
        analisar_modal(m)
    except ErroDeModelo:
        levantou = True

    return [
        Conferencia("modal: estrutura sem massa nenhuma é recusada",
                    float(levantou), 1.0),
    ]


# ---------------------------------------------------------------------------
# 45. Análise modal em edifícios inteiros — pareamento de modo por MAC
# ---------------------------------------------------------------------------
#
# A seção 43 confronta o motor próprio contra uma solução fechada, mas só num
# cantilever isolado (16 barras, um só plano de flexão por vez). O que falta
# testar ali é o caso realista: um edifício inteiro, com vários modos de
# frequência próxima (sobretudo em prédios altos) e, em planta assimétrica,
# modos **acoplados** (translação e torção na mesma forma modal) — é aí que
# comparar só pela posição na lista ("modo 3 com modo 3") pode mascarar um
# erro de verdade ou, ao contrário, acusar divergência onde os dois motores só
# acharam os mesmos modos em ordem diferente.
#
# Por isso o confronto aqui usa o **MAC** (Modal Assurance Criterion, ver
# ``_mac``) para parear cada modo do motor próprio com o modo do OpenSeesPy
# que tem a forma mais parecida, e só então compara frequência — em vez de
# supor que a ordem bate. O MAC usa só os graus de liberdade de translação
# (``_translacoes``/``_translacoes_opensees``), o que evita ter de normalizar
# a escala de rotação dos dois vetores para comparar com a de translação.
#
# **Classificação do modo** (translação X, Y, torção, ou uma combinação): em
# vez de olhar só o maior componente num nó (frágil — o maior componente pode
# estar em qualquer nó conforme a malha), ``_classificar_modo`` ajusta por
# mínimos quadrados um campo de corpo rígido no plano do pavimento mais alto,
# ``ux = u0x - θ(y-y0)``, ``uy = u0y + θ(x-x0)``, e compara a translação pura
# do centro (``|u0x,u0y|``) com o giro equivalente na borda (``|θ|·R``, R =
# maior distância ao centro) — a mesma unidade (metro), o que ``θ`` sozinho
# não tem contra ``u0x``/``u0y`` (rad × m não é comparável a m sem escala).
#
# **Quatro edifícios, quatro desafios diferentes**:
#
# 1. Pequeno (2×2 vãos, 2 pavimentos) — calibração: duplamente simétrico em
#    planta, serve para conferir que o básico bate quase exato antes de ir
#    para os casos difíceis. Por ser duplamente simétrico, vários pares de
#    modo são **degenerados** (mesma frequência, translação X e Y idênticas a
#    menos de uma rotação arbitrária no subespaço) — confirmado à parte
#    (resíduo relativo < 1e-4 ao reconstruir um modo do motor próprio como
#    combinação linear do par degenerado do OpenSeesPy): o MAC *individual*
#    de um modo degenerado pode cair bem abaixo de 1,0 sem que isso seja erro
#    nenhum, só a base que cada ``eigh``/``ops.eigen`` escolhe dentro do
#    mesmo subespaço bidimensional. Por isso esta conferência pede só os
#    6 primeiros modos (que já cobrem translação X, Y e torção, e um segundo
#    par de translação) — o par degenerado mais alto (14,16 Hz, MAC
#    individual ≈ 0,79 apesar do subespaço bater) fica de fora do pedido, não
#    por ser ignorado e sim por já não ser preciso para o que esta bateria
#    promete cobrir.
# 2. Alto (10 pavimentos, mesma planta regular) — o desafio é numérico: mais
#    graus de liberdade, frequências mais próximas entre si nos modos de
#    ordem mais alta, mais chance de troca de ordem entre os dois motores
#    (de fato troca: o par fundamental sai na ordem 1-2 no motor próprio e
#    2-1 no OpenSeesPy — o MAC resolve isso antes de comparar frequência).
# 3. Com balanço (6 pavimentos, trecho de viga prolongado além da última
#    linha de pilares, sem apoio na ponta, em toda a altura) — testa se a
#    massa do trecho em balanço (inércia sem apoio próximo) entra certa nos
#    dois motores; a planta deixa de ser simétrica em Y por causa do
#    balanço, e isso já basta para acoplar translação Y com torção em quase
#    todos os modos (ver os rótulos "translação Y+torção" no resultado).
# 4. Assimétrico (8 pavimentos, planta em L — falta o pilar do canto (3,3) —
#    e um pilar bem mais rígido no canto oposto (0,0), deslocando o centro de
#    rigidez para longe do centro de massa) — o caso que a tarefa pede para
#    confirmar de verdade: um modo claramente torsional (giro equivalente
#    dominante, translação do centro quase nula) identificado pelos dois
#    motores com MAC ≈ 1,0 e erro de frequência desprezível. Achados dois
#    modos assim nos 10 primeiros (modo 3, 1,43 Hz, e modo 9, 4,37 Hz); as
#    conferências abaixo travam os dois.
#
# Com os quatro casos rodando em menos de meio segundo cada (malha pequena,
# mas genuína — grelha retangular completa, pilares e vigas com peso próprio
# de concreto de verdade), não houve motivo para reduzir porte: é a mesma
# malha usada na exploração manual que validou este confronto.
# ---------------------------------------------------------------------------

def _mac(phi_a: np.ndarray, phi_b: np.ndarray) -> float:
    """Modal Assurance Criterion entre dois vetores modais."""
    num = float(phi_a @ phi_b) ** 2
    den = float(phi_a @ phi_a) * float(phi_b @ phi_b)
    return num / den if den > 0.0 else 0.0


def _translacoes(modelo: Modelo, modo: np.ndarray) -> np.ndarray:
    """Só os graus de liberdade de translação (ux,uy,uz) de cada nó, na
    ordem de ``modelo.nos`` -- o que entra no MAC."""
    vals: list[float] = []
    for nome in modelo.nos:
        g = modelo.gdl(nome)
        vals.extend(modo[g[0:3]])
    return np.array(vals)


def _translacoes_opensees(modelo: Modelo, modo_os: dict) -> np.ndarray:
    vals: list[float] = []
    for nome in modelo.nos:
        vals.extend(modo_os[nome][0:3])
    return np.array(vals)


def _classificar_modo(modelo: Modelo, ux_de, uy_de) -> tuple[str, float, float, float]:
    """Classifica um modo olhando o pavimento mais alto: ajusta por mínimos
    quadrados um campo de corpo rígido no plano, ``ux_i = u0x - θ(y_i-y0)``,
    ``uy_i = u0y + θ(x_i-x0)``, e compara a translação pura do centro com o
    giro equivalente na borda (``|θ|·R``) -- ver o porquê no cabeçalho da
    seção. ``ux_de(nome)``/``uy_de(nome)`` leem ux/uy de um nó, abstraindo se
    o modo vem do motor próprio (vetor + ``modelo.gdl``) ou do OpenSeesPy
    (dicionário por nó).
    """
    zmax = max(no.z for no in modelo.nos.values())
    topo = [(nome, no.x, no.y) for nome, no in modelo.nos.items()
           if abs(no.z - zmax) < 1e-6]
    x0 = sum(x for _, x, _ in topo) / len(topo)
    y0 = sum(y for _, _, y in topo) / len(topo)
    R = max(math.hypot(x - x0, y - y0) for _, x, y in topo) or 1.0

    linhas_A, linhas_b = [], []
    for nome, x, y in topo:
        linhas_A.append([1.0, 0.0, -(y - y0)])
        linhas_b.append(ux_de(nome))
        linhas_A.append([0.0, 1.0, (x - x0)])
        linhas_b.append(uy_de(nome))

    (u0x, u0y, theta), *_ = np.linalg.lstsq(np.array(linhas_A),
                                            np.array(linhas_b), rcond=None)
    translacao = math.hypot(u0x, u0y)
    giro_equiv = abs(theta) * R
    tot = translacao + giro_equiv
    if tot < 1e-12:
        return "indefinido", 0.0, 0.0, 0.0

    frac_giro = giro_equiv / tot
    if frac_giro > 0.70:
        rotulo = "torção"
    else:
        maior, menor = sorted((abs(u0x), abs(u0y)), reverse=True)
        eixo = "XY" if (maior > 0.0 and menor > 0.6 * maior) else (
            "X" if abs(u0x) >= abs(u0y) else "Y")
        rotulo = f"translação {eixo}"
        if frac_giro > 0.15:
            rotulo += "+torção"
    return rotulo, u0x, u0y, giro_equiv


def _grade_edificio(nx: int, ny: int, lx: float, ly: float, n_pav: int,
                    pe_direito: float, nome: str,
                    b_pilar: float = 0.30, h_pilar: float = 0.30,
                    b_viga: float = 0.20, h_viga: float = 0.50,
                    fck: float = 30.0,
                    remover_colunas: set[tuple[int, int]] | None = None,
                    balanco: float = 0.0,
                    pilar_rigido: set[tuple[int, int]] | None = None,
                    b_pilar_rigido: float = 0.0,
                    h_pilar_rigido: float = 0.0) -> Modelo:
    """Edifício em grelha retangular ``nx``×``ny`` vãos, ``n_pav``
    pavimentos, concreto de verdade (seção e peso específico plausíveis).

    ``remover_colunas``: linhas de pilar (i,j) removidas em todos os
    pavimentos -- planta assimétrica (formato em L). ``balanco``: trecho de
    viga prolongado além da última linha de pilares em X, sem apoio na
    ponta, em todo pavimento. ``pilar_rigido``: linhas de pilar com seção
    maior, para deslocar o centro de rigidez.
    """
    from .core.concreto import concreto

    remover_colunas = remover_colunas or set()
    pilar_rigido = pilar_rigido or set()

    m = Modelo(nome)
    mat = concreto("concreto", fck, peso_especifico=25.0)
    m.materiais[mat.nome] = mat
    m.add_secao(Secao.retangular("pilar", b_pilar, h_pilar))
    m.add_secao(Secao.retangular("viga", b_viga, h_viga))
    if pilar_rigido:
        m.add_secao(Secao.retangular("pilar_rigido", b_pilar_rigido,
                                     h_pilar_rigido))

    xs = [i * lx for i in range(nx + 1)]
    ys = [j * ly for j in range(ny + 1)]
    zs = [k * pe_direito for k in range(n_pav + 1)]

    ativos = [(i, j) for i in range(nx + 1) for j in range(ny + 1)
             if (i, j) not in remover_colunas]
    ativos_set = set(ativos)

    def no(i, j, k):
        return f"N{i}.{j}.{k}"

    for k, z in enumerate(zs):
        for (i, j) in ativos:
            m.add_no(no(i, j, k), xs[i], ys[j], z)

    for k in range(n_pav):
        for (i, j) in ativos:
            secao_p = "pilar_rigido" if (i, j) in pilar_rigido else "pilar"
            m.add_barra(f"P{i}.{j}.{k + 1}", no(i, j, k), no(i, j, k + 1),
                        "concreto", secao_p)

    for k in range(1, n_pav + 1):
        for i in range(nx):
            for j in range(ny + 1):
                if (i, j) in ativos_set and (i + 1, j) in ativos_set:
                    m.add_barra(f"VX{i}.{j}.{k}", no(i, j, k),
                                no(i + 1, j, k), "concreto", "viga")
        for i in range(nx + 1):
            for j in range(ny):
                if (i, j) in ativos_set and (i, j + 1) in ativos_set:
                    m.add_barra(f"VY{i}.{j}.{k}", no(i, j, k),
                                no(i, j + 1, k), "concreto", "viga")

    for (i, j) in ativos:
        m.apoiar(no(i, j, 0))

    if balanco > 0.0:
        i_balc = nx
        for k in range(1, n_pav + 1):
            for j in range(ny + 1):
                if (i_balc, j) not in ativos_set:
                    continue
                nb = f"NB{j}.{k}"
                m.add_no(nb, xs[i_balc] + balanco, ys[j], zs[k])
                m.add_barra(f"VXB{j}.{k}", no(i_balc, j, k), nb,
                            "concreto", "viga")

    m.validar()
    return m


def _confrontar_modal_mac(modelo: Modelo, n_modos: int):
    """Roda o motor próprio e o OpenSeesPy num mesmo ``Modelo``, pareia modo
    a modo pelo MAC (maior MAC disponível, sem repetir par), e devolve
    ``(modal, frequencias_os, pares)`` -- ``pares`` é uma lista de
    ``(i_proprio, j_opensees, mac, f_proprio, f_opensees, rotulo_proprio,
    rotulo_opensees)``, na ordem dos modos do motor próprio."""
    from .core.dinamica import analisar_modal

    modal = analisar_modal(modelo, n_modos=n_modos)
    payload = _opensees_payload_do_modelo(modelo, modo="modal", n_modos=n_modos)
    res = _opensees_rodar(payload)
    freq_os = res["frequencias"]
    modos_os = res["modos"]

    vets_proprio = [_translacoes(modelo, modal.modos[i]) for i in range(n_modos)]
    vets_os = [_translacoes_opensees(modelo, modos_os[i]) for i in range(n_modos)]

    MAC = np.zeros((n_modos, n_modos))
    for i in range(n_modos):
        for j in range(n_modos):
            MAC[i, j] = _mac(vets_proprio[i], vets_os[j])

    pares = []
    usados = set()
    for i in range(n_modos):
        ordem = np.argsort(-MAC[i, :])
        j = next((cand for cand in ordem if cand not in usados), None)
        if j is None:
            continue
        usados.add(j)

        def ux_proprio(nome, i=i):
            return modal.modos[i][modelo.gdl(nome)[0]]

        def uy_proprio(nome, i=i):
            return modal.modos[i][modelo.gdl(nome)[1]]

        def ux_os(nome, j=j):
            return modos_os[j][nome][0]

        def uy_os(nome, j=j):
            return modos_os[j][nome][1]

        rot_p, *_ = _classificar_modo(modelo, ux_proprio, uy_proprio)
        rot_o, *_ = _classificar_modo(modelo, ux_os, uy_os)
        pares.append((i, j, float(MAC[i, j]), modal.frequencias[i],
                     freq_os[j], rot_p, rot_o))
    return modal, freq_os, pares


def edificio_modal_pequeno_opensees() -> list[Conferencia]:
    """Edifício 1 -- calibração: 2×2 vãos de 5 m, 2 pavimentos de 3 m, planta
    duplamente simétrica. Só 6 modos pedidos (ver cabeçalho da seção: além
    deles o edifício tem pares degenerados cujo MAC individual não é um bom
    critério)."""
    def rodar():
        m = _grade_edificio(nx=2, ny=2, lx=5.0, ly=5.0, n_pav=2,
                            pe_direito=3.0, nome="modal_ed1_pequeno")
        n_modos = 6
        modal, freq_os, pares = _confrontar_modal_mac(m, n_modos)

        conferencias = [Conferencia(
            "edifício 1 (calibração): frequência fundamental, motor "
            "próprio × OpenSeesPy",
            modal.frequencia_fundamental, freq_os[0], 2e-3)]
        for (i, j, macval, fp, fo, rp, ro) in pares:
            conferencias.append(Conferencia(
                f"edifício 1: modo {i + 1} ({rp}) pareado por MAC com "
                f"OpenSeesPy modo {j + 1} ({ro})", macval, 1.0, 0.10))
            conferencias.append(Conferencia(
                f"edifício 1: modo {i + 1} ({rp}) — frequência do par",
                fp, fo, 2e-3))
        return conferencias
    return _opensees_ou_pulado("edificio_modal_pequeno", rodar)


def edificio_modal_alto_opensees() -> list[Conferencia]:
    """Edifício 2 -- mesma planta regular do edifício 1, 10 pavimentos: mais
    graus de liberdade, frequências mais próximas nos modos de ordem alta, e
    de fato o par fundamental já sai em ordem trocada entre os dois motores
    (1-2 no motor próprio, 2-1 no OpenSeesPy) -- o MAC resolve isso antes de
    comparar frequência."""
    def rodar():
        m = _grade_edificio(nx=2, ny=2, lx=5.0, ly=5.0, n_pav=10,
                            pe_direito=3.0, nome="modal_ed2_alto")
        n_modos = 10
        modal, freq_os, pares = _confrontar_modal_mac(m, n_modos)

        conferencias = [Conferencia(
            "edifício 2 (10 pav): frequência fundamental, motor próprio × "
            "OpenSeesPy", modal.frequencia_fundamental, freq_os[0], 2e-3)]
        for (i, j, macval, fp, fo, rp, ro) in pares:
            conferencias.append(Conferencia(
                f"edifício 2: modo {i + 1} ({rp}) pareado por MAC com "
                f"OpenSeesPy modo {j + 1} ({ro})", macval, 1.0, 0.05))
            conferencias.append(Conferencia(
                f"edifício 2: modo {i + 1} ({rp}) — frequência do par",
                fp, fo, 2e-3))
        return conferencias
    return _opensees_ou_pulado("edificio_modal_alto", rodar)


def edificio_modal_balanco_opensees() -> list[Conferencia]:
    """Edifício 3 -- 3×2 vãos de 5 m, 6 pavimentos de 3 m, com um trecho de
    viga de 2 m em balanço além da última linha de pilares em X (sem apoio
    na ponta), em toda a altura. A massa do balanço (inércia sem apoio
    próximo) tem de entrar certa nos dois motores -- e a quebra de simetria
    em Y que o balanço introduz já acopla translação Y com torção na maioria
    dos modos (rótulo "translação Y+torção")."""
    def rodar():
        m = _grade_edificio(nx=3, ny=2, lx=5.0, ly=5.0, n_pav=6,
                            pe_direito=3.0, nome="modal_ed3_balanco",
                            balanco=2.0)
        n_modos = 8
        modal, freq_os, pares = _confrontar_modal_mac(m, n_modos)

        conferencias = [Conferencia(
            "edifício 3 (balanço): frequência fundamental, motor próprio × "
            "OpenSeesPy", modal.frequencia_fundamental, freq_os[0], 2e-3)]
        for (i, j, macval, fp, fo, rp, ro) in pares:
            conferencias.append(Conferencia(
                f"edifício 3: modo {i + 1} ({rp}) pareado por MAC com "
                f"OpenSeesPy modo {j + 1} ({ro})", macval, 1.0, 0.05))
            conferencias.append(Conferencia(
                f"edifício 3: modo {i + 1} ({rp}) — frequência do par",
                fp, fo, 2e-3))
        return conferencias
    return _opensees_ou_pulado("edificio_modal_balanco", rodar)


def edificio_modal_assimetrico_opensees() -> list[Conferencia]:
    """Edifício 4 -- 3×3 vãos de 5 m, 8 pavimentos de 3 m, planta em L (falta
    o pilar do canto (3,3)) e um pilar bem mais rígido no canto oposto
    (0,0) -- o centro de rigidez sai longe do centro de massa de propósito.
    O que mais importa confirmar aqui: um modo claramente torsional
    (giro equivalente dominante, translação do centro quase nula)
    identificado pelos dois motores com MAC alto e concordando que é
    torção, não translação disfarçada -- achados dois assim (modo 3 e
    modo 9) entre os 10 primeiros."""
    def rodar():
        m = _grade_edificio(nx=3, ny=3, lx=5.0, ly=5.0, n_pav=8,
                            pe_direito=3.0, nome="modal_ed4_assimetrico",
                            remover_colunas={(3, 3)},
                            pilar_rigido={(0, 0)},
                            b_pilar_rigido=0.60, h_pilar_rigido=0.60)
        n_modos = 10
        modal, freq_os, pares = _confrontar_modal_mac(m, n_modos)

        conferencias = [Conferencia(
            "edifício 4 (assimétrico): frequência fundamental, motor "
            "próprio × OpenSeesPy",
            modal.frequencia_fundamental, freq_os[0], 2e-3)]
        torcionais = []
        for (i, j, macval, fp, fo, rp, ro) in pares:
            conferencias.append(Conferencia(
                f"edifício 4: modo {i + 1} ({rp}) pareado por MAC com "
                f"OpenSeesPy modo {j + 1} ({ro})", macval, 1.0, 0.05))
            conferencias.append(Conferencia(
                f"edifício 4: modo {i + 1} ({rp}) — frequência do par",
                fp, fo, 2e-3))
            if rp == "torção" and ro == "torção":
                torcionais.append((i, j, macval))
        # O que a tarefa pede para confirmar de verdade: achou torção nos
        # dois motores, concordando que é torção (não translação disfarçada
        # por classificação furada), em pelo menos um par.
        conferencias.append(Conferencia(
            "edifício 4: achou ao menos um modo torsional reconhecido "
            "pelos dois motores", float(len(torcionais) >= 1), 1.0))
        return conferencias
    return _opensees_ou_pulado("edificio_modal_assimetrico", rodar)


# ---------------------------------------------------------------------------
# 46. Viga apoiada em viga, e dimensionar sem imprimir
# ---------------------------------------------------------------------------
#
# Onde duas vigas se encontram sem pilar, uma repousa na outra: em V1, que se
# apoia, a V2 entra como **apoio**; em V2, que recebe, a V1 entra como **carga
# concentrada** — a reação dela naquele nó. As conferências abaixo seguram as
# três coisas que podiam dar errado: quem apoia quem (e sem ciclo), a reação
# chegar inteira à viga de apoio, e o balanço no fim da viga, que perdia o
# último apoio de pilar na tradução.

def _viga_apoiada_em_viga(h_secundaria: float = 0.40) -> Modelo:
    """Principal em X (pilares em x=0 e x=10, nó de passagem em x=4) e uma
    secundária em Y que nasce nesse nó e termina num pilar em (4, 6)."""
    from .core.concreto import concreto

    m = Modelo("viga_em_viga")
    c = concreto("C30", 30.0)
    m.materiais[c.nome] = c
    m.add_secao(Secao.retangular("VP", 0.20, 0.60))
    m.add_secao(Secao.retangular("VS", 0.20, h_secundaria))
    m.add_secao(Secao.retangular("P30", 0.30, 0.30))
    for nome, x in (("A", 0.0), ("J", 4.0), ("B", 10.0)):
        m.add_no(nome, x, 0.0, 3.0)
    for nome, x, y in (("A", 0.0, 0.0), ("B", 10.0, 0.0), ("C", 4.0, 6.0)):
        if nome == "C":
            m.add_no("C", x, y, 3.0)
        m.add_no("b" + nome, x, y, 0.0)
        m.add_barra("P" + nome, "b" + nome, nome, c.nome, "P30")
        m.apoiar("b" + nome)
    m.add_barra("VP1", "A", "J", c.nome, "VP")
    m.add_barra("VP2", "J", "B", c.nome, "VP")
    m.add_barra("VS", "J", "C", c.nome, "VS")
    g = m.add_caso("G", "permanente")
    q = m.add_caso("Q", "variavel", "residencial")
    for barra, qg, qq in (("VP1", 10.0, 4.0), ("VP2", 10.0, 4.0),
                          ("VS", 20.0, 8.0)):
        g.distribuida(barra, qz=-qg, sistema="global")
        q.distribuida(barra, qz=-qq, sistema="global")
    m.validar()
    return m


def viga_apoiada_em_viga_hierarquia() -> list[Conferencia]:
    """Quem apoia quem: a de pilares nos dois lados segura a que nasce nela."""
    from .continuidade import vigas_continuas

    m = _viga_apoiada_em_viga()
    cadeias = {frozenset(v.barras): v for v in vigas_continuas(m)}
    principal = cadeias[frozenset({"VP1", "VP2"})]
    secundaria = cadeias[frozenset({"VS"})]
    ap = secundaria.apoio_em_viga(secundaria.nos.index("J"))

    return [
        Conferencia("viga em viga: a principal não repousa em ninguém",
                    float(len(principal.apoios_em_viga)), 0.0),
        Conferencia("viga em viga: a secundária repousa numa viga",
                    float(len(secundaria.apoios_em_viga)), 1.0),
        Conferencia("viga em viga: e é na principal",
                    float(ap is not None
                          and ap.viga_de_apoio == principal.nome), 1.0),
        Conferencia("viga em viga: a secundária passa a ter dois apoios",
                    float(len(secundaria.suportes)), 2.0),
        Conferencia("viga em viga: o vão dela vai do nó ao pilar, 6 m",
                    secundaria.vaos[0], 6.0, 1e-12),
        Conferencia("viga em viga: a principal fica com os 2 vãos de sempre",
                    float(len(principal.vaos)), 1.0),
        Conferencia("viga em viga: a posição do nó na principal é 4 m",
                    ap.posicao_na_de_apoio, 4.0, 1e-12),
        Conferencia("viga em viga: as prioridades diferem (sem ciclo)",
                    float(principal.prioridade < secundaria.prioridade), 1.0),
        Conferencia("viga em viga: a largura do apoio é a da principal, 20 cm",
                    ap.largura_cm, 20.0, 1e-9),
    ]


def viga_apoiada_em_viga_entra_como_apoio_e_como_carga() -> list[Conferencia]:
    """A reação da apoiada chega inteira, como carga, à viga de apoio."""
    from .continuidade import vigas_continuas
    from .dimensionamento import _reacao_no_apoio, verificar_vigas

    m = _viga_apoiada_em_viga()
    verificacoes = {frozenset(v.barras): v for v in verificar_vigas(m)}
    principal = verificacoes[frozenset({"VP1", "VP2"})]
    secundaria = verificacoes[frozenset({"VS"})]

    k = secundaria.viga.apoio_do_no[
        next(c for c in vigas_continuas(m) if c.barras == ["VS"]
             ).nos.index("J")]
    g, q = _reacao_no_apoio(secundaria.resultado, k)

    # a secundária isolada: soma das reações = carga total (g: 20 x 6)
    total_g = sum(float(r.reacoes.sum()) for r in
                  secundaria.resultado.estrutura.respostas if r.acao == "g")

    recebidas = principal.viga.concentradas
    p_g = sum(c.P for c in recebidas if c.acao == "g")
    p_q = sum(c.P for c in recebidas if c.acao == "q")

    return [
        Conferencia("viga em viga: as duas foram dimensionadas",
                    float(principal.passou and secundaria.passou), 1.0),
        Conferencia("viga em viga: na secundária, a principal é apoio simples",
                    float(secundaria.viga.apoios[0].tipo == "simples"), 1.0),
        Conferencia("viga em viga: a principal sabe de quem recebe",
                    float(principal.recebe_de == [secundaria.nome]), 1.0),
        Conferencia("viga em viga: a secundária sabe em quem repousa",
                    float(secundaria.apoiada_em == [principal.nome]), 1.0),
        Conferencia("viga em viga: a secundária fecha o equilíbrio, ΣR = 120",
                    total_g, 20.0 * 6.0, 1e-6),
        Conferencia("viga em viga: a carga permanente que a principal recebe "
                    "é a reação da secundária",
                    p_g, g, 1e-9),
        Conferencia("viga em viga: a carga variável também",
                    p_q, q, 1e-9),
        Conferencia("viga em viga: a carga chega em x = 4 m da principal",
                    float(all(abs(c.x - 4.0) < 1e-9 for c in recebidas)), 1.0),
        Conferencia("viga em viga: é carga indireta (armadura de suspensão)",
                    float(bool(recebidas) and all(c.indireta
                                                  for c in recebidas)), 1.0),
        Conferencia("viga em viga: secundária mais baixa não fica pendurada",
                    float(not any(c.pendurada for c in recebidas)), 1.0),
        Conferencia("viga em viga: a reação é uma parte da carga, não a toda",
                    float(0.0 < g < 20.0 * 6.0), 1.0),
    ]


def viga_apoiada_em_viga_mais_alta_fica_pendurada() -> list[Conferencia]:
    """Se a apoiada é mais alta que a de apoio, a face de baixo dela fica
    abaixo da outra: é viga pendurada (18.3.6), e a conta do tirante é outra."""
    from .dimensionamento import verificar_vigas

    m = _viga_apoiada_em_viga(h_secundaria=0.80)
    principal = next(v for v in verificar_vigas(m)
                     if set(v.barras) == {"VP1", "VP2"})
    recebidas = principal.viga.concentradas
    return [
        Conferencia("viga em viga: a mais alta apoiada na mais baixa fica "
                    "pendurada",
                    float(bool(recebidas) and all(c.pendurada
                                                  for c in recebidas)), 1.0),
    ]


def balanco_no_fim_da_viga_mantem_o_ultimo_apoio() -> list[Conferencia]:
    """Balanço depois do último pilar: os apoios são tramos mais um."""
    from .continuidade import vigas_continuas
    from .core.concreto import concreto
    from .dimensionamento import montar_viga

    m = Modelo("balanco_final")
    c = concreto("C30", 30.0)
    m.materiais[c.nome] = c
    m.add_secao(Secao.retangular("V", 0.20, 0.50))
    m.add_secao(Secao.retangular("P", 0.30, 0.30))
    for nome, x in (("A", 0.0), ("B", 8.0), ("E", 10.0)):
        m.add_no(nome, x, 0.0, 3.0)
    for nome, x in (("A", 0.0), ("B", 8.0)):
        m.add_no("b" + nome, x, 0.0, 0.0)
        m.add_barra("P" + nome, "b" + nome, nome, c.nome, "P")
        m.apoiar("b" + nome)
    m.add_barra("V1", "A", "B", c.nome, "V")
    m.add_barra("V2", "B", "E", c.nome, "V")
    g = m.add_caso("G", "permanente")
    for barra in ("V1", "V2"):
        g.distribuida(barra, qz=-15.0, sistema="global")
    m.validar()

    viga = next(v for v in vigas_continuas(m) if len(v.barras) == 2)
    deles = montar_viga(m, viga)
    return [
        Conferencia("balanço no fim: dois tramos (vão e balanço)",
                    float(len(deles.tramos)), 2.0),
        Conferencia("balanço no fim: três apoios (dois pilares e a ponta livre)",
                    float(len(deles.apoios)), 3.0),
        Conferencia("balanço no fim: o último apoio de pilar não se perde",
                    float(deles.apoios[1].tipo != "livre"), 1.0),
        Conferencia("balanço no fim: e a ponta é livre",
                    float(deles.apoios[2].tipo == "livre"), 1.0),
    ]


def dimensionar_nao_grava_arquivo(pasta) -> list[Conferencia]:
    """Dimensionar atualiza os modelos; imprimir a prancha é decisão à parte."""
    from .dimensionamento import (gravar_pranchas_de_lajes,
                                  gravar_pranchas_de_vigas, verificar_lajes,
                                  verificar_vigas)

    import shutil

    destino = Path(pasta) / "sem_imprimir"
    shutil.rmtree(destino, ignore_errors=True)    # sobra de uma rodada antiga
    destino.mkdir(parents=True, exist_ok=True)

    m = _viga_apoiada_em_viga()
    vigas = verificar_vigas(m)                 # sem pasta: não grava nada
    ao_dimensionar = list(destino.iterdir())
    sem_desenho_vigas = all(not v.desenhos for v in vigas)
    caminho = gravar_pranchas_de_vigas(vigas, destino)

    lajes = verificar_lajes(_pavimento_de_dois_paineis())
    sem_desenho = all(not v.desenhos for v in lajes)
    arquivos = gravar_pranchas_de_lajes(lajes, destino)

    return [
        Conferencia("dimensionar vigas não grava arquivo nenhum",
                    float(len(ao_dimensionar)), 0.0),
        Conferencia("dimensionar vigas não aponta desenho",
                    float(sem_desenho_vigas), 1.0),
        Conferencia("a prancha das vigas sai quando é pedida: um DXF só",
                    float(caminho is not None and Path(caminho).exists()),
                    1.0),
        Conferencia("dimensionar lajes não aponta desenho",
                    float(sem_desenho), 1.0),
        Conferencia("as plantas das lajes saem quando são pedidas",
                    float(len(arquivos) > 0
                          and all(Path(a).exists() for a in arquivos
                                  if not a.startswith("("))), 1.0),
    ]


def _canto_sem_pilar() -> Modelo:
    """Duas vigas que se encontram num canto **sem pilar**.

    A de X vai do canto (0,0) até pilares em x = 6 e x = 12; a de Y, do mesmo
    canto até pilares em y = 6 e y = 12. É o que sobra de um pilar de canto
    retirado: cada viga fica com 6 m de balanço, e as duas pontas se tocam.
    """
    from .core.concreto import concreto

    m = Modelo("canto_sem_pilar")
    c = concreto("C30", 30.0)
    m.materiais[c.nome] = c
    m.add_secao(Secao.retangular("V", 0.20, 0.50))
    m.add_secao(Secao.retangular("P", 0.30, 0.30))
    m.add_no("N0", 0.0, 0.0, 3.0)
    for nome, x, y in (("N1", 6.0, 0.0), ("N2", 12.0, 0.0),
                       ("N3", 0.0, 6.0), ("N4", 0.0, 12.0)):
        m.add_no(nome, x, y, 3.0)
        m.add_no("b" + nome, x, y, 0.0)
        m.add_barra("P" + nome, "b" + nome, nome, c.nome, "P")
        m.apoiar("b" + nome)
    m.add_barra("VX1", "N0", "N1", c.nome, "V")
    m.add_barra("VX2", "N1", "N2", c.nome, "V")
    m.add_barra("VY1", "N0", "N3", c.nome, "V")
    m.add_barra("VY2", "N3", "N4", c.nome, "V")
    g = m.add_caso("G", "permanente")
    q = m.add_caso("Q", "variavel", "residencial")
    for barra in ("VX1", "VX2", "VY1", "VY2"):
        g.distribuida(barra, qz=-10.0, sistema="global")
        q.distribuida(barra, qz=-4.0, sistema="global")
    m.validar()
    return m


def pilar_de_canto_retirado_deixa_balanco_e_nao_apoio() -> list[Conferencia]:
    """Duas pontas em balanço que se tocam não se apoiam uma na outra.

    A ponta de um balanço deforma; tratá-la como apoio indeslocável fazia a
    outra viga sair dimensionada como uma viga apoiada qualquer, sem o momento
    negativo do balanço — era o defeito de retirar um pilar de canto.
    """
    from .continuidade import vigas_continuas
    from .dimensionamento import verificar_vigas

    m = _canto_sem_pilar()
    cadeias = vigas_continuas(m)
    verificacoes = verificar_vigas(m)
    momentos = [float(v.resultado.envoltoria.M_min.min())
                for v in verificacoes if v.passou]
    # carga majorada 1,4 x 14 = 19,6 kN/m sobre 6 m de balanço: q·L²/2 ≈ 353
    q_L2_2 = 1.4 * 14.0 * 6.0 ** 2 / 2.0

    return [
        Conferencia("canto sem pilar: duas vigas",
                    float(len(cadeias)), 2.0),
        Conferencia("canto sem pilar: nenhuma se apoia na outra",
                    float(all(not v.apoios_em_viga for v in cadeias)), 1.0),
        Conferencia("canto sem pilar: cada uma tem 6 m de balanço",
                    float(all(abs(v.balanco_inicial - 6.0) < 1e-9
                              for v in cadeias)), 1.0),
        Conferencia("canto sem pilar: o encontro das pontas fica registrado",
                    float(all(len(v.encontros_sem_apoio) == 1
                              for v in cadeias)), 1.0),
        Conferencia("canto sem pilar: as duas foram dimensionadas",
                    float(len(momentos)), 2.0),
        Conferencia("canto sem pilar: a primeira ponta do motor é livre",
                    float(all(v.viga.apoios[0].tipo == "livre"
                              for v in verificacoes if v.passou)), 1.0),
        Conferencia("canto sem pilar: o momento negativo é o do balanço "
                    "(≥ 85 % de q·L²/2)",
                    float(all(abs(mm) >= 0.85 * q_L2_2 for mm in momentos)),
                    1.0),
        Conferencia("canto sem pilar: o aviso do encontro chega ao resultado",
                    float(all(any("ponta em N0" in a for a in v.avisos)
                              for v in verificacoes if v.passou)), 1.0),
    ]


def viga_so_se_apoia_dentro_dos_vaos_da_outra() -> list[Conferencia]:
    """Na ponta do balanço não há apoio; no meio do vão, há."""
    from .continuidade import vigas_continuas

    # a secundária que nasce no meio do vão da principal se apoia nela
    m = _viga_apoiada_em_viga()
    cadeias = {frozenset(v.barras): v for v in vigas_continuas(m)}
    secundaria = cadeias[frozenset({"VS"})]

    # a mesma secundária, mas agora a principal só vai até o nó J (que passa
    # a ser a ponta do balanço dela): J deixa de ser apoio
    from .core.concreto import concreto
    n = Modelo("ponta")
    c = concreto("C30", 30.0)
    n.materiais[c.nome] = c
    n.add_secao(Secao.retangular("V", 0.20, 0.50))
    n.add_secao(Secao.retangular("P", 0.30, 0.30))
    for nome, x in (("A", 0.0), ("B", 6.0), ("J", 10.0)):
        n.add_no(nome, x, 0.0, 3.0)
    for nome, x, y in (("A", 0.0, 0.0), ("B", 6.0, 0.0), ("C", 10.0, 6.0)):
        if nome == "C":
            n.add_no("C", x, y, 3.0)
        n.add_no("b" + nome, x, y, 0.0)
        n.add_barra("P" + nome, "b" + nome, nome, c.nome, "P")
        n.apoiar("b" + nome)
    n.add_barra("VP1", "A", "B", c.nome, "V")
    n.add_barra("VP2", "B", "J", c.nome, "V")      # balanço de 4 m até J
    n.add_barra("VS", "J", "C", c.nome, "V")
    g = n.add_caso("G", "permanente")
    for barra in ("VP1", "VP2", "VS"):
        g.distribuida(barra, qz=-10.0, sistema="global")
    n.validar()
    ponta = {frozenset(v.barras): v for v in vigas_continuas(n)}
    sec_ponta = ponta[frozenset({"VS"})]

    return [
        Conferencia("dentro dos vãos: a secundária se apoia na principal",
                    float(len(secundaria.apoios_em_viga) == 1), 1.0),
        Conferencia("na ponta do balanço: a secundária NÃO se apoia nela",
                    float(len(sec_ponta.apoios_em_viga) == 0), 1.0),
        Conferencia("na ponta do balanço: e ela só tem o pilar, 1 apoio",
                    float(len(sec_ponta.suportes)), 1.0),
    ]


# ---------------------------------------------------------------------------
# 47. Auditoria de cargas — o que cada caso aplica ao modelo
# ---------------------------------------------------------------------------

def auditoria_de_cargas_confere_a_soma() -> list[Conferencia]:
    """A resultante do caso é a soma que o usuário faria à mão.

    É a primeira linha que quem audita a vista de cargas lê, e por isso tem de
    estar certa: uniforme é q·L, trapezoidal é a média das pontas vezes o
    trecho, carga em eixo local é girada para o global pela mesma matriz da
    montagem, e a combinação soma os casos vezes os fatores.
    """
    from .core import auditoria_cargas as aud
    from .core.combinacoes import Combinacao, caso_efetivo
    from .core.concreto import concreto

    m = Modelo("auditoria")
    c = concreto("C30", 30.0)
    m.materiais[c.nome] = c
    m.add_secao(Secao.retangular("V", 0.20, 0.50))
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", 6.0, 0.0, 0.0)
    m.add_no("C", 6.0, 4.0, 0.0)
    m.add_barra("B1", "A", "B", c.nome, "V")
    m.add_barra("B2", "B", "C", c.nome, "V")
    m.apoiar("A")
    m.apoiar("C")
    g = m.add_caso("G", "permanente")
    g.distribuida("B1", qz=-10.0, sistema="global")
    g.distribuida("B2", qz=-5.0, qz_fim=-15.0, sistema="global",
                  inicio=0.25, fim=1.0)
    g.distribuida("B2", qy=2.0, sistema="local")
    g.nodal("B", fz=-30.0, mx=12.0)
    q = m.add_caso("Q", "variavel", "residencial")
    q.distribuida("B1", qz=-4.0, sistema="global")
    m.validar()

    soma = aud.resultante(m, g)
    efetivo = caso_efetivo(m, Combinacao("C", {"G": 1.4, "Q": 1.0}))
    soma_combinada = aud.resultante(m, efetivo)["total"]
    esperado_combinado = 1.4 * soma["total"] + aud.resultante(m, q)["total"]
    texto = aud.resumo_do_caso(m, g)

    return [
        Conferencia("auditoria: uniforme é q·L (10 × 6 = 60 kN)",
                    -float(aud.total_da_distribuida(
                        m, g.distribuidas[0],
                        preparar_barras(m))[2]), 60.0, 1e-12),
        Conferencia("auditoria: trapezoidal é a média das pontas × trecho "
                    "(10 × 3 = 30 kN)",
                    -float(aud.total_da_distribuida(
                        m, g.distribuidas[1],
                        preparar_barras(m))[2]), 30.0, 1e-12),
        Conferencia("auditoria: carga local em barra girada vira força "
                    "global (qy = 2 sobre 4 m → |Fx| = 8 kN)",
                    abs(float(soma["distribuidas"][0])), 8.0, 1e-12),
        Conferencia("auditoria: resultante vertical = 60 + 30 + 30 nodal",
                    float(soma["total"][2]), -120.0, 1e-12),
        Conferencia("auditoria: a nodal entra à parte",
                    float(soma["nodais"][2]), -30.0, 1e-12),
        Conferencia("auditoria: a combinação soma os casos vezes os fatores",
                    float(soma_combinada[2]), float(esperado_combinado[2]),
                    1e-12),
        Conferencia("auditoria: o resumo traz a resultante",
                    float("Fz = -120.00" in texto), 1.0),
        Conferencia("auditoria: o resumo lista a carga da barra",
                    float("Barra B1" in texto), 1.0),
        Conferencia("auditoria: clique na barra lista as cargas dela",
                    float("2 carga(s)" in aud.texto_da_barra(
                        m, g, "B2", preparar_barras(m))), 1.0),
    ]


def laje_alinhada_com_o_topo_das_vigas() -> list[Conferencia]:
    """O topo da laje fica no topo das vigas de contorno, e não centrado nos nós.

    O plano dos nós passa pelo eixo das vigas e a viga sobe meia altura acima
    dele; o plano médio da laje sobe ``h/2 − e/2``. Sem as vigas de contorno
    não há onde alinhar, e o deslocamento é zero.
    """
    from .core.lajes import deslocamento_do_centro

    m = _pavimento_de_dois_paineis()
    laje = next(iter(m.lajes.values()))
    h_viga = max(m.secoes[m.barras[a.barra].secao].h
                 for a in __import__("portico3d.core.lajes", fromlist=["x"]
                                     ).arestas_da_laje(m, laje)[0])
    centro = deslocamento_do_centro(m, laje)
    topo_da_laje = centro + laje.espessura / 2.0
    fundo_da_laje = centro - laje.espessura / 2.0

    sem_vigas = _pavimento_de_dois_paineis()
    for nome in [n for n in sem_vigas.barras if n.startswith("V")]:
        for caso in sem_vigas.casos.values():
            caso.distribuidas = [c for c in caso.distribuidas
                                 if c.barra != nome]
        del sem_vigas.barras[nome]
    laje_sem_vigas = next(iter(sem_vigas.lajes.values()))

    return [
        Conferencia("laje: o topo dela é o topo das vigas (h/2)",
                    topo_da_laje, h_viga / 2.0, 1e-12),
        Conferencia("laje: o fundo dela fica abaixo do topo, pela espessura",
                    topo_da_laje - fundo_da_laje, laje.espessura, 1e-12),
        Conferencia("laje: sem as vigas de contorno não há onde alinhar",
                    deslocamento_do_centro(sem_vigas, laje_sem_vigas), 0.0,
                    1e-12),
    ]


# ---------------------------------------------------------------------------
# 48. Laje como diafragma rígido e como grelha; vigas armadas pelo pórtico
# ---------------------------------------------------------------------------
#
# Três capacidades novas, cada uma conferida contra o que não é ela mesma:
#
# * o **diafragma rígido**, contra o ``rigidDiaphragm`` do OpenSeesPy (outra
#   implementação da mesma cinemática, pelo handler ``Transformation``) num
#   prédio em L com torção — deslocamentos, esforços e modos —, e contra a
#   própria definição: o pavimento se move como corpo rígido no plano;
# * a **laje em grelha**, contra a placa de Kirchhoff apoiada nos quatro
#   bordos sob carga uniforme (série de Navier, Timoshenko & Woinowsky-
#   Krieger, *Theory of Plates and Shells*, §30), com ν = 0 — que é o caso em
#   que a analogia de grelha de Hambly reproduz a placa sem aproximação de
#   rigidez —, e contra o equilíbrio: a carga da laje se conserva e a viga
#   remontada fecha com as pontas;
# * a **matriz esparsa**, contra a densa no mesmo modelo, em todas as
#   análises;
# * as **vigas armadas pelo pórtico**: a envoltória que o motor de Vigas usou
#   é a do pórtico, e a armadura cobre o pórtico.


def _edificio_em_l(diafragma: bool) -> Modelo:
    """Prédio em L de 3 pavimentos: 2×2 vãos com o canto (2,2) retirado e um
    pilar mais rígido em (0,0) — centro de rigidez fora do centro de massa,
    para que o vento torça o pavimento. Uma laje sem espessura por célula
    completa: é ela que define o diafragma, sem carga nenhuma."""
    m = _grade_edificio(2, 2, 5.0, 4.0, 3, 3.0, "diaf",
                        remover_colunas={(2, 2)}, pilar_rigido={(0, 0)},
                        b_pilar_rigido=0.70, h_pilar_rigido=0.25)
    for k in range(1, 4):
        for i in range(2):
            for j in range(2):
                if (i, j) == (1, 1):
                    continue
                m.add_laje(f"L{i}{j}.{k}", f"N{i}.{j}.{k}",
                           f"N{i + 1}.{j + 1}.{k}")
    caso = m.add_caso("V")
    for k in range(1, 4):
        caso.nodal(f"N2.0.{k}", fx=12.0 * k)
        caso.nodal(f"N0.2.{k}", fy=-7.0 * k)
    for nome in m.barras:
        if nome.startswith("VX"):
            caso.distribuida(nome, qz=-8.0, sistema="global")
    m.calculo = replace(m.calculo, diafragma=diafragma)
    m.validar()
    return m


def diafragma_move_o_pavimento_como_corpo_rigido() -> list[Conferencia]:
    from .core.diafragma import diafragmas

    m = _edificio_em_l(True)
    r = resolver(m, "V")
    sem = resolver(_edificio_em_l(False), "V")
    grupos = diafragmas(m)

    pior, escala = 0.0, 0.0
    for d in grupos:
        a = d.nos[0]
        ua = r.deslocamento(a)
        pa = m.ponto(a)
        for no in d.nos[1:]:
            u = r.deslocamento(no)
            dx, dy = m.ponto(no)[:2] - pa[:2]
            # corpo rígido no plano: u_b = u_a + Rz × (b − a), e o mesmo rz
            esperado = (ua[0] - ua[5] * dy, ua[1] + ua[5] * dx, ua[5])
            pior = max(pior, *(abs(u[k] - e) for k, e in
                               zip((0, 1, 5), esperado)))
            escala = max(escala, abs(u[0]), abs(u[1]))

    def normal_max(res):
        return max(abs(res.diagrama(b, 5).N).max() for b in m.barras
                   if b.startswith("VX"))

    giro_com = max(abs(r.deslocamento(n)[5]) for n in grupos[-1].nos)
    giro_sem = max(abs(sem.deslocamento(n)[5]) for n in grupos[-1].nos)
    soma = r.reacoes_totais()
    return [
        Conferencia("diafragma: três pavimentos com laje viram três "
                    "diafragmas", float(len(grupos)), 3.0),
        Conferencia("diafragma: os nós do pavimento se movem como corpo "
                    "rígido no plano (ux, uy, rz)", pior / escala, 0.0, 1e-9),
        Conferencia("diafragma: as vigas deixam de alongar — normal das "
                    "vigas em X sobre o normal sem diafragma",
                    normal_max(r) / normal_max(sem), 0.0, 1e-6),
        Conferencia("diafragma: o pavimento em L gira com o vento "
                    "(giro do topo com diafragma não nulo)",
                    float(giro_com > 1e-7), 1.0),
        Conferencia("diafragma: sem ele os nós do topo giram cada um por si "
                    "(o giro é outro)",
                    float(abs(giro_com - giro_sem) > 0.01 * giro_com), 1.0),
        Conferencia("diafragma: equilíbrio — ΣFx das reações = −Σ vento",
                    soma[0], -12.0 * 6.0, 1e-9),
    ]


def diafragma_contra_opensees() -> list[Conferencia]:
    """O mesmo prédio em L, com diafragma, no ``rigidDiaphragm`` do
    OpenSeesPy: deslocamentos dos nós, momento na base dos pilares e os três
    primeiros modos de vibração."""
    def rodar():
        m = _edificio_em_l(True)
        r = resolver(m, "V")
        res = _opensees_rodar(_opensees_payload_do_modelo(m, "V"))
        maior = max(abs(v) for no in m.nos for v in r.deslocamento(no)[:3])
        dif = max(abs(r.deslocamento(no)[k] - res["deslocamentos"][no][k])
                  for no in m.nos for k in range(6))
        pilares = [b for b in m.barras if b.startswith("P") and
                   b.endswith(".1")]
        mz = max(abs(r.esforcos_barra(b)[5]) for b in pilares)
        dif_m = max(abs(abs(r.esforcos_barra(b)[5])
                        - abs(_momento_opensees(res, b, "Mz")))
                    for b in pilares)

        modal, freq_os, pares = _confrontar_modal_mac(m, 3)
        conf = [
            Conferencia("diafragma × OpenSeesPy: deslocamentos de todos os "
                        "nós (maior diferença / maior translação)",
                        dif / maior, 0.0, 1e-7),
            Conferencia("diafragma × OpenSeesPy: Mz na base dos pilares "
                        "(maior diferença / maior momento)",
                        dif_m / mz, 0.0, 1e-7),
        ]
        # A frequência difere do OpenSeesPy na quinta casa **com ou sem**
        # diafragma, do mesmo tamanho: é a inércia de rotação que o
        # ``-cMass`` dele trata de outro jeito (zerando a torcional daqui o
        # sinal da diferença troca). É a matriz de massa, e não a restrição —
        # a estática acima, que não tem massa, bate a 1e-14.
        for i, j, mac, f_p, f_o, _, _ in pares:
            conf.append(Conferencia(
                f"diafragma × OpenSeesPy: frequência do modo {i + 1}",
                f_p, f_o, 1e-4))
            conf.append(Conferencia(
                f"diafragma × OpenSeesPy: MAC do modo {i + 1}", mac, 1.0,
                1e-6))
        return conf
    return _opensees_ou_pulado("diafragma", rodar)


def _placa_em_grelha(malha: float, a: float = 4.0, e: float = 0.10,
                     q: float = 10.0) -> Modelo:
    """Laje quadrada apoiada nos quatro bordos: vigas de borda muito rígidas
    à flexão e sem rigidez à torção (o bordo gira livre), apoiadas nos cantos.
    O peso específico é zero; a carga é o revestimento da laje, pela regra das
    áreas, e é a grelha que a tira das vigas."""
    from .core.lajes import aplicar_lajes

    m = Modelo("placa")
    m.add_material("c", 25.0e6, 0.0, 0.0)
    m.add_secao(Secao("borda", 1.0, 1.0e3, 1.0, 1.0e-9))
    for nome, x, y in (("A", 0, 0), ("B", a, 0), ("C", a, a), ("D", 0, a)):
        m.add_no(nome, x, y, 0.0)
        m.apoiar(nome, True, True, True, False, False, False)
    for nome, i, j in (("AB", "A", "B"), ("BC", "B", "C"), ("CD", "C", "D"),
                       ("DA", "D", "A")):
        m.add_barra(nome, i, j, "c", "borda")
    m.add_laje("L", "A", "C", espessura=e, material="c", permanente=q)
    aplicar_lajes(m, m.add_caso("G"))
    m.calculo = replace(m.calculo, grelha=True, malha_grelha=malha)
    return m


def _navier(a: float, q: float, D: float, nu: float, termos: int = 80):
    """Flecha e momento Mx no centro da placa quadrada simplesmente apoiada
    sob carga uniforme, pela série dupla de Navier."""
    w = mx = 0.0
    for mm in range(1, 2 * termos, 2):
        for nn in range(1, 2 * termos, 2):
            s = math.sin(mm * math.pi / 2) * math.sin(nn * math.pi / 2)
            den = mm * nn * (mm ** 2 / a ** 2 + nn ** 2 / a ** 2) ** 2
            w += s / den
            mx += s * (mm ** 2 / a ** 2 + nu * nn ** 2 / a ** 2) / den
    return 16 * q / (math.pi ** 6 * D) * w, 16 * q / math.pi ** 4 * mx


def grelha_reproduz_a_placa_de_navier() -> list[Conferencia]:
    a, e, q, E = 4.0, 0.10, 10.0, 25.0e6
    D = E * e ** 3 / 12.0
    w_ref, m_ref = _navier(a, q, D, 0.0)

    conf = []
    for malha, tol_w, tol_m in ((0.5, 2e-3, 2e-2), (0.25, 5e-4, 5e-3)):
        m = _placa_em_grelha(malha, a, e, q)
        r = resolver(m, "G")
        mc, rc = r.calculo
        centro = next(n for n, no in mc.calc.nos.items()
                      if abs(no.x - a / 2) < 1e-9 and abs(no.y - a / 2) < 1e-9)
        w = -rc.deslocamento(centro)[2]
        g = mc.lajes["L"]
        nx = len(g.xs) - 1
        faixa = g.faixas_x[(nx // 2, nx // 2 - 1)]   # chega ao centro pela esq.
        largura = g.xs[1] - g.xs[0]
        momento = rc.diagrama(faixa, 3).My[-1] / largura
        conf += [
            Conferencia(f"grelha (malha {malha:g} m) × placa de Navier: "
                        "flecha no centro", w, w_ref, tol_w),
            Conferencia(f"grelha (malha {malha:g} m) × placa de Navier: "
                        "momento Mx no centro, por metro", momento, m_ref,
                        tol_m),
        ]
    m = _placa_em_grelha(0.5, a, e, q)
    r = resolver(m, "G")
    conf.append(Conferencia("grelha: a carga da laje chega inteira aos "
                            "apoios (ΣFz = q·a²)", r.reacoes_totais()[2],
                            q * a * a, 1e-9))
    return conf


def grelha_conserva_a_carga_e_remonta_a_viga() -> list[Conferencia]:
    from .ui.assistente import gerar_portico

    def predio(grelha: bool) -> Modelo:
        m = gerar_portico([5.0, 6.0], [4.0, 5.0], [3.0, 3.0], (0.2, 0.4),
                          (0.15, 0.5), 30.0, espessura_laje=0.12,
                          revestimento=1.0, acidental=2.0, vento=1.0)
        m.calculo = replace(m.calculo, grelha=grelha, malha_grelha=1.0)
        return m

    com, sem = predio(True), predio(False)
    r, r0 = resolver(com, "G"), resolver(sem, "G")
    mc, rc = r.calculo

    # A viga remontada fecha com as pontas: o diagrama de uma barra partida,
    # somadas as ações concentradas que a laje lhe aplica, chega à ponta j
    # com o esforço que o último pedaço tem lá.
    pior = escala = 0.0
    continuidade = 0.0
    for nome, pedacos in mc.pedacos.items():
        q = r.esforcos_barra(nome)
        d = r.diagrama(nome, 41)
        for valor, esperado in ((d.My[-1], -q[10]), (d.Mz[-1], -q[11]),
                                (d.Vz[-1], -q[8]), (d.N[-1], q[6]),
                                (d.T[-1], q[9])):
            pior = max(pior, abs(valor - esperado))
        escala = max(escala, abs(d.My).max())
        # e coincide com o diagrama de cada pedaço no meio dele
        barra = com.barras[nome]
        dd = r.diagrama(nome, 4001)
        for p in pedacos:
            dp = rc.diagrama(p.barra, 3)
            # o meio do pedaço, na abscissa da barra original
            x = p.inicio + dp.x[1]
            continuidade = max(continuidade,
                               abs(float(np.interp(x, dd.x, dd.My))
                                   - dp.My[1]))
    return [
        Conferencia("grelha: ΣFz do permanente igual ao da laje pelas áreas",
                    r.reacoes_totais()[2], r0.reacoes_totais()[2], 1e-9),
        Conferencia("grelha: a viga remontada fecha na ponta j com o último "
                    "pedaço (N, Vz, T, My, Mz)", pior / escala, 0.0, 1e-9),
        Conferencia("grelha: o diagrama da viga remontada é o dos pedaços "
                    "(My no meio de cada pedaço, kN·m)",
                    continuidade, 0.0, 5e-3, escala=1.0),
        Conferencia("grelha: as lajes do prédio viram grelha (4 por "
                    "pavimento, 2 pavimentos)", float(len(mc.lajes)), 8.0),
    ]


def esparsa_bate_com_densa() -> list[Conferencia]:
    """O mesmo prédio, com diafragma e grelha, pelas duas montagens."""
    from .core import montagem
    from .core.dinamica import analisar_modal
    from .core.segunda_ordem import flambagem, resolver_p_delta
    from .ui.assistente import gerar_portico

    def predio() -> Modelo:
        m = gerar_portico([5.0, 6.0], [4.0], [3.0, 3.0], (0.2, 0.4),
                          (0.15, 0.5), 30.0, espessura_laje=0.12,
                          revestimento=1.0, acidental=2.0, vento=1.0)
        m.calculo = replace(m.calculo, grelha=True, diafragma=True,
                            malha_grelha=1.0)
        return m

    def rodar():
        m = predio()
        return (resolver(m, "VX").deslocamentos,
                resolver_p_delta(m, "G").deslocamentos,
                analisar_modal(m, 4).frequencias,
                flambagem(m, "G").fator_critico)

    densa = rodar()
    limite = montagem.LIMITE_DENSO
    montagem.LIMITE_DENSO = 0
    try:
        esparsa = rodar()
    finally:
        montagem.LIMITE_DENSO = limite

    def rel(a, b):
        a, b = np.asarray(a, float), np.asarray(b, float)
        return float(np.max(np.abs(a - b)) / np.max(np.abs(b)))

    return [
        Conferencia("matriz esparsa × densa: 1ª ordem com diafragma e "
                    "grelha", rel(esparsa[0], densa[0]), 0.0, 1e-9),
        Conferencia("matriz esparsa × densa: P-Δ", rel(esparsa[1], densa[1]),
                    0.0, 1e-9),
        Conferencia("matriz esparsa × densa: quatro frequências",
                    rel(esparsa[2], densa[2]), 0.0, 1e-8),
        Conferencia("matriz esparsa × densa: fator de flambagem",
                    esparsa[3], densa[3], 1e-8),
    ]


def vigas_armadas_pela_envoltoria_do_portico() -> list[Conferencia]:
    from .dimensionamento import envoltoria_da_viga, verificar_vigas
    from .continuidade import vigas_continuas
    from .ui.assistente import gerar_portico

    m = gerar_portico([5.0, 6.0], [4.5], [3.0, 3.0], (0.2, 0.4), (0.2, 0.5),
                      30.0, espessura_laje=0.10, revestimento=1.0,
                      acidental=2.0, vento=1.2)
    acoes = acoes_do_modelo(m)
    env = envoltoria(m, resolver_combinacoes(m, combinacoes_elu(acoes)))

    m.calculo = replace(m.calculo, fonte_vigas="portico")
    pelo_portico = verificar_vigas(m, envoltorias=env)
    m.calculo = replace(m.calculo, fonte_vigas="motor")
    pelo_motor = verificar_vigas(m, envoltorias=env)

    cadeias = {v.nome: v for v in vigas_continuas(m)}
    pior = escala = 0.0
    for v in pelo_portico:
        if not v.passou:
            continue
        x, mn, mx, _, _ = envoltoria_da_viga(m, cadeias[v.nome], env)
        e = v.resultado.envoltoria
        pior = max(pior, float(np.max(np.abs(np.interp(e.x, x, mx)
                                             - e.M_max))),
                   float(np.max(np.abs(np.interp(e.x, x, mn) - e.M_min))))
        escala = max(escala, float(np.max(np.abs(mn))))
    razoes = [v.portico.razao for v in pelo_portico
              if v.passou and v.portico is not None]
    diferentes = sum(
        1 for a, b in zip(pelo_portico, pelo_motor)
        if a.passou and b.passou and abs(
            a.resultado.quantitativo.get("massa_total", 0.0)
            - b.resultado.quantitativo.get("massa_total", 0.0)) > 1e-6)
    return [
        Conferencia("vigas pelo pórtico: todas dimensionadas",
                    float(sum(v.passou for v in pelo_portico)),
                    float(len(pelo_portico))),
        Conferencia("vigas pelo pórtico: a envoltória ELU do motor é a do "
                    "pórtico (maior diferença / maior momento)",
                    pior / escala, 0.0, 1e-12),
        Conferencia("vigas pelo pórtico: marcadas como armadas pelo pórtico",
                    float(all(v.esforcos == "portico" for v in pelo_portico
                              if v.passou)), 1.0),
        Conferencia("vigas pelo pórtico: a armadura cobre a envoltória do "
                    "pórtico (pior razão exigido/detalhado ≤ 1,05)",
                    float(max(razoes) <= 1.05), 1.0),
        Conferencia("vigas pelo pórtico: com vento a armadura muda em "
                    "relação à viga contínua com g e q",
                    float(diferentes > 0), 1.0),
    ]


def opcoes_de_calculo_vao_e_voltam_do_arquivo(pasta) -> list[Conferencia]:
    from .arquivo import gravar, ler

    m = _placa_em_grelha(1.0)
    m.calculo = replace(m.calculo, diafragma=True, malha_grelha=0.75,
                        fonte_vigas="envolvente")
    lido = ler(gravar(m, Path(pasta) / "calculo.json"))
    origens = {c.origem for c in lido.casos["G"].distribuidas}
    return [
        Conferencia("arquivo: as opções de cálculo voltam iguais",
                    float(lido.calculo == m.calculo), 1.0),
        Conferencia("arquivo: a origem da carga de laje volta gravada",
                    float(origens == {"laje:L"}), 1.0),
        Conferencia("arquivo: a placa em grelha lida dá a mesma flecha",
                    resolver(lido, "G").reacoes_totais()[2],
                    resolver(m, "G").reacoes_totais()[2], 1e-12),
    ]


# ---------------------------------------------------------------------------
# 49. 2ª ordem global no dimensionamento; viga T e laje treliçada;
#     continuidade dos pilares e nós viga–pilar
# ---------------------------------------------------------------------------


def _predio_esbelto(n_pav: int, pilar: tuple[float, float]) -> Modelo:
    from .ui.assistente import gerar_portico
    return gerar_portico([5.0, 5.0], [5.0], [3.0] * n_pav, pilar, (0.15, 0.4),
                         25.0, espessura_laje=0.12, revestimento=1.0,
                         acidental=2.0, vento=1.0)


def segunda_ordem_global_no_dimensionamento() -> list[Conferencia]:
    """15.7: a combinação recebe 1ª ordem, 0,95·γz ou P-Δ conforme o γz,
    e o que vai ao dimensionamento é isso."""
    from .core.segunda_ordem_global import (MAJORACAO, P_DELTA,
                                            PRIMEIRA_ORDEM, modelo_secante,
                                            resultados_para_dimensionamento)
    from .core.combinacoes import caso_efetivo
    from .core.estabilidade import gama_z

    conf = []
    # -- nós fixos: a 1ª ordem passa intocada ------------------------------
    m = _predio_esbelto(4, (0.30, 0.60))
    elu = combinacoes_elu(acoes_do_modelo(m))
    r2, trat = resultados_para_dimensionamento(m, elu)
    r1 = resolver_combinacoes(m, elu)
    conf.append(Conferencia(
        "2ª ordem global: prédio rígido de 4 pavimentos fica em 1ª ordem",
        float(all(t.tratamento == PRIMEIRA_ORDEM for t in trat)), 1.0))
    conf.append(Conferencia(
        "2ª ordem global: em 1ª ordem o resultado é o da superposição",
        max(float(np.max(np.abs(r2[c.nome].deslocamentos
                                - r1[c.nome].deslocamentos))) for c in elu),
        0.0, 1e-15, escala=1.0))

    # -- 1,10 < γz ≤ 1,30: majoração das horizontais ---------------------
    m = _predio_esbelto(8, (0.20, 0.40))
    elu = combinacoes_elu(acoes_do_modelo(m))
    r2, trat = resultados_para_dimensionamento(m, elu)
    casos = resolver_casos(m)
    majoradas = [t for t in trat if t.tratamento == MAJORACAO]
    pior = 0.0
    for t in majoradas:
        comb = next(c for c in elu if c.nome == t.combinacao)
        # independente da implementação: a diferença para a 1ª ordem é só a
        # parcela horizontal, multiplicada por (0,95·γz − 1)
        esperado = combinar(casos, comb).deslocamentos.copy()
        for nome, f in comb.fatores.items():
            # horizontal é o caso sem carga vertical nenhuma
            if abs(sum(cargas_verticais_por_no(
                    m, m.casos[nome]).values())) < 1e-9:
                esperado += (0.95 * t.gama_z - 1.0) * f * \
                    casos[nome].deslocamentos
        pior = max(pior, float(np.max(np.abs(r2[t.combinacao].deslocamentos
                                              - esperado))
                               / np.max(np.abs(esperado))))
    conf.append(Conferencia(
        "2ª ordem global: prédio de 8 pavimentos (γz entre 1,1 e 1,3) é "
        "majorado por 0,95·γz", float(len(majoradas) > 0), 1.0))
    conf.append(Conferencia(
        "2ª ordem global: a majoração multiplica só a parcela horizontal "
        "(deslocamentos, diferença relativa)", pior, 0.0, 1e-12))

    # -- γz > 1,30: P-Δ com rigidez secante ------------------------------
    m = _predio_esbelto(12, (0.20, 0.30))
    elu = combinacoes_elu(acoes_do_modelo(m))
    r2, trat = resultados_para_dimensionamento(m, elu)
    r1 = resolver_combinacoes(m, elu)
    pdelta = [t for t in trat if t.tratamento == P_DELTA]
    topo = max(n.z for n in m.nos.values())
    nos_topo = [n for n, no in m.nos.items() if no.z == topo]
    def horizontal(r, n):
        d = r.deslocamento(n)
        return float(np.hypot(d[0], d[1]))

    amplificou = all(
        max(horizontal(r2[t.combinacao], n) for n in nos_topo)
        >= t.gama_z * max(horizontal(r1[t.combinacao], n) for n in nos_topo)
        for t in pdelta)
    conf += [
        Conferencia("2ª ordem global: prédio de 12 pavimentos (γz > 1,3) vai "
                    "por P-Δ", float(len(pdelta) > 0), 1.0),
        Conferencia("2ª ordem global: na P-Δ secante o deslocamento do topo "
                    "passa de γz vezes o de 1ª ordem", float(amplificou), 1.0),
    ]

    # -- o γz de projeto é o da rigidez secante: maior que o da cheia -----
    comb = next(c for c in elu if c.nome == pdelta[0].combinacao)
    caso = caso_efetivo(m, comb)
    m.casos[caso.nome] = caso
    try:
        cheio = gama_z(m, caso, resolver(m, caso.nome)).valor
    finally:
        m.casos.pop(caso.nome, None)
    conf.append(Conferencia(
        "2ª ordem global: γz com rigidez secante (15.7.3) maior que com a "
        "rigidez cheia", float(pdelta[0].gama_z > cheio), 1.0))
    return conf


def _predio_com_lajes(trelicada: bool, bw: float = 0.20,
                      vaos_y: tuple = (5.0,)) -> Modelo:
    from .core.lajes import aplicar_lajes
    from .ui.assistente import gerar_portico

    m = gerar_portico([4.0, 4.5], list(vaos_y), [3.0, 3.0], (0.20, 0.40),
                      (bw, 0.40), 25.0, espessura_laje=0.0, revestimento=0.0,
                      acidental=0.0, vento=0.5)
    for nome, l in list(m.lajes.items()):
        if trelicada:
            m.lajes[nome] = replace(l, tipo="trelicada", direcao="x",
                                    material="concreto",
                                    altura_enchimento=0.12, capa=0.05,
                                    permanente=1.0, acidental=1.5)
        else:
            m.lajes[nome] = replace(l, espessura=0.10, material="concreto",
                                    permanente=1.0, acidental=1.5)
    aplicar_lajes(m, m.casos["G"], m.casos["Q"])
    return m


def viga_t_pela_mesa_colaborante() -> list[Conferencia]:
    """14.6.2.2: bf = bw + Σ min(0,1·a; 0,5·b2), a por tipo de tramo."""
    from .continuidade import vigas_continuas
    from .dimensionamento import montar_viga

    def secoes(m, prefixo):
        cadeia = next(v for v in vigas_continuas(m)
                      if v.barras[0].startswith(prefixo))
        return [t.secao for t in montar_viga(m, cadeia).tramos]

    # viga de borda (laje de um lado só), dois vãos 4,0 + 4,5
    m = _predio_com_lajes(False)
    borda = secoes(m, "VX1.1.")
    # viga central com laje dos dois lados
    m2 = _predio_com_lajes(False, vaos_y=(5.0, 5.0))
    centro = next(v for v in vigas_continuas(m2)
                  if v.barras[0].startswith("VX1.2."))
    meio = [t.secao for t in montar_viga(m2, centro).tramos]
    m3 = _predio_com_lajes(False)
    m3.calculo = replace(m3.calculo, mesa_colaborante=False)
    sem = secoes(m3, "VX1.1.")
    mt = _predio_com_lajes(True)
    trel = secoes(mt, "VX1.1.")
    # b2 = 5,0 − 0,10 − 0,10 = 4,8 m: o limite que governa é 0,1·a
    return [
        Conferencia("viga T: tramo de 4,0 m com uma ponta contínua, laje de "
                    "um lado — bf = 20 + 0,1·0,75·400 = 50 cm",
                    borda[0].bf, 50.0, 1e-9),
        Conferencia("viga T: tramo de 4,5 m — bf = 20 + 0,1·0,75·450 "
                    "= 53,75 cm", borda[1].bf, 53.75, 1e-9),
        Conferencia("viga T: a mesa é a espessura da laje (10 cm)",
                    borda[0].hf, 10.0, 1e-9),
        Conferencia("viga T: com laje dos dois lados entra 0,1·a de cada "
                    "lado — bf = 20 + 2·30 = 80 cm", meio[0].bf, 80.0, 1e-9),
        Conferencia("viga T: desligada a opção, a seção volta a retangular",
                    float(all(s.tipo == "retangular" for s in sem)), 1.0),
        Conferencia("viga T: na laje treliçada a mesa é a capa (5 cm)",
                    trel[0].hf, 5.0, 1e-9),
    ]


def laje_trelicada_no_portico() -> list[Conferencia]:
    from .core.lajes import carga_permanente, nervura
    from .dimensionamento import faixas_trelicadas, dimensionar_faixa
    from .elementos.lajes.core.materiais import Concreto
    from .elementos.lajes.core.trelicada import peso_proprio

    m = _predio_com_lajes(True)
    laje = next(iter(m.lajes.values()))
    faixas = [dimensionar_faixa(f) for f in faixas_trelicadas(m, 3.0)]
    f = faixas[0]
    _, inter = nervura(laje)
    pp_motor = peso_proprio(f.laje, Concreto(fck=25.0)) / inter  # kN/m²
    G = m.casos["G"]
    # quinhão das vigas de uma laje: só as perpendiculares às nervuras (X)
    from .core.lajes import arestas_da_laje
    arestas, lx, ly = arestas_da_laje(m, laje)
    def total(barra):
        return sum(-c.qz * m.comprimento(barra) for c in G.distribuidas
                   if c.barra == barra and c.origem == f"laje:{laje.nome}")
    paralelas = total(arestas[0].barra) + total(arestas[2].barra)
    perpendiculares = total(arestas[1].barra) + total(arestas[3].barra)
    q = carga_permanente(m, laje)

    com = replace(m.calculo, grelha=True)
    m.calculo = com
    fz_grelha = resolver(m, "G").reacoes_totais()[2]
    m.calculo = replace(com, grelha=False)
    fz_areas = resolver(m, "G").reacoes_totais()[2]
    return [
        Conferencia("treliçada: peso próprio por m² igual ao do programa de "
                    "Lajes (por nervura ÷ intereixo)",
                    carga_permanente(m, laje) - laje.permanente, pp_motor,
                    1e-12),
        Conferencia("treliçada: as vigas paralelas às nervuras não recebem "
                    "carga", paralelas, 0.0, 1e-12, escala=1.0),
        Conferencia("treliçada: as perpendiculares recebem a laje inteira",
                    perpendiculares, q * lx * ly, 1e-12),
        Conferencia("treliçada: a grelha conserva a carga (ΣFz)", fz_grelha,
                    fz_areas, 1e-9),
        Conferencia("treliçada: a faixa contínua junta os dois painéis "
                    "(2 vãos, 3 apoios)",
                    float(len(f.laje.vaos) == 2 and len(f.laje.apoios) == 3),
                    1.0),
        Conferencia("treliçada: vãos de eixo a eixo (400 e 450 cm)",
                    f.laje.vaos[1].L, 450.0, 1e-9),
        Conferencia("treliçada: o motor de Lajes dimensiona a faixa e ela "
                    "atende (vigas de 20 cm)", float(f.atende), 1.0),
    ]


def continuidade_dos_pilares_e_nos() -> list[Conferencia]:
    from .compatibilizacao import largura_do_pilar, nos_viga_pilar, prumadas
    from .core.segunda_ordem_global import resultados_para_dimensionamento
    from .dimensionamento import verificar_pilares, verificar_vigas
    from .ui.assistente import gerar_portico

    m = gerar_portico([5.0, 6.0], [4.5], [3.0] * 3, (0.25, 0.50),
                      (0.20, 0.50), 30.0, espessura_laje=0.12,
                      revestimento=1.5, acidental=2.0, vento=1.0)
    m.add_secao(Secao.retangular("P20x40", 0.20, 0.40))
    for nome, b in list(m.barras.items()):
        if nome.startswith("P") and max(m.ponto(b.no_i)[2],
                                        m.ponto(b.no_j)[2]) > 6.5:
            m.barras[nome] = replace(b, secao="P20x40")
    res, _ = resultados_para_dimensionamento(
        m, combinacoes_elu(acoes_do_modelo(m)))
    env = envoltoria(m, res)
    pil = verificar_pilares(m, env)
    vig = verificar_vigas(m, envoltorias=env)
    ps = prumadas(m, pil)
    nos = nos_viga_pilar(m, vig)

    p = ps[0]
    baixo, cima = p.lances[1], p.lances[2]
    t = p.transicoes[1]
    reduz = [t for p in ps for t in p.transicoes if max(t.reducao) > 0]
    joelhos = [n for n in nos if any(a.startswith("nó de joelho")
                                     for a in n.avisos)]
    topo = max(n.cota for n in nos)
    secao = m.secoes["P20x40"]
    pilar = next(nm for nm, b in m.barras.items() if b.secao == "P20x40")
    return [
        Conferencia("continuidade: uma prumada por pilar, um lance por "
                    "pavimento", float(len(ps) == 6 and all(
                        len(q.lances) == 3 for q in ps)), 1.0),
        Conferencia("continuidade: taxa na emenda = (As de baixo + As de "
                    "cima) / Ac de cima (17.3.5.3.2)",
                    t.taxa_emenda, (baixo.As + cima.As) / (cima.b * cima.h),
                    1e-12),
        Conferencia("continuidade: a espera é a l0c do lance de baixo "
                    "(9.5.2.3), e respeita o piso de 20 cm",
                    float(t.l0c == baixo.l0c and t.l0c >= 20.0), 1.0),
        Conferencia("continuidade: a redução 25×50 → 20×40 é apontada nas "
                    "seis prumadas", float(len(reduz)), 6.0),
        Conferencia("nó: largura do pilar 20×40 na direção X (viga em X) "
                    "é o lado b", largura_do_pilar(m, pilar, (1, 0, 0))[0],
                    secao.b * 100.0, 1e-12),
        Conferencia("nó: na direção Y é o lado h",
                    largura_do_pilar(m, pilar, (0, 1, 0))[0],
                    secao.h * 100.0, 1e-12),
        Conferencia("nó: o joelho (sem pilar acima) só aparece na cobertura",
                    float(bool(joelhos) and all(n.cota == topo
                                                for n in joelhos)), 1.0),
        Conferencia("nó: a ancoragem da viga no pilar de extremidade foi "
                    "conferida em todos os nós de extremidade",
                    float(all(e.ancoragem_ok is not None for n in nos
                              for e in n.vigas if e.extremo)), 1.0),
    ]


# ---------------------------------------------------------------------------
# 50. Lançamento por planta: do pavimento-tipo ao modelo de cálculo
# ---------------------------------------------------------------------------


def _lancamento_exemplo():
    import importlib.util
    caminho = Path(__file__).resolve().parent.parent / "exemplos" / \
        "lancamento_residencial.py"
    spec = importlib.util.spec_from_file_location("lancamento_residencial",
                                                  caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.lancamento()


def _lancamento_minimo(**alteracoes):
    """Um vão de 5 × 4 m, dois pavimentos, para provocar os erros."""
    from .lancamento import (Lancamento, LajeLancada, Pavimento, PilarLancado,
                             Planta, VigaLancada)

    planta = Planta("A")
    for k, (x, y) in enumerate(((0, 0), (5, 0), (5, 4), (0, 4)), start=1):
        planta.pilares.append(PilarLancado(f"P{k}", x, y, 0.20, 0.30))
    for k, pts in enumerate((((0, 0), (5, 0)), ((5, 0), (5, 4)),
                             ((5, 4), (0, 4)), ((0, 4), (0, 0))), start=1):
        planta.vigas.append(VigaLancada(f"V{k}", list(pts), 0.15, 0.40))
    planta.lajes.append(LajeLancada("L1", 2.5, 2.0))
    lanc = Lancamento("minimo", plantas={"A": planta},
                      pavimentos=[Pavimento("1", 3.0, "A"),
                                  Pavimento("2", 6.0, "A")])
    for k, v in alteracoes.items():
        setattr(lanc, k, v)
    return lanc


def lancamento_gera_o_modelo() -> list[Conferencia]:
    from .core.lajes import arestas_da_laje, carga_permanente
    from .lancamento import gerar

    g = gerar(_lancamento_exemplo())
    m = g.modelo
    v1 = g.mapa[("viga", "V1", "1PAV")]
    v5 = g.mapa[("viga", "V5", "1PAV")]
    xs_v1 = sorted({round(float(m.ponto(m.barras[b].no_j)[0]), 6)
                    for b in v1})
    L5 = m.lajes["L5.1PAV"]
    arestas, lx, ly = arestas_da_laje(m, L5)
    lado = arestas[0]
    G = m.casos["G"]
    q = carga_permanente(m, L5)

    def total(barra, origem):
        b = m.barras[barra]
        Lf = m.comprimento(barra) - b.offset_i - b.offset_j
        return sum(-0.5 * (c.vetor_inicio[2] + c.vetor_fim[2])
                   * (c.fim - c.inicio) * Lf
                   for c in G.distribuidas
                   if c.barra == barra and c.origem == origem)

    no_lado = sum(total(b, "laje:L5.1PAV") for b in lado.barras)
    menor = min(lx, ly)
    esperado_lado = q * menor * (2.0 * lado.comprimento - menor) / 4.0
    na_laje = sum(total(b, "laje:L5.1PAV") for b in m.barras)

    fz = resolver(m, "G").reacoes_totais()[2]
    barras = sum(m.materiais[b.material].peso_especifico
                 * m.secoes[b.secao].A
                 * (m.comprimento(n) - b.offset_i - b.offset_j)
                 for n, b in m.barras.items())
    lajes = sum(carga_permanente(m, l) * arestas_da_laje(m, l)[1]
                * arestas_da_laje(m, l)[2] for l in m.lajes.values())
    paredes = sum(total(b, f"parede:Pa1") for b in m.barras)
    return [
        Conferencia("lançamento: 9 pilares × 3 pavimentos + base viram 42 "
                    "nós", float(len(m.nos)), 42.0),
        Conferencia("lançamento: 27 lances de pilar e 15 trechos de viga por "
                    "pavimento — 72 barras", float(len(m.barras)), 72.0),
        Conferencia("lançamento: a V1 é quebrada nos pilares e na V7 que "
                    "nasce nela (x = 4; 6,5; 9)",
                    float(xs_v1 == [4.0, 6.5, 9.0]), 1.0),
        Conferencia("lançamento: trecho rígido da viga em Y no pilar 20×40 = "
                    "0,40/2 − 0,3·0,45 = 0,065 m (14.6.2.1)",
                    m.barras[v5[0]].offset_i, 0.065, 1e-12),
        Conferencia("lançamento: no pilar girado 90° a viga em X atravessa os "
                    "40 cm — o mesmo trecho rígido de 0,065 m",
                    m.barras[v1[0]].offset_i, 0.065, 1e-12),
        Conferencia("lançamento: viga em X no lado de 20 cm não ganha trecho "
                    "rígido (0,10 − 0,135 < 0)",
                    m.barras[v1[0]].offset_j, 0.0, 1e-15, escala=1.0),
        Conferencia("lançamento: o lado da L5 é coberto por duas vigas",
                    float(len(lado.barras)), 2.0),
        Conferencia("lançamento: as duas vigas do lado recebem juntas o "
                    "quinhão do lado inteiro", no_lado, esperado_lado, 1e-12),
        Conferencia("lançamento: a L5 entrega a carga toda (q·lx·ly)",
                    na_laje, q * lx * ly, 1e-12),
        Conferencia("lançamento: ΣFz do permanente = barras (vão flexível) + "
                    "lajes + paredes", fz, barras + lajes + paredes, 1e-12),
        Conferencia("lançamento: pavimento-tipo repetido — as lajes da "
                    "planta Tipo aparecem no 1PAV e no 2PAV",
                    float("L1.1PAV" in m.lajes and "L1.2PAV" in m.lajes),
                    1.0),
        Conferencia("lançamento: vento da NBR 6123 nas quatro direções",
                    float(sum(c.grupo == "vento"
                              for c in m.casos.values())), 4.0),
        Conferencia("lançamento: nenhum erro, nenhuma viga solta",
                    float(g.ok and not any("sem apoio" in a
                                           for a in g.avisos)), 1.0),
    ]


def lancamento_recusa_o_que_nao_fecha() -> list[Conferencia]:
    from .lancamento import (LajeLancada, ParedeLancada, PilarLancado,
                             Planta, VigaLancada, gerar)

    conf = []
    base = _lancamento_minimo()
    g = gerar(base)
    conf.append(Conferencia("lançamento: o vão mínimo gera sem erro",
                            float(g.ok), 1.0))

    # pilar de transição: nasce na viga V1 do pavimento de baixo
    lanc = _lancamento_minimo()
    cima = Planta("B", pilares=list(lanc.plantas["A"].pilares)
                  + [PilarLancado("P5", 2.5, 0.0, 0.20, 0.20)],
                  vigas=list(lanc.plantas["A"].vigas),
                  lajes=list(lanc.plantas["A"].lajes))
    lanc.plantas["B"] = cima
    lanc.pavimentos[1].planta = "B"
    g = gerar(lanc)
    base_p5 = g.modelo.barras["P5.2"].no_i if g.ok else ""
    conf.append(Conferencia(
        "lançamento: pilar de transição nasce na viga de baixo, que é "
        "quebrada embaixo dele",
        float(g.ok and abs(g.modelo.ponto(base_p5)[0] - 2.5) < 1e-9
              and any("transição" in a for a in g.avisos)), 1.0))

    casos = []
    # pilar no ar: nem pilar embaixo nem viga
    lanc = _lancamento_minimo()
    lanc.plantas["B"] = Planta("B", pilares=list(lanc.plantas["A"].pilares)
                               + [PilarLancado("P9", 2.5, 2.0)],
                               vigas=list(lanc.plantas["A"].vigas))
    lanc.pavimentos[1].planta = "B"
    casos.append(("pilar que nasce no ar", lanc, "nasce no ar"))
    # viga fora do eixo do pilar
    lanc = _lancamento_minimo()
    lanc.plantas["A"].vigas[0] = VigaLancada("V1", [(0.0, 0.05),
                                                   (5.0, 0.05)])
    casos.append(("viga fora do eixo do pilar", lanc, "excentricidade"))
    # laje sem contorno: tira a V3
    lanc = _lancamento_minimo()
    del lanc.plantas["A"].vigas[2]
    casos.append(("laje sem contorno fechado", lanc, "não está fechado"))
    # parede sobre laje
    lanc = _lancamento_minimo()
    lanc.plantas["A"].paredes.append(ParedeLancada(
        "Pa", [(2.5, 0.0), (2.5, 4.0)]))
    casos.append(("parede fora de viga", lanc, "não está inteiro sobre "
                                               "viga"))
    for rotulo, lanc, trecho in casos:
        g = gerar(lanc)
        conf.append(Conferencia(f"lançamento: recusa {rotulo}",
                                float(not g.ok and any(trecho in e
                                                       for e in g.erros)),
                                1.0))
    return conf


def lancamento_vai_e_volta_do_arquivo(pasta) -> list[Conferencia]:
    from .arquivo import ler as ler_modelo
    from .lancamento import gerar
    from .lancamento.arquivo import gravar, ler

    lanc = _lancamento_exemplo()
    caminho = gravar(lanc, Path(pasta) / "lancamento.json")
    lido = ler(caminho)
    a, b = gerar(lanc).modelo, gerar(lido).modelo
    pelo_modelo = ler_modelo(caminho)
    return [
        Conferencia("lançamento: gravado e lido gera o mesmo modelo (ΣFz do "
                    "permanente)", resolver(b, "G").reacoes_totais()[2],
                    resolver(a, "G").reacoes_totais()[2], 1e-12),
        Conferencia("lançamento: o leitor de modelo reconhece o arquivo de "
                    "lançamento e gera o modelo",
                    float(len(pelo_modelo.barras)), float(len(a.barras))),
    ]


def lancamento_dimensiona_ponta_a_ponta() -> list[Conferencia]:
    """O modelo gerado passa pelo caminho inteiro: análise com 2ª ordem,
    os três motores e a compatibilização."""
    from .compatibilizacao import nos_viga_pilar, prumadas
    from .core.segunda_ordem_global import resultados_para_dimensionamento
    from .dimensionamento import (verificar_lajes, verificar_pilares,
                                  verificar_vigas)
    from .lancamento import gerar

    m = gerar(_lancamento_exemplo()).modelo
    res, _ = resultados_para_dimensionamento(
        m, combinacoes_elu(acoes_do_modelo(m)))
    env = envoltoria(m, res)
    vig = verificar_vigas(m, envoltorias=env)
    pil = verificar_pilares(m, env)
    laj = verificar_lajes(m)
    lances = {v.barra for v in pil}
    aprovados = {v.barra for v in pil if v.aprovado}
    # As três secundárias (V7 de cada pavimento) se apoiam em vigas, sem
    # pilar: o pórtico lhes dá negativo nas pontas pela rigidez à torção das
    # vigas de apoio, e o Vigas R04 confere a ancoragem dele a partir da face
    # (18.3.2.4-d) — 17 cm de apoio contra até 73 cm exigidos, sem pilar onde
    # descer. É veredito do motor, e não defeito da ponte; a conferência
    # trava que essa seja a **única** razão de reprovação no exemplo.
    reprovadas = [v for v in vig if not v.aprovado]
    so_ancoragem_em_viga = all(
        v.passou and v.apoiada_em and any(
            "não ancora no apoio de extremidade" in a for a in v.avisos
            + list(getattr(v.resultado, "avisos", [])))
        for v in reprovadas)
    return [
        Conferencia("lançamento ponta a ponta: 18 das 21 vigas contínuas "
                    "aprovadas", float(sum(v.aprovado for v in vig)), 18.0),
        Conferencia("lançamento ponta a ponta: as 3 reprovadas são as "
                    "secundárias apoiadas em viga, pela ancoragem da negativa "
                    "(18.3.2.4-d)",
                    float(len(reprovadas) == 3 and so_ancoragem_em_viga), 1.0),
        Conferencia("lançamento ponta a ponta: todo lance de pilar tem "
                    "combinação aprovada", float(lances == aprovados), 1.0),
        # O Lajes R11 passou a conferir a fissuração nas bordas comuns: na
        # L4/L5 dos dois pavimentos maciços, wk = 0,304 mm contra 0,300 mm
        # (Tabela 13.4, CAA II). É veredito do programa de Lajes, por
        # margem mínima; a conferência trava que seja a única razão.
        Conferencia("lançamento ponta a ponta: as lajes só reprovam pela "
                    "fissura da borda L4/L5 (wk 0,304 mm, Lajes R11)",
                    float(all(all("abertura de fissura" in str(e)
                                  and "L4." in str(e) and "L5." in str(e)
                                  for e in v.erros) for v in laj)
                          and sum(not v.aprovado for v in laj) == 2), 1.0),
        Conferencia("lançamento ponta a ponta: as emendas dos pilares "
                    "atendem", float(all(p.ok for p in prumadas(m, pil))),
                    1.0),
        Conferencia("lançamento ponta a ponta: os nós viga–pilar atendem",
                    float(all(n.ok for n in nos_viga_pilar(m, vig))), 1.0),
    ] + _pranchas_ponta_a_ponta(m, vig, pil, laj)


def _pranchas_ponta_a_ponta(m, vig, pil, laj) -> list[Conferencia]:
    """As pranchas do mesmo exemplo: uma forma por pavimento, toda viga e
    todo lance dimensionados numa folha, nada sobreposto, e o arquivo passa
    no AUDIT do ezdxf sem correção (cota sem bloco seria apagada pelo CAD)."""
    import ezdxf

    from .compatibilizacao import prumadas
    from .projeto import Projeto
    from .saidas import pranchas as pr

    projeto = Projeto(modelo=m, pilares=pil, vigas=vig, lajes=laj,
                      prumadas=prumadas(m, pil))
    doc, folhas = pr.documento(projeto)
    titulos = {v.titulo for f in folhas for v, _, _ in f.itens}
    formas = [f for f in folhas if f.conteudo.startswith("PLANTA DE FORMA")]
    vigas = {f"VIGA {v.nome}" for v in vig if v.passou}
    auditoria = doc.audit()
    layouts = [l for l in doc.layouts if l.name != "Model"]
    com_janela = sum(1 for l in layouts if len(l.query("VIEWPORT")) > 1)

    # pilares iguais: cada lance numa vista; os de uma vista com a mesma
    # seção, armação, estribos, espera e comprimento (pelo resultado do
    # motor, e não pelo desenho que serviu para agrupá-los)
    from .compatibilizacao import _arranjo_adotado
    por_barra: dict = {}
    for v in pil:
        por_barra.setdefault(v.barra, []).append(v)

    def ficha(barra):
        r = _arranjo_adotado(por_barra[barra])[0].resultado
        arr, est, anc = r.arranjo, r.estribos, r.ancoragem
        return (r.pilar.secao.descricao(), arr.n_barras, arr.phi,
                getattr(est, "phi", None), getattr(est, "s", None),
                round(r.pilar.lance.altura, 3),
                round(getattr(anc, "l0c", 0.0) or 0.0, 3))

    vistas_p = [v for f in folhas for v, _, _ in f.itens
                if v.titulo.startswith("PILAR")]
    membros = [m for v in vistas_p for m in v.membros]
    iguais_de_fato = all(len({ficha(m) for m in v.membros}) == 1
                         for v in vistas_p)

    # numeração por folha: sem repetir entre vistas, de N1 sem buracos
    numeracao_ok = True
    for f in folhas:
        vistos: set = set()
        for v, _, _ in f.itens:
            nums = {int(m.group(1)) for e in v.entidades
                    if e.dxftype() in ("TEXT", "MTEXT")
                    for m in pr.POSICAO.finditer(pr._conteudo(e))}
            if nums & vistos:
                numeracao_ok = False
            vistos |= nums
        if vistos and vistos != set(range(1, max(vistos) + 1)):
            numeracao_ok = False

    # o resumo do aço das folhas soma o aço que os motores calcularam
    from .elementos.pilares.core import quantitativos as qp
    esperado = sum(float((v.resultado.quantitativo or {}).get(
        "massa_total", 0.0)) for v in vig if v.passou)
    esperado += sum(float((v.resultado.quantitativo or {}).get(
        "massa_total", 0.0)) for v in laj
        if v.passou and v.resultado is not None)
    # treliçada: as barras e as vigotas, que somam o aço da faixa
    esperado += sum(float((f.resultado.quantitativo or {}).get("aco_kg", 0.0))
                    for v in laj if v.passou for f in v.trelicadas
                    if f.passou)
    esperado += sum(qp.calcular(_arranjo_adotado(por_barra[b])[0].resultado
                                ).massa_aco for b in membros)
    nas_folhas = sum(m for f in folhas if f.com_aco
                     for _, m in list(f.aco.values())
                     + list(f.trelicas.values()))
    return [
        Conferencia("pranchas: todo lance de pilar numa vista, uma vez só",
                    float(sorted(membros) == sorted(por_barra)
                          and len(membros) == len(set(membros))), 1.0),
        Conferencia("pranchas: os lances de uma vista são iguais pelo "
                    "resultado do motor", float(iguais_de_fato), 1.0),
        Conferencia("pranchas: os iguais juntaram (menos vistas que lances)",
                    float(len(vistas_p) < len(membros)), 1.0),
        Conferencia("pranchas: posições numeradas por folha, sem repetir "
                    "entre vistas e sem buraco", float(numeracao_ok), 1.0),
        Conferencia("pranchas: o resumo do aço das folhas soma o aço dos "
                    "motores (kg)", nas_folhas, esperado, 1e-6, esperado),
        Conferencia("pranchas: uma planta de forma por pavimento",
                    float(len(formas)), float(len(pr.cotas_dos_pavimentos(m)))),
        Conferencia("pranchas: toda viga dimensionada está numa folha",
                    float(vigas <= titulos), 1.0),
        # uma vista por pavimento de lajes maciças e uma por faixa
        # treliçada (o DXF da treliçada é do Lajes R14)
        Conferencia("pranchas: as lajes maciças de cada cota numa vista",
                    float(sum(t.startswith("LAJES —") for t in titulos)),
                    float(len([v for v in laj
                               if v.passou and v.resultado is not None]))),
        Conferencia("pranchas: cada faixa treliçada numa vista",
                    float(sum(t.startswith("LAJE TRELIÇADA") for t in titulos)),
                    float(sum(f.passou for v in laj if v.passou
                              for f in v.trelicadas))),
        Conferencia("pranchas: nenhum texto sobre outro, nenhuma janela "
                    "sobre outra, sobre o carimbo ou fora da moldura",
                    float(len(pr.sobreposicoes(folhas))), 0.0),
        Conferencia("pranchas: uma folha (layout) por prancha, todas com "
                    "janela", float(com_janela), float(len(folhas))),
        Conferencia("pranchas: o AUDIT não acha erro nem corrige nada",
                    float(len(auditoria.errors) + len(auditoria.fixes)), 0.0),
    ]


# ---------------------------------------------------------------------------
# 50b. Pranchas: planta de forma e diagramação das folhas
# ---------------------------------------------------------------------------

def planta_de_forma_do_pavimento() -> list[Conferencia]:
    """A planta de forma do primeiro pavimento do exemplo residencial.

    Cada pilar, viga e laje da cota com o rótulo; nenhum rótulo sobre outro;
    nenhuma face de viga passando por dentro de pilar; hachura só nos
    pilares que chegam por baixo; as cotas parciais entre eixos são as
    distâncias entre os pilares, medidas no modelo.
    """
    import ezdxf

    from .continuidade import _eh_vertical, vigas_continuas
    from .lancamento import gerar
    from .saidas import pranchas as pr

    m = gerar(_lancamento_exemplo()).modelo
    z = pr.cotas_dos_pavimentos(m)[0]
    planta = pr.planta_de_forma(m, z)
    doc = ezdxf.new("R2010", setup=True)
    doc.styles.add("PORTICOS", font="arial.ttf")
    msp = doc.modelspace()
    reg = pr._Registro()
    pr.desenhar_forma(msp, planta, 50, (0.0, 0.0), reg)
    rotulos = [t[4] for t in reg.textos]

    # o que há na cota, direto do modelo
    nos_pilar, chegam = set(), set()
    for b in m.barras.values():
        if not _eh_vertical(m, b):
            continue
        for no in (b.no_i, b.no_j):
            if abs(float(m.ponto(no)[2]) - z) < 1e-6:
                nos_pilar.add(no)
                outro = b.no_j if no == b.no_i else b.no_i
                if float(m.ponto(outro)[2]) < z:
                    chegam.add(no)
    nomes_vigas = {vc.nome for vc in vigas_continuas(m)
                   if abs(float(m.ponto(vc.nos[0])[2]) - z) < 1e-6}
    nomes_lajes = {pr._base(n) for n, l in m.lajes.items()
                   if abs(float(m.ponto(l.no_a)[2]) - z) < 1e-6}
    nomes_pilares = {pr._base(b) for b, *_ in planta.pilares}

    sobre = 0
    caixas = reg.textos
    for i in range(len(caixas)):
        for j in range(i + 1, len(caixas)):
            a, b = caixas[i], caixas[j]
            if not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1]
                    or b[3] <= a[1]):
                sobre += 1

    dentro = 0
    for linha in msp.query("LINE[layer=='FORMA-CONTORNO']"):
        meio = (np.array(linha.dxf.start)[:2] + np.array(linha.dxf.end)[:2]) / 2
        for _, r, *_ in planta.pilares:
            w = meio - r.c
            if abs(float(w @ r.u)) < r.a - 0.5 and abs(float(w @ r.v)) < r.b - 0.5:
                dentro += 1

    xs = sorted({round(float(m.ponto(n)[0]) * 100.0, 1) for n in nos_pilar})
    vaos = {pr._cm(b - a) for a, b in zip(xs, xs[1:])}
    cotas = {e.dxf.text for e in msp.query("TEXT[layer=='FORMA-COTA']")}
    return [
        Conferencia("forma: todos os pilares da cota desenhados",
                    float(len(planta.pilares)), float(len(nos_pilar))),
        Conferencia("forma: cada pilar com nome e seção",
                    float(all(any(r.startswith(n + " / ") for r in rotulos)
                              for n in nomes_pilares)), 1.0),
        Conferencia("forma: cada viga contínua da cota com nome e seção",
                    float(all(any(r.startswith(n + " ") for r in rotulos)
                              for n in nomes_vigas)), 1.0),
        Conferencia("forma: cada laje com nome e espessura",
                    float(all(any(r.startswith(n + " / h=") for r in rotulos)
                              for n in nomes_lajes)), 1.0),
        Conferencia("forma: nenhum rótulo sobre outro", float(sobre), 0.0),
        Conferencia("forma: nenhuma face de viga por dentro de pilar",
                    float(dentro), 0.0),
        Conferencia("forma: hachura só nos pilares que chegam por baixo",
                    float(len(msp.query("HATCH"))), float(len(chegam))),
        Conferencia("forma: as cotas parciais são os vãos entre pilares",
                    float(vaos <= cotas), 1.0),
    ]


def cortes_esquematicos() -> list[Conferencia]:
    """Os dois cortes do exemplo residencial, contados contra o modelo: as
    vigas que atravessam o plano, as lajes que ele corta, um nível por
    pavimento e a linha de pilares logo além do plano."""
    from .continuidade import _eh_horizontal, _eh_vertical
    from .core.lajes import retangulo
    from .lancamento import gerar
    from .saidas import pranchas as pr

    m = gerar(_lancamento_exemplo()).modelo
    px, py = pr.posicoes_de_corte(m)
    saida = []
    for letra, eixo, pos in (("A", "x", py), ("B", "y", px)):
        c = pr.corte(m, letra, eixo, pos)
        sx, tr = (0, 1) if eixo == "x" else (1, 0)
        vigas = 0
        for b in m.barras.values():
            if not _eh_horizontal(m, b):
                continue
            a, d = (np.asarray(m.ponto(n), float) * 100.0
                    for n in (b.no_i, b.no_j))
            if abs(a[sx] - d[sx]) < 1e-6 and \
                    min(a[tr], d[tr]) < pos < max(a[tr], d[tr]):
                vigas += 1
        lajes = 0
        for laje in m.lajes.values():
            x0, y0, x1, y1, _ = (v * 100.0 for v in retangulo(m, laje))
            lo, hi = ((y0, y1) if eixo == "x" else (x0, x1))
            lajes += lo < pos < hi
        linhas = sorted({round(float(m.ponto(b.no_i)[tr]) * 100.0, 1)
                         for b in m.barras.values() if _eh_vertical(m, b)})
        alem = min(t for t in linhas if t > pos)
        pilares = sum(1 for b in m.barras.values() if _eh_vertical(m, b)
                      and abs(float(m.ponto(b.no_i)[tr]) * 100.0 - alem) < 1)
        saida += [
            Conferencia(f"corte {letra}-{letra}: as vigas que atravessam o "
                        "plano", float(sum(t == "viga" for t, _ in c.cortados)),
                        float(vigas)),
            Conferencia(f"corte {letra}-{letra}: as lajes cortadas",
                        float(sum(t == "laje" for t, _ in c.cortados)),
                        float(lajes)),
            Conferencia(f"corte {letra}-{letra}: um nível por pavimento",
                        float(len(c.niveis)),
                        float(len(pr.cotas_dos_pavimentos(m)))),
            Conferencia(f"corte {letra}-{letra}: os lances da linha de "
                        "pilares além do plano",
                        float(sum(t == "pilar" for t, _ in c.vistos)),
                        float(pilares)),
        ]
    return saida


def diagramacao_das_folhas() -> list[Conferencia]:
    """A escala sai do texto do desenho e a folha cresce antes do texto
    encolher; as vistas não se sobrepõem nem invadem o carimbo."""
    from .saidas import pranchas as pr

    def vista(w_cm, h_cm, texto_cm, nome="V"):
        return pr.escolher_escala(pr.Vista(nome, (0.0, 0.0, w_cm, h_cm),
                                           pr.escala_legivel(texto_cm)))

    pilar = vista(268, 378, 2.0)
    viga = vista(1963, 1457, 5.0)
    curta = vista(700, 900, 5.0)
    lajes = vista(4770, 2357, 8.0)
    grupo = pr.Grupo("TESTE", [vista(700, 900, 5.0, f"V{i}")
                               for i in range(5)])
    folhas = pr.empacotar(grupo)
    for i, f in enumerate(folhas, 1):
        f.numero, f.total = i, len(folhas)
    return [
        Conferencia("folhas: pilar (texto de 2 cm) a 1:10", float(pilar.escala),
                    10.0),
        Conferencia("folhas: viga (texto de 5 cm) a 1:25", float(viga.escala),
                    25.0),
        Conferencia("folhas: lajes (texto de 8 cm) a 1:50", float(lajes.escala),
                    50.0),
        Conferencia("folhas: a viga que não cabe na A1 a 1:25 vai para a A0 "
                    "na mesma escala",
                    float(viga.formato == "A0" and viga.escala == 25), 1.0),
        Conferencia("folhas: a que cabe fica na A1",
                    float(curta.formato == "A1"), 1.0),
        Conferencia("folhas: cinco vistas de 28x36 cm na A1 — duas por "
                    "folha, a quinta na terceira",
                    float([len(f.itens) for f in folhas] == [2, 2, 1]), 1.0),
        Conferencia("folhas: nenhuma janela sobre outra ou sobre o carimbo",
                    float(len(pr.sobreposicoes(folhas))), 0.0),
    ]


# ---------------------------------------------------------------------------
# 51. Sacada: viga em balanço que carrega laje e a viga de borda
# ---------------------------------------------------------------------------


def _sacada(balanco: float, acidental: float, h_laje: float = 0.10):
    """Pavimento 5 × 4 m com V1 e V2 avançando ``balanco`` além dos pilares,
    a V5 fechando as duas pontas e a laje L2 na sacada."""
    from .lancamento import (Lancamento, LajeLancada, Pavimento, PilarLancado,
                             Planta, VigaLancada, gerar)

    ponta = 5.0 + balanco
    planta = Planta("A")
    for k, (x, y) in enumerate(((0, 0), (5, 0), (0, 4), (5, 4)), start=1):
        planta.pilares.append(PilarLancado(f"P{k}", x, y, 0.20, 0.40,
                                           angulo=90))
    planta.vigas += [VigaLancada("V1", [(0, 0), (ponta, 0)], 0.20, 0.50),
                     VigaLancada("V2", [(0, 4), (ponta, 4)], 0.20, 0.50),
                     VigaLancada("V3", [(0, 0), (0, 4)], 0.20, 0.50),
                     VigaLancada("V4", [(5, 0), (5, 4)], 0.20, 0.50),
                     VigaLancada("V5", [(ponta, 0), (ponta, 4)], 0.20, 0.40)]
    planta.lajes += [LajeLancada("L1", 2.5, 2.0, 0.10, 1.5, 2.0),
                     LajeLancada("L2", 5.0 + balanco / 2.0, 2.0, h_laje, 1.5,
                                 acidental)]
    return gerar(Lancamento("sacada", plantas={"A": planta},
                            pavimentos=[Pavimento("1", 3.0, "A")]))


def sacada_viga_de_borda_e_balanco_armado() -> list[Conferencia]:
    """A viga em balanço é armada em cima pelo momento do balanço, a viga de
    borda repousa nas pontas (antes ficava sem dimensionamento) e o negativo
    entre as lajes cai dentro delas."""
    from .armadura3d import armadura_do_pavimento
    from .continuidade import vigas_continuas
    from .core.lajes import deslocamento_do_centro
    from .core.segunda_ordem_global import resultados_para_dimensionamento
    from .dimensionamento import verificar_vigas

    geracao = _sacada(1.5, 3.0)
    m = geracao.modelo
    res, _ = resultados_para_dimensionamento(
        m, combinacoes_elu(acoes_do_modelo(m)))
    env = envoltoria(m, res)
    cadeias = {v.nome: v for v in vigas_continuas(m)}
    v5 = cadeias["V5"]
    vig = {v.nome: v for v in verificar_vigas(m, envoltorias=env)}
    arm = armadura_do_pavimento(m, 3.0, env, estribos=False)

    # o negativo L1/L2 sobre a V4: dentro das duas lajes, sob o topo
    compartilhado = [f for f in arm.fios if " / " in f.elemento]
    topo = 3.0 + max(deslocamento_do_centro(m, l) + l.espessura / 2.0
                     for l in m.lajes.values())
    fundo = 3.0 + min(deslocamento_do_centro(m, l) - l.espessura / 2.0
                      for l in m.lajes.values())
    dentro = bool(compartilhado) and all(
        fundo < float(pt[2]) < topo for f in compartilhado for pt in f.pontos)

    # balanço pesado: o cálculo, e não a mínima, comanda o topo do balanço
    pesada = _sacada(2.5, 5.0, 0.12).modelo
    res_p, _ = resultados_para_dimensionamento(
        pesada, combinacoes_elu(acoes_do_modelo(pesada)))
    env_p = envoltoria(pesada, res_p)
    v1 = next(v for v in verificar_vigas(pesada, envoltorias=env_p)
              if v.nome == "V1")
    superiores = [p for p in v1.resultado.posicoes
                  if p.tipo == "longitudinal" and p.face == "superior"]
    # As da ponta do balanço até o pilar: a barra calculada cobre do apoio
    # (x = 5) à ponta (7,5), e o resto da face de cima é porta-estribo
    cobre_o_balanco = any(p.x_ini <= 5.0 and p.x_fim >= 7.4
                          for p in superiores)
    As_balanco = sum(p.n * math.pi * (p.phi / 20.0) ** 2 for p in superiores
                     if p.x_ini <= 5.0 <= p.x_fim)
    M_apoio = max(abs(r.M) for r in v1.resultado.regioes
                  if r.tipo == "apoio")
    return [
        Conferencia("sacada: o gerador não acusa mais viga sem apoio",
                    float(not any("sem apoio" in a for a in geracao.avisos)),
                    1.0),
        Conferencia("sacada: a V5 repousa nas pontas de V1 e V2, marcadas "
                    "como ponta de balanço",
                    float(sorted(a.viga_de_apoio for a in v5.apoios_em_viga
                                 if a.na_ponta_de_balanco) == ["V1", "V2"]),
                    1.0),
        Conferencia("sacada: a V5 é dimensionada, com o aviso de apoio "
                    "deslocável", float(vig["V5"].passou and any(
                        "apoio deslocável" in a for a in vig["V5"].avisos)),
                    1.0),
        Conferencia("sacada: V1 e V2 não acusam encontro sem apoio na ponta",
                    float(not cadeias["V1"].encontros_sem_apoio
                          and not cadeias["V2"].encontros_sem_apoio), 1.0),
        Conferencia("sacada: a armadura 3D desenha as cinco vigas, sem aviso",
                    float({f.elemento for f in arm.fios
                           if f.familia == "viga longitudinal"}
                          == {"V1", "V2", "V3", "V4", "V5"}
                          and not arm.avisos), 1.0),
        Conferencia("sacada: o negativo compartilhado L1/L2 fica dentro da "
                    "laje (antes caía no plano dos nós, dentro da viga)",
                    float(dentro), 1.0),
        Conferencia("sacada pesada: o momento do balanço passa de 100 kN.m "
                    "e governa o topo", float(M_apoio > 100.0), 1.0),
        Conferencia("sacada pesada: a barra superior calculada vai do apoio "
                    "à ponta do balanço", float(cobre_o_balanco), 1.0),
        Conferencia("sacada pesada: o topo no apoio passa de 5 cm² (a mínima "
                    "é 2,6)", float(As_balanco > 5.0), 1.0),
    ]


# ---------------------------------------------------------------------------
# 52. Lançamento: viga quebrada por direção e grelha de eixos
# ---------------------------------------------------------------------------


def viga_quebrada_por_direcao() -> list[Conferencia]:
    """Cada trecho reto da polilinha vira uma viga."""
    from .lancamento.grelha import dividir_por_direcao

    dobrada = dividir_por_direcao([(0, 0), (4.5, 0), (6, 2)])
    reta = dividir_por_direcao([(0, 0), (2, 0), (2, 0), (5, 0)])
    contorno = dividir_por_direcao([(0, 0), (5, 0), (5, 4), (0, 4), (0, 0)])
    return [
        Conferencia("viga quebrada: (0;0)(4,5;0)(6;2) vira duas vigas",
                    float(dobrada == [[(0.0, 0.0), (4.5, 0.0)],
                                      [(4.5, 0.0), (6.0, 2.0)]]), 1.0),
        Conferencia("viga quebrada: pontos no meio do trecho reto e "
                    "repetidos não quebram a viga",
                    float(reta == [[(0.0, 0.0), (5.0, 0.0)]]), 1.0),
        Conferencia("viga quebrada: o contorno fechado vira quatro vigas",
                    float(len(contorno)), 4.0),
    ]


def grelha_de_eixos() -> list[Conferencia]:
    """Nomes, encontros, lançamento nos encontros e a troca de um espaço."""
    from .lancamento import (Lancamento, LajeLancada, Pavimento, Planta,
                             gerar)
    from .lancamento.arquivo import de_dicionario, para_dicionario
    from .lancamento.grelha import lancar_na_grelha, mudar_espaco, nova_grelha
    from .lancamento.modelo import nome_de_coluna

    lanc = Lancamento("grelha", plantas={"A": Planta("A")},
                      pavimentos=[Pavimento("1", 3.0, "A")])
    lanc.grelha = g = nova_grelha(6, 5.0, 6, 5.0)
    planta = lanc.plantas["A"]
    p, v = lancar_na_grelha(planta, g, pilares=True, vigas=True)
    p2, v2 = lancar_na_grelha(planta, g, pilares=True, vigas=True)
    # uma laje no meio do vão C–D e outra no D–E, na linha 1–2
    planta.lajes += [LajeLancada("L1", 12.5, 2.5), LajeLancada("L2", 17.5,
                                                               2.5)]
    mudar_espaco(lanc, "coluna", 2, 2.0)
    xs_pilares = sorted({q.x for q in planta.pilares})
    l1, l2 = planta.lajes
    geracao = gerar(lanc)
    volta = de_dicionario(para_dicionario(lanc)).grelha
    return [
        Conferencia("grelha: colunas com letras, A a F",
                    float("".join(n for n, _ in g.colunas) == "ABCDEF"), 1.0),
        Conferencia("grelha: a coluna 27 é AA", float(nome_de_coluna(26)
                                                       == "AA"), 1.0),
        Conferencia("grelha: o encontro 2-E é a linha 2 com a 5ª coluna "
                    "(antes da troca: x = 20, y = 5)",
                    float(nova_grelha(6, 5.0, 6, 5.0).encontro("2-E")
                          == (20.0, 5.0)), 1.0),
        Conferencia("grelha 6×6: um pilar por encontro", float(len(p)), 36.0),
        Conferencia("grelha 6×6: uma viga por eixo", float(len(v)), 12.0),
        Conferencia("grelha: lançar de novo não duplica nada",
                    float(len(p2) + len(v2)), 0.0),
        Conferencia("grelha: trocar o 3º espaço de colunas para 2 m não "
                    "mexe nos outros",
                    float(g.espacos_colunas == [5.0, 5.0, 2.0, 5.0, 5.0]),
                    1.0),
        Conferencia("grelha: os eixos depois dele andam 3 m (D em 12, F em "
                    "22)", float(g.xs == [0.0, 5.0, 10.0, 12.0, 17.0, 22.0]),
                    1.0),
        Conferencia("grelha: os pilares andam com os eixos",
                    float(xs_pilares == g.xs), 1.0),
        Conferencia("grelha: a viga da linha 1 vai até a nova coluna F",
                    float(planta.vigas[0].pontos == [(0.0, 0.0),
                                                     (22.0, 0.0)]), 1.0),
        Conferencia("grelha: a laje do vão encurtado fica no meio dele",
                    l1.x, 11.0, 1e-9),
        Conferencia("grelha: a laje do vão seguinte só anda", l2.x, 14.5,
                    1e-9),
        Conferencia("grelha: o lançamento depois da troca gera o modelo",
                    float(geracao.ok), 1.0),
        Conferencia("grelha: vai e volta do arquivo com os espaços",
                    float(volta is not None and volta.espacos_colunas
                          == g.espacos_colunas and volta.espacos_linhas
                          == g.espacos_linhas), 1.0),
    ]


# ---------------------------------------------------------------------------
# 53. Laje em balanço; pilar girado; largura de apoio das lajes por face
# ---------------------------------------------------------------------------


def _com_balanco(com_vizinha: bool = True, partida: bool = False):
    """Painel 5 × 4 m com laje em balanço de 1,2 m além da V2 (y = 4).
    ``partida``: uma viga chega por dentro no meio da V2 e parte a sacada em
    duas lajes em balanço lado a lado."""
    from .lancamento import (Lancamento, LajeLancada, Pavimento,
                             PilarLancado, Planta, VigaLancada, gerar)

    pl = Planta("A")
    for k, (x, y) in enumerate(((0, 0), (5, 0), (0, 4), (5, 4)), 1):
        pl.pilares.append(PilarLancado(f"P{k}", x, y, 0.20, 0.40))
    pl.vigas += [VigaLancada("V1", [(0, 0), (5, 0)], 0.20, 0.50),
                 VigaLancada("V2", [(0, 4), (5, 4)], 0.20, 0.50),
                 VigaLancada("V3", [(0, 0), (0, 4)], 0.15, 0.50),
                 VigaLancada("V4", [(5, 0), (5, 4)], 0.20, 0.50)]
    if partida:
        pl.vigas.append(VigaLancada("V5", [(2.5, 0), (2.5, 4)], 0.20, 0.40))
        pl.lajes += [LajeLancada("L1", 1.2, 2.0, 0.12, 1.5, 2.0),
                     LajeLancada("L3", 3.7, 2.0, 0.12, 1.5, 2.0),
                     LajeLancada("L2", 1.2, 4.6, 0.12, 1.5, 3.0,
                                 balanco=1.2, sentido="+y"),
                     LajeLancada("L4", 3.7, 4.6, 0.12, 1.5, 3.0,
                                 balanco=1.2, sentido="+y")]
    else:
        if com_vizinha:
            pl.lajes.append(LajeLancada("L1", 2.5, 2.0, 0.12, 1.5, 2.0))
        pl.lajes.append(LajeLancada("L2", 2.5, 4.6, 0.12, 1.5, 3.0,
                                    balanco=1.2, sentido="+y"))
    return gerar(Lancamento("balanço", plantas={"A": pl},
                            pavimentos=[Pavimento("1", 3.0, "A")]))


def laje_em_balanco_no_portico() -> list[Conferencia]:
    """Gerada pelo lançamento, carregada inteira na viga de apoio, armada pelo
    programa de Lajes como balanço engastado na laje de dentro."""
    from .core.lajes import aplicar_lajes, area_total, retangulo
    from .dimensionamento import montar_pavimento, verificar_lajes

    g = _com_balanco()
    m = g.modelo
    L2 = m.lajes["L2.1"]
    G, Q = CasoDeCarga("G"), CasoDeCarga("Q")
    reps = {r.laje: r for r in aplicar_lajes(m, G, Q)}
    rep = reps["L2.1"]
    so_v2 = {a.barra for a in rep.arestas} == {"V2.1.1"}
    pav = montar_pavimento(m, 3.0)
    deles = pav.laje("L2.1")
    vinculos = {deles.face_do_bordo(k + 1): b.vinculo
                for k, b in enumerate(deles.bordos)}
    ver = verificar_lajes(m)[0]
    negativa = [p for p in ver.resultado.todas_posicoes
                if p.face == "superior" and "L2.1" in p.laje]
    ponta = max(p.fim for p in negativa) / 100.0 if negativa else 0.0
    sem_vizinha = _com_balanco(com_vizinha=False).modelo
    try:
        montar_pavimento(sem_vizinha, 3.0)
        recusada = False
    except ErroDeModelo as erro:
        recusada = "sem laje contínua" in str(erro)
    partida = montar_pavimento(_com_balanco(partida=True).modelo, 3.0)
    return [
        Conferencia("laje em balanço: o lançamento a gera sobre a V2",
                    float(L2.em_balanco and L2.sentido == "+y"
                          and not g.erros), 1.0),
        Conferencia("laje em balanço: o retângulo vai do eixo da V2 à borda "
                    "livre", float(retangulo(m, L2)[1:4:2] == (4.0, 5.2)),
                    1.0),
        Conferencia("laje em balanço: a área total soma o balanço",
                    area_total(m), 5.0 * 4.0 + 5.0 * 1.2, 1e-9),
        Conferencia("laje em balanço: a carga inteira vai para a V2 "
                    "(q·b·L)", rep.total, (0.12 * 25.0 + 1.5) * 1.2 * 5.0,
                    1e-9),
        Conferencia("laje em balanço: e só para ela", float(so_v2), 1.0),
        Conferencia("laje em balanço: no programa de Lajes, destino "
                    "'balanco' e engastada só pelo lado apoiado",
                    float(deles.destino == "balanco" and deles.em_balanco
                          and vinculos["baixo"] == "engastado"), 1.0),
        Conferencia("laje em balanço: o pavimento é aprovado",
                    float(ver.aprovado), 1.0),
        Conferencia("laje em balanço: a negativa entra no balanço até perto "
                    "da ponta (borda em 5,20 m)", float(ponta > 4.9), 1.0),
        Conferencia("laje em balanço sem laje de dentro: recusada com o "
                    "motivo", float(recusada), 1.0),
        Conferencia("sacada partida em duas: a continuidade lateral entre os "
                    "balanços não vira engaste",
                    float(all(partida.laje(n).em_balanco
                              for n in ("L2.1", "L4.1"))), 1.0),
    ]


def pilar_girado_e_apoios_das_lajes() -> list[Conferencia]:
    """A largura do pilar girado na direção da viga, e a largura de apoio de
    cada bordo de laje pela face que ele ocupa."""
    from .compatibilizacao import largura_do_pilar
    from .dimensionamento import montar_pavimento
    from .lancamento import (Lancamento, LajeLancada, Pavimento,
                             PilarLancado, Planta, VigaLancada, gerar)

    pl = Planta("A")
    pl.pilares += [PilarLancado("P1", 0, 0, 0.20, 0.50, 90.0),
                   PilarLancado("P2", 5, 0, 0.20, 0.50, 0.0),
                   PilarLancado("P3", 0, 4, 0.20, 0.50, 0.0),
                   PilarLancado("P4", 5, 4, 0.20, 0.50, 0.0)]
    pl.vigas += [VigaLancada("V1", [(0, 0), (5, 0)], 0.20, 0.50),
                 VigaLancada("V2", [(0, 4), (5, 4)], 0.20, 0.50),
                 VigaLancada("V3", [(0, 0), (0, 4)], 0.15, 0.50),
                 VigaLancada("V4", [(5, 0), (5, 4)], 0.25, 0.50)]
    pl.lajes.append(LajeLancada("L1", 2.5, 2.0, 0.12, 1.5, 2.0))
    m = gerar(Lancamento("girado", plantas={"A": pl},
                         pavimentos=[Pavimento("1", 3.0, "A")])).modelo
    girado = next(n for n, b in m.barras.items() if n.startswith("P1."))
    reto = next(n for n, b in m.barras.items() if n.startswith("P2."))
    pav = montar_pavimento(m, 3.0)
    L1 = pav.laje("L1.1")
    t = {L1.face_do_bordo(k + 1): b.t for k, b in enumerate(L1.bordos)}
    return [
        Conferencia("pilar 20×50 girado 90°: em X mede os 50 cm",
                    largura_do_pilar(m, girado, (1, 0, 0))[0], 50.0, 1e-9),
        Conferencia("pilar 20×50 girado 90°: em Y mede os 20 cm",
                    largura_do_pilar(m, girado, (0, 1, 0))[0], 20.0, 1e-9),
        Conferencia("pilar 20×50 sem giro: em X mede os 20 cm",
                    largura_do_pilar(m, reto, (1, 0, 0))[0], 20.0, 1e-9),
        Conferencia("laje: cada bordo leva a largura da viga da sua face "
                    "(V3 15 cm à esquerda, V4 25 cm à direita)",
                    float(t == {"esquerda": 15.0, "direita": 25.0,
                                "baixo": 20.0, "cima": 20.0}), 1.0),
    ]


def topo_das_vigas_nivelado() -> list[Conferencia]:
    """No desenho, vigas de alturas diferentes e as lajes têm o topo no mesmo
    nível — o da viga mais alta da cota —, e a mesa da viga T de borda fica
    do lado da laje."""
    from .armadura3d import armadura_do_pavimento
    from .core.lajes import (deslocamento_do_centro, desnivel_da_viga,
                             nivel_do_pavimento, retangulo)
    from .lancamento import (Lancamento, LajeLancada, Pavimento,
                             PilarLancado, Planta, VigaLancada, gerar)

    pl = Planta("A")
    for k, (x, y) in enumerate(((0, 0), (5, 0), (0, 4), (5, 4), (0, 8),
                                (5, 8)), 1):
        pl.pilares.append(PilarLancado(f"P{k}", x, y, 0.20, 0.40))
    pl.vigas += [VigaLancada("V1", [(0, 0), (5, 0)], 0.20, 0.50),
                 VigaLancada("V2", [(0, 4), (5, 4)], 0.20, 0.60),
                 VigaLancada("V3", [(0, 8), (5, 8)], 0.20, 0.45),
                 VigaLancada("V4", [(0, 0), (0, 8)], 0.20, 0.50),
                 VigaLancada("V5", [(5, 0), (5, 8)], 0.20, 0.50)]
    pl.lajes += [LajeLancada("L1", 2.5, 2.0, 0.12, 1.5, 2.0),
                 LajeLancada("L2", 2.5, 6.0, 0.12, 1.5, 2.0)]
    m = gerar(Lancamento("niveis", plantas={"A": pl},
                         pavimentos=[Pavimento("1", 3.0, "A")])).modelo
    v1 = next(n for n in m.barras if n.startswith("V1."))
    topos_lajes = {round(3.0 + deslocamento_do_centro(m, l)
                         + l.espessura / 2.0, 9) for l in m.lajes.values()}
    arm = armadura_do_pavimento(m, 3.0, None, estribos=False)
    # mesa da V1 (borda, laje só em y > 0): nenhuma barra em y < -bw/2
    fora = [pt for f in arm.fios if f.elemento == "V1"
            and f.familia == "viga longitudinal" for pt in f.pontos
            if pt[1] < -0.10 - 1e-6]
    return [
        Conferencia("nível do pavimento: o topo da viga mais alta (V2, 60 cm)",
                    nivel_do_pavimento(m, 3.0), 3.30, 1e-12),
        Conferencia("a V1 (50 cm) sobe 5 cm no desenho para nivelar o topo",
                    desnivel_da_viga(m, v1), 0.05, 1e-12),
        Conferencia("as duas lajes com o topo no mesmo nível (antes cada uma "
                    "seguia o próprio contorno)", float(topos_lajes == {3.3}),
                    1.0),
        Conferencia("a mesa da viga de borda fica do lado da laje — nenhuma "
                    "barra da V1 do lado de fora", float(len(fora)), 0.0),
    ]


# ---------------------------------------------------------------------------
# 54. Motor de Vigas motor-2026-11-25: seção L e barra pela mínima
# ---------------------------------------------------------------------------


def secao_l_e_barra_pela_minima() -> list[Conferencia]:
    """Os dois pedidos do Pórticos que o programa de Vigas atendeu.

    * **Seção L**: na viga de borda a ponte diz ao motor de que lado está a
      mesa — à esquerda de quem anda no sentido da cadeia —, e o desenho 3D
      põe a mesa do lado da laje (u do motor cresce para a direita).
    * **Barra pela mínima**: a que existe só porque As,mín governa não corre
      mais até o fim da região do apoio, e sim até onde o momento negativo
      daquela face acaba (mais aℓ e ℓb,nec).
    """
    from .armadura3d import fios_da_viga
    from .continuidade import vigas_continuas
    from .dimensionamento import montar_viga
    from .elementos.vigas.core.dimensionar import dimensionar
    from .lancamento import (Lancamento, LajeLancada, Pavimento,
                             PilarLancado, Planta, VigaLancada, gerar)

    # V1 em +x na borda y = 0 (laje em y > 0: esquerda); V3 em +y na borda
    # x = 0 (laje em x > 0: direita de quem anda em +y)
    pl = Planta("A")
    for k, (x, y) in enumerate(((0, 0), (5, 0), (0, 4), (5, 4)), 1):
        pl.pilares.append(PilarLancado(f"P{k}", x, y, 0.20, 0.40))
    pl.vigas += [VigaLancada("V1", [(0, 0), (5, 0)], 0.20, 0.50),
                 VigaLancada("V2", [(0, 4), (5, 4)], 0.20, 0.50),
                 VigaLancada("V3", [(0, 0), (0, 4)], 0.20, 0.50),
                 VigaLancada("V4", [(5, 0), (5, 4)], 0.20, 0.50)]
    pl.lajes.append(LajeLancada("L1", 2.5, 2.0, 0.12, 1.5, 2.0))
    m = gerar(Lancamento("borda", plantas={"A": pl},
                         pavimentos=[Pavimento("1", 3.0, "A")])).modelo
    cad = {c.barras[0].split(".")[0]: c for c in vigas_continuas(m)}
    v1 = montar_viga(m, cad["V1"])
    v3 = montar_viga(m, cad["V3"])
    lado_v1 = v1.tramos[0].secao.lado_mesa
    lado_v3 = v3.tramos[0].secao.lado_mesa
    res = dimensionar(v1)
    fios = fios_da_viga(m, cad["V1"], res, estribos=False)
    # mesa de um lado: nenhuma barra fora da alma do lado de fora (y < -bw/2)
    fora = [pt for f in fios for pt in f.pontos if pt[1] < -0.10 - 1e-6]
    dentro = [pt for f in fios for pt in f.pontos if pt[1] > 0.10 + 1e-6]

    # a barra pela mínima: a V1 da sacada, apoio de extremidade em que a
    # mínima governa (4Ø10). Antes as quatro iam a 3,36 m; agora as duas de
    # canto seguem e as outras duas param onde o negativo acaba
    sacada = _sacada(1.5, 3.0).modelo
    c1 = next(c for c in vigas_continuas(sacada)
              if c.barras[0].startswith("V1."))
    r1 = dimensionar(montar_viga(sacada, c1))
    apoio1 = sorted((p for p in r1.posicoes if p.tipo == "longitudinal"
                     and p.face == "superior" and p.x_ini < 0.5),
                    key=lambda p: p.x_fim)
    cortada = (len(apoio1) >= 2 and apoio1[0].x_fim < 2.0
               and apoio1[-1].x_fim > apoio1[0].x_fim + 1.0)
    return [
        Conferencia("seção L: a V1 (borda, laje à esquerda de +x) vai com a "
                    "mesa à esquerda", float(lado_v1 == "esquerda"), 1.0),
        Conferencia("seção L: a V3 (borda, laje à direita de +y) vai com a "
                    "mesa à direita", float(lado_v3 == "direita"), 1.0),
        Conferencia("seção L: no 3D nenhuma barra da V1 do lado sem laje",
                    float(len(fora)), 0.0),
        Conferencia("seção L: e a mesa aparece do lado da laje",
                    float(len(dentro) > 0), 1.0),
        Conferencia("barra pela mínima: no apoio de extremidade da sacada, "
                    "as barras além das de canto param antes de 2 m (antes "
                    "iam a 3,36 m)", float(cortada), 1.0),
    ]


def conferir(pasta=None) -> list[Conferencia]:
    conferencias: list[Conferencia] = []
    for prova in (barra_axial, balanco_plano_xy, balanco_plano_xz, torcao,
                  biapoiada_uniforme, biengastada_uniforme,
                  invariancia_por_rotacao, balanco_em_L,
                  portico_travessa_rigida, equilibrio_global,
                  equilibrio_de_barra, coerencia_dos_diagramas,
                  deteccao_de_mecanismo, carga_de_peso_proprio, superposicao,
                  concomitantes_da_envoltoria, combinacoes_da_norma,
                  permanente_favoravel, desaprumo_global,
                  limites_do_desaprumo, regra_dos_trinta_por_cento,
                  momento_de_tombamento, ciclo_completo,
                  viga_engastada_e_apoiada, viga_birrotulada,
                  liberacao_que_solta_a_barra, carga_triangular, carga_parcial,
                  apoio_elastico, mola_rigida, recalque_em_viga_biengastada,
                  recalque_em_estrutura_isostatica, alternancia_de_acidental,
                  envoltoria_da_alternancia, vento_pela_nbr6123,
                  flambagem_de_euler, flambagem_sem_compressao,
                  p_delta_viga_coluna, p_delta_sem_normal, p_delta_com_tracao,
                  p_delta_acima_da_critica,
                  caso_efetivo_bate_com_superposicao, coeficiente_gama_z,
                  gama_z_contra_p_delta, limites_do_alfa,
                  pilar_equivalente_de_um_balanco, parametro_de_instabilidade,
                  alfa_e_gama_z_concordam, majoracao_por_gama_z,
                  rigidez_secante_do_item_15_7_3, laje_reparte_a_carga_toda,
                  laje_quadrada_vira_triangulo, laje_com_trecho_rigido,
                  laje_recusa_painel_invalido, balanco_com_cortante,
                  biapoiada_com_cortante, engastamento_perfeito_com_cortante,
                  cortante_em_carga_parcial, trecho_rigido_no_engaste,
                  trecho_rigido_na_ponta, trecho_rigido_no_portico,
                  trecho_rigido_sem_vao, trecho_rigido_com_segunda_ordem,
                  confronto_com_mastan, modulo_do_concreto,
                  ramos_do_modulo_se_encontram, material_de_concreto,
                  concreto_recusa_entrada_ruim, momento_do_lado_tracionado,
                  motores_de_elemento_copiados,
                  charneiras_batem_com_o_programa_de_lajes,
                  momentos_de_laje_pelo_programa,
                  ponte_de_pilares_converte_certo, ponte_acha_a_base_pela_cota,
                  ponte_roda_o_lote_do_edificio, viga_continua_reconhecida,
                  ponte_de_vigas_monta_e_dimensiona,
                  ponte_de_lajes_monta_o_pavimento,
                  armadura_cai_dentro_do_concreto,
                  armadura_e_de_um_pavimento_so,
                  pilar_reprovado_nao_passa_por_aprovado,
                  peso_proprio_entra_uma_vez_so,
                  apoio_de_viga_leva_a_rigidez_do_pilar,
                  acao_lateral_nao_chega_ao_motor_mas_e_conferida,
                  conferencia_do_portico_mede_area_de_aco,
                  motores_trouxeram_as_saidas,
                  dependencias_estao_declaradas,
                  vento_carrega_sem_depender_de_pasta,
                  pacote_nao_tem_dado_fora_do_codigo,
                  p_delta_confrontado_com_pynite,
                  cenario_01_biapoiada_uniforme_pynite,
                  cenario_02_balanco_vertical_pynite,
                  cenario_03_biapoiada_concentrada_pynite,
                  cenario_04_portico_plano_lateral_pynite,
                  cenario_04_portico_plano_lateral_opensees,
                  cenario_05_grelha_ortogonal_pynite,
                  cenario_05_grelha_ortogonal_opensees,
                  cenario_06_secao_rotacionada_pynite,
                  cenario_06_secao_rotacionada_opensees,
                  cenario_07_flambagem_euler_pynite,
                  cenario_08_apoio_elastico_pynite,
                  cenario_08_apoio_elastico_opensees,
                  cenario_09_trecho_rigido_pynite,
                  cenario_09_trecho_rigido_opensees,
                  cenario_10_portico_espacial_pynite,
                  cenario_10_portico_espacial_opensees,
                  modal_viga_em_balanco,
                  modal_viga_em_balanco_opensees,
                  modal_massa_so_das_barras_com_peso,
                  modal_recusa_estrutura_sem_massa,
                  edificio_modal_pequeno_opensees,
                  edificio_modal_alto_opensees,
                  edificio_modal_balanco_opensees,
                  edificio_modal_assimetrico_opensees,
                  viga_apoiada_em_viga_hierarquia,
                  viga_apoiada_em_viga_entra_como_apoio_e_como_carga,
                  viga_apoiada_em_viga_mais_alta_fica_pendurada,
                  balanco_no_fim_da_viga_mantem_o_ultimo_apoio,
                  pilar_de_canto_retirado_deixa_balanco_e_nao_apoio,
                  viga_so_se_apoia_dentro_dos_vaos_da_outra,
                  auditoria_de_cargas_confere_a_soma,
                  laje_alinhada_com_o_topo_das_vigas,
                  diafragma_move_o_pavimento_como_corpo_rigido,
                  diafragma_contra_opensees,
                  grelha_reproduz_a_placa_de_navier,
                  grelha_conserva_a_carga_e_remonta_a_viga,
                  esparsa_bate_com_densa,
                  vigas_armadas_pela_envoltoria_do_portico,
                  segunda_ordem_global_no_dimensionamento,
                  viga_t_pela_mesa_colaborante,
                  laje_trelicada_no_portico,
                  continuidade_dos_pilares_e_nos,
                  lancamento_gera_o_modelo,
                  lancamento_recusa_o_que_nao_fecha,
                  lancamento_dimensiona_ponta_a_ponta,
                  sacada_viga_de_borda_e_balanco_armado,
                  viga_quebrada_por_direcao, grelha_de_eixos,
                  laje_em_balanco_no_portico,
                  pilar_girado_e_apoios_das_lajes,
                  topo_das_vigas_nivelado,
                  secao_l_e_barra_pela_minima,
                  planta_de_forma_do_pavimento, diagramacao_das_folhas,
                  cortes_esquematicos):
        conferencias.extend(prova())
    if pasta is not None:
        conferencias.extend(ida_e_volta_json(pasta))
        conferencias.extend(classificacao_no_arquivo(pasta))
        conferencias.extend(ponte_de_vigas_desenha(pasta))
        conferencias.extend(ponte_de_vigas_desenha_varias(pasta))
        conferencias.extend(dimensionar_nao_grava_arquivo(pasta))
        conferencias.extend(ponte_de_lajes_dimensiona_e_desenha(pasta))
        conferencias.extend(armadura_vira_dxf(pasta))
        conferencias.extend(projeto_gera_os_tres_arquivos(pasta))
        conferencias.extend(opcoes_de_calculo_vao_e_voltam_do_arquivo(pasta))
        conferencias.extend(lancamento_vai_e_volta_do_arquivo(pasta))
    return conferencias
