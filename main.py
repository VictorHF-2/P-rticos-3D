# -*- coding: utf-8 -*-
"""
main.py
Ponto de entrada do solver de pórticos espaciais.

    py main.py                         abre a janela
    py main.py modelo.json --janela    abre a janela já com um modelo
    py main.py --autoteste [pasta]     roda as conferências de referência
    py main.py modelo.json [caso]      resolve um modelo e imprime o resumo
    py main.py modelo.json --envoltoria  gera as combinações da NBR 6118,
                                       resolve todas e imprime a envoltória
    py main.py modelo.json --estabilidade  γz por combinação, classificação de
                                       nós fixos ou móveis, e flambagem
"""

from __future__ import annotations

import os
import sys

if getattr(sys, "frozen", False):
    # Empacotado pelo PyInstaller, ``__file__`` aponta para o diretório
    # temporário em que o executável se descompacta — que some ao fechar, e
    # que ninguém vai procurar. A pasta do programa, aqui, é onde o .exe
    # está: é lá que o usuário espera achar o que o programa gravou.
    PASTA = os.path.dirname(os.path.abspath(sys.executable))
else:
    PASTA = os.path.dirname(os.path.abspath(__file__))
    if PASTA not in sys.path:
        sys.path.insert(0, PASTA)

# Os nomes das conferências trazem δ, γ, Δ e ². Num console em cp1252 — que é
# o do cmd.exe e o do Git Bash em português — imprimir isso levanta
# UnicodeEncodeError e derruba o programa no meio do relatório. Forçar UTF-8
# resolve onde o console aceita, e o "replace" garante que, onde não aceitar,
# o caractere vire "?" em vez de interromper a execução.
for fluxo in (sys.stdout, sys.stderr):
    if hasattr(fluxo, "reconfigure"):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def conferir_janela(destino: str) -> list[str]:
    """Monta a janela sem tela e percorre todas as vistas.

    Não confere número nenhum — disso cuidam as conferências do ``core``. O
    que se prova aqui é que a interface monta, que o assistente gera um modelo
    que o solver aceita, e que cada vista desenha sem quebrar. É o tipo de
    defeito que só aparece ao abrir o programa, e que uma conferência
    puramente numérica nunca pegaria.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from portico3d.ui.assistente import gerar_portico
    from portico3d.ui.janela import Janela
    from portico3d.ui.tema import aplicar_tema_claro
    from portico3d.ui.janela import ANALISES
    from portico3d.ui.vista3d import VISTAS_DE_ESFORCO

    aplicacao = QApplication.instance() or QApplication([])
    aplicar_tema_claro(aplicacao)

    janela = Janela()
    janela.modelo = gerar_portico([6.0, 5.0], [5.0], [3.0, 3.0, 3.0],
                                  (0.25, 0.50), (0.20, 0.50), fck=30.0,
                                  espessura_laje=0.12, revestimento=1.5,
                                  acidental=2.0, parede=6.0, vento=30.0)
    janela._carregar_nas_tabelas()

    notas = [f"janela: modelo do assistente com {len(janela.modelo.nos)} nós "
             f"e {len(janela.modelo.barras)} barras"]

    if not janela.aplicar():
        raise RuntimeError("a ida e volta pelas tabelas recusou o modelo")
    notas.append("janela: as tabelas devolveram o mesmo modelo")

    # Acrescentar e remover linha em cada tabela. Parece bobo, mas foi
    # exatamente aqui que a versão anterior quebrava — a linha nova nasce com
    # célula vazia, e formatar vazio como número derrubava a janela.
    for chave, tabela in janela.dados.tabelas.items():
        antes = tabela.tabela.rowCount()
        tabela.acrescentar_linha()
        if tabela.tabela.rowCount() != antes + 1:
            raise RuntimeError(f"a tabela '{chave}' não acrescentou linha")
        tabela.tabela.selectRow(tabela.tabela.rowCount() - 1)
        tabela.remover_selecionadas()
        if tabela.tabela.rowCount() != antes:
            raise RuntimeError(f"a tabela '{chave}' não removeu a linha")
    notas.append(f"janela: linha acrescentada e removida nas "
                 f"{len(janela.dados.tabelas)} tabelas")

    secoes = janela.dados.tabelas["secoes"]
    indice = secoes._indice
    calculada = secoes.tabela.item(0, indice["Iy"])
    if calculada is None or not calculada.text():
        raise RuntimeError("a seção retangular não teve as propriedades "
                           "calculadas")
    notas.append(f"janela: seção calculada pelos lados, Iy = {calculada.text()}")

    # Um botão só roda todas as análises; a lista Análise escolhe qual olhar.
    janela.analisar_tudo()
    if "G" not in janela.resultados:
        raise RuntimeError("a análise do caso G não produziu resultado")
    if "G" not in janela.resultados_2a:
        raise RuntimeError("a 2ª ordem do caso G não produziu resultado")
    notas.append("janela: um clique em Análise resolveu 1ª e 2ª ordem")
    if not janela.flambagens or not janela.resultados_estab:
        raise RuntimeError("flambagem ou estabilidade ficaram sem resultado")
    notas.append("janela: combinações, estabilidade e flambagem percorridas")

    if janela.modal_atual is None:
        raise RuntimeError("a análise modal não produziu resultado")
    notas.append(f"janela: modal com {len(janela.modal_atual.frequencias)} "
                 f"frequências (f1 = {janela.modal_atual.frequencia_fundamental:.3f} Hz)")

    # Cada análise oferece só as vistas que fazem sentido para ela: o modal
    # não tem armadura, e a flambagem não tem diagrama de momento.
    janela.escolha_analise.setCurrentText("Modal")
    vistas_modal = [janela.escolha_vista.itemText(i)
                    for i in range(janela.escolha_vista.count())]
    if "Armadura" in vistas_modal or "My" in vistas_modal:
        raise RuntimeError(f"o modal oferece vistas que não são dele: "
                           f"{vistas_modal}")
    notas.append(f"janela: o modal oferece só {vistas_modal}")

    # Os três "Dimensionar" não abrem diálogo: calculam, guardam o resultado e
    # atualizam o modelo 3D da armadura. A pasta só é perguntada em
    # ``Emitir > Pranchas`` — aí o diálogo é trocado por uma pasta fixa, porque
    # diálogo modal em modo offscreen fica esperando para sempre.
    import tempfile

    from portico3d.dimensionamento import cotas_com_laje
    cotas = cotas_com_laje(janela.modelo)
    janela.dimensionar_lajes()
    lajes = janela.dimensionamento.get("lajes") or []
    if not any(v.passou for v in lajes):
        raise RuntimeError("nenhum pavimento de laje foi dimensionado")
    if any(v.desenhos for v in lajes):
        raise RuntimeError("dimensionar lajes gravou desenho sem ser pedido")
    notas.append(f"janela: {len(cotas)} pavimentos de laje dimensionados, "
                 "sem gravar planta")

    antes = len(janela.relatorio.toPlainText())
    janela.dimensionar_pilares()
    if "Dimensionamento de pilares" not in janela.relatorio.toPlainText()[antes:]:
        raise RuntimeError("o dimensionamento de pilares não produziu relatório")
    notas.append("janela: pilares dimensionados pelo motor copiado")

    janela.dimensionar_vigas()
    vigas = janela.dimensionamento.get("vigas") or []
    if not any(v.passou for v in vigas):
        raise RuntimeError("nenhuma viga foi dimensionada")
    if any(v.desenhos for v in vigas):
        raise RuntimeError("dimensionar vigas gravou desenho sem ser pedido")
    notas.append(f"janela: {len(vigas)} vigas dimensionadas, sem gravar "
                 "prancha")
    if not all(v.esforcos == "portico" for v in vigas if v.passou):
        raise RuntimeError("as vigas não foram armadas pela envoltória do "
                           "pórtico, que é o padrão")
    notas.append("janela: vigas armadas pela envoltória do pórtico")

    # O menu Cálculo: diafragma e grelha ligados pela ação, como o usuário
    # faria, e a Análise de novo. A opção vai para o modelo, sobrevive ao
    # "Aplicar tabelas" e apaga as análises feitas com a opção anterior.
    janela.acao_diafragma.setChecked(True)
    janela.acao_grelha.setChecked(True)
    if janela.resultados:
        raise RuntimeError("ligar a grelha não apagou as análises antigas")
    janela.analisar_tudo()
    calculo = janela.modelo.calculo
    texto = janela.relatorio.toPlainText()
    if not (calculo.diafragma and calculo.grelha):
        raise RuntimeError("o menu Cálculo não chegou ao modelo")
    if "Diafragma rígido: 3 pavimentos" not in texto or "grelha:" not in texto:
        raise RuntimeError("a Análise não relatou o diafragma e a grelha")
    r = janela.resultados.get("G")
    if r is None or r.calculo is None:
        raise RuntimeError("a 1ª ordem não passou pela grelha")
    janela._mostrar("1ª ordem", "My")
    notas.append(f"janela: diafragma e grelha pelo menu Cálculo — "
                 f"{r.calculo[0].calc.n_gdl} graus de liberdade no cálculo, "
                 f"f1 = {janela.modal_atual.frequencia_fundamental:.3f} Hz")
    janela.acao_grelha.setChecked(False)
    janela.acao_diafragma.setChecked(False)
    janela.analisar_tudo()

    with tempfile.TemporaryDirectory() as pasta_pranchas:
        janela._pasta_de_saida = lambda titulo: pasta_pranchas
        janela.emitir_pranchas_de_vigas()
        janela.emitir_pranchas_de_lajes()
        gravados = os.listdir(pasta_pranchas)
    if not any(a.endswith(".dxf") for a in gravados):
        raise RuntimeError("as pranchas pedidas não foram gravadas")
    notas.append(f"janela: pranchas gravadas só ao pedir ({len(gravados)} "
                 "arquivos)")

    janela.escolha_analise.setCurrentText("1ª ordem")
    janela.escolha_caso.setCurrentText("G")
    antes = len(janela.relatorio.toPlainText())
    janela.mostrar_reacoes()
    texto = janela.relatorio.toPlainText()
    if "Reações" not in texto[antes:]:
        raise RuntimeError("a tabela de reações não foi para o relatório")
    notas.append("janela: tabela de reações emitida")

    # Cada análise com as vistas dela, e o caso que ela resolveu.
    desenhadas = 0
    for analise in ANALISES:
        janela.escolha_analise.setCurrentText(analise)
        for i in range(janela.escolha_vista.count()):
            janela.escolha_vista.setCurrentIndex(i)
            janela.redesenhar()
            desenhadas += 1
    notas.append(f"janela: {desenhadas} combinações de análise e vista "
                 "desenhadas")
    # O vento do assistente (cargas nodais horizontais) aparece na vista de
    # cargas, e "todos os casos" junta o permanente, o variável e o vento; as
    # cargas na mesma barra ficam em camadas, e não umas sobre as outras.
    from portico3d.ui.janela import TODOS_OS_CASOS

    janela.escolha_analise.setCurrentText("Cargas")
    janela.escolha_vista.setCurrentText("Cargas")
    janela.escolha_caso.setCurrentText("VX")
    janela.redesenhar()
    setas_vento = [n for n in janela.vista.renderer.actors
                   if n.startswith("carga_")]
    if not setas_vento:
        raise RuntimeError("o vento VX não apareceu na vista de cargas")
    if not any("Fx = +" in t for t, _ in
               janela.vista._alvo_de_carga.values()):
        raise RuntimeError("a carga horizontal do vento não tem o texto de Fx")
    janela.escolha_caso.setCurrentText(TODOS_OS_CASOS)
    janela.redesenhar()
    setas_todas = [n for n in janela.vista.renderer.actors
                   if n.startswith("carga_")]
    if len(setas_todas) <= len(setas_vento):
        raise RuntimeError("'todos os casos' não juntou as cargas dos casos")
    empilhadas = [v for v in janela.vista._camadas.values() if v > 0.0]
    if not empilhadas:
        raise RuntimeError("as cargas da vista não foram empilhadas em camadas")
    notas.append(f"janela: vista de cargas com o vento ({len(setas_vento)} "
                 f"setas) e todos os casos juntos ({len(setas_todas)} cargas, "
                 f"{len(empilhadas)} pilhas de camadas)")

    janela.escolha_analise.setCurrentText("Modelo")
    janela.escolha_vista.setCurrentText("Armadura")
    janela.redesenhar()

    # A vista de Armadura roda os três motores de elemento e guarda o
    # resultado por cota. Conferir o cache é conferir que girar o desenho não
    # redimensiona o prédio de novo, que é a razão de ele existir.
    if not janela.armaduras:
        raise RuntimeError("a vista de armadura não calculou pavimento nenhum")
    cota, armadura = next(iter(janela.armaduras.items()))
    if not armadura.fios:
        raise RuntimeError(f"a armadura da cota {cota:g} m saiu vazia")
    janela.redesenhar()
    if len(janela.armaduras) != 1:
        raise RuntimeError("o redesenho recalculou a armadura em vez de "
                           "reaproveitar a guardada")
    notas.append(f"janela: armadura da cota {cota:g} m com "
                 f"{len(armadura.fios)} barras e "
                 f"{armadura.segmentos} segmentos")

    # ``exportar_armadura`` abre diálogo de pasta, como os outros botões que
    # gravam: o que se prova aqui é a gravação por baixo.
    from portico3d.armadura_dxf import contar_entidades, exportar
    caminho = exportar(armadura, os.path.join(destino, "armadura.dxf"),
                       janela.modelo)
    entidades = contar_entidades(caminho)
    if entidades < len(armadura.fios):
        raise RuntimeError(f"o DXF da armadura tem {entidades} entidades para "
                           f"{len(armadura.fios)} barras")
    notas.append(f"janela: armadura em DXF com {entidades} polilinhas 3D")

    # ``gerar_projeto`` abre diálogo de pasta, como os demais botões que
    # gravam. O que se prova aqui é o caminho por baixo: calcular o edifício e
    # emitir os três arquivos.
    from portico3d.projeto import calcular, gerar
    projeto = calcular(janela.modelo)
    if not projeto.vigas or not projeto.lajes:
        raise RuntimeError("o projeto não reconheceu vigas ou lajes")
    conferidas = [v for v in projeto.vigas if v.portico is not None]
    if not conferidas:
        raise RuntimeError("nenhuma viga foi conferida contra a envoltória "
                           "do pórtico — o efeito das ações laterais não "
                           "estaria entrando")
    notas.append(f"janela: projeto com {len(projeto.pilares)} verificações de "
                 f"pilar, {len(projeto.vigas)} vigas ({len(conferidas)} "
                 f"conferidas contra o pórtico) e {len(projeto.lajes)} "
                 "pavimentos")

    emitidos = gerar(projeto, os.path.join(destino, "projeto"))
    falhos = [a for a in emitidos if a.startswith("(")]
    if falhos:
        raise RuntimeError(f"o projeto não emitiu tudo: {falhos}")
    for arquivo in emitidos:
        if os.path.getsize(arquivo) < 4000:
            raise RuntimeError(f"{arquivo} saiu pequeno demais")
    notas.append("janela: projeto emitido — "
                 + ", ".join(os.path.splitext(a)[1] for a in emitidos))

    if janela._ultimo_relatorio_de_laje is None:
        raise RuntimeError("a vista de laje não produziu relatório")
    notas.append(f"janela: vista de laje com {len(janela._ultimo_relatorio_de_laje)}"
                 " painéis calculados")

    # O motor de desenho é PyVista/VTK: sob QT_QPA_PLATFORM=offscreen o
    # widget embutido monta a cena inteira (add_mesh, reset_camera, add_text)
    # normalmente, mas ``render()``/``screenshot()`` não têm janela real para
    # desenhar (RenderWindowUnavailable — ver a nota no topo de vista3d.py).
    # A conferência que faz sentido aqui é a mesma que Consolos R03 e
    # Lajes R06 adotaram: o CONTEÚDO da cena, não o pixel renderizado. A
    # última vista percorrida no laço acima foi "Modo de vibração", que
    # desenha pelo menos uma linha do modo — e o esqueleto do modelo.
    # As lajes do modelo 3D: opacas, e escondidas pela caixa "lajes" sem
    # redesenhar (a câmera fica onde está).
    janela.escolha_analise.setCurrentText("Modelo")
    janela.escolha_vista.setCurrentText("3D")
    janela.redesenhar()
    lajes_3d = [(n, a) for n, a in janela.vista.renderer.actors.items()
                if n.startswith("laje_")]
    if not lajes_3d:
        raise RuntimeError("o modelo 3D não desenhou nenhuma laje")
    if any(a.GetProperty().GetOpacity() < 1.0 for _, a in lajes_3d):
        raise RuntimeError("as lajes do modelo 3D ainda estão transparentes")
    if not janela.mostrar_lajes.isEnabled():
        raise RuntimeError("a caixa das lajes está apagada na vista 3D")
    janela.vista.camera_position = [(30.0, -40.0, 25.0), (6.0, 5.0, 3.0),
                                    (0.0, 0.0, 1.0)]
    posicao = [tuple(p) for p in janela.vista.camera_position]
    janela.mostrar_lajes.setChecked(False)
    if any(a.GetVisibility() for _, a in lajes_3d):
        raise RuntimeError("desmarcar a caixa não escondeu as lajes")
    if [tuple(p) for p in janela.vista.camera_position] != posicao:
        raise RuntimeError("esconder as lajes mexeu na câmera")
    janela.redesenhar()                  # o estado da caixa sobrevive ao redesenho
    if any(a.GetVisibility() for n, a in janela.vista.renderer.actors.items()
           if n.startswith("laje_")):
        raise RuntimeError("o redesenho trouxe as lajes de volta")
    janela.mostrar_lajes.setChecked(True)
    if not all(a.GetVisibility() for n, a in janela.vista.renderer.actors.items()
               if n.startswith("laje_")):
        raise RuntimeError("marcar a caixa não devolveu as lajes")
    janela.escolha_vista.setCurrentText("Modelo")
    janela.redesenhar()
    if janela.mostrar_lajes.isEnabled():
        raise RuntimeError("a caixa das lajes devia ficar apagada fora do 3D")
    notas.append(f"janela: {len(lajes_3d)} lajes opacas no 3D, escondidas e "
                 "devolvidas pela caixa sem mexer na câmera")

    # a vista de Armadura embutida só mostra um aviso: volta ao modelo para
    # contar o que a cena desenhou de verdade
    janela.escolha_vista.setCurrentText("Modelo")
    janela.redesenhar()
    n_atores = len(janela.vista.renderer.actors)
    if n_atores == 0:
        raise RuntimeError("a vista 3D não desenhou nenhum ator (PyVista)")
    notas.append(f"janela: cena 3D com {n_atores} atores (motor PyVista)")

    # A vista de Armadura é a única que abre como janela nativa separada
    # (VistaArmadura3D.mostrar() bloqueia com pv.Plotter().show(), o que
    # travaria o autoteste); o que se confere aqui é a montagem da cena por
    # baixo, com um Plotter fora de tela — o mesmo padrão de
    # ``dimensionar_lajes``/``dimensionar_vigas`` acima, que testam a função
    # e não o diálogo.
    import pyvista as pv

    from portico3d.ui.vista3d import construir_cena_armadura

    plotter_armadura = pv.Plotter(off_screen=True)
    info_armadura = construir_cena_armadura(plotter_armadura, janela.modelo,
                                            armadura, cota)
    plotter_armadura.close()
    if not info_armadura:
        raise RuntimeError("a cena da armadura não identificou família "
                           "nenhuma")
    notas.append(f"janela: cena da armadura com {len(info_armadura)} "
                 "famílias identificáveis (janela nativa, PyVista)")

    # -- cabe em qualquer tela --------------------------------------------
    # O que decide isto é o ``minimumSizeHint``: o Qt ignora um mínimo menor
    # que o do conteúdo, e era por isso que a janela não descia de 1752 px de
    # largura — não cabia em notebook de 1366, nem em 1920 com escala de
    # 150 %, que dá 1280 lógicos. A conferência mede o que o conteúdo exige e
    # depois abre a janela nos tamanhos reais que se encontram por aí.
    from portico3d.ui.janela import JANELA_MINIMA

    exigido = janela.minimumSizeHint()
    if (exigido.width() > JANELA_MINIMA[0]
            or exigido.height() > JANELA_MINIMA[1]):
        raise RuntimeError(
            f"o conteúdo da janela exige {exigido.width()}x"
            f"{exigido.height()} px, acima do piso declarado "
            f"{JANELA_MINIMA[0]}x{JANELA_MINIMA[1]} — ela não caberia numa "
            "tela pequena")
    notas.append(f"janela: o conteúdo cabe em {exigido.width()}x"
                 f"{exigido.height()} px, dentro do piso de "
                 f"{JANELA_MINIMA[0]}x{JANELA_MINIMA[1]}")

    for largura, altura in ((1920, 1080), (1366, 768), (1280, 720),
                            (1024, 768), (800, 600)):
        janela.showNormal()
        janela.resize(largura, altura)
        janela.repartir()
        aplicacao.processEvents()
        esquerda, direita = janela.divisor.sizes()
        if min(esquerda, direita) < 200:
            raise RuntimeError(
                f"em {largura}x{altura} o divisor deixou {esquerda}/{direita} "
                "px — um dos lados ficou inutilizável")
        if janela.relatorio.height() > altura // 2:
            raise RuntimeError(
                f"em {largura}x{altura} o relatório tomou "
                f"{janela.relatorio.height()} px, mais de meia tela")
    notas.append("janela: utilizável de 1920x1080 a 800x600")

    # Os atalhos passaram a morar dentro de menus, e menu que não está aberto
    # só responde ao atalho se a ação estiver na cadeia da janela.
    faltando = [t for t in ("F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9")
                if not any(a.shortcuts()
                           and a.shortcuts()[0].toString() == t
                           for a in janela.actions())]
    if faltando:
        raise RuntimeError(f"atalhos fora do alcance da janela: {faltando}")
    notas.append("janela: os oito atalhos de F2 a F9 alcançam a janela")

    notas += conferir_editor_de_lancamento(janela, aplicacao)
    janela.close()
    return notas


def conferir_editor_de_lancamento(janela, aplicacao) -> list[str]:
    """O editor de planta por cliques de mouse de verdade (``QTest``), e o
    modelo gerado chegando à janela.

    Um pórtico de 5 × 4 m em dois pavimentos: quatro pilares clicados de
    propósito fora da grade (a captura os põe no lugar), a viga como
    polilinha que captura os centros dos pilares, a laje com um clique, e
    "Gerar modelo". Depois o exemplo residencial aberto no editor.
    """
    from pathlib import Path

    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    notas = []
    janela.abrir_lancamento()
    ed = janela.editor_de_lancamento
    ed.resize(1400, 900)
    ed.show()
    aplicacao.processEvents()
    ed.redesenhar(enquadrar=True)
    aplicacao.processEvents()

    def clicar(x, y, modificador=Qt.NoModifier):
        pos = ed.vista.mapFromScene(QPointF(x, -y))
        QTest.mouseMove(ed.vista.viewport(), pos)
        QTest.mouseClick(ed.vista.viewport(), Qt.LeftButton,
                         modificador, pos)
        aplicacao.processEvents()

    ed.escolher_ferramenta("Pilar")
    for x, y in ((0.02, -0.01), (5.01, 0.02), (4.99, 3.99), (-0.02, 3.98)):
        clicar(x, y)
    centros = sorted((p.x, p.y) for p in ed.planta.pilares)
    if centros != [(0.0, 0.0), (0.0, 4.0), (5.0, 0.0), (5.0, 4.0)]:
        raise RuntimeError(f"a captura não pôs os pilares na grade: "
                           f"{centros}")
    ed.escolher_ferramenta("Viga")
    for x, y in ((0.03, 0.02), (5.0, 0.04), (5.02, 4.0), (0.01, 4.02),
                 (0.0, 0.03)):
        clicar(x, y)
    QTest.keyClick(ed.vista, Qt.Key_Return)
    aplicacao.processEvents()
    ed.escolher_ferramenta("Laje")
    clicar(2.5, 2.0)
    ed.acrescentar_pavimento()
    g = ed.gerar_modelo()
    if not g.ok:
        raise RuntimeError("o lançamento clicado não gerou: "
                           + "; ".join(g.erros))
    if len(janela.modelo.barras) != 16 or len(janela.modelo.lajes) != 2:
        raise RuntimeError("o modelo gerado não chegou à janela")
    notas.append("editor de lançamento: pilares, viga e laje por clique "
                 "(captura na grade e nos pilares), dois pavimentos — "
                 f"{len(janela.modelo.nos)} nós e "
                 f"{len(janela.modelo.barras)} barras entregues à janela")

    # Precisão: passo de 10 cm sem captura em objetos, coordenada digitada
    # (absoluta e relativa) e o giro do próximo pilar antes de colocá-lo.
    ed.escolher_ferramenta("Pilar")
    ed.definir_passo(0.10)
    ed.captura_objetos.setChecked(False)
    if ed.capturar(2.2349, 2.8761) != (2.2, 2.9):
        raise RuntimeError("o passo de 10 cm não travou a captura")
    ed.girar()
    ed.entrar_coordenada("2,2; 2,8")
    ed.entrar_coordenada("@3; 0")
    novos = [p for p in ed.planta.pilares if p.y == 2.8]
    if [(p.x, p.angulo) for p in novos] != [(2.2, 90.0), (5.2, 90.0)]:
        raise RuntimeError(f"coordenada digitada ou giro falharam: "
                           f"{[(p.x, p.y, p.angulo) for p in novos]}")
    ed._ao_mover(1.0, 1.0, Qt.NoModifier)
    if len(ed._dinamicos) < 3:
        raise RuntimeError("o pilar não aparece junto do cursor antes do "
                           "clique")
    for p in novos:
        ed.apagar(p)
    ed.captura_objetos.setChecked(True)
    ed.definir_passo(0.05)
    notas.append("editor de lançamento: passo de 10 cm, coordenada digitada "
                 "(2,2; 2,8 e @3; 0), pilar girado visto no cursor antes do "
                 "clique")

    # Zoom pela roda: o ponto sob o mouse fica onde está (antes ia ao 0; 0)
    from PySide6.QtCore import QPoint
    pixel = QPoint(ed.vista.viewport().width() * 3 // 4,
                   ed.vista.viewport().height() // 4)
    antes = ed.vista.mapToScene(pixel)
    for fator in (1.15, 1.15, 1.15, 1 / 1.15):
        ed.vista.zoom_em(pixel, fator)
    depois = ed.vista.mapToScene(pixel)
    deriva_px = ((depois - antes).manhattanLength() * ed.vista.escala)
    if deriva_px > 2.0:
        raise RuntimeError(f"o zoom não ficou no ponto sob o mouse "
                           f"({deriva_px:.1f} px de deriva)")
    ed.redesenhar(enquadrar=True)
    aplicacao.processEvents()

    # A viga clicada com mudança de direção sai como duas vigas
    antes_v = len(ed.planta.vigas)
    ed.escolher_ferramenta("Viga")
    for x, y in ((0.0, 0.0), (4.5, 0.0), (6.0, 2.0)):
        clicar(x, y)
    QTest.keyClick(ed.vista, Qt.Key_Return)
    aplicacao.processEvents()
    dobradas = ed.planta.vigas[antes_v:]
    if [v.pontos for v in dobradas] != [[(0.0, 0.0), (4.5, 0.0)],
                                        [(4.5, 0.0), (6.0, 2.0)]]:
        raise RuntimeError(f"a viga dobrada não virou duas: "
                           f"{[v.pontos for v in dobradas]}")
    for v in dobradas:
        ed.apagar(v)
    notas.append(f"editor de lançamento: zoom preso ao ponto sob o mouse "
                 f"({deriva_px:.2f} px), viga dobrada clicada vira duas")

    # Grelha 6 × 6 numa planta nova, a cota de um espaço clicada e trocada
    ed.nova_planta()
    ed.gerar_grelha(6, 5.0, 6, 5.0, pilares=True, vigas=True)
    if len(ed.planta.pilares) != 36 or len(ed.planta.vigas) != 12:
        raise RuntimeError("a grelha não lançou 36 pilares e 12 vigas")
    aplicacao.processEvents()
    _, _, (cx, cy) = next(c for c in ed._cotas_da_grelha
                          if c[:2] == ("coluna", 2))
    if ed._cota_da_grelha_em(cx + 0.1, cy) != ("coluna", 2):
        raise RuntimeError("o clique na cota do 3º espaço não a acha")
    ed.editar_espaco("coluna", 2, 2.0)
    if ed.lanc.grelha.xs != [0.0, 5.0, 10.0, 12.0, 17.0, 22.0]:
        raise RuntimeError(f"a troca do espaço moveu errado: "
                           f"{ed.lanc.grelha.xs}")
    notas.append("editor de lançamento: grelha 6×6 com 36 pilares e 12 "
                 "vigas; a cota C–D clicada vira 2 m e só ela muda")

    # Seleção múltipla: Ctrl+clique soma, Alt+clique tira, viga não entra
    # numa seleção de pilares, e o painel e o R valem para todos
    ed.redesenhar(enquadrar=True)
    aplicacao.processEvents()
    ed.escolher_ferramenta("Selecionar")
    clicar(0.0, 0.0)
    for x, y in ((5.0, 0.0), (10.0, 5.0), (12.0, 10.0)):
        clicar(x, y, Qt.ControlModifier)
    clicar(2.5, 0.0, Qt.ControlModifier)                  # a viga V1
    clicar(10.0, 5.0, Qt.AltModifier)
    sel = [p for p in ed.selecionados]
    if [type(p).__name__ for p in sel] != ["PilarLancado"] * 3 or \
            sorted(p.centro for p in sel) != [(0.0, 0.0), (5.0, 0.0),
                                              (12.0, 10.0)]:
        raise RuntimeError(f"Ctrl/Alt+clique montou a seleção errada: "
                           f"{[(o.nome, getattr(o, 'centro', '')) for o in sel]}")
    ed.form._campos["b"].setValue(0.30)
    fora = [p for p in ed.planta.pilares if not ed.esta_selecionado(p)]
    angulos = {id(p): p.angulo for p in ed.planta.pilares}
    ed.girar()
    if any(p.b != 0.30 or p.angulo != (angulos[id(p)] + 90.0) % 360.0
           for p in sel) or \
            any(p.b == 0.30 or p.angulo != angulos[id(p)] for p in fora) or \
            "nome" in ed.form._campos:
        raise RuntimeError("a mudança em lote não foi só para os "
                           "selecionados")
    notas.append("editor de lançamento: Ctrl+clique em 4 pilares, Alt+clique "
                 "tira 1, a viga fica fora; seção e giro valem para os 3")
    ed.apagar_grelha()

    exemplo = Path(__file__).parent / "exemplos" / \
        "lancamento-residencial.json"
    if exemplo.exists():
        ed.abrir(str(exemplo))
        g = ed.gerar_modelo()
        if not g.ok or len(janela.modelo.barras) != 72:
            raise RuntimeError("o exemplo residencial não gerou pelo editor")
        notas.append("editor de lançamento: o exemplo residencial abre e "
                     "gera o mesmo modelo (72 barras, 15 lajes)")
    ed.close()
    return notas


def conferir_montagem_pela_janela() -> list[str]:
    """Monta uma viga do zero pelas tabelas, como o usuário faria.

    É o caminho principal do programa agora: material, seção pelos lados, nós,
    barra apontando para os nós, apoios, caso e carga — nessa ordem, e cada um
    dependendo do anterior. No fim confere um número conhecido, wL²/8, para
    que a prova não seja só "não deu erro", mas "deu o resultado certo".
    """
    from PySide6.QtCore import Qt

    from portico3d.ui.janela import Janela

    janela = Janela()
    tabelas = janela.dados.tabelas

    def preencher(chave: str, valores: dict) -> None:
        tabela = tabelas[chave]
        tabela.acrescentar_linha()
        linha = tabela.tabela.rowCount() - 1
        for campo, valor in valores.items():
            celula = tabela.tabela.item(linha, tabela._indice[campo])
            if isinstance(valor, bool):
                celula.setCheckState(Qt.Checked if valor else Qt.Unchecked)
            else:
                celula.setText(str(valor))

    L, w = 5.0, 20.0
    # O material entra pela classe: quem digita C30 recebe o módulo da norma.
    preencher("materiais", {"nome": "C30", "tipo": "concreto",
                            "classe": "C30", "agregado": "granito e gnaisse",
                            "modulo": "Ecs", "peso_especifico": 0})
    preencher("secoes", {"nome": "V20x50", "tipo": "retangular", "b": 0.20,
                         "h": 0.50})
    preencher("nos", {"nome": "N1", "x": 0, "y": 0, "z": 0})
    preencher("nos", {"nome": "N2", "x": L, "y": 0, "z": 0})

    # A lista suspensa da barra tem de enxergar os nós recém-digitados.
    disponiveis = tabelas["nos"].valores("nome")
    if disponiveis != ["N1", "N2"]:
        raise RuntimeError(f"a lista de nós saiu como {disponiveis}")

    preencher("barras", {"nome": "B1", "no_i": "N1", "no_j": "N2",
                         "material": "C30", "secao": "V20x50",
                         "rotacao": 0, "offset_i": 0, "offset_j": 0})
    preencher("apoios", {"no": "N1", "ux": True, "uy": True, "uz": True,
                         "rx": True, "ry": False, "rz": False})
    preencher("apoios", {"no": "N2", "ux": False, "uy": True, "uz": True,
                         "rx": False, "ry": False, "rz": False})
    preencher("casos", {"nome": "G", "natureza": "permanente"})
    preencher("distribuidas", {"caso": "G", "barra": "B1", "qz": -w,
                               "sistema": "local", "inicio": 0, "fim": 1})

    # A coluna calculada é de exibição, arredondada a seis dígitos — e é por
    # isso que a leitura de volta refaz a seção pelos lados, em vez de ler as
    # propriedades da tela. Aqui basta conferir que o que aparece descreve a
    # seção digitada.
    secao = tabelas["secoes"]
    calculado = float(secao.tabela.item(0, secao._indice["Iy"]).text())
    esperado = 0.20 * 0.50 ** 3 / 12.0
    if abs(calculado - esperado) > 1e-5 * esperado:
        raise RuntimeError(f"Iy calculado saiu {calculado}, esperado {esperado}")

    # O módulo tem de ter saído da classe, não de um campo digitado.
    materiais = tabelas["materiais"]
    from portico3d.core.concreto import modulo_secante
    calculado_e = float(materiais.tabela.item(0, materiais._indice["E"]).text())
    esperado_e = modulo_secante(30.0) * 1000.0
    if abs(calculado_e - esperado_e) > 1e-5 * esperado_e:
        raise RuntimeError(f"E do C30 saiu {calculado_e}, esperado {esperado_e}")

    if not janela.aplicar():
        raise RuntimeError("as tabelas montadas à mão foram recusadas")

    janela.analisar_tudo()
    resultado = janela.resultados.get("G")
    if resultado is None:
        raise RuntimeError("a análise da viga montada não produziu resultado")

    meio = resultado.diagrama("B1", 3).My[1]
    if abs(meio - w * L ** 2 / 8.0) > 1e-9:
        raise RuntimeError(f"momento no vão saiu {meio}, esperado "
                           f"{w * L ** 2 / 8.0}")

    # Ler o esforço com o clique: no diagrama de My, o ponto do meio do vão
    # tem de devolver wL²/8, com a unidade, e a leitura de verdade (raio
    # lançado da tela) tem de achar a barra.
    import numpy as np

    janela.escolha_analise.setCurrentText("1ª ordem")
    janela.escolha_vista.setCurrentText("My")
    janela.redesenhar()
    vista = janela.vista
    # sem tela o renderizador nasce com tamanho zero, e então o raio lançado
    # da tela não significa nada: dá-lhe um tamanho de verdade
    vista.render_window.SetSize(800, 600)
    janela.redesenhar()
    if not vista._barra_do_ator:
        raise RuntimeError("o diagrama de esforços não tem nada em que clicar")
    # o clique não pode devolver a câmera à posição inicial
    vista.camera_position = [(10.0, -12.0, 8.0), (L / 2.0, 0.0, 0.0),
                             (0.0, 0.0, 1.0)]
    camera_antes = [tuple(np.round(p, 6)) for p in vista.camera_position]
    texto = vista._ler_esforco("B1", np.array([L / 2.0, 0.0, 0.0]))
    camera_depois = [tuple(np.round(p, 6)) for p in vista.camera_position]
    if camera_antes != camera_depois:
        raise RuntimeError("o clique para ler o esforço moveu a câmera")
    esperado = f"{w * L ** 2 / 8.0:+.2f} kN·m"
    if esperado not in texto:
        raise RuntimeError(f"a leitura do meio do vão saiu '{texto}', "
                           f"esperado {esperado}")
    vista.renderer.SetWorldPoint(L / 2.0, 0.0, 0.0, 1.0)
    vista.renderer.WorldToDisplay()
    x_tela, y_tela, _ = vista.renderer.GetDisplayPoint()
    vista._picker.Pick(x_tela, y_tela, 0, vista.renderer)
    if vista._barra_do_ator.get(vista._picker.GetActor()) != "B1":
        raise RuntimeError("o clique no meio da barra não achou a barra")

    # A vista de Cargas: o que o caso aplica, clicável, com a resultante.
    janela.escolha_analise.setCurrentText("Cargas")
    janela.escolha_caso.setCurrentText("G")
    janela.redesenhar()
    if not vista._alvo_de_carga:
        raise RuntimeError("a vista de cargas não tem nada em que clicar")
    textos = [t for t, _ in vista._alvo_de_carga.values()]
    if not any(f"qz = {-w:+.2f} kN/m" in t for t in textos):
        raise RuntimeError("a carga distribuída da viga não está na vista")
    resumo = janela._texto_da_analise("Cargas")
    if f"Fz = {-w * L:+.2f} kN" not in resumo:
        raise RuntimeError(f"a resultante do caso não fechou: {resumo}")
    vista.renderer.SetWorldPoint(L / 2.0, 0.0, 0.0, 1.0)
    vista.renderer.WorldToDisplay()
    x_tela, y_tela, _ = vista.renderer.GetDisplayPoint()
    vista._picker.Pick(x_tela, y_tela, 0, vista.renderer)
    if vista._picker.GetActor() not in vista._alvo_de_carga:
        raise RuntimeError("o clique no meio da viga não achou carga nem barra")

    janela.close()
    return [f"janela: viga montada do zero pelas tabelas, My no vão = "
            f"{meio:.4f} = wL²/8",
            f"janela: clique no diagrama lê {esperado} no meio do vão, "
            "sem mexer na câmera",
            f"janela: vista de cargas confere a resultante Fz = {-w * L:+.2f} kN"]


def autoteste(destino: str) -> int:
    from portico3d.validacao import conferir

    os.makedirs(destino, exist_ok=True)
    conferencias = conferir(destino)

    largura = max(len(c.nome) for c in conferencias)
    falhas = 0
    for c in conferencias:
        marca = "OK    " if c.passou else "FALHOU"
        print(f"  {marca}  {c.nome:<{largura}}  "
              f"obtido {c.obtido:+.8e}  esperado {c.esperado:+.8e}  "
              f"erro {c.erro:.2e}")
        falhas += not c.passou

    print()
    if falhas:
        print(f"{falhas} de {len(conferencias)} conferências falharam.")
        return 1
    print(f"{len(conferencias)} conferências, todas dentro da tolerância.")

    try:
        for nota in conferir_janela(destino):
            print(f"  {nota}")
        for nota in conferir_montagem_pela_janela():
            print(f"  {nota}")
    except Exception as erro:               # noqa: BLE001 - relatar e falhar
        print(f"  FALHOU  a interface não montou: {erro}")
        return 1

    print(f"Arquivos do autoteste em: {destino}")
    return 0


def analisar(caminho: str, caso: str | None) -> int:
    from portico3d.arquivo import ler
    from portico3d.core.modelo import ErroDeModelo
    from portico3d.core.montagem import resolver

    try:
        modelo = ler(caminho)
        resultado = resolver(modelo, caso)
    except ErroDeModelo as erro:
        print(f"Erro no modelo: {erro}", file=sys.stderr)
        return 1

    print(resultado.resumo())
    return 0


def envoltoriar(caminho: str) -> int:
    from portico3d.arquivo import ler
    from portico3d.core.combinacoes import resolver_combinacoes
    from portico3d.core.envoltoria import envoltoria
    from portico3d.core.modelo import ErroDeModelo
    from portico3d.core.nbr6118 import (acoes_do_modelo, combinacoes_elu,
                                        combinacoes_els, validar_acoes)

    try:
        modelo = ler(caminho)
        acoes = acoes_do_modelo(modelo)
        validar_acoes(modelo, acoes)
        from portico3d.core.segunda_ordem_global import (
            resultados_para_dimensionamento, resumo)
        elu = combinacoes_elu(acoes)
        combinacoes = elu + combinacoes_els(acoes)
        resultados, tratamento = resultados_para_dimensionamento(modelo, elu)
        env = envoltoria(modelo, resultados)
    except ErroDeModelo as erro:
        print(f"Erro no modelo: {erro}", file=sys.stderr)
        return 1

    print(f"{len(modelo.casos)} casos, {len(combinacoes)} combinações "
          f"({sum(c.tipo == 'ELU' for c in combinacoes)} ELU, "
          f"{sum(c.tipo.startswith('ELS') for c in combinacoes)} ELS)")
    for c in combinacoes:
        fatores = "  ".join(f"{k}×{v:g}" for k, v in c.fatores.items())
        print(f"  {c.nome:<10} {fatores:<34} {c.descricao}")

    print("\n" + resumo(tratamento))
    print("\nEnvoltória ELU (com a 2ª ordem global) — extremos e esforços "
          "concomitantes")
    for nome, barra in env.items():
        print(f"\n  {nome}")
        for componente in ("N", "My", "Mz"):
            for tipo in ("max", "min"):
                print(f"    {barra.extremo(componente, tipo)}")
    return 0


def estabilidade(caminho: str) -> int:
    from portico3d.arquivo import ler
    from portico3d.core.estabilidade import gama_z
    from portico3d.core.combinacoes import caso_efetivo
    from portico3d.core.modelo import ErroDeModelo
    from portico3d.core.montagem import resolver
    from portico3d.core.nbr6118 import (acoes_do_modelo, combinacoes_elu,
                                        validar_acoes)
    from portico3d.core.segunda_ordem import flambagem

    try:
        modelo = ler(caminho)
        acoes = acoes_do_modelo(modelo)
        validar_acoes(modelo, acoes)
        combinacoes = combinacoes_elu(acoes)
    except ErroDeModelo as erro:
        print(f"Erro no modelo: {erro}", file=sys.stderr)
        return 1

    from portico3d.core.segunda_ordem_global import modelo_secante
    secante = modelo_secante(modelo)
    print("Estabilidade global — NBR 6118, itens 15.5.3 e 15.7.2, γz com a "
          "rigidez secante do 15.7.3\n")
    pior = None
    for combinacao in combinacoes:
        caso = caso_efetivo(secante, combinacao)
        secante.casos[caso.nome] = caso
        try:
            g = gama_z(secante, caso, resolver(secante, caso.nome))
        except ErroDeModelo as erro:
            print(f"  {combinacao.nome:<10} sem γz: {erro}")
            continue
        print(f"  {combinacao.nome:<10} γz = {g.valor:.4f}  "
              f"{'nós fixos' if g.nos_fixos else 'nós móveis'}"
              + ("" if g.majoracao_valida else "   [acima de 1,3]"))
        if pior is None or g.valor > pior[1].valor:
            pior = (caso.nome, g)

    if pior is None:
        print("\nNenhuma combinação tem ação horizontal para avaliar o γz.")
        return 0

    print(f"\nGovernante: {pior[0]}")
    print(pior[1])

    try:
        print("\n" + str(flambagem(modelo, pior[0])))
    except ErroDeModelo as erro:
        print(f"\nFlambagem não avaliada: {erro}")
    return 0


def janela(caminho: str | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    from portico3d.arquivo import ler
    from portico3d.core.modelo import ErroDeModelo
    from portico3d.ui.janela import Janela
    from portico3d.ui.tema import aplicar_tema_claro

    aplicacao = QApplication(sys.argv)
    aplicar_tema_claro(aplicacao)

    principal = Janela()
    if caminho:
        try:
            principal.modelo = ler(caminho)
            principal._carregar_nas_tabelas()
            principal.registrar(f"Aberto {caminho}.")
        except (ErroDeModelo, OSError, ValueError) as erro:
            principal.registrar(f"ERRO ao abrir {caminho}: {erro}")
    principal.show()
    return aplicacao.exec()


def main(argv: list[str]) -> int:
    if not argv:
        return janela()
    if "--janela" in argv:
        alvos = [a for a in argv if not a.startswith("--")]
        return janela(alvos[0] if alvos else None)
    if argv[0] == "--autoteste":
        destino = argv[1] if len(argv) > 1 else os.path.join(PASTA, "autoteste")
        return autoteste(destino)
    if "--envoltoria" in argv[1:]:
        return envoltoriar(argv[0])
    if "--estabilidade" in argv[1:]:
        return estabilidade(argv[0])
    return analisar(argv[0], argv[1] if len(argv) > 1 else None)


if __name__ == "__main__":
    # No executável do PyInstaller, cada processo filho (o pool dos pilares,
    # ``portico3d.cache_motores``, e o da busca do motor de Pilares) reexecuta
    # este arquivo; sem isto, o filho abriria o programa de novo em vez de
    # fazer a conta que lhe foi pedida
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main(sys.argv[1:]))
