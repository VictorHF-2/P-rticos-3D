# -*- coding: utf-8 -*-
"""
armadura_dxf.py
A armadura do pavimento para o CAD, em três dimensões.

Cada barra de aço vira uma **polilinha 3D** no DXF, na camada da sua família,
com as coordenadas do modelo em metros. Não é uma planta: é o arame do
pavimento no espaço, que é justamente o que a vista de Armadura mostra e o que
não cabe numa folha.

**DXF, e não DWG**, pela mesma razão de sempre: o DWG é binário e fechado, sem
especificação pública, e a biblioteca de CAD daqui (ezdxf) grava DXF — que é o
formato de troca publicado e que AutoCAD, BricsCAD e QCAD abrem sem conversão.

A fôrma vai junto, na camada ``FORMA``, e é só o contorno: as quatro arestas
de cada pilar e de cada viga, e o retângulo de cada laje. Sem ela a armadura
flutua no vazio e não há como conferir cobrimento nenhum; com a seção inteira
sólida, o arquivo dobraria de tamanho para mostrar o que a fôrma já mostra.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .armadura3d import ArmaduraDoPavimento
from .core.modelo import ErroDeModelo, Modelo

#: Camada e cor (índice ACI) de cada família de armadura.
CAMADAS = {
    "pilar longitudinal": ("ARM-PILAR", 1),
    "pilar estribo": ("ARM-PILAR-EST", 6),
    "viga longitudinal": ("ARM-VIGA", 3),
    "viga estribo": ("ARM-VIGA-EST", 4),
    "laje positiva": ("ARM-LAJE-POS", 5),
    "laje negativa": ("ARM-LAJE-NEG", 2),
}
CAMADA_FORMA = ("FORMA", 8)


def arestas_da_forma(modelo: Modelo, cota: float) -> list[np.ndarray]:
    """O contorno de concreto do pavimento: pilares, vigas e lajes.

    Só arestas. Da barra saem as quatro longitudinais mais os dois retângulos
    de topo; da laje, o retângulo de cima e o de baixo. É o bastante para
    situar a armadura e para medir cobrimento no CAD.
    """
    from .armadura3d import lances_do_pavimento, vigas_do_pavimento
    from .core.lajes import _cantos
    from .core.montagem import preparar_barras

    alvos = list(lances_do_pavimento(modelo, cota))
    for viga in vigas_do_pavimento(modelo, cota):
        alvos.extend(viga.barras)

    try:
        preparadas = preparar_barras(modelo)
    except ErroDeModelo:
        return []

    saida: list[np.ndarray] = []
    for nome in alvos:
        p = preparadas.get(nome)
        if p is None:
            continue
        barra = modelo.barras[nome]
        secao = modelo.secoes[barra.secao]
        if secao.b <= 0.0 or secao.h <= 0.0:
            continue
        pi, pj = modelo.ponto(barra.no_i), modelo.ponto(barra.no_j)
        ey, ez = p.R[1], p.R[2]
        cantos = [(-secao.b / 2, -secao.h / 2), (secao.b / 2, -secao.h / 2),
                  (secao.b / 2, secao.h / 2), (-secao.b / 2, secao.h / 2)]
        inicio = [pi + u * ey + v * ez for u, v in cantos]
        fim = [pj + u * ey + v * ez for u, v in cantos]
        saida.append(np.array(inicio + [inicio[0]]))
        saida.append(np.array(fim + [fim[0]]))
        saida.extend(np.array([a, b]) for a, b in zip(inicio, fim))

    for laje in modelo.lajes.values():
        if abs(float(modelo.ponto(laje.no_a)[2]) - cota) > 1e-6:
            continue
        try:
            cantos, _, _ = _cantos(modelo, laje)
        except ErroDeModelo:
            continue
        base = np.array([modelo.ponto(c) for c in cantos])
        meia = max(laje.espessura, 0.01) / 2.0
        for sinal in (-1.0, 1.0):
            face = base + np.array([0.0, 0.0, sinal * meia])
            saida.append(np.vstack([face, face[:1]]))
    return saida


def exportar(armadura: ArmaduraDoPavimento, caminho: str | Path,
             modelo: Modelo | None = None, forma: bool = True) -> Path:
    """Grava a armadura do pavimento como polilinhas 3D num DXF.

    ``modelo`` só é preciso para a fôrma; sem ele, sai a armadura sozinha.
    Devolve o caminho gravado, e levanta ``ErroDeModelo`` se o ezdxf não
    estiver instalado — falhar dizendo o que falta é melhor que gravar um
    arquivo vazio.
    """
    try:
        import ezdxf
    except ImportError as erro:                      # pragma: no cover
        raise ErroDeModelo(
            "para exportar em DXF é preciso o ezdxf: "
            "py -m pip install ezdxf") from erro

    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6                      # metros
    for nome, cor in list(CAMADAS.values()) + [CAMADA_FORMA]:
        if nome not in doc.layers:
            doc.layers.add(nome, color=cor)
    msp = doc.modelspace()

    if forma and modelo is not None:
        for linha in arestas_da_forma(modelo, armadura.cota):
            msp.add_polyline3d([tuple(float(c) for c in p) for p in linha],
                               dxfattribs={"layer": CAMADA_FORMA[0]})

    for fio in armadura.fios:
        camada = CAMADAS.get(fio.familia, CAMADA_FORMA)[0]
        msp.add_polyline3d([tuple(float(c) for c in p) for p in fio.pontos],
                           dxfattribs={"layer": camada})

    doc.saveas(destino)
    return destino


def contar_entidades(caminho: str | Path) -> int:
    """Quantas entidades o arquivo tem, lendo-o de volta.

    Ler de volta é o que distingue "gravou um arquivo" de "gravou um desenho".
    """
    import ezdxf

    return len(ezdxf.readfile(str(caminho)).modelspace())
