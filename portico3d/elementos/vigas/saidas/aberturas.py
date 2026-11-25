# -*- coding: utf-8 -*-
"""
aberturas.py
Saídas dos furos e aberturas na alma (NBR 6118:2026, 13.2.5 e 21.3): o que o
furo põe na elevação (contorno, estribos retirados ou deslocados, barras e
estribos dos banzos, suspensão), o desenho local de cada abertura, o capítulo
da memória de cálculo, as linhas do roteiro de verificações e a aba da
planilha.

Tudo lê ``res.aberturas`` (:class:`vigas.core.aberturas.ResultadoAberturas`)
e não faz nada na viga sem furo -- os ganchos nos módulos de saída são uma
linha cada, para não mexer no que já existe.
"""

from __future__ import annotations

import math

from ..core import aberturas as ab
from . import estilo

#: Segmentos do círculo no contorno do furo circular.
SEGMENTOS = ab.SEGMENTOS_CIRCULO


def _lista(res) -> list:
    r = getattr(res, "aberturas", None)
    return list(r.lista) if r is not None else []


def _n(v, casas: int = 2) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


# ---------------------------------------------------------------------------
# Elevação (geometria.montar_elevacao chama esta)
# ---------------------------------------------------------------------------

def contorno_furo(r, base: float) -> list[tuple[float, float]]:
    """Contorno do furo na elevação, cm (x ao longo da viga, y da base do
    desenho). O furo vertical aparece como o retângulo que ele ocupa na
    altura toda."""
    a = r.abertura
    topo = base + r.h
    if a.vertical:
        return [(r.x0, base), (r.x1, base), (r.x1, topo), (r.x0, topo)]
    y0, y1 = topo - a.topo - a.altura, topo - a.topo
    if a.circular:
        xc, yc, raio = (r.x0 + r.x1) / 2.0, (y0 + y1) / 2.0, a.diametro / 2.0
        return [(xc + raio * math.cos(2 * math.pi * k / SEGMENTOS),
                 yc + raio * math.sin(2 * math.pi * k / SEGMENTOS))
                for k in range(SEGMENTOS)]
    return [(r.x0, y0), (r.x1, y0), (r.x1, y1), (r.x0, y1)]


def na_elevacao(res, el, bases, mostrar_estribos: bool = True) -> None:
    """Acrescenta à elevação ``el`` (``geometria.Elevacao``) o que os furos
    mudam: o contorno de cada furo, os estribos da viga retirados ou
    deslocados, as barras novas dos banzos e os estribos dos banzos e da
    suspensão. As cotas entram em ``el.cotas_estribo`` antes do
    escalonamento, para não colidirem com as demais."""
    lista = _lista(res)
    if not lista:
        return
    from .geometria import Polilinha, camada_barra
    viga = res.viga
    trechos = viga.trechos
    res_ab = res.aberturas
    for r in lista:
        k = viga.trecho_em(r.abertura.x_centro)
        el.contorno.append(Polilinha(contorno_furo(r, bases[k]),
                                     camada="CONCRETO", fechada=True))
    if not mostrar_estribos:
        return
    retirados = res_ab.estribos_retirados
    deslocados = res_ab.estribos_deslocados
    novos = []
    for pol in el.estribos:
        pts = pol.pontos
        vertical = len(pts) == 2 and abs(pts[0][0] - pts[1][0]) < 1e-9
        if not vertical or pol.camada != "ESTRIBO":
            novos.append(pol)
            continue
        x = pts[0][0]
        if any(abs(x - q) < 1e-6 for q in retirados):
            continue
        destino = next((v for q, v in deslocados.items()
                        if abs(x - q) < 1e-6), None)
        if destino is not None:
            pol = Polilinha([(destino, pts[0][1]), (destino, pts[1][1])],
                            camada=pol.camada)
        novos.append(pol)
    el.estribos[:] = novos
    for r in lista:
        k = viga.trecho_em(r.abertura.x_centro)
        topo = bases[k] + r.h
        for t in r.tracados:
            if t["tipo"] == "barra":
                y = topo + t["z"]
                # sem cota: a barra é identificada na vista explodida, e uma
                # cota por barra nova empilhava rótulos acima do título
                el.barras.append(Polilinha([(t["x0"], y), (t["x1"], y)],
                                           camada=camada_barra(t["face"])))
            elif t["tipo"] == "estribos":
                for x in t["xs"]:
                    el.estribos.append(Polilinha(
                        [(x, topo + t["z0"]), (x, topo + t["z1"])],
                        camada="ESTRIBO"))
                if t["papel"] == "banzo":
                    el.cotas_estribo.append((t["xs"][0], t["xs"][-1],
                                             el.h_max + 14.0, t["rotulo"]))


# ---------------------------------------------------------------------------
# Desenho local de cada abertura (memória)
# ---------------------------------------------------------------------------

def _janela(res, r) -> tuple[float, float]:
    viga = res.viga
    if r.modelo == "banzos":
        lb = max([bz.ancoragem_furo["lb_adot"] for bz in r.banzos
                  if bz.ancoragem_furo] + [0.0])
        m = r.h / 4.0 + lb + 20.0
    else:
        m = max(r.h * 0.8, 40.0)
    return (max(r.x0 - m, viga.x_inicio_fisico * 100.0),
            min(r.x1 + m, viga.x_fim_fisico * 100.0))


def figura_abertura(res, r):
    """Elevação local armada da abertura ``r`` (``ResultadoAbertura``): o
    trecho da viga com o furo, os estribos da viga que ficam, as barras e
    os estribos dos banzos, a suspensão e as cotas principais."""
    from matplotlib.figure import Figure
    from matplotlib.patches import Polygon, Rectangle

    estilo.aplicar_estilo()
    viga = res.viga
    h = r.h
    cob = viga.ambiente.cobrimento_nominal
    xa, xb = _janela(res, r)
    a = r.abertura
    fig = Figure(figsize=(max(7.5, min(13.0, (xb - xa) / 22.0)), 4.6))
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(f"{r.nome} — trecho da viga com o furo "
                 f"({'dispensado' if r.modelo == 'dispensa' else r.modelo})",
                 fontsize=10)
    ax.add_patch(Rectangle((xa, -h), xb - xa, h, facecolor=estilo.CONCRETO,
                           edgecolor=estilo.CINZA, lw=1.0, zorder=1))
    pts = [(x, y - h) for x, y in contorno_furo(r, 0.0)]
    ax.add_patch(Polygon(pts, closed=True, facecolor="white",
                         edgecolor=estilo.CINZA, lw=1.1,
                         ls="--" if a.vertical else "-", zorder=2))
    # estribos da viga que ficam (deslocados onde for o caso)
    res_ab = res.aberturas
    retirados = res_ab.estribos_retirados
    desloc = res_ab.estribos_deslocados
    # as faixas de estribo (zonas_estribo) não mudam com o furo: é delas que
    # sai a posição de cada estribo, a mesma conta da elevação
    for x in ab.estribos_viga(res):
        xx = x[0]
        if any(abs(xx - q) < 1e-6 for q in retirados):
            continue
        xx = next((v for q, v in desloc.items() if abs(xx - q) < 1e-6), xx)
        if xa <= xx <= xb:
            ax.plot([xx, xx], [-h + cob, -cob], color=estilo.VERDE, lw=0.7,
                    zorder=3)
    cores = {"superior": estilo.AZUL_MEDIO, "inferior": estilo.VERMELHO}
    for t in r.tracados:
        if t["tipo"] == "barra":
            ax.plot([max(t["x0"], xa), min(t["x1"], xb)], [t["z"], t["z"]],
                    color=cores.get(t["face"], estilo.CINZA), lw=1.8,
                    zorder=5, solid_capstyle="round")
            ax.text(max(t["x0"], xa) + 2.0, t["z"] + 1.0, t["rotulo"],
                    fontsize=6.5, color=cores.get(t["face"], estilo.CINZA),
                    zorder=6)
        elif t["tipo"] == "estribos":
            cor = estilo.LARANJA if t["papel"] == "suspensao" else \
                estilo.AZUL
            for x in t["xs"]:
                ax.plot([x, x], [t["z0"], t["z1"]], color=cor, lw=1.0,
                        zorder=4)
    # cotas
    def cota_v(z0, z1, x, texto):
        ax.annotate("", xy=(x, z0), xytext=(x, z1),
                    arrowprops=dict(arrowstyle="<->", color=estilo.CINZA,
                                    lw=0.7))
        ax.text(x - 1.5, (z0 + z1) / 2.0, texto, ha="right", va="center",
                fontsize=7, color=estilo.CINZA)

    def cota_h(x0, x1, y, texto):
        ax.annotate("", xy=(x0, y), xytext=(x1, y),
                    arrowprops=dict(arrowstyle="<->", color=estilo.CINZA,
                                    lw=0.7))
        ax.text((x0 + x1) / 2.0, y + 1.2, texto, ha="center", va="bottom",
                fontsize=7, color=estilo.CINZA)

    x_c = xa - 4.0
    if not a.vertical:
        cota_v(-a.topo, 0.0, x_c, _n(a.topo, 0))
        cota_v(-(a.topo + a.altura), -a.topo, x_c, _n(a.altura, 0))
        cota_v(-h, -(a.topo + a.altura), x_c,
               _n(h - a.topo - a.altura, 0))
    else:
        cota_v(-h, 0.0, x_c, f"h = {_n(h, 0)}")
    cota_h(r.x0, r.x1, 5.0, ("ø " if a.circular else "") + _n(a.extensao, 0))
    if r.modelo == "banzos":
        zona = h / 4.0
        cota_h(r.x0 - zona, r.x0, 5.0, f"h/4 = {_n(zona, 1)}")
        cota_h(r.x1, r.x1 + zona, 5.0, f"h/4 = {_n(zona, 1)}")
        ax.text((r.x0 + r.x1) / 2.0, -h - 6.0,
                f"estribos dos banzos ø{_n(r.banzos[0].estribos['phi'], 1)}"
                f" c/{_n(r.s_compatibilizado, 1)}; suspensão "
                f"{r.suspensao['n']} + {r.suspensao['n']} em h/4",
                ha="center", va="top", fontsize=7.5, color=estilo.AZUL)
    elif r.modelo == "bielas":
        ax.text((r.x0 + r.x1) / 2.0, -h - 6.0,
                "Fora do modelo de banzos: verificar por bielas e tirantes "
                "(NBR 6118, 21.3.1 e Seção 22)", ha="center", va="top",
                fontsize=8, color=estilo.VERMELHO, fontweight="bold")
    elif r.modelo == "dispensa":
        ax.text((r.x0 + r.x1) / 2.0, -h - 6.0,
                "Dispensado da verificação (13.2.5.1 a–d); estribos da viga "
                "deslocados para as bordas do furo", ha="center", va="top",
                fontsize=8, color=estilo.VERDE)
    ax.set_xlim(xa - 18.0, xb + 6.0)
    ax.set_ylim(-h - 14.0, 14.0)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Memória de cálculo (relatorio._capitulos_da_viga chama esta)
# ---------------------------------------------------------------------------

CAB_LINHA = ["Grandeza", "Valor", "Unid.", "Limite / critério", "Verif.",
             "Referência"]


def linhas_tabela(linhas) -> list[list[str]]:
    """``Linha`` do cálculo → linha de tabela (texto)."""
    saida = []
    for l in linhas:
        verif = "" if l.ok is None else ("OK" if l.ok else "NÃO OK")
        saida.append([l.grandeza.strip(), l.valor, l.unidade, l.limite,
                      verif, l.referencia])
    return saida


METODOLOGIA = (
    ("Furo horizontal (atravessa a largura bw, 13.2.5.1)",
     "Distância do furo às faces da viga ≥ máx(5 cm; 2c). A verificação "
     "estrutural é dispensada quando valem ao mesmo tempo: a) o furo está "
     "na zona de tração (abaixo da linha neutra do ELU com momento "
     "positivo, acima dela com momento negativo) e a pelo menos 2h da face "
     "do apoio mais próximo; b) o furo tem no máximo 12 x 12 cm (ø 12,5 cm "
     "se circular) e no máximo h/3; c) a distância entre faces de furos do "
     "mesmo tramo é ≥ 2h; d) cobrimentos suficientes e nenhuma armadura "
     "longitudinal seccionada."),
    ("Modelo de banzos (roteiro de Bolina, UFRGS)",
     "Não dispensado, a viga é, no trecho do furo, um quadro de dois "
     "banzos: N_c = N_t = M_d / z, com z = d − λx/2 da região de flexão; "
     "V_c = 0,80 V_d no banzo comprimido e V_t = 0,20 V_d no tracionado; "
     "M_c = V_c·L/2 e M_t = V_t·L/2, L a extensão do furo (o furo circular "
     "entra pelo quadrado circunscrito). M_d e V_d saem da envoltória ELU "
     "no trecho do furo (pior valor) ou na seção do centro, conforme o "
     "critério da abertura. Numa viga contínua com momento dos dois sinais "
     "no trecho, os dois casos são calculados e cada banzo fica com o "
     "pior."),
    ("Banzos",
     "Cada banzo é uma seção retangular bw x h_banzo com armadura "
     "simétrica, dimensionada por equilíbrio e compatibilidade (bloco "
     "retangular λx com α_c·η_c·f_cd, domínios 1 a 5, 17.2.2) — o "
     "comprimido à flexo-compressão, com A_s ≥ 0,15 N_d/f_yd ≥ 0,4 % A_c "
     "(17.3.5.3.1); o tracionado à flexo-tração, com A_s ≥ ρ_mín A_c "
     "(Tabela 17.3). As barras existentes da viga na face externa do banzo "
     "são aproveitadas; as da face junto ao furo são novas."),
    ("Estribos dos banzos",
     "Modelo I (17.4.2.2): V_Rd2 = 0,27 α_v2 f_cd b d; V_c0 = 0,6 f_ctd b d "
     "(zero no banzo tracionado com a linha neutra fora da seção); "
     "A_sw/s = (V − V_c)/(0,9 d f_ywd) ≥ 0,2 f_ctm/f_ywk b; s ≤ 0,6 d ≤ 30 "
     "cm (ou 0,3 d ≤ 20 cm se V > 0,67 V_Rd2). Os dois banzos ficam com o "
     "menor espaçamento."),
    ("Suspensão e ancoragem",
     "A_susp = V_c / f_ywd de cada lado do furo, em estribos da seção "
     "inteira distribuídos em h/4; os estribos da viga que caem nessa "
     "faixa saem, e a suspensão soma a parcela de cisalhamento que eles "
     "levavam. As barras novas dos banzos ancoram l_b = (ø/4)·f_yd/f_bd ≥ "
     "25 ø (9.4.2.4) além do fim da suspensão, com a aderência da posição "
     "da barra (9.3.1). Barras de pele cortadas pelo furo (ou pela camada "
     "das barras novas) viram trechos com gancho a 90° (0,7 l_b, 9.4.2.5)."),
    ("Furo vertical (atravessa a altura, 21.3.3)",
     "ø ≤ bw/3; distância às faces laterais ≥ máx(5 cm; 2c); nenhuma barra "
     "longitudinal dentro do furo com o cobrimento; num conjunto de furos "
     "alinhados, distância entre faces ≥ máx(5 cm; ø) e pelo menos um "
     "estribo em cada intervalo. A seção reduzida (bw − ø) é verificada à "
     "flexão (M_Rd e x/d) e ao cortante (V_Rd2 e V_Rd3 = V_c + V_sw com os "
     "estribos reais)."),
    ("Limites do modelo",
     "Furo sobre o apoio, que atravesse uma mudança de seção, que entre na "
     "mesa de uma seção T ou que se sobreponha a outro é erro de entrada. "
     "Com torção no tramo do furo os limites deveriam ser ajustados "
     "(21.3.3): o programa avisa e não faz o ajuste. Banzo menor que 3 d', "
     "suspensão que não cabe entre o furo e o apoio, furos vizinhos a menos "
     "de h/2 e furo que secciona a armadura saem do modelo de banzos e "
     "pedem bielas e tirantes (21.3.1, Seção 22) — a abertura fica "
     "reprovada."),
)


def capitulo_memoria(doc, res, n) -> None:
    """Capítulo da memória: metodologia, e por abertura a figura local e a
    tabela das verificações."""
    from .relatorio import (CINZA, VERMELHO, _figura, _paragrafo, _tabela,
                            _titulo)
    lista = _lista(res)
    _titulo(doc, f"{n}. Furos e aberturas na alma (13.2.5 e 21.3)", 1)
    _paragrafo(doc, "Os furos leem o resultado da viga calculada sem "
                    "alterá-lo: o que é novo (barras e estribos dos banzos, "
                    "suspensão, trechos de pele) entra como posições novas "
                    "da tabela de ferros, e o que o furo tira da viga "
                    "(estribos dentro da abertura e na faixa da suspensão, "
                    "barras de pele cortadas) entra como ajuste da contagem "
                    "das posições existentes.")
    _titulo(doc, f"{n}.1 Metodologia", 2)
    _tabela(doc, ["Tema", "Critério"], [list(t) for t in METODOLOGIA],
            [4.5, 11.5])
    _tabela(doc, ["Abertura", "Tipo", "Posição (m)", "Modelo", "Situação"],
            [[r.abertura.nome(r.indice),
              ("vertical ø " + _n(r.abertura.diametro, 1)
               if r.abertura.vertical else
               "horizontal " + ab._forma_txt(r.abertura)),
              f"{_n(r.abertura.x_ini)} a {_n(r.abertura.x_fim)}",
              r.modelo, "OK" if r.ok else "NÃO OK"] for r in lista],
            [3.0, 5.0, 3.0, 2.5, 2.5])
    for k, r in enumerate(lista, 2):
        _titulo(doc, f"{n}.{k} Abertura {r.abertura.nome(r.indice)} — "
                     f"modelo {r.modelo}", 2)
        if r.modelo != "inválida":
            try:
                _figura(doc, figura_abertura(res, r), largura_cm=15.0)
            except Exception:                           # noqa: BLE001
                pass
        _tabela(doc, CAB_LINHA, linhas_tabela(r.linhas),
                [4.6, 3.0, 1.3, 4.2, 1.3, 2.6])
        if r.posicoes:
            _paragrafo(doc, "Posições novas: " + "; ".join(
                f"N{p.numero} {p.texto_quantidade} ø{_n(p.phi, 1)} "
                f"C={p.comprimento:.0f} ({p.descricao.split(': ', 1)[-1]})"
                for p in r.posicoes) + ".", cor=CINZA)
        for texto in r.avisos:
            _paragrafo(doc, texto, cor=VERMELHO)


# ---------------------------------------------------------------------------
# Roteiro de verificações (auditoria.roteiro chama esta)
# ---------------------------------------------------------------------------

def verificacoes(res) -> list:
    """Linhas do roteiro para 13.2.5 (horizontal) e 21.3.3 (vertical)."""
    from .auditoria import (ATENDIDO, NAO_APLICAVEL, NAO_ATENDIDO,
                            NAO_VERIFICADO, Verificacao)
    lista = _lista(res)
    horizontais = [r for r in lista if not r.abertura.vertical]
    verticais = [r for r in lista if r.abertura.vertical]
    saida = []

    def situacao(rs):
        if not rs:
            return NAO_APLICAVEL
        if any(not r.ok for r in rs):
            return NAO_ATENDIDO
        if any(r.com_torcao for r in rs):
            return NAO_VERIFICADO
        return ATENDIDO

    def resumo(rs):
        partes = []
        for r in rs:
            txt = f"{r.nome} {r.modelo}"
            if not r.ok:
                ruins = [l.grandeza.strip() for l in r.linhas
                         if l.ok is False]
                txt += " — reprova: " + "; ".join(ruins[:2])
            elif r.com_torcao:
                txt += " — com torção, limites não ajustados"
            partes.append(txt)
        return "; ".join(partes)

    saida.append(Verificacao(
        "13.2.5", "Furos horizontais na alma: distância às faces, dispensa "
                  "(a–d) ou modelo de banzos",
        situacao(horizontais),
        resumo(horizontais) if horizontais
        else "nenhum furo horizontal lançado"))
    saida.append(Verificacao(
        "21.3.3", "Furos verticais: ø ≤ b/3, faces, conjunto e seção "
                  "reduzida",
        situacao(verticais),
        resumo(verticais) if verticais
        else "nenhum furo vertical lançado"))
    return saida


# ---------------------------------------------------------------------------
# Planilha (planilha._abas_da_viga chama esta)
# ---------------------------------------------------------------------------

def aba_planilha(wb, res) -> None:
    """Aba ABERTURAS: uma tabela por furo, com as linhas da verificação."""
    lista = _lista(res)
    if not lista:
        return
    from .estilo_planilha import (cabecalho, linha_tabela, nota,
                                  preparar_tabela, secao, separador, titulo)
    ws = wb.create_sheet("ABERTURAS")
    preparar_tabela(ws, [44.0, 30.0, 10.0, 34.0, 10.0, 26.0])
    L = 2
    L = titulo(ws, L, f"VIGA {res.viga.nome} — FUROS E ABERTURAS NA ALMA",
               2, 7)
    L = nota(ws, L, "NBR 6118:2026, 13.2.5 (furos horizontais) e 21.3.3 "
                    "(furos verticais); modelo de banzos de Bolina (UFRGS)",
             2, 7)
    L = separador(ws, L)
    for r in lista:
        L = secao(ws, L, f"{r.abertura.nome(r.indice)} — modelo {r.modelo}"
                         f" — {'OK' if r.ok else 'NÃO OK'}", 2, 7)
        L = cabecalho(ws, L, CAB_LINHA)
        for linha in linhas_tabela(r.linhas):
            L = linha_tabela(ws, L, linha)
        for texto in r.avisos:
            L = nota(ws, L, texto, 2, 7)
        L = separador(ws, L)
