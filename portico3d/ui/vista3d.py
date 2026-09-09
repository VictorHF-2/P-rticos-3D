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

import math

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection

from ..core.carregamento import _matriz_forma
from ..core.modelo import ErroDeModelo, Modelo
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


def _cantos_do_painel(modelo: Modelo, laje):
    from ..core.lajes import _cantos
    return _cantos(modelo, laje)


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


def perfil_da_secao(secao) -> np.ndarray:
    """Contorno da seção no plano local (y, z), para extrudar.

    Retângulo e círculo saem das dimensões que a seção guarda. A seção
    genérica, que só tem propriedades, ganha o **retângulo equivalente** —
    aquele de mesma área e mesmas inércias, ``h = √(12·Iy/A)`` e
    ``b = √(12·Iz/A)``. É desenho, não cálculo: serve para dar volume à barra
    sem inventar uma forma que a seção não declarou.
    """
    if secao.tipo == "retangular" and secao.b > 0.0 and secao.h > 0.0:
        b, h = secao.b, secao.h
    elif secao.tipo == "circular" and secao.b > 0.0:
        raio = secao.b / 2.0
        angulos = np.linspace(0.0, 2.0 * np.pi, 17)[:-1]
        return np.column_stack([raio * np.cos(angulos), raio * np.sin(angulos)])
    else:
        if secao.A <= 0.0:
            return np.zeros((0, 2))
        h = math.sqrt(max(12.0 * secao.Iy / secao.A, 1e-12))
        b = math.sqrt(max(12.0 * secao.Iz / secao.A, 1e-12))
    return np.array([[-b / 2.0, -h / 2.0], [b / 2.0, -h / 2.0],
                     [b / 2.0, h / 2.0], [-b / 2.0, h / 2.0]])


def faces_da_barra(modelo: Modelo, preparada, perfil: np.ndarray
                   ) -> list[np.ndarray]:
    """As faces do sólido da barra, no sistema global."""
    if len(perfil) == 0:
        return []
    pi = modelo.ponto(preparada.barra.no_i)
    pj = modelo.ponto(preparada.barra.no_j)
    ey, ez = preparada.R[1], preparada.R[2]

    inicio = np.array([pi + c[0] * ey + c[1] * ez for c in perfil])
    fim = np.array([pj + c[0] * ey + c[1] * ez for c in perfil])

    faces = [inicio, fim[::-1]]
    n = len(perfil)
    for k in range(n):
        j = (k + 1) % n
        faces.append(np.array([inicio[k], inicio[j], fim[j], fim[k]]))
    return faces


def faces_da_laje(modelo: Modelo, laje) -> list[np.ndarray]:
    """A placa da laje, desenhada centrada no plano dos nós.

    Centrada, e não apoiada no topo da viga, porque é isso que o modelo
    representa: tudo aqui está referido ao eixo das barras. O desenho não
    finge saber de um rebaixo que o modelo não tem.
    """
    from ..core.lajes import _cantos

    try:
        cantos, _, _ = _cantos(modelo, laje)
    except ErroDeModelo:
        return []
    meia = max(laje.espessura, 0.01) / 2.0
    base = np.array([modelo.ponto(c) for c in cantos])
    baixo = base - np.array([0.0, 0.0, meia])
    cima = base + np.array([0.0, 0.0, meia])

    faces = [baixo[::-1], cima]
    for k in range(4):
        j = (k + 1) % 4
        faces.append(np.array([baixo[k], baixo[j], cima[j], cima[k]]))
    return faces


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
                        extras: np.ndarray | None = None,
                        apenas_extras: bool = False) -> None:
        """Mantém a escala igual nos três eixos, para o desenho não mentir.

        ``extras`` são os pontos do que mais foi traçado — deformada, diagrama,
        modo. Eles entram no enquadramento porque o desenho pode sair da caixa
        dos nós: numa viga reta, a extensão em Z é zero, e um diagrama traçado
        em Z ficaria inteiramente fora do quadro se só os nós mandassem.
        """
        pontos = np.array([[no.x, no.y, no.z] for no in modelo.nos.values()])
        if apenas_extras and extras is not None and len(extras):
            # Planta de um pavimento: enquadrar o edifício inteiro deixaria o
            # nível desenhado espremido numa faixa do desenho.
            pontos = np.asarray(extras).reshape(-1, 3)
        elif extras is not None and len(extras):
            pontos = np.vstack([pontos, np.asarray(extras).reshape(-1, 3)])
        if len(pontos) == 0:
            return
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

    def desenhar_solido(self, modelo: Modelo) -> None:
        """A estrutura com as dimensões reais das seções, não com linhas.

        Serve para conferir o que a tabela diz: seção trocada, barra girada,
        laje na cota errada — tudo isso salta aos olhos aqui e passa
        despercebido no desenho de eixos.
        """
        from ..core.montagem import preparar_barras

        self.modelo = modelo
        self._limpar()
        if not modelo.barras:
            self.ax.set_title("modelo sem barras", color=tema.AZUL)
            self.draw_idle()
            return

        try:
            preparadas = preparar_barras(modelo)
        except ErroDeModelo as erro:
            self.ax.set_title(f"modelo incompleto: {erro}", color=tema.VERMELHO,
                              fontsize=8)
            self.draw_idle()
            return

        faces, pontos = [], []
        for nome, p in preparadas.items():
            secao = modelo.secoes[p.barra.secao]
            for face in faces_da_barra(modelo, p, perfil_da_secao(secao)):
                faces.append(face)
                pontos.append(face)

        faces_laje = []
        for laje in modelo.lajes.values():
            for face in faces_da_laje(modelo, laje):
                faces_laje.append(face)
                pontos.append(face)

        if faces:
            self.ax.add_collection3d(Poly3DCollection(
                faces, facecolors=tema.COR_SOLIDO, edgecolors=tema.COR_BARRA,
                linewidths=0.3, alpha=1.0))
        if faces_laje:
            self.ax.add_collection3d(Poly3DCollection(
                faces_laje, facecolors=tema.COR_LAJE,
                edgecolors=tema.COR_BARRA, linewidths=0.3, alpha=0.55))

        self._apoios(modelo)
        self._proporcao_real(modelo, np.vstack(pontos) if pontos else None)
        self.ax.set_title(
            f"{len(modelo.barras)} barras e {len(modelo.lajes)} lajes em "
            "dimensão real", color=tema.AZUL, fontsize=10)
        self.draw_idle()

    def desenhar_lajes(self, modelo: Modelo,
                       cota: float | None = None) -> list[str]:
        """Planta das lajes: charneiras plásticas e momentos nas duas direções.

        As vigas e os pilares aparecem apagados e sem dado nenhum — eles são
        contorno, não o assunto. O assunto é o painel: as linhas de ruptura e
        os momentos que o programa de Lajes calculou para ele.

        Desenha **um nível por vez**, porque planta de laje é de um pavimento:
        com os quatro pavimentos de um edifício sobrepostos, as charneiras de
        todos caem umas sobre as outras e não se lê nada. ``cota`` escolhe o
        nível; sem ela, entram todos.
        """
        from ..core.programa_lajes import (calcular_momentos, charneiras,
                                           vinculos_automaticos)

        self.modelo = modelo
        self._limpar()
        self._linhas_do_modelo(modelo, tema.COR_CONTEXTO, 1.0, 0.9)
        self._apoios(modelo)

        if not modelo.lajes:
            self._proporcao_real(modelo)
            self.ax.set_title("o modelo não tem lajes", color=tema.AZUL,
                              fontsize=10)
            self.draw_idle()
            return ["O modelo não tem lajes."]

        automaticos = vinculos_automaticos(modelo)
        relatorio, contornos, linhas = [], [], []

        for nome, laje in modelo.lajes.items():
            if cota is not None and abs(
                    modelo.ponto(laje.no_a)[2] - cota) > 1e-6:
                continue
            try:
                momentos = calcular_momentos(modelo, laje,
                                             automaticos.get(nome))
            except ErroDeModelo as erro:
                relatorio.append(f"{nome}: {erro}")
                continue

            cantos, _, _ = _cantos_do_painel(modelo, laje)
            origem = modelo.ponto(cantos[0])
            eixo_a = (np.array([1.0, 0.0, 0.0]) if momentos.direcao_a == "X"
                      else np.array([0.0, 1.0, 0.0]))
            eixo_b = (np.array([0.0, 1.0, 0.0]) if momentos.direcao_a == "X"
                      else np.array([1.0, 0.0, 0.0]))

            contorno = np.array([modelo.ponto(c) for c in cantos])
            contornos.append(contorno)

            for traco in charneiras(momentos.a, momentos.b,
                                    momentos.vinculos).values():
                if len(traco) < 2:
                    continue
                pontos = np.array([origem + eixo_b * p[0] + eixo_a * p[1]
                                   for p in traco])
                linhas.extend([[pontos[k], pontos[k + 1]]
                               for k in range(len(pontos) - 1)])

            centro = contorno.mean(axis=0)
            outra = "y" if momentos.direcao_a == "X" else "x"
            self.ax.text(centro[0], centro[1], centro[2],
                         f"{nome}\nm{momentos.direcao_a.lower()}="
                         f"{momentos.ma:.1f}\nm{outra}={momentos.mb:.1f}",
                         fontsize=7, color=tema.COR_MOMENTO_VAO,
                         ha="center", va="center")
            relatorio.append(str(momentos))

        if contornos:
            self.ax.add_collection3d(Poly3DCollection(
                contornos, facecolors=tema.COR_LAJE, alpha=0.20,
                edgecolors=tema.COR_BARRA, linewidths=0.8))
        if linhas:
            self.ax.add_collection3d(Line3DCollection(
                linhas, colors=tema.COR_CHARNEIRA, linewidths=1.4))

        self._proporcao_real(modelo,
                             np.vstack(contornos) if contornos else None,
                             apenas_extras=cota is not None and bool(contornos))
        # Vista em planta: é assim que se lê uma laje.
        self.ax.view_init(elev=78, azim=-90)
        onde = f"cota {cota:.2f} m" if cota is not None else "todos os níveis"
        self.ax.set_title(
            f"{len(contornos)} lajes na {onde} — charneiras plásticas e "
            "momentos em kN·m/m", color=tema.AZUL, fontsize=10)
        self.draw_idle()
        return relatorio

    def desenhar_armadura(self, modelo: Modelo, armadura) -> None:
        """A armadura de um pavimento no espaço, sobre o concreto translúcido.

        Recebe a armadura pronta — quem dimensiona é a ponte, não o desenho —,
        e aqui só se escolhe cor, espessura e enquadramento. O concreto entra
        com transparência alta para dar referência sem esconder o aço: sem ele
        não há como julgar cobrimento nenhum.

        Um pavimento por vez, pela medição que está em ``armadura3d``: o
        edifício inteiro passa dos 10 000 segmentos e a vista deixa de girar.
        """
        from ..armadura3d import lances_do_pavimento, vigas_do_pavimento
        from ..core.montagem import preparar_barras

        self.modelo = modelo
        self._limpar()

        alvos = list(lances_do_pavimento(modelo, armadura.cota))
        for viga in vigas_do_pavimento(modelo, armadura.cota):
            alvos.extend(viga.barras)

        faces, pontos = [], []
        try:
            preparadas = preparar_barras(modelo)
        except ErroDeModelo:
            preparadas = {}
        for nome in alvos:
            p = preparadas.get(nome)
            if p is None:
                continue
            secao = modelo.secoes[p.barra.secao]
            faces.extend(faces_da_barra(modelo, p, perfil_da_secao(secao)))

        faces_laje = []
        for laje in modelo.lajes.values():
            if abs(float(modelo.ponto(laje.no_a)[2]) - armadura.cota) > 1e-6:
                continue
            faces_laje.extend(faces_da_laje(modelo, laje))

        if faces:
            self.ax.add_collection3d(Poly3DCollection(
                faces, facecolors=tema.COR_SOLIDO, edgecolors=tema.COR_BARRA,
                linewidths=0.2, alpha=0.15))
        if faces_laje:
            self.ax.add_collection3d(Poly3DCollection(
                faces_laje, facecolors=tema.COR_LAJE, edgecolors="none",
                alpha=0.10))

        for familia, fios in armadura.por_familia().items():
            segmentos = []
            for fio in fios:
                segmentos.extend([[fio.pontos[k], fio.pontos[k + 1]]
                                  for k in range(len(fio.pontos) - 1)])
                pontos.append(fio.pontos)
            if not segmentos:
                continue
            self.ax.add_collection3d(Line3DCollection(
                segmentos, colors=tema.COR_ARMADURA.get(familia, "#000000"),
                linewidths=0.9, label=familia))

        for face in faces + faces_laje:
            pontos.append(face)

        self._proporcao_real(modelo,
                             np.vstack(pontos) if pontos else None,
                             apenas_extras=bool(pontos))
        self.ax.set_title(
            f"Armadura da cota {armadura.cota:g} m — {len(armadura.fios)} "
            f"barras, {armadura.segmentos} segmentos, "
            f"{armadura.aco:.0f} m de aço", color=tema.AZUL, fontsize=10)
        if armadura.fios:
            self.ax.legend(loc="upper left", fontsize=7, framealpha=0.8)
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
