# -*- coding: utf-8 -*-
"""
conversao.py
Traduz o modelo para as linhas das tabelas e de volta.

Fica separado das tabelas de propósito: aqui mora o conhecimento do modelo, e
lá o dos widgets. A volta monta um modelo **novo** em vez de alterar o que
está em uso, para que uma tabela pela metade nunca deixe um modelo válido
corrompido — se a leitura falhar, o modelo anterior segue intacto.
"""

from __future__ import annotations

from ..core.concreto import concreto, fck_da_classe
from ..core.modelo import ErroDeModelo, Modelo, Secao


def _lista(texto: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in str(texto).split(",") if p.strip())


def modelo_para_registros(modelo: Modelo) -> dict[str, list[dict]]:
    nodais, distribuidas, recalques = [], [], []
    for caso in modelo.casos.values():
        for c in caso.nodais:
            nodais.append({"caso": caso.nome, "no": c.no, "fx": c.fx,
                           "fy": c.fy, "fz": c.fz, "mx": c.mx, "my": c.my,
                           "mz": c.mz})
        for c in caso.distribuidas:
            distribuidas.append({"caso": caso.nome, "barra": c.barra,
                                 "qx": c.qx, "qy": c.qy, "qz": c.qz,
                                 "sistema": c.sistema, "inicio": c.inicio,
                                 "fim": c.fim, "qx_fim": c.qx_fim,
                                 "qy_fim": c.qy_fim, "qz_fim": c.qz_fim,
                                 "origem": c.origem})
        for c in caso.recalques:
            recalques.append({"caso": caso.nome, "no": c.no, "ux": c.ux,
                              "uy": c.uy, "uz": c.uz, "rx": c.rx,
                              "ry": c.ry, "rz": c.rz})

    return {
        "materiais": [{"nome": m.nome, "tipo": m.tipo,
                       "classe": (f"C{m.fck:g}" if m.fck else ""),
                       "agregado": m.agregado, "modulo": m.modulo, "E": m.E,
                       "poisson": m.poisson,
                       "peso_especifico": m.peso_especifico}
                      for m in modelo.materiais.values()],
        "secoes": [{"nome": s.nome, "tipo": s.tipo, "b": s.b, "h": s.h,
                    "cortante": s.cortante, "A": s.A, "Iy": s.Iy, "Iz": s.Iz,
                    "J": s.J, "Asy": s.Asy, "Asz": s.Asz}
                   for s in modelo.secoes.values()],
        "nos": [{"nome": n.nome, "x": n.x, "y": n.y, "z": n.z}
                for n in modelo.nos.values()],
        "barras": [{"nome": b.nome, "no_i": b.no_i, "no_j": b.no_j,
                    "material": b.material, "secao": b.secao,
                    "rotacao": b.rotacao,
                    "liberacoes_i": ", ".join(b.liberacoes_i),
                    "liberacoes_j": ", ".join(b.liberacoes_j),
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
                   "tipo_carga": l.tipo_carga,
                   "permanente": l.permanente, "acidental": l.acidental,
                   "tipo": l.tipo, "direcao": l.direcao,
                   "trelica": l.trelica, "enchimento": l.enchimento,
                   "altura_enchimento": l.altura_enchimento,
                   "capa": l.capa, "largura_bloco": l.largura_bloco,
                   "base_vigota": l.base_vigota,
                   "balanco": l.balanco, "sentido": l.sentido}
                  for l in modelo.lajes.values()],
        "cargas_lajes": [{"nome": t.nome, "permanente": t.permanente,
                          "acidental": t.acidental, "descricao": t.descricao}
                         for t in modelo.cargas_de_laje.values()],
        "casos": [{"nome": c.nome, "natureza": c.natureza,
                   "categoria": c.categoria, "grupo": c.grupo}
                  for c in modelo.casos.values()],
        "nodais": nodais,
        "distribuidas": distribuidas,
        "recalques": recalques,
    }


def registros_para_modelo(registros: dict[str, list[dict]],
                          nome: str = "portico") -> Modelo:
    modelo = Modelo(nome)

    for r in registros["materiais"]:
        # Concreto declarado por classe é refeito da classe, e não lido da
        # coluna de módulo: assim o que vale é sempre o fck digitado, pelo
        # mesmo motivo que a seção retangular é refeita dos lados.
        if r["tipo"] == "concreto":
            try:
                fck = fck_da_classe(r["classe"])
            except ErroDeModelo as erro:
                raise ErroDeModelo(
                    f"material '{r['nome']}': {erro}. Informe a classe, ou "
                    "mude o tipo para 'generico' e digite o E") from None
            modelo.materiais[r["nome"]] = concreto(
                r["nome"], fck, r["agregado"] or None,
                r["modulo"] or "Ecs", r["peso_especifico"] or None)
        else:
            modelo.add_material(r["nome"], r["E"], r["poisson"],
                                r["peso_especifico"])
    for r in registros["secoes"]:
        # A seção calculável é refeita a partir dos lados, e não lida das
        # colunas de propriedade: assim o que vale é sempre a dimensão
        # digitada, mesmo que a coluna calculada tenha ficado para trás.
        if r["tipo"] in ("retangular", "circular"):
            modelo.add_secao(Secao.criar(r["nome"], r["tipo"], r["b"], r["h"],
                                         r["cortante"]))
        else:
            modelo.add_secao(Secao(r["nome"], r["A"], r["Iy"], r["Iz"],
                                   r["J"], r["Asy"], r["Asz"]))
    for r in registros["nos"]:
        modelo.add_no(r["nome"], r["x"], r["y"], r["z"])
    for r in registros["barras"]:
        modelo.add_barra(r["nome"], r["no_i"], r["no_j"], r["material"],
                         r["secao"], r["rotacao"], None,
                         _lista(r["liberacoes_i"]), _lista(r["liberacoes_j"]),
                         r["offset_i"], r["offset_j"])
    for r in registros["apoios"]:
        modelo.apoiar(r["no"], r["ux"], r["uy"], r["uz"], r["rx"], r["ry"],
                      r["rz"])
    for r in registros["molas"]:
        modelo.add_mola(r["no"], r["kx"], r["ky"], r["kz"], r["krx"],
                        r["kry"], r["krz"])

    # Os tipos de carga entram antes das lajes: uma laje pode citar um tipo
    # que ainda não existiria se a ordem fosse a outra.
    for r in registros.get("cargas_lajes", []):
        modelo.add_carga_de_laje(r["nome"], r["permanente"], r["acidental"],
                                 r.get("descricao", ""))

    for r in registros["lajes"]:
        modelo.add_laje(r["nome"], r["no_a"], r["no_c"], r["espessura"],
                        r["material"], r["permanente"], r["acidental"],
                        r.get("tipo_carga", ""),
                        tipo=(r.get("tipo") or "macica").strip(),
                        direcao=(r.get("direcao") or "x").strip(),
                        trelica=(r.get("trelica") or "TR 12646").strip(),
                        enchimento=(r.get("enchimento") or "EPS").strip(),
                        altura_enchimento=r.get("altura_enchimento") or 0.0,
                        capa=r.get("capa") or 0.0,
                        largura_bloco=r.get("largura_bloco") or 0.40,
                        base_vigota=r.get("base_vigota") or 0.12,
                        balanco=r.get("balanco") or 0.0,
                        sentido=(r.get("sentido") or "").strip())
    # Uma laje com tipo_carga tem os valores do tipo, não os digitados nela —
    # é a mesma regra de "a seção vem dos lados": o tipo é a fonte.
    modelo.aplicar_cargas_de_laje()

    for r in registros["casos"]:
        modelo.add_caso(r["nome"], r["natureza"] or "permanente",
                        r["categoria"], r["grupo"])

    for r in registros["nodais"]:
        _caso(modelo, r["caso"]).nodal(r["no"], r["fx"], r["fy"], r["fz"],
                                       r["mx"], r["my"], r["mz"])
    for r in registros["distribuidas"]:
        _caso(modelo, r["caso"]).distribuida(
            r["barra"], r["qx"], r["qy"], r["qz"], r["sistema"] or "local",
            r["inicio"], r["fim"] if r["fim"] else 1.0,
            r["qx_fim"], r["qy_fim"], r["qz_fim"],
            str(r.get("origem", "") or "").strip())
    for r in registros["recalques"]:
        _caso(modelo, r["caso"]).recalque(r["no"], r["ux"], r["uy"], r["uz"],
                                          r["rx"], r["ry"], r["rz"])

    return modelo


def _caso(modelo: Modelo, nome: str):
    from ..core.modelo import ErroDeModelo
    if nome not in modelo.casos:
        raise ErroDeModelo(
            f"a carga cita o caso '{nome}', que não está na aba de casos de "
            "carga")
    return modelo.casos[nome]
