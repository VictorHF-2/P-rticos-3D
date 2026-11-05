# -*- coding: utf-8 -*-
"""
tabelas.py
Entrada de dados por tabela, uma por entidade do modelo.

Duas decisões que fazem a tabela ser utilizável em vez de só existir:

* **Campo que aponta para outra coisa é lista suspensa, não texto livre.** O nó
  de uma barra, o material, a seção, o caso de uma carga — todos saem de uma
  lista montada na hora a partir do que já foi digitado nas outras abas. Assim
  o nome nunca sai errado, e o programa mostra o que existe em vez de esperar
  que alguém lembre.
* **A seção é definida pelos lados, e as propriedades saem sozinhas.** Ninguém
  deveria calcular b·h³/12 na mão para digitar aqui. Quem informa os lados
  recebe A, Iy, Iz, J e as áreas de cisalhamento calculadas e travadas contra
  edição; quem tem uma seção que não é retângulo nem círculo escolhe o tipo
  ``generica`` e digita as propriedades.

As tabelas não editam o modelo em cima da digitação: elas são lidas para um
modelo novo quando alguém pede. Assim uma linha pela metade nunca deixa o
modelo em estado inválido, e o erro aparece no relatório em vez de derrubar a
janela.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout,
                               QHeaderView, QPushButton, QStyledItemDelegate,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from ..core.concreto import ALFA_E, CLASSES, concreto, fck_da_classe
from ..core.modelo import ErroDeModelo, Secao
from ..core.nbr6118 import PSI

TIPOS_DE_SECAO = ("retangular", "circular", "generica")
TIPOS_DE_MATERIAL = ("concreto", "generico")
CLASSES_DE_CONCRETO = CLASSES
AGREGADOS = tuple(ALFA_E)
MODULOS = ("Ecs", "Eci")
NATUREZAS = ("permanente", "variavel")
SISTEMAS = ("local", "global")
TIPOS_DE_LAJE = ("macica", "trelicada")
ENCHIMENTOS = ("EPS", "Cerâmico")
TRELICAS = ("TR 8644", "TR 8645", "TR 12645", "TR 12646", "TR 16745",
            "TR 16746", "TR 20745", "TR 20756", "TR 25856", "TR 25858",
            "TR 30856", "TR 30858")
LIBERACOES = ("", "ry, rz", "rx, ry, rz", "u", "v, w", "ry", "rz")

# Colunas que o programa calcula quando o tipo não é genérico.
CALCULADAS = ("A", "Iy", "Iz", "J", "Asy", "Asz")
CALCULADAS_MATERIAL = ("E",)
CALCULADAS_LAJE = ("permanente", "acidental")


def para_float(texto: str, campo: str) -> float:
    """Converte aceitando vírgula decimal, que é como se digita aqui."""
    limpo = str(texto).strip().replace(",", ".")
    if not limpo:
        return 0.0
    try:
        return float(limpo)
    except ValueError:
        raise ErroDeModelo(f"'{texto}' não é um número em {campo}") from None


@dataclass(frozen=True)
class Coluna:
    titulo: str
    chave: str
    # "texto", "numero", "logico" ou "opcional" — este último distingue o
    # vazio do zero, distinção que importa na intensidade de fim da carga
    # trapezoidal: vazio quer dizer uniforme, zero quer dizer que a carga
    # morre na ponta.
    tipo: str = "texto"
    largura: int = 90
    ajuda: str = ""
    # Lista fixa de opções, ou o nome de outra tabela de onde tirar os nomes.
    lista: tuple[str, ...] = ()
    fonte: str = ""
    livre: bool = False          # lista suspensa que também aceita digitação


class DelegadoDeLista(QStyledItemDelegate):
    """Editor de célula em lista suspensa, montada no momento de abrir."""

    def __init__(self, opcoes, livre: bool = False, pai=None) -> None:
        super().__init__(pai)
        self._opcoes = opcoes
        self._livre = livre

    def createEditor(self, pai, opcao, indice):        # noqa: N802 - API Qt
        combo = QComboBox(pai)
        combo.setEditable(self._livre)
        combo.addItems([""] + list(self._opcoes()))
        return combo

    def setEditorData(self, editor, indice):           # noqa: N802 - API Qt
        texto = indice.data() or ""
        posicao = editor.findText(texto)
        if posicao >= 0:
            editor.setCurrentIndex(posicao)
        elif self._livre:
            editor.setEditText(texto)

    def setModelData(self, editor, modelo, indice):    # noqa: N802 - API Qt
        modelo.setData(indice, editor.currentText())


class TabelaDeRegistros(QWidget):
    """Tabela editável de linhas homogêneas, com acrescentar e remover."""

    alterado = Signal()
    #: Um dicionário por linha removida em ``remover_selecionadas`` (``chave
    #: da coluna -> texto``) — a linha inteira, não só o nome, porque uma
    #: cascata pode precisar de outra coluna (a barra apagada carrega
    #: ``no_i``/``no_j``, não só o próprio nome). Quem ouve decide se isso
    #: exige exclusão em cascata noutra tabela (ver
    #: ``PainelDeDados._remover_cargas_da_barra``).
    linhas_removidas = Signal(list)

    def __init__(self, colunas: list[Coluna], rotulo: str) -> None:
        super().__init__()
        self.colunas = colunas
        self.rotulo = rotulo
        self._indice = {c.chave: i for i, c in enumerate(colunas)}

        self.tabela = QTableWidget(0, len(colunas))
        self.tabela.setHorizontalHeaderLabels([c.titulo for c in colunas])
        self.tabela.verticalHeader().setDefaultSectionSize(22)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setAlternatingRowColors(True)
        for i, c in enumerate(colunas):
            self.tabela.setColumnWidth(i, c.largura)
            if c.ajuda:
                self.tabela.horizontalHeaderItem(i).setToolTip(c.ajuda)
        self.tabela.horizontalHeader().setSectionResizeMode(
            len(colunas) - 1, QHeaderView.Stretch)
        self.tabela.itemChanged.connect(self._ao_mudar)

        # Rótulo curto no botão, frase inteira no balão. "Acrescentar material"
        # e "Remover selecionadas" somavam 508 px de largura mínima — mais que
        # a própria tabela, que precisa de 70 —, e eram eles que impediam o
        # painel de encolher numa tela pequena. A aba já diz de que registro se
        # trata, de modo que o verbo sozinho basta.
        acrescentar = QPushButton("Acrescentar")
        acrescentar.setToolTip(f"Acrescentar {rotulo}")
        acrescentar.clicked.connect(self.acrescentar_linha)
        remover = QPushButton("Remover")
        remover.setToolTip("Remover as linhas selecionadas")
        remover.clicked.connect(self.remover_selecionadas)

        botoes = QHBoxLayout()
        botoes.addWidget(acrescentar)
        botoes.addWidget(remover)
        botoes.addStretch(1)

        leiaute = QVBoxLayout(self)
        leiaute.setContentsMargins(6, 6, 6, 6)
        leiaute.addWidget(self.tabela)
        leiaute.addLayout(botoes)

    # -- listas suspensas --------------------------------------------------

    def instalar_listas(self, fontes: dict[str, callable]) -> None:
        """Liga cada coluna de referência à lista que a alimenta."""
        for i, coluna in enumerate(self.colunas):
            if coluna.lista:
                opcoes = (lambda c=coluna: c.lista)
            elif coluna.fonte and coluna.fonte in fontes:
                opcoes = fontes[coluna.fonte]
            else:
                continue
            self.tabela.setItemDelegateForColumn(
                i, DelegadoDeLista(opcoes, coluna.livre, self.tabela))

    def valores(self, chave: str) -> list[str]:
        """Os valores não vazios de uma coluna, para alimentar outras listas."""
        coluna = self._indice.get(chave)
        if coluna is None:
            return []
        saida = []
        for linha in range(self.tabela.rowCount()):
            item = self.tabela.item(linha, coluna)
            texto = "" if item is None else item.text().strip()
            if texto:
                saida.append(texto)
        return saida

    # -- conteúdo ----------------------------------------------------------

    def _celula(self, coluna: Coluna, valor) -> QTableWidgetItem:
        item = QTableWidgetItem()
        if coluna.tipo == "logico":
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
                          | Qt.ItemIsSelectable)
            item.setCheckState(Qt.Checked if valor else Qt.Unchecked)
            return item

        if coluna.tipo in ("numero", "opcional"):
            # ``valor`` chega como texto na linha recém-criada e como número
            # ao carregar do modelo; formatar só o que é número evita o erro
            # de aplicar formato numérico a texto vazio.
            item.setText("" if valor is None or valor == ""
                         else f"{float(valor):g}")
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        else:
            item.setText("" if valor is None else str(valor))
        return item

    def carregar(self, registros: list[dict]) -> None:
        self.tabela.blockSignals(True)
        self.tabela.setRowCount(len(registros))
        for linha, registro in enumerate(registros):
            for i, coluna in enumerate(self.colunas):
                self.tabela.setItem(linha, i,
                                    self._celula(coluna, registro.get(coluna.chave)))
        self.tabela.blockSignals(False)
        self.alterado.emit()

    def registros(self) -> list[dict]:
        saida = []
        for linha in range(self.tabela.rowCount()):
            registro = {}
            vazia = True
            for i, coluna in enumerate(self.colunas):
                item = self.tabela.item(linha, i)
                if coluna.tipo == "logico":
                    registro[coluna.chave] = (
                        item is not None and item.checkState() == Qt.Checked)
                    continue
                texto = "" if item is None else item.text().strip()
                if texto:
                    vazia = False
                onde = (f"{self.rotulo}, linha {linha + 1}, "
                        f"coluna {coluna.titulo}")
                if coluna.tipo == "numero":
                    registro[coluna.chave] = para_float(texto, onde)
                elif coluna.tipo == "opcional":
                    registro[coluna.chave] = (para_float(texto, onde)
                                              if texto else None)
                else:
                    registro[coluna.chave] = texto
            if not vazia:
                saida.append(registro)
        return saida

    def _ao_mudar(self, item: QTableWidgetItem) -> None:
        self.alterado.emit()

    def acrescentar_linha(self) -> None:
        linha = self.tabela.rowCount()
        self.tabela.blockSignals(True)
        self.tabela.insertRow(linha)
        for i, coluna in enumerate(self.colunas):
            padrao = False if coluna.tipo == "logico" else None
            if coluna.lista and not coluna.livre:
                padrao = coluna.lista[0]
            self.tabela.setItem(linha, i, self._celula(coluna, padrao))
        self.tabela.blockSignals(False)
        self.tabela.setCurrentCell(linha, 0)
        self.alterado.emit()

    def remover_selecionadas(self) -> None:
        linhas = sorted({i.row() for i in self.tabela.selectedIndexes()},
                        reverse=True)
        removidos = []
        for linha in linhas:
            registro = {}
            for i, coluna in enumerate(self.colunas):
                item = self.tabela.item(linha, i)
                registro[coluna.chave] = ("" if item is None
                                          else item.text().strip())
            if registro.get(self.colunas[0].chave):
                removidos.append(registro)
            self.tabela.removeRow(linha)
        if linhas:
            self.alterado.emit()
        if removidos:
            self.linhas_removidas.emit(removidos)

    def remover_onde(self, chave: str, valores: set[str]) -> int:
        """Remove as linhas cujo campo ``chave`` está em ``valores``.

        É a exclusão em cascata: uma barra apagada não pode deixar uma carga
        distribuída apontando para um nome que não existe mais — sem isto,
        "Aplicar tabelas" só reprovava o modelo com um erro de referência, e
        quem apagou a barra tinha de caçar a carga órfã na mão.
        """
        coluna = self._indice.get(chave)
        if coluna is None or not valores:
            return 0
        removidas = 0
        for linha in reversed(range(self.tabela.rowCount())):
            item = self.tabela.item(linha, coluna)
            if item is not None and item.text().strip() in valores:
                self.tabela.removeRow(linha)
                removidas += 1
        if removidas:
            self.alterado.emit()
        return removidas


# ---------------------------------------------------------------------------
# As doze tabelas do modelo
# ---------------------------------------------------------------------------

COLUNAS = {
    "materiais": [
        Coluna("Nome", "nome", "texto", 110),
        Coluna("Tipo", "tipo", "texto", 95,
               "Concreto tem o módulo calculado do fck; genérico espera o E",
               lista=TIPOS_DE_MATERIAL),
        Coluna("Classe", "classe", "texto", 80,
               "Classe do concreto, de C20 a C90", lista=CLASSES_DE_CONCRETO,
               livre=True),
        Coluna("Agregado", "agregado", "texto", 130,
               "O agregado graúdo define o α_E da fórmula do módulo",
               lista=AGREGADOS),
        Coluna("Módulo", "modulo", "texto", 75,
               "Ecs é o secante, usado na análise estrutural; Eci é o inicial",
               lista=MODULOS),
        Coluna("E (kN/m²)", "E", "numero", 110),
        Coluna("Poisson", "poisson", "numero", 70),
        Coluna("γ (kN/m³)", "peso_especifico", "numero", 90,
               "Peso específico; zero significa sem peso próprio"),
    ],
    "secoes": [
        Coluna("Nome", "nome", "texto", 110),
        Coluna("Tipo", "tipo", "texto", 100,
               "Retangular e circular têm as propriedades calculadas; "
               "genérica espera que você as informe",
               lista=TIPOS_DE_SECAO),
        Coluna("b ou ⌀ (m)", "b", "numero", 90,
               "Lado na direção local y, ou diâmetro na seção circular"),
        Coluna("h (m)", "h", "numero", 80,
               "Lado na direção local z. A rotação da barra gira esses eixos"),
        Coluna("Cortante", "cortante", "logico", 75,
               "Calcula as áreas de cisalhamento e liga a formulação de "
               "Timoshenko"),
        Coluna("A (m²)", "A", "numero"),
        Coluna("Iy (m⁴)", "Iy", "numero"),
        Coluna("Iz (m⁴)", "Iz", "numero"),
        Coluna("J (m⁴)", "J", "numero"),
        Coluna("Asy (m²)", "Asy", "numero", 90),
        Coluna("Asz (m²)", "Asz", "numero", 90),
    ],
    "nos": [
        Coluna("Nome", "nome", "texto", 90),
        Coluna("X (m)", "x", "numero"),
        Coluna("Y (m)", "y", "numero"),
        Coluna("Z (m)", "z", "numero"),
    ],
    "barras": [
        Coluna("Nome", "nome", "texto", 90),
        Coluna("Nó i", "no_i", "texto", 80, fonte="nos"),
        Coluna("Nó j", "no_j", "texto", 80, fonte="nos"),
        Coluna("Material", "material", "texto", 100, fonte="materiais"),
        Coluna("Seção", "secao", "texto", 100, fonte="secoes"),
        Coluna("Rotação (°)", "rotacao", "numero", 90,
               "Giro dos eixos locais y e z em torno do eixo da barra"),
        Coluna("Liberações i", "liberacoes_i", "texto", 115,
               "Graus locais soltos no nó inicial: u, v, w, rx, ry, rz",
               lista=LIBERACOES, livre=True),
        Coluna("Liberações j", "liberacoes_j", "texto", 115,
               "Graus locais soltos no nó final: u, v, w, rx, ry, rz",
               lista=LIBERACOES, livre=True),
        Coluna("Trecho i (m)", "offset_i", "numero", 95,
               "Comprimento do trecho rígido junto ao nó inicial"),
        Coluna("Trecho j (m)", "offset_j", "numero", 95,
               "Comprimento do trecho rígido junto ao nó final"),
    ],
    "apoios": [
        Coluna("Nó", "no", "texto", 100, fonte="nos"),
        Coluna("ux", "ux", "logico", 45), Coluna("uy", "uy", "logico", 45),
        Coluna("uz", "uz", "logico", 45), Coluna("rx", "rx", "logico", 45),
        Coluna("ry", "ry", "logico", 45), Coluna("rz", "rz", "logico", 45),
    ],
    "molas": [
        Coluna("Nó", "no", "texto", 100, fonte="nos"),
        Coluna("kx", "kx", "numero"), Coluna("ky", "ky", "numero"),
        Coluna("kz", "kz", "numero"), Coluna("krx", "krx", "numero"),
        Coluna("kry", "kry", "numero"), Coluna("krz", "krz", "numero"),
    ],
    "lajes": [
        Coluna("Nome", "nome", "texto", 100),
        Coluna("Canto A", "no_a", "texto", 95, fonte="nos",
               ajuda="Um canto do painel"),
        Coluna("Canto oposto", "no_c", "texto", 105, fonte="nos",
               ajuda="O canto diagonalmente oposto ao primeiro"),
        Coluna("Espessura (m)", "espessura", "numero", 105,
               "O peso próprio da laje sai daqui, pelo γ do material"),
        Coluna("Material", "material", "texto", 105, fonte="materiais"),
        Coluna("Tipo de carga", "tipo_carga", "texto", 130,
               "Escolha um tipo da aba 'Carga nas lajes' para preencher "
               "Revestimento e Acidental sozinhos; em branco, digite os "
               "dois à mão",
               fonte="cargas_lajes", livre=True),
        Coluna("Revestimento (kN/m²)", "permanente", "numero", 150,
               "Permanente além do peso próprio: contrapiso, forro, piso. "
               "Calculado quando há Tipo de carga"),
        Coluna("Acidental (kN/m²)", "acidental", "numero", 140,
               "Vai para o caso variável, não para o permanente. "
               "Calculado quando há Tipo de carga"),
        Coluna("Laje", "tipo", "texto", 90, lista=TIPOS_DE_LAJE,
               ajuda="Maciça, ou treliçada (vigotas com treliça, armada numa "
                     "direção só)"),
        Coluna("Nervuras", "direcao", "texto", 75, lista=("x", "y"),
               ajuda="Treliçada: direção das nervuras. A laje apoia só nas "
                     "duas vigas perpendiculares a elas"),
        Coluna("Treliça", "trelica", "texto", 95, lista=TRELICAS,
               ajuda="Treliçada: a treliça eletrossoldada (NBR 14862)"),
        Coluna("Enchimento", "enchimento", "texto", 95, lista=ENCHIMENTOS,
               ajuda="Treliçada: material do bloco de enchimento"),
        Coluna("h enchimento (m)", "altura_enchimento", "numero", 115,
               "Treliçada: altura do bloco de enchimento"),
        Coluna("Capa (m)", "capa", "numero", 80,
               "Treliçada: capa de concreto sobre os blocos (≥ 4 cm, "
               "13.2.4.2)"),
        Coluna("Bloco (m)", "largura_bloco", "numero", 80,
               "Treliçada: largura do bloco de enchimento (Le)"),
        Coluna("Base vigota (m)", "base_vigota", "numero", 110,
               "Treliçada: largura da base da vigota pré-moldada"),
        Coluna("Balanço (m)", "balanco", "numero", 90,
               "Laje em balanço: do eixo da viga de apoio até a borda "
               "livre. Aí Canto A e Canto oposto são as pontas do lado "
               "apoiado. Zero = laje apoiada nas quatro vigas"),
        Coluna("Sentido", "sentido", "texto", 75,
               lista=("", "+x", "-x", "+y", "-y"),
               ajuda="Laje em balanço: para onde ela avança a partir do "
                     "lado apoiado"),
    ],
    "cargas_lajes": [
        Coluna("Nome", "nome", "texto", 120,
               "Ex.: corredor, biblioteca, lavanderia, dormitório"),
        Coluna("Descrição", "descricao", "texto", 220,
               "Nota livre; não entra em nenhuma conta"),
        Coluna("Revestimento (kN/m²)", "permanente", "numero", 150,
               "Permanente além do peso próprio, para toda laje deste tipo"),
        Coluna("Acidental (kN/m²)", "acidental", "numero", 140,
               "Vai para o caso variável, para toda laje deste tipo"),
    ],
    "casos": [
        Coluna("Nome", "nome", "texto", 130),
        Coluna("Natureza", "natureza", "texto", 110, lista=NATUREZAS),
        Coluna("Categoria", "categoria", "texto", 130,
               "Linha da Tabela 11.2 da NBR 6118, só para ação variável",
               lista=tuple(PSI)),
        Coluna("Grupo", "grupo", "texto", 110,
               "Casos do mesmo grupo nunca entram juntos numa combinação",
               livre=True),
    ],
    "nodais": [
        Coluna("Caso", "caso", "texto", 120, fonte="casos"),
        Coluna("Nó", "no", "texto", 90, fonte="nos"),
        Coluna("Fx", "fx", "numero", 80), Coluna("Fy", "fy", "numero", 80),
        Coluna("Fz", "fz", "numero", 80), Coluna("Mx", "mx", "numero", 80),
        Coluna("My", "my", "numero", 80), Coluna("Mz", "mz", "numero", 80),
    ],
    "distribuidas": [
        Coluna("Caso", "caso", "texto", 120, fonte="casos"),
        Coluna("Barra", "barra", "texto", 90, fonte="barras"),
        Coluna("qx", "qx", "numero", 75), Coluna("qy", "qy", "numero", 75),
        Coluna("qz", "qz", "numero", 75),
        Coluna("Sistema", "sistema", "texto", 80, lista=SISTEMAS),
        Coluna("Início", "inicio", "numero", 70, "Fração do vão, de 0 a 1"),
        Coluna("Fim", "fim", "numero", 70, "Fração do vão, de 0 a 1"),
        Coluna("qx fim", "qx_fim", "opcional", 75,
               "Vazio: carga uniforme. Zero: carga que morre na ponta"),
        Coluna("qy fim", "qy_fim", "opcional", 75,
               "Vazio: carga uniforme. Zero: carga que morre na ponta"),
        Coluna("qz fim", "qz_fim", "opcional", 75,
               "Vazio: carga uniforme. Zero: carga que morre na ponta"),
        Coluna("Origem", "origem", "texto", 90,
               "De onde a carga veio quando não foi digitada: 'laje:L1' é o "
               "quinhão da laje L1. A laje em grelha tira estas cargas das "
               "vigas e as devolve à laje"),
    ],
    "recalques": [
        Coluna("Caso", "caso", "texto", 120, fonte="casos"),
        Coluna("Nó", "no", "texto", 90, fonte="nos"),
        Coluna("ux", "ux", "numero"), Coluna("uy", "uy", "numero"),
        Coluna("uz", "uz", "numero"), Coluna("rx", "rx", "numero"),
        Coluna("ry", "ry", "numero"), Coluna("rz", "rz", "numero"),
    ],
}

ROTULOS = {
    "materiais": ("Materiais", "material"),
    "secoes": ("Seções", "seção"),
    "nos": ("Nós", "nó"),
    "barras": ("Barras", "barra"),
    "apoios": ("Apoios", "apoio"),
    "molas": ("Molas", "mola"),
    "lajes": ("Lajes", "laje"),
    "cargas_lajes": ("Carga nas lajes", "tipo de carga"),
    "casos": ("Casos de carga", "caso"),
    "nodais": ("Cargas nodais", "carga"),
    "distribuidas": ("Cargas distribuídas", "carga"),
    "recalques": ("Recalques", "recalque"),
}

# De onde cada lista suspensa tira os nomes.
CHAVE_DO_NOME = {"nos": "nome", "barras": "nome", "materiais": "nome",
                 "secoes": "nome", "casos": "nome", "cargas_lajes": "nome"}

#: As doze tabelas agrupadas em três abas principais, cada uma com as suas
#: sub-abas. Antes eram onze abas soltas lado a lado — e onze é congestionado
#: em qualquer resolução, o texto do rótulo já começa a truncar por volta da
#: sétima. Agrupado por assunto, cada aba principal cabe com folga, e o
#: agrupamento segue a ordem de preenchimento de um modelo novo: primeiro o
#: que não depende de geometria (materiais, seções, casos, os tipos de carga
#: de laje), depois a geometria em si, depois as cargas que a usam.
GRUPOS = [
    ("Inicial", ("materiais", "secoes", "casos", "cargas_lajes")),
    ("Geometria", ("nos", "barras", "apoios", "molas", "lajes")),
    ("Cargas", ("nodais", "distribuidas", "recalques")),
]


class PainelDeDados(QTabWidget):
    """As doze tabelas, agrupadas em três abas e ligadas pelas listas suspensas.

    O agrupamento é só de apresentação — ``self.tabelas`` continua um
    dicionário achatado por chave, igual antes, e é dali que o resto do
    programa lê e escreve. Quem muda é só onde a tabela aparece: dentro de
    ``Inicial``, ``Geometria`` ou ``Cargas``, e não mais as doze lado a lado.
    """

    alterado = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.tabelas: dict[str, TabelaDeRegistros] = {}
        #: a sub-aba de cada grupo, para quem quiser abrir uma delas por
        #: código (o assistente, por exemplo, pode querer pousar em "Cargas")
        self.subabas: dict[str, QTabWidget] = {}
        for titulo_grupo, chaves in GRUPOS:
            sub = QTabWidget()
            for chave in chaves:
                titulo, singular = ROTULOS[chave]
                tabela = TabelaDeRegistros(COLUNAS[chave], singular)
                tabela.alterado.connect(self.alterado.emit)
                self.tabelas[chave] = tabela
                sub.addTab(tabela, titulo)
            self.subabas[titulo_grupo] = sub
            self.addTab(sub, titulo_grupo)

        fontes = {chave: (lambda c=chave: self.tabelas[c].valores(
            CHAVE_DO_NOME[c])) for chave in CHAVE_DO_NOME}
        for tabela in self.tabelas.values():
            tabela.instalar_listas(fontes)

        self.tabelas["secoes"].tabela.itemChanged.connect(self._recalcular_secao)
        self.tabelas["materiais"].tabela.itemChanged.connect(
            self._recalcular_material)
        self.tabelas["lajes"].tabela.itemChanged.connect(
            self._recalcular_carga_de_laje)
        self.tabelas["barras"].linhas_removidas.connect(
            self._remover_cargas_da_barra)

    # -- exclusão em cascata -------------------------------------------------

    def _remover_cargas_da_barra(self, registros: list[dict]) -> None:
        """Apagar uma barra apaga com ela as cargas distribuídas que a
        referenciam — senão "Aplicar tabelas" reprovaria o modelo com uma
        carga apontando para uma barra que não existe mais. Depois, verifica
        se algum dos dois nós da barra ficou sem barra nenhuma tocando nele
        (ver ``_remover_nos_orfaos``)."""
        nomes = {r["nome"] for r in registros if r.get("nome")}
        if nomes:
            self.tabelas["distribuidas"].remover_onde("barra", nomes)
        self._remover_nos_orfaos(registros)

    def _remover_nos_orfaos(self, barras_removidas: list[dict]) -> None:
        """Um nó que só a barra apagada tocava deixa de fazer sentido no
        modelo, e desaparece com ela — junto com o apoio, a mola, o recalque
        e a carga nodal que ele tivesse. O exemplo que motivou isto: apagar o
        pilar da base de um pórtico gerado pelo assistente apaga, com ele, o
        engaste e as cargas daquele nó — mas o nó do **topo** do pilar fica,
        porque a viga continua chegando nele.

        Um nó que uma laje ainda referencia (canto do painel) **não** é
        considerado órfão, mesmo sem barra nenhuma — apagá-lo quebraria a
        laje, e isso exigiria decidir o que fazer com ela, o que não foi
        pedido.
        """
        candidatos = {r[campo] for r in barras_removidas
                     for campo in ("no_i", "no_j") if r.get(campo)}
        if not candidatos:
            return

        barras = self.tabelas["barras"]
        tocados = set(barras.valores("no_i")) | set(barras.valores("no_j"))
        lajes = self.tabelas["lajes"]
        referenciados_por_laje = (set(lajes.valores("no_a"))
                                  | set(lajes.valores("no_c")))
        orfaos = candidatos - tocados - referenciados_por_laje
        if not orfaos:
            return

        self.tabelas["nos"].remover_onde("nome", orfaos)
        for chave in ("apoios", "molas", "recalques", "nodais"):
            self.tabelas[chave].remover_onde("no", orfaos)

    # -- materiais ---------------------------------------------------------

    def _recalcular_material(self, item: QTableWidgetItem) -> None:
        """Refaz o módulo quando a classe, o agregado ou o módulo mudam.

        Só o **E** é calculado e travado. O coeficiente de Poisson e o peso
        específico ficam editáveis: a norma sugere 0,2 e 25 kN/m³, mas peso
        específico é justamente onde se costuma embutir outra coisa — nos
        modelos do MASTAN desta mesma pasta ele está em 35 —, e travar isso
        atrapalharia mais do que ajuda. Eles são preenchidos com o valor da
        norma só quando estão em branco.
        """
        tabela = self.tabelas["materiais"]
        indice = tabela._indice
        if item.column() not in (indice["tipo"], indice["classe"],
                                 indice["agregado"], indice["modulo"]):
            return

        linha = item.row()

        def texto(chave: str) -> str:
            celula = tabela.tabela.item(linha, indice[chave])
            return "" if celula is None else celula.text().strip()

        if texto("tipo") != "concreto":
            self._travar(tabela, linha, CALCULADAS_MATERIAL, False)
            return

        try:
            material = concreto(texto("nome") or "concreto",
                                fck_da_classe(texto("classe")),
                                texto("agregado") or None,
                                texto("modulo") or "Ecs")
        except ErroDeModelo:
            return                    # linha ainda incompleta

        tabela.tabela.blockSignals(True)
        self._escrever(tabela, linha, "E", f"{material.E:g}")
        for chave, padrao in (("poisson", material.poisson),
                              ("peso_especifico", material.peso_especifico)):
            if not texto(chave):
                self._escrever(tabela, linha, chave, f"{padrao:g}")
        tabela.tabela.blockSignals(False)
        self._travar(tabela, linha, CALCULADAS_MATERIAL, True)

    @staticmethod
    def _escrever(tabela: TabelaDeRegistros, linha: int, chave: str,
                  valor: str) -> None:
        celula = tabela.tabela.item(linha, tabela._indice[chave])
        if celula is None:
            celula = QTableWidgetItem()
            tabela.tabela.setItem(linha, tabela._indice[chave], celula)
        celula.setText(valor)
        celula.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    @staticmethod
    def _travar(tabela: TabelaDeRegistros, linha: int,
                colunas: tuple[str, ...], travar: bool) -> None:
        tabela.tabela.blockSignals(True)
        for chave in colunas:
            celula = tabela.tabela.item(linha, tabela._indice[chave])
            if celula is None:
                continue
            marcas = celula.flags()
            if travar:
                celula.setFlags(marcas & ~Qt.ItemIsEditable)
                celula.setForeground(Qt.darkGray)
                celula.setToolTip("Calculado; edite a origem para mudar")
            else:
                celula.setFlags(marcas | Qt.ItemIsEditable)
                celula.setData(Qt.ForegroundRole, None)
                celula.setToolTip("")
        tabela.tabela.blockSignals(False)

    # -- carga nas lajes -----------------------------------------------------

    def _recalcular_carga_de_laje(self, item: QTableWidgetItem) -> None:
        """Preenche Revestimento/Acidental quando o Tipo de carga é escolhido.

        A mesma regra da seção calculada: o **tipo** é a fonte, não um valor
        inicial que a laje possa desviar depois. Escolhido um tipo que existe
        na aba "Carga nas lajes", as duas colunas ficam travadas com o valor
        dele; em branco, ou com um nome que não bate com tipo nenhum, elas
        voltam a aceitar digitação livre.
        """
        tabela = self.tabelas["lajes"]
        indice = tabela._indice
        if item.column() != indice["tipo_carga"]:
            return

        linha = item.row()
        nome_tipo = item.text().strip()

        tipos = self.tabelas["cargas_lajes"]
        i_tipos = tipos._indice
        encontrado = None
        for r in range(tipos.tabela.rowCount()):
            celula = tipos.tabela.item(r, i_tipos["nome"])
            if celula is not None and celula.text().strip() == nome_tipo:
                encontrado = r
                break

        if not nome_tipo or encontrado is None:
            self._travar(tabela, linha, CALCULADAS_LAJE, False)
            return

        def valor_do_tipo(chave: str) -> str:
            celula = tipos.tabela.item(encontrado, i_tipos[chave])
            return "" if celula is None else celula.text().strip() or "0"

        tabela.tabela.blockSignals(True)
        for chave in CALCULADAS_LAJE:
            self._escrever(tabela, linha, chave, valor_do_tipo(chave))
        tabela.tabela.blockSignals(False)
        self._travar(tabela, linha, CALCULADAS_LAJE, True)

    # -- seções ------------------------------------------------------------

    def _recalcular_secao(self, item: QTableWidgetItem) -> None:
        """Refaz as propriedades da linha quando o tipo ou os lados mudam.

        Fica ligado à edição, e não a um botão, porque a propriedade calculada
        que não acompanha o lado digitado é pior do que não ter cálculo
        nenhum: o número na tela deixaria de descrever a seção sem avisar.
        """
        tabela = self.tabelas["secoes"]
        indice = tabela._indice
        if item.column() not in (indice["tipo"], indice["b"], indice["h"],
                                 indice["cortante"]):
            return

        linha = item.row()

        def texto(chave: str) -> str:
            celula = tabela.tabela.item(linha, indice[chave])
            return "" if celula is None else celula.text().strip()

        tipo = texto("tipo")
        if tipo not in ("retangular", "circular"):
            self._travar_calculadas(linha, False)
            return

        try:
            b = para_float(texto("b"), "seção, lado b")
            h = para_float(texto("h"), "seção, lado h")
            marcada = tabela.tabela.item(linha, indice["cortante"])
            cortante = (marcada is not None
                        and marcada.checkState() == Qt.Checked)
            secao = Secao.criar(texto("nome") or "seção", tipo, b,
                                h if tipo == "retangular" else b, cortante)
        except ErroDeModelo:
            return                    # linha ainda incompleta; nada a fazer

        tabela.tabela.blockSignals(True)
        for chave in CALCULADAS:
            self._escrever(tabela, linha, chave, f"{getattr(secao, chave):g}")
        tabela.tabela.blockSignals(False)
        self._travar(tabela, linha, CALCULADAS, True)

    def _travar_calculadas(self, linha: int, travar: bool) -> None:
        self._travar(self.tabelas["secoes"], linha, CALCULADAS, travar)

    def recalcular_todas_as_secoes(self) -> None:
        """Refaz as linhas calculadas depois de carregar um modelo.

        ``carregar`` silencia os sinais da tabela para não recalcular a cada
        célula preenchida, de modo que as linhas chegam sem travar; é aqui que
        elas são acertadas.
        """
        for chave, coluna, refazer in (("secoes", "tipo", self._recalcular_secao),
                                       ("materiais", "tipo",
                                        self._recalcular_material),
                                       ("lajes", "tipo_carga",
                                        self._recalcular_carga_de_laje)):
            tabela = self.tabelas[chave]
            for linha in range(tabela.tabela.rowCount()):
                item = tabela.tabela.item(linha, tabela._indice[coluna])
                if item is not None:
                    refazer(item)
