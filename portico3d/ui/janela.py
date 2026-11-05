# -*- coding: utf-8 -*-
"""
janela.py
Janela principal: tabelas à esquerda, desenho à direita, relatório embaixo.

O fluxo é o de sempre nesta pasta de programas — montar, analisar, ler o
resultado —, e a janela só existe para encurtar esse caminho. Toda a conta
continua no ``core``: aqui não há uma linha de mecânica, e é de propósito. O
que a interface faz é ler tabelas, chamar o solver e desenhar o que voltou.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFileDialog, QInputDialog,
                               QLabel,
                               QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter,
                               QToolButton, QVBoxLayout, QWidget)

from ..arquivo import gravar, ler
from ..core.combinacoes import caso_efetivo, resolver_combinacoes
from ..core.envoltoria import envoltoria
from ..core.estabilidade import gama_z
from dataclasses import replace

from ..core.modelo import ErroDeModelo, Modelo
from ..core.montagem import resolver
from ..core.nbr6118 import (acoes_do_modelo, combinacoes_elu, combinacoes_els,
                            validar_acoes)
from ..core.resultados import Resultado
from ..core.dinamica import analisar_modal
from ..core.segunda_ordem import flambagem, resolver_p_delta
from .assistente import AssistenteDePortico
from .conversao import modelo_para_registros, registros_para_modelo
from .tabelas import PainelDeDados
from .vista3d import (REPRESENTACOES_DE_DIAGRAMA, VISTAS_DE_ESFORCO, Vista3D,
                      abrir_vista_interativa_armadura)

VISTAS = ["Modelo", "3D", "Laje", "Armadura", "Cargas", "Deformada",
          *VISTAS_DE_ESFORCO, "Modo de flambagem", "Modo de vibração"]

#: As análises que o botão "Análise" roda de uma vez. A lista ao lado da vista
#: escolhe qual delas está na tela; "Modelo" é o desenho do que foi digitado,
#: antes (ou sem) qualquer análise.
ANALISES = ["Modelo", "Cargas", "1ª ordem", "2ª ordem", "Combinações",
            "Estabilidade", "Flambagem", "Modal"]

#: Nem toda vista cabe em toda análise: o modo de vibração não tem armadura, e
#: o diagrama de momento não diz nada de uma carga crítica. Cada análise
#: oferece só as vistas que respondem alguma coisa sobre ela. A armadura vai
#: onde há dimensionamento por trás — o desenho do modelo e a envoltória das
#: combinações.
_ESFORCOS = list(VISTAS_DE_ESFORCO)
VISTAS_POR_ANALISE = {
    "Modelo": ["Modelo", "3D", "Laje", "Armadura"],
    "Cargas": ["Cargas", "Modelo"],
    "1ª ordem": ["Deformada", *_ESFORCOS, "Modelo"],
    "2ª ordem": ["Deformada", *_ESFORCOS, "Modelo"],
    "Combinações": ["Deformada", *_ESFORCOS, "Armadura", "Modelo"],
    "Estabilidade": ["Deformada", "Modelo"],
    "Flambagem": ["Modo de flambagem", "Modelo"],
    "Modal": ["Modo de vibração", "Modelo"],
}

#: Entrada da lista de casos da vista de Cargas que mostra **todos os casos de
#: carga juntos** — o permanente, o variável e o vento de uma vez, cada um com
#: a sua cor —, para ver de relance o que o modelo aplica por inteiro.
TODOS_OS_CASOS = "todos os casos"

#: As análises que dependem do caso escolhido na caixa Caso. O modal é vibração
#: livre e o desenho do modelo não analisa nada: para eles a caixa fica
#: desligada, em vez de oferecer uma escolha que não muda coisa nenhuma.
ANALISES_COM_CASO = ("Cargas", "1ª ordem", "2ª ordem", "Combinações",
                     "Estabilidade", "Flambagem")

#: Piso de tamanho da janela, px — o que ainda é utilizável, não o desejável.
#: Cabe num monitor de 1024x768 descontadas a barra de tarefas e as bordas.
#: O piso só vale se o **conteúdo** couber nele: o Qt ignora um mínimo menor
#: que o ``minimumSizeHint`` do que está dentro, e era isso que acontecia aqui
#: — a linha de controles e o painel de tabelas juntos exigiam 1752 px, de
#: modo que a janela não descia disso em tela nenhuma.
JANELA_MINIMA = (800, 520)

#: Tamanho preferido, px, quando a tela permite.
JANELA_DESEJADA = (1500, 900)

#: Fração da área útil da tela que a janela ocupa quando não cabe inteira.
FRACAO_DA_TELA = 0.94

#: Altura do painel de relatório: teto e piso, px. Entre os dois ele
#: acompanha a altura da janela, para não comer a tela pequena.
ALTURA_RELATORIO = 220
ALTURA_RELATORIO_MINIMA = 90

#: Quantos caracteres uma lista suspensa mostra antes de truncar. Sem isto a
#: caixa de Vista nascia com 234 px só para caber "Modo de flambagem", e a de
#: Caso crescia com o nome da combinação — que pode ser bem longo.
CARACTERES_NA_LISTA = 12

#: Quanto da largura fica com as tabelas; o resto vai para o desenho.
FRACAO_DAS_TABELAS = 0.42


class Janela(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pórticos 3D — solver matricial de pórticos "
                            "espaciais")
        self.setMinimumSize(*JANELA_MINIMA)

        self.modelo = Modelo("portico")
        #: 1ª ordem: os casos do modelo **e** as combinações, por nome.
        self.resultados: dict[str, Resultado] = {}
        #: 2ª ordem (P-Δ) por caso, e a 1ª ordem de cada combinação ELU
        #: resolvida na estabilidade. Ficam à parte para a 2ª ordem não
        #: apagar a 1ª do mesmo caso, que era o que acontecia.
        self.resultados_2a: dict[str, Resultado] = {}
        self.resultados_estab: dict[str, Resultado] = {}
        self.flambagens: dict[str, object] = {}
        #: As combinações geradas por "Análise", por nome — a vista de Cargas
        #: monta o caso ponderado de cada uma para mostrar o que ela aplica.
        self._combinacoes: dict[str, object] = {}
        self.modal_atual = None
        self._modal_caso_referencia = None
        #: O texto de cada análise, para mostrar o detalhe quando o usuário a
        #: escolhe na lista, sem despejar tudo no relatório de uma vez.
        self._textos: dict[str, str] = {}
        self.caminho: Path | None = None
        self._ultimo_relatorio_de_laje: list[str] | None = None
        # A armadura de um pavimento custa alguns segundos: são os três
        # motores de elemento rodando. Guardá-la por cota é o que permite
        # girar o desenho sem redimensionar o prédio a cada arrasto.
        self.armaduras: dict[float, object] = {}
        #: A envoltória das combinações últimas, compartilhada entre as ações
        #: que precisam dela.
        self._envoltoria = None
        #: Como a 2ª ordem global entrou em cada combinação ELU.
        self._tratamento_2a: list = []
        #: O que "Dimensionar" calculou por último (``vigas``, ``lajes``,
        #: ``pilares``). É daqui que "Emitir > Pranchas" lê: dimensionar
        #: atualiza os modelos, e imprimir é uma decisão à parte, que não
        #: deve obrigar a calcular de novo.
        self.dimensionamento: dict[str, object] = {}
        self._assinatura_das_tabelas: str | None = None
        #: O lançamento por planta de onde o modelo veio, se veio de um.
        self.lancamento = None
        self.editor_de_lancamento = None

        self.dados = PainelDeDados()
        self.vista = Vista3D()
        self.vista.definir_callback_selecao(self._ao_selecionar_elemento)
        self.relatorio = QPlainTextEdit()
        self.relatorio.setReadOnly(True)
        self.relatorio.setMaximumHeight(220)

        self._montar_barra()
        self._montar_corpo()
        self._carregar_nas_tabelas()
        self._ajustar_a_tela()
        self.registrar("Pronto. Use o assistente para gerar um pórtico "
                       "regular, ou abra um modelo.")

    # -- tamanho -----------------------------------------------------------

    def _ajustar_a_tela(self) -> None:
        """Abre a janela no tamanho que a tela **desta** máquina permite.

        Um ``resize(1500, 900)`` fixo abria fora da tela num notebook de
        1366x768 — e com a escala do Windows em 125 % ou 150 % até um monitor
        de 1920x1080 fica com 1536x864 ou 1280x720 de área útil, porque o Qt
        trabalha em pixels lógicos. Aqui o tamanho sai da área **útil** (já
        sem a barra de tarefas), a janela é centrada nela, e quando a tela é
        pequena abre maximizada — que é o que o usuário faria à mão.
        """
        tela = self.screen() or QApplication.primaryScreen()
        if tela is None:
            self.resize(*JANELA_DESEJADA)
            return
        area = tela.availableGeometry()
        largura = min(JANELA_DESEJADA[0], int(area.width() * FRACAO_DA_TELA))
        altura = min(JANELA_DESEJADA[1], int(area.height() * FRACAO_DA_TELA))
        self.resize(max(largura, JANELA_MINIMA[0]),
                    max(altura, JANELA_MINIMA[1]))
        quadro = self.frameGeometry()
        quadro.moveCenter(area.center())
        self.move(quadro.topLeft())
        if (area.width() <= JANELA_DESEJADA[0] * 0.8
                or area.height() <= JANELA_DESEJADA[1] * 0.8):
            self.showMaximized()
        self.repartir()

    def repartir(self) -> None:
        """Divide a largura entre tabelas e desenho, em proporção.

        Precisa ser dito explicitamente: ``setStretchFactor`` só reparte a
        **sobra** quando o divisor é arrastado, e o tamanho inicial sai do
        ``sizeHint`` de cada lado. Como o painel de tabelas encolheu para
        caber em tela pequena, o seu ``sizeHint`` virou 272 px — e sem esta
        repartição ele nascia com isso mesmo numa janela de 1366, com o
        desenho ficando com 1086. Depois de aberta, o arrasto do usuário
        manda, porque isto roda uma vez só.
        """
        largura = max(self.width(), JANELA_MINIMA[0])
        self.divisor.setSizes([int(largura * FRACAO_DAS_TABELAS),
                               largura - int(largura * FRACAO_DAS_TABELAS)])

    def resizeEvent(self, evento) -> None:      # noqa: N802 (API do Qt)
        """O relatório acompanha a altura da janela, entre um piso e um teto.

        Com altura fixa de 220 px ele comia 40 % de uma tela de 560 px, e o
        desenho — que é o assunto — ficava numa faixa.
        """
        super().resizeEvent(evento)
        self.relatorio.setMaximumHeight(
            max(ALTURA_RELATORIO_MINIMA,
                min(ALTURA_RELATORIO, self.height() // 4)))

    # -- construção --------------------------------------------------------

    def _acao(self, texto: str, gatilho, atalho: str = "") -> QAction:
        acao = QAction(texto, self)
        acao.triggered.connect(gatilho)
        if atalho:
            acao.setShortcut(atalho)
            # A ação também entra na janela, e não só no lugar onde é
            # mostrada. Com as ações agrupadas em menus, o atalho passou a
            # depender de o Qt alcançar a ação pela cadeia botão → barra →
            # janela; registrá-la aqui torna isso certo em vez de provável, e
            # não desenha nada — a QMainWindow não mostra as próprias ações.
            self.addAction(acao)
        return acao

    def _menu_na_barra(self, barra, titulo: str,
                       itens: list[tuple]) -> QToolButton:
        """Um botão da barra que abre um menu, em vez de N botões em fila.

        Dezesseis ações lado a lado pediam 3 322 px — a barra transbordava
        para o botão "»" **até num monitor de 1920**, e metade do programa
        ficava a dois cliques em qualquer tela. Agrupadas por assunto, cabem.
        Os atalhos continuam valendo: eles são da ``QAction``, e não do lugar
        onde ela é mostrada.
        """
        botao = QToolButton()
        botao.setText(titulo)
        botao.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(botao)
        for texto, gatilho, atalho in itens:
            menu.addAction(self._acao(texto, gatilho, atalho))
        botao.setMenu(menu)
        barra.addWidget(botao)
        return botao

    def _montar_barra(self) -> None:
        barra = self.addToolBar("Principal")
        barra.setMovable(False)
        for texto, gatilho, atalho in (
                ("Novo", self.novo, "Ctrl+N"),
                ("Abrir", self.abrir, "Ctrl+O"),
                ("Salvar", self.salvar, "Ctrl+S"),
                ("Assistente", self.assistente, "Ctrl+G"),
                ("Lançamento", self.abrir_lancamento, "Ctrl+L")):
            barra.addAction(self._acao(texto, gatilho, atalho))
        barra.addSeparator()

        # As duas ações do dia a dia ficam soltas; o resto vai para menus.
        barra.addAction(self._acao("Aplicar tabelas", self.aplicar, "F5"))
        # Um botão só: roda todas as análises. Qual delas aparece na tela, e
        # para qual caso, quem escolhe é a lista ao lado da vista.
        barra.addAction(self._acao("Análise", self.analisar_tudo, "F9"))
        self._montar_menu_de_calculo(barra)
        barra.addSeparator()
        self._menu_na_barra(barra, "Dimensionar ▾", [
            ("Pilares", self.dimensionar_pilares, "F7"),
            ("Vigas", self.dimensionar_vigas, "F6"),
            ("Lajes", self.dimensionar_lajes, "F4"),
        ])
        self._menu_na_barra(barra, "Emitir ▾", [
            ("Projeto completo", self.gerar_projeto, "F2"),
            ("Armadura em DXF", self.exportar_armadura, "F3"),
            ("Pranchas de vigas", self.emitir_pranchas_de_vigas, ""),
            ("Pranchas de lajes", self.emitir_pranchas_de_lajes, ""),
            ("Reações", self.mostrar_reacoes, "F8"),
        ])
        barra.addSeparator()
        self._menu_na_barra(barra, "Relatório ▾", [
            ("Salvar relatório", self.salvar_relatorio, ""),
            ("Limpar relatório", self.relatorio.clear, ""),
        ])

    def _montar_menu_de_calculo(self, barra) -> None:
        """As opções de **como** o modelo é calculado.

        Moram no modelo (``Modelo.calculo``) e vão para o arquivo: um modelo
        aberto de novo é calculado do mesmo jeito. Mudar uma delas apaga as
        análises feitas, porque elas foram feitas com a outra.
        """
        botao = QToolButton()
        botao.setText("Cálculo ▾")
        botao.setPopupMode(QToolButton.InstantPopup)
        botao.setToolTip("Laje como diafragma ou grelha, e com que esforços "
                         "as vigas são armadas")
        menu = QMenu(botao)

        self.acao_diafragma = QAction("Laje como diafragma rígido", self,
                                      checkable=True)
        self.acao_diafragma.setToolTip(
            "Os nós de cada pavimento transladam em X e Y e giram em Z "
            "juntos: o vento se reparte pela rigidez dos pórticos")
        self.acao_diafragma.toggled.connect(
            lambda v: self._mudar_calculo(diafragma=bool(v)))
        self.acao_grelha = QAction("Lajes em grelha", self, checkable=True)
        self.acao_grelha.setToolTip(
            "Cada laje vira uma grelha de barras ligada às vigas: a carga "
            "chega às vigas pela rigidez, e não pelas áreas a 45°")
        self.acao_grelha.toggled.connect(
            lambda v: self._mudar_calculo(grelha=bool(v)))
        menu.addAction(self.acao_diafragma)
        menu.addAction(self.acao_grelha)
        menu.addAction(self._acao("Malha da grelha…", self._pedir_malha))
        menu.addSeparator()

        self.acao_mesa = QAction("Vigas com mesa colaborante (seção T)",
                                 self, checkable=True)
        self.acao_mesa.setToolTip(
            "A viga é armada como seção T com a laje ao lado (14.6.2.2); a "
            "análise do pórtico segue com a seção retangular")
        self.acao_mesa.toggled.connect(
            lambda v: self._mudar_calculo(mesa_colaborante=bool(v)))
        menu.addAction(self.acao_mesa)

        vigas = menu.addMenu("Vigas armadas com")
        grupo = QActionGroup(self)
        self.acoes_fonte_vigas: dict[str, QAction] = {}
        for fonte, texto in (
                ("portico", "Envoltória do pórtico"),
                ("envolvente", "Pior entre pórtico e viga contínua"),
                ("motor", "Só a viga contínua (g e q)")):
            acao = QAction(texto, self, checkable=True)
            acao.setData(fonte)
            grupo.addAction(acao)
            vigas.addAction(acao)
            acao.toggled.connect(
                lambda v, f=fonte: v and self._mudar_calculo(fonte_vigas=f))
            self.acoes_fonte_vigas[fonte] = acao

        botao.setMenu(menu)
        barra.addWidget(botao)
        self._sincronizar_calculo()

    def _sincronizar_calculo(self) -> None:
        """Marca no menu as opções do modelo que está aberto."""
        c = self.modelo.calculo
        for acao, valor in ((self.acao_diafragma, c.diafragma),
                            (self.acao_grelha, c.grelha),
                            (self.acao_mesa, c.mesa_colaborante)):
            acao.blockSignals(True)
            acao.setChecked(valor)
            acao.blockSignals(False)
        for fonte, acao in self.acoes_fonte_vigas.items():
            acao.blockSignals(True)
            acao.setChecked(fonte == c.fonte_vigas)
            acao.blockSignals(False)
        self.acao_grelha.setText(
            f"Lajes em grelha (malha {c.malha_grelha:g} m)")

    def _mudar_calculo(self, **mudancas) -> None:
        novo = replace(self.modelo.calculo, **mudancas)
        if novo == self.modelo.calculo:
            return
        self.modelo.calculo = novo
        # o que foi analisado e dimensionado foi com a opção anterior
        self._assinatura_das_tabelas = None
        self._limpar_resultados()
        self.armaduras.clear()
        self.dimensionamento.clear()
        self._envoltoria = None
        self._sincronizar_calculo()
        fonte = {"portico": "envoltória do pórtico",
                 "envolvente": "pior entre pórtico e viga contínua",
                 "motor": "só a viga contínua"}[novo.fonte_vigas]
        self.registrar(
            "Cálculo: diafragma " + ("ligado" if novo.diafragma else
                                     "desligado")
            + ", lajes " + (f"em grelha (malha {novo.malha_grelha:g} m)"
                            if novo.grelha else "como carga (áreas a 45°)")
            + f", vigas armadas com {fonte}"
            + (" em seção T" if novo.mesa_colaborante else "")
            + ". Rode a Análise de novo.")
        if novo.grelha:
            from ..core.grelha import avisos_da_grelha
            try:
                avisos = avisos_da_grelha(self.modelo)
            except ErroDeModelo as erro:
                self._erro(erro)
                return
            if avisos:
                self.registrar("  " + "\n  ".join(avisos))

    def _pedir_malha(self) -> None:
        valor, ok = QInputDialog.getDouble(
            self, "Malha da grelha",
            "Espaçamento-alvo das barras da laje (m):",
            self.modelo.calculo.malha_grelha, 0.1, 10.0, 2)
        if ok:
            self._mudar_calculo(malha_grelha=float(valor))

    def _estreitar(self, caixa: QComboBox) -> QComboBox:
        """Impede que uma lista suspensa cresça com o texto do maior item.

        O padrão do Qt é dimensionar a caixa pelo item mais longo, e era daí
        que vinha metade do piso de largura da janela: "Modo de flambagem"
        obrigava 234 px, e o nome de uma combinação obrigaria mais. Truncado
        assim, o item continua legível na lista aberta e no balão de dica.
        """
        caixa.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        caixa.setMinimumContentsLength(CARACTERES_NA_LISTA)
        return caixa

    def _montar_corpo(self) -> None:
        # A análise escolhe quais vistas existem (``VISTAS_POR_ANALISE``) e que
        # casos podem ser olhados; a vista e o caso vêm depois dela.
        self.escolha_analise = self._estreitar(QComboBox())
        self.escolha_analise.addItems(ANALISES)
        self.escolha_analise.setToolTip(
            "Qual análise está na tela. O botão Análise roda todas; aqui se "
            "escolhe qual olhar")
        self.escolha_analise.currentTextChanged.connect(
            self._ao_trocar_analise)
        self.escolha_vista = self._estreitar(QComboBox())
        self.escolha_vista.addItems(VISTAS_POR_ANALISE["Modelo"])
        self.escolha_vista.currentTextChanged.connect(self.redesenhar)
        self.escolha_caso = self._estreitar(QComboBox())
        self.escolha_caso.currentTextChanged.connect(self.redesenhar)
        self.escala = QDoubleSpinBox()
        self.escala.setRange(0.0, 1.0e6)
        self.escala.setDecimals(1)
        self.escala.setValue(0.0)
        self.escala.setSpecialValueText("automática")
        self.escala.valueChanged.connect(self.redesenhar)
        self.escolha_nivel = self._estreitar(QComboBox())
        self.escolha_nivel.setToolTip(
            "Pavimento a desenhar. Vale nas vistas de Laje e de Armadura, "
            "que são de um pavimento por vez")
        self.escolha_nivel.currentTextChanged.connect(self.redesenhar)
        # As lajes do modelo 3D: opacas, e escondidas quando o usuário
        # quiser ver as vigas e os pilares por baixo. Liga e desliga os atores
        # sem redesenhar, para a câmera não voltar ao início.
        self.mostrar_lajes = QCheckBox("lajes")
        self.mostrar_lajes.setChecked(True)
        self.mostrar_lajes.setToolTip(
            "Mostrar as lajes no modelo 3D (desmarcar as esconde)")
        self.mostrar_lajes.toggled.connect(self.vista.definir_lajes_visiveis)
        self.rotulos_nos = QCheckBox("nós")
        self.rotulos_barras = QCheckBox("barras")
        for c in (self.rotulos_nos, self.rotulos_barras):
            c.stateChanged.connect(self.redesenhar)

        # O Diagrama de esforços alterna entre o esqueleto de sempre
        # ("barras") e o sólido extrudado da seção real ("3D") — deixa óbvio
        # quando um elemento muito solicitado tem seção pequena. Só é lido
        # quando a vista escolhida é um componente de esforço.
        self.representacao_diagrama = self._estreitar(QComboBox())
        self.representacao_diagrama.addItems(list(REPRESENTACOES_DE_DIAGRAMA))
        self.representacao_diagrama.currentTextChanged.connect(self.redesenhar)

        # A vista de Armadura abre como janela nativa separada do VTK, não no
        # widget embutido (ver ``vista3d.VistaArmadura3D``): este botão é o
        # gatilho, habilitado só quando a vista e o nível fazem sentido.
        #
        # Fica **fora** da barra de ferramentas de propósito: a barra
        # transborda para dentro do botão "»" do Qt quando não cabe tudo (ver
        # o comentário abaixo), e foi exatamente aí que este botão sumiu de
        # vista numa janela mais estreita — sendo o último item da lista, é o
        # primeiro a ser engolido. Uma linha própria acima do desenho, que só
        # aparece quando a vista é "Armadura", não compete por espaço com o
        # resto dos controles.
        self.botao_armadura_3d = QPushButton("Abrir vista 3D da armadura")
        self.botao_armadura_3d.setEnabled(False)
        self.botao_armadura_3d.setVisible(False)
        self.botao_armadura_3d.clicked.connect(self.abrir_armadura_3d)
        self._ultima_armadura_aberta: tuple[str, float] | None = None

        # Os controles do desenho vão numa **segunda barra de ferramentas**, e
        # não numa linha dentro do corpo. A diferença é que a barra transborda
        # sozinha: o que não couber some para dentro do botão "»" do Qt, em vez
        # de empurrar a largura mínima da janela. Era essa linha, somada ao
        # painel de tabelas, que fixava o piso em 1752 px.
        self.barra_de_vista = self.addToolBar("Desenho")
        self.barra_de_vista.setMovable(False)
        for rotulo, controle in (("Análise:", self.escolha_analise),
                                 ("Vista:", self.escolha_vista),
                                 (None, self.mostrar_lajes),
                                 ("Caso:", self.escolha_caso),
                                 ("Nível:", self.escolha_nivel),
                                 ("Escala:", self.escala),
                                 ("Rótulos:", self.rotulos_nos),
                                 (None, self.rotulos_barras),
                                 ("Diagrama:", self.representacao_diagrama)):
            if rotulo is not None:
                self.barra_de_vista.addWidget(QLabel(" " + rotulo + " "))
            self.barra_de_vista.addWidget(controle)

        direita = QWidget()
        leiaute = QVBoxLayout(direita)
        leiaute.setContentsMargins(6, 6, 6, 6)
        leiaute.addWidget(self.botao_armadura_3d)
        leiaute.addWidget(self.vista, 1)

        self.divisor = QSplitter(Qt.Horizontal)
        self.divisor.addWidget(self.dados)
        self.divisor.addWidget(direita)
        # Proporção, não pixels: 620/880 era a repartição de uma janela de
        # 1500 px, e numa de 900 px deixava o desenho com 280.
        self.divisor.setStretchFactor(0, 4)
        self.divisor.setStretchFactor(1, 6)
        # Numa tela apertada, poder encolher um dos lados a zero é o que
        # salva: o usuário arrasta o divisor e trabalha só na tabela ou só no
        # desenho, em vez de ver os dois espremidos.
        self.divisor.setChildrenCollapsible(True)

        vertical = QSplitter(Qt.Vertical)
        vertical.addWidget(self.divisor)
        vertical.addWidget(self.relatorio)
        vertical.setStretchFactor(0, 5)
        vertical.setStretchFactor(1, 1)

        self.setCentralWidget(vertical)
        self.statusBar().showMessage("Pronto")

    # -- utilidades --------------------------------------------------------

    def registrar(self, texto: str) -> None:
        self.relatorio.appendPlainText(texto)
        self.statusBar().showMessage(texto.splitlines()[0][:160])

    def _erro(self, erro: Exception) -> None:
        self.registrar(f"ERRO: {erro}")
        self.statusBar().showMessage(str(erro)[:200])

    def _carregar_nas_tabelas(self) -> None:
        registros = modelo_para_registros(self.modelo)
        for chave, tabela in self.dados.tabelas.items():
            tabela.carregar(registros[chave])
        # ``carregar`` silencia os sinais da tabela para não recalcular a cada
        # célula preenchida; as seções calculáveis são travadas aqui, depois.
        self.dados.recalcular_todas_as_secoes()
        self._atualizar_casos()
        self._atualizar_niveis()
        self.vista.desenhar_modelo(self.modelo)

    def _atualizar_niveis(self) -> None:
        """Lista as cotas em que há laje, mais a opção de ver todas."""
        cotas = sorted({round(self.modelo.ponto(l.no_a)[2], 6)
                        for l in self.modelo.lajes.values()})
        self.escolha_nivel.blockSignals(True)
        self.escolha_nivel.clear()
        self.escolha_nivel.addItems([f"{z:g} m" for z in cotas] + ["todos"])
        self.escolha_nivel.blockSignals(False)

    def _cota_escolhida(self) -> float | None:
        texto = self.escolha_nivel.currentText()
        if not texto or texto == "todos":
            return None
        try:
            return float(texto.replace(" m", "").replace(",", "."))
        except ValueError:
            return None

    def _casos_da_analise(self, analise: str) -> list[str]:
        """Os casos que a análise escolhida tem para mostrar.

        Só entram os que a análise **de fato resolveu** — um caso em que a 2ª
        ordem não convergiu, ou em que a estrutura não flamba, não aparece na
        lista dela, em vez de aparecer e não desenhar nada. Antes de qualquer
        análise, a 1ª ordem lista os casos do modelo.
        """
        casos = list(self.modelo.casos)
        if analise == "Cargas":
            return casos + list(self._combinacoes) + [TODOS_OS_CASOS]
        if analise == "1ª ordem":
            feitos = [c for c in casos if c in self.resultados]
            return feitos or casos
        if analise == "2ª ordem":
            return [c for c in casos if c in self.resultados_2a]
        if analise == "Combinações":
            return [n for n in self.resultados if n not in self.modelo.casos]
        if analise == "Estabilidade":
            return list(self.resultados_estab)
        if analise == "Flambagem":
            return [c for c in casos if c in self.flambagens]
        return []

    def _atualizar_casos(self) -> None:
        analise = self.escolha_analise.currentText()
        atual = self.escolha_caso.currentText()
        self.escolha_caso.blockSignals(True)
        self.escolha_caso.clear()
        self.escolha_caso.addItems(self._casos_da_analise(analise))
        if atual:
            indice = self.escolha_caso.findText(atual)
            if indice >= 0:
                self.escolha_caso.setCurrentIndex(indice)
        self.escolha_caso.blockSignals(False)
        self.escolha_caso.setEnabled(analise in ANALISES_COM_CASO)

    def _atualizar_vistas(self) -> None:
        """Deixa na lista de vistas só as da análise escolhida."""
        permitidas = VISTAS_POR_ANALISE[self.escolha_analise.currentText()]
        atual = self.escolha_vista.currentText()
        self.escolha_vista.blockSignals(True)
        self.escolha_vista.clear()
        self.escolha_vista.addItems(permitidas)
        if atual in permitidas:
            self.escolha_vista.setCurrentText(atual)
        self.escolha_vista.blockSignals(False)

    def _ao_trocar_analise(self, *_args) -> None:
        """A análise mudou: vistas e casos passam a ser os dela.

        Escreve no relatório o texto da análise escolhida — o detalhe que o
        botão Análise não despeja de uma vez —, só quando ela já foi rodada.
        """
        self._atualizar_vistas()
        self._atualizar_casos()
        self.redesenhar()
        analise = self.escolha_analise.currentText()
        texto = self._texto_da_analise(analise)
        if texto:
            self.registrar("\n" + texto)

    def _texto_da_analise(self, analise: str) -> str:
        """O resumo da análise para o caso escolhido, se ela já foi rodada."""
        caso = self.escolha_caso.currentText()
        if analise == "Cargas":
            efetivos = self._caso_de_carga(caso)
            if efetivos is None:
                return ""
            if not isinstance(efetivos, list):
                efetivos = [efetivos]
            from ..core.auditoria_cargas import resumo_do_caso
            try:
                return "\n".join(resumo_do_caso(self.modelo, c, limite=15)
                                 for c in efetivos)
            except ErroDeModelo as erro:
                return str(erro)
        if analise in ("1ª ordem", "Combinações"):
            resultado = self.resultados.get(caso)
            return resultado.resumo() if resultado is not None else ""
        if analise == "2ª ordem":
            resultado = self.resultados_2a.get(caso)
            if resultado is None:
                return ""
            return (f"Segunda ordem de '{caso}': convergiu em "
                    f"{resultado.iteracoes} iterações.\n"
                    + resultado.resumo())
        if analise == "Flambagem":
            f = self.flambagens.get(caso)
            return str(f) if f is not None else ""
        return self._textos.get(analise, "")

    def _caso_de_carga(self, nome: str):
        """O caso que a vista de Cargas mostra: o do modelo ou, para uma
        combinação, o caso **ponderado** — as ações já multiplicadas pelos
        fatores da combinação, que é o que de fato é aplicado. Para
        ``TODOS_OS_CASOS``, a lista de todos os casos do modelo."""
        if nome == TODOS_OS_CASOS:
            return list(self.modelo.casos.values())
        if nome in self.modelo.casos:
            return self.modelo.casos[nome]
        combinacao = self._combinacoes.get(nome)
        if combinacao is None:
            return None
        from ..core.combinacoes import caso_efetivo
        try:
            return caso_efetivo(self.modelo, combinacao)
        except ErroDeModelo:
            return None

    def _mostrar(self, analise: str, vista: str) -> None:
        """Põe uma análise e uma vista dela na tela."""
        self.escolha_analise.setCurrentText(analise)
        if self.escolha_vista.findText(vista) >= 0:
            self.escolha_vista.setCurrentText(vista)

    def _resultado_atual(self) -> Resultado | None:
        """O resultado do caso escolhido, **na análise escolhida**."""
        fonte = {"2ª ordem": self.resultados_2a,
                 "Estabilidade": self.resultados_estab
                 }.get(self.escolha_analise.currentText(), self.resultados)
        return fonte.get(self.escolha_caso.currentText())

    def _limpar_resultados(self) -> None:
        """O modelo é outro: nada do que foi analisado vale mais."""
        self.resultados.clear()
        self.resultados_2a.clear()
        self.resultados_estab.clear()
        self.flambagens.clear()
        self._combinacoes.clear()
        self.modal_atual = None
        self._modal_caso_referencia = None
        self._textos.clear()

    # -- ações -------------------------------------------------------------

    def novo(self) -> None:
        self.modelo = Modelo("portico")
        self._limpar_resultados()
        self.caminho = None
        self._carregar_nas_tabelas()
        self._sincronizar_calculo()
        self.registrar("Modelo novo, vazio.")

    def abrir(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Abrir modelo ou lançamento", "",
            "Modelo de pórtico ou lançamento (*.json)")
        if not caminho:
            return
        try:
            self.modelo = ler(caminho)
        except (ErroDeModelo, OSError, ValueError) as erro:
            self._erro(erro)
            return
        self.caminho = Path(caminho)
        self._limpar_resultados()
        self._carregar_nas_tabelas()
        self._sincronizar_calculo()
        self.registrar(f"Aberto {caminho}: {len(self.modelo.nos)} nós, "
                       f"{len(self.modelo.barras)} barras.")
        geracao = self.modelo.__dict__.get("geracao")
        self.lancamento = self.modelo.__dict__.get("lancamento")
        if geracao is not None:
            # Arquivo de lançamento: o modelo foi gerado agora, a partir das
            # plantas. As tabelas mostram o modelo de cálculo; editar nelas
            # não volta ao lançamento, e salvar grava o modelo de cálculo.
            self.registrar(geracao.resumo())
            self.registrar("O modelo veio de um lançamento por planta: "
                           "edições nas tabelas não voltam a ele.")

    def salvar(self) -> None:
        if not self.aplicar():
            return
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Salvar modelo", str(self.caminho or "portico.json"),
            "Modelo de pórtico (*.json)")
        if not caminho:
            return
        try:
            gravar(self.modelo, caminho)
        except OSError as erro:
            self._erro(erro)
            return
        self.caminho = Path(caminho)
        self.registrar(f"Salvo em {caminho}.")

    def abrir_lancamento(self) -> None:
        """Abre o editor de lançamento por planta.

        Abre com o lançamento de onde o modelo atual veio, ou com um novo. O
        "Gerar modelo" do editor manda o modelo para cá
        (``_receber_lancamento``); o editor fica aberto ao lado, para
        lançar, gerar e conferir sem ir e voltar.
        """
        from .editor_planta import EditorDeLancamento

        if self.editor_de_lancamento is None:
            self.editor_de_lancamento = EditorDeLancamento(
                self.lancamento, ao_gerar=self._receber_lancamento, pai=self)
        self.editor_de_lancamento.show()
        self.editor_de_lancamento.raise_()

    def _receber_lancamento(self, geracao, lancamento) -> None:
        """O editor gerou um modelo: ele passa a ser o modelo da janela,
        com as opções de cálculo que o usuário já tinha escolhido aqui."""
        modelo = geracao.modelo
        modelo.calculo = replace(self.modelo.calculo)
        self.modelo = modelo
        self.lancamento = lancamento
        self._limpar_resultados()
        self.armaduras.clear()
        self.dimensionamento.clear()
        self._envoltoria = None
        self._assinatura_das_tabelas = None
        self._carregar_nas_tabelas()
        self._sincronizar_calculo()
        self.registrar(geracao.resumo())

    def assistente(self) -> None:
        dialogo = AssistenteDePortico(self)
        if dialogo.exec() != AssistenteDePortico.Accepted:
            return
        calculo = replace(self.modelo.calculo)
        try:
            self.modelo = dialogo.modelo()
        except ErroDeModelo as erro:
            self._erro(erro)
            return
        # o pórtico novo é calculado como o usuário já tinha escolhido
        self.modelo.calculo = calculo
        self._limpar_resultados()
        self._carregar_nas_tabelas()
        self.registrar(
            f"Pórtico gerado: {len(self.modelo.nos)} nós, "
            f"{len(self.modelo.barras)} barras, "
            f"{len(self.modelo.casos)} casos de carga.")

    def aplicar(self) -> bool:
        """Lê as tabelas para um modelo novo. Devolve se deu certo."""
        try:
            registros = {chave: tabela.registros()
                         for chave, tabela in self.dados.tabelas.items()}
            modelo = registros_para_modelo(registros, self.modelo.nome)
            # As opções de cálculo não moram nas tabelas: passam do modelo
            # anterior para o novo.
            modelo.calculo = replace(self.modelo.calculo)
            modelo.validar()
        except ErroDeModelo as erro:
            self._erro(erro)
            return False
        # Dimensionar vigas e depois lajes aplica as tabelas duas vezes. Se elas
        # não mudaram, o dimensionamento e a armadura guardados continuam
        # valendo — e é deles que "Emitir > Pranchas" lê sem recalcular.
        assinatura = repr((sorted(registros.items()), modelo.calculo))
        inalterado = assinatura == self._assinatura_das_tabelas
        self._assinatura_das_tabelas = assinatura

        self.modelo = modelo
        self._ultimo_relatorio_de_laje = None
        if not inalterado:
            # o modelo é outro: o que foi guardado é do anterior — as análises
            # inclusive. Com as tabelas iguais elas continuam valendo, e é
            # isso que deixa "Dimensionar" rodar sem apagar a análise que está
            # na tela.
            self._limpar_resultados()
            self.armaduras.clear()
            self.dimensionamento.clear()
            self._envoltoria = None
        self._atualizar_casos()
        self._atualizar_niveis()
        self.redesenhar()
        self.registrar(f"Tabelas aplicadas: {len(modelo.nos)} nós, "
                       f"{len(modelo.barras)} barras.")
        return True

    def analisar_tudo(self) -> None:
        """Roda **todas** as análises de uma vez.

        1ª ordem e 2ª ordem para cada caso de carga, as combinações da NBR com
        a envoltória, a estabilidade global, a flambagem de cada caso e o
        modal. Quem escolhe o que olhar depois é a lista **Análise** da barra
        de desenho — cada análise com as vistas que fazem sentido para ela, e
        com o caso que ela resolveu. O botão não pergunta qual rodar: uma
        análise que não se aplica ao modelo (sem carga vertical, a flambagem
        não tem fator positivo) é anotada e não derruba as outras.
        """
        if not self.aplicar():
            return
        casos = list(self.modelo.casos)
        if not casos:
            self.registrar("Não há caso de carga para analisar.")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.registrar("Analisando: 1ª ordem, 2ª ordem, combinações, "
                           "estabilidade, flambagem e modal…")
            linhas = self._linhas_do_calculo()
            linhas += self._rodar_primeira_ordem(casos)
            linhas += self._rodar_segunda_ordem(casos)
            linhas += self._rodar_combinacoes()
            linhas += self._rodar_estabilidade()
            linhas += self._rodar_flambagem(casos)
            linhas += self._rodar_modal()
        finally:
            QApplication.restoreOverrideCursor()

        self.registrar("\n".join(linhas))
        # Primeira vez: sai do desenho do modelo para a 1ª ordem. Depois, fica
        # na análise que o usuário estava olhando.
        if self.escolha_analise.currentText() == "Modelo":
            self._mostrar("1ª ordem", "Deformada")
        else:
            self._ao_trocar_analise()

    def _linhas_do_calculo(self) -> list[str]:
        """O que o diafragma e a grelha fizeram com o modelo, em poucas linhas
        — para quem lê o relatório saber com que modelo os números saíram."""
        linhas = []
        if self.modelo.calculo.diafragma:
            from ..core.diafragma import diafragmas
            grupos = diafragmas(self.modelo)
            linhas.append(f"Diafragma rígido: {len(grupos)} pavimentos.")
            linhas += [f"  {d}" for d in grupos if d.excluidos]
        if self.modelo.calculo.grelha:
            from ..core.grelha import avisos_da_grelha
            try:
                linhas += avisos_da_grelha(self.modelo)
            except ErroDeModelo as erro:
                linhas.append(f"Grelha: {erro}")
        return linhas

    def _rodar_primeira_ordem(self, casos: list[str]) -> list[str]:
        feitos, falhas = 0, []
        for caso in casos:
            try:
                self.resultados[caso] = resolver(self.modelo, caso)
                feitos += 1
            except ErroDeModelo as erro:
                falhas.append(f"  {caso}: {erro}")
        return ([f"1ª ordem: {feitos} de {len(casos)} casos resolvidos."]
                + falhas)

    def _rodar_segunda_ordem(self, casos: list[str]) -> list[str]:
        feitos, falhas = [], []
        for caso in casos:
            try:
                r = resolver_p_delta(self.modelo, caso)
            except ErroDeModelo as erro:
                falhas.append(f"  {caso}: {erro}")
                continue
            self.resultados_2a[caso] = r
            feitos.append(f"{caso} ({r.iteracoes} it.)")
        return ["2ª ordem (P-Δ): " + (", ".join(feitos)
                                      or "nenhum caso convergiu")] + falhas

    def _rodar_combinacoes(self) -> list[str]:
        """As combinações da NBR: as ELU **já com a 2ª ordem global** (o
        que vai ao dimensionamento), as ELS em 1ª ordem. A envoltória das ELU
        fica guardada: é ela que "Dimensionar" usa, sem resolver de novo."""
        from ..core.segunda_ordem_global import (
            resultados_para_dimensionamento, resumo)
        try:
            acoes = acoes_do_modelo(self.modelo)
            validar_acoes(self.modelo, acoes)
            elu, els = combinacoes_elu(acoes), combinacoes_els(acoes)
            combinacoes = elu + els
            casos = {c: self.resultados[c] for c in self.modelo.casos
                     if c in self.resultados}
            resultados_elu, tratamento = resultados_para_dimensionamento(
                self.modelo, elu, casos)
            self.resultados.update(resultados_elu)
            self.resultados.update(resolver_combinacoes(self.modelo, els,
                                                        casos or None))
            env = envoltoria(self.modelo, resultados_elu)
        except ErroDeModelo as erro:
            return [f"Combinações: {erro}"]
        self._combinacoes = {c.nome: c for c in combinacoes}
        self._envoltoria = env
        self._tratamento_2a = tratamento

        linhas = [f"{len(combinacoes)} combinações resolvidas "
                  f"({sum(c.tipo == 'ELU' for c in combinacoes)} ELU, "
                  f"{sum(c.tipo.startswith('ELS') for c in combinacoes)} ELS).",
                  "", resumo(tratamento), "",
                  "Envoltória ELU (a do dimensionamento) — extremos com "
                  "esforços concomitantes:"]
        for nome, barra in list(env.items())[:12]:
            for componente in ("N", "My", "Mz"):
                linhas.append("  " + str(barra.extremo(componente, "min")))
        if len(env) > 12:
            linhas.append(f"  ... e mais {len(env) - 12} barras.")
        self._textos["Combinações"] = "\n".join(linhas)
        moveis = [t for t in tratamento if t.tratamento != "1ª ordem"]
        return [f"Combinações: {len(combinacoes)} resolvidas, envoltória "
                "montada"
                + (f"; 2ª ordem global em {len(moveis)} combinações ELU "
                   f"(γz máx {max(t.gama_z for t in moveis):.3f})."
                   if moveis else "; nós fixos, 1ª ordem.")]

    def _rodar_estabilidade(self) -> list[str]:
        try:
            acoes = acoes_do_modelo(self.modelo)
            validar_acoes(self.modelo, acoes)
            combinacoes = combinacoes_elu(acoes)
        except ErroDeModelo as erro:
            return [f"Estabilidade: {erro}"]

        from ..core.segunda_ordem_global import modelo_secante

        # O γz é o da rigidez secante do 15.7.3 — a rigidez com que a norma
        # pede a análise dos esforços globais de 2ª ordem, e a mesma que
        # decide, nas combinações, se o dimensionamento leva 2ª ordem.
        secante = modelo_secante(self.modelo)
        linhas = ["Estabilidade global — NBR 6118, itens 15.5.3 e 15.7.2, "
                  "γz com a rigidez secante do 15.7.3"]
        pior = None
        for combinacao in combinacoes:
            caso = None
            try:
                caso = caso_efetivo(secante, combinacao)
                # O caso efetivo só existe para esta conta: fica no modelo o
                # tempo de resolvê-lo e sai, para não aparecer como caso de
                # carga do usuário nas listas.
                secante.casos[caso.nome] = caso
                resultado = resolver(secante, caso.nome)
                g = gama_z(secante, caso, resultado)
            except ErroDeModelo as erro:
                linhas.append(f"  {combinacao.nome:<10} sem γz: {erro}")
                continue
            finally:
                if caso is not None:
                    secante.casos.pop(caso.nome, None)
            self.resultados_estab[combinacao.nome] = resultado
            linhas.append(
                f"  {combinacao.nome:<10} γz = {g.valor:.4f}  "
                f"{'nós fixos' if g.nos_fixos else 'nós móveis'}"
                + ("" if g.majoracao_valida else "   [acima de 1,3]"))
            if pior is None or g.valor > pior.valor:
                pior = g
        if pior is not None:
            linhas.append("")
            linhas.append(str(pior))
        self._textos["Estabilidade"] = "\n".join(linhas)
        if pior is None:
            return ["Estabilidade: nenhuma combinação com γz."]
        return [f"Estabilidade: γz máximo {pior.valor:.4f} "
                f"({'nós fixos' if pior.nos_fixos else 'nós móveis'})."]

    def _rodar_flambagem(self, casos: list[str]) -> list[str]:
        feitos, falhas = [], []
        for caso in casos:
            try:
                self.flambagens[caso] = flambagem(self.modelo, caso)
            except ErroDeModelo as erro:
                falhas.append(f"  {caso}: {erro}")
                continue
            fator = self.flambagens[caso].fator_critico
            feitos.append(f"{caso} (fator {fator:.3f})")
        return ["Flambagem: " + (", ".join(feitos)
                                 or "nenhum caso perde estabilidade")] + falhas

    def _rodar_modal(self) -> list[str]:
        """Frequências e modos de vibração livre, sem amortecimento.

        Não depende de carga: é vibração livre. O desenho do modo só usa a
        geometria preparada de um ``Resultado`` — a de qualquer caso resolvido
        serve —, e é por isso que guarda um caso de referência.
        """
        try:
            self.modal_atual = analisar_modal(self.modelo)
        except ErroDeModelo as erro:
            return [f"Modal: {erro}"]
        self._modal_caso_referencia = next(iter(self.resultados), None)
        self._textos["Modal"] = str(self.modal_atual)
        return [f"Modal: f1 = {self.modal_atual.frequencia_fundamental:.3f} Hz "
                f"(T1 = {self.modal_atual.periodo_fundamental:.3f} s), "
                f"{len(self.modal_atual.frequencias)} modos."]

    def dimensionar_pilares(self) -> None:
        """Envia os lances verticais ao motor de Pilares, pela envoltória.

        Gera as combinações últimas, monta a envoltória e entrega a cada lance
        os trios de esforço concomitantes que o governam. O veredito é do
        programa de Pilares; daqui sai só a tradução.
        """
        from ..dimensionamento import (barras_verticais, resumo,
                                       verificar_pilares)

        if not self.aplicar():
            return
        env = self.envoltoria_atual()
        if env is None:
            return
        try:
            pilares = barras_verticais(self.modelo)
            if not pilares:
                self.registrar("O modelo não tem barras verticais.")
                return
            verificacoes = verificar_pilares(self.modelo, env)
        except ErroDeModelo as erro:
            self._erro(erro)
            return
        self.dimensionamento["pilares"] = verificacoes
        self.registrar("\n" + resumo(verificacoes))
        self._compatibilizar()
        self._atualizar_modelos_3d()

    def _compatibilizar(self) -> None:
        """Continuidade dos pilares e nós viga–pilar, quando os dois motores
        já rodaram — é a fronteira entre as peças, que nenhum deles vê."""
        from ..compatibilizacao import nos_viga_pilar, prumadas, resumo

        pilares = self.dimensionamento.get("pilares")
        vigas = self.dimensionamento.get("vigas")
        if not pilares or not vigas:
            return
        try:
            p = prumadas(self.modelo, pilares)
            n = nos_viga_pilar(self.modelo, vigas)
        except (ErroDeModelo, KeyError, ValueError) as erro:
            self.registrar(f"Compatibilização: {erro}")
            return
        self.dimensionamento["prumadas"] = p
        self.dimensionamento["nos"] = n
        self.registrar("\n" + resumo(p, n))

    def _atualizar_modelos_3d(self) -> None:
        """Refaz a armadura 3D com o que acabou de ser dimensionado.

        É o que "Dimensionar" entrega: o modelo 3D da armadura, pronto para
        olhar — e **nenhum arquivo**. Gravar prancha é decisão à parte
        (``Emitir > Pranchas``), e dimensionar não deve perguntar pasta nem
        escrever desenho. A armadura guardada é descartada porque ficou velha;
        a do nível escolhido, se houver, é refeita já.
        """
        self.armaduras.clear()
        cota = self._cota_escolhida()
        if cota is None:
            self.registrar("Modelo 3D da armadura atualizado — escolha um "
                           "nível para vê-lo na vista 'Armadura'.")
            return
        try:
            self.armadura_do_nivel(cota)
        except (ErroDeModelo, ValueError, KeyError) as erro:
            self.registrar(f"Modelo 3D da cota {cota:g} m não atualizou: "
                           f"{erro}")
            return
        if self.escolha_vista.currentText() == "Armadura":
            # a janela nativa do VTK bloqueia até ser fechada: recalcular não
            # pode reabri-la à força, só trocar o aviso embutido
            self._ultima_armadura_aberta = ("Armadura", cota)
            self.redesenhar()
        self.registrar(f"Modelo 3D da armadura da cota {cota:g} m atualizado.")

    def dimensionar_vigas(self) -> None:
        """Reconhece as vigas, dimensiona e atualiza o modelo 3D.

        Não pergunta pasta nem grava desenho: a prancha sai em
        ``Emitir > Pranchas de vigas``, quando o usuário pedir.

        Viga que repousa noutra entra aqui também: nela a de apoio é apoio, e
        na de apoio ela é carga concentrada.
        """
        from ..continuidade import vigas_continuas
        from ..dimensionamento import resumo_de_vigas, verificar_vigas

        if not self.aplicar():
            return
        cadeias = [v for v in vigas_continuas(self.modelo)
                   if len(v.suportes) >= 2]
        if not cadeias:
            self.registrar("Nenhuma viga com dois apoios, de pilar ou de "
                           "outra viga.")
            return

        self.registrar(f"Dimensionando {len(cadeias)} vigas…")
        try:
            # A envoltória vai junto, e é o que faz a diferença: sem ela o
            # motor de Vigas dimensiona só para G e Q, e o efeito das ações
            # laterais — que no exemplo dá mais momento na viga que o peso
            # permanente — não chega à armadura. Com ela, a viga é conferida
            # contra o que o edifício inteiro exige.
            verificacoes = verificar_vigas(
                self.modelo, envoltorias=self.envoltoria_atual())
        except ErroDeModelo as erro:
            self._erro(erro)
            return
        self.dimensionamento["vigas"] = verificacoes
        self.registrar("\n" + resumo_de_vigas(verificacoes))
        self._compatibilizar()
        self._atualizar_modelos_3d()

    def dimensionar_lajes(self) -> None:
        """Dimensiona as lajes de cada pavimento e atualiza o modelo 3D.

        Vai por **pavimento**, e não painel a painel, porque a compatibilização
        dos momentos negativos do item 14.7.6.2 acontece entre painéis
        vizinhos: painel sozinho não tem com quem compatibilizar. Não grava
        planta: isso é ``Emitir > Pranchas de lajes``.
        """
        from ..dimensionamento import (cotas_com_laje, resumo_de_lajes,
                                       verificar_lajes)

        if not self.aplicar():
            return
        cotas = cotas_com_laje(self.modelo)
        if not cotas:
            self.registrar("O modelo não tem lajes.")
            return

        self.registrar(f"Dimensionando as lajes de {len(cotas)} pavimentos…")
        try:
            verificacoes = verificar_lajes(self.modelo)
        except ErroDeModelo as erro:
            self._erro(erro)
            return
        self.dimensionamento["lajes"] = verificacoes
        self.registrar("\n" + resumo_de_lajes(verificacoes))
        self._atualizar_modelos_3d()

    def _pasta_de_saida(self, titulo: str) -> str:
        padrao = str(self.caminho.parent if self.caminho else Path.cwd())
        return QFileDialog.getExistingDirectory(self, titulo, padrao)

    def emitir_pranchas_de_vigas(self) -> None:
        """Grava a prancha das vigas já dimensionadas — todas lado a lado.

        Usa o último "Dimensionar vigas"; se ainda não houve, dimensiona
        antes. A pasta é perguntada aqui, e só aqui.
        """
        from ..dimensionamento import gravar_pranchas_de_vigas

        if "vigas" not in self.dimensionamento:
            self.dimensionar_vigas()
        verificacoes = self.dimensionamento.get("vigas")
        if not verificacoes:
            return
        pasta = self._pasta_de_saida("Onde gravar a prancha das vigas")
        if not pasta:
            return
        try:
            caminho = gravar_pranchas_de_vigas(verificacoes, pasta)
        except OSError as erro:
            self._erro(erro)
            return
        self.registrar(f"Prancha das vigas gravada em {caminho}."
                       if caminho else
                       "Nenhuma viga dimensionada com sucesso: nada a gravar.")

    def emitir_pranchas_de_lajes(self) -> None:
        """Grava as plantas de armação dos pavimentos já dimensionados."""
        from ..dimensionamento import gravar_pranchas_de_lajes

        if "lajes" not in self.dimensionamento:
            self.dimensionar_lajes()
        verificacoes = self.dimensionamento.get("lajes")
        if not verificacoes:
            return
        pasta = self._pasta_de_saida("Onde gravar as plantas das lajes")
        if not pasta:
            return
        try:
            arquivos = gravar_pranchas_de_lajes(verificacoes, pasta)
        except OSError as erro:
            self._erro(erro)
            return
        self.registrar(f"{len(arquivos)} arquivo(s) das lajes gravado(s) em "
                       f"{pasta}.")

    def envoltoria_atual(self, avisar: bool = True):
        """A envoltória das combinações últimas, calculada uma vez e guardada.

        Três ações precisam dela — dimensionar pilares, dimensionar vigas e a
        vista de Armadura —, e montá-la custa resolver todas as combinações do
        edifício. Guardá-la evita refazer isso a cada botão; ``aplicar`` a
        joga fora, porque aí o modelo é outro.
        """
        if self._envoltoria is not None:
            return self._envoltoria
        from ..core.segunda_ordem_global import (
            resultados_para_dimensionamento, resumo)
        try:
            acoes = acoes_do_modelo(self.modelo)
            validar_acoes(self.modelo, acoes)
            # Com a 2ª ordem global: 0,95·γz ou P-Δ conforme o γz de cada
            # combinação (15.7). É isto que pilares e vigas recebem.
            resultados, tratamento = resultados_para_dimensionamento(
                self.modelo, combinacoes_elu(acoes))
            self._envoltoria = envoltoria(self.modelo, resultados)
            self._tratamento_2a = tratamento
            self.resultados.update(resultados)
            if avisar:
                self.registrar(resumo(tratamento))
            self._atualizar_casos()
        except ErroDeModelo as erro:
            if avisar:
                self.registrar(f"Sem envoltória: {erro}")
            return None
        return self._envoltoria

    def armadura_do_nivel(self, cota: float):
        """A armadura do pavimento, calculada uma vez e guardada.

        Os três motores rodam aqui: o de Pilares pela envoltória, o de Vigas
        por viga contínua e o de Lajes pelo pavimento. Custa alguns segundos,
        e por isso o resultado fica no cache — trocar de vista ou girar o
        desenho não pode redimensionar o prédio de novo.
        """
        from ..armadura3d import armadura_do_pavimento

        if cota in self.armaduras:
            return self.armaduras[cota]

        # Sem envoltória os pilares ficam de fora, mas vigas e laje não
        # dependem dela: vale mais meia armadura com aviso do que nenhuma.
        armadura = armadura_do_pavimento(self.modelo, cota,
                                         self.envoltoria_atual())
        self.armaduras[cota] = armadura
        self.registrar("\n" + armadura.resumo())
        return armadura

    def exportar_armadura(self) -> None:
        """Grava a armadura do pavimento escolhido como polilinhas 3D em DXF."""
        from ..armadura_dxf import exportar

        if not self.aplicar():
            return
        cota = self._cota_escolhida()
        if cota is None:
            self.registrar("Escolha um nível: o DXF de armadura é de um "
                           "pavimento por vez.")
            return

        padrao = str(self.caminho.parent if self.caminho else Path.cwd())
        destino, _ = QFileDialog.getSaveFileName(
            self, f"Gravar a armadura da cota {cota:g} m",
            str(Path(padrao) / f"armadura-cota-{cota:g}m.dxf"),
            "Desenho DXF (*.dxf)")
        if not destino:
            return

        try:
            armadura = self.armadura_do_nivel(cota)
            caminho = exportar(armadura, destino, self.modelo)
        except (ErroDeModelo, OSError, ValueError) as erro:
            self._erro(erro)
            return
        self.registrar(f"Armadura gravada em {caminho} — "
                       f"{len(armadura.fios)} polilinhas 3D.")

    def gerar_projeto(self) -> None:
        """Resolve o edifício e grava os três arquivos do projeto.

        É o botão que fecha o programa: dali saem a memória de cálculo, o
        quadro de quantidades e a prancha, num só lugar e de uma vez. Custa
        alguns minutos num edifício inteiro — são os três motores de elemento
        rodando peça por peça —, e por isso pergunta a pasta antes.
        """
        from ..projeto import calcular, gerar

        if not self.aplicar():
            return
        padrao = str(self.caminho.parent if self.caminho else Path.cwd())
        pasta = QFileDialog.getExistingDirectory(
            self, "Onde gravar os arquivos do projeto", padrao)
        if not pasta:
            return

        self.registrar("Calculando o projeto — pórtico, envoltória e os três "
                       "motores de elemento. Pode levar alguns minutos…")
        try:
            projeto = calcular(self.modelo)
        except ErroDeModelo as erro:
            self._erro(erro)
            return
        self.registrar("\n" + projeto.resumo())

        self.registrar("Gravando memória de cálculo, quadro de quantidades e "
                       "prancha…")
        for arquivo in gerar(projeto, pasta):
            self.registrar(f"  {arquivo}")

    def mostrar_reacoes(self) -> None:
        """Tabela de reações do caso ou combinação escolhido na caixa Caso.

        Existe como ação própria porque a reação é o que se leva para a
        fundação, e ficava soterrada no meio do resumo geral — num modelo de
        sessenta nós, depois de sessenta linhas de deslocamento.
        """
        resultado = self._resultado_atual()
        if resultado is None:
            if not self.resultados:
                # nada foi analisado ainda: o botão Análise roda tudo
                self.analisar_tudo()
            resultado = self._resultado_atual()
            if resultado is None:
                self.registrar("Escolha a análise e o caso cujas reações "
                               "quer ver.")
                return
        self.registrar("\n" + resultado.reacoes_resumo())

    def salvar_relatorio(self) -> None:
        """Grava o relatório em texto, para levar à planilha ou ao memorial."""
        if not self.relatorio.toPlainText().strip():
            self.registrar("O relatório está vazio.")
            return
        padrao = str((self.caminho.with_suffix(".txt") if self.caminho
                      else Path("relatorio.txt")))
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Salvar relatório", padrao, "Texto (*.txt)")
        if not caminho:
            return
        try:
            Path(caminho).write_text(self.relatorio.toPlainText(),
                                     encoding="utf-8")
        except OSError as erro:
            self._erro(erro)
            return
        self.registrar(f"Relatório salvo em {caminho}.")

    # -- desenho -----------------------------------------------------------

    def redesenhar(self) -> None:
        vista = self.escolha_vista.currentText()
        escala = self.escala.value() or None
        # Cada controle só vale para as vistas a que se refere; os outros ficam
        # apagados em vez de oferecer uma escolha que não muda o desenho.
        e_esforco = vista in VISTAS_DE_ESFORCO
        self.representacao_diagrama.setEnabled(e_esforco)
        self.escala.setEnabled(e_esforco or vista in (
            "Deformada", "Modo de flambagem", "Modo de vibração", "Cargas"))
        self.escolha_nivel.setEnabled(vista in ("Laje", "Armadura"))
        self.mostrar_lajes.setEnabled(vista == "3D")
        self.rotulos_nos.setEnabled(vista == "Modelo")
        self.rotulos_barras.setEnabled(vista == "Modelo")
        # Só aparece (e só fica habilitado) enquanto a vista de Armadura, com
        # nível escolhido, está na tela — nas demais, abrir a janela nativa
        # não faz sentido.
        self.botao_armadura_3d.setVisible(vista == "Armadura")
        self.botao_armadura_3d.setEnabled(False)
        if vista != "Armadura":
            self._ultima_armadura_aberta = None
        try:
            if vista == "Modelo" or not self.modelo.barras:
                self.vista.desenhar_modelo(
                    self.modelo, self.rotulos_nos.isChecked(),
                    self.rotulos_barras.isChecked())
                return

            if vista == "3D":
                self.vista.desenhar_solido(self.modelo)
                return

            if vista == "Laje":
                # O relatório das lajes vai para o painel de baixo só quando a
                # vista é escolhida, e não a cada redesenho, para não repetir o
                # mesmo texto ao girar o desenho ou mexer na escala.
                relatorio = self.vista.desenhar_lajes(self.modelo,
                                                      self._cota_escolhida())
                if relatorio and relatorio != self._ultimo_relatorio_de_laje:
                    self._ultimo_relatorio_de_laje = relatorio
                    self.registrar("\nLajes — momentos em kN·m/m\n  "
                                   + "\n  ".join(relatorio))
                return

            if vista == "Armadura":
                cota = self._cota_escolhida()
                if cota is None:
                    self.vista.desenhar_solido(self.modelo)
                    self.registrar("Escolha um nível: a vista de Armadura é "
                                   "de um pavimento por vez.")
                    return
                # A vista de Armadura abre como janela nativa separada (ver
                # ``abrir_armadura_3d``); o widget embutido só avisa que os
                # dados já foram calculados e guardados no cache.
                self.vista.preparar_aviso_armadura(
                    cota, self.armadura_do_nivel(cota))
                self.botao_armadura_3d.setEnabled(True)
                # Abre sozinha na primeira vez que se chega a este nível —
                # troca de pavimento reabre, mas girar o desenho ou mexer
                # noutro controle da barra (que também chama ``redesenhar``)
                # não reabre à toa, porque a chave (vista, cota) não mudou.
                # Some sob QT_QPA_PLATFORM=offscreen (o --autoteste): lá não
                # há usuário para fechar a janela nativa, que bloqueia até
                # isso acontecer.
                chave = (vista, cota)
                if (chave != self._ultima_armadura_aberta
                        and QApplication.instance().platformName()
                        != "offscreen"):
                    self._ultima_armadura_aberta = chave
                    self.abrir_armadura_3d()
                return

            if vista == "Cargas":
                caso = self._caso_de_carga(self.escolha_caso.currentText())
                self.vista.desenhar_cargas(self.modelo, caso, escala)
                return

            if vista == "Modo de flambagem":
                f = self.flambagens.get(self.escolha_caso.currentText())
                referencia = (self.resultados.get(f.caso)
                              if f is not None else None)
                if f is None or referencia is None:
                    self.vista.desenhar_modelo(self.modelo)
                    return
                self.vista.desenhar_modo(
                    self.modelo, referencia, f.modos[0], f.fator_critico, 0,
                    escala)
                return

            if vista == "Modo de vibração":
                referencia = self.resultados.get(self._modal_caso_referencia)
                if self.modal_atual is None or referencia is None:
                    self.vista.desenhar_modelo(self.modelo)
                    return
                self.vista.desenhar_modo_vibracao(
                    self.modelo, referencia, self.modal_atual.modos[0],
                    self.modal_atual.frequencias[0],
                    self.modal_atual.periodos[0], 0, escala)
                return

            resultado = self._resultado_atual()
            if resultado is None:
                self.vista.desenhar_modelo(self.modelo)
                return

            if vista == "Deformada":
                self.vista.desenhar_deformada(resultado, escala)
            else:
                self.vista.desenhar_diagrama(
                    resultado, vista, escala,
                    self.representacao_diagrama.currentText())
        except (ErroDeModelo, KeyError, ValueError) as erro:
            self._erro(erro)

    def abrir_armadura_3d(self) -> None:
        """Abre a janela nativa do VTK com a armadura do nível escolhido.

        Bloqueia até o usuário fechá-la — o mesmo comportamento de
        ``Plotter.show()`` que Consolos R03 e Lajes R06 já usam para a peça
        detalhada. ``redesenhar()`` já chama isto sozinha na primeira vez que
        a vista de Armadura chega a um nível novo (ver o comentário lá); este
        método continua existindo como o gatilho do botão, para reabrir a
        mesma janela sem trocar de nível.
        """
        cota = self._cota_escolhida()
        if cota is None:
            self.registrar("Escolha um nível antes de abrir a vista 3D da "
                           "armadura.")
            return
        armadura = self.armadura_do_nivel(cota)
        abrir_vista_interativa_armadura(self.modelo, armadura, cota)

    # -- sincronização do 3D com a tabela ativa ------------------------------

    def _tabela_ativa(self) -> str | None:
        """A chave da tabela que está visível agora nas sub-abas de dados.

        ``None`` quando nada de reconhecível está em foco — o painel de
        dados sempre mostra alguma sub-aba, mas ler ``currentWidget()`` é
        mais robusto que supor a ordem das abas.
        """
        grupo = self.dados.currentWidget()
        if grupo is None:
            return None
        atual = grupo.currentWidget()
        for chave, tabela in self.dados.tabelas.items():
            if tabela is atual:
                return chave
        return None

    def _selecionar_linha(self, chave: str, coluna: str, valor: str) -> bool:
        """Destaca, na tabela ``chave``, a linha cuja coluna ``coluna`` tem
        ``valor``. Devolve se achou."""
        tabela = self.dados.tabelas.get(chave)
        if tabela is None:
            return False
        indice = tabela._indice.get(coluna)
        if indice is None:
            return False
        for linha in range(tabela.tabela.rowCount()):
            item = tabela.tabela.item(linha, indice)
            if item is not None and item.text().strip() == valor:
                tabela.tabela.selectRow(linha)
                tabela.tabela.scrollToItem(item)
                return True
        return False

    def _ao_selecionar_elemento(self, info: dict | None) -> None:
        """Callback central do picking em "Modelo"/"Sólido" (ver
        ``Vista3D.definir_callback_selecao``): olha qual sub-aba de dados
        está em foco e destaca, nela, a linha correspondente ao elemento
        apontado no 3D. O 3D já se destaca e mostra um texto sozinho — isto
        só soma a sincronização com a tabela, quando ela existe.
        """
        if info is None:
            return
        chave_ativa = self._tabela_ativa()
        tipo, nome = info["tipo"], info["nome"]

        if tipo == "barra":
            barra = self.modelo.barras.get(nome)
            if chave_ativa == "barras":
                self._selecionar_linha("barras", "nome", nome)
            elif chave_ativa == "secoes" and barra is not None:
                self._selecionar_linha("secoes", "nome", barra.secao)
            elif chave_ativa == "materiais" and barra is not None:
                self._selecionar_linha("materiais", "nome", barra.material)
        elif tipo == "no":
            if chave_ativa in ("nos", "apoios", "molas"):
                coluna = "nome" if chave_ativa == "nos" else "no"
                self._selecionar_linha(chave_ativa, coluna, nome)


def abrir_janela(modelo: Modelo | None = None) -> Janela:
    janela = Janela()
    if modelo is not None:
        janela.modelo = modelo
        janela._carregar_nas_tabelas()
    return janela
