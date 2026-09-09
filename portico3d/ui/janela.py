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
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFileDialog, QLabel,
                               QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QSplitter, QToolButton,
                               QVBoxLayout, QWidget)

from ..arquivo import gravar, ler
from ..core.combinacoes import caso_efetivo, resolver_combinacoes
from ..core.envoltoria import envoltoria
from ..core.estabilidade import gama_z
from ..core.modelo import ErroDeModelo, Modelo
from ..core.montagem import resolver
from ..core.nbr6118 import (acoes_do_modelo, combinacoes_elu, combinacoes_els,
                            validar_acoes)
from ..core.resultados import Resultado
from ..core.segunda_ordem import flambagem, resolver_p_delta
from .assistente import AssistenteDePortico
from .conversao import modelo_para_registros, registros_para_modelo
from .tabelas import PainelDeDados
from .vista3d import VISTAS_DE_ESFORCO, Vista3D

VISTAS = ["Modelo", "3D", "Laje", "Armadura", "Deformada",
          *VISTAS_DE_ESFORCO, "Modo de flambagem"]

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
        self.resultados: dict[str, Resultado] = {}
        self.flambagem_atual = None
        self.caminho: Path | None = None
        self._ultimo_relatorio_de_laje: list[str] | None = None
        # A armadura de um pavimento custa alguns segundos: são os três
        # motores de elemento rodando. Guardá-la por cota é o que permite
        # girar o desenho sem redimensionar o prédio a cada arrasto.
        self.armaduras: dict[float, object] = {}
        #: A envoltória das combinações últimas, compartilhada entre as ações
        #: que precisam dela.
        self._envoltoria = None

        self.dados = PainelDeDados()
        self.vista = Vista3D()
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
                ("Assistente", self.assistente, "Ctrl+G")):
            barra.addAction(self._acao(texto, gatilho, atalho))
        barra.addSeparator()

        # As duas ações do dia a dia ficam soltas; o resto vai para menus.
        barra.addAction(self._acao("Aplicar tabelas", self.aplicar, "F5"))
        barra.addAction(self._acao("Analisar caso", self.analisar, "F9"))
        self._menu_na_barra(barra, "Análise ▾", [
            ("Segunda ordem", self.analisar_segunda_ordem, ""),
            ("Combinações NBR", self.analisar_combinacoes, ""),
            ("Estabilidade global", self.analisar_estabilidade, ""),
            ("Flambagem", self.analisar_flambagem, ""),
        ])
        barra.addSeparator()
        self._menu_na_barra(barra, "Dimensionar ▾", [
            ("Pilares", self.dimensionar_pilares, "F7"),
            ("Vigas", self.dimensionar_vigas, "F6"),
            ("Lajes", self.dimensionar_lajes, "F4"),
        ])
        self._menu_na_barra(barra, "Emitir ▾", [
            ("Projeto completo", self.gerar_projeto, "F2"),
            ("Armadura em DXF", self.exportar_armadura, "F3"),
            ("Reações", self.mostrar_reacoes, "F8"),
        ])
        barra.addSeparator()
        self._menu_na_barra(barra, "Relatório ▾", [
            ("Salvar relatório", self.salvar_relatorio, ""),
            ("Limpar relatório", self.relatorio.clear, ""),
        ])

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
        self.escolha_vista = self._estreitar(QComboBox())
        self.escolha_vista.addItems(VISTAS)
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
        self.rotulos_nos = QCheckBox("nós")
        self.rotulos_barras = QCheckBox("barras")
        for c in (self.rotulos_nos, self.rotulos_barras):
            c.stateChanged.connect(self.redesenhar)

        # Os controles do desenho vão numa **segunda barra de ferramentas**, e
        # não numa linha dentro do corpo. A diferença é que a barra transborda
        # sozinha: o que não couber some para dentro do botão "»" do Qt, em vez
        # de empurrar a largura mínima da janela. Era essa linha, somada ao
        # painel de tabelas, que fixava o piso em 1752 px.
        self.barra_de_vista = self.addToolBar("Desenho")
        self.barra_de_vista.setMovable(False)
        for rotulo, controle in (("Vista:", self.escolha_vista),
                                 ("Caso:", self.escolha_caso),
                                 ("Nível:", self.escolha_nivel),
                                 ("Escala:", self.escala),
                                 ("Rótulos:", self.rotulos_nos),
                                 (None, self.rotulos_barras)):
            if rotulo is not None:
                self.barra_de_vista.addWidget(QLabel(" " + rotulo + " "))
            self.barra_de_vista.addWidget(controle)

        direita = QWidget()
        leiaute = QVBoxLayout(direita)
        leiaute.setContentsMargins(6, 6, 6, 6)
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

    def _atualizar_casos(self) -> None:
        atual = self.escolha_caso.currentText()
        self.escolha_caso.blockSignals(True)
        self.escolha_caso.clear()
        self.escolha_caso.addItems(list(self.modelo.casos)
                                   + [n for n in self.resultados
                                      if n not in self.modelo.casos])
        if atual:
            indice = self.escolha_caso.findText(atual)
            if indice >= 0:
                self.escolha_caso.setCurrentIndex(indice)
        self.escolha_caso.blockSignals(False)

    def _resultado_atual(self) -> Resultado | None:
        return self.resultados.get(self.escolha_caso.currentText())

    # -- ações -------------------------------------------------------------

    def novo(self) -> None:
        self.modelo = Modelo("portico")
        self.resultados.clear()
        self.flambagem_atual = None
        self.caminho = None
        self._carregar_nas_tabelas()
        self.registrar("Modelo novo, vazio.")

    def abrir(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Abrir modelo", "", "Modelo de pórtico (*.json)")
        if not caminho:
            return
        try:
            self.modelo = ler(caminho)
        except (ErroDeModelo, OSError, ValueError) as erro:
            self._erro(erro)
            return
        self.caminho = Path(caminho)
        self.resultados.clear()
        self.flambagem_atual = None
        self._carregar_nas_tabelas()
        self.registrar(f"Aberto {caminho}: {len(self.modelo.nos)} nós, "
                       f"{len(self.modelo.barras)} barras.")

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

    def assistente(self) -> None:
        dialogo = AssistenteDePortico(self)
        if dialogo.exec() != AssistenteDePortico.Accepted:
            return
        try:
            self.modelo = dialogo.modelo()
        except ErroDeModelo as erro:
            self._erro(erro)
            return
        self.resultados.clear()
        self.flambagem_atual = None
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
            modelo.validar()
        except ErroDeModelo as erro:
            self._erro(erro)
            return False
        self.modelo = modelo
        self.resultados.clear()
        self.flambagem_atual = None
        self._ultimo_relatorio_de_laje = None
        # o modelo é outro: a armadura guardada é do anterior
        self.armaduras.clear()
        self._envoltoria = None
        self._atualizar_casos()
        self._atualizar_niveis()
        self.redesenhar()
        self.registrar(f"Tabelas aplicadas: {len(modelo.nos)} nós, "
                       f"{len(modelo.barras)} barras.")
        return True

    def analisar(self) -> None:
        if not self.aplicar():
            return
        caso = self.escolha_caso.currentText()
        if not caso:
            self.registrar("Não há caso de carga para analisar.")
            return
        try:
            self.resultados[caso] = resolver(self.modelo, caso)
        except ErroDeModelo as erro:
            self._erro(erro)
            return
        self.escolha_vista.setCurrentText("Deformada")
        self.redesenhar()
        self.registrar(self.resultados[caso].resumo())

    def analisar_segunda_ordem(self) -> None:
        if not self.aplicar():
            return
        caso = self.escolha_caso.currentText()
        if not caso:
            self.registrar("Não há caso de carga para analisar.")
            return
        try:
            resultado = resolver_p_delta(self.modelo, caso)
        except ErroDeModelo as erro:
            self._erro(erro)
            return
        self.resultados[caso] = resultado
        self.escolha_vista.setCurrentText("Deformada")
        self.redesenhar()
        self.registrar(f"Segunda ordem de '{caso}': convergiu em "
                       f"{resultado.iteracoes} iterações.\n"
                       + resultado.resumo())

    def analisar_combinacoes(self) -> None:
        if not self.aplicar():
            return
        try:
            acoes = acoes_do_modelo(self.modelo)
            validar_acoes(self.modelo, acoes)
            combinacoes = combinacoes_elu(acoes) + combinacoes_els(acoes)
            self.resultados.update(
                resolver_combinacoes(self.modelo, combinacoes))
            env = envoltoria(self.modelo, {c.nome: self.resultados[c.nome]
                                           for c in combinacoes})
        except ErroDeModelo as erro:
            self._erro(erro)
            return

        self._atualizar_casos()
        linhas = [f"{len(combinacoes)} combinações resolvidas "
                  f"({sum(c.tipo == 'ELU' for c in combinacoes)} ELU, "
                  f"{sum(c.tipo.startswith('ELS') for c in combinacoes)} ELS).",
                  "Envoltória — extremos com esforços concomitantes:"]
        for nome, barra in list(env.items())[:12]:
            for componente in ("N", "My", "Mz"):
                linhas.append("  " + str(barra.extremo(componente, "min")))
        if len(env) > 12:
            linhas.append(f"  ... e mais {len(env) - 12} barras.")
        self.registrar("\n".join(linhas))

    def analisar_estabilidade(self) -> None:
        if not self.aplicar():
            return
        try:
            acoes = acoes_do_modelo(self.modelo)
            validar_acoes(self.modelo, acoes)
            combinacoes = combinacoes_elu(acoes)
        except ErroDeModelo as erro:
            self._erro(erro)
            return

        linhas = ["Estabilidade global — NBR 6118, itens 15.5.3 e 15.7.2"]
        pior = None
        for combinacao in combinacoes:
            try:
                caso = caso_efetivo(self.modelo, combinacao)
                self.modelo.casos[caso.nome] = caso
                g = gama_z(self.modelo, caso, resolver(self.modelo, caso.nome))
            except ErroDeModelo as erro:
                linhas.append(f"  {combinacao.nome:<10} sem γz: {erro}")
                continue
            linhas.append(
                f"  {combinacao.nome:<10} γz = {g.valor:.4f}  "
                f"{'nós fixos' if g.nos_fixos else 'nós móveis'}"
                + ("" if g.majoracao_valida else "   [acima de 1,3]"))
            if pior is None or g.valor > pior.valor:
                pior = g
        if pior is not None:
            linhas.append("")
            linhas.append(str(pior))
        self._atualizar_casos()
        self.registrar("\n".join(linhas))

    def analisar_flambagem(self) -> None:
        if not self.aplicar():
            return
        caso = self.escolha_caso.currentText()
        if not caso:
            self.registrar("Não há caso de carga para analisar.")
            return
        try:
            self.resultados.setdefault(caso, resolver(self.modelo, caso))
            self.flambagem_atual = flambagem(self.modelo, caso)
        except ErroDeModelo as erro:
            self._erro(erro)
            return
        self.escolha_vista.setCurrentText("Modo de flambagem")
        self.redesenhar()
        self.registrar(str(self.flambagem_atual))

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
        self.registrar("\n" + resumo(verificacoes))

    def dimensionar_vigas(self) -> None:
        """Reconhece as vigas contínuas, dimensiona e grava os desenhos.

        Pergunta a pasta antes de calcular: o desenho é o que o usuário leva
        embora, e obrigá-lo a repetir o cálculo por não ter escolhido onde
        gravar seria desperdício.
        """
        from ..continuidade import vigas_continuas
        from ..dimensionamento import resumo_de_vigas, verificar_vigas

        if not self.aplicar():
            return
        cadeias = [v for v in vigas_continuas(self.modelo)
                   if len(v.apoios) >= 2]
        if not cadeias:
            self.registrar("Nenhuma viga contínua com dois apoios de pilar.")
            return

        padrao = str(self.caminho.parent if self.caminho else Path.cwd())
        pasta = QFileDialog.getExistingDirectory(
            self, f"Onde gravar os desenhos das {len(cadeias)} vigas", padrao)
        if not pasta:
            return

        self.registrar(f"Dimensionando {len(cadeias)} vigas contínuas…")
        try:
            # A envoltória vai junto, e é o que faz a diferença: sem ela o
            # motor de Vigas dimensiona só para G e Q, e o efeito das ações
            # laterais — que no exemplo dá mais momento na viga que o peso
            # permanente — não chega à armadura. Com ela, a viga é conferida
            # contra o que o edifício inteiro exige.
            verificacoes = verificar_vigas(
                self.modelo, pasta_desenhos=pasta,
                envoltorias=self.envoltoria_atual())
        except ErroDeModelo as erro:
            self._erro(erro)
            return
        self.registrar("\n" + resumo_de_vigas(verificacoes))

    def dimensionar_lajes(self) -> None:
        """Dimensiona as lajes de cada pavimento e grava as plantas de armação.

        Vai por **pavimento**, e não painel a painel, porque a compatibilização
        dos momentos negativos do item 14.7.6.2 acontece entre painéis
        vizinhos: painel sozinho não tem com quem compatibilizar.
        """
        from ..dimensionamento import (cotas_com_laje, resumo_de_lajes,
                                       verificar_lajes)

        if not self.aplicar():
            return
        cotas = cotas_com_laje(self.modelo)
        if not cotas:
            self.registrar("O modelo não tem lajes.")
            return

        padrao = str(self.caminho.parent if self.caminho else Path.cwd())
        pasta = QFileDialog.getExistingDirectory(
            self, f"Onde gravar as plantas dos {len(cotas)} pavimentos", padrao)
        if not pasta:
            return

        self.registrar(f"Dimensionando as lajes de {len(cotas)} pavimentos…")
        try:
            verificacoes = verificar_lajes(self.modelo, pasta_desenhos=pasta)
        except ErroDeModelo as erro:
            self._erro(erro)
            return
        self.registrar("\n" + resumo_de_lajes(verificacoes))

    def envoltoria_atual(self, avisar: bool = True):
        """A envoltória das combinações últimas, calculada uma vez e guardada.

        Três ações precisam dela — dimensionar pilares, dimensionar vigas e a
        vista de Armadura —, e montá-la custa resolver todas as combinações do
        edifício. Guardá-la evita refazer isso a cada botão; ``aplicar`` a
        joga fora, porque aí o modelo é outro.
        """
        if self._envoltoria is not None:
            return self._envoltoria
        try:
            acoes = acoes_do_modelo(self.modelo)
            validar_acoes(self.modelo, acoes)
            resultados = resolver_combinacoes(self.modelo,
                                              combinacoes_elu(acoes))
            self._envoltoria = envoltoria(self.modelo, resultados)
            self.resultados.update(resultados)
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
            caso = self.escolha_caso.currentText()
            if not caso:
                self.registrar("Não há caso de carga para analisar.")
                return
            self.analisar()
            resultado = self._resultado_atual()
            if resultado is None:
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
                self.vista.desenhar_armadura(self.modelo,
                                             self.armadura_do_nivel(cota))
                return

            if vista == "Modo de flambagem":
                if self.flambagem_atual is None:
                    self.vista.desenhar_modelo(self.modelo)
                    return
                referencia = self.resultados[self.flambagem_atual.caso]
                self.vista.desenhar_modo(
                    self.modelo, referencia, self.flambagem_atual.modos[0],
                    self.flambagem_atual.fator_critico, 0, escala)
                return

            resultado = self._resultado_atual()
            if resultado is None:
                self.vista.desenhar_modelo(self.modelo)
                return

            if vista == "Deformada":
                self.vista.desenhar_deformada(resultado, escala)
            else:
                self.vista.desenhar_diagrama(resultado, vista, escala)
        except (ErroDeModelo, KeyError, ValueError) as erro:
            self._erro(erro)


def abrir_janela(modelo: Modelo | None = None) -> Janela:
    janela = Janela()
    if modelo is not None:
        janela.modelo = modelo
        janela._carregar_nas_tabelas()
    return janela
