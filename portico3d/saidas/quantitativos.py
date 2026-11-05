# -*- coding: utf-8 -*-
"""
quantitativos.py
O quadro de quantidades do edifício, em Excel.

Aço por bitola e por tipo de peça, concreto por tipo de peça, e o resumo com
as taxas. Cada motor de elemento já produz o seu quantitativo; aqui eles são
somados e postos lado a lado, que é o que o orçamento pede.

## Fôrmas

O critério é o do vazamento: conta-se **só a face que precisa conter o
concreto**. Das três peças, duas trazem a conta pronta do seu motor e uma é
calculada aqui, porque depende de quem está encostado nela:

**Laje** — ``lajes.core.formas``. Fundo descontada a faixa de ``t/2`` que se
apoia sobre a viga (senão a mesma chapa é medida duas vezes), mais o
fechamento lateral só nos bordos livres: onde apoia numa viga, a lateral dela
já sobe e fecha; onde é bordo comum, o concreto é contínuo e não há o que
fechar.

**Pilar** — ``pilares.core.quantitativos``. Perímetro moldante vezes a altura
do lance.

**Viga** — daqui, e é o caso que justifica a conta ser deste nível. O fundo
sempre leva fôrma. Cada lateral leva ``h`` menos a espessura da laje que
encosta ali: onde a laje entra, ela fecha a fôrma naquela altura. Uma viga
entre dois painéis desconta dos dois lados; uma viga de bordo, de um só. O
topo nunca leva: é por onde se concreta. Nada disso o motor de Vigas tem como
saber, porque ele não conhece as lajes vizinhas.

O estilo é o ``estilo_planilha`` dos próprios motores: fonte Aptos, a paleta e
os formatos numéricos com a unidade embutida, de modo que este quadro e o da
viga avulsa saiam iguais.
"""

from __future__ import annotations

from pathlib import Path

#: Massa linear nominal, kg/m, das bitolas da Tabela 4 da NBR 7480.
MASSA_LINEAR = {5.0: 0.154, 6.3: 0.245, 8.0: 0.395, 10.0: 0.617,
                12.5: 0.963, 16.0: 1.578, 20.0: 2.466, 25.0: 3.853,
                32.0: 6.313, 40.0: 9.865}


def _somar_bitolas(destino: dict, origem: dict) -> None:
    """Soma um ``por_bitola`` de motor de elemento no acumulador."""
    for phi, dados in (origem or {}).items():
        chave = float(phi)
        alvo = destino.setdefault(chave, {"comprimento": 0.0, "massa": 0.0})
        alvo["comprimento"] += float(dados.get("comprimento", 0.0) or 0.0)
        alvo["massa"] += float(dados.get("massa", 0.0) or 0.0)


def formas_das_vigas(projeto) -> dict:
    """Área de fôrma das vigas, m², descontando o que a laje fecha.

    Devolve ``{"fundo": m², "laterais": m², "total": m²}``. O desconto é por
    lado: cada painel de laje que encosta na barra fecha uma lateral na altura
    da sua espessura. Viga interna, com painel dos dois lados, desconta duas
    vezes; viga de bordo, uma vez só.
    """
    from ..core.lajes import arestas_da_laje
    from ..core.modelo import ErroDeModelo

    modelo = projeto.modelo
    # barra -> espessuras das lajes que encostam nela
    encostadas: dict[str, list[float]] = {}
    for laje in modelo.lajes.values():
        try:
            arestas, _, _ = arestas_da_laje(modelo, laje)
        except ErroDeModelo:
            continue
        for aresta in arestas:
            for barra in aresta.barras:
                encostadas.setdefault(barra, []).append(
                    max(laje.altura, 0.0))

    fundo = laterais = 0.0
    for v in projeto.vigas:
        if not v.passou:
            continue
        for nome in v.barras:
            barra = modelo.barras.get(nome)
            if barra is None:
                continue
            secao = modelo.secoes.get(barra.secao)
            if secao is None or secao.b <= 0.0 or secao.h <= 0.0:
                continue
            comprimento = modelo.comprimento(nome)
            fundo += secao.b * comprimento
            # duas laterais; cada uma perde a espessura da laje que a fecha
            espessuras = sorted(encostadas.get(nome, []), reverse=True)[:2]
            for lado in range(2):
                hf = espessuras[lado] if lado < len(espessuras) else 0.0
                laterais += max(secao.h - hf, 0.0) * comprimento
    return {"fundo": fundo, "laterais": laterais,
            "total": fundo + laterais}


def consolidar(projeto) -> dict:
    """Soma os quantitativos dos três motores, por tipo de peça.

    O concreto dos pilares é calculado aqui — o motor de Pilares dimensiona um
    lance por vez e não tem por que somar o edifício —, e vem da seção e do
    comprimento de cada lance verificado, contado uma vez só ainda que várias
    combinações o tenham governado.
    """
    por_elemento: dict[str, dict] = {}
    por_bitola_total: dict[float, dict] = {}

    # -- pilares -----------------------------------------------------------
    aco_p = concreto_p = formas_p = 0.0
    bitolas_p: dict[float, dict] = {}
    vistos = set()
    for v in projeto.pilares:
        if not v.aprovado or v.barra in vistos:
            continue
        vistos.add(v.barra)
        pilar = getattr(v.resultado, "pilar", None)
        arranjo = getattr(v.resultado, "arranjo", None)
        estribos = getattr(v.resultado, "estribos", None)
        if pilar is None:
            continue
        altura = pilar.lance.comprimento / 100.0            # cm -> m
        concreto_p += pilar.secao.area / 1e4 * altura
        try:
            from ..elementos.pilares.core import quantitativos as qp
            formas_p += qp.calcular(v.resultado).area_formas
        except Exception:                                # noqa: BLE001
            formas_p += qp_perimetro(pilar) * altura
        if arranjo is not None:
            massa = arranjo.massa(altura * 100.0) if hasattr(arranjo, "massa") \
                else arranjo.As / 1e4 * altura * 7850.0
            aco_p += float(massa)
            d = bitolas_p.setdefault(float(arranjo.phi),
                                     {"comprimento": 0.0, "massa": 0.0})
            d["comprimento"] += arranjo.n_barras * altura
            d["massa"] += float(massa)
        if estribos is not None:
            aco_p += float(getattr(estribos, "massa", 0.0) or 0.0)
    if vistos:
        por_elemento["Pilares"] = {"aco": aco_p, "aco_perdas": aco_p * 1.10,
                                   "concreto": concreto_p,
                                   "formas": formas_p,
                                   "itens": len(vistos)}
        _somar_bitolas(por_bitola_total, bitolas_p)

    # -- vigas -------------------------------------------------------------
    aco_v = concreto_v = 0.0
    n_v = 0
    for v in projeto.vigas:
        if not v.passou:
            continue
        n_v += 1
        q = v.resultado.quantitativo or {}
        aco_v += float(q.get("massa_total", 0.0) or 0.0)
        concreto_v += sum(t.secao.area / 1e4 * t.L for t in v.viga.tramos)
        _somar_bitolas(por_bitola_total, q.get("por_bitola"))
    if n_v:
        por_elemento["Vigas"] = {"aco": aco_v, "aco_perdas": aco_v * 1.10,
                                 "concreto": concreto_v,
                                 "formas": formas_das_vigas(projeto)["total"],
                                 "itens": n_v}

    # -- lajes -------------------------------------------------------------
    aco_l = concreto_l = formas_l = 0.0
    n_l = 0
    for v in projeto.lajes:
        if not v.passou:
            continue
        n_l += 1
        if v.resultado is not None:
            q = v.resultado.quantitativo or {}
            aco_l += float(q.get("massa_total", 0.0) or 0.0)
            concreto_l += float(q.get("volume_concreto", 0.0) or 0.0)
            _somar_bitolas(por_bitola_total, q.get("por_bitola"))
            formas_l += _formas_do_pavimento(v)
        # Treliçada: o aço e o concreto moldado no local do motor; a fôrma é
        # a vigota com o enchimento, que não leva fôrma.
        for f in getattr(v, "trelicadas", []):
            if f.passou:
                q = f.resultado.quantitativo or {}
                aco_l += float(q.get("aco_kg", 0.0) or 0.0)
                concreto_l += float(q.get("volume_concreto", 0.0) or 0.0)
    if n_l:
        por_elemento["Lajes"] = {"aco": aco_l, "aco_perdas": aco_l * 1.10,
                                 "concreto": concreto_l,
                                 "formas": formas_l, "itens": n_l}

    aco = sum(d["aco"] for d in por_elemento.values())
    concreto = sum(d["concreto"] for d in por_elemento.values())
    formas = sum(d.get("formas", 0.0) for d in por_elemento.values())
    return {"por_elemento": por_elemento,
            "por_bitola": dict(sorted(por_bitola_total.items())),
            "aco": aco, "aco_perdas": aco * 1.10, "concreto": concreto,
            "formas": formas}


def _formas_do_pavimento(verificacao) -> float:
    """Fôrma de um pavimento de lajes, pelo módulo do próprio motor."""
    try:
        from ..elementos.lajes.core import formas as fl
    except ImportError:
        return 0.0
    pav = getattr(verificacao, "pavimento", None)
    if pav is None:
        return 0.0
    return fl.total([fl.calcular(l) for l in pav.lajes])["forma_total"]


def qp_perimetro(pilar) -> float:
    """Perímetro moldante do pilar, em metros — reserva se o motor falhar."""
    from ..elementos.pilares.core import quantitativos as qp

    return qp.perimetro_moldante(pilar.secao) / 100.0


# ---------------------------------------------------------------------------
# As abas
# ---------------------------------------------------------------------------

def _aba_resumo(wb, projeto, q) -> None:
    from ..elementos.vigas.saidas.estilo_planilha import (NF, cabecalho,
                                                          grandeza,
                                                          linha_tabela, nota,
                                                          preparar_memoria,
                                                          secao, separador,
                                                          titulo)

    ws = wb.create_sheet("RESUMO")
    preparar_memoria(ws)
    L = 2
    L = titulo(ws, L, "QUADRO DE QUANTIDADES")
    L = nota(ws, L, projeto.modelo.nome or "pórtico espacial")
    L = separador(ws, L)

    L = secao(ws, L, "o modelo")
    L = grandeza(ws, L, "nós =", len(projeto.modelo.nos), "", NF["inteiro"])
    L = grandeza(ws, L, "barras =", len(projeto.modelo.barras), "",
                 NF["inteiro"])
    L = grandeza(ws, L, "painéis de laje =", len(projeto.modelo.lajes), "",
                 NF["inteiro"])
    L = separador(ws, L)

    L = secao(ws, L, "totais")
    L = grandeza(ws, L, "aço =", q["aco"], "(sem perdas)", NF["kg"])
    L = grandeza(ws, L, "aço com perdas =", q["aco_perdas"],
                 "(10 % de perdas e pontas)", NF["kg"])
    L = grandeza(ws, L, "concreto =", q["concreto"], "", '0.000\\ "m³"')
    L = grandeza(ws, L, "fôrmas =", q["formas"],
                 "(só as faces que contêm o concreto)", '0.00\\ "m²"')
    if q["concreto"]:
        L = grandeza(ws, L, "taxa =", q["aco"] / q["concreto"],
                     "(aço por metro cúbico)", '0.0\\ "kg/m³"')
        L = grandeza(ws, L, "fôrma por m³ =", q["formas"] / q["concreto"],
                     "", '0.0\\ "m²/m³"')
    L = separador(ws, L)

    L = secao(ws, L, "critério das fôrmas")
    L = nota(ws, L, "Laje: fundo menos a faixa apoiada sobre a viga, mais o "
                    "fechamento lateral só nos bordos livres.")
    L = nota(ws, L, "Viga: fundo integral, mais cada lateral com h menos a "
                    "espessura da laje que encosta nela. O topo não leva: é "
                    "por onde se concreta.")
    L = nota(ws, L, "Pilar: perímetro moldante vezes a altura do lance.")


def _aba_por_elemento(wb, projeto, q) -> None:
    from ..elementos.vigas.saidas.estilo_planilha import (NF, cabecalho,
                                                          linha_tabela, nota,
                                                          preparar_tabela,
                                                          separador, titulo)

    ws = wb.create_sheet("POR ELEMENTO")
    preparar_tabela(ws, [16.0, 10.0, 15.0, 17.0, 15.0, 15.0, 15.0])
    L = 2
    L = titulo(ws, L, "QUANTIDADES POR TIPO DE PEÇA", 2, 8)
    L = separador(ws, L)
    L = cabecalho(ws, L, ["Peça", "itens", "aço (kg)", "aço + 10 % (kg)",
                          "concreto (m³)", "fôrmas (m²)", "taxa (kg/m³)"])
    for nome, d in q["por_elemento"].items():
        taxa = d["aco"] / d["concreto"] if d["concreto"] else 0.0
        L = linha_tabela(ws, L, [nome, d["itens"], d["aco"], d["aco_perdas"],
                                 d["concreto"], d.get("formas", 0.0), taxa],
                         [None, NF["inteiro"], NF["kg"], NF["kg"],
                          '0.000\\ "m³"', '0.00\\ "m²"', '0.0\\ "kg/m³"'])
    taxa = q["aco"] / q["concreto"] if q["concreto"] else 0.0
    L = linha_tabela(ws, L, ["TOTAL", "", q["aco"], q["aco_perdas"],
                             q["concreto"], q["formas"], taxa],
                     [None, None, NF["kg"], NF["kg"], '0.000\\ "m³"',
                      '0.00\\ "m²"', '0.0\\ "kg/m³"'])


def _aba_aco(wb, q) -> None:
    from ..elementos.vigas.saidas.estilo_planilha import (NF, cabecalho,
                                                          linha_tabela, nota,
                                                          preparar_tabela,
                                                          separador, titulo)

    ws = wb.create_sheet("AÇO")
    preparar_tabela(ws, [12.0, 20.0, 18.0, 18.0])
    L = 2
    L = titulo(ws, L, "AÇO POR BITOLA", 2, 5)
    L = nota(ws, L, "Massas nominais da Tabela 4 da NBR 7480", 2, 5)
    L = separador(ws, L)
    L = cabecalho(ws, L, ["Ø (mm)", "comprimento (m)", "massa (kg)",
                          "massa + 10 % (kg)"])
    for phi, d in q["por_bitola"].items():
        L = linha_tabela(ws, L, [phi, d["comprimento"], d["massa"],
                                 d["massa"] * 1.10],
                         [NF["bitola"], NF["m"], NF["kg"], NF["kg"]])
    total = sum(d["massa"] for d in q["por_bitola"].values())
    L = linha_tabela(ws, L, ["TOTAL", "", total, total * 1.10],
                     [None, None, NF["kg"], NF["kg"]])


def _aba_verificacoes(wb, projeto) -> None:
    from ..elementos.vigas.saidas.estilo_planilha import (NF, cabecalho,
                                                          linha_tabela, nota,
                                                          preparar_tabela,
                                                          separador, titulo)

    ws = wb.create_sheet("VERIFICAÇÕES")
    preparar_tabela(ws, [18.0, 14.0, 16.0, 46.0])
    L = 2
    L = titulo(ws, L, "VEREDITO POR PEÇA", 2, 5)
    L = separador(ws, L)
    L = cabecalho(ws, L, ["Peça", "tipo", "veredito", "observação"])

    vistos = set()
    for v in projeto.pilares:
        if v.barra in vistos:
            continue
        vistos.add(v.barra)
        iguais = [x for x in projeto.pilares if x.barra == v.barra]
        bom = any(x.aprovado for x in iguais)
        motivo = "" if bom else (iguais[0].motivos or [""])[0]
        L = linha_tabela(ws, L, [v.barra, "pilar",
                                 "aprovado" if bom else "REPROVADO",
                                 motivo[:200]])
    for v in projeto.vigas:
        obs = str(v.portico) if v.portico is not None else (v.erro or "")
        L = linha_tabela(ws, L, [v.nome, "viga",
                                 "aprovada" if v.aprovado else "REPROVADA",
                                 obs[:200]])
    for v in projeto.lajes:
        erros = v.erros if v.passou else []
        L = linha_tabela(ws, L, [f"cota {v.cota:g} m", "pavimento",
                                 "aprovado" if v.passou and not erros
                                 else "REPROVADO",
                                 (str(erros[0]) if erros else v.erro)[:200]])


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------

def gerar(projeto, caminho) -> Path:
    """Grava o quadro de quantidades do edifício e devolve o caminho."""
    try:
        from openpyxl import Workbook
    except ImportError as erro:                          # pragma: no cover
        raise RuntimeError(
            "para gravar o quadro de quantidades é preciso o openpyxl: "
            "py -m pip install openpyxl") from erro

    q = consolidar(projeto)
    wb = Workbook()
    wb.remove(wb.active)
    _aba_resumo(wb, projeto, q)
    _aba_por_elemento(wb, projeto, q)
    _aba_aco(wb, q)
    _aba_verificacoes(wb, projeto)

    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(destino))
    return destino
