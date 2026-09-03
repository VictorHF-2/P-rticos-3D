# -*- coding: utf-8 -*-
"""
vista3d.py
Desenho do pórtico: modelo, deformada, diagramas e modos de flambagem.

A deformada não liga os nós deslocados por retas. Ela é traçada com as
**mesmas funções de forma** que o solver usa para montar o vetor de
engastamento perfeito, de modo que a curva desenhada é a curva que a
formulação descreve — inclusive a curvatura que aparece dentro de uma barra
carregada, que a ligação por retas esconderia justamente onde ela interessa.

O visualizador é matplotlib, e não uma biblioteca 3D dedicada, para não
acrescentar dependência ao que os outros programas da pasta já usam. O preço
é a rotação ficar lenta em modelo muito grande; é a peça mais isolada do
programa, e trocá-la um dia não mexe em mais nada.
"""

from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Line3DCollection

from ..core.carregamento import _matriz_forma
from ..core.modelo import Modelo
from ..core.resultados import COMPONENTES, Resultado
from . import tema

ESTACOES = 13

# Em qual eixo local cada componente é desenhado a partir da barra. O momento
# sai no plano em que ele flete, que é o que torna o diagrama legível.
EIXO_DO_COMPONENTE = {"N": 2, "Vy": 1, "Vz": 2, "T": 2, "My": 2, "Mz": 1}

# O momento fletor é traçado **do lado da fibra tracionada**, que é a convenção
# de projeto: numa biapoiada sob gravidade, o momento positivo traciona a face
# inferior e o diagrama aparece embaixo da viga.
#
# Os dois planos não levam o mesmo sinal, e isso não é descuido. Com carga para
# baixo, o momento no meio do vão sai **+wL²/8 em My** e **−wL²/8 em Mz**: é a
# mesma troca de sinal que a convenção θy = −dw/dx impõe à matriz de rigidez.
# Como o Mz já nasce negativo do lado tracionado, ele é desenhado direto; o My
# precisa da inversão. Há conferência travando os dois.
SINAL_DE_DESENHO = {"N": 1.0, "Vy": 1.0, "Vz": 1.0, "T": 1.0,
                    "My": -1.0, "Mz": 1.0}

VISTAS_DE_ESFORCO = list(COMPONENTES)


def pontos_do_diagrama(resultado: Resultado, barra: str, componente: str,
                       escala: float, n: int = ESTACOES
                       ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Base e topo do diagrama de uma barra, no sistema global.

    Devolve ``(base, topo, valor)``. Fica fora da tela para poder ser
    conferido sem abrir janela: o lado em que o momento é traçado é decisão de
    convenção, e convenção que não é conferida se perde na primeira mudança.
    """
    d = resultado.diagrama(barra, n)
    p = resultado.preparadas[barra]
    origem = resultado.modelo.ponto(p.barra.no_i)
    direcao = p.R[EIXO_DO_COMPONENTE[componente]]

    base = np.array([origem + p.R[0] * xi for xi in d.x])
    valor = getattr(d, componente)
    topo = base + escala * SINAL_DE_DESENHO[componente] * np.outer(valor,
                                                                  direcao)
    return base, topo, valor


def _pontos_da_barra(modelo: Modelo, nome: str) -> tuple[np.ndarray, np.ndarray]:
    barra = modelo.barras[nome]
    return modelo.ponto(barra.no_i), modelo.ponto(barra.no_j)


def _forma_deformada(resultado: Resultado, nome: str, deslocamentos: np.ndarray,
                     escala: float, n: int = ESTACOES) -> np.ndarray:
    """Pontos da barra deformada, no sistema global.

    O trecho rígido não flete: ele entra como reta entre o nó deslocado e a
    ponta do vão flexível, que é o que um braço rígido faz.
    """
    p = resultado.preparadas[nome]
    modelo = resultado.modelo
    pi, pj = _pontos_da_barra(modelo, nome)
    eixo = p.R[0]

    d_global = deslocamentos[np.array(p.gdl)]
    d_local = p.TH @ d_global

    s = np.linspace(0.0, p.Lf, n)
    pontos = []
    for si in s:
        u = _matriz_forma(float(si), p.Lf, p.phi_y, p.phi_z) @ d_local
        origem = pi + eixo * (p.barra.offset_i + si)
        pontos.append(origem + escala * (p.R.T @ u))

    if p.tem_trecho_rigido:
        no_i = pi + escala * d_global[:3]
        no_j = pj + escala * d_global[6:9]
        pontos = [no_i, *pontos, no_j]

    return np.array(pontos)


class Vista3D(FigureCanvasQTAgg):
    """Tela de desenho do pórtico, com rotação pelo mouse."""

    def __init__(self) -> None:
        figura = Figure(figsize=(7.0, 5.5), dpi=100)
        figura.patch.set_facecolor("white")
        super().__init__(figura)
        self.ax = figura.add_subplot(111, projection="3d")
        self.modelo: Modelo | None = None
        self.resultado: Resultado | None = None
        self._limpar()

    # -- desenho -----------------------------------------------------------

    def _limpar(self) -> None:
        self.ax.clear()
        self.ax.set_facecolor("white")
        self.ax.set_xlabel("X")
        self.ax.set_ylabel("Y")
        self.ax.set_zlabel("Z")
        self.ax.grid(True, alpha=0.25)

    def _proporcao_real(self, modelo: Modelo,
                        extras: np.ndarray | None = None) -> None:
        """Mantém a escala igual nos três eixos, para o desenho não mentir.

        ``extras`` são os pontos do que mais foi traçado — deformada, diagrama,
        modo. Eles entram no enquadramento porque o desenho pode sair da caixa
        dos nós: numa viga reta, a extensão em Z é zero, e um diagrama traçado
        em Z ficaria inteiramente fora do quadro se só os nós mandassem.
        """
        pontos = np.array([[no.x, no.y, no.z] for no in modelo.nos.values()])
        if len(pontos) == 0:
            return
        if extras is not None and len(extras):
            pontos = np.vstack([pontos, np.asarray(extras).reshape(-1, 3)])
        minimos, maximos = pontos.min(axis=0), pontos.max(axis=0)
        vao = np.maximum(maximos - minimos, 1e-6)
        self.ax.set_box_aspect(vao)
        folga = 0.08 * vao.max()
        self.ax.set_xlim(minimos[0] - folga, maximos[0] + folga)
        self.ax.set_ylim(minimos[1] - folga, maximos[1] + folga)
        self.ax.set_zlim(minimos[2] - folga, maximos[2] + folga)

    def _linhas_do_modelo(self, modelo: Modelo, cor: str, largura: float,
                          alfa: float) -> None:
        segmentos = []
        for nome in modelo.barras:
            pi, pj = _pontos_da_barra(modelo, nome)
            segmentos.append([pi, pj])
        if segmentos:
            self.ax.add_collection3d(Line3DCollection(
                segmentos, colors=cor, linewidths=largura, alpha=alfa))

    def _apoios(self, modelo: Modelo) -> None:
        for nome, apoio in modelo.apoios.items():
            p = modelo.ponto(nome)
            engastado = all(apoio.restricoes)
            self.ax.scatter([p[0]], [p[1]], [p[2]],
                            c=tema.COR_APOIO, s=70 if engastado else 45,
                            marker="s" if engastado else "^", depthshade=False)
        for nome in modelo.molas:
            p = modelo.ponto(nome)
            self.ax.scatter([p[0]], [p[1]], [p[2]], c=tema.COR_MOLA, s=55,
                            marker="D", depthshade=False)

    def _rotulos(self, modelo: Modelo, mostrar_nos: bool,
                 mostrar_barras: bool) -> None:
        if mostrar_nos:
            for nome, no in modelo.nos.items():
                self.ax.text(no.x, no.y, no.z, f" {nome}", fontsize=7,
                             color=tema.COR_NO)
        if mostrar_barras:
            for nome in modelo.barras:
                pi, pj = _pontos_da_barra(modelo, nome)
                meio = (pi + pj) / 2.0
                self.ax.text(meio[0], meio[1], meio[2], nome, fontsize=7,
                             color=tema.COR_BARRA)

    def desenhar_modelo(self, modelo: Modelo, rotulos_nos: bool = False,
                        rotulos_barras: bool = False) -> None:
        self.modelo = modelo
        self._limpar()
        if not modelo.nos:
            self.ax.set_title("modelo vazio", color=tema.AZUL)
            self.draw_idle()
            return

        self._linhas_do_modelo(modelo, tema.COR_BARRA, 1.6, 1.0)
        pontos = np.array([[n.x, n.y, n.z] for n in modelo.nos.values()])
        self.ax.scatter(pontos[:, 0], pontos[:, 1], pontos[:, 2],
                        c=tema.COR_NO, s=12, depthshade=False)
        self._apoios(modelo)
        self._rotulos(modelo, rotulos_nos, rotulos_barras)
        self._proporcao_real(modelo)
        self.ax.set_title(
            f"{len(modelo.nos)} nós · {len(modelo.barras)} barras",
            color=tema.AZUL, fontsize=10)
        self.draw_idle()

    def desenhar_deformada(self, resultado: Resultado,
                           escala: float | None = None) -> float:
        modelo = resultado.modelo
        self.modelo, self.resultado = modelo, resultado
        self._limpar()
        self._linhas_do_modelo(modelo, "#b9c1cc", 1.0, 0.8)

        escala = escala if escala is not None else self._escala_automatica(
            modelo, resultado.deslocamentos)

        curvas = [_forma_deformada(resultado, nome, resultado.deslocamentos,
                                   escala)
                  for nome in modelo.barras]
        self._desenhar_curvas(curvas, tema.COR_DEFORMADA, 1.8)
        self._apoios(modelo)
        self._proporcao_real(modelo, np.vstack(curvas) if curvas else None)
        self.ax.set_title(f"deformada de '{resultado.caso}' — escala {escala:.0f}×"
                          + ("  (2ª ordem)" if resultado.segunda_ordem else ""),
                          color=tema.AZUL, fontsize=10)
        self.draw_idle()
        return escala

    def desenhar_modo(self, modelo: Modelo, resultado: Resultado,
                      modo: np.ndarray, fator: float, indice: int,
                      escala: float | None = None) -> float:
        self.modelo = modelo
        self._limpar()
        self._linhas_do_modelo(modelo, "#b9c1cc", 1.0, 0.8)

        escala = escala if escala is not None else self._escala_automatica(
            modelo, modo)
        curvas = [_forma_deformada(resultado, nome, modo, escala)
                  for nome in modelo.barras]
        self._desenhar_curvas(curvas, tema.LARANJA, 1.8)
        self._apoios(modelo)
        self._proporcao_real(modelo, np.vstack(curvas) if curvas else None)
        self.ax.set_title(
            f"modo de flambagem {indice + 1} — fator crítico {fator:.4f}",
            color=tema.AZUL, fontsize=10)
        self.draw_idle()
        return escala

    def desenhar_diagrama(self, resultado: Resultado, componente: str,
                          escala: float | None = None) -> float:
        modelo = resultado.modelo
        self.modelo, self.resultado = modelo, resultado
        self._limpar()
        self._linhas_do_modelo(modelo, tema.COR_BARRA, 1.2, 1.0)

        diagramas = {nome: resultado.diagrama(nome, ESTACOES)
                     for nome in modelo.barras}
        valores = np.concatenate([getattr(d, componente) for d in
                                  diagramas.values()]) if diagramas else np.zeros(1)
        pico = float(np.max(np.abs(valores))) or 1.0
        escala = escala if escala is not None else (
            0.10 * self._dimensao(modelo) / pico)

        positivos, negativos = [], []
        tracados = []
        for nome in diagramas:
            base, topo, valor = pontos_do_diagrama(resultado, nome,
                                                   componente, escala,
                                                   ESTACOES)
            tracados.append(topo)
            for k in range(len(valor) - 1):
                trecho = [topo[k], topo[k + 1]]
                alvo = positivos if valor[k] + valor[k + 1] >= 0 else negativos
                alvo.append(trecho)
            for k in range(0, len(valor), 3):
                alvo = positivos if valor[k] >= 0 else negativos
                alvo.append([base[k], topo[k]])

        for trechos, cor in ((positivos, tema.COR_DIAGRAMA_POSITIVO),
                             (negativos, tema.COR_DIAGRAMA_NEGATIVO)):
            if trechos:
                self.ax.add_collection3d(Line3DCollection(
                    trechos, colors=cor, linewidths=1.1))

        self._apoios(modelo)
        self._proporcao_real(modelo, np.vstack(tracados) if tracados else None)
        nota = ("  ·  traçado do lado tracionado"
                if componente in ("My", "Mz") else "")
        self.ax.set_title(
            f"{componente} de '{resultado.caso}' — máximo {pico:.4g}{nota}",
            color=tema.AZUL, fontsize=10)
        self.draw_idle()
        return escala

    # -- apoio -------------------------------------------------------------

    def _desenhar_curvas(self, curvas: list[np.ndarray], cor: str,
                         largura: float) -> None:
        trechos = []
        for curva in curvas:
            trechos.extend([[curva[k], curva[k + 1]]
                            for k in range(len(curva) - 1)])
        if trechos:
            self.ax.add_collection3d(Line3DCollection(
                trechos, colors=cor, linewidths=largura))

    @staticmethod
    def _dimensao(modelo: Modelo) -> float:
        pontos = np.array([[n.x, n.y, n.z] for n in modelo.nos.values()])
        if len(pontos) == 0:
            return 1.0
        return float(np.max(pontos.max(axis=0) - pontos.min(axis=0))) or 1.0

    def _escala_automatica(self, modelo: Modelo,
                           deslocamentos: np.ndarray) -> float:
        """Escala que faz o maior deslocamento valer 8 % da maior dimensão.

        Deformada em escala real de um pórtico bem projetado é uma linha reta:
        o deslocamento é milimétrico contra metros de estrutura. A escala
        exagerada é o que torna o desenho legível, e por isso ela vai escrita
        no título — para ninguém confundir o desenho com a realidade.
        """
        translacoes = deslocamentos.reshape(-1, 6)[:, :3]
        pico = float(np.max(np.abs(translacoes))) if translacoes.size else 0.0
        if pico <= 0.0:
            return 1.0
        return 0.08 * self._dimensao(modelo) / pico
