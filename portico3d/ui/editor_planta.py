# -*- coding: utf-8 -*-
"""
editor_planta.py
O editor de lançamento: a planta de fôrma de cada pavimento, desenhada.

É a camada que os programas de edifício têm e que aqui faltava. O editor só
desenha e grava o ``Lancamento`` (``portico3d.lancamento``); toda regra
estrutural — onde a viga quebra, quem apoia em quem, o trecho rígido, o
contorno da laje — é do gerador, que o botão "Gerar modelo" chama. Assim o
mesmo arquivo serve ao editor, à linha de comando e às conferências.

O desenho é em metros, com Y para cima (a cena do Qt tem Y para baixo, e a
conversão é ``(x, -y)``).

Ferramentas: Selecionar, Pilar, Viga, Laje, Parede e Apagar.

* **Pilar** e **Laje**: um clique.
* **Viga** e **Parede**: clique a clique, como polilinha; duplo clique, Enter
  ou o botão direito termina, Esc cancela. Com Shift o trecho sai na
  horizontal ou na vertical.
* **Captura**: o clique vai para o ponto notável mais próximo dentro de
  ``TOLERANCIA_PX`` pixels — centro de pilar, vértice ou cruzamento de vigas,
  ponta de linha do DXF de fundo —, senão para o eixo da viga mais próxima,
  senão para a grade.

**Seleção**: clique seleciona; Ctrl+clique soma à seleção e Alt+clique tira,
sempre dentro de uma família (pilares, vigas, lajes ou paredes). O painel, o
giro e o Delete valem para todos os selecionados.

O painel da direita mostra as propriedades do elemento selecionado — ou, sem
seleção, as do próximo elemento da ferramenta —, num formulário montado a
partir dos campos do próprio lançamento.
"""

from __future__ import annotations

import math
from dataclasses import fields, replace
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QActionGroup, QBrush, QColor, QFont,
                           QKeySequence, QPainter, QPainterPath, QPen,
                           QPolygonF, QTransform)
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QGridLayout, QGroupBox, QSpinBox,
                               QDockWidget, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGraphicsScene, QGraphicsView,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from ..core.modelo import ErroDeModelo
from ..lancamento import (Lancamento, LajeLancada, ParedeLancada, Pavimento,
                          PilarLancado, Planta, VigaLancada, gerar)
from ..lancamento.grelha import (dividir_por_direcao, lancar_na_grelha,
                                 mudar_espaco, nova_grelha)
from ..lancamento.modelo import INSERCOES
from . import tema

TOLERANCIA_PX = 10.0
PASSO_DA_GRADE = 0.05           # m, passo padrão da captura na grade
#: Menor distância, px, entre duas linhas da grade desenhada: abaixo disso a
#: grade se adensa de 2 em 2, 2,5 em 2,5 — como a régua de um CAD.
GRADE_MINIMA_PX = 8.0
COR_GRADE_FORTE = QColor("#d5dbe3")
COR_EIXO = QColor("#9fb3c8")

FERRAMENTAS = ("Selecionar", "Pilar", "Viga", "Laje", "Parede", "Apagar")

#: Opções fechadas dos campos que têm lista.
OPCOES = {
    "insercao": INSERCOES,
    "tipo": ("macica", "trelicada"),
    "direcao": ("x", "y"),
    "sentido": ("", "+x", "-x", "+y", "-y"),
    "enchimento": ("EPS", "Cerâmico"),
    "trelica": ("TR 8644", "TR 8645", "TR 12645", "TR 12646", "TR 16745",
                "TR 16746", "TR 20745", "TR 20756", "TR 25856", "TR 25858",
                "TR 30856", "TR 30858"),
}

COR_PILAR = QColor(tema.AZUL)
COR_VIGA = QColor("#7d8b9c")
COR_PAREDE = QColor(tema.LARANJA)
COR_LAJE = QColor(tema.COR_LAJE)
COR_SELECAO = QColor("#e8a317")
COR_FANTASMA = QColor("#b9c1cc")
COR_DXF = QColor("#c9ced6")
COR_GRADE = QColor("#eceff3")
COR_ERRO = QColor(tema.VERMELHO)
COR_GRELHA = QColor("#7f97b2")

#: O nome de cada família de elemento, para títulos e mensagens.
_FAMILIAS = {PilarLancado: "Pilar", VigaLancada: "Viga", LajeLancada: "Laje",
             ParedeLancada: "Parede"}
_PLURAIS = {PilarLancado: "pilares", VigaLancada: "vigas", LajeLancada: "lajes",
            ParedeLancada: "paredes"}
#: Quanto o eixo da grelha passa do primeiro encontro, do último, e onde fica
#: a linha de cotas dos espaçamentos (a partir do último encontro), m.
INICIO_DA_GRELHA = 2.0
FIM_DA_GRELHA = 6.0
COTA_DA_GRELHA = 4.0


def _cena(x: float, y: float) -> QPointF:
    return QPointF(x, -y)


def _planta(p: QPointF) -> tuple[float, float]:
    return p.x(), -p.y()


def _ler_pontos(texto: str) -> list[tuple[float, float]]:
    """``"0, 0; 5, 0; 5, 4"`` -> lista de pontos."""
    pontos = []
    for par in texto.replace("\n", ";").split(";"):
        if not par.strip():
            continue
        x, y = (float(v.strip().replace(",", ".")) for v in
                par.replace(" ", ",", 1).split(",") if v.strip())
        pontos.append((x, y))
    return pontos


def _texto_pontos(pontos) -> str:
    return "; ".join(f"{x:g}, {y:g}" for x, y in pontos)


def _num(v: float, casas: int = 2) -> str:
    """Número com vírgula decimal, como se lê na obra."""
    return f"{v:.{casas}f}".replace(".", ",")


def _coordenada(x: float, y: float) -> str:
    return f"({_num(x)}; {_num(y)})"


def ler_coordenada(texto: str) -> tuple[bool, float, float]:
    """``"2,2; 2,8"`` -> ``(False, 2.2, 2.8)``; ``"@3; 0"`` -> relativo.

    O separador entre x e y é ``;`` (ou espaço), porque a vírgula é a
    decimal. Ponto também é aceito como decimal.
    """
    texto = texto.strip()
    relativo = texto.startswith("@")
    if relativo:
        texto = texto[1:]
    partes = [t for t in (texto.split(";") if ";" in texto
                          else texto.split()) if t.strip()]
    if len(partes) != 2:
        raise ValueError("use x; y — por exemplo 2,2; 2,8 — ou @dx; dy")
    x, y = (float(t.strip().replace(",", ".")) for t in partes)
    return relativo, x, y


# ---------------------------------------------------------------------------
# Vista da planta
# ---------------------------------------------------------------------------

class VistaPlanta(QGraphicsView):
    """A folha: zoom na roda, arrasto com o botão do meio, e os cliques e
    movimentos de mouse traduzidos para metros de planta."""

    movido = Signal(float, float, object)           # x, y, modificadores
    clicado = Signal(float, float, object, object)  # x, y, botão, modif.
    duplo = Signal(float, float)
    tecla = Signal(int)

    def __init__(self, cena: QGraphicsScene) -> None:
        super().__init__(cena)
        self.setRenderHint(QPainter.Antialiasing)
        self.setMouseTracking(True)
        # o zoom da roda prende o ponto sob o mouse por conta própria
        # (``zoom_em``); fora dele, escalar mantém o centro da vista
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QBrush(QColor(tema.BASE)))
        self._arrastando = None
        #: O passo da captura, m — a grade fina é desenhada nele.
        self.passo_grade = PASSO_DA_GRADE
        self.scale(60.0, 60.0)

    def drawBackground(self, pintor: QPainter, area: QRectF) -> None:  # noqa
        """A grade, desenhada no fundo da área visível inteira — e não só em
        volta do que já foi lançado. A fina segue o passo da captura e se
        adensa quando o zoom a deixaria ilegível; a forte marca o metro (ou
        os 10 m, de longe); os eixos x = 0 e y = 0 vão em azul."""
        pintor.fillRect(area, QColor(tema.BASE))
        escala = max(self.escala, 1e-9)
        fino = self.passo_grade
        fatores = (2.0, 2.5, 2.0)
        k = 0
        while fino * escala < GRADE_MINIMA_PX:
            fino *= fatores[k % 3]
            k += 1
        forte = 1.0
        while forte * escala < 4.0 * GRADE_MINIMA_PX:
            forte *= 10.0
        forte = max(forte, fino)

        def linhas(passo: float, cor: QColor) -> None:
            pintor.setPen(QPen(cor, 0))
            x = math.floor(area.left() / passo) * passo
            while x <= area.right():
                pintor.drawLine(QPointF(x, area.top()),
                                QPointF(x, area.bottom()))
                x += passo
            y = math.floor(area.top() / passo) * passo
            while y <= area.bottom():
                pintor.drawLine(QPointF(area.left(), y),
                                QPointF(area.right(), y))
                y += passo

        linhas(fino, COR_GRADE)
        linhas(forte, COR_GRADE_FORTE)
        pintor.setPen(QPen(COR_EIXO, 0))
        pintor.drawLine(QPointF(0.0, area.top()), QPointF(0.0, area.bottom()))
        pintor.drawLine(QPointF(area.left(), 0.0), QPointF(area.right(), 0.0))

    @property
    def escala(self) -> float:
        """Pixels por metro."""
        return float(self.transform().m11())

    def enquadrar(self, retangulo: QRectF) -> None:
        if retangulo.isEmpty():
            return
        margem = max(retangulo.width(), retangulo.height()) * 0.08 + 0.5
        self.fitInView(retangulo.adjusted(-margem, -margem, margem, margem),
                       Qt.KeepAspectRatio)

    def wheelEvent(self, evento) -> None:            # noqa: N802
        fator = 1.15 if evento.angleDelta().y() > 0 else 1.0 / 1.15
        self.zoom_em(evento.position().toPoint(), fator)

    def zoom_em(self, pixel, fator: float) -> None:
        """Aproxima ou afasta mantendo parado o ponto da planta sob o pixel
        ``pixel`` da vista — é onde o usuário está olhando.

        A âncora "sob o mouse" do próprio Qt não serve aqui: ela usa a última
        posição que o ``mouseMoveEvent`` da classe base registrou, e este o
        substitui sem chamá-la — a âncora ficava na origem, e todo zoom
        recentralizava a folha no (0; 0). Por isso o ponto é preso à mão:
        guarda-se onde ele está na planta, escala-se, e as barras de rolagem
        devolvem o ponto ao mesmo pixel.
        """
        alvo = self.mapToScene(pixel)
        ancora = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.scale(fator, fator)
        self.setTransformationAnchor(ancora)
        desvio = self.mapFromScene(alvo) - pixel
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() + desvio.x())
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() + desvio.y())
        self.viewport().update()

    def mousePressEvent(self, evento) -> None:       # noqa: N802
        if evento.button() == Qt.MiddleButton:
            self._arrastando = evento.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        x, y = _planta(self.mapToScene(evento.position().toPoint()))
        self.clicado.emit(x, y, evento.button(), evento.modifiers())

    def mouseMoveEvent(self, evento) -> None:        # noqa: N802
        if self._arrastando is not None:
            delta = evento.position() - self._arrastando
            self._arrastando = evento.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y()))
            return
        x, y = _planta(self.mapToScene(evento.position().toPoint()))
        self.movido.emit(x, y, evento.modifiers())

    def mouseReleaseEvent(self, evento) -> None:     # noqa: N802
        if evento.button() == Qt.MiddleButton:
            self._arrastando = None
            self.setCursor(Qt.CrossCursor)

    def mouseDoubleClickEvent(self, evento) -> None:  # noqa: N802
        x, y = _planta(self.mapToScene(evento.position().toPoint()))
        self.duplo.emit(x, y)

    def keyPressEvent(self, evento) -> None:         # noqa: N802
        self.tecla.emit(evento.key())


# ---------------------------------------------------------------------------
# Formulário de propriedades
# ---------------------------------------------------------------------------

class Formulario(QWidget):
    """Formulário montado dos campos de um dataclass do lançamento."""

    mudou = Signal()

    #: Campos que não se editam em lote: dar o mesmo nome ou a mesma posição
    #: a vários elementos não é transformação nenhuma, é empilhá-los.
    SO_UM = ("nome", "x", "y", "pontos")

    def __init__(self) -> None:
        super().__init__()
        self._layout = QFormLayout(self)
        self.objeto = None
        self.alvos: list = []
        self._campos: dict[str, QWidget] = {}

    def mostrar(self, objeto, titulo: str = "", so=None, alvos=None) -> None:
        """Mostra os campos de ``objeto`` (só os de ``so``, se dado).
        Campo que é lista ou dicionário só aparece se for ``pontos``.

        Com ``alvos`` (vários elementos da mesma família), o campo editado é
        gravado em **todos** eles; o formulário mostra os valores do
        primeiro, e o campo em que eles diferem leva "(vários)" no rótulo.
        Nome, posição e pontos ficam de fora (``SO_UM``)."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # tira já do painel: só o ``deleteLater`` deixava o campo
                # antigo visível até o próximo ciclo de eventos
                widget.setParent(None)
                widget.deleteLater()
        self._campos = {}
        self.objeto = objeto
        self.alvos = list(alvos) if alvos else ([objeto] if objeto is not None
                                                else [])
        em_lote = len(self.alvos) > 1
        if objeto is None:
            return
        if titulo:
            rotulo = QLabel(titulo)
            rotulo.setStyleSheet("font-weight: bold;")
            self._layout.addRow(rotulo)
        for f in fields(objeto):
            valor = getattr(objeto, f.name)
            if so is not None and f.name not in so:
                continue
            if em_lote and f.name in self.SO_UM:
                continue
            if f.name != "pontos" and (isinstance(valor, (list, dict, tuple))
                                       or hasattr(valor, "__dataclass_fields__")):
                continue
            if f.name in OPCOES:
                w = QComboBox()
                w.addItems(list(OPCOES[f.name]))
                w.setCurrentText(str(valor))
                w.currentTextChanged.connect(
                    lambda v, n=f.name: self._gravar(n, v))
            elif isinstance(valor, bool):
                w = QCheckBox()
                w.setChecked(valor)
                w.toggled.connect(lambda v, n=f.name: self._gravar(n, v))
            elif isinstance(valor, (int, float)):
                w = QDoubleSpinBox()
                w.setRange(-1.0e6, 1.0e6)
                w.setDecimals(3)
                w.setSingleStep(0.05)
                w.setValue(float(valor))
                w.valueChanged.connect(
                    lambda v, n=f.name: self._gravar(n, float(v)))
            elif f.name == "pontos":
                w = QLineEdit(_texto_pontos(valor))
                w.setToolTip("x, y; x, y; ... em metros")
                w.editingFinished.connect(
                    lambda n=f.name, c=w: self._gravar_pontos(n, c))
            else:
                w = QLineEdit(str(valor))
                w.editingFinished.connect(
                    lambda n=f.name, c=w: self._gravar(n, c.text().strip()))
            self._campos[f.name] = w
            rotulo = f.name.replace("_", " ")
            if em_lote and any(getattr(a, f.name) != valor
                               for a in self.alvos):
                rotulo += " (vários)"
                w.setToolTip("Os selecionados têm valores diferentes; "
                             "o que for digitado vale para todos")
            self._layout.addRow(rotulo, w)

    def _gravar(self, nome: str, valor) -> None:
        if self.objeto is None:
            return
        for alvo in self.alvos or [self.objeto]:
            setattr(alvo, nome, valor)
        self.mudou.emit()

    def _gravar_pontos(self, nome: str, campo: QLineEdit) -> None:
        try:
            pontos = _ler_pontos(campo.text())
        except ValueError:
            campo.setText(_texto_pontos(getattr(self.objeto, nome)))
            return
        if len(pontos) >= 2:
            self._gravar(nome, pontos)


# ---------------------------------------------------------------------------
# O editor
# ---------------------------------------------------------------------------

class EditorDeLancamento(QMainWindow):
    """A janela do lançamento por planta."""

    def __init__(self, lancamento: Lancamento | None = None,
                 ao_gerar=None, pai=None) -> None:
        super().__init__(pai)
        self.setWindowTitle("Lançamento por planta")
        self.setMinimumSize(800, 520)
        # No Fusion claro a caixa da opção sai com borda quase branca sobre o
        # painel branco: desmarcada, não se via que havia o que marcar
        self.setStyleSheet(
            f"QCheckBox::indicator {{ width: 13px; height: 13px; "
            f"border: 1px solid #8a96a6; border-radius: 2px; "
            f"background: {tema.BASE}; }}"
            f"QCheckBox::indicator:checked {{ background: {tema.AZUL_CLARO};"
            f" border-color: {tema.AZUL}; }}")
        self.lanc = lancamento or self._lancamento_novo()
        self.ao_gerar = ao_gerar
        self.caminho: Path | None = None
        self.ferramenta = "Selecionar"
        self.planta_atual = next(iter(self.lanc.plantas))
        self.em_curso: list[tuple[float, float]] = []
        #: A seleção: um ou vários elementos, sempre da mesma família.
        self.selecionados: list = []
        self.geracao = None
        self.fundo: list[QPainterPath] = []
        self.pontos_do_fundo: list[tuple[float, float]] = []
        self.padroes = {
            "Pilar": PilarLancado("P", 0.0, 0.0, 0.20, 0.40),
            "Viga": VigaLancada("V", [], 0.15, 0.40),
            "Laje": LajeLancada("L", 0.0, 0.0, 0.10),
            "Parede": ParedeLancada("Pa", [], 0.15, 13.0),
        }
        self._itens: dict[int, object] = {}
        self._cursor_ponto: tuple[float, float] | None = None
        self.passo = PASSO_DA_GRADE
        #: O último ponto colocado — a base da coordenada relativa (@dx; dy).
        self.ultimo_ponto: tuple[float, float] = (0.0, 0.0)

        self.cena = QGraphicsScene(self)
        # Área fixa e folgada: sem ela a cena cresce a cada item desenhado e
        # a vista se recentraliza sozinha — a folha "pula" debaixo do mouse
        # enquanto se desenha, e o clique cai noutro ponto.
        self.cena.setSceneRect(QRectF(-5000.0, -5000.0, 10000.0, 10000.0))
        self.vista = VistaPlanta(self.cena)
        self.vista.setCursor(Qt.CrossCursor)
        self.vista.movido.connect(self._ao_mover)
        self.vista.clicado.connect(self._ao_clicar)
        self.vista.duplo.connect(lambda x, y: self.terminar_polilinha())
        self.vista.tecla.connect(self._ao_teclar)
        self.setCentralWidget(self.vista)

        self._montar_barra()
        self._montar_painel_esquerdo()
        self._montar_painel_direito()
        self.statusBar().showMessage("Pronto")
        self._carregar_pavimentos()
        self.redesenhar(enquadrar=True)

    # -- montagem -----------------------------------------------------------

    @staticmethod
    def _lancamento_novo() -> Lancamento:
        lanc = Lancamento("edificio")
        lanc.plantas["Tipo"] = Planta("Tipo")
        lanc.pavimentos = [Pavimento("1PAV", 3.0, "Tipo")]
        return lanc

    def _montar_barra(self) -> None:
        barra = self.addToolBar("Lançamento")
        barra.setMovable(False)
        for texto, gatilho, atalho in (
                ("Abrir", self.abrir, "Ctrl+O"),
                ("Salvar", self.salvar, "Ctrl+S"),
                ("DXF de fundo", self.importar_dxf, "")):
            acao = QAction(texto, self)
            acao.triggered.connect(gatilho)
            if atalho:
                acao.setShortcut(QKeySequence(atalho))
            barra.addAction(acao)
        barra.addSeparator()
        grupo = QActionGroup(self)
        self.acoes_ferramenta: dict[str, QAction] = {}
        teclas = {"Selecionar": "S", "Pilar": "P", "Viga": "V", "Laje": "L",
                  "Parede": "W", "Apagar": "Del"}
        for nome in FERRAMENTAS:
            acao = QAction(nome, self, checkable=True)
            acao.setShortcut(QKeySequence(teclas[nome]))
            acao.setToolTip(f"{nome} ({teclas[nome]})")
            acao.triggered.connect(lambda _=False, n=nome:
                                   self.escolher_ferramenta(n))
            grupo.addAction(acao)
            barra.addAction(acao)
            self.acoes_ferramenta[nome] = acao
        self.acoes_ferramenta["Selecionar"].setChecked(True)
        barra.addSeparator()
        enquadrar = QAction("Enquadrar", self)
        enquadrar.triggered.connect(lambda: self.redesenhar(enquadrar=True))
        barra.addAction(enquadrar)
        gerar_acao = QAction("Gerar modelo", self)
        gerar_acao.setShortcut(QKeySequence("F9"))
        gerar_acao.triggered.connect(self.gerar_modelo)
        barra.addAction(gerar_acao)

        # -- segunda linha: a precisão do posicionamento ------------------
        self.addToolBarBreak()
        precisao = self.addToolBar("Precisão")
        precisao.setMovable(False)
        precisao.addWidget(QLabel(" Passo: "))
        self.campo_passo = QDoubleSpinBox()
        self.campo_passo.setRange(0.01, 10.0)
        self.campo_passo.setDecimals(2)
        self.campo_passo.setSingleStep(0.05)
        self.campo_passo.setSuffix(" m")
        self.campo_passo.setValue(PASSO_DA_GRADE)
        self.campo_passo.setToolTip(
            "Passo da captura na grade: com 0,10 m os pontos só caem de 10 "
            "em 10 cm")
        self.campo_passo.valueChanged.connect(self.definir_passo)
        precisao.addWidget(self.campo_passo)
        self.captura_objetos = QCheckBox("Captura em objetos")
        self.captura_objetos.setChecked(True)
        self.captura_objetos.setToolTip(
            "Ligada, o clique vai para centro de pilar, vértice e eixo de "
            "viga antes da grade. Desligada, só o passo vale")
        precisao.addWidget(self.captura_objetos)
        self.mostrar_coordenadas = QCheckBox("Coordenadas dos pilares")
        self.mostrar_coordenadas.setToolTip(
            "Escreve (x; y) ao lado de cada pilar")
        self.mostrar_coordenadas.toggled.connect(lambda _: self.redesenhar())
        precisao.addWidget(self.mostrar_coordenadas)
        precisao.addSeparator()
        girar = QAction("Girar 90° (R)", self)
        girar.setShortcut(QKeySequence("R"))
        girar.triggered.connect(self.girar)
        precisao.addAction(girar)
        precisao.addSeparator()
        precisao.addWidget(QLabel(" Coordenada: "))
        self.campo_coordenada = QLineEdit()
        self.campo_coordenada.setPlaceholderText("x; y   ou   @dx; dy")
        self.campo_coordenada.setToolTip(
            "Coloca o ponto exato da ferramenta: 2,2; 2,8 é absoluto, "
            "@3; 0 é relativo ao último ponto. Enter confirma")
        self.campo_coordenada.setFixedWidth(170)
        self.campo_coordenada.returnPressed.connect(
            lambda: self.entrar_coordenada(self.campo_coordenada.text()))
        precisao.addWidget(self.campo_coordenada)

    def _montar_painel_esquerdo(self) -> None:
        abas = QTabWidget()

        # -- pavimentos e plantas -------------------------------------------
        pav = QWidget()
        v = QVBoxLayout(pav)
        v.addWidget(QLabel("Pavimentos (de baixo para cima)"))
        self.tabela_pav = QTableWidget(0, 3)
        self.tabela_pav.setHorizontalHeaderLabels(["Nome", "Cota (m)",
                                                   "Planta"])
        self.tabela_pav.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.tabela_pav.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela_pav.itemChanged.connect(self._ao_editar_pavimento)
        self.tabela_pav.currentCellChanged.connect(
            lambda l, *_: self._ao_escolher_pavimento(l))
        self.tabela_pav.setMaximumHeight(150)
        v.addWidget(self.tabela_pav)
        linha = QHBoxLayout()
        for texto, gatilho in (("+ pavimento", self.acrescentar_pavimento),
                               ("− pavimento", self.remover_pavimento)):
            b = QPushButton(texto)
            b.clicked.connect(gatilho)
            linha.addWidget(b)
        v.addLayout(linha)
        v.addWidget(QLabel("Planta em edição"))
        self.escolha_planta = QComboBox()
        self.escolha_planta.currentTextChanged.connect(self._ao_trocar_planta)
        v.addWidget(self.escolha_planta)
        linha = QHBoxLayout()
        for texto, gatilho in (("Nova", self.nova_planta),
                               ("Duplicar", self.duplicar_planta),
                               ("Renomear", self.renomear_planta)):
            b = QPushButton(texto)
            b.clicked.connect(gatilho)
            linha.addWidget(b)
        v.addLayout(linha)
        v.addWidget(self._montar_grelha())
        v.addStretch(1)
        abas.addTab(pav, "Pavimentos")

        # -- dados do edifício ------------------------------------------------
        geral = QWidget()
        g = QVBoxLayout(geral)
        self.form_edificio = Formulario()
        self.form_vento = Formulario()
        self.form_edificio.mudou.connect(self._invalidar)
        self.form_vento.mudou.connect(self._invalidar)
        g.addWidget(self.form_edificio)
        g.addWidget(QLabel("Vento (NBR 6123) — v0 = 0 desliga"))
        g.addWidget(self.form_vento)
        g.addWidget(QLabel("Tipos de carga de laje (permanente, acidental)"))
        self.tabela_cargas = QTableWidget(0, 3)
        self.tabela_cargas.setHorizontalHeaderLabels(["Nome", "g (kN/m²)",
                                                      "q (kN/m²)"])
        self.tabela_cargas.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.tabela_cargas.itemChanged.connect(self._ao_editar_cargas)
        g.addWidget(self.tabela_cargas)
        b = QPushButton("+ tipo de carga")
        b.clicked.connect(self._acrescentar_tipo_de_carga)
        g.addWidget(b)
        g.addStretch(1)
        abas.addTab(geral, "Edifício")

        doca = QDockWidget("Edifício", self)
        # Largura fixa nos dois painéis: trocar de ferramenta troca o
        # formulário, e um painel que muda de largura empurra a folha — a
        # planta se mexeria debaixo do mouse.
        abas.setFixedWidth(290)
        doca.setWidget(abas)
        doca.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.LeftDockWidgetArea, doca)

    def _montar_grelha(self) -> QGroupBox:
        """A grelha de eixos: colunas com letras (verticais), linhas com
        números (horizontais), e o que lançar nos encontros."""
        caixa = QGroupBox("Grelha")
        grade = QGridLayout(caixa)
        grade.setContentsMargins(6, 6, 6, 6)
        grade.addWidget(QLabel("Quant."), 0, 1)
        grade.addWidget(QLabel("Espaço"), 0, 2)

        def inteiro(valor: int) -> QSpinBox:
            campo = QSpinBox()
            campo.setRange(1, 60)
            campo.setValue(valor)
            return campo

        def metros(valor: float, minimo: float = 0.10) -> QDoubleSpinBox:
            campo = QDoubleSpinBox()
            campo.setRange(minimo, 500.0)
            campo.setDecimals(2)
            campo.setSingleStep(0.5)
            campo.setSuffix(" m")
            campo.setValue(valor)
            return campo

        self.grelha_n_colunas, self.grelha_esp_colunas = inteiro(4), metros(5.0)
        self.grelha_n_linhas, self.grelha_esp_linhas = inteiro(3), metros(4.0)
        self.grelha_x0 = metros(0.0, -500.0)
        self.grelha_y0 = metros(0.0, -500.0)
        for k, (rotulo, a, b, dica) in enumerate((
                ("Colunas", self.grelha_n_colunas,
                 self.grelha_esp_colunas,
                 "Eixos verticais, com letras, da esquerda para a direita"),
                ("Linhas", self.grelha_n_linhas,
                 self.grelha_esp_linhas,
                 "Eixos horizontais, com números, de baixo para cima"),
                ("Origem x, y", self.grelha_x0, self.grelha_y0,
                 "Onde passam a coluna A e a linha 1")), start=1):
            texto = QLabel(rotulo)
            texto.setToolTip(dica)
            grade.addWidget(texto, k, 0)
            grade.addWidget(a, k, 1)
            grade.addWidget(b, k, 2)
        self.grelha_pilares = QCheckBox("Pilares")
        self.grelha_pilares.setToolTip(
            "Um pilar em cada encontro de eixos (onde já há um, fica o que "
            "está)")
        self.grelha_vigas = QCheckBox("Vigas")
        self.grelha_vigas.setToolTip(
            "Em cada eixo, uma viga do primeiro ao último pilar sobre ele")
        grade.addWidget(self.grelha_pilares, 4, 0)
        grade.addWidget(self.grelha_vigas, 4, 1, 1, 2)
        gerar_b = QPushButton("Gerar grelha")
        gerar_b.clicked.connect(lambda: self.gerar_grelha())
        apagar_b = QPushButton("Apagar")
        apagar_b.clicked.connect(self.apagar_grelha)
        grade.addWidget(gerar_b, 5, 0, 1, 2)
        grade.addWidget(apagar_b, 5, 2)
        dica = QLabel("Clique na cota de um espaço, na planta, para mudar "
                      "só aquele espaço.")
        dica.setWordWrap(True)
        dica.setStyleSheet("color: #5f6b7a;")
        grade.addWidget(dica, 6, 0, 1, 3)
        return caixa

    def gerar_grelha(self, n_colunas: int | None = None,
                     espaco_colunas: float | None = None,
                     n_linhas: int | None = None,
                     espaco_linhas: float | None = None,
                     pilares: bool | None = None,
                     vigas: bool | None = None) -> None:
        """Cria (ou refaz) a grelha com os valores do painel — ou com os
        dados aqui, que têm precedência — e lança na planta em edição os
        pilares e as vigas pedidos."""
        lanc = self.lanc
        lanc.grelha = nova_grelha(
            n_colunas or self.grelha_n_colunas.value(),
            espaco_colunas or self.grelha_esp_colunas.value(),
            n_linhas or self.grelha_n_linhas.value(),
            espaco_linhas or self.grelha_esp_linhas.value(),
            self.grelha_x0.value(), self.grelha_y0.value())
        pilares = self.grelha_pilares.isChecked() if pilares is None \
            else pilares
        vigas = self.grelha_vigas.isChecked() if vigas is None else vigas
        novos_p, novas_v = lancar_na_grelha(
            self.planta, lanc.grelha, pilares, vigas, self.padroes["Pilar"],
            self.padroes["Viga"])
        self._invalidar()
        self.redesenhar(enquadrar=True)
        g = lanc.grelha
        self.statusBar().showMessage(
            f"Grelha {len(g.xs)} colunas × {len(g.ys)} linhas: "
            f"{len(novos_p)} pilares e {len(novas_v)} vigas lançados")

    def apagar_grelha(self) -> None:
        """Tira os eixos; o que foi lançado neles fica."""
        self.lanc.grelha = None
        self.redesenhar()

    def editar_espaco(self, eixo: str, indice: int,
                      valor: float | None = None) -> bool:
        """Muda um espaçamento da grelha — só ele. Sem ``valor``, pergunta."""
        g = self.lanc.grelha
        if g is None:
            return False
        espacos = g.espacos_colunas if eixo == "coluna" else g.espacos_linhas
        if valor is None:
            if eixo == "coluna":
                nomes = [n for n, _ in g.colunas]
            else:
                nomes = [n for n, _ in g.linhas]
            valor, ok = QInputDialog.getDouble(
                self, "Espaçamento da grelha",
                f"{'Colunas' if eixo == 'coluna' else 'Linhas'} "
                f"{nomes[indice]}–{nomes[indice + 1]} (m):",
                espacos[indice], 0.01, 500.0, 2)
            if not ok:
                return False
        try:
            mudar_espaco(self.lanc, eixo, indice, valor)
        except (ValueError, IndexError) as erro:
            self.statusBar().showMessage(f"Grelha: {erro}")
            return False
        self._invalidar()
        self.redesenhar()
        quais = "colunas" if eixo == "coluna" else "linhas"
        self.statusBar().showMessage(
            f"Espaço {indice + 1} das {quais} = {_num(valor)} m; os eixos "
            "seguintes e o que está sobre eles andaram junto")
        return True

    def _cota_da_grelha_em(self, x: float, y: float):
        """A cota de espaçamento sob o ponto, como (eixo, índice), ou None.

        A cota é texto de tamanho fixo na tela, e por isso a área de clique
        é medida em pixels."""
        escala = max(self.vista.escala, 1e-9)
        for eixo, indice, (cx, cy) in getattr(self, "_cotas_da_grelha", []):
            if abs(x - cx) * escala <= 26 and abs(y - cy) * escala <= 11:
                return eixo, indice
        return None

    def _montar_painel_direito(self) -> None:
        painel = QWidget()
        v = QVBoxLayout(painel)
        self.form = Formulario()
        self.form.mudou.connect(self._ao_mudar_propriedade)
        v.addWidget(self.form, 1)
        v.addWidget(QLabel("Conferência do lançamento"))
        self.lista_conferencia = QListWidget()
        v.addWidget(self.lista_conferencia, 1)
        doca = QDockWidget("Propriedades", self)
        painel.setFixedWidth(290)
        doca.setWidget(painel)
        doca.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.RightDockWidgetArea, doca)

    # -- pavimentos, plantas e dados gerais ----------------------------------

    def _carregar_pavimentos(self) -> None:
        self.tabela_pav.blockSignals(True)
        self.tabela_pav.setRowCount(0)
        for p in sorted(self.lanc.pavimentos, key=lambda p: p.cota):
            linha = self.tabela_pav.rowCount()
            self.tabela_pav.insertRow(linha)
            self.tabela_pav.setItem(linha, 0, QTableWidgetItem(p.nome))
            self.tabela_pav.setItem(linha, 1, QTableWidgetItem(f"{p.cota:g}"))
            combo = QComboBox()
            combo.addItems(list(self.lanc.plantas))
            combo.setCurrentText(p.planta)
            combo.currentTextChanged.connect(
                lambda texto, nome=p.nome: self._mudar_planta_do_pavimento(
                    nome, texto))
            self.tabela_pav.setCellWidget(linha, 2, combo)
        self.tabela_pav.blockSignals(False)
        self.escolha_planta.blockSignals(True)
        self.escolha_planta.clear()
        self.escolha_planta.addItems(list(self.lanc.plantas))
        self.escolha_planta.setCurrentText(self.planta_atual)
        self.escolha_planta.blockSignals(False)
        self.form_edificio.mostrar(self.lanc, "", so=(
            "nome", "fck", "agregado", "peso_especifico", "cota_base",
            "trecho_rigido", "categoria_acidental"))
        self.form_vento.mostrar(self.lanc.vento)
        self.tabela_cargas.blockSignals(True)
        self.tabela_cargas.setRowCount(0)
        for nome, (g, q) in self.lanc.cargas_de_laje.items():
            linha = self.tabela_cargas.rowCount()
            self.tabela_cargas.insertRow(linha)
            for col, valor in enumerate((nome, f"{g:g}", f"{q:g}")):
                self.tabela_cargas.setItem(linha, col,
                                           QTableWidgetItem(valor))
        self.tabela_cargas.blockSignals(False)

    def _ao_editar_pavimento(self, item: QTableWidgetItem) -> None:
        pavs = sorted(self.lanc.pavimentos, key=lambda p: p.cota)
        linha = item.row()
        if linha >= len(pavs):
            return
        p = pavs[linha]
        if item.column() == 0:
            p.nome = item.text().strip() or p.nome
        elif item.column() == 1:
            try:
                p.cota = float(item.text().replace(",", "."))
            except ValueError:
                pass
        self._invalidar()

    def _ao_escolher_pavimento(self, linha: int) -> None:
        pavs = sorted(self.lanc.pavimentos, key=lambda p: p.cota)
        if 0 <= linha < len(pavs):
            self.escolha_planta.setCurrentText(pavs[linha].planta)

    def _mudar_planta_do_pavimento(self, nome: str, planta: str) -> None:
        for p in self.lanc.pavimentos:
            if p.nome == nome and planta in self.lanc.plantas:
                p.planta = planta
        self._invalidar()

    def acrescentar_pavimento(self) -> None:
        pavs = sorted(self.lanc.pavimentos, key=lambda p: p.cota)
        cota = pavs[-1].cota + 3.0 if pavs else self.lanc.cota_base + 3.0
        nome = f"{len(pavs) + 1}PAV"
        while any(p.nome == nome for p in pavs):
            nome += "'"
        self.lanc.pavimentos.append(Pavimento(nome, cota, self.planta_atual))
        self._carregar_pavimentos()
        self._invalidar()

    def remover_pavimento(self) -> None:
        pavs = sorted(self.lanc.pavimentos, key=lambda p: p.cota)
        linha = self.tabela_pav.currentRow()
        if len(pavs) > 1 and 0 <= linha < len(pavs):
            self.lanc.pavimentos.remove(pavs[linha])
            self._carregar_pavimentos()
            self._invalidar()

    def _nome_livre(self, base: str) -> str:
        nome, k = base, 1
        while nome in self.lanc.plantas:
            k += 1
            nome = f"{base} {k}"
        return nome

    def nova_planta(self) -> None:
        nome = self._nome_livre("Planta")
        self.lanc.plantas[nome] = Planta(nome)
        self.planta_atual = nome
        self._carregar_pavimentos()
        self.redesenhar()

    def duplicar_planta(self) -> None:
        from copy import deepcopy
        origem = self.lanc.plantas[self.planta_atual]
        nome = self._nome_livre(f"{origem.nome} (cópia)")
        copia = deepcopy(origem)
        copia.nome = nome
        self.lanc.plantas[nome] = copia
        self.planta_atual = nome
        self._carregar_pavimentos()
        self.redesenhar()

    def renomear_planta(self) -> None:
        novo, ok = QInputDialog.getText(self, "Renomear planta", "Nome:",
                                        text=self.planta_atual)
        novo = novo.strip()
        if not ok or not novo or novo in self.lanc.plantas:
            return
        planta = self.lanc.plantas.pop(self.planta_atual)
        planta.nome = novo
        self.lanc.plantas[novo] = planta
        for p in self.lanc.pavimentos:
            if p.planta == self.planta_atual:
                p.planta = novo
        self.planta_atual = novo
        self._carregar_pavimentos()

    def _ao_trocar_planta(self, nome: str) -> None:
        if nome in self.lanc.plantas:
            self.planta_atual = nome
            self.em_curso = []
            self.selecionar(None)
            self.redesenhar()

    def _ao_editar_cargas(self, item: QTableWidgetItem) -> None:
        cargas = {}
        for linha in range(self.tabela_cargas.rowCount()):
            celulas = [self.tabela_cargas.item(linha, c) for c in range(3)]
            if celulas[0] is None or not celulas[0].text().strip():
                continue
            try:
                g = float((celulas[1].text() if celulas[1] else "0")
                          .replace(",", "."))
                q = float((celulas[2].text() if celulas[2] else "0")
                          .replace(",", "."))
            except ValueError:
                continue
            cargas[celulas[0].text().strip()] = (g, q)
        self.lanc.cargas_de_laje = cargas
        self._invalidar()

    def _acrescentar_tipo_de_carga(self) -> None:
        linha = self.tabela_cargas.rowCount()
        self.tabela_cargas.insertRow(linha)
        self.tabela_cargas.setItem(linha, 0,
                                   QTableWidgetItem(f"tipo {linha + 1}"))
        self.tabela_cargas.setItem(linha, 1, QTableWidgetItem("1.0"))
        self.tabela_cargas.setItem(linha, 2, QTableWidgetItem("1.5"))

    # -- ferramentas -------------------------------------------------------------

    @property
    def planta(self) -> Planta:
        return self.lanc.plantas[self.planta_atual]

    def escolher_ferramenta(self, nome: str) -> None:
        self.ferramenta = nome
        self.em_curso = []
        if nome in self.acoes_ferramenta:
            self.acoes_ferramenta[nome].setChecked(True)
        if nome in self.padroes:
            self.selecionar(None)
            self.form.mostrar(self.padroes[nome], f"Próximo {nome.lower()}")
        self.redesenhar()
        dicas = {"Pilar": "clique no centro (ou canto) do pilar",
                 "Viga": "clique ponto a ponto; duplo clique, Enter ou botão "
                         "direito termina; Shift trava em X/Y",
                 "Laje": "clique dentro do contorno de vigas",
                 "Parede": "clique ponto a ponto sobre as vigas",
                 "Apagar": "clique no elemento",
                 "Selecionar": "clique num elemento para editar"}
        self.statusBar().showMessage(f"{nome}: {dicas[nome]}")

    def _proximo_nome(self, prefixo: str, itens) -> str:
        usados = {i.nome for i in itens}
        k = 1
        while f"{prefixo}{k}" in usados:
            k += 1
        return f"{prefixo}{k}"

    def adicionar_pilar(self, x: float, y: float) -> PilarLancado:
        padrao = self.padroes["Pilar"]
        p = replace(padrao, nome=self._proximo_nome("P", self.planta.pilares),
                    x=x, y=y)
        self.planta.pilares.append(p)
        self._invalidar()
        return p

    def adicionar_viga(self, pontos) -> list[VigaLancada]:
        """Uma viga por trecho reto: a polilinha que muda de direção vira
        várias vigas, cada uma com o seu nome (``dividir_por_direcao``)."""
        padrao = self.padroes["Viga"]
        novas = []
        for trecho in dividir_por_direcao(pontos):
            v = replace(padrao,
                        nome=self._proximo_nome("V", self.planta.vigas),
                        pontos=trecho)
            self.planta.vigas.append(v)
            novas.append(v)
        if novas:
            self._invalidar()
        return novas

    def _endireitar_viga(self, viga: VigaLancada) -> None:
        """A viga editada pelo formulário que ficou com mudança de direção é
        quebrada como a desenhada: o primeiro trecho fica com o nome dela, os
        outros ganham nomes novos logo depois dela na lista."""
        trechos = dividir_por_direcao(viga.pontos)
        if len(trechos) <= 1:
            return
        viga.pontos = trechos[0]
        k = next(i for i, v in enumerate(self.planta.vigas) if v is viga)
        for j, trecho in enumerate(trechos[1:], start=1):
            nova = replace(viga, nome=self._proximo_nome("V",
                                                         self.planta.vigas),
                           pontos=trecho)
            self.planta.vigas.insert(k + j, nova)
        self.statusBar().showMessage(
            f"{viga.nome} mudava de direção: virou {len(trechos)} vigas")
        # o formulário que mandou o sinal ainda está na pilha: refazê-lo
        # agora apagaria o campo que está emitindo
        QTimer.singleShot(0, lambda: self.selecionar(viga))

    def adicionar_laje(self, x: float, y: float) -> LajeLancada:
        padrao = self.padroes["Laje"]
        laje = replace(padrao, nome=self._proximo_nome("L", self.planta.lajes),
                       x=x, y=y)
        self.planta.lajes.append(laje)
        self._invalidar()
        return laje

    def adicionar_parede(self, pontos) -> ParedeLancada | None:
        pontos = [tuple(p) for p in pontos]
        if len(pontos) < 2:
            return None
        padrao = self.padroes["Parede"]
        pa = replace(padrao,
                     nome=self._proximo_nome("Pa", self.planta.paredes),
                     pontos=pontos)
        self.planta.paredes.append(pa)
        self._invalidar()
        return pa

    def apagar(self, objeto) -> None:
        for lista in (self.planta.pilares, self.planta.vigas,
                      self.planta.lajes, self.planta.paredes):
            if any(o is objeto for o in lista):
                lista[:] = [o for o in lista if o is not objeto]
        if self.esta_selecionado(objeto):
            self.selecionados = [o for o in self.selecionados
                                 if o is not objeto]
            self._mostrar_selecao()
        self._invalidar()

    # -- seleção ------------------------------------------------------------

    @property
    def selecionado(self):
        """O primeiro da seleção — o que o formulário mostra —, ou None."""
        return self.selecionados[0] if self.selecionados else None

    def esta_selecionado(self, objeto) -> bool:
        return any(o is objeto for o in self.selecionados)

    def selecionar(self, objeto) -> None:
        """Seleciona só ``objeto`` (None limpa a seleção)."""
        self.selecionados = [] if objeto is None else [objeto]
        self._mostrar_selecao()
        self.redesenhar()

    def acrescentar_a_selecao(self, objeto) -> bool:
        """Ctrl+clique: soma o elemento à seleção, se for da mesma família
        dos já selecionados — pilar com pilar, viga com viga."""
        if objeto is None or self.esta_selecionado(objeto):
            return False
        if self.selecionados and type(objeto) is not type(
                self.selecionados[0]):
            self.statusBar().showMessage(
                f"{objeto.nome} não entra: a seleção é de "
                f"{_PLURAIS[type(self.selecionados[0])]}, e só "
                "se seleciona junto elemento da mesma família")
            return False
        self.selecionados.append(objeto)
        self._mostrar_selecao()
        self.redesenhar()
        return True

    def retirar_da_selecao(self, objeto) -> bool:
        """Alt+clique: tira o elemento da seleção."""
        if objeto is None or not self.esta_selecionado(objeto):
            return False
        self.selecionados = [o for o in self.selecionados if o is not objeto]
        self._mostrar_selecao()
        self.redesenhar()
        return True

    def _mostrar_selecao(self) -> None:
        """O formulário da seleção: o elemento, ou os vários de uma vez —
        o que se digita vale para todos —, ou, sem seleção, o próximo
        elemento da ferramenta."""
        sel = self.selecionados
        if not sel:
            padrao = self.padroes.get(self.ferramenta)
            self.form.mostrar(padrao, f"Próximo {self.ferramenta.lower()}"
                              if padrao is not None else "")
            return
        tipo = _FAMILIAS.get(type(sel[0]), "")
        if len(sel) == 1:
            self.form.mostrar(sel[0], f"{tipo} {sel[0].nome}")
            self.statusBar().showMessage(
                f"{tipo} {sel[0].nome} — Ctrl+clique soma à seleção, "
                "Alt+clique tira")
        else:
            nomes = ", ".join(o.nome for o in sel[:6]) + (
                "…" if len(sel) > 6 else "")
            self.form.mostrar(sel[0], f"{len(sel)} {_PLURAIS[type(sel[0])]}: {nomes}",
                              alvos=sel)
            self.statusBar().showMessage(
                f"{len(sel)} {_PLURAIS[type(sel[0])]} na seleção — o que mudar no "
                "painel, R (girar) e Delete valem para todos")

    def terminar_polilinha(self) -> None:
        if self.ferramenta == "Viga" and len(self.em_curso) >= 2:
            self.adicionar_viga(self.em_curso)
        elif self.ferramenta == "Parede" and len(self.em_curso) >= 2:
            self.adicionar_parede(self.em_curso)
        self.em_curso = []
        self.redesenhar()

    # -- captura de pontos ---------------------------------------------------

    def pontos_notaveis(self) -> list[tuple[float, float]]:
        """Centros de pilar, vértices e cruzamentos de viga, pontos do DXF."""
        pts = [p.centro for p in self.planta.pilares]
        pts += [p.centro for p in self._pilares_de_baixo()]
        segs = []
        for v in self.planta.vigas:
            pts += list(v.pontos)
            segs += list(zip(v.pontos, v.pontos[1:]))
        for pa in self.planta.paredes:
            pts += list(pa.pontos)
        from ..lancamento.gerador import _intersecao
        for k, (a, b) in enumerate(segs):
            for c, d in segs[k + 1:]:
                r = _intersecao(a, b, c, d)
                if r is not None:
                    t = r[0]
                    pts.append((a[0] + t * (b[0] - a[0]),
                                a[1] + t * (b[1] - a[1])))
        if self.lanc.grelha is not None:
            pts += [(x, y) for _, x, y in self.lanc.grelha.encontros()]
        pts += self.pontos_do_fundo
        pts += self.em_curso
        return pts

    def capturar(self, x: float, y: float, travar: bool = False
                 ) -> tuple[float, float]:
        """O ponto que um clique em ``(x, y)`` de fato lança."""
        if travar and self.em_curso:
            ax, ay = self.em_curso[-1]
            if abs(x - ax) >= abs(y - ay):
                y = ay
            else:
                x = ax
        tol = TOLERANCIA_PX / max(self.vista.escala, 1e-9)
        melhor, dist = None, tol
        objetos = getattr(self, "captura_objetos", None)
        if objetos is not None and not objetos.isChecked():
            return self._na_grade(x, y, travar)
        for px, py in self.pontos_notaveis():
            d = math.hypot(px - x, py - y)
            if d < dist:
                melhor, dist = (px, py), d
        if melhor is not None:
            return melhor
        from ..lancamento.gerador import _projecao
        for v in self.planta.vigas:
            for a, b in zip(v.pontos, v.pontos[1:]):
                t, d = _projecao((x, y), a, b)
                if 0.0 <= t <= 1.0 and d < dist:
                    # ao longo do eixo o ponto anda no passo, contado do
                    # vértice: sem isso o clique em 4,5 caía em 4,503
                    L = math.dist(a, b)
                    if L > 0.0:
                        t = min(max(round(t * L / self.passo) * self.passo
                                    / L, 0.0), 1.0)
                    melhor = (round(a[0] + t * (b[0] - a[0]), 6),
                              round(a[1] + t * (b[1] - a[1]), 6))
                    dist = d
        # sobre um eixo da grelha, o ponto cai no eixo e anda no passo ao
        # longo dele
        g = self.lanc.grelha
        if g is not None:
            gx, gy = self._na_grade(x, y, travar)
            for _, xe in g.colunas:
                if abs(x - xe) < dist:
                    melhor, dist = (xe, gy), abs(x - xe)
            for _, ye in g.linhas:
                if abs(y - ye) < dist:
                    melhor, dist = (gx, ye), abs(y - ye)
        if melhor is not None:
            return melhor
        return self._na_grade(x, y, travar)

    def _na_grade(self, x: float, y: float, travar: bool
                  ) -> tuple[float, float]:
        passo = self.passo
        gx, gy = round(x / passo) * passo, round(y / passo) * passo
        if travar and self.em_curso:
            ax, ay = self.em_curso[-1]
            gx, gy = (gx, ay) if y == ay else (ax, gy)
        return round(gx, 6), round(gy, 6)

    def definir_passo(self, passo: float) -> None:
        """O passo da captura na grade, m: com 0,10 os pontos caem só de 10
        em 10 cm."""
        self.passo = max(float(passo), 1e-4)
        self.vista.passo_grade = self.passo
        if hasattr(self, "campo_passo") and \
                abs(self.campo_passo.value() - self.passo) > 1e-9:
            self.campo_passo.blockSignals(True)
            self.campo_passo.setValue(self.passo)
            self.campo_passo.blockSignals(False)
        self.vista.viewport().update()
        self.statusBar().showMessage(f"Passo da grade: {_num(self.passo)} m")

    def girar(self) -> None:
        """Gira 90° os pilares selecionados — cada um em torno do próprio
        ponto de inserção — ou o próximo pilar, que aparece já girado junto
        do cursor antes do clique."""
        pilares = [o for o in self.selecionados
                   if isinstance(o, PilarLancado)]
        alvo = pilares[0] if pilares else self.padroes["Pilar"]
        for p in pilares or [alvo]:
            p.angulo = (p.angulo + 90.0) % 360.0
        if pilares:
            self._invalidar()
            self._mostrar_selecao()
        elif self.ferramenta == "Pilar":
            self.form.mostrar(alvo, "Próximo pilar")
        self.redesenhar()
        self.statusBar().showMessage(
            f"Pilar a {alvo.angulo:g}°: {_num(alvo.b)} m em "
            f"{'X' if alvo.angulo % 180 == 0 else 'Y'}")

    def entrar_coordenada(self, texto: str) -> bool:
        """A coordenada digitada faz o que o clique faria, sem captura: o
        ponto é exatamente o digitado."""
        try:
            relativo, x, y = ler_coordenada(texto)
        except ValueError as erro:
            self.statusBar().showMessage(f"Coordenada: {erro}")
            return False
        if relativo:
            bx, by = self.em_curso[-1] if self.em_curso else self.ultimo_ponto
            x, y = bx + x, by + y
        self._executar_em(round(x, 6), round(y, 6), x, y)
        if hasattr(self, "campo_coordenada"):
            self.campo_coordenada.clear()
        return True

    def _pilares_de_baixo(self) -> list[PilarLancado]:
        """Os pilares da planta do pavimento logo abaixo de um pavimento que
        usa esta planta — o desenho os mostra em fantasma, para o pilar de
        cima nascer em cima deles."""
        pavs = sorted(self.lanc.pavimentos, key=lambda p: p.cota)
        for i, p in enumerate(pavs):
            if p.planta == self.planta_atual and i > 0:
                de_baixo = pavs[i - 1].planta
                if de_baixo != self.planta_atual:
                    return list(self.lanc.plantas[de_baixo].pilares)
                return []
        return []

    # -- eventos de mouse e teclado ------------------------------------------

    def _ao_mover(self, x: float, y: float, modificadores) -> None:
        travar = bool(modificadores & Qt.ShiftModifier)
        self._cursor_ponto = self.capturar(x, y, travar)
        cx, cy = self._cursor_ponto
        texto = f"x = {_num(cx, 3)} m   y = {_num(cy, 3)} m"
        if self.em_curso:
            ax, ay = self.em_curso[-1]
            texto += (f"   ·   trecho {_num(math.hypot(cx - ax, cy - ay))} m "
                      f"a {math.degrees(math.atan2(cy - ay, cx - ax)):.1f}°")
        if not self.em_curso and self._cota_da_grelha_em(x, y) is not None:
            self.vista.viewport().setCursor(Qt.PointingHandCursor)
            texto = "Clique para mudar este espaço da grelha (só ele)"
        else:
            self.vista.viewport().setCursor(Qt.CrossCursor)
        self.statusBar().showMessage(texto)
        self._desenhar_cursor()

    def _ao_clicar(self, x: float, y: float, botao, modificadores) -> None:
        if botao == Qt.RightButton:
            self.terminar_polilinha()
            return
        # a cota de um espaço da grelha se edita com um clique, com qualquer
        # ferramenta — menos no meio de uma polilinha, que segue
        cota = self._cota_da_grelha_em(x, y) if not self.em_curso else None
        if cota is not None and botao == Qt.LeftButton:
            self.editar_espaco(*cota)
            return
        # Ctrl+clique soma à seleção e Alt+clique tira, com qualquer
        # ferramenta (fora do meio de uma polilinha): a seleção é o que se
        # está montando, e trocar de ferramenta para isso seria um passo a
        # mais
        if botao == Qt.LeftButton and not self.em_curso and (
                modificadores & (Qt.ControlModifier | Qt.AltModifier)):
            objeto = self.objeto_em(x, y)
            if modificadores & Qt.AltModifier:
                self.retirar_da_selecao(objeto)
            else:
                self.acrescentar_a_selecao(objeto)
            return
        travar = bool(modificadores & Qt.ShiftModifier)
        px, py = self.capturar(x, y, travar)
        self._executar_em(px, py, x, y)

    def _executar_em(self, px: float, py: float, x: float, y: float) -> None:
        """O que a ferramenta faz no ponto ``(px, py)`` já capturado (``x, y``
        é o ponto cru, para achar o elemento sob o mouse)."""
        f = self.ferramenta
        if f in ("Pilar", "Laje", "Viga", "Parede"):
            self.ultimo_ponto = (px, py)
        if f == "Pilar":
            self.adicionar_pilar(px, py)
        elif f == "Laje":
            self.adicionar_laje(px, py)
        elif f in ("Viga", "Parede"):
            if not self.em_curso or math.dist(self.em_curso[-1],
                                              (px, py)) > 1e-6:
                self.em_curso.append((px, py))
        elif f in ("Selecionar", "Apagar"):
            objeto = self.objeto_em(x, y)
            if f == "Apagar":
                if objeto is not None:
                    self.apagar(objeto)
            else:
                self.selecionar(objeto)
        self.redesenhar()

    def _ao_teclar(self, tecla: int) -> None:
        if tecla in (Qt.Key_Return, Qt.Key_Enter):
            self.terminar_polilinha()
        elif tecla == Qt.Key_Escape:
            self.em_curso = []
            self.selecionar(None)
        elif tecla == Qt.Key_Delete and self.selecionados:
            for objeto in list(self.selecionados):
                self.apagar(objeto)
            self.redesenhar()
        elif tecla == Qt.Key_R:
            self.girar()

    def objeto_em(self, x: float, y: float):
        """O elemento sob o ponto: pilar, depois viga, parede e laje."""
        tol = TOLERANCIA_PX / max(self.vista.escala, 1e-9)
        for p in self.planta.pilares:
            cx, cy = p.centro
            if math.hypot(cx - x, cy - y) <= max(p.b, p.h) / 2.0 + tol:
                return p
        from ..lancamento.gerador import _projecao
        for lista in (self.planta.vigas, self.planta.paredes):
            for o in lista:
                for a, b in zip(o.pontos, o.pontos[1:]):
                    t, d = _projecao((x, y), a, b)
                    if -0.01 <= t <= 1.01 and d <= max(o.b if hasattr(
                            o, "b") else o.espessura, 0.0) / 2.0 + tol:
                        return o
        for laje in self.planta.lajes:
            if math.hypot(laje.x - x, laje.y - y) <= 3.0 * tol:
                return laje
        return None

    def _ao_mudar_propriedade(self) -> None:
        if len(self.selecionados) == 1 and isinstance(self.selecionado,
                                                      VigaLancada):
            self._endireitar_viga(self.selecionado)
        self._invalidar()
        self.redesenhar()

    def _invalidar(self) -> None:
        """O lançamento mudou: a última geração não vale mais."""
        self.geracao = None

    # -- desenho -------------------------------------------------------------

    def redesenhar(self, enquadrar: bool = False) -> None:
        self.cena.clear()
        self._itens = {}

        for caminho in self.fundo:
            self.cena.addPath(caminho, QPen(COR_DXF, 0))

        # painéis de laje detectados na última geração
        if self.geracao is not None and self.geracao.modelo is not None:
            m = self.geracao.modelo
            pav = self._um_pavimento_da_planta()
            for laje in self.planta.lajes:
                chave = ("laje", laje.nome, pav.nome if pav else "")
                for nome in self.geracao.mapa.get(chave, []):
                    from ..core.lajes import retangulo
                    x0, y0, x1, y1, _ = retangulo(m, m.lajes[nome])
                    r = QRectF(_cena(x0, y1), _cena(x1, y0))
                    cor = QColor(COR_LAJE)
                    cor.setAlpha(90)
                    self.cena.addRect(r, QPen(Qt.NoPen), QBrush(cor))

        self._desenhar_grelha()

        for p in self._pilares_de_baixo():
            self.cena.addPolygon(self._poligono_do_pilar(p),
                                 QPen(COR_FANTASMA, 0, Qt.DashLine))

        for v in self.planta.vigas:
            self._desenhar_polilinha(v, v.pontos, v.b, COR_VIGA)
        # a parede vai por cima da viga que a recebe, tracejada e mais fina,
        # e com o nome do outro lado do eixo
        for pa in self.planta.paredes:
            self._desenhar_polilinha(pa, pa.pontos, pa.espessura * 0.5,
                                     COR_PAREDE, Qt.DashLine, lado=-1.0)
        for p in self.planta.pilares:
            cor = COR_SELECAO if self.esta_selecionado(p) else COR_PILAR
            item = self.cena.addPolygon(self._poligono_do_pilar(p),
                                        QPen(cor.darker(130), 0),
                                        QBrush(cor))
            self._itens[id(item)] = p
            # o nome fica no canto de cima, à direita, fora do pilar
            folga = max(p.b, p.h) / 2.0 + 0.04
            nome = p.nome
            if self.esta_selecionado(p) or (
                    getattr(self, "mostrar_coordenadas", None) is not None
                    and self.mostrar_coordenadas.isChecked()):
                nome += " " + _coordenada(*p.centro)
            self._rotulo(nome, (p.centro[0] + folga, p.centro[1] + folga),
                         cor)
        for laje in self.planta.lajes:
            cor = COR_SELECAO if self.esta_selecionado(laje) else \
                QColor(tema.AZUL_CLARO)
            caneta = QPen(cor, 0)
            self.cena.addLine(laje.x - 0.15, -laje.y, laje.x + 0.15, -laje.y,
                              caneta)
            self.cena.addLine(laje.x, -laje.y - 0.15, laje.x, -laje.y + 0.15,
                              caneta)
            rotulo = laje.nome + (" (treliçada)" if laje.tipo == "trelicada"
                                  else f" h={laje.espessura * 100:g}")
            if laje.balanco > 0.0:
                rotulo += f" balanço {_num(laje.balanco)} m {laje.sentido}"
            self._rotulo(rotulo, (laje.x + 0.1, laje.y + 0.1), cor)

        # coordenadas dos vértices do elemento selecionado
        for sel in self.selecionados:
            if isinstance(sel, (VigaLancada, ParedeLancada)):
                for ponto in sel.pontos:
                    self._rotulo(_coordenada(*ponto), ponto, COR_SELECAO)
            elif isinstance(sel, LajeLancada):
                self._rotulo(_coordenada(sel.x, sel.y), (sel.x + 0.1,
                                                         sel.y - 0.25),
                             COR_SELECAO)

        self._dinamicos = []
        self._desenhar_cursor()
        if enquadrar:
            self.vista.enquadrar(self._caixa())

    def _desenhar_grelha(self) -> None:
        """Os eixos, com a bolha do nome nas duas pontas, e a linha de cotas
        dos espaçamentos a ``COTA_DA_GRELHA`` m do último encontro.

        Cada cota guarda o espaço que mede (``_cotas_da_grelha``): é por ela
        que o clique sabe qual espaço editar."""
        self._cotas_da_grelha = []
        g = self.lanc.grelha
        if g is None:
            return
        xs, ys = g.xs, g.ys
        caneta = QPen(COR_GRELHA, 0, Qt.DashDotLine)
        y_ini, y_fim = ys[0] - INICIO_DA_GRELHA, ys[-1] + FIM_DA_GRELHA
        x_ini, x_fim = xs[0] - INICIO_DA_GRELHA, xs[-1] + FIM_DA_GRELHA
        for nome, x in g.colunas:
            self.cena.addLine(x, -y_ini, x, -y_fim, caneta)
            for y in (y_ini, y_fim):
                self._marca(nome, (x, y), bolha=True)
        for nome, y in g.linhas:
            self.cena.addLine(x_ini, -y, x_fim, -y, caneta)
            for x in (x_ini, x_fim):
                self._marca(nome, (x, y), bolha=True)

        # as linhas de cota, a 4 m do último encontro, com um tique em cada
        # eixo e o valor de cada espaço no meio dele — clicável
        cota = QPen(COR_GRELHA, 0)
        yc, xc = ys[-1] + COTA_DA_GRELHA, xs[-1] + COTA_DA_GRELHA
        tique = 0.15
        if len(xs) > 1:
            self.cena.addLine(xs[0], -yc, xs[-1], -yc, cota)
            for x in xs:
                self.cena.addLine(x - tique, -yc - tique, x + tique,
                                  -yc + tique, cota)
        if len(ys) > 1:
            self.cena.addLine(xc, -ys[0], xc, -ys[-1], cota)
            for y in ys:
                self.cena.addLine(xc - tique, -y - tique, xc + tique,
                                  -y + tique, cota)
        for k, e in enumerate(g.espacos_colunas):
            ponto = ((xs[k] + xs[k + 1]) / 2.0, yc)
            self._marca(_num(e), ponto)
            self._cotas_da_grelha.append(("coluna", k, ponto))
        for k, e in enumerate(g.espacos_linhas):
            ponto = (xc, (ys[k] + ys[k + 1]) / 2.0)
            self._marca(_num(e), ponto)
            self._cotas_da_grelha.append(("linha", k, ponto))

    def _marca(self, texto: str, ponto, bolha: bool = False):
        """Texto de tamanho fixo na tela, centrado no ponto: numa bolha (o
        nome do eixo) ou numa caixa (a cota, que se clica)."""
        caminho = QPainterPath()
        fonte = QFont("Segoe UI", 8)
        fonte.setBold(bolha)
        caminho.addText(0, 0, fonte, texto)
        r = caminho.boundingRect()
        caminho.translate(-r.center())
        fundo = QPainterPath()
        if bolha:
            raio = max(r.width(), r.height()) / 2.0 + 5.0
            fundo.addEllipse(QPointF(0, 0), raio, raio)
        else:
            fundo.addRoundedRect(QRectF(-r.width() / 2 - 4,
                                        -r.height() / 2 - 2,
                                        r.width() + 8, r.height() + 4), 3, 3)
        grupo = self.cena.createItemGroup([])
        borda = QPen(COR_GRELHA if bolha else QColor(tema.AZUL_CLARO), 0)
        grupo.addToGroup(self.cena.addPath(fundo, borda,
                                           QBrush(QColor(255, 255, 255))))
        grupo.addToGroup(self.cena.addPath(
            caminho, QPen(Qt.NoPen),
            QBrush(QColor(tema.AZUL if not bolha else tema.TEXTO))))
        grupo.setFlag(grupo.GraphicsItemFlag.ItemIgnoresTransformations, True)
        grupo.setPos(_cena(*ponto))
        grupo.setZValue(5)
        return grupo

    def _desenhar_cursor(self) -> None:
        """Só o que muda com o mouse — a linha elástica da polilinha em curso
        e a marca do ponto capturado. O resto da cena (e o DXF de fundo, que
        pode ter milhares de linhas) não é refeito a cada movimento."""
        for item in getattr(self, "_dinamicos", []):
            self.cena.removeItem(item)
        self._dinamicos = []
        f = self.ferramenta
        transparente = QColor(COR_SELECAO)
        transparente.setAlpha(110)
        if self.em_curso:
            pontos = list(self.em_curso)
            if self._cursor_ponto is not None:
                pontos.append(self._cursor_ponto)
            caminho = QPainterPath(_cena(*pontos[0]))
            for p in pontos[1:]:
                caminho.lineTo(_cena(*p))
            # a largura de verdade do elemento, transparente, e o eixo
            largura = (self.padroes["Viga"].b if f == "Viga"
                       else self.padroes["Parede"].espessura)
            self._dinamicos.append(self.cena.addPath(
                caminho, QPen(transparente, largura, Qt.SolidLine,
                              Qt.FlatCap, Qt.MiterJoin)))
            self._dinamicos.append(self.cena.addPath(
                caminho, QPen(COR_SELECAO, 0, Qt.DashLine)))
            if len(pontos) >= 2:
                a, b = pontos[-2], pontos[-1]
                self._dinamicos.append(self._etiqueta(
                    f"{_num(math.dist(a, b))} m",
                    ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0), (8, -18)))
        if self._cursor_ponto is None:
            return
        cx, cy = self._cursor_ponto
        if f == "Pilar":
            # o pilar que vai sair do clique, com a seção, o giro e o ponto
            # de inserção atuais — R gira antes de colocar
            previa = replace(self.padroes["Pilar"], x=cx, y=cy)
            self._dinamicos.append(self.cena.addPolygon(
                self._poligono_do_pilar(previa), QPen(COR_SELECAO, 0),
                QBrush(transparente)))
            self._dinamicos.append(self._etiqueta(
                f"{previa.b * 100:g}×{previa.h * 100:g} · "
                f"{previa.angulo:g}°", (cx, cy), (12, 14)))
        if f != "Selecionar":
            r = 6.0 / max(self.vista.escala, 1e-9)
            self._dinamicos.append(self.cena.addEllipse(
                cx - r, -cy - r, 2 * r, 2 * r, QPen(COR_SELECAO, 0)))
        self._dinamicos.append(self._etiqueta(_coordenada(cx, cy), (cx, cy),
                                              (12, -22)))

    def _etiqueta(self, texto: str, ponto, deslocamento_px):
        """Texto em tamanho fixo de tela, deslocado em pixels do ponto, com
        fundo branco — para ler por cima do desenho."""
        caminho = QPainterPath()
        fonte = QFont("Segoe UI", 8)
        caminho.addText(0, 0, fonte, texto)
        caixa = caminho.boundingRect().adjusted(-3, -2, 3, 2)
        fundo = QPainterPath()
        fundo.addRoundedRect(caixa, 3, 3)
        grupo = self.cena.createItemGroup([])
        fundo_item = self.cena.addPath(fundo, QPen(COR_SELECAO, 0),
                                       QBrush(QColor(255, 255, 255, 225)))
        texto_item = self.cena.addPath(caminho, QPen(Qt.NoPen),
                                       QBrush(QColor(tema.TEXTO)))
        grupo.addToGroup(fundo_item)
        grupo.addToGroup(texto_item)
        grupo.setFlag(grupo.GraphicsItemFlag.ItemIgnoresTransformations,
                      True)
        grupo.setPos(_cena(*ponto))
        grupo.setTransform(QTransform.fromTranslate(*deslocamento_px))
        grupo.setZValue(10)
        return grupo

    def _caixa(self) -> QRectF:
        xs, ys = [], []
        for p in self.planta.pilares + self._pilares_de_baixo():
            xs.append(p.centro[0])
            ys.append(p.centro[1])
        for o in self.planta.vigas + self.planta.paredes:
            for x, y in o.pontos:
                xs.append(x)
                ys.append(y)
        for x, y in self.pontos_do_fundo:
            xs.append(x)
            ys.append(y)
        g = self.lanc.grelha
        if g is not None:
            xs += [g.xs[0] - INICIO_DA_GRELHA, g.xs[-1] + FIM_DA_GRELHA]
            ys += [g.ys[0] - INICIO_DA_GRELHA, g.ys[-1] + FIM_DA_GRELHA]
        if not xs:
            return QRectF(-1.0, -11.0, 12.0, 12.0)
        return QRectF(QPointF(min(xs) - 1, -max(ys) - 1),
                      QPointF(max(xs) + 1, -min(ys) + 1))

    def _poligono_do_pilar(self, p: PilarLancado) -> QPolygonF:
        cx, cy = p.centro
        a = math.radians(p.angulo)
        c, s = math.cos(a), math.sin(a)
        cantos = []
        for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            lx, ly = dx * p.b / 2.0, dy * p.h / 2.0
            cantos.append(_cena(cx + c * lx - s * ly, cy + s * lx + c * ly))
        return QPolygonF(cantos)

    def _desenhar_polilinha(self, objeto, pontos, largura: float,
                            cor: QColor, estilo=Qt.SolidLine,
                            lado: float = 1.0) -> None:
        if len(pontos) < 2:
            return
        cor = COR_SELECAO if self.esta_selecionado(objeto) else cor
        caminho = QPainterPath(_cena(*pontos[0]))
        for p in pontos[1:]:
            caminho.lineTo(_cena(*p))
        caneta = QPen(cor, max(largura, 0.02), estilo, Qt.FlatCap,
                      Qt.MiterJoin)
        item = self.cena.addPath(caminho, caneta)
        self._itens[id(item)] = objeto
        # o nome no meio do trecho do meio, afastado meia largura do eixo
        meio = len(pontos) // 2
        a, b = pontos[meio - 1], pontos[meio]
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1.0
        folga = lado * (max(largura, 0.15) / 2.0 + 0.08)
        self._rotulo(objeto.nome, ((a[0] + b[0]) / 2 - dy / n * folga,
                                   (a[1] + b[1]) / 2 + dx / n * folga), cor)

    def _rotulo(self, texto: str, ponto, cor: QColor) -> None:
        item = self.cena.addSimpleText(texto, QFont("Segoe UI", 8))
        item.setBrush(QBrush(cor.darker(140)))
        item.setFlag(item.GraphicsItemFlag.ItemIgnoresTransformations, True)
        item.setPos(_cena(*ponto))

    def _um_pavimento_da_planta(self) -> Pavimento | None:
        for p in sorted(self.lanc.pavimentos, key=lambda p: p.cota):
            if p.planta == self.planta_atual:
                return p
        return None

    # -- DXF de fundo -----------------------------------------------------------

    def importar_dxf(self, caminho: str | None = None,
                     unidade: str | None = None) -> int:
        """Lê linhas, polilinhas, arcos e círculos de um DXF e os põe de
        fundo, em cinza. As pontas viram pontos de captura."""
        import ezdxf

        if caminho is None:
            caminho, _ = QFileDialog.getOpenFileName(
                self, "DXF da arquitetura", "", "Desenho (*.dxf)")
            if not caminho:
                return 0
        try:
            doc = ezdxf.readfile(caminho)
        except (OSError, ezdxf.DXFError) as erro:
            QMessageBox.warning(self, "DXF", str(erro))
            return 0
        por_codigo = {4: "mm", 5: "cm", 6: "m"}
        if unidade is None:
            sugerida = por_codigo.get(doc.header.get("$INSUNITS", 0), "m")
            unidade, ok = QInputDialog.getItem(
                self, "Unidade do DXF", "O desenho está em:",
                ["m", "cm", "mm"], ["m", "cm", "mm"].index(sugerida), False)
            if not ok:
                return 0
        fator = {"m": 1.0, "cm": 0.01, "mm": 0.001}[unidade]

        entidades = []
        for e in doc.modelspace():
            if e.dxftype() == "INSERT":
                try:
                    entidades.extend(e.virtual_entities())
                except Exception:              # noqa: BLE001
                    continue
            else:
                entidades.append(e)
        caminhos, pontos = [], []

        def segmento(pts):
            if len(pts) < 2:
                return
            c = QPainterPath(_cena(pts[0][0] * fator, pts[0][1] * fator))
            for x, y in pts[1:]:
                c.lineTo(_cena(x * fator, y * fator))
            caminhos.append(c)
            pontos.extend((x * fator, y * fator) for x, y in (pts[0],
                                                                pts[-1]))

        for e in entidades:
            tipo = e.dxftype()
            try:
                if tipo == "LINE":
                    segmento([(e.dxf.start.x, e.dxf.start.y),
                              (e.dxf.end.x, e.dxf.end.y)])
                elif tipo == "LWPOLYLINE":
                    pts = [(p[0], p[1]) for p in e.get_points()]
                    if e.closed and pts:
                        pts.append(pts[0])
                    segmento(pts)
                elif tipo == "POLYLINE":
                    pts = [(v.dxf.location.x, v.dxf.location.y)
                           for v in e.vertices]
                    if e.is_closed and pts:
                        pts.append(pts[0])
                    segmento(pts)
                elif tipo in ("ARC", "CIRCLE"):
                    c, r = e.dxf.center, e.dxf.radius
                    a0 = math.radians(e.dxf.start_angle) if tipo == "ARC" \
                        else 0.0
                    a1 = math.radians(e.dxf.end_angle) if tipo == "ARC" \
                        else 2 * math.pi
                    if a1 <= a0:
                        a1 += 2 * math.pi
                    n = max(8, int((a1 - a0) / (math.pi / 16)))
                    segmento([(c.x + r * math.cos(a0 + (a1 - a0) * k / n),
                               c.y + r * math.sin(a0 + (a1 - a0) * k / n))
                              for k in range(n + 1)])
            except AttributeError:
                continue
        self.fundo = caminhos
        self.pontos_do_fundo = pontos
        self.redesenhar(enquadrar=True)
        self.statusBar().showMessage(
            f"DXF de fundo: {len(caminhos)} entidades, em {unidade}")
        return len(caminhos)

    # -- arquivo -------------------------------------------------------------

    def abrir(self, caminho: str | None = None) -> bool:
        from ..lancamento.arquivo import ler
        if caminho is None:
            caminho, _ = QFileDialog.getOpenFileName(
                self, "Abrir lançamento", "", "Lançamento (*.json)")
            if not caminho:
                return False
        try:
            self.lanc = ler(caminho)
        except (ErroDeModelo, OSError, ValueError, KeyError) as erro:
            QMessageBox.warning(self, "Lançamento", str(erro))
            return False
        self.caminho = Path(caminho)
        if not self.lanc.plantas:
            self.lanc.plantas["Tipo"] = Planta("Tipo")
        self.planta_atual = next(iter(self.lanc.plantas))
        self.selecionar(None)
        self._invalidar()
        self._carregar_pavimentos()
        self.redesenhar(enquadrar=True)
        return True

    def salvar(self, caminho: str | None = None) -> bool:
        from ..lancamento.arquivo import gravar
        if caminho is None:
            caminho, _ = QFileDialog.getSaveFileName(
                self, "Salvar lançamento",
                str(self.caminho or f"{self.lanc.nome}-lancamento.json"),
                "Lançamento (*.json)")
            if not caminho:
                return False
        self.caminho = gravar(self.lanc, caminho)
        self.statusBar().showMessage(f"Lançamento salvo em {self.caminho}")
        return True

    # -- gerar -----------------------------------------------------------------

    def gerar_modelo(self):
        """Roda o gerador, mostra a conferência e entrega o modelo à janela
        principal quando ele fecha."""
        self.terminar_polilinha()
        self.geracao = gerar(self.lanc)
        self.lista_conferencia.clear()
        for texto in self.geracao.erros:
            item = QListWidgetItem(f"ERRO: {texto}")
            item.setForeground(QBrush(COR_ERRO))
            self.lista_conferencia.addItem(item)
        for texto in self.geracao.avisos:
            item = QListWidgetItem(f"aviso: {texto}")
            item.setForeground(QBrush(QColor(tema.LARANJA)))
            self.lista_conferencia.addItem(item)
        if self.geracao.ok:
            m = self.geracao.modelo
            self.lista_conferencia.insertItem(0, QListWidgetItem(
                f"Modelo gerado: {len(m.nos)} nós, {len(m.barras)} barras, "
                f"{len(m.lajes)} lajes"))
            if self.ao_gerar is not None:
                self.ao_gerar(self.geracao, self.lanc)
        self.redesenhar()
        return self.geracao
