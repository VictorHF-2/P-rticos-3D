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

import math
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

        origem = raiz / dados["origem"] if raiz else None
        if origem is None or not origem.is_dir():
            conferencias.append(Conferencia(
                f"elementos: origem de {elemento} fora de alcance, "
                "cópia não confrontada", 0.0, 0.0))
            continue

        diferentes = []
        for parte, arquivo in copiados:
            par = (origem / parte / arquivo.name) if parte else (origem
                                                                 / arquivo.name)
            if not par.exists():
                # O ``__init__.py`` vazio é criação nossa, para o pacote
                # existir; ele não vem da origem e não conta como diferença.
                if arquivo.name == "__init__.py" and not arquivo.read_bytes():
                    continue
                diferentes.append(arquivo.name)
                continue
            if (hashlib.sha256(arquivo.read_bytes()).digest()
                    != hashlib.sha256(par.read_bytes()).digest()):
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
    """Dimensiona e grava o desenho, que é o que o usuário leva embora."""
    from pathlib import Path

    from .dimensionamento import verificar_vigas

    destino = Path(pasta) / "vigas"
    m = _pavimento_de_tres_vaos()
    verificacoes = verificar_vigas(m, pasta_desenhos=destino)
    com_veredito = [v for v in verificacoes if v.passou]
    arquivos = [Path(a) for v in com_veredito for a in v.desenhos]

    pngs = [a for a in arquivos if a.suffix == ".png"]
    dxfs = [a for a in arquivos if a.suffix == ".dxf"]

    return [
        Conferencia("ponte de vigas: a viga foi dimensionada",
                    float(len(com_veredito)), 1.0),
        Conferencia("ponte de vigas: elevação e seções em imagem",
                    float(len(pngs)), 2.0),
        Conferencia("ponte de vigas: e um DXF para levar ao CAD",
                    float(len(dxfs)), 1.0),
        Conferencia("ponte de vigas: os arquivos existem e não estão vazios",
                    float(all(a.exists() and a.stat().st_size > 5000
                              for a in arquivos)), 1.0),
        Conferencia("ponte de vigas: o DXF abre e tem entidades",
                    float(_entidades_do_dxf(dxfs[0]) > 0 if dxfs else 0), 1.0),
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
            pior_viga = max(pior_viga,
                            abs(float(d @ p.R[1])) / (secao.b / 2.0),
                            abs(float(d @ p.R[2])) / (secao.h / 2.0))

    # A laje é desenhada centrada no plano dos nós: as barras têm de cair
    # entre as duas faces, e a positiva abaixo da negativa.
    espessura = 0.12
    zs_pos = [float(pt[2]) for f in arm.fios if f.familia == "laje positiva"
              for pt in f.pontos]
    zs_neg = [float(pt[2]) for f in arm.fios if f.familia == "laje negativa"
              for pt in f.pontos]
    dentro = all(3.0 - espessura / 2.0 < z < 3.0 + espessura / 2.0
                 for z in zs_pos + zs_neg)

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
                    float(max(zs_pos) < min(zs_neg) if zs_pos and zs_neg
                          else 0.0), 1.0),
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
    peso = secao.peso_proprio(deles.concreto.peso_especifico)

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
    """O apoio vai como mola, e a mola vale 4EI/ℓ dos lances que chegam.

    A inércia que conta é a do pilar **na direção da viga**, e é isso que a
    conferência trava: girando a seção do pilar, a mola tem de mudar na razão
    dos cubos dos lados. Um erro de eixo aqui passaria despercebido — a mola
    continuaria existindo, só com o valor errado.
    """
    from dataclasses import replace

    from .continuidade import vigas_continuas
    from .dimensionamento import montar_viga, rigidez_dos_pilares

    m = _portico_com_vento()
    viga = next(v for v in vigas_continuas(m) if len(v.apoios) >= 2)
    k = rigidez_dos_pilares(m, viga, 1)

    # o apoio 1 é interno: dois lances? Não — aqui cada prumada tem um lance
    # só, do chão à laje. Vale 4EI/ℓ de um lance.
    barra = next(b for n, b in m.barras.items() if n.startswith("P")
                 and viga.nos[viga.apoios[1]] in (b.no_i, b.no_j))
    secao = m.secoes[barra.secao]
    material = m.materiais[barra.material]
    esperado = 4.0 * material.E * secao.Iz / m.comprimento(
        next(n for n, b in m.barras.items() if b is barra))

    # girando o pilar de 30×30 para 20×45, a inércia na direção da viga cai
    m2 = _portico_com_vento()
    m2.add_secao(Secao.retangular("P20x45", 0.20, 0.45))
    for nome, b in list(m2.barras.items()):
        if nome.startswith("P"):
            m2.barras[nome] = replace(b, secao="P20x45")
    viga2 = next(v for v in vigas_continuas(m2) if len(v.apoios) >= 2)
    k2 = rigidez_dos_pilares(m2, viga2, 1)

    deles = montar_viga(m, viga)
    apoios_mola = [a for a in deles.apoios if a.tipo == "mola"]

    return [
        Conferencia("mola do apoio: vale 4EI/ℓ do lance",
                    k, esperado, 1e-9),
        # 30³ contra 20³: a mola cai na razão dos cubos do lado que fica no
        # rumo da viga, e não na dos lados perpendiculares
        Conferencia("mola do apoio: segue o lado na direção da viga",
                    k2 / k, (0.20 ** 3 * 0.45) / (0.30 ** 3 * 0.30), 1e-9),
        Conferencia("mola do apoio: todos os apoios de pilar são mola",
                    float(len(apoios_mola)), float(len(viga.apoios))),
        Conferencia("mola do apoio: o motor recebeu k > 0",
                    float(all(a.k_mola > 0.0 for a in apoios_mola)), 1.0),
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
    subia e quebrava na primeira exportação. Declarar é o conserto.
    """
    if _empacotado():
        # No executável não há o que instalar: as sete já vieram dentro. O que
        # importa ali é que elas **importem**, e é isso que se confere.
        import importlib

        modulos = ("numpy", "scipy", "PySide6", "matplotlib", "docx",
                   "openpyxl", "ezdxf")
        vivas = 0
        for modulo in modulos:
            try:
                importlib.import_module(modulo)
            except ImportError:
                continue
            vivas += 1
        return [Conferencia("dependências: as sete estão dentro do executável",
                            float(vivas), float(len(modulos)))]

    caminho = Path(__file__).resolve().parent.parent / "requirements.txt"
    texto = caminho.read_text(encoding="utf-8").lower() if caminho.exists()         else ""
    exigidas = ("numpy", "scipy", "pyside6", "matplotlib",
                "python-docx", "openpyxl", "ezdxf")
    return [
        Conferencia("dependências: o arquivo existe",
                    float(caminho.exists()), 1.0),
        Conferencia("dependências: todas as sete estão declaradas",
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
                  pacote_nao_tem_dado_fora_do_codigo):
        conferencias.extend(prova())
    if pasta is not None:
        conferencias.extend(ida_e_volta_json(pasta))
        conferencias.extend(classificacao_no_arquivo(pasta))
        conferencias.extend(ponte_de_vigas_desenha(pasta))
        conferencias.extend(ponte_de_lajes_dimensiona_e_desenha(pasta))
        conferencias.extend(armadura_vira_dxf(pasta))
        conferencias.extend(projeto_gera_os_tres_arquivos(pasta))
    return conferencias
