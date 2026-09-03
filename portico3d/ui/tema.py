# -*- coding: utf-8 -*-
"""
tema.py
Tema claro fixo, o mesmo dos outros programas da pasta.

O tema é fixo, e não o do sistema, porque os desenhos têm fundo branco: com o
Windows em modo escuro, uma janela escura em volta de figuras claras fica
desconfortável de ler.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

AZUL = "#1f4e79"
AZUL_CLARO = "#2e75b6"
FUNDO = "#f5f6f8"
BASE = "#ffffff"
TEXTO = "#1a1a1a"
BORDA = "#c9ced6"
VERMELHO = "#a5232f"
VERDE = "#2e7d4f"
LARANJA = "#c26a00"

# Cores do desenho
COR_BARRA = "#3b4757"
COR_NO = "#1f4e79"
COR_APOIO = "#a5232f"
COR_MOLA = "#c26a00"
COR_DEFORMADA = "#2e75b6"
COR_CARGA = "#2e7d4f"
COR_DIAGRAMA_POSITIVO = "#2e75b6"
COR_DIAGRAMA_NEGATIVO = "#a5232f"

FOLHA_DE_ESTILO = f"""
QMainWindow, QWidget {{ font-size: 10pt; }}
QToolBar {{ background: {BASE}; border-bottom: 1px solid {BORDA}; padding: 4px; spacing: 6px; }}
QToolBar QToolButton {{ padding: 5px 12px; border-radius: 4px; }}
QToolBar QToolButton:hover {{ background: #e3edf7; }}
QTabWidget::pane {{ border: 1px solid {BORDA}; background: {BASE}; }}
QTabBar::tab {{ padding: 7px 14px; margin-right: 2px; background: #e6e9ee;
                border: 1px solid {BORDA}; border-bottom: none;
                border-top-left-radius: 4px; border-top-right-radius: 4px; }}
QTabBar::tab:selected {{ background: {BASE}; color: {AZUL}; font-weight: bold; }}
QTabBar::tab:disabled {{ color: #9aa1ab; }}
QGroupBox {{ border: 1px solid {BORDA}; border-radius: 4px; margin-top: 10px;
             padding: 10px; background: {BASE}; font-weight: bold; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px;
                    color: {AZUL}; }}
QHeaderView::section {{ background: {AZUL}; color: white; padding: 4px 6px;
                        border: none; border-right: 1px solid #16395a;
                        font-weight: bold; }}
QTableView, QTableWidget {{ gridline-color: #dde3ea;
                            selection-background-color: #cfe2f3;
                            selection-color: {TEXTO}; }}
QScrollArea {{ border: none; }}
QStatusBar {{ background: {BASE}; border-top: 1px solid {BORDA}; }}
QPushButton {{ padding: 5px 12px; border: 1px solid {BORDA}; border-radius: 4px;
               background: {BASE}; }}
QPushButton:hover {{ background: #e3edf7; }}
QPushButton:disabled {{ color: #9aa1ab; }}
QPlainTextEdit {{ border: 1px solid {BORDA}; background: {BASE};
                  font-family: Consolas, monospace; font-size: 9pt; }}
"""


def aplicar_tema_claro(aplicacao: QApplication) -> None:
    """Fixa o estilo Fusion e a paleta clara na aplicação."""
    aplicacao.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.Window, QColor(FUNDO))
    p.setColor(QPalette.WindowText, QColor(TEXTO))
    p.setColor(QPalette.Base, QColor(BASE))
    p.setColor(QPalette.AlternateBase, QColor("#eef1f5"))
    p.setColor(QPalette.Text, QColor(TEXTO))
    p.setColor(QPalette.Button, QColor(BASE))
    p.setColor(QPalette.ButtonText, QColor(TEXTO))
    p.setColor(QPalette.Highlight, QColor(AZUL_CLARO))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    aplicacao.setPalette(p)
    aplicacao.setStyleSheet(FOLHA_DE_ESTILO)
