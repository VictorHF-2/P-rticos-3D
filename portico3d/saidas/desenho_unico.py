# -*- coding: utf-8 -*-
"""
desenho_unico.py
As vigas dimensionadas num DXF só, uma abaixo da outra — o que a ação
"Dimensionar vigas" grava.

As pranchas do edifício (folhas com moldura, carimbo e vistas em escala,
forma e armação por pavimento) saem de ``pranchas.py``; daqui elas usavam
o mesmo encaixe, que era um DXF único com todas as peças lado a lado.

## Como o encaixe é feito

Cada desenho é gerado no seu próprio arquivo e importado inteiro para o
documento final, com as camadas que ele trouxe, e então **transladado** para a
sua vaga. As vagas saem da extensão real de cada desenho, medida depois de
importado, e não de um passo arbitrário.

**DXF, e não DWG**, pelo motivo de sempre: o DWG é binário e fechado, sem
especificação pública, e o ezdxf grava DXF — o formato de troca publicado, que
AutoCAD, BricsCAD e QCAD abrem sem conversão.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

#: Folga entre desenhos vizinhos, nas unidades do desenho (centímetros).
FOLGA = 150.0


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
    # a cota (DIMENSION) chega sem o bloco de geometria e o AUDIT do CAD a
    # apaga: explodida na origem, vira as linhas e os textos que desenha
    for cota in list(fonte.modelspace().query("DIMENSION")):
        try:
            cota.explode()
        except Exception:                                # noqa: BLE001
            continue
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


def montar_coluna_de_vigas(alvo, msp, pares, x_coluna: float = 0.0,
                          y_inicial: float = 0.0) -> tuple[float, int]:
    """Desenha uma viga por vaga, empilhadas numa coluna só.

    ``pares`` é uma lista de ``(nome, resultado)`` já dimensionados. Cada
    viga entra **sem PNG** — só o DXF é gerado, que é a metade do desenho que
    esta prancha de fato usa; a elevação e as seções em imagem, que ninguém
    abre aqui, custariam o render inteiro do matplotlib à toa.

    Não se acrescenta título aqui: o próprio DXF de cada viga já nasce com
    ``VIGA <nome> - DETALHAMENTO`` escrito no topo do desenho (ver
    ``vigas.saidas.dxf``), e repetir o rótulo por cima só duplicaria o texto.

    Devolve ``(largura_usada, quantidade desenhada)``, para quem chama saber
    onde termina a coluna e se algo saiu.
    """
    from ..dimensionamento import gravar_desenhos

    largura_maxima = 0.0
    y = y_inicial
    desenhadas = 0
    with tempfile.TemporaryDirectory(prefix="portico3d_vigas_") as temporaria:
        temp = Path(temporaria)
        for nome, resultado in pares:
            try:
                arquivos = gravar_desenhos(resultado, nome, temp,
                                           com_dxf=True, com_png=False)
            except Exception:                            # noqa: BLE001
                continue
            fontes = [Path(a) for a in arquivos
                      if isinstance(a, str) and a.endswith(".dxf")]
            if not fontes or not fontes[0].exists():
                continue
            tamanho = _importar(alvo, msp, fontes[0], x_coluna, y)
            if tamanho is None:
                continue
            largura_maxima = max(largura_maxima, tamanho[0])
            y -= tamanho[1] + FOLGA
            desenhadas += 1
    return largura_maxima, desenhadas


def montar_dxf_de_vigas(pares, caminho) -> Path:
    """A prancha só das vigas: uma coluna, lado a lado, tudo num DXF só.

    É o que a ação "Dimensionar vigas" grava — um arquivo, e não um par de
    PNG mais um DXF por viga. Mais rápido de gerar, porque poupa o desenho em
    matplotlib que ninguém abria, e mais fácil de levar à obra: uma prancha
    em vez de N arquivos soltos.
    """
    import ezdxf

    alvo = ezdxf.new("R2010", setup=True)
    if "PRANCHA" not in alvo.layers:
        alvo.layers.add("PRANCHA", color=7)
    msp = alvo.modelspace()
    montar_coluna_de_vigas(alvo, msp, pares)

    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    alvo.saveas(str(destino))
    return destino
