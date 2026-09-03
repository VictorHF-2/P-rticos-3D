# -*- coding: utf-8 -*-
"""
assistente.py
Gerador de pórtico regular a partir dos vãos e dos pés-direitos.

É o que resolve o caso comum. Um edifício de quatro pavimentos com seis
prumadas tem umas cem barras, e digitá-las uma a uma seria absurdo; aqui isso
sai de três listas de números. O ajuste fino do que foi gerado é que fica nas
tabelas.

Os nomes são posicionais — ``N2.3.1`` é o nó da segunda prumada em X, terceira
em Y, no primeiro pavimento — para que a tabela continue legível depois de
gerada, e para que dê para achar uma barra pelo nome sem consultar o desenho.
"""

from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QLabel, QLineEdit, QVBoxLayout)

from ..core.concreto import fck_da_classe

from ..core.cargas import peso_proprio
from ..core.concreto import ALFA_E, CLASSES, concreto
from ..core.lajes import aplicar_lajes
from ..core.modelo import ErroDeModelo, Modelo, Secao


def ler_lista(texto: str, campo: str) -> list[float]:
    """Lê '6, 6, 5' como três vãos consecutivos."""
    valores = []
    for parte in str(texto).replace(";", ",").split(","):
        parte = parte.strip().replace(",", ".") if parte.strip() else ""
        if not parte:
            continue
        try:
            valor = float(parte)
        except ValueError:
            raise ErroDeModelo(f"'{parte}' não é um número em {campo}") from None
        if valor <= 0.0:
            raise ErroDeModelo(f"{campo}: os valores têm de ser positivos")
        valores.append(valor)
    if not valores:
        raise ErroDeModelo(f"{campo} está vazio")
    return valores


def acumular(vaos: list[float]) -> list[float]:
    posicoes, total = [0.0], 0.0
    for v in vaos:
        total += v
        posicoes.append(total)
    return posicoes


def gerar_portico(vaos_x: list[float], vaos_y: list[float],
                  pes_direitos: list[float], pilar: tuple[float, float],
                  viga: tuple[float, float], fck: float,
                  agregado: str | None = None, modulo: str = "Ecs",
                  peso_especifico: float = 25.0, espessura_laje: float = 0.0,
                  revestimento: float = 0.0, acidental: float = 0.0,
                  parede: float = 0.0, vento: float = 0.0,
                  peso_proprio_barras: bool = True,
                  nome: str = "portico") -> Modelo:
    """Monta o pórtico regular completo, com lajes, apoios e casos de carga.

    Cada célula da grelha vira um painel de laje, e é ele que carrega as vigas
    — por área de influência, o que dá carga triangular no lado menor e
    trapezoidal no maior. A carga direta nas vigas fica sendo a **parede** que
    se apoia nelas, que é o que de fato é linear.
    """
    m = Modelo(nome)
    material = concreto("concreto", fck, agregado, modulo, peso_especifico)
    m.materiais[material.nome] = material
    m.add_secao(Secao.retangular("pilar", pilar[0], pilar[1]))
    m.add_secao(Secao.retangular("viga", viga[0], viga[1]))

    xs, ys, zs = acumular(vaos_x), acumular(vaos_y), acumular(pes_direitos)

    def no(i: int, j: int, k: int) -> str:
        return f"N{i + 1}.{j + 1}.{k}"

    for k, z in enumerate(zs):
        for i, x in enumerate(xs):
            for j, y in enumerate(ys):
                m.add_no(no(i, j, k), x, y, z)

    for k in range(len(zs) - 1):
        for i in range(len(xs)):
            for j in range(len(ys)):
                m.add_barra(f"P{i + 1}.{j + 1}.{k + 1}", no(i, j, k),
                            no(i, j, k + 1), "concreto", "pilar")

    for k in range(1, len(zs)):
        for j in range(len(ys)):
            for i in range(len(xs) - 1):
                m.add_barra(f"VX{i + 1}.{j + 1}.{k}", no(i, j, k),
                            no(i + 1, j, k), "concreto", "viga")
        for i in range(len(xs)):
            for j in range(len(ys) - 1):
                m.add_barra(f"VY{i + 1}.{j + 1}.{k}", no(i, j, k),
                            no(i, j + 1, k), "concreto", "viga")

    for i in range(len(xs)):
        for j in range(len(ys)):
            m.apoiar(no(i, j, 0))

    for k in range(1, len(zs)):
        for i in range(len(xs) - 1):
            for j in range(len(ys) - 1):
                m.add_laje(f"L{i + 1}.{j + 1}.{k}", no(i, j, k),
                           no(i + 1, j + 1, k), espessura_laje, "concreto",
                           revestimento, acidental)

    caso_permanente = m.add_caso("G", "permanente")
    # O peso das barras e o da laje são coisas separadas: o primeiro sai da
    # seção, o segundo da espessura. Desligar um não pode desligar o outro.
    if peso_proprio_barras and peso_especifico > 0.0:
        peso_proprio(m, caso_permanente)
    if parede > 0.0:
        for nome_barra in list(m.barras):
            if nome_barra.startswith("V"):
                caso_permanente.distribuida(nome_barra, qz=-parede,
                                            sistema="global")

    caso_acidental = m.add_caso("Q", "variavel", "residencial")
    if m.lajes:
        aplicar_lajes(m, caso_permanente, caso_acidental)

    if vento > 0.0:
        # Força horizontal por pavimento, repartida entre as prumadas de
        # barlavento. É um vento simplificado, para o modelo já nascer
        # analisável; o vento da NBR 6123 entra pelo menu de cargas.
        for direcao, eixo in (("VX", "x"), ("VY", "y")):
            caso = m.add_caso(direcao, "variavel", "vento", grupo="vento")
            for k in range(1, len(zs)):
                if eixo == "x":
                    alvos = [no(0, j, k) for j in range(len(ys))]
                else:
                    alvos = [no(i, 0, k) for i in range(len(xs))]
                quinhao = vento / len(alvos)
                for alvo in alvos:
                    if eixo == "x":
                        caso.nodal(alvo, fx=quinhao)
                    else:
                        caso.nodal(alvo, fy=quinhao)

    m.validar()
    return m


class AssistenteDePortico(QDialog):
    """Diálogo do gerador."""

    def __init__(self, pai=None) -> None:
        super().__init__(pai)
        self.setWindowTitle("Assistente de pórtico regular")
        self.setMinimumWidth(460)

        self.vaos_x = QLineEdit("6, 6")
        self.vaos_y = QLineEdit("5, 5")
        self.pes = QLineEdit("3, 3, 3, 3")
        for campo, dica in ((self.vaos_x, "vãos consecutivos na direção X, em m"),
                            (self.vaos_y, "vãos consecutivos na direção Y, em m"),
                            (self.pes, "pé-direito de cada pavimento, em m")):
            campo.setToolTip(dica)

        geometria = QGroupBox("Geometria")
        f = QFormLayout(geometria)
        f.addRow("Vãos em X (m):", self.vaos_x)
        f.addRow("Vãos em Y (m):", self.vaos_y)
        f.addRow("Pés-direitos (m):", self.pes)

        self.pilar_b = self._spin(0.25, 0.05, 3.0)
        self.pilar_h = self._spin(0.50, 0.05, 3.0)
        self.viga_b = self._spin(0.20, 0.05, 3.0)
        self.viga_h = self._spin(0.50, 0.05, 3.0)
        secoes = QGroupBox("Seções")
        f = QFormLayout(secoes)
        f.addRow("Pilar b × h (m):", self._par(self.pilar_b, self.pilar_h))
        f.addRow("Viga b × h (m):", self._par(self.viga_b, self.viga_h))

        self.classe = QComboBox()
        self.classe.addItems(CLASSES)
        self.classe.setCurrentText("C30")
        self.agregado = QComboBox()
        self.agregado.addItems(list(ALFA_E))
        self.agregado.setCurrentText("granito e gnaisse")
        self.modulo = QComboBox()
        self.modulo.addItems(["Ecs", "Eci"])
        self.gama = self._spin(25.0, 0.0, 100.0, passo=1.0, casas=1)
        self.modulo_lido = QLabel()

        material = QGroupBox("Concreto")
        f = QFormLayout(material)
        f.addRow("Classe:", self.classe)
        f.addRow("Agregado graúdo:", self.agregado)
        f.addRow("Módulo:", self.modulo)
        f.addRow("Peso específico (kN/m³):", self.gama)
        f.addRow("Resulta em:", self.modulo_lido)
        for w in (self.classe, self.agregado, self.modulo):
            w.currentTextChanged.connect(self._mostrar_modulo)
        self._mostrar_modulo()

        self.espessura = self._spin(0.12, 0.0, 1.0, passo=0.01, casas=3)
        self.revestimento = self._spin(1.5, 0.0, 50.0, passo=0.5, casas=2)
        self.acidental = self._spin(2.0, 0.0, 50.0, passo=0.5, casas=2)
        laje = QGroupBox("Lajes")
        f = QFormLayout(laje)
        f.addRow("Espessura (m):", self.espessura)
        f.addRow("Revestimento (kN/m²):", self.revestimento)
        f.addRow("Acidental (kN/m²):", self.acidental)

        self.parede = self._spin(6.0, 0.0, 200.0, passo=1.0, casas=2)
        self.vento = self._spin(30.0, 0.0, 1000.0, passo=5.0, casas=1)
        self.gerar_peso = QCheckBox("Gerar peso próprio das barras")
        self.gerar_peso.setChecked(True)
        cargas = QGroupBox("Cargas nas vigas e vento")
        f = QFormLayout(cargas)
        f.addRow("Parede sobre as vigas (kN/m):", self.parede)
        f.addRow("Vento por pavimento (kN):", self.vento)
        f.addRow(self.gerar_peso)

        aviso = QLabel(
            "Cada célula da grelha vira um painel de laje, e é a laje que "
            "carrega as vigas — por área de influência, o que dá carga "
            "triangular no lado menor e trapezoidal no maior. O peso próprio "
            "da laje sai da espessura; o das barras, da seção. A carga direta "
            "nas vigas é só a parede.\n\n"
            "A laje é painel de carga, não elemento de casca: ela não trabalha "
            "como diafragma, de modo que as prumadas resistem ao vento cada "
            "uma pela sua rigidez.")
        aviso.setWordWrap(True)
        aviso.setStyleSheet("color: #4a5666; font-size: 9pt;")

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        leiaute = QVBoxLayout(self)
        for w in (geometria, secoes, material, laje, cargas, aviso, botoes):
            leiaute.addWidget(w)

    def _mostrar_modulo(self) -> None:
        """Mostra o módulo que sai da classe, antes de gerar o modelo.

        O valor aparece na tela porque é conta da norma feita pelo programa, e
        conta que ninguém vê é conta em que ninguém repara quando sai errada.
        """
        from ..core.concreto import fck_da_classe, modulo_inicial, modulo_secante

        try:
            fck = fck_da_classe(self.classe.currentText())
        except ErroDeModelo:
            self.modulo_lido.setText("—")
            return
        agregado = self.agregado.currentText()
        em_mpa = (modulo_secante(fck, agregado) if self.modulo.currentText()
                  == "Ecs" else modulo_inicial(fck, agregado))
        self.modulo_lido.setText(
            f"{self.modulo.currentText()} = {em_mpa:,.0f} MPa"
            .replace(",", ".") + f"  ({em_mpa * 1000:,.0f} kN/m²)"
            .replace(",", "."))

    @staticmethod
    def _spin(valor: float, minimo: float, maximo: float, passo: float = 0.05,
              casas: int = 3) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(minimo, maximo)
        s.setDecimals(casas)
        s.setSingleStep(passo)
        s.setValue(valor)
        return s

    @staticmethod
    def _par(a, b):
        from PySide6.QtWidgets import QHBoxLayout, QWidget
        caixa = QWidget()
        leiaute = QHBoxLayout(caixa)
        leiaute.setContentsMargins(0, 0, 0, 0)
        leiaute.addWidget(a)
        leiaute.addWidget(b)
        return caixa

    def modelo(self) -> Modelo:
        return gerar_portico(
            ler_lista(self.vaos_x.text(), "vãos em X"),
            ler_lista(self.vaos_y.text(), "vãos em Y"),
            ler_lista(self.pes.text(), "pés-direitos"),
            (self.pilar_b.value(), self.pilar_h.value()),
            (self.viga_b.value(), self.viga_h.value()),
            fck_da_classe(self.classe.currentText()),
            self.agregado.currentText(), self.modulo.currentText(),
            self.gama.value(),
            self.espessura.value(), self.revestimento.value(),
            self.acidental.value(), self.parede.value(), self.vento.value(),
            self.gerar_peso.isChecked())
