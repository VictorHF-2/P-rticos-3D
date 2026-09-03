# -*- coding: utf-8 -*-
"""
arquivo.py
Leitura e gravação do modelo em JSON.

O arquivo é a fronteira do programa: é por ele que entram os modelos vindos
de planilha, de CAD ou de outro programa, e é ele que o orquestrador vai ler
quando o solver for acoplado aos programas de elemento. Por isso a leitura
valida os campos em vez de confiar no que vem escrito.
"""

from __future__ import annotations

import json
from pathlib import Path

from .core.modelo import (Apoio, CargaDistribuida, CargaNodal, CasoDeCarga,
                          ErroDeModelo, Modelo, Recalque, Secao)

VERSAO = 1


def _exigir(d: dict, campo: str, contexto: str):
    if campo not in d:
        raise ErroDeModelo(f"{contexto}: falta o campo '{campo}'")
    return d[campo]


def para_dicionario(modelo: Modelo) -> dict:
    return {
        "versao": VERSAO,
        "nome": modelo.nome,
        "unidades": "kN, m",
        "materiais": [{"nome": m.nome, "E": m.E, "poisson": m.poisson,
                       "peso_especifico": m.peso_especifico, "tipo": m.tipo,
                       "fck": m.fck, "agregado": m.agregado,
                       "modulo": m.modulo}
                      for m in modelo.materiais.values()],
        "secoes": [{"nome": s.nome, "A": s.A, "Iy": s.Iy, "Iz": s.Iz,
                    "J": s.J, "Asy": s.Asy, "Asz": s.Asz,
                    "tipo": s.tipo, "b": s.b, "h": s.h}
                   for s in modelo.secoes.values()],
        "nos": [{"nome": n.nome, "x": n.x, "y": n.y, "z": n.z}
                for n in modelo.nos.values()],
        "barras": [{"nome": b.nome, "no_i": b.no_i, "no_j": b.no_j,
                    "material": b.material, "secao": b.secao,
                    "rotacao": b.rotacao,
                    "vetor_ref": list(b.vetor_ref) if b.vetor_ref else None,
                    "liberacoes_i": list(b.liberacoes_i),
                    "liberacoes_j": list(b.liberacoes_j),
                    "offset_i": b.offset_i, "offset_j": b.offset_j}
                   for b in modelo.barras.values()],
        "apoios": [{"no": a.no, "ux": a.ux, "uy": a.uy, "uz": a.uz,
                    "rx": a.rx, "ry": a.ry, "rz": a.rz}
                   for a in modelo.apoios.values()],
        "molas": [{"no": m.no, "kx": m.kx, "ky": m.ky, "kz": m.kz,
                   "krx": m.krx, "kry": m.kry, "krz": m.krz}
                  for m in modelo.molas.values()],
        "lajes": [{"nome": l.nome, "no_a": l.no_a, "no_c": l.no_c,
                   "espessura": l.espessura, "material": l.material,
                   "permanente": l.permanente, "acidental": l.acidental}
                  for l in modelo.lajes.values()],
        "casos": [{"nome": c.nome, "natureza": c.natureza,
                   "categoria": c.categoria, "grupo": c.grupo,
                   "nodais": [{"no": q.no, "fx": q.fx, "fy": q.fy, "fz": q.fz,
                               "mx": q.mx, "my": q.my, "mz": q.mz}
                              for q in c.nodais],
                   "distribuidas": [{"barra": q.barra, "qx": q.qx, "qy": q.qy,
                                     "qz": q.qz, "sistema": q.sistema,
                                     "inicio": q.inicio, "fim": q.fim,
                                     "qx_fim": q.qx_fim, "qy_fim": q.qy_fim,
                                     "qz_fim": q.qz_fim}
                                    for q in c.distribuidas],
                   "recalques": [{"no": r.no, "ux": r.ux, "uy": r.uy,
                                  "uz": r.uz, "rx": r.rx, "ry": r.ry,
                                  "rz": r.rz}
                                 for r in c.recalques]}
                  for c in modelo.casos.values()],
    }


def de_dicionario(d: dict) -> Modelo:
    versao = d.get("versao", VERSAO)
    if versao > VERSAO:
        raise ErroDeModelo(
            f"arquivo na versão {versao}; este programa lê até a {VERSAO}")

    modelo = Modelo(nome=d.get("nome", "modelo"))

    for m in d.get("materiais", []):
        modelo.add_material(_exigir(m, "nome", "material"),
                            float(_exigir(m, "E", "material")),
                            float(m.get("poisson", 0.2)),
                            float(m.get("peso_especifico", 0.0)),
                            m.get("tipo", "generico"),
                            float(m.get("fck", 0.0)),
                            m.get("agregado", ""),
                            m.get("modulo", ""))

    for s in d.get("secoes", []):
        ctx = "seção"
        modelo.add_secao(Secao(_exigir(s, "nome", ctx),
                               float(_exigir(s, "A", ctx)),
                               float(_exigir(s, "Iy", ctx)),
                               float(_exigir(s, "Iz", ctx)),
                               float(_exigir(s, "J", ctx)),
                               float(s.get("Asy", 0.0)),
                               float(s.get("Asz", 0.0)),
                               s.get("tipo", "generica"),
                               float(s.get("b", 0.0)),
                               float(s.get("h", 0.0))))

    for n in d.get("nos", []):
        ctx = "nó"
        modelo.add_no(_exigir(n, "nome", ctx), float(_exigir(n, "x", ctx)),
                      float(_exigir(n, "y", ctx)), float(_exigir(n, "z", ctx)))

    for b in d.get("barras", []):
        ctx = "barra"
        ref = b.get("vetor_ref")
        modelo.add_barra(_exigir(b, "nome", ctx), _exigir(b, "no_i", ctx),
                         _exigir(b, "no_j", ctx), _exigir(b, "material", ctx),
                         _exigir(b, "secao", ctx), float(b.get("rotacao", 0.0)),
                         tuple(float(v) for v in ref) if ref else None,
                         tuple(b.get("liberacoes_i", ())),
                         tuple(b.get("liberacoes_j", ())),
                         float(b.get("offset_i", 0.0)),
                         float(b.get("offset_j", 0.0)))

    for a in d.get("apoios", []):
        modelo.apoios[_exigir(a, "no", "apoio")] = Apoio(
            a["no"], bool(a.get("ux", True)), bool(a.get("uy", True)),
            bool(a.get("uz", True)), bool(a.get("rx", True)),
            bool(a.get("ry", True)), bool(a.get("rz", True)))

    for m in d.get("molas", []):
        modelo.add_mola(_exigir(m, "no", "mola"), float(m.get("kx", 0.0)),
                        float(m.get("ky", 0.0)), float(m.get("kz", 0.0)),
                        float(m.get("krx", 0.0)), float(m.get("kry", 0.0)),
                        float(m.get("krz", 0.0)))

    for l in d.get("lajes", []):
        ctx = "laje"
        modelo.add_laje(_exigir(l, "nome", ctx), _exigir(l, "no_a", ctx),
                        _exigir(l, "no_c", ctx),
                        float(l.get("espessura", 0.0)),
                        l.get("material", ""),
                        float(l.get("permanente", 0.0)),
                        float(l.get("acidental", 0.0)))

    for c in d.get("casos", []):
        caso = CasoDeCarga(_exigir(c, "nome", "caso de carga"),
                           natureza=c.get("natureza", "permanente"),
                           categoria=c.get("categoria", ""),
                           grupo=c.get("grupo", ""))
        for q in c.get("nodais", []):
            caso.nodais.append(CargaNodal(
                _exigir(q, "no", "carga nodal"),
                float(q.get("fx", 0.0)), float(q.get("fy", 0.0)),
                float(q.get("fz", 0.0)), float(q.get("mx", 0.0)),
                float(q.get("my", 0.0)), float(q.get("mz", 0.0))))
        for q in c.get("distribuidas", []):
            def opcional(campo):
                valor = q.get(campo)
                return None if valor is None else float(valor)

            caso.distribuidas.append(CargaDistribuida(
                _exigir(q, "barra", "carga distribuída"),
                float(q.get("qx", 0.0)), float(q.get("qy", 0.0)),
                float(q.get("qz", 0.0)), q.get("sistema", "local"),
                float(q.get("inicio", 0.0)), float(q.get("fim", 1.0)),
                opcional("qx_fim"), opcional("qy_fim"), opcional("qz_fim")))
        for r in c.get("recalques", []):
            caso.recalques.append(Recalque(
                _exigir(r, "no", "recalque"), float(r.get("ux", 0.0)),
                float(r.get("uy", 0.0)), float(r.get("uz", 0.0)),
                float(r.get("rx", 0.0)), float(r.get("ry", 0.0)),
                float(r.get("rz", 0.0))))
        modelo.casos[caso.nome] = caso

    modelo.validar()
    return modelo


def gravar(modelo: Modelo, caminho: str | Path) -> Path:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(para_dicionario(modelo), indent=2, ensure_ascii=False),
        encoding="utf-8")
    return caminho


def ler(caminho: str | Path) -> Modelo:
    texto = Path(caminho).read_text(encoding="utf-8")
    try:
        return de_dicionario(json.loads(texto))
    except json.JSONDecodeError as erro:
        raise ErroDeModelo(f"JSON inválido em {caminho}: {erro}") from None
