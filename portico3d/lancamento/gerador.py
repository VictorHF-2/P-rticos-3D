# -*- coding: utf-8 -*-
"""
gerador.py
Do lançamento ao modelo de cálculo: nós, barras, apoios, lajes e casos.

O que o gerador decide sozinho, e que antes era digitado à mão:

* **Nós.** Onde viga cruza viga, onde viga encosta noutra, onde passa por
  um pilar, e em cada vértice da polilinha. Pontos coincidentes viram um nó
  só.
* **Vigas.** A polilinha é quebrada nesses nós; cada trecho é uma barra. Se
  o nó tem pilar, a barra ganha **trecho rígido** pelo 14.6.2.1 (Figura
  14.1): do eixo do pilar até ``0,3·h`` da viga antes da face, isto é,
  ``c/2 − 0,3·h``, com ``c`` a dimensão do pilar na direção da viga.
* **Pilares.** Um lance por pavimento, com a seção girada pelo ângulo. O de
  baixo engasta na fundação; o que não tem pilar embaixo nasce na viga do
  pavimento de baixo (transição) — e precisa haver viga ali.
* **Lajes.** O retângulo de vigas em volta do ponto lançado: o lado pode ser
  coberto por várias vigas na mesma reta.
* **Casos.** ``G`` (peso próprio das barras, lajes, paredes), ``Q``
  (acidental das lajes) e, com ``v0 > 0``, vento da NBR 6123 nas quatro
  direções.

O que ele **recusa**, com a lista de motivos em vez de um modelo errado — é a
conferência de lançamento:

* pilar que nasce no ar (sem pilar embaixo e sem viga onde nascer);
* viga que passa perto do pilar mas fora do eixo dele (a excentricidade
  viga–pilar ainda não é modelada; alinhe pelo eixo);
* laje sem contorno fechado de vigas, ou com viga atravessando o meio;
* parede fora de viga (parede sobre laje ainda não é carga da laje);
* pavimentos fora de ordem, planta inexistente, nome repetido.

E avisa sem recusar: viga sem apoio nenhum, pilar sem viga no topo, viga em
balanço livre, trecho rígido que não coube.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from ..core.modelo import ErroDeModelo, Modelo, Secao
from .modelo import Lancamento

TOL = 1.0e-6
#: Distância do eixo da viga ao centro do pilar abaixo da qual eles são
#: ditos alinhados, m.
TOL_EIXO = 0.01


@dataclass
class Geracao:
    """O resultado: o modelo (``None`` havendo erro) e a conferência."""

    modelo: Modelo | None
    erros: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    #: elemento lançado -> o que ele virou no modelo, por pavimento:
    #: ``("viga", nome, pavimento) -> [barras]`` e assim por diante.
    mapa: dict[tuple[str, str, str], list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.modelo is not None and not self.erros

    def resumo(self) -> str:
        if self.modelo is None:
            linhas = [f"Lançamento com {len(self.erros)} erro(s) — o modelo "
                      "não foi gerado:"]
        else:
            m = self.modelo
            linhas = [f"Modelo gerado do lançamento: {len(m.nos)} nós, "
                      f"{len(m.barras)} barras, {len(m.lajes)} lajes, "
                      f"{len(m.casos)} casos de carga."]
        linhas += [f"  ERRO: {e}" for e in self.erros]
        linhas += [f"  aviso: {a}" for a in self.avisos]
        return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Geometria de planta
# ---------------------------------------------------------------------------

def _chave(x: float, y: float) -> tuple[float, float]:
    return (round(x, 6) + 0.0, round(y, 6) + 0.0)


def _projecao(p, a, b) -> tuple[float, float]:
    """``(t, distância)`` do ponto ``p`` ao segmento ``a→b``, t em [0, 1]
    quando a projeção cai dentro."""
    a, b, p = np.asarray(a, float), np.asarray(b, float), np.asarray(p, float)
    d = b - a
    L2 = float(d @ d)
    t = float((p - a) @ d) / L2 if L2 > 0 else 0.0
    q = a + max(0.0, min(1.0, t)) * d
    return t, float(np.linalg.norm(p - q))


def _intersecao(a, b, c, d) -> tuple[float, float] | None:
    """Parâmetros ``(t, u)`` do cruzamento dos segmentos ``a→b`` e ``c→d``,
    os dois em [0, 1]; ``None`` se paralelos ou sem cruzamento."""
    a, b, c, d = (np.asarray(v, float) for v in (a, b, c, d))
    r, s = b - a, d - c
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    w = c - a
    t = (w[0] * s[1] - w[1] * s[0]) / den
    u = (w[0] * r[1] - w[1] * r[0]) / den
    if -TOL <= t <= 1 + TOL and -TOL <= u <= 1 + TOL:
        return t, u
    return None


# ---------------------------------------------------------------------------
# Gerador
# ---------------------------------------------------------------------------

def gerar(lanc: Lancamento) -> Geracao:
    """O modelo de cálculo do lançamento, ou a lista do que impede gerá-lo."""
    from ..core.cargas import peso_proprio
    from ..core.concreto import concreto
    from ..core.lajes import aplicar_lajes

    g = Geracao(None)
    _conferir_estrutura(lanc, g)
    if g.erros:
        return g

    m = Modelo(lanc.nome)
    material = concreto("concreto", lanc.fck, lanc.agregado or None, "Ecs",
                        lanc.peso_especifico)
    m.materiais[material.nome] = material
    m.calculo = replace(lanc.calculo)
    for nome, (perm, acid) in lanc.cargas_de_laje.items():
        m.add_carga_de_laje(nome, perm, acid)

    pavs = sorted(lanc.pavimentos, key=lambda p: p.cota)
    cotas = [lanc.cota_base] + [p.cota for p in pavs]

    def secao(b: float, h: float) -> str:
        nome = f"R{b * 100:g}x{h * 100:g}"
        if nome not in m.secoes:
            m.add_secao(Secao.retangular(nome, b, h))
        return nome

    # -- pilares de cada pavimento, já com o centro calculado -------------
    pilares = [[(p, p.centro) for p in lanc.plantas[pav.planta].pilares]
               for pav in pavs]

    def pilar_em(i: int, c) -> object | None:
        """O pilar do pavimento ``i`` com centro em ``c``, se houver."""
        if i < 0 or i >= len(pavs):
            return None
        for p, cc in pilares[i]:
            if math.dist(cc, c) < 1e-3:
                return p
        return None

    # -- nós da base --------------------------------------------------------
    nos_do_nivel: list[dict] = [dict() for _ in cotas]

    def no(nivel: int, x: float, y: float, nome: str) -> str:
        chave = _chave(x, y)
        tabela = nos_do_nivel[nivel]
        if chave not in tabela:
            if nome.endswith(".N"):
                nome = f"{nome}{len(tabela) + 1}"
            nome_final, k = nome, 1
            while nome_final in m.nos:
                k += 1
                nome_final = f"{nome}~{k}"
            m.add_no(nome_final, x, y, cotas[nivel])
            tabela[chave] = nome_final
        return tabela[chave]

    for p, c in pilares[0] if pilares else []:
        n = no(0, c[0], c[1], f"{p.nome}.base")
        m.apoiar(n)

    # -- vigas de cada pavimento -------------------------------------------
    pilar_do_no: dict[str, object] = {}
    for i, pav in enumerate(pavs):
        nivel = i + 1
        planta = lanc.plantas[pav.planta]
        # pontos com pilar nesta cota: os que chegam e os que nascem aqui
        com_pilar = [(p, c, "chega") for p, c in pilares[i]]
        if i + 1 < len(pavs):
            com_pilar += [(p, c, "nasce") for p, c in pilares[i + 1]
                          if pilar_em(i, c) is None]
        for p, c, papel in com_pilar:
            if papel == "chega":
                nome = no(nivel, c[0], c[1], f"{p.nome}.{pav.nome}")
                pilar_do_no.setdefault(nome, p)
        _gerar_vigas(m, lanc, g, planta, pav, nivel, com_pilar, no, secao,
                     pilar_do_no)

    # -- lances de pilar ----------------------------------------------------
    for i, pav in enumerate(pavs):
        nivel = i + 1
        for p, c in pilares[i]:
            topo = nos_do_nivel[nivel].get(_chave(*c))
            base = nos_do_nivel[nivel - 1].get(_chave(*c))
            if base is None:
                g.erros.append(
                    f"pilar {p.nome} ({pav.nome}) nasce no ar: não há pilar "
                    f"embaixo nem viga do pavimento de baixo passando em "
                    f"({c[0]:g}; {c[1]:g})")
                continue
            nome = f"{p.nome}.{pav.nome}"
            m.add_barra(nome, base, topo, "concreto", secao(p.b, p.h),
                        rotacao=p.angulo)
            g.mapa[("pilar", p.nome, pav.nome)] = [nome]
            if i > 0 and pilar_em(i - 1, c) is None:
                g.avisos.append(
                    f"pilar {p.nome} ({pav.nome}) nasce na viga do pavimento "
                    "de baixo (pilar de transição)")
            ligado = any(topo in (b.no_i, b.no_j) for n, b in m.barras.items()
                         if n != nome)
            if not ligado:
                g.avisos.append(f"pilar {p.nome} ({pav.nome}) sem viga no "
                                "topo")

    # -- lajes ----------------------------------------------------------------
    for i, pav in enumerate(pavs):
        for laje in lanc.plantas[pav.planta].lajes:
            _gerar_laje(m, g, laje, pav, i + 1, nos_do_nivel, cotas)

    if g.erros:
        return g

    # -- casos de carga -----------------------------------------------------
    G = m.add_caso("G", "permanente")
    Q = m.add_caso("Q", "variavel", lanc.categoria_acidental)
    peso_proprio(m, G)
    m.aplicar_cargas_de_laje()
    if m.lajes:
        aplicar_lajes(m, G, Q)
    for i, pav in enumerate(pavs):
        _gerar_paredes(m, g, lanc.plantas[pav.planta], pav, i + 1, cotas, G)
    if g.erros:
        return g

    if lanc.vento.v0 > 0.0:
        from ..core.vento import forcas_de_vento
        for nome, d in (("VX+", (1.0, 0.0)), ("VX-", (-1.0, 0.0)),
                        ("VY+", (0.0, 1.0)), ("VY-", (0.0, -1.0))):
            caso = m.add_caso(nome, "variavel", "vento", grupo="vento")
            forcas_de_vento(m, caso, lanc.vento.v0, d, lanc.vento.categoria,
                            lanc.vento.grupo_s3, lanc.vento.s1)

    try:
        m.validar()
    except ErroDeModelo as erro:
        g.erros.append(f"o modelo gerado não fecha: {erro}")
        return g
    _avisar_vigas_soltas(m, g)
    g.modelo = m
    return g


def _conferir_estrutura(lanc: Lancamento, g: Geracao) -> None:
    if not lanc.pavimentos:
        g.erros.append("o lançamento não tem pavimento")
        return
    cotas = sorted(p.cota for p in lanc.pavimentos)
    if cotas[0] <= lanc.cota_base + TOL:
        g.erros.append("há pavimento na cota da base ou abaixo dela")
    if len(set(round(c, 6) for c in cotas)) != len(cotas):
        g.erros.append("dois pavimentos na mesma cota")
    nomes = [p.nome for p in lanc.pavimentos]
    if len(set(nomes)) != len(nomes):
        g.erros.append("nome de pavimento repetido")
    for p in lanc.pavimentos:
        if p.planta not in lanc.plantas:
            g.erros.append(f"pavimento {p.nome} usa a planta '{p.planta}', "
                           "que não existe")
    for planta in lanc.plantas.values():
        for tipo, itens in (("pilar", planta.pilares),
                            ("viga", planta.vigas), ("laje", planta.lajes)):
            vistos = [x.nome for x in itens]
            if len(set(vistos)) != len(vistos):
                g.erros.append(f"planta {planta.nome}: nome de {tipo} "
                               "repetido")
        for v in planta.vigas:
            if len(v.pontos) < 2:
                g.erros.append(f"viga {v.nome}: precisa de dois pontos")


def _gerar_vigas(m: Modelo, lanc: Lancamento, g: Geracao, planta, pav,
                 nivel: int, com_pilar: list, no, secao,
                 pilar_do_no: dict) -> None:
    """Quebra as vigas da planta nos encontros e cria as barras."""
    segmentos = []                  # (viga, a, b)
    for v in planta.vigas:
        for a, b in zip(v.pontos, v.pontos[1:]):
            if math.dist(a, b) > TOL:
                segmentos.append((v, tuple(a), tuple(b)))

    # pontos de quebra de cada segmento, em parâmetro t ∈ [0, 1]
    quebras: list[set[float]] = [{0.0, 1.0} for _ in segmentos]
    for k, (_, a, b) in enumerate(segmentos):
        for j, (_, c, d) in enumerate(segmentos):
            if j <= k:
                continue
            r = _intersecao(a, b, c, d)
            if r is not None:
                quebras[k].add(min(max(r[0], 0.0), 1.0))
                quebras[j].add(min(max(r[1], 0.0), 1.0))
        for p, c, _ in com_pilar:
            t, dist = _projecao(c, a, b)
            if not -TOL <= t <= 1 + TOL:
                continue
            if dist <= TOL_EIXO:
                quebras[k].add(min(max(t, 0.0), 1.0))
            elif dist < max(p.b, p.h) / 2.0:
                g.erros.append(
                    f"viga {segmentos[k][0].nome} ({pav.nome}) passa a "
                    f"{dist * 100:.1f} cm do eixo do pilar {p.nome}: a "
                    "excentricidade viga–pilar ainda não é modelada — alinhe "
                    "a viga pelo eixo do pilar")

    pilar_no_ponto = {_chave(*c): p for p, c, _ in com_pilar}
    for k, (v, a, b) in enumerate(segmentos):
        ts = sorted(quebras[k])
        pts = [(a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])) for t in ts]
        unicos = [pts[0]]
        for p in pts[1:]:
            if math.dist(p, unicos[-1]) > TOL:
                unicos.append(p)
        barras = g.mapa.setdefault(("viga", v.nome, pav.nome), [])
        for pa, pb in zip(unicos, unicos[1:]):
            na = no(nivel, *pa, f"{pav.nome}.N")
            nb = no(nivel, *pb, f"{pav.nome}.N")
            for chave, n in ((_chave(*pa), na), (_chave(*pb), nb)):
                if chave in pilar_no_ponto:
                    pilar_do_no.setdefault(n, pilar_no_ponto[chave])
            nome = f"{v.nome}.{pav.nome}.{len(barras) + 1}"
            off = []
            for n in (na, nb):
                p = pilar_do_no.get(n)
                if p is None or not lanc.trecho_rigido:
                    off.append(0.0)
                    continue
                c = p.dimensao_na_direcao(pb[0] - pa[0], pb[1] - pa[1])
                off.append(max(0.0, c / 2.0 - 0.3 * v.h))
            L = math.dist(pa, pb)
            if off[0] + off[1] >= 0.9 * L:
                g.avisos.append(f"viga {v.nome} ({pav.nome}): trecho de "
                                f"{L:.2f} m curto demais para os trechos "
                                "rígidos — ficou sem eles")
                off = [0.0, 0.0]
            m.add_barra(nome, na, nb, "concreto", secao(v.b, v.h),
                        offset_i=off[0], offset_j=off[1])
            barras.append(nome)


def _gerar_laje(m: Modelo, g: Geracao, laje, pav, nivel: int,
                nos_do_nivel: list, cotas: list) -> None:
    """Acha o retângulo de vigas em volta do ponto e cria o ``core.Laje``."""
    z = cotas[nivel]
    px, py = laje.x, laje.y
    horizontais, verticais = [], []
    for nome, b in m.barras.items():
        pi, pj = m.ponto(b.no_i), m.ponto(b.no_j)
        if abs(pi[2] - z) > TOL or abs(pj[2] - z) > TOL:
            continue
        if abs(pi[1] - pj[1]) < TOL:
            horizontais.append((float(pi[1]), *sorted((pi[0], pj[0]))))
        elif abs(pi[0] - pj[0]) < TOL:
            verticais.append((float(pi[0]), *sorted((pi[1], pj[1]))))

    def mais_perto(linhas, coord, ao_longo, sinal):
        candidatas = [l for l in linhas if l[1] - TOL < ao_longo < l[2] + TOL
                      and sinal * (l[0] - coord) > TOL]
        if not candidatas:
            return None
        return min(candidatas, key=lambda l: abs(l[0] - coord))[0]

    rotulo = f"laje {laje.nome} ({pav.nome})"
    if laje.balanco > 0.0:
        _gerar_laje_em_balanco(m, g, laje, pav, nivel, nos_do_nivel,
                               horizontais, verticais, rotulo)
        return
    y0 = mais_perto(horizontais, py, px, -1)
    y1 = mais_perto(horizontais, py, px, 1)
    x0 = mais_perto(verticais, px, py, -1)
    x1 = mais_perto(verticais, px, py, 1)
    if None in (x0, x1, y0, y1):
        g.erros.append(f"{rotulo}: o ponto ({px:g}; {py:g}) não está "
                       "fechado por vigas nos quatro lados")
        return

    def coberto(linhas, coord, ini, fim) -> bool:
        trechos = sorted((l[1], l[2]) for l in linhas
                         if abs(l[0] - coord) < TOL and l[2] > ini + TOL
                         and l[1] < fim - TOL)
        alcance = ini
        for a, b in trechos:
            if a > alcance + TOL:
                return False
            alcance = max(alcance, b)
        return alcance >= fim - TOL

    if not (coberto(horizontais, y0, x0, x1) and coberto(horizontais, y1, x0,
                                                         x1)
            and coberto(verticais, x0, y0, y1)
            and coberto(verticais, x1, y0, y1)):
        g.erros.append(f"{rotulo}: o contorno em volta de ({px:g}; {py:g}) "
                       "não é um retângulo fechado de vigas — laje não "
                       "retangular ainda não é gerada; divida-a com vigas")
        return
    atravessa = ([l for l in horizontais if y0 + TOL < l[0] < y1 - TOL
                  and l[1] < x1 - TOL and l[2] > x0 + TOL]
                 + [l for l in verticais if x0 + TOL < l[0] < x1 - TOL
                    and l[1] < y1 - TOL and l[2] > y0 + TOL])
    if atravessa:
        g.erros.append(f"{rotulo}: há viga dentro do painel — lance uma laje "
                       "de cada lado dela")
        return
    tabela = nos_do_nivel[nivel]
    a, c = tabela.get(_chave(x0, y0)), tabela.get(_chave(x1, y1))
    if a is None or c is None:
        g.erros.append(f"{rotulo}: falta nó num canto do painel")
        return
    nome = f"{laje.nome}.{pav.nome}"
    if nome in m.lajes:
        g.erros.append(f"{rotulo}: repetida")
        return
    m.add_laje(nome, a, c, laje.espessura if laje.tipo == "macica" else 0.0,
               "concreto", laje.permanente, laje.acidental, laje.tipo_carga,
               tipo=laje.tipo, direcao=laje.direcao, trelica=laje.trelica,
               enchimento=laje.enchimento,
               altura_enchimento=laje.altura_enchimento, capa=laje.capa,
               largura_bloco=laje.largura_bloco,
               base_vigota=laje.base_vigota)
    g.mapa[("laje", laje.nome, pav.nome)] = [nome]


def _gerar_laje_em_balanco(m: Modelo, g: Geracao, laje, pav, nivel: int,
                           nos_do_nivel: list, horizontais: list,
                           verticais: list, rotulo: str) -> None:
    """A laje em balanço: o ponto lançado fica na sacada, e a viga de apoio
    é a primeira que se encontra andando **contra** o ``sentido`` — no
    máximo a ``balanco`` do ponto. Ao longo da viga, a laje vai de um eixo
    perpendicular a outro (os que chegam à viga dos dois lados do ponto, os
    mesmos que fecham a laje de dentro)."""
    px, py = laje.x, laje.y
    if laje.sentido not in ("+x", "-x", "+y", "-y"):
        g.erros.append(f"{rotulo}: em balanço, o sentido é +x, -x, +y ou -y")
        return
    if laje.tipo != "macica":
        g.erros.append(f"{rotulo}: laje em balanço só maciça")
        return
    sinal = 1 if laje.sentido[0] == "+" else -1
    if laje.sentido[1] == "y":
        apoios, transversais, coord, ao_longo = horizontais, verticais, py, px
    else:
        apoios, transversais, coord, ao_longo = verticais, horizontais, px, py
    # a viga de apoio fica atrás do ponto (contra o sentido), e o ponto cai
    # dentro do balanço
    candidatas = [l for l in apoios if l[1] - TOL < ao_longo < l[2] + TOL
                  and 0.0 < -sinal * (l[0] - coord) <= laje.balanco + TOL]
    if not candidatas:
        g.erros.append(
            f"{rotulo}: não há viga a até {laje.balanco:g} m do ponto "
            f"({px:g}; {py:g}), no sentido contrário ao balanço "
            f"({laje.sentido}) — é nela que a laje se apoia")
        return
    apoio = min(candidatas, key=lambda l: abs(l[0] - coord))[0]

    def limite(lado: int):
        achadas = [l[0] for l in transversais
                   if l[1] - TOL <= apoio <= l[2] + TOL
                   and lado * (l[0] - ao_longo) > TOL]
        return (min(achadas, key=lambda v: abs(v - ao_longo))
                if achadas else None)

    s0, s1 = limite(-1), limite(1)
    if s0 is None or s1 is None:
        g.erros.append(
            f"{rotulo}: o lado apoiado precisa de uma viga transversal "
            "chegando à viga de apoio de cada lado do ponto — são elas que "
            "limitam a laje ao longo da viga")
        return
    tabela = nos_do_nivel[nivel]
    if laje.sentido[1] == "y":
        a, c = tabela.get(_chave(s0, apoio)), tabela.get(_chave(s1, apoio))
    else:
        a, c = tabela.get(_chave(apoio, s0)), tabela.get(_chave(apoio, s1))
    if a is None or c is None:
        g.erros.append(f"{rotulo}: falta nó numa ponta do lado apoiado")
        return
    nome = f"{laje.nome}.{pav.nome}"
    if nome in m.lajes:
        g.erros.append(f"{rotulo}: repetida")
        return
    m.add_laje(nome, a, c, laje.espessura, "concreto", laje.permanente,
               laje.acidental, laje.tipo_carga, balanco=laje.balanco,
               sentido=laje.sentido)
    g.mapa[("laje", laje.nome, pav.nome)] = [nome]


def _gerar_paredes(m: Modelo, g: Geracao, planta, pav, nivel: int,
                   cotas: list, G) -> None:
    """A parede vira carga distribuída nas vigas que estão embaixo dela."""
    z = cotas[nivel]
    acima = cotas[nivel + 1] if nivel + 1 < len(cotas) else None
    for parede in planta.paredes:
        for a, b in zip(parede.pontos, parede.pontos[1:]):
            a, b = np.array(a, float), np.array(b, float)
            Lp = float(np.linalg.norm(b - a))
            if Lp <= TOL:
                continue
            u = (b - a) / Lp
            coberto = []
            for nome, barra in m.barras.items():
                pi, pj = m.ponto(barra.no_i), m.ponto(barra.no_j)
                if abs(pi[2] - z) > TOL or abs(pj[2] - z) > TOL:
                    continue
                ti = float((pi[:2] - a) @ u)
                tj = float((pj[:2] - a) @ u)
                fora = max(float(np.linalg.norm(pi[:2] - a - ti * u)),
                           float(np.linalg.norm(pj[:2] - a - tj * u)))
                if fora > TOL:
                    continue
                s0, s1 = max(min(ti, tj), 0.0), min(max(ti, tj), Lp)
                if s1 - s0 <= TOL:
                    continue
                coberto.append((s0, s1))
                secao = m.secoes[barra.secao]
                altura = parede.altura
                if altura <= 0.0:
                    pe = (acima - z) if acima is not None else \
                        (z - cotas[nivel - 1])
                    altura = max(pe - secao.h, 0.0)
                    if acima is None:
                        g.avisos.append(
                            f"parede {parede.nome} ({pav.nome}) na cobertura "
                            "sem altura: adotado o pé-direito de baixo")
                q = parede.peso_especifico * parede.espessura * altura
                # posição na barra, medida do nó i
                L = m.comprimento(nome)
                da = abs(s0 - ti) if ti <= tj else abs(ti - s1)
                db = da + (s1 - s0)
                f0, f1 = barra.offset_i, L - barra.offset_j
                ia, ib = max(da, f0), min(db, f1)
                if ib - ia <= TOL:
                    continue
                G.distribuida(nome, qz=-q, sistema="global",
                              inicio=(ia - f0) / (f1 - f0),
                              fim=(ib - f0) / (f1 - f0),
                              origem=f"parede:{parede.nome}")
            coberto.sort()
            alcance = 0.0
            for s0, s1 in coberto:
                if s0 > alcance + TOL:
                    break
                alcance = max(alcance, s1)
            if alcance < Lp - TOL:
                g.erros.append(
                    f"parede {parede.nome} ({pav.nome}): o trecho de "
                    f"({a[0]:g}; {a[1]:g}) a ({b[0]:g}; {b[1]:g}) não está "
                    "inteiro sobre viga — parede sobre laje ainda não vira "
                    "carga da laje")


def _avisar_vigas_soltas(m: Modelo, g: Geracao) -> None:
    from ..continuidade import vigas_continuas
    for v in vigas_continuas(m):
        if not v.suportes:
            g.avisos.append(f"viga {v.nome} ({', '.join(v.barras[:3])}…) "
                            "sem apoio em pilar nem em viga")
