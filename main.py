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

    janela.escolha_caso.setCurrentText("G")
    janela.analisar()
    if "G" not in janela.resultados:
        raise RuntimeError("a análise do caso G não produziu resultado")
    notas.append("janela: caso G analisado")

    janela.analisar_flambagem()
    janela.analisar_combinacoes()
    janela.analisar_estabilidade()
    notas.append("janela: combinações, estabilidade e flambagem percorridas")

    # ``dimensionar_lajes`` e ``dimensionar_vigas`` abrem diálogo de pasta, e
    # diálogo modal em modo offscreen fica esperando para sempre. O que se
    # prova aqui é a função por baixo, que é onde mora o cálculo; o botão em
    # si já é exercitado pelos outros que não pedem pasta.
    from portico3d.dimensionamento import cotas_com_laje, verificar_lajes
    cotas = cotas_com_laje(janela.modelo)
    lajes = verificar_lajes(janela.modelo)
    if not any(v.passou for v in lajes):
        raise RuntimeError("nenhum pavimento de laje foi dimensionado")
    notas.append(f"janela: {len(cotas)} pavimentos de laje dimensionados")

    antes = len(janela.relatorio.toPlainText())
    janela.dimensionar_pilares()
    if "Dimensionamento de pilares" not in janela.relatorio.toPlainText()[antes:]:
        raise RuntimeError("o dimensionamento de pilares não produziu relatório")
    notas.append("janela: pilares dimensionados pelo motor copiado")

    janela.escolha_caso.setCurrentText("G")
    antes = len(janela.relatorio.toPlainText())
    janela.mostrar_reacoes()
    texto = janela.relatorio.toPlainText()
    if "Reações" not in texto[antes:]:
        raise RuntimeError("a tabela de reações não foi para o relatório")
    notas.append("janela: tabela de reações emitida")

    for vista in ["Modelo", "3D", "Laje", "Armadura", "Deformada",
                  *VISTAS_DE_ESFORCO, "Modo de flambagem"]:
        janela.escolha_vista.setCurrentText(vista)
        janela.redesenhar()
    notas.append(f"janela: {len(VISTAS_DE_ESFORCO) + 6} vistas desenhadas")

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

    figura = os.path.join(destino, "janela.png")
    janela.vista.figure.savefig(figura, dpi=110, facecolor="white")
    notas.append(f"janela: figura gravada em {figura}")

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

    janela.close()
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

    janela.escolha_caso.setCurrentText("G")
    janela.analisar()
    resultado = janela.resultados.get("G")
    if resultado is None:
        raise RuntimeError("a análise da viga montada não produziu resultado")

    meio = resultado.diagrama("B1", 3).My[1]
    if abs(meio - w * L ** 2 / 8.0) > 1e-9:
        raise RuntimeError(f"momento no vão saiu {meio}, esperado "
                           f"{w * L ** 2 / 8.0}")

    janela.close()
    return [f"janela: viga montada do zero pelas tabelas, My no vão = "
            f"{meio:.4f} = wL²/8"]


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
        combinacoes = combinacoes_elu(acoes) + combinacoes_els(acoes)
        resultados = resolver_combinacoes(modelo, combinacoes)
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

    print("\nEnvoltória — extremos e esforços concomitantes")
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

    print("Estabilidade global — NBR 6118, itens 15.5.3 e 15.7.2\n")
    pior = None
    for combinacao in combinacoes:
        caso = caso_efetivo(modelo, combinacao)
        modelo.casos[caso.nome] = caso
        try:
            g = gama_z(modelo, caso, resolver(modelo, caso.nome))
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
    sys.exit(main(sys.argv[1:]))
