# -*- coding: utf-8 -*-
"""
mastan.py
Leitura de modelos do MASTAN2 (.mat) e comparação de resultados.

Existe para aferição: o MASTAN2 é a referência que este programa se propõe a
substituir, e a maneira honesta de sustentar isso é resolver os mesmos modelos
e comparar número a número. O arquivo do MASTAN guarda, além do modelo, os
deslocamentos, as reações e os esforços de extremidade que ele mesmo calculou,
de modo que a comparação não depende de transcrever nada à mão.

O formato não é documentado aqui por adivinhação: cada campo abaixo foi
confirmado por conferência numérica contra os próprios arquivos — em
particular o equilíbrio vertical, que fecha ao último dígito quando o peso
próprio automático é incluído.

## O que foi decifrado

``node_info``   colunas 1-3: coordenadas. As demais são handles do MATLAB.
``elem_info``   1-2 nós, 3 seção, 4 material, **8-10 o eixo local y**.
``sect_info``   1 A, 2 Izz, 3 Iyy, 4 J.
``mat_info``    1 E, 2 ν, 3 Fy, **4 peso específico**.
``fixity_info`` 0 onde há vínculo, NaN onde é livre.
``nload_info``  1-6 Fx Fy Fz Mx My Mz no sistema global.
``uniload_info`` 1-3 wx wy wz nos eixos **locais** da barra.
``defl``/``react`` por nó, no global; ``ele_for`` por barra, no local.

## Os dois sistemas de eixos

No MASTAN2 o vertical é **Y**; aqui é **Z**. A conversão é a permutação
cíclica ``(x, y, z) → (z, x, y)``, escolhida entre as seis possíveis por ser
**rotação e não reflexão**: qualquer permutação ímpar inverteria a mão do
sistema, e com ela o sinal de toda torção e de todo momento. Vetores e
coordenadas passam pela mesma permutação.

Grandezas **locais** — carga distribuída em eixos de barra, esforços de
extremidade — não passam por conversão nenhuma, desde que os eixos locais
sejam alinhados na importação. É o que o vetor de referência faz.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .core.cargas import peso_proprio
from .core.modelo import ErroDeModelo, Modelo, Secao

# Peso próprio: o MASTAN2 o gera do peso específico do material, sem que ele
# apareça na tabela de cargas distribuídas.
COL_PESO_ESPECIFICO = 3


def _permutar(v) -> np.ndarray:
    """(x, y, z) do MASTAN → (z, x, y) daqui. Rotação, não reflexão."""
    a = np.asarray(v, float)
    return np.array([a[2], a[0], a[1]])


def _permutar_seis(v) -> np.ndarray:
    """Idem para um vetor de seis componentes: três de força, três de momento."""
    a = np.asarray(v, float)
    return np.concatenate([_permutar(a[:3]), _permutar(a[3:6])])


@dataclass
class ModeloMastan:
    """O modelo lido e, quando houver, os resultados que o MASTAN gravou."""

    modelo: Modelo
    caso: str
    nos: list[str]
    barras: list[str]
    deslocamentos: np.ndarray | None = None
    reacoes: np.ndarray | None = None
    esforcos: np.ndarray | None = None
    peso_proprio_incluido: bool = False
    avisos: list[str] = field(default_factory=list)


def ler_mat(caminho, caso: str = "MASTAN") -> ModeloMastan:
    """Lê um arquivo do MASTAN2 e monta o modelo equivalente."""
    try:
        from scipy.io import loadmat
    except ImportError:  # pragma: no cover - scipy é dependência declarada
        raise ErroDeModelo("a leitura de arquivos do MASTAN2 precisa do scipy")

    d = loadmat(str(caminho), struct_as_record=False)
    for campo in ("node_info", "elem_info", "sect_info", "mat_info"):
        if campo not in d:
            raise ErroDeModelo(
                f"'{caminho}' não parece um modelo do MASTAN2: falta "
                f"'{campo}'")

    titulo = str(d.get("model_title", ["MASTAN"])[0])
    m = Modelo(titulo)
    avisos: list[str] = []

    # -- materiais e seções -------------------------------------------------
    mat_info = np.atleast_2d(d["mat_info"])
    nomes_mat = _nomes(d.get("mat_name"), len(mat_info), "material")
    for i, linha in enumerate(mat_info):
        m.add_material(nomes_mat[i], float(linha[0]), float(linha[1]),
                       float(linha[COL_PESO_ESPECIFICO]))

    sect_info = np.atleast_2d(d["sect_info"])
    nomes_sec = _nomes(d.get("sect_name"), len(sect_info), "seção")
    for i, linha in enumerate(sect_info):
        # MASTAN: [A, Izz, Iyy, J]. O Izz dele é o nosso Iz e o Iyy o nosso Iy
        # — os dois programas nomeiam a inércia pelo eixo em torno do qual ela
        # atua, então os nomes já correspondem.
        m.add_secao(Secao(nomes_sec[i], float(linha[0]), float(linha[2]),
                          float(linha[1]), float(linha[3])))

    # -- nós ----------------------------------------------------------------
    node_info = np.atleast_2d(d["node_info"])
    nos = []
    for i, linha in enumerate(node_info):
        nome = f"N{i + 1}"
        x, y, z = _permutar(linha[:3])
        m.add_no(nome, float(x), float(y), float(z))
        nos.append(nome)

    # -- barras -------------------------------------------------------------
    elem_info = np.atleast_2d(d["elem_info"])
    barras = []
    for i, linha in enumerate(elem_info):
        nome = f"E{i + 1}"
        no_i, no_j = nos[int(linha[0]) - 1], nos[int(linha[1]) - 1]
        secao = nomes_sec[int(linha[2]) - 1]
        material = nomes_mat[int(linha[3]) - 1]

        # O vetor de referência é escolhido para que o nosso eixo local y caia
        # exatamente sobre o do MASTAN: com ``ey = vr × ex``, basta tomar
        # ``vr = ex × ey``, porque (ex × ey) × ex devolve ey.
        eixo_y = _permutar(linha[7:10])
        p_i, p_j = m.ponto(no_i), m.ponto(no_j)
        ex = (p_j - p_i) / np.linalg.norm(p_j - p_i)
        if np.linalg.norm(eixo_y) < 1e-9:
            avisos.append(f"barra {nome}: sem eixo local no arquivo; "
                          "usada a orientação padrão")
            vetor_ref = None
        else:
            eixo_y = eixo_y / np.linalg.norm(eixo_y)
            vetor_ref = tuple(float(c) for c in np.cross(ex, eixo_y))

        m.add_barra(nome, no_i, no_j, material, secao, vetor_ref=vetor_ref)
        barras.append(nome)

    # -- vínculos -----------------------------------------------------------
    fixity = np.atleast_2d(d["fixity_info"])[:, :6]
    for i, linha in enumerate(fixity):
        preso = ~np.isnan(linha)
        if not preso.any():
            continue
        travas = _permutar_seis(np.where(preso, 1.0, 0.0)) > 0.5
        m.apoiar(nos[i], *[bool(t) for t in travas])
        if np.any(np.nan_to_num(linha) != 0.0):
            avisos.append(
                f"nó {nos[i]}: o arquivo traz deslocamento prescrito no "
                "vínculo, que não foi importado")

    # -- cargas -------------------------------------------------------------
    caso_de_carga = m.add_caso(caso, "permanente")

    nload = np.nan_to_num(np.atleast_2d(d.get(
        "nload_info", np.zeros((len(nos), 6))))[:, :6])
    for i, linha in enumerate(nload):
        if not np.any(linha):
            continue
        f = _permutar_seis(linha)
        caso_de_carga.nodal(nos[i], *[float(c) for c in f])

    uniload = np.nan_to_num(np.atleast_2d(d.get(
        "uniload_info", np.zeros((len(barras), 6))))[:, :6])
    for i, linha in enumerate(uniload):
        if not np.any(linha[:3]):
            continue
        # Carga em eixos locais: como os eixos foram alinhados na importação,
        # ela entra sem conversão nenhuma.
        caso_de_carga.distribuida(barras[i], qx=float(linha[0]),
                                  qy=float(linha[1]), qz=float(linha[2]),
                                  sistema="local")
        if np.any(linha[3:6]):
            avisos.append(f"barra {barras[i]}: momento distribuído no "
                          "arquivo, que este programa não representa")

    peso = any(mat.peso_especifico != 0.0 for mat in m.materiais.values())
    if peso:
        peso_proprio(m, caso_de_carga)

    settle = np.atleast_2d(d.get("settle_info", np.zeros((1, 6))))[:, :6]
    if np.any(np.nan_to_num(settle) != 0.0):
        avisos.append("o arquivo traz recalques, que não foram importados")

    m.validar()

    return ModeloMastan(
        modelo=m, caso=caso, nos=nos, barras=barras,
        deslocamentos=(_permuta_linhas(d["defl"]) if "defl" in d else None),
        reacoes=(_permuta_linhas(d["react"]) if "react" in d else None),
        esforcos=(np.nan_to_num(d["ele_for"])[:, :12]
                  if "ele_for" in d else None),
        peso_proprio_incluido=peso, avisos=avisos)


def _permuta_linhas(bruto: np.ndarray) -> np.ndarray:
    dados = np.nan_to_num(np.atleast_2d(bruto))[:, :6]
    return np.array([_permutar_seis(linha) for linha in dados])


def _nomes(bruto, quantidade: int, rotulo: str) -> list[str]:
    if bruto is None:
        return [f"{rotulo}{i + 1}" for i in range(quantidade)]
    achatado = np.atleast_2d(bruto).ravel()
    nomes = []
    for i in range(quantidade):
        try:
            nomes.append(str(np.atleast_1d(achatado[i])[0]))
        except (IndexError, TypeError):
            nomes.append(f"{rotulo}{i + 1}")
    # Nome repetido viraria a mesma entrada no dicionário do modelo.
    vistos: dict[str, int] = {}
    unicos = []
    for nome in nomes:
        if nome in vistos:
            vistos[nome] += 1
            nome = f"{nome} ({vistos[nome]})"
        else:
            vistos[nome] = 0
        unicos.append(nome)
    return unicos
