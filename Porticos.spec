# -*- mode: python ; coding: utf-8 -*-
"""Receita do PyInstaller para o Pórticos 3D.

Gera duas saídas a partir da mesma análise de dependências:

* ``dist/Porticos/Porticos.exe`` — pasta do programa. Abre rápido; é a forma
  recomendada de distribuir.
* ``dist/Porticos-portatil.exe`` — arquivo único. Mais cômodo de passar
  adiante, porém se descompacta num diretório temporário a cada abertura, o
  que custa alguns segundos de espera.

Uso:
    python -m PyInstaller --noconfirm Porticos.spec

## O que este programa precisa e o Hidra não

Três bibliotecas que a receita do Hidra **exclui** são obrigatórias aqui, e
excluí-las por simetria quebraria o programa na primeira exportação:

``scipy``
    autovalores da flambagem (``eigh``) e os sistemas esparsos da montagem.

``openpyxl``
    o quadro de quantidades em Excel.

``python-docx`` e ``ezdxf``
    a memória de cálculo em Word e os desenhos em CAD. As duas carregam
    **arquivos de dados** — os modelos .xml do docx e os recursos do ezdxf —,
    que precisam ser coletados à mão: sem eles o pacote monta e só falha na
    hora de gravar, que é o pior momento para descobrir.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

RAIZ = Path(SPECPATH)
ICONE = RAIZ / "portico3d" / "recursos" / "porticos.ico"

# Recursos próprios e os exemplos. Os exemplos vão junto porque abrir um
# modelo pronto é a primeira coisa que se faz num programa destes — sem eles,
# a primeira tela é um pórtico vazio e nenhuma pista de por onde começar.
recursos = [
    (str(ICONE), "portico3d/recursos"),
    (str(RAIZ / "portico3d" / "recursos" / "porticos_logo.png"),
     "portico3d/recursos"),
    (str(RAIZ / "exemplos"), "exemplos"),
    (str(RAIZ / "LEIAME.md"), "."),
    (str(RAIZ / "requirements.txt"), "."),
]

# Dados das bibliotecas de saída: modelos do Word, recursos do CAD.
recursos += collect_data_files("docx")
recursos += collect_data_files("ezdxf")

ocultos = [
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_agg",
    "openpyxl.cell._writer",
    # o Importer do ezdxf é carregado só na hora de montar a prancha única
    "ezdxf.addons",
    "ezdxf.addons.importer",
    "ezdxf.bbox",
]
# O ezdxf resolve parte dos seus módulos por nome, em tempo de execução.
ocultos += collect_submodules("ezdxf.render")

# **Os motores de elemento inteiros.** O programa alcança boa parte deles por
# nome montado em tempo de execução, e o que o PyInstaller não vê importado
# ele não empacota: sem isto, o relatório e a planilha de cada motor ficavam
# de fora, e só se descobria ao tentar emitir. Vendorizar é prometer que a
# cópia dentro do programa é a cópia inteira, e a promessa vale também depois
# de empacotado.
ocultos += collect_submodules("portico3d.elementos")

# Módulos que nada no programa usa. Sem excluí-los, o PyInstaller varre o Qt
# inteiro e o pacote passa de 1 GB.
excluir = [
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
    "sphinx",
    "setuptools",
    "pip",
    "pandas",
    "PIL.ImageQt",
    "matplotlib.backends.backend_webagg",
    "matplotlib.backends.backend_tkagg",
    "matplotlib.backends._tkagg",
    # Módulos Qt fora de uso: só QtCore, QtGui e QtWidgets entram.
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
]

analise = Analysis(
    ["main.py"],
    pathex=[str(RAIZ)],
    binaries=[],
    datas=recursos,
    hiddenimports=ocultos,
    excludes=excluir,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analise.pure)

# ---------------------------------------------------------------- pasta

exe_pasta = EXE(
    pyz,
    analise.scripts,
    [],
    exclude_binaries=True,
    name="Porticos",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ICONE),
    version=None,
)

COLLECT(
    exe_pasta,
    analise.binaries,
    analise.datas,
    strip=False,
    upx=False,
    name="Porticos",
)

# ------------------------------------------------------------ arquivo único

EXE(
    pyz,
    analise.scripts,
    analise.binaries,
    analise.datas,
    [],
    name="Porticos-portatil",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon=str(ICONE),
)
