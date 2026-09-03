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
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                               QFileDialog, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPlainTextEdit, QSplitter,
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

VISTAS = ["Modelo", "Deformada", *VISTAS_DE_ESFORCO, "Modo de flambagem"]


class Janela(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pórticos 3D — solver matricial de pórticos espaciais")
        self.resize(1500, 900)

        self.modelo = Modelo("portico")
        self.resultados: dict[str, Resultado] = {}
        self.flambagem_atual = None
        self.caminho: Path | None = None

        self.dados = PainelDeDados()
        self.vista = Vista3D()
        self.relatorio = QPlainTextEdit()
        self.relatorio.setReadOnly(True)
        self.relatorio.setMaximumHeight(220)

        self._montar_barra()
        self._montar_corpo()
        self._carregar_nas_tabelas()
        self.registrar("Pronto. Use o assistente para gerar um pórtico "
                       "regular, ou abra um modelo.")

    # -- construção --------------------------------------------------------

    def _acao(self, texto: str, gatilho, atalho: str = "") -> QAction:
        acao = QAction(texto, self)
        acao.triggered.connect(gatilho)
        if atalho:
            acao.setShortcut(atalho)
        return acao

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
        for texto, gatilho, atalho in (
                ("Aplicar tabelas", self.aplicar, "F5"),
                ("Analisar caso", self.analisar, "F9"),
                ("Segunda ordem", self.analisar_segunda_ordem, ""),
                ("Combinações NBR", self.analisar_combinacoes, ""),
                ("Estabilidade", self.analisar_estabilidade, ""),
                ("Flambagem", self.analisar_flambagem, "")):
            barra.addAction(self._acao(texto, gatilho, atalho))
        barra.addSeparator()
        for texto, gatilho, atalho in (
                ("Reações", self.mostrar_reacoes, "F8"),
                ("Salvar relatório", self.salvar_relatorio, ""),
                ("Limpar relatório", self.relatorio.clear, "")):
            barra.addAction(self._acao(texto, gatilho, atalho))

    def _montar_corpo(self) -> None:
        controles = QHBoxLayout()
        self.escolha_vista = QComboBox()
        self.escolha_vista.addItems(VISTAS)
        self.escolha_vista.currentTextChanged.connect(self.redesenhar)
        self.escolha_caso = QComboBox()
        self.escolha_caso.currentTextChanged.connect(self.redesenhar)
        self.escala = QDoubleSpinBox()
        self.escala.setRange(0.0, 1.0e6)
        self.escala.setDecimals(1)
        self.escala.setValue(0.0)
        self.escala.setSpecialValueText("automática")
        self.escala.valueChanged.connect(self.redesenhar)
        self.rotulos_nos = QCheckBox("nós")
        self.rotulos_barras = QCheckBox("barras")
        for c in (self.rotulos_nos, self.rotulos_barras):
            c.stateChanged.connect(self.redesenhar)

        controles.addWidget(QLabel("Vista:"))
        controles.addWidget(self.escolha_vista)
        controles.addWidget(QLabel("Caso:"))
        controles.addWidget(self.escolha_caso, 1)
        controles.addWidget(QLabel("Escala:"))
        controles.addWidget(self.escala)
        controles.addWidget(QLabel("Rótulos:"))
        controles.addWidget(self.rotulos_nos)
        controles.addWidget(self.rotulos_barras)

        direita = QWidget()
        leiaute = QVBoxLayout(direita)
        leiaute.setContentsMargins(6, 6, 6, 6)
        leiaute.addLayout(controles)
        leiaute.addWidget(self.vista, 1)

        divisor = QSplitter(Qt.Horizontal)
        divisor.addWidget(self.dados)
        divisor.addWidget(direita)
        divisor.setSizes([620, 880])

        vertical = QSplitter(Qt.Vertical)
        vertical.addWidget(divisor)
        vertical.addWidget(self.relatorio)
        vertical.setSizes([700, 200])

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
        self.vista.desenhar_modelo(self.modelo)

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
        self._atualizar_casos()
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
