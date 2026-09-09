# -*- coding: utf-8 -*-
"""
desenho_unico.py
A prancha do edifício: um DXF com todas as peças detalhadas.

Cada motor de elemento já sabe desenhar a sua peça em CAD — a elevação e as
seções da viga, a planta de armação do pavimento, o corte do pilar. O que
faltava era juntar: num edifício de quatro pavimentos são dezenas de arquivos,
e o que se leva para a obra é uma prancha.

## Como o encaixe é feito

Cada desenho é gerado no seu próprio arquivo e importado inteiro para o
documento final, com as camadas que ele trouxe, e então **transladado** para a
sua vaga. As vagas saem da extensão real de cada desenho, medida depois de
importado, e não de um passo arbitrário — desenho de viga de três vãos é bem
mais largo que o de um vão, e um passo fixo ou os sobreporia ou deixaria meia
prancha vazia.

A organização é em colunas por tipo de peça: vigas numa faixa, pavimentos
noutra, pilares noutra. É como se lê uma prancha, e mantém junto o que se
confere junto.

**DXF, e não DWG**, pelo motivo de sempre: o DWG é binário e fechado, sem
especificação pública, e o ezdxf grava DXF — o formato de troca publicado, que
AutoCAD, BricsCAD e QCAD abrem sem conversão.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

#: Folga entre desenhos vizinhos, nas unidades do desenho (centímetros).
FOLGA = 150.0
#: Folga entre as colunas de tipos de peça.
FOLGA_COLUNA = 400.0


def _extensao(entidades):
    """Caixa envolvente de um punhado de entidades: (x0, y0, x1, y1)."""
    import ezdxf.bbox

    try:
        caixa = ezdxf.bbox.extents(entidades, fast=True)
    except Exception:                                    # noqa: BLE001
        return None
    if not caixa.has_data:
        return None
    return (caixa.extmin.x, caixa.extmin.y, caixa.extmax.x, caixa.extmax.y)


def _importar(alvo, msp, origem_dxf: Path, dx: float, dy: float):
    """Traz o desenho inteiro para a prancha, deslocado. Devolve a extensão."""
    import ezdxf
    from ezdxf.addons import Importer

    fonte = ezdxf.readfile(str(origem_dxf))
    antes = {id(e) for e in msp}
    importador = Importer(fonte, alvo)
    importador.import_modelspace()
    importador.finalize()
    novas = [e for e in msp if id(e) not in antes]
    if not novas:
        return None

    caixa = _extensao(novas)
    # o desenho vem com a origem dele; encosta-se o canto inferior esquerdo
    # na vaga, senão dois desenhos com origens diferentes se sobrepõem
    ox, oy = (caixa[0], caixa[1]) if caixa else (0.0, 0.0)
    for entidade in novas:
        try:
            entidade.translate(dx - ox, dy - oy, 0.0)
        except (AttributeError, TypeError):
            continue
    if caixa is None:
        return None
    return (caixa[2] - caixa[0], caixa[3] - caixa[1])


def _titulo(msp, texto: str, x: float, y: float, altura: float = 25.0) -> None:
    msp.add_text(texto, dxfattribs={"layer": "PRANCHA", "height": altura}
                 ).set_placement((x, y))


def _quadro(msp, projeto, x: float, y: float) -> None:
    """O quadro de quantidades, desenhado na própria prancha.

    Levar a prancha sem o quantitativo obriga a abrir a planilha ao lado; o
    quadro aqui é o resumo, não o detalhe — o detalhe está no Excel.
    """
    from .quantitativos import consolidar

    q = consolidar(projeto)
    linhas = [("QUADRO DE QUANTIDADES", "", "", ""),
              ("peça", "aço (kg)", "aço +10 %", "concreto (m³)")]
    for nome, d in q["por_elemento"].items():
        linhas.append((nome, f"{d['aco']:.1f}", f"{d['aco_perdas']:.1f}",
                       f"{d['concreto']:.3f}"))
    linhas.append(("TOTAL", f"{q['aco']:.1f}", f"{q['aco_perdas']:.1f}",
                   f"{q['concreto']:.3f}"))
    linhas.append(("", "", "", ""))
    linhas.append(("fôrmas: não quantificadas", "", "", ""))

    passo, colunas = 22.0, (0.0, 220.0, 340.0, 470.0)
    for i, linha in enumerate(linhas):
        for coluna, texto in zip(colunas, linha):
            if not texto:
                continue
            altura = 16.0 if i == 0 else 11.0
            msp.add_text(texto, dxfattribs={"layer": "QUADRO",
                                            "height": altura}
                         ).set_placement((x + coluna, y - i * passo))


def gerar(projeto, caminho) -> Path:
    """Grava a prancha única do edifício e devolve o caminho."""
    try:
        import ezdxf
    except ImportError as erro:                          # pragma: no cover
        raise RuntimeError("para gravar a prancha é preciso o ezdxf: "
                           "py -m pip install ezdxf") from erro

    from ..dimensionamento import gravar_desenhos, gravar_desenhos_de_laje

    alvo = ezdxf.new("R2010", setup=True)
    for camada, cor in (("PRANCHA", 7), ("QUADRO", 7)):
        if camada not in alvo.layers:
            alvo.layers.add(camada, color=cor)
    msp = alvo.modelspace()

    with tempfile.TemporaryDirectory(prefix="portico3d_") as temporaria:
        temp = Path(temporaria)
        x_coluna = 0.0

        # -- vigas ---------------------------------------------------------
        largura_maxima = 0.0
        y = 0.0
        desenhadas = 0
        for v in projeto.vigas:
            if not v.passou:
                continue
            try:
                arquivos = gravar_desenhos(v.resultado, v.nome, temp / "vigas",
                                           com_dxf=True)
            except Exception:                            # noqa: BLE001
                continue
            fontes = [Path(a) for a in arquivos
                      if isinstance(a, str) and a.endswith(".dxf")]
            if not fontes or not fontes[0].exists():
                continue
            _titulo(msp, f"VIGA {v.nome}", x_coluna, y + 40.0)
            tamanho = _importar(alvo, msp, fontes[0], x_coluna, y)
            if tamanho is None:
                continue
            largura_maxima = max(largura_maxima, tamanho[0])
            y -= tamanho[1] + FOLGA
            desenhadas += 1
        if desenhadas:
            x_coluna += largura_maxima + FOLGA_COLUNA

        # -- pavimentos de laje --------------------------------------------
        largura_maxima = 0.0
        y = 0.0
        for v in projeto.lajes:
            if not v.passou:
                continue
            try:
                arquivos = gravar_desenhos_de_laje(
                    v.resultado, v.cota, temp / "lajes", com_dxf=True)
            except Exception:                            # noqa: BLE001
                continue
            fontes = [Path(a) for a in arquivos
                      if isinstance(a, str) and a.endswith(".dxf")]
            if not fontes or not fontes[0].exists():
                continue
            _titulo(msp, f"PAVIMENTO — COTA {v.cota:g} m", x_coluna, y + 40.0)
            tamanho = _importar(alvo, msp, fontes[0], x_coluna, y)
            if tamanho is None:
                continue
            largura_maxima = max(largura_maxima, tamanho[0])
            y -= tamanho[1] + FOLGA
        if largura_maxima:
            x_coluna += largura_maxima + FOLGA_COLUNA

        # -- pilares -------------------------------------------------------
        largura_maxima = 0.0
        y = 0.0
        vistos = set()
        from ..elementos.pilares.saidas import dxf as dxf_pilar
        for v in projeto.pilares:
            if not v.aprovado or v.barra in vistos:
                continue
            vistos.add(v.barra)
            destino = temp / "pilares" / f"{v.barra}.dxf"
            destino.parent.mkdir(parents=True, exist_ok=True)
            try:
                dxf_pilar.exportar(v.resultado, str(destino))
            except Exception:                            # noqa: BLE001
                continue
            if not destino.exists():
                continue
            _titulo(msp, f"PILAR {v.barra}", x_coluna, y + 40.0)
            tamanho = _importar(alvo, msp, destino, x_coluna, y)
            if tamanho is None:
                continue
            largura_maxima = max(largura_maxima, tamanho[0])
            y -= tamanho[1] + FOLGA
        if largura_maxima:
            x_coluna += largura_maxima + FOLGA_COLUNA

    _quadro(msp, projeto, x_coluna, 0.0)
    _titulo(msp, (projeto.modelo.nome or "pórtico espacial").upper(),
            0.0, 140.0, altura=40.0)

    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    alvo.saveas(str(destino))
    return destino
