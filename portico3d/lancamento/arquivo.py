# -*- coding: utf-8 -*-
"""
arquivo.py
O lançamento em JSON — o arquivo que o editor de planta vai gravar e ler.

Distinto do arquivo do modelo de cálculo (``portico3d/arquivo.py``) pela
chave ``"tipo": "lancamento"``: abrir um arquivo de lançamento gera o modelo
de cálculo na hora, e o lançamento continua sendo a fonte.
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path

from ..core.modelo import ErroDeModelo, OpcoesDeCalculo
from .modelo import (Grelha, Lancamento, LajeLancada, ParedeLancada, Pavimento,
                     PilarLancado, Planta, VentoLancado, VigaLancada)

VERSAO = 1
TIPO = "lancamento"


def para_dicionario(lanc: Lancamento) -> dict:
    d = asdict(lanc)
    d["plantas"] = {nome: asdict(p) for nome, p in lanc.plantas.items()}
    d["cargas_de_laje"] = {n: list(v) for n, v in lanc.cargas_de_laje.items()}
    calculo = d.pop("calculo")
    calculo.pop("fator_rigidez_laje", None)
    d["calculo"] = calculo
    return {"versao": VERSAO, "tipo": TIPO, **d}


def _so_campos(cls, d: dict) -> dict:
    nomes = {f.name for f in fields(cls)}
    return {k: v for k, v in d.items() if k in nomes}


def de_dicionario(d: dict) -> Lancamento:
    if d.get("tipo") != TIPO:
        raise ErroDeModelo("o arquivo não é um lançamento")
    if d.get("versao", VERSAO) > VERSAO:
        raise ErroDeModelo(f"lançamento na versão {d['versao']}; este "
                           f"programa lê até a {VERSAO}")
    lanc = Lancamento(**_so_campos(Lancamento, {
        k: v for k, v in d.items()
        if k not in ("plantas", "pavimentos", "vento", "calculo",
                     "cargas_de_laje", "grelha")}))
    if d.get("grelha"):
        g = d["grelha"]
        lanc.grelha = Grelha(**{
            **_so_campos(Grelha, g),
            "espacos_colunas": [float(e) for e in g.get("espacos_colunas",
                                                        [])],
            "espacos_linhas": [float(e) for e in g.get("espacos_linhas",
                                                       [])]})
    for nome, p in d.get("plantas", {}).items():
        lanc.plantas[nome] = Planta(
            nome,
            pilares=[PilarLancado(**_so_campos(PilarLancado, x))
                     for x in p.get("pilares", [])],
            vigas=[VigaLancada(**{**_so_campos(VigaLancada, x),
                                  "pontos": [tuple(q) for q in x["pontos"]]})
                   for x in p.get("vigas", [])],
            lajes=[LajeLancada(**_so_campos(LajeLancada, x))
                   for x in p.get("lajes", [])],
            paredes=[ParedeLancada(**{**_so_campos(ParedeLancada, x),
                                      "pontos": [tuple(q)
                                                 for q in x["pontos"]]})
                     for x in p.get("paredes", [])])
    lanc.pavimentos = [Pavimento(**_so_campos(Pavimento, x))
                       for x in d.get("pavimentos", [])]
    lanc.vento = VentoLancado(**_so_campos(VentoLancado, d.get("vento", {})))
    lanc.calculo = OpcoesDeCalculo(**_so_campos(OpcoesDeCalculo,
                                                d.get("calculo", {})))
    lanc.cargas_de_laje = {n: tuple(v) for n, v in
                           d.get("cargas_de_laje", {}).items()}
    return lanc


def gravar(lanc: Lancamento, caminho) -> Path:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(para_dicionario(lanc), indent=2,
                                  ensure_ascii=False), encoding="utf-8")
    return caminho


def ler(caminho) -> Lancamento:
    try:
        return de_dicionario(json.loads(Path(caminho).read_text(
            encoding="utf-8")))
    except json.JSONDecodeError as erro:
        raise ErroDeModelo(f"JSON inválido em {caminho}: {erro}") from None


def e_lancamento(caminho) -> bool:
    """Se o arquivo é de lançamento (e não de modelo de cálculo)."""
    try:
        return json.loads(Path(caminho).read_text(
            encoding="utf-8")).get("tipo") == TIPO
    except (OSError, ValueError, AttributeError):
        return False
