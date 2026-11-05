# -*- coding: utf-8 -*-
"""
vista3d.py
Desenho do pórtico: modelo, deformada, diagramas e modos de flambagem.

A deformada não liga os nós deslocados por retas. Ela é traçada com as
**mesmas funções de forma** que o solver usa para montar o vetor de
engastamento perfeito, de modo que a curva desenhada é a curva que a
formulação descreve — inclusive a curvatura que aparece dentro de uma barra
carregada, que a ligação por retas esconderia justamente onde ela interessa.

## Motor de desenho: PyVista/VTK (revisão R03)

Era matplotlib; virou PyVista/VTK, seguindo o mesmo caminho que Consolos R03
e Lajes R06 já fizeram (ver as memórias ``programa-consolos-r03-vista3d`` e
``programa-lajes-r06-pyvista``). Toda a geometria pura — ``perfil_da_secao``,
``faces_da_barra``, ``faces_da_laje``, ``_forma_deformada``,
``pontos_do_diagrama`` — continua exatamente igual; só a representação final
mudou, de ``Poly3DCollection``/``Line3DCollection`` para ``PolyData``.

**Arquitetura de janela**: as seis vistas "Modelo", "3D" (sólido), "Laje",
"Deformada", os componentes de esforço e "Modo de flambagem" usam o widget
embutido (``Vista3D``, um ``pyvistaqt.QtInteractor``) dentro da aba — o
número de atores em cada uma é baixo o bastante para não pesar o widget
embutido. Só "Armadura" abre como **janela nativa separada**
(``VistaArmadura3D``/``abrir_vista_interativa_armadura``), porque é ali que o
número de segmentos cresce (um pavimento inteiro de aço) e o widget Qt
embutido mede ~16 ms por evento de mouse contra ~2 ms da janela nativa — a
mesma lição registrada em Consolos R03 e Lajes R06.

**Picking** (nó/barra sob o mouse ou clicado) só existe em "Modelo" e
"Sólido", que são as vistas de conferência de entrada de dados — é ali que
faz sentido perguntar "que barra é essa" ou "que seção tem essa barra".
"Deformada" e "Modo de flambagem" continuam desenhadas como esqueleto de
linhas, sem picking. O "Diagrama de esforços" ganhou duas representações,
alternadas por um botão da barra de ferramentas: "barras" (o esqueleto de
sempre) e "3D" (o sólido extrudado da seção real, com o diagrama desenhado
ao redor dele — para deixar óbvio quando um elemento muito solicitado tem
seção pequena).

**Offscreen e ``--autoteste``**: só o ``render()``/``screenshot()`` final de
um ``QtInteractor`` falha sob ``QT_QPA_PLATFORM=offscreen``
(``RenderWindowUnavailable``) — montar a cena inteira (``add_mesh``,
``reset_camera``, ``add_text``, os observadores de picking) funciona
normalmente. ``_render_seguro()`` isola essa chamada; o autoteste confere o
**conteúdo** da cena (contagem de atores), não o pixel renderizado.
"""

from __future__ import annotations

import math
import os

import numpy as np

os.environ.setdefault("QT_API", "pyside6")

import pyvista as pv
from pyvistaqt import QtInteractor
from vtkmodules.vtkRenderingCore import vtkCellPicker

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

#: Unidade de cada componente — a leitura de projeto sem unidade não vale.
UNIDADE_DO_ESFORCO = {"N": "kN", "Vy": "kN", "Vz": "kN",
                      "T": "kN·m", "My": "kN·m", "Mz": "kN·m"}

#: As duas representações do Diagrama de esforços.
REPRESENTACOES_DE_DIAGRAMA = ("barras", "3D")

#: Cor de destaque do picking — âmbar, a mesma semântica de "atenção" do
#: resto da casa (ver Consolos R03 / Lajes R06).
_AMBAR = (0.69, 0.49, 0.11)

#: Onde fica o texto da leitura (clique): coordenadas **normalizadas** da
#: janela, de 0 a 1. Ficava em "upper_left" e cobria a legenda da vista, que
#: ocupa o alto; mais abaixo as duas não se encontram.
POSICAO_DA_LEITURA = (0.01, 0.66)

COR_FORCA = "#c0392b"
COR_MOMENTO = "#8e44ad"
COR_DISTRIBUIDA = "#2e6da4"
COR_RECALQUE = "#e67e22"

#: Uma cor por caso, quando vários aparecem juntos na vista de cargas.
CORES_DOS_CASOS = ["#2e6da4", "#16a085", "#d35400", "#7f8c8d", "#c0392b",
                   "#8e44ad"]
_OPACIDADE_APAGADA = 0.15

_MENSAGEM_ARMADURA = (
    "Gire com o botão esquerdo, aproxime com a roda do mouse.\n"
    "Passe sobre uma família de armadura para identificá-la — ou clique\n"
    "para fixar a explicação."
)


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
    """As faces do sólido da barra, no sistema global.

    A viga sobe o que for preciso para o topo ficar no nível do pavimento
    (``core.lajes.desnivel_da_viga``), como a laje e a armadura."""
    from ..core.lajes import desnivel_da_viga

    if len(perfil) == 0:
        return []
    nome = next((n for n, b in modelo.barras.items()
                 if b is preparada.barra), None)
    dz = np.array([0.0, 0.0, desnivel_da_viga(modelo, nome)
                   if nome is not None else 0.0])
    pi = modelo.ponto(preparada.barra.no_i) + dz
    pj = modelo.ponto(preparada.barra.no_j) + dz
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
    """A placa da laje, com o topo alinhado ao topo das vigas de contorno.

    O modelo refere tudo ao eixo das barras, mas é assim que a laje aparece no
    prédio — nivelada com as vigas, e não atravessada por elas ao meio. A
    altura vem de ``core.lajes.deslocamento_do_centro``.
    """
    from ..core.lajes import contorno, deslocamento_do_centro

    try:
        base = contorno(modelo, laje)
    except ErroDeModelo:
        return []
    meia = max(laje.altura, 0.01) / 2.0
    # O topo da laje fica no **topo das vigas**: o plano dos nós passa pelo eixo
    # das barras, e a viga sobe meia altura acima dele.
    centro = deslocamento_do_centro(modelo, laje)
    baixo = base + np.array([0.0, 0.0, centro - meia])
    cima = base + np.array([0.0, 0.0, centro + meia])

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


# ---------------------------------------------------------------------------
# Helpers de conversão para PyVista
# ---------------------------------------------------------------------------

def _rgb(cor_hex: str) -> tuple[float, float, float]:
    """``"#RRGGBB"`` -> ``(r, g, b)`` em [0, 1], o que ``add_mesh`` espera."""
    cor_hex = cor_hex.lstrip("#")
    return tuple(int(cor_hex[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _malha_das_faces(faces: list[np.ndarray]) -> pv.PolyData | None:
    """Um ``PolyData`` de polígonos soltos, cada face com os próprios pontos.

    Não solda vértices entre faces: cada uma é plana e independente, o que
    dispensa calcular normais compartilhadas — a barra e a laje já vêm com a
    face certa a cada painel.
    """
    pontos, celulas = [], []
    offset = 0
    for face in faces:
        n = len(face)
        if n < 3:
            continue
        pontos.extend(face)
        celulas.append(n)
        celulas.extend(range(offset, offset + n))
        offset += n
    if not pontos:
        return None
    malha = pv.PolyData(np.asarray(pontos), np.asarray(celulas))
    malha = malha.compute_normals(auto_orient_normals=False,
                                  split_vertices=True, inplace=False)
    return malha


def _malha_de_linhas(segmentos: list[tuple[np.ndarray, np.ndarray]]
                     ) -> pv.PolyData | None:
    """Um ``PolyData`` de segmentos soltos (não uma polilinha contínua)."""
    if not segmentos:
        return None
    pontos, linhas = [], []
    offset = 0
    for a, b in segmentos:
        pontos.append(a)
        pontos.append(b)
        linhas.extend([2, offset, offset + 1])
        offset += 2
    return pv.PolyData(np.asarray(pontos), lines=np.asarray(linhas))


# ---------------------------------------------------------------------------
# Vista embutida (widget Qt) — Modelo, Sólido, Laje, Deformada, Diagramas,
# Modo de flambagem
# ---------------------------------------------------------------------------

class Vista3D(QtInteractor):
    """Tela de desenho do pórtico, embutida na aba, com picking em duas
    vistas ("Modelo" e "Sólido")."""

    def __init__(self) -> None:
        super().__init__()
        self.modelo: Modelo | None = None
        self.resultado: Resultado | None = None
        self._callback_selecao = None
        self._picker = vtkCellPicker()
        self._picker.SetTolerance(0.003)
        self.iren.add_observer("MouseMoveEvent", self._ao_mover)
        self.iren.add_observer("LeftButtonPressEvent", self._ao_clicar)
        # O valor do esforço é lido num **clique**, e não no apertar do botão:
        # apertar também começa a girar o desenho, e ler o valor a cada giro
        # seria o oposto de ajudar. Clique é apertar e soltar quase no mesmo
        # lugar.
        self.iren.add_observer("LeftButtonReleaseEvent", self._ao_soltar)
        self._pos_apertado = None
        #: As lajes do modelo 3D aparecem ou não. Fica fora de ``_limpar``:
        #: é escolha do usuário, e tem de sobreviver a cada redesenho.
        self._lajes_visiveis = True
        self._limpar()

    # -- integração com a janela --------------------------------------------

    def definir_callback_selecao(self, callback) -> None:
        """``callback(info | None)`` — chamado a cada seleção/deseleção.

        ``info`` é ``{"tipo": "no"|"barra", "nome": str}``. Fica centralizado
        aqui para a janela decidir o que sincronizar (tabela ativa) sem
        duplicar a lógica de picking em cada vista.
        """
        self._callback_selecao = callback

    # -- utilidades de desenho -----------------------------------------------

    def _render_seguro(self) -> None:
        """``render()`` só funciona havendo janela de verdade.

        Sob ``QT_QPA_PLATFORM=offscreen`` (o ``--autoteste``) o
        ``QtInteractor`` levanta ``RenderWindowUnavailable`` — ao contrário
        de montar a cena (``add_mesh`` etc.), que funciona normalmente sem
        tela. Ver a nota no topo do módulo.
        """
        try:
            self.render()
        except Exception:                                   # noqa: BLE001
            pass

    def _limpar(self) -> None:
        self.clear()
        self.set_background("white")
        self._info: dict = {}
        self._cor_original: dict = {}
        self._atores: list = []
        self._atual = None
        self._fixado = False
        self._picking_habilitado = False
        #: Contexto do diagrama de esforços na tela (``None`` fora dele) e o
        #: nome da barra de cada ator em que se pode clicar para ler o valor.
        self._esforco: dict | None = None
        self._barra_do_ator: dict = {}
        #: Vista de cargas: o texto de auditoria de cada ator clicável, e o
        #: ator que está destacado agora (com a cor que ele tinha).
        self._cargas: dict | None = None
        #: Quanto já se afastou da barra, por (barra, eixo, sinal): as cargas
        #: que atuam do mesmo lado se empilham em camadas.
        self._camadas: dict = {}
        self._alvo_de_carga: dict = {}
        self._carga_destacada = None

    @staticmethod
    def _dimensao(modelo: Modelo) -> float:
        pontos = np.array([[n.x, n.y, n.z] for n in modelo.nos.values()])
        if len(pontos) == 0:
            return 1.0
        return float(np.max(pontos.max(axis=0) - pontos.min(axis=0))) or 1.0

    def _raio_barra(self, modelo: Modelo) -> float:
        return max(0.006 * self._dimensao(modelo), 0.01)

    def _titulo(self, texto: str, cor: str = tema.AZUL) -> None:
        self.add_text(texto, position="upper_edge", font_size=10, color=cor,
                     name="titulo")

    def _linhas_do_modelo(self, modelo: Modelo, cor: str, largura: float,
                          nome: str = "linhas_modelo",
                          opacidade: float = 1.0) -> None:
        segmentos = [_pontos_da_barra(modelo, nome_barra)
                    for nome_barra in modelo.barras]
        malha = _malha_de_linhas(segmentos)
        if malha is not None:
            self.add_mesh(malha, color=cor, line_width=largura,
                         opacity=opacidade, render_lines_as_tubes=True,
                         pickable=False, name=nome)

    def _desenhar_curvas(self, curvas: list[np.ndarray], cor: str,
                         largura: float, nome: str) -> None:
        segmentos = []
        for curva in curvas:
            segmentos.extend([(curva[k], curva[k + 1])
                              for k in range(len(curva) - 1)])
        malha = _malha_de_linhas(segmentos)
        if malha is not None:
            self.add_mesh(malha, color=cor, line_width=largura,
                         render_lines_as_tubes=True, pickable=False,
                         name=nome)

    def _apoios(self, modelo: Modelo) -> None:
        raio = max(self._raio_barra(modelo) * 2.0, 0.04)
        eng, mov, mola = [], [], []
        for nome, apoio in modelo.apoios.items():
            p = modelo.ponto(nome)
            (eng if all(apoio.restricoes) else mov).append(p)
        for nome in modelo.molas:
            mola.append(modelo.ponto(nome))

        if eng:
            nuvem = pv.PolyData(np.array(eng))
            cubo = pv.Cube(x_length=raio * 1.8, y_length=raio * 1.8,
                          z_length=raio * 1.8)
            self.add_mesh(nuvem.glyph(geom=cubo, scale=False),
                         color=tema.COR_APOIO, pickable=False,
                         name="apoios_engaste")
        if mov:
            nuvem = pv.PolyData(np.array(mov))
            cone = pv.Cone(height=raio * 1.8, radius=raio,
                          direction=(0.0, 0.0, 1.0))
            self.add_mesh(nuvem.glyph(geom=cone, scale=False),
                         color=tema.COR_APOIO, pickable=False,
                         name="apoios_movel")
        if mola:
            nuvem = pv.PolyData(np.array(mola))
            cubo = pv.Cube(x_length=raio * 1.4, y_length=raio * 1.4,
                          z_length=raio * 1.4)
            self.add_mesh(nuvem.glyph(geom=cubo, scale=False),
                         color=tema.COR_MOLA, pickable=False, name="molas")

    def _rotulos(self, modelo: Modelo, mostrar_nos: bool,
                 mostrar_barras: bool) -> None:
        if mostrar_nos and modelo.nos:
            pontos = np.array([modelo.ponto(n) for n in modelo.nos])
            self.add_point_labels(pontos, list(modelo.nos),
                                  name="rotulos_nos", text_color=tema.COR_NO,
                                  font_size=12, shape=None,
                                  always_visible=True, shape_opacity=0.0)
        if mostrar_barras and modelo.barras:
            pontos, nomes = [], []
            for nome in modelo.barras:
                pi, pj = _pontos_da_barra(modelo, nome)
                pontos.append((pi + pj) / 2.0)
                nomes.append(nome)
            self.add_point_labels(np.array(pontos), nomes,
                                  name="rotulos_barras",
                                  text_color=tema.COR_BARRA, font_size=12,
                                  shape=None, always_visible=True,
                                  shape_opacity=0.0)

    # -- picking --------------------------------------------------------------

    def _finalizar_pickable(self, info_por_nome: dict) -> None:
        """Religa nome -> ator vivo depois de toda a cena montada.

        Chaveado pelo ``name=`` de ``add_mesh``, e não por ``id(ator)``: o
        objeto devolvido por ``add_mesh`` não fica retido em lugar nenhum
        além da variável local do laço de montagem, e o GC do Python pode
        reciclar o endereço antes do laço terminar (ver as memórias do
        Consolos R03 e do Lajes R06).
        """
        self._info = {}
        self._cor_original = {}
        self._atores = []
        for nome, ator in self.renderer.actors.items():
            if nome in info_por_nome:
                self._info[ator] = info_por_nome[nome]
                self._cor_original[ator] = ator.GetProperty().GetColor()
                self._atores.append(ator)
        self._atual = None
        self._fixado = False

    def _ator_sob_o_mouse(self):
        x, y = self.iren.get_event_position()
        self._picker.Pick(x, y, 0, self.renderer)
        ator = self._picker.GetActor()
        return ator if ator is not None and ator in self._info else None

    def _destacar(self, ator) -> None:
        for outro in self._atores:
            prop = outro.GetProperty()
            if outro is ator:
                prop.SetColor(*_AMBAR)
                prop.SetOpacity(1.0)
            else:
                prop.SetOpacity(_OPACIDADE_APAGADA)

    def _limpar_destaque(self) -> None:
        for ator in self._atores:
            prop = ator.GetProperty()
            cor = self._cor_original.get(ator)
            if cor is not None:
                prop.SetColor(*cor)
            prop.SetOpacity(1.0)

    def _texto_do_elemento(self, info: dict) -> str:
        modelo = self.modelo
        if info["tipo"] == "no":
            no = modelo.nos[info["nome"]]
            linhas = [f"Nó {info['nome']}",
                     f"({no.x:g}, {no.y:g}, {no.z:g}) m"]
            apoio = modelo.apoios.get(info["nome"])
            if apoio is not None:
                graus = ", ".join(
                    g for g, r in zip(("ux", "uy", "uz", "rx", "ry", "rz"),
                                      apoio.restricoes) if r)
                linhas.append(f"Apoio: {graus or '(nenhuma restrição)'}")
            if info["nome"] in modelo.molas:
                linhas.append("Mola de apoio")
            return "\n".join(linhas)

        barra = modelo.barras[info["nome"]]
        pi, pj = _pontos_da_barra(modelo, info["nome"])
        comp = float(np.linalg.norm(pj - pi))
        return (f"Barra {info['nome']}\nMaterial: {barra.material}\n"
                f"Seção: {barra.secao}\nComprimento: {comp:.2f} m")

    def _aplicar_selecao(self, ator) -> None:
        if ator is not None:
            self._destacar(ator)
            info = self._info[ator]
            self.add_text(self._texto_do_elemento(info), position="upper_left",
                         font_size=9, color=tema.COR_BARRA, name="tooltip")
        else:
            self._limpar_destaque()
            self.add_text("", position="upper_left", font_size=9,
                         name="tooltip")
            info = None
        self._render_seguro()
        if self._callback_selecao is not None:
            self._callback_selecao(info)

    def _ao_mover(self, _caller, _evento) -> None:
        if not self._picking_habilitado or self._fixado:
            return
        ator = self._ator_sob_o_mouse()
        if ator is self._atual:
            return
        self._atual = ator
        self._aplicar_selecao(ator)

    def _ao_clicar(self, _caller, _evento) -> None:
        self._pos_apertado = tuple(self.iren.get_event_position())
        if not self._picking_habilitado:
            return
        ator = self._ator_sob_o_mouse()
        if ator is None:
            if self._fixado:
                self._fixado = False
                self._atual = None
                self._aplicar_selecao(None)
            return
        if self._fixado and ator is self._atual:
            self._fixado = False
            self._aplicar_selecao(None)
        else:
            self._fixado = True
            self._atual = ator
            self._aplicar_selecao(ator)

    # -- desenho ---------------------------------------------------------------

    def desenhar_modelo(self, modelo: Modelo, rotulos_nos: bool = False,
                        rotulos_barras: bool = False) -> None:
        self.modelo, self.resultado = modelo, None
        self._limpar()
        if not modelo.nos:
            self._titulo("modelo vazio")
            self._render_seguro()
            return

        raio = self._raio_barra(modelo)
        info = {}
        for nome in modelo.barras:
            pi, pj = _pontos_da_barra(modelo, nome)
            tubo = pv.Line(pi, pj).tube(radius=raio)
            ator_nome = f"barra_{nome}"
            self.add_mesh(tubo, color=tema.COR_BARRA, name=ator_nome,
                         pickable=True, smooth_shading=True)
            info[ator_nome] = {"tipo": "barra", "nome": nome}

        raio_no = raio * 1.8
        for nome in modelo.nos:
            esfera = pv.Sphere(radius=raio_no, center=modelo.ponto(nome))
            ator_nome = f"no_{nome}"
            self.add_mesh(esfera, color=tema.COR_NO, name=ator_nome,
                         pickable=True)
            info[ator_nome] = {"tipo": "no", "nome": nome}

        self._apoios(modelo)
        self._rotulos(modelo, rotulos_nos, rotulos_barras)
        self._finalizar_pickable(info)
        self._picking_habilitado = True
        self._titulo(f"{len(modelo.nos)} nós · {len(modelo.barras)} barras")
        self.reset_camera()
        self._render_seguro()

    def definir_lajes_visiveis(self, visivel: bool) -> None:
        """Mostra ou esconde as lajes **sem redesenhar**: só liga ou desliga os
        atores, e a câmera fica onde o usuário a deixou."""
        self._lajes_visiveis = bool(visivel)
        for nome, ator in self.renderer.actors.items():
            if nome.startswith("laje_"):
                ator.SetVisibility(self._lajes_visiveis)
        self._render_seguro()

    def desenhar_solido(self, modelo: Modelo) -> None:
        """A estrutura com as dimensões reais das seções, não com linhas.

        Serve para conferir o que a tabela diz: seção trocada, barra girada,
        laje na cota errada — tudo isso salta aos olhos aqui e passa
        despercebido no desenho de eixos.
        """
        from ..core.montagem import preparar_barras

        self.modelo, self.resultado = modelo, None
        self._limpar()
        if not modelo.barras:
            self._titulo("modelo sem barras")
            self._render_seguro()
            return

        try:
            preparadas = preparar_barras(modelo)
        except ErroDeModelo as erro:
            self._titulo(f"modelo incompleto: {erro}", tema.VERMELHO)
            self._render_seguro()
            return

        info = {}
        for nome, p in preparadas.items():
            secao = modelo.secoes[p.barra.secao]
            malha = _malha_das_faces(faces_da_barra(modelo, p,
                                                    perfil_da_secao(secao)))
            ator_nome = f"barra_{nome}"
            if malha is None:
                pi, pj = _pontos_da_barra(modelo, nome)
                malha = pv.Line(pi, pj).tube(radius=self._raio_barra(modelo))
            self.add_mesh(malha, color=tema.COR_SOLIDO, show_edges=True,
                         edge_color=tema.COR_BARRA, line_width=0.5,
                         name=ator_nome, pickable=True)
            info[ator_nome] = {"tipo": "barra", "nome": nome}

        for nome, laje in modelo.lajes.items():
            malha = _malha_das_faces(faces_da_laje(modelo, laje))
            if malha is not None:
                # Opaca: a transparência deixava a laje ao mesmo tempo ali e
                # não ali, e a viga por baixo aparecia pela metade.
                ator = self.add_mesh(malha, color=tema.COR_LAJE,
                                     pickable=False, name=f"laje_{nome}")
                ator.SetVisibility(self._lajes_visiveis)

        raio_no = self._raio_barra(modelo) * 1.8
        for nome in modelo.nos:
            esfera = pv.Sphere(radius=raio_no, center=modelo.ponto(nome))
            ator_nome = f"no_{nome}"
            self.add_mesh(esfera, color=tema.COR_NO, name=ator_nome,
                         pickable=True)
            info[ator_nome] = {"tipo": "no", "nome": nome}

        self._apoios(modelo)
        self._finalizar_pickable(info)
        self._picking_habilitado = True
        self._titulo(f"{len(modelo.barras)} barras e {len(modelo.lajes)} "
                    "lajes em dimensão real")
        self.reset_camera()
        self._render_seguro()

    def desenhar_lajes(self, modelo: Modelo,
                       cota: float | None = None) -> list[str]:
        """Planta das lajes: charneiras plásticas e momentos nas duas direções.

        As vigas e os pilares aparecem apagados e sem dado nenhum — eles são
        contorno, não o assunto. O assunto é o painel: as linhas de ruptura e
        os momentos que o programa de Lajes calculou para ele.

        Desenha **um nível por vez**, porque planta de laje é de um pavimento:
        com os quatro pavimentos de um edifício sobrepostos, as charneiras de
        todos caem umas sobre as outras e não se lê nada. ``cota`` escolhe o
        nível; sem ela, entram todos. Sem picking — é vista de conferência de
        cálculo, não de entrada de dados.
        """
        from ..core.programa_lajes import (calcular_momentos, charneiras,
                                           vinculos_automaticos)

        self.modelo, self.resultado = modelo, None
        self._limpar()
        self._linhas_do_modelo(modelo, tema.COR_CONTEXTO, 1.0, opacidade=0.9)
        self._apoios(modelo)

        if not modelo.lajes:
            self._titulo("o modelo não tem lajes")
            self.reset_camera()
            self._render_seguro()
            return ["O modelo não tem lajes."]

        automaticos = vinculos_automaticos(modelo)
        relatorio: list[str] = []
        contornos, linhas_charneira = [], []
        rotulos_pts, rotulos_txt = [], []

        for nome, laje in modelo.lajes.items():
            if cota is not None and abs(
                    modelo.ponto(laje.no_a)[2] - cota) > 1e-6:
                continue
            if laje.trelicada:
                # A treliçada não tem charneira nem momento por tabela: é
                # armada numa direção, por faixa (Dimensionar > Lajes).
                relatorio.append(f"{nome}: treliçada, nervuras em "
                                 f"{laje.direcao.upper()} — momentos por "
                                 "faixa no Dimensionar lajes")
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
                linhas_charneira.extend(
                    [(pontos[k], pontos[k + 1])
                     for k in range(len(pontos) - 1)])

            centro = contorno.mean(axis=0)
            outra = "y" if momentos.direcao_a == "X" else "x"
            rotulos_pts.append(centro)
            rotulos_txt.append(
                f"{nome}\nm{momentos.direcao_a.lower()}={momentos.ma:.1f}\n"
                f"m{outra}={momentos.mb:.1f}")
            relatorio.append(str(momentos))

        for i, contorno in enumerate(contornos):
            malha = _malha_das_faces([contorno])
            if malha is not None:
                self.add_mesh(malha, color=tema.COR_LAJE, opacity=0.20,
                             show_edges=True, edge_color=tema.COR_BARRA,
                             pickable=False, name=f"painel_{i}")
        malha_charneiras = _malha_de_linhas(linhas_charneira)
        if malha_charneiras is not None:
            self.add_mesh(malha_charneiras, color=tema.COR_CHARNEIRA,
                         line_width=2.5, render_lines_as_tubes=True,
                         pickable=False, name="charneiras")
        if rotulos_pts:
            self.add_point_labels(np.array(rotulos_pts), rotulos_txt,
                                  name="rotulos_lajes",
                                  text_color=tema.COR_MOMENTO_VAO,
                                  font_size=11, shape=None,
                                  always_visible=True, shape_opacity=0.0)

        onde = f"cota {cota:.2f} m" if cota is not None else "todos os níveis"
        self._titulo(f"{len(contornos)} lajes na {onde} — charneiras "
                    "plásticas e momentos em kN·m/m")
        self.view_xy()
        self.reset_camera()
        self._render_seguro()
        return relatorio

    def preparar_aviso_armadura(self, cota: float, armadura) -> None:
        """O que o widget embutido mostra quando "Armadura" é escolhida.

        A vista de Armadura, por decisão do usuário, é a única que abre como
        **janela nativa separada** (ver ``abrir_vista_interativa_armadura``):
        o widget embutido só avisa que os dados já foram calculados e convida
        a abrir a janela.
        """
        self.modelo, self.resultado = None, None
        self._limpar()
        self._titulo(
            f"Armadura da cota {cota:g} m calculada — {len(armadura.fios)} "
            f"barras, {armadura.aco:.0f} m de aço.\n"
            "Use \"Abrir vista 3D da armadura\" para a janela interativa, "
            "com destaque por família sob o mouse.")
        self._render_seguro()

    def desenhar_deformada(self, resultado: Resultado,
                           escala: float | None = None) -> float:
        modelo = resultado.modelo
        self.modelo, self.resultado = modelo, resultado
        self._limpar()
        self._linhas_do_modelo(modelo, "#b9c1cc", 1.0, nome="linhas_base",
                              opacidade=0.8)

        escala = escala if escala is not None else self._escala_automatica(
            modelo, resultado.deslocamentos)

        curvas = [_forma_deformada(resultado, nome, resultado.deslocamentos,
                                   escala)
                  for nome in modelo.barras]
        self._desenhar_curvas(curvas, tema.COR_DEFORMADA, 3.0, "deformada")
        self._apoios(modelo)
        self._titulo(f"deformada de '{resultado.caso}' — escala {escala:.0f}×"
                    + ("  (2ª ordem)" if resultado.segunda_ordem else ""))
        self.reset_camera()
        self._render_seguro()
        return escala

    def desenhar_modo(self, modelo: Modelo, resultado: Resultado,
                      modo: np.ndarray, fator: float, indice: int,
                      escala: float | None = None) -> float:
        self.modelo, self.resultado = modelo, None
        self._limpar()
        self._linhas_do_modelo(modelo, "#b9c1cc", 1.0, nome="linhas_base",
                              opacidade=0.8)

        escala = escala if escala is not None else self._escala_automatica(
            modelo, modo)
        curvas = [_forma_deformada(resultado, nome, modo, escala)
                  for nome in modelo.barras]
        self._desenhar_curvas(curvas, tema.LARANJA, 3.0, "modo")
        self._apoios(modelo)
        self._titulo(f"modo de flambagem {indice + 1} — fator crítico "
                    f"{fator:.4f}")
        self.reset_camera()
        self._render_seguro()
        return escala

    def desenhar_modo_vibracao(self, modelo: Modelo, resultado: Resultado,
                               modo: np.ndarray, frequencia: float,
                               periodo: float, indice: int,
                               escala: float | None = None) -> float:
        """O modo de vibração livre, mesmo esqueleto de ``desenhar_modo``.

        Só o título muda — frequência e período, não fator crítico —, e o
        modo vem de ``dinamica.analisar_modal`` em vez de
        ``segunda_ordem.flambagem``; a forma de desenhar (curva de Hermite
        por barra, a partir de ``resultado.preparadas``) é a mesma, porque
        um modo é só um vetor de deslocamento nodal, não importa de qual
        autovalor ele veio.
        """
        self.modelo, self.resultado = modelo, None
        self._limpar()
        self._linhas_do_modelo(modelo, "#b9c1cc", 1.0, nome="linhas_base",
                              opacidade=0.8)

        escala = escala if escala is not None else self._escala_automatica(
            modelo, modo)
        curvas = [_forma_deformada(resultado, nome, modo, escala)
                  for nome in modelo.barras]
        self._desenhar_curvas(curvas, tema.LARANJA, 3.0, "modo")
        self._apoios(modelo)
        self._titulo(f"modo de vibração {indice + 1} — "
                    f"f = {frequencia:.4f} Hz   T = {periodo:.4f} s")
        self.reset_camera()
        self._render_seguro()
        return escala

    def desenhar_diagrama(self, resultado: Resultado, componente: str,
                          escala: float | None = None,
                          representacao: str = "barras") -> float:
        from ..core.montagem import preparar_barras

        modelo = resultado.modelo
        self.modelo, self.resultado = modelo, resultado
        self._limpar()

        diagramas = {nome: resultado.diagrama(nome, ESTACOES)
                     for nome in modelo.barras}
        valores = (np.concatenate([getattr(d, componente)
                                   for d in diagramas.values()])
                  if diagramas else np.zeros(1))
        pico = float(np.max(np.abs(valores))) or 1.0
        escala = escala if escala is not None else (
            0.10 * self._dimensao(modelo) / pico)

        # Atores em que se pode clicar para ler o esforço: a barra (o eixo, ou
        # o sólido no modo 3D) e a área do diagrama. Cada um guarda o nome da
        # barra a que pertence.
        clicaveis: dict[str, str] = {}

        if representacao == "3D":
            try:
                preparadas = preparar_barras(modelo)
            except ErroDeModelo:
                preparadas = {}
            for nome, p in preparadas.items():
                secao = modelo.secoes[p.barra.secao]
                malha = _malha_das_faces(
                    faces_da_barra(modelo, p, perfil_da_secao(secao)))
                if malha is not None:
                    self.add_mesh(malha, color=tema.COR_SOLIDO, opacity=0.35,
                                 show_edges=True, edge_color=tema.COR_BARRA,
                                 line_width=0.4, pickable=True,
                                 name=f"solido_{nome}")
                    clicaveis[f"solido_{nome}"] = nome
        else:
            raio = self._raio_barra(modelo) * 0.6
            for nome in modelo.barras:
                pi, pj = _pontos_da_barra(modelo, nome)
                self.add_mesh(pv.Line(pi, pj).tube(radius=raio),
                              color=tema.COR_BARRA, pickable=True,
                              name=f"eixo_{nome}")
                clicaveis[f"eixo_{nome}"] = nome

        positivos, negativos = [], []
        tracados = []
        for nome in diagramas:
            base, topo, valor = pontos_do_diagrama(resultado, nome,
                                                   componente, escala,
                                                   ESTACOES)
            tracados.append(topo)
            # A área entre a barra e o diagrama é clicável: tocar nela, e não
            # só na linha fina, já lê o valor. Duas áreas por barra quando o
            # esforço troca de sinal, cada uma na cor do seu sinal.
            for sinal, cor, rotulo in (
                    (1.0, tema.COR_DIAGRAMA_POSITIVO, "pos"),
                    (-1.0, tema.COR_DIAGRAMA_NEGATIVO, "neg")):
                faixas = [np.array([base[k], base[k + 1], topo[k + 1],
                                    topo[k]])
                          for k in range(len(valor) - 1)
                          if sinal * (valor[k] + valor[k + 1]) > 0.0]
                malha_area = _malha_das_faces(faixas) if faixas else None
                if malha_area is not None:
                    nome_ator = f"esf_{rotulo}_{nome}"
                    self.add_mesh(malha_area, color=cor, opacity=0.28,
                                 pickable=True, name=nome_ator)
                    clicaveis[nome_ator] = nome
            for k in range(len(valor) - 1):
                trecho = (topo[k], topo[k + 1])
                alvo = positivos if valor[k] + valor[k + 1] >= 0 else negativos
                alvo.append(trecho)
            for k in range(0, len(valor), 3):
                alvo = positivos if valor[k] >= 0 else negativos
                alvo.append((base[k], topo[k]))

        for trechos, cor, nome_ator in (
                (positivos, tema.COR_DIAGRAMA_POSITIVO, "diagrama_pos"),
                (negativos, tema.COR_DIAGRAMA_NEGATIVO, "diagrama_neg")):
            malha = _malha_de_linhas(trechos)
            if malha is not None:
                self.add_mesh(malha, color=cor, line_width=1.8,
                             render_lines_as_tubes=True, pickable=False,
                             name=nome_ator)

        self._apoios(modelo)
        nota = ("  ·  traçado do lado tracionado"
                if componente in ("My", "Mz") else "")
        self._titulo(f"{componente} de '{resultado.caso}' — máximo "
                    f"{pico:.4g}{nota}  ·  representação: {representacao}\n"
                    "clique numa barra ou no diagrama para ler o valor")
        # Religa nome -> ator vivo depois da cena inteira montada, pelo
        # ``name=`` de ``add_mesh`` e não por ``id(ator)`` (o GC recicla o
        # endereço dentro de um laço).
        self._barra_do_ator = {
            ator: clicaveis[nome]
            for nome, ator in self.renderer.actors.items()
            if nome in clicaveis}
        self._esforco = {"resultado": resultado, "componente": componente,
                         "escala": escala}
        self.reset_camera()
        self._render_seguro()
        return escala

    # -- cargas aplicadas -----------------------------------------------------

    def desenhar_cargas(self, modelo: Modelo, casos,
                        escala: float | None = None) -> float:
        """As cargas de um ou de **vários** casos, para conferir o que está
        sendo considerado.

        Cada carga é uma seta que aponta para onde ela atua, de tamanho
        fixo (o valor está no rótulo e no clique): força nodal em vermelho, momento em roxo
        (eixo do vetor, regra da mão direita), carga distribuída em azul — uma
        fileira de setas com a linha que une as caudas, que é o diagrama da
        carga —, e recalque como um cubo laranja no nó. O título traz a
        **resultante**: a soma das forças no sistema global, que é a primeira
        coisa a conferir (o peso próprio tem de bater com o peso da estrutura,
        o vento com a força horizontal total).

        **Várias cargas na mesma barra não se sobrepõem**: cada uma fica numa
        camada, empilhadas para fora a partir da barra — a primeira encostada
        nela, a seguinte depois do fim das setas da anterior. Com vários casos
        juntos, cada um tem a sua cor e a etiqueta traz o nome do caso.

        Tudo é clicável: a seta mostra a carga inteira, a barra mostra as
        cargas que caem nela e o nó, as nodais e os recalques dele. É o mesmo
        texto do relatório, que sai de ``core/auditoria_cargas``.
        """
        from ..core import auditoria_cargas as aud
        from ..core.montagem import preparar_barras

        if casos is not None and not isinstance(casos, (list, tuple)):
            casos = [casos]
        casos = list(casos or [])

        self.modelo, self.resultado = modelo, None
        self._limpar()
        if not casos or not modelo.nos:
            self._titulo("sem caso de carga para mostrar")
            self.reset_camera()
            self._render_seguro()
            return 1.0
        try:
            preparadas = preparar_barras(modelo)
        except ErroDeModelo as erro:
            self._titulo(f"modelo incompleto: {erro}", tema.VERMELHO)
            self._render_seguro()
            return 1.0

        varios = len(casos) > 1
        dim = self._dimensao(modelo)
        mult = escala or 1.0
        raio = self._raio_barra(modelo)
        #: nome do ator -> (texto de auditoria, o que sincronizar na tabela)
        alvos: dict[str, tuple[str, dict]] = {}
        rotulos: list[tuple[np.ndarray, str]] = []

        for nome in modelo.barras:
            pi, pj = _pontos_da_barra(modelo, nome)
            self.add_mesh(pv.Line(pi, pj).tube(radius=raio * 0.7),
                          color="#7f8c8d", pickable=True, name=f"eixo_{nome}")
            alvos[f"eixo_{nome}"] = (
                "\n".join(aud.texto_da_barra(modelo, c, nome, preparadas)
                          for c in casos),
                {"tipo": "barra", "nome": nome})
        for nome in modelo.nos:
            self.add_mesh(pv.Sphere(radius=raio * 1.4,
                                    center=modelo.ponto(nome)),
                          color=tema.COR_NO, pickable=True, name=f"no_{nome}")
            alvos[f"no_{nome}"] = (
                "\n".join(aud.texto_do_no(c, nome) for c in casos),
                {"tipo": "no", "nome": nome})

        todas_nodais = [c for caso in casos for c in caso.nodais]
        todas_distribuidas = [(caso, c) for caso in casos
                              for c in caso.distribuidas]
        f_max = max([float(np.linalg.norm(c.vetor[:3]))
                     for c in todas_nodais] or [0.0]) or 1.0
        m_max = max([float(np.linalg.norm(c.vetor[3:]))
                     for c in todas_nodais] or [0.0]) or 1.0
        modulos = []
        for _, c in todas_distribuidas:
            qa, qb = aud.intensidades_globais(c, preparadas)
            modulos += [float(np.linalg.norm(qa)), float(np.linalg.norm(qb))]
        q_max = max(modulos or [0.0]) or 1.0

        def camada_de(c) -> tuple:
            """Em que pilha de camadas a carga cai. As que atuam na mesma
            barra e para o mesmo lado (mesmo eixo e sinal) se empilham; a que
            atua para o outro lado — o vento contra a gravidade — não disputa
            lugar. A carga **ao longo** da barra (o peso próprio de um pilar)
            não se empilha para fora: ela vai ao lado da barra."""
            pi, pj = _pontos_da_barra(modelo, c.barra)
            qa, qb = aud.intensidades_globais(c, preparadas)
            dominante = qa if (np.linalg.norm(qa) >= np.linalg.norm(qb)) \
                else qb
            eixo_barra = (pj - pi) / (float(np.linalg.norm(pj - pi)) or 1.0)
            modulo = float(np.linalg.norm(dominante))
            if modulo > 1e-12 and abs(float(np.dot(dominante / modulo,
                                                   eixo_barra))) > 0.9:
                return (c.barra, "axial"), True, eixo_barra
            eixo = int(np.argmax(np.abs(dominante)))
            return ((c.barra, eixo, 1 if dominante[eixo] >= 0 else -1),
                    False, eixo_barra)

        # Tamanho fixo: a seta indica direção e sentido; o valor está no
        # rótulo e na auditoria por clique, não no comprimento.
        comprimento_f = 0.07 * dim * mult
        comprimento_q = 0.04 * dim * mult
        folga = 0.12 * comprimento_q
        com_rotulo = len(todas_distribuidas) <= 60
        k = 0

        for indice_caso, caso in enumerate(casos):
            cor_q = (CORES_DOS_CASOS[indice_caso % len(CORES_DOS_CASOS)]
                     if varios else COR_DISTRIBUIDA)
            prefixo = f"{caso.nome}: " if varios else ""

            # -- nodais: forças e momentos -----------------------------------
            for c in caso.nodais:
                ponto = modelo.ponto(c.no)
                for vetor, cor, referencia, nomes, unidade in (
                        (c.vetor[:3], COR_FORCA, f_max, aud.GRAUS[:3], "kN"),
                        (c.vetor[3:], COR_MOMENTO, m_max, aud.GRAUS[3:],
                         "kN·m")):
                    modulo = float(np.linalg.norm(vetor))
                    if modulo < 1e-12:
                        continue
                    direcao = vetor / modulo
                    comp = comprimento_f
                    seta = pv.Arrow(start=ponto - direcao * comp,
                                    direction=direcao, scale=comp,
                                    tip_length=0.32, tip_radius=0.12,
                                    shaft_radius=0.045)
                    nome_ator = f"carga_{k}"
                    k += 1
                    self.add_mesh(seta, color=cor, pickable=True,
                                  name=nome_ator)
                    alvos[nome_ator] = (
                        (f"Caso '{caso.nome}' · " if varios else "")
                        + aud.texto_da_nodal(c),
                        {"tipo": "no", "nome": c.no})
                    partes = [f"{n} = {v:+.2f}" for n, v in zip(nomes, vetor)
                              if abs(v) > 1e-12]
                    rotulos.append((ponto - direcao * comp,
                                    prefixo + ", ".join(partes)
                                    + f" {unidade}"))

            # -- distribuídas: camadas empilhadas a partir da barra ---------
            for c in caso.distribuidas:
                if c.barra not in modelo.barras:
                    continue
                pi, pj = _pontos_da_barra(modelo, c.barra)
                qa, qb = aud.intensidades_globais(c, preparadas)
                trecho = aud.comprimento_do_trecho(modelo, c)
                n = int(np.clip(round(trecho / (0.09 * dim)) + 1, 3, 7))

                chave, axial, eixo_barra = camada_de(c)
                recuo = self._camadas.get(chave, 0.0)
                # Carga ao longo da barra: sai ao lado dela, perpendicular ao
                # eixo, em vez de se empilhar sobre a própria barra.
                lado = np.cross(eixo_barra, [0.0, 0.0, 1.0])
                lado = (lado / float(np.linalg.norm(lado))
                        if np.linalg.norm(lado) > 1e-9
                        else np.array([1.0, 0.0, 0.0]))

                setas, caudas, maior = [], [], 0.0
                for i in range(n):
                    t = i / (n - 1)
                    q = qa + (qb - qa) * t
                    modulo = float(np.linalg.norm(q))
                    ponto = (pi + (pj - pi)
                             * (c.inicio + (c.fim - c.inicio) * t))
                    if modulo < 1e-12:
                        caudas.append(ponto)
                        continue
                    direcao = q / modulo
                    comp = comprimento_q
                    maior = max(maior, comp)
                    if axial:
                        ponta = ponto + lado * (raio * 2.5 + recuo)
                    else:
                        ponta = ponto - direcao * recuo   # camada afastada
                    setas.append(pv.Arrow(start=ponta - direcao * comp,
                                          direction=direcao, scale=comp,
                                          tip_length=0.35, tip_radius=0.11,
                                          shaft_radius=0.04))
                    caudas.append(ponta - direcao * comp)
                self._camadas[chave] = recuo + (raio * 3.0 if axial
                                                else maior + folga)

                partes = list(setas)
                ligacao = _malha_de_linhas(
                    [(caudas[i], caudas[i + 1])
                     for i in range(len(caudas) - 1)])
                if ligacao is not None:
                    partes.append(ligacao)
                if not partes:
                    continue
                malha = pv.merge(partes) if len(partes) > 1 else partes[0]
                nome_ator = f"carga_{k}"
                k += 1
                self.add_mesh(malha, color=cor_q, pickable=True,
                              name=nome_ator)
                alvos[nome_ator] = (
                    (f"Caso '{caso.nome}' · " if varios else "")
                    + aud.texto_da_distribuida(modelo, c, preparadas),
                    {"tipo": "barra", "nome": c.barra})
                if com_rotulo:
                    forte = max(float(np.linalg.norm(qa)),
                                float(np.linalg.norm(qb)))
                    rotulos.append((caudas[len(caudas) // 2],
                                    f"{prefixo}{forte:.2f} kN/m"))

            # -- recalques -----------------------------------------------------
            for c in caso.recalques:
                ponto = modelo.ponto(c.no)
                nome_ator = f"carga_{k}"
                k += 1
                self.add_mesh(pv.Cube(center=ponto, x_length=raio * 3.5,
                                      y_length=raio * 3.5,
                                      z_length=raio * 3.5),
                              color=COR_RECALQUE, pickable=True,
                              name=nome_ator)
                alvos[nome_ator] = (
                    (f"Caso '{caso.nome}' · " if varios else "")
                    + aud.texto_do_recalque(c), {"tipo": "no", "nome": c.no})
                rotulos.append((ponto, prefixo + "recalque"))

        if rotulos:
            self.add_point_labels(
                np.array([p for p, _ in rotulos]), [t for _, t in rotulos],
                font_size=11, text_color="black", shape="rounded_rect",
                shape_color="white", shape_opacity=0.75, show_points=False,
                always_visible=True, name="rotulos_cargas",
                reset_camera=False)

        self._apoios(modelo)
        if varios:
            partes_titulo = []
            for caso in casos:
                s = aud.resultante(modelo, caso, preparadas)["total"]
                eixos = [f"{n}={v:+.1f}" for n, v in zip(("Fx", "Fy", "Fz"), s)
                         if abs(v) > 1e-9]
                partes_titulo.append(f"{caso.nome}: " + (" ".join(eixos)
                                                        or "sem força"))
            self._titulo(f"Cargas de todos os casos ({len(casos)})  ·  "
                         "resultantes (kN)\n" + "   ·   ".join(partes_titulo))
        else:
            caso = casos[0]
            soma = aud.resultante(modelo, caso, preparadas)["total"]
            self._titulo(
                f"Cargas do caso '{caso.nome}' ({caso.natureza})  ·  "
                "resultante: "
                + ", ".join(f"{n} = {v:+.2f}"
                            for n, v in zip(("Fx", "Fy", "Fz"), soma))
                + " kN\n"
                f"{len(caso.nodais)} nodais · {len(caso.distribuidas)} "
                f"distribuídas · {len(caso.recalques)} recalques  ·  clique "
                "numa carga, barra ou nó para auditar")
        legenda = ("vermelho: força · roxo: momento · "
                   + ("cor por caso: " + ", ".join(
                       f"{c.nome}" for c in casos) if varios
                      else "azul: distribuída")
                   + " · laranja: recalque\n"
                   f"maior força {f_max:.2f} kN · maior distribuída "
                   f"{q_max:.2f} kN/m · várias cargas na mesma barra ficam "
                   "em camadas · setas de tamanho fixo (o valor está no rótulo)")
        if not com_rotulo:
            legenda += "  (valores das distribuídas: clique na carga)"
        self.add_text(legenda, position="lower_left", font_size=8,
                      color=tema.COR_BARRA, name="legenda_cargas")

        self._alvo_de_carga = {ator: alvos[nome]
                               for nome, ator in self.renderer.actors.items()
                               if nome in alvos}
        self._cargas = {"casos": [c.nome for c in casos]}
        self.reset_camera()
        self._render_seguro()
        return mult

    def _clicar_carga(self, ator) -> None:
        """O que está sob o clique, em texto, e a seta destacada em âmbar."""
        if self._carga_destacada is not None:
            antigo, cor = self._carga_destacada
            antigo.GetProperty().SetColor(*cor)
            self._carga_destacada = None
        alvo = self._alvo_de_carga.get(ator) if ator is not None else None
        if alvo is None:
            self.add_text("", position=POSICAO_DA_LEITURA, viewport=True,
                          font_size=9, name="valor_esforco")
            self._render_seguro()
            return
        texto, sincronizar = alvo
        self._carga_destacada = (ator, ator.GetProperty().GetColor())
        ator.GetProperty().SetColor(*_AMBAR)
        self.add_text(texto, position=POSICAO_DA_LEITURA, viewport=True,
                      font_size=9, color=tema.COR_BARRA, name="valor_esforco")
        self._render_seguro()
        if self._callback_selecao is not None and sincronizar:
            self._callback_selecao(sincronizar)

    # -- ler o esforço com o clique -------------------------------------------

    def _ao_soltar(self, _caller, _evento) -> None:
        """Um clique (apertar e soltar no mesmo lugar) lê o esforço — ou, na
        vista de cargas, a carga sob o mouse."""
        if ((self._esforco is None and self._cargas is None)
                or self._pos_apertado is None):
            return
        x, y = self.iren.get_event_position()
        x0, y0 = self._pos_apertado
        self._pos_apertado = None
        if (x - x0) ** 2 + (y - y0) ** 2 > 25:        # arrastou: foi um giro
            return
        self._picker.Pick(x, y, 0, self.renderer)
        ator = self._picker.GetActor()
        if self._cargas is not None:
            self._clicar_carga(ator)
            return
        barra = self._barra_do_ator.get(ator) if ator is not None else None
        if barra is None:
            self._limpar_leitura()
            return
        self._ler_esforco(barra, np.array(self._picker.GetPickPosition()))
        if self._callback_selecao is not None:
            self._callback_selecao({"tipo": "barra", "nome": barra})

    def _limpar_leitura(self) -> None:
        for nome in ("marca_esforco", "linha_esforco"):
            self.remove_actor(nome, render=False)
        self.remove_actor("rotulo_esforco", render=False)
        self.add_text("", position=POSICAO_DA_LEITURA, viewport=True,
                      font_size=9, name="valor_esforco")
        self._render_seguro()

    def _ler_esforco(self, barra: str, ponto: np.ndarray) -> str:
        """O esforço da barra no ponto clicado, marcado no diagrama.

        O ponto vem da superfície sob o mouse — o eixo, o sólido ou a área do
        diagrama —, e o que interessa dele é só **onde ao longo da barra** ele
        está: a projeção no eixo. O valor sai do diagrama refinado (81
        estações, e não as 13 do desenho), interpolado nessa posição, porque
        é leitura para projeto e o momento é uma parábola.
        """
        ctx = self._esforco
        resultado, componente = ctx["resultado"], ctx["componente"]
        modelo = resultado.modelo
        pi, pj = _pontos_da_barra(modelo, barra)
        comprimento = float(np.linalg.norm(pj - pi))
        eixo = (pj - pi) / comprimento
        x = float(np.clip(np.dot(ponto - pi, eixo), 0.0, comprimento))

        base, topo, valor = pontos_do_diagrama(resultado, barra, componente,
                                               ctx["escala"], 81)
        xs = (base - pi) @ eixo
        v = float(np.interp(x, xs, valor))
        sobre_o_diagrama = np.array([np.interp(x, xs, topo[:, k])
                                     for k in range(3)])
        no_eixo = pi + eixo * x

        # ``reset_camera=False`` em tudo que se acrescenta: o padrão do
        # PyVista é recentrar a câmera a cada malha nova, e era isso que
        # devolvia a vista à posição inicial a cada clique.
        raio = self._raio_barra(modelo)
        self.add_mesh(pv.Sphere(radius=raio * 2.2, center=sobre_o_diagrama),
                      color=_AMBAR, pickable=False, name="marca_esforco",
                      reset_camera=False)
        afastamento = sobre_o_diagrama - no_eixo
        if float(np.linalg.norm(afastamento)) > 1e-9:
            self.add_mesh(pv.Line(no_eixo, sobre_o_diagrama),
                          color=_AMBAR, line_width=3, pickable=False,
                          name="linha_esforco", reset_camera=False)
            lado = afastamento / float(np.linalg.norm(afastamento))
        else:
            self.remove_actor("linha_esforco", render=False)
            lado = np.cross(eixo, [0.0, 0.0, 1.0])
            lado = lado / (float(np.linalg.norm(lado)) or 1.0)

        unidade = UNIDADE_DO_ESFORCO[componente]
        i_max, i_min = int(np.argmax(valor)), int(np.argmin(valor))
        texto = (
            f"Barra {barra} · {componente} · caso '{resultado.caso}'\n"
            f"No ponto (x = {x:.2f} m de {comprimento:.2f} m): "
            f"{v:+.2f} {unidade}\n"
            f"Nó i: {float(valor[0]):+.2f}   Nó j: {float(valor[-1]):+.2f} "
            f"{unidade}\n"
            f"Máx {float(valor[i_max]):+.2f} (x = {float(xs[i_max]):.2f} m)   "
            f"Mín {float(valor[i_min]):+.2f} (x = {float(xs[i_min]):.2f} m)")
        self.add_text(texto, position=POSICAO_DA_LEITURA, viewport=True,
                      font_size=9, color=tema.COR_BARRA, name="valor_esforco")
        # O valor também fica **ao lado do ponto**, no próprio 3D: é o que se
        # lê de relance, sem tirar o olho do diagrama para o texto do canto.
        self.add_point_labels(
            np.array([sobre_o_diagrama + lado * raio * 7.0]),
            [f"{v:+.2f} {unidade}"], font_size=14, text_color="black",
            shape="rounded_rect", shape_color="white", shape_opacity=0.85,
            show_points=False, always_visible=True, name="rotulo_esforco",
            reset_camera=False)
        self._render_seguro()
        return texto

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


# ---------------------------------------------------------------------------
# Vista de Armadura: janela nativa separada (não embutida)
# ---------------------------------------------------------------------------

def construir_cena_armadura(plotter, modelo: Modelo, armadura, cota: float
                            ) -> dict[str, tuple[str, str]]:
    """Monta a cena da armadura de um pavimento em ``plotter`` (qualquer
    ``pv.Plotter`` — o de tela ou o de fora de tela).

    Devolve ``{nome_do_ator: (título, texto)}`` para quem faz a interação —
    aqui a granularidade do destaque é **por família** (pilar longitudinal,
    viga estribo, laje positiva, ...), a mesma agregação que
    ``ArmaduraDoPavimento.por_familia()`` já usa no resumo textual; detalhar
    por barra individual, como Consolos R03 faz com cada posição, deixaria
    milhares de atores num pavimento inteiro.
    """
    from ..armadura3d import lances_do_pavimento, vigas_do_pavimento
    from ..core.montagem import preparar_barras

    alvos = list(lances_do_pavimento(modelo, cota))
    for viga in vigas_do_pavimento(modelo, cota):
        alvos.extend(viga.barras)

    try:
        preparadas = preparar_barras(modelo)
    except ErroDeModelo:
        preparadas = {}
    for nome in alvos:
        p = preparadas.get(nome)
        if p is None:
            continue
        secao = modelo.secoes[p.barra.secao]
        malha = _malha_das_faces(faces_da_barra(modelo, p,
                                                perfil_da_secao(secao)))
        if malha is not None:
            plotter.add_mesh(malha, color=tema.COR_SOLIDO, opacity=0.15,
                             pickable=False, name=f"concreto_{nome}")

    for nome, laje in modelo.lajes.items():
        if abs(float(modelo.ponto(laje.no_a)[2]) - cota) > 1e-6:
            continue
        malha = _malha_das_faces(faces_da_laje(modelo, laje))
        if malha is not None:
            plotter.add_mesh(malha, color=tema.COR_LAJE, opacity=0.10,
                             pickable=False, name=f"laje_conc_{nome}")

    info: dict[str, tuple[str, str]] = {}
    for familia, fios in armadura.por_familia().items():
        segmentos = []
        for fio in fios:
            segmentos.extend([(fio.pontos[k], fio.pontos[k + 1])
                              for k in range(len(fio.pontos) - 1)])
        malha = _malha_de_linhas(segmentos)
        if malha is None:
            continue
        cor = _rgb(tema.COR_ARMADURA.get(familia, "#000000"))
        nome_ator = "familia_" + familia.replace(" ", "_")
        plotter.add_mesh(malha, color=cor, line_width=2.4,
                         render_lines_as_tubes=True, name=nome_ator)
        comprimento = sum(f.comprimento for f in fios)
        texto = f"{familia}\n{len(fios)} barras, {comprimento:.1f} m de aço"
        info[nome_ator] = (familia, texto)

    plotter.set_background("white")
    return info


def _posicionar_camera_armadura(plotter) -> None:
    plotter.reset_camera()
    plotter.camera.zoom(1.2)


class VistaArmadura3D:
    """Janela nativa do VTK para a armadura de um pavimento, com destaque por
    família sob o mouse ou ao clicar.

    Janela nativa, e não ``pyvistaqt.QtInteractor`` embutido — o padrão já
    adotado por Consolos R03 e Lajes R06: o pavimento inteiro de aço tem
    ordens de magnitude mais segmentos do que "Modelo" ou "Sólido", e o
    widget Qt embutido mede ~16 ms por evento de mouse contra ~2 ms da janela
    nativa.
    """

    def __init__(self, modelo: Modelo, armadura, cota: float,
                titulo: str = "Vista 3D da armadura") -> None:
        self.plotter = pv.Plotter(title=titulo, window_size=[1180, 820])
        self.plotter.set_background("white")
        info_por_nome = construir_cena_armadura(self.plotter, modelo,
                                                armadura, cota)

        self._info: dict = {}
        self._cor_original: dict = {}
        self._atores: list = []
        for nome, ator in self.plotter.renderer.actors.items():
            if nome in info_por_nome:
                self._info[ator] = info_por_nome[nome]
                self._cor_original[ator] = ator.GetProperty().GetColor()
                self._atores.append(ator)
        self._moldura = [a for nome, a in self.plotter.renderer.actors.items()
                         if nome not in info_por_nome]
        self._atual = None
        self._fixado = False
        self._legenda = self.plotter.add_text(
            _MENSAGEM_ARMADURA, position="upper_left", font_size=9,
            color=tema.COR_BARRA, name="legenda_3d")

        self._picker = vtkCellPicker()
        self._picker.SetTolerance(0.003)
        self.plotter.iren.add_observer("MouseMoveEvent", self._ao_mover)
        self.plotter.iren.add_observer("LeftButtonPressEvent", self._ao_clicar)
        _posicionar_camera_armadura(self.plotter)

    def _ator_sob_o_mouse(self):
        x, y = self.plotter.iren.get_event_position()
        self._picker.Pick(x, y, 0, self.plotter.renderer)
        ator = self._picker.GetActor()
        return ator if ator is not None and ator in self._info else None

    def _destacar(self, ator) -> None:
        for outro in self._atores:
            prop = outro.GetProperty()
            if outro is ator:
                prop.SetColor(*_AMBAR)
                prop.SetOpacity(1.0)
            else:
                prop.SetOpacity(_OPACIDADE_APAGADA)
        for peca in self._moldura:
            peca.GetProperty().SetOpacity(0.06)

    def _limpar_destaque(self) -> None:
        for ator in self._atores:
            prop = ator.GetProperty()
            cor = self._cor_original.get(ator)
            if cor is not None:
                prop.SetColor(*cor)
            prop.SetOpacity(1.0)
        for peca in self._moldura:
            peca.GetProperty().SetOpacity(0.15)

    def _mostrar_info(self, ator) -> None:
        if self._legenda is None:
            return
        if ator is None:
            self._legenda.set_text("upper_left", _MENSAGEM_ARMADURA)
            return
        titulo, texto = self._info[ator]
        prefixo = "[fixado] " if self._fixado else ""
        self._legenda.set_text("upper_left", f"{prefixo}{titulo}\n{texto}")

    def _render(self) -> None:
        try:
            self.plotter.render()
        except Exception:                                   # noqa: BLE001
            pass

    def _ao_mover(self, _caller, _evento) -> None:
        if self._fixado:
            return
        ator = self._ator_sob_o_mouse()
        if ator is self._atual:
            return
        self._atual = ator
        if ator is not None:
            self._destacar(ator)
        else:
            self._limpar_destaque()
        self._mostrar_info(ator)
        self._render()

    def _ao_clicar(self, _caller, _evento) -> None:
        ator = self._ator_sob_o_mouse()
        if ator is None:
            if self._fixado:
                self._fixado = False
                self._atual = None
                self._limpar_destaque()
                self._mostrar_info(None)
                self._render()
            return
        if self._fixado and ator is self._atual:
            self._fixado = False
            self._limpar_destaque()
            self._mostrar_info(None)
        else:
            self._fixado = True
            self._atual = ator
            self._destacar(ator)
            self._mostrar_info(ator)
        self._render()

    def mostrar(self) -> None:
        self.plotter.show()


def abrir_vista_interativa_armadura(modelo: Modelo, armadura, cota: float,
                                    titulo: str = "Vista 3D da armadura"
                                    ) -> None:
    """Abre a janela nativa da armadura. Bloqueia até o usuário fechá-la."""
    VistaArmadura3D(modelo, armadura, cota, titulo).mostrar()
