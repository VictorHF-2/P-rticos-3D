# -*- coding: utf-8 -*-
"""
resultados.py
Deslocamentos, reações, esforços de extremidade e diagramas ao longo da barra.

Convenção de sinais dos diagramas — vale a pena ler antes de usar os números:

* ``N``  tração positiva.
* ``Vy`` e ``Vz`` são as cortantes nos planos x–y e x–z, ambas ligadas ao
  momento pela relação dM/dx = V do respectivo plano.
* ``T``  torção positiva no sentido do eixo local x.
* ``My`` e ``Mz`` são positivos quando tracionam a face de coordenada local
  negativa — ou seja, positivo é o momento de vão de uma barra que "barriga"
  no sentido oposto ao da carga. Numa viga horizontal sob gravidade isso dá
  ``My`` positivo no vão e negativo sobre os apoios, que é a leitura usual.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .carregamento import Segmento, acumulado
from .elemento import BarraPreparada
from .modelo import ErroDeModelo, Modelo

COMPONENTES = ("N", "Vy", "Vz", "T", "My", "Mz")


@dataclass
class Diagrama:
    """Esforços internos em estações igualmente espaçadas ao longo da barra."""

    barra: str
    x: np.ndarray
    N: np.ndarray
    Vy: np.ndarray
    Vz: np.ndarray
    T: np.ndarray
    My: np.ndarray
    Mz: np.ndarray

    def maximos(self) -> dict[str, tuple[float, float]]:
        """Para cada componente, o valor de maior módulo e onde ele ocorre."""
        saida = {}
        for nome in COMPONENTES:
            v = getattr(self, nome)
            i = int(np.argmax(np.abs(v)))
            saida[nome] = (float(v[i]), float(self.x[i]))
        return saida


@dataclass
class Resultado:
    modelo: Modelo
    caso: str
    deslocamentos: np.ndarray
    reacoes: np.ndarray
    esforcos: dict[str, np.ndarray]
    preparadas: dict[str, BarraPreparada]
    segmentos: dict[str, list[Segmento]]
    gdl_restritos: np.ndarray = field(default_factory=lambda: np.array([]))
    reacoes_mola: dict[str, np.ndarray] = field(default_factory=dict)
    # Preenchidos pela análise de segunda ordem; na linear ficam no padrão.
    iteracoes: int = 0
    segunda_ordem: bool = False

    # -- por nó -------------------------------------------------------------

    def deslocamento(self, no: str) -> np.ndarray:
        """(ux, uy, uz, rx, ry, rz) no sistema global."""
        return self.deslocamentos[self.modelo.gdl(no)]

    def reacao(self, no: str) -> np.ndarray:
        """(Fx, Fy, Fz, Mx, My, Mz) que o apoio aplica na estrutura."""
        if no not in self.modelo.apoios:
            raise ErroDeModelo(f"o nó '{no}' não tem apoio")
        r = np.zeros(6)
        base = 6 * self.modelo.indice(no)
        for k, restrito in enumerate(self.modelo.apoios[no].restricoes):
            if restrito:
                r[k] = self.reacoes[base + k]
        return r

    def reacao_mola(self, no: str) -> np.ndarray:
        """Força que o apoio elástico aplica na estrutura, igual a -k·d."""
        if no not in self.modelo.molas:
            raise ErroDeModelo(f"o nó '{no}' não tem mola")
        return self.reacoes_mola.get(no, np.zeros(6))

    def reacoes_totais(self) -> np.ndarray:
        """Resultante das reações: (ΣFx, ΣFy, ΣFz, ΣMx, ΣMy, ΣMz) na origem.

        Entram as reações dos apoios e as das molas — sem estas o equilíbrio
        global não fecharia num modelo com apoio elástico.
        """
        total = np.zeros(6)
        contribuicoes = [(no, self.reacao(no)) for no in self.modelo.apoios]
        contribuicoes += [(no, r) for no, r in self.reacoes_mola.items()]
        for no, r in contribuicoes:
            p = self.modelo.ponto(no)
            total[:3] += r[:3]
            total[3:] += r[3:] + np.cross(p, r[:3])
        return total

    # -- por barra ----------------------------------------------------------

    def esforcos_barra(self, barra: str) -> np.ndarray:
        """Os doze esforços de extremidade nos eixos locais."""
        if barra not in self.esforcos:
            raise ErroDeModelo(f"barra '{barra}' não existe")
        return self.esforcos[barra]

    def diagrama(self, barra: str, n: int = 11) -> Diagrama:
        """Esforços internos em ``n`` estações ao longo da barra.

        ``F`` e ``M`` são a resultante e o momento da carga distribuída do
        trecho já percorrido — para carga uniforme valem ``q·x`` e ``q·x²/2``,
        e é daí que vêm as fórmulas conhecidas.
        """
        q = self.esforcos_barra(barra)
        segmentos = self.segmentos[barra]
        p = self.preparadas[barra]

        # O diagrama percorre o vão flexível, mas as abscissas são medidas a
        # partir do nó inicial, para que continuem casando com a geometria do
        # modelo. Havendo trecho rígido, o diagrama começa depois do nó e
        # termina antes do outro — é justamente ali que ele deixa de valer.
        s = np.linspace(0.0, p.Lf, n)
        x = s + p.barra.offset_i

        acumulados = [acumulado(segmentos, float(si)) for si in s]
        F = np.array([a[0] for a in acumulados])
        M = np.array([a[1] for a in acumulados])

        return Diagrama(
            barra=barra,
            x=x,
            N=-q[0] - F[:, 0],
            Vy=-q[1] - F[:, 1],
            Vz=q[2] + F[:, 2],
            T=np.full_like(x, -q[3]),
            My=q[4] + q[2] * s + M[:, 2],
            Mz=q[5] - q[1] * s - M[:, 1],
        )

    # -- leitura rápida -----------------------------------------------------

    def reacoes_resumo(self) -> str:
        """Tabela das reações, com as molas e a resultante.

        As molas entram porque sem elas a soma não fecharia: num modelo com
        apoio elástico, parte da carga sai pela mola e não pelo apoio rígido, e
        uma tabela que só listasse os apoios mostraria um total menor que a
        carga aplicada, sem dizer por quê.
        """
        largura = max([len(n) for n in self.modelo.apoios]
                      + [len(n) for n in self.reacoes_mola] + [6])
        linhas = [f"Reações — caso '{self.caso}'"
                  + ("  (2ª ordem)" if self.segunda_ordem else ""),
                  f"  {'nó':<{largura}} {'Fx':>13} {'Fy':>13} {'Fz':>13}"
                  f" {'Mx':>13} {'My':>13} {'Mz':>13}"]

        def linha(no: str, r, marca: str = "") -> str:
            return (f"  {no + marca:<{largura}} " +
                    " ".join(f"{v:>13.4f}" for v in r))

        for no in self.modelo.apoios:
            linhas.append(linha(no, self.reacao(no)))
        for no, r in self.reacoes_mola.items():
            if np.any(r):
                linhas.append(linha(no, r, " ~"))

        total = self.reacoes_totais()
        linhas += ["  " + "-" * (largura + 84),
                   linha("Σ", total),
                   "",
                   f"  Carga vertical total: {total[2]:.4f}",
                   f"  Cortante na base: Fx = {total[0]:.4f}, "
                   f"Fy = {total[1]:.4f}",
                   f"  Momento na origem: Mx = {total[3]:.4f}, "
                   f"My = {total[4]:.4f}, Mz = {total[5]:.4f}"]
        if self.reacoes_mola:
            linhas.append("  O til marca apoio elástico: a força é -k·d.")
        return "\n".join(linhas)

    def resumo(self) -> str:
        linhas = [f"Caso de carga: {self.caso}", "", "Deslocamentos nodais"]
        for no in self.modelo.nos:
            d = self.deslocamento(no)
            linhas.append(
                f"  {no:<8} ux={d[0]:+.6e}  uy={d[1]:+.6e}  uz={d[2]:+.6e}"
                f"  rx={d[3]:+.6e}  ry={d[4]:+.6e}  rz={d[5]:+.6e}")

        linhas += ["", self.reacoes_resumo()]

        linhas += ["", "Esforços máximos por barra (módulo)"]
        for nome in self.modelo.barras:
            m = self.diagrama(nome, 21).maximos()
            linhas.append(
                f"  {nome:<8} N={m['N'][0]:+.4f}  Vy={m['Vy'][0]:+.4f}"
                f"  Vz={m['Vz'][0]:+.4f}  T={m['T'][0]:+.4f}"
                f"  My={m['My'][0]:+.4f}  Mz={m['Mz'][0]:+.4f}")

        return "\n".join(linhas)
