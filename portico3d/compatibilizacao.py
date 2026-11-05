# -*- coding: utf-8 -*-
"""
compatibilizacao.py
O que acontece **entre** as peças: a continuidade do pilar de um lance para
o outro, e o nó em que a viga encontra o pilar.

Cada motor de elemento dimensiona a sua peça sozinho — o de Pilares um lance
por vez, o de Vigas uma viga contínua por vez. O que nenhum dos dois vê é a
fronteira entre elas, e é aqui que ela é conferida. Base normativa,
conferida no PDF da NBR 6118:2026:

* **9.5.2.3** — emenda por traspasse de barras comprimidas:
  ``ℓ0c = ℓb,nec ≥ ℓ0c,mín``, este o maior entre ``0,6·ℓb``, ``15·φ`` e
  200 mm. O ``ℓ0c`` de cada lance já sai do motor de Pilares (a espera).
* **17.3.5.3.2** — ``As,máx = 0,08·Ac``, "inclusive a sobreposição de
  armadura existente em regiões de emenda". Na emenda, as barras do lance de
  baixo e as do de cima convivem na seção do de cima: a taxa é a das duas.
* **18.4.2.2** — o espaçamento livre mínimo (20 mm, φ e 1,2·dmáx) "se aplica
  também às regiões de emendas por traspasse".
* **18.4.3** — o estribo do pilar é "obrigatória[mente]" colocado "na região
  de cruzamento com vigas e lajes".
* **21.4** — nós de pórtico: "a resistência do conjunto depende da
  resistência à tração do concreto e da disposição da armadura, que devem
  ser consideradas no dimensionamento". A norma não dá conta para o nó: ele é
  região D (Figura 22.1, a2), de bielas e tirantes. O que se faz aqui é o que
  dá para conferir sem modelo de bielas — a ancoragem da viga dentro do
  pilar, a largura, e a marcação dos nós de canto, onde o detalhamento do
  laço é obrigatório e é de quem detalha.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .core.modelo import Modelo

TOL = 1.0e-6
#: 17.3.5.3.2
TAXA_MAXIMA = 0.08
#: Dimensão máxima do agregado graúdo, cm — a brita 1 usual (o motor de
#: Pilares usa o mesmo padrão).
DMAX_AGREGADO = 1.9


# ---------------------------------------------------------------------------
# Continuidade dos pilares
# ---------------------------------------------------------------------------

@dataclass
class Lance:
    barra: str
    base: float                 # m, cota
    topo: float
    b: float                    # cm, direção X
    h: float                    # cm, direção Y
    n: int = 0
    phi: float = 0.0            # mm
    As: float = 0.0             # cm²
    l0c: float = 0.0            # cm, espera (9.5.2.3)
    recuo: float = 0.0          # cm, face ao eixo da barra
    nx: int = 0                 # barras em cada face que corre em X (b)
    ny: int = 0                 # barras em cada face que corre em Y (h)
    aprovado: bool = False
    sem_veredito: str = ""


@dataclass
class Transicao:
    """A emenda entre um lance e o de cima, no nível do pavimento."""

    abaixo: str
    acima: str
    cota: float
    l0c: float                  # cm, a espera das barras de baixo
    taxa_emenda: float          # (As abaixo + As acima) / Ac acima
    espaco_livre: float         # cm, entre pares emendados
    espaco_minimo: float
    param: int = 0              # barras de baixo que não continuam
    comecam: int = 0            # barras de cima que não têm de onde vir
    reducao: tuple[float, float] = (0.0, 0.0)   # cm, recuo de cada face
    avisos: list[str] = field(default_factory=list)

    @property
    def taxa_ok(self) -> bool:
        return self.taxa_emenda <= TAXA_MAXIMA + 1e-9

    @property
    def espaco_ok(self) -> bool:
        return self.espaco_livre >= self.espaco_minimo - 1e-9

    @property
    def ok(self) -> bool:
        return self.taxa_ok and self.espaco_ok


@dataclass
class Prumada:
    nome: str
    lances: list[Lance] = field(default_factory=list)
    transicoes: list[Transicao] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(t.ok for t in self.transicoes)


def _arranjo_adotado(verificacoes: list):
    """O arranjo executado de um lance: entre as combinações aprovadas, o de
    maior área de aço — é ele que governa (o mesmo critério do desenho 3D)."""
    aprovadas = [v for v in verificacoes if v.aprovado]
    candidatas = aprovadas or [v for v in verificacoes if v.passou]
    if not candidatas:
        return None, bool(aprovadas)

    def area(v):
        arr = getattr(v.resultado, "arranjo", None)
        return float(getattr(arr, "As", 0.0) or 0.0)

    return max(candidatas, key=area), bool(aprovadas)


def prumadas(modelo: Modelo, verificacoes_pilares: list) -> list[Prumada]:
    """As prumadas do edifício, lance a lance, com as emendas entre eles."""
    from .dimensionamento import barras_verticais

    por_barra: dict[str, list] = {}
    for v in verificacoes_pilares:
        por_barra.setdefault(v.barra, []).append(v)

    grupos: dict[tuple, list[Lance]] = {}
    for nome in barras_verticais(modelo):
        b = modelo.barras[nome]
        pi, pj = modelo.ponto(b.no_i), modelo.ponto(b.no_j)
        base, topo = sorted((float(pi[2]), float(pj[2])))
        secao = modelo.secoes[b.secao]
        lance = Lance(nome, base, topo, secao.b * 100.0, secao.h * 100.0)
        escolhida, aprovado = _arranjo_adotado(por_barra.get(nome, []))
        if escolhida is None:
            lance.sem_veredito = "sem dimensionamento"
        else:
            arr = escolhida.resultado.arranjo
            anc = getattr(escolhida.resultado, "ancoragem", None)
            lance.n = arr.n_barras
            lance.phi = arr.phi
            lance.As = arr.As
            lance.recuo = arr.recuo
            lance.nx, lance.ny = arr.nx, arr.ny
            lance.l0c = getattr(anc, "l0c", 0.0) if anc is not None else 0.0
            lance.aprovado = aprovado
        chave = (round(float(pi[0]), 4), round(float(pi[1]), 4))
        grupos.setdefault(chave, []).append(lance)

    saida = []
    for (x, y), lances in sorted(grupos.items()):
        lances.sort(key=lambda l: l.base)
        p = Prumada(f"({x:g}; {y:g})", lances)
        for baixo, cima in zip(lances, lances[1:]):
            if abs(baixo.topo - cima.base) > TOL or not baixo.n or not cima.n:
                continue
            p.transicoes.append(_transicao(baixo, cima))
        saida.append(p)
    return saida


def _transicao(baixo: Lance, cima: Lance) -> Transicao:
    ac = cima.b * cima.h
    phi = max(baixo.phi, cima.phi) / 10.0
    # Na emenda as barras andam aos pares, encostadas: entre um par e o
    # vizinho o espaço livre é o passo das barras, na seção de cima, menos a
    # largura do par (as duas bitolas). Cada face com as suas barras — a que
    # corre em X (lado b) e a que corre em Y (lado h) —, e vale a pior.
    par = (baixo.phi + cima.phi) / 10.0
    livres = []
    for lado, n in ((cima.b, max(cima.nx, baixo.nx)),
                    (cima.h, max(cima.ny, baixo.ny))):
        if n >= 2:
            livres.append((lado - 2.0 * cima.recuo) / (n - 1) - par)
    livre = min(livres) if livres else float("inf")
    minimo = max(2.0, phi, 1.2 * DMAX_AGREGADO)

    t = Transicao(baixo.barra, cima.barra, baixo.topo, baixo.l0c,
                  (baixo.As + cima.As) / ac if ac > 0 else 0.0,
                  livre, minimo,
                  param=max(baixo.n - cima.n, 0),
                  comecam=max(cima.n - baixo.n, 0),
                  reducao=(max(baixo.b - cima.b, 0.0) / 2.0,
                           max(baixo.h - cima.h, 0.0) / 2.0))
    if not t.taxa_ok:
        t.avisos.append(
            f"taxa na emenda {100 * t.taxa_emenda:.1f} % > 8 % "
            "(17.3.5.3.2, a sobreposição conta): escalone as emendas ou "
            "aumente a seção")
    if not t.espaco_ok:
        t.avisos.append(
            f"espaço livre entre pares emendados {t.espaco_livre:.1f} cm < "
            f"{t.espaco_minimo:.1f} cm (18.4.2.2 vale na emenda)")
    if t.param:
        t.avisos.append(
            f"{t.param} barra(s) de {baixo.barra} não continuam acima: "
            "ancorar no nó (ℓb a partir da face de baixo da viga)")
    if t.comecam:
        t.avisos.append(
            f"{t.comecam} barra(s) de {cima.barra} nascem no pavimento: "
            f"precisam de espera de {cima.l0c:.0f} cm dentro de {baixo.barra}")
    if max(t.reducao) > 0.0:
        t.avisos.append(
            f"seção reduz de {baixo.b:.0f}×{baixo.h:.0f} para "
            f"{cima.b:.0f}×{cima.h:.0f} cm: as barras de baixo recuam "
            f"{max(t.reducao):.1f} cm — dobrar a espera ou usar esperas "
            "novas")
    if abs(baixo.phi - cima.phi) > 1e-9:
        t.avisos.append(
            f"bitola muda de ø{baixo.phi:g} para ø{cima.phi:g}: a emenda é "
            "calculada pela barra de baixo, que é a que espera")
    return t


# ---------------------------------------------------------------------------
# Nós viga–pilar
# ---------------------------------------------------------------------------

@dataclass
class EncontroDeViga:
    viga: str
    direcao: str                # "X", "Y" ou "oblíqua"
    extremo: bool               # a viga termina neste pilar
    bw: float                   # cm
    largura_pilar: float        # cm, na direção da viga
    largura_transversal: float  # cm, perpendicular a ela
    ancoragem_ok: bool | None = None
    ancoragem: str = ""


@dataclass
class No:
    no: str
    cota: float
    pilar_abaixo: str = ""
    pilar_acima: str = ""
    vigas: list[EncontroDeViga] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def tipo(self) -> str:
        extremos = [e for e in self.vigas if e.extremo]
        if not self.pilar_acima and extremos:
            return "canto (cobertura)" if len(self.vigas) <= 2 else "topo"
        if len(extremos) == len(self.vigas):
            return "canto" if len(self.vigas) >= 2 else "extremidade"
        if extremos:
            return "borda"
        return "interno"

    @property
    def ok(self) -> bool:
        """Ancoragem e largura atendem. O nó de joelho continua "ok": o
        aviso dele é de detalhamento, não de reprovação."""
        return all(e.ancoragem_ok is not False for e in self.vigas) and \
            all(e.bw <= e.largura_transversal + 1e-6 for e in self.vigas)


def largura_do_pilar(modelo: Modelo, barra: str, direcao) -> tuple[float,
                                                                     float]:
    """Dimensões do pilar, cm: ``(na direção dada, perpendicular a ela)``.

    ``b`` mede no eixo local y da barra e ``h`` no z; projeta-se a direção
    dada nos dois. Os eixos locais vêm da montagem, **com a rotação da
    barra**: na barra vertical sem rotação o y local é o X global, mas o
    pilar lançado girado 90° vira barra com ``rotacao = 90``, e aí o ``b``
    mede em Y. Supor y = X, como se fazia, trocava os lados de todo pilar
    girado — a viga em Y sobre um 20×50 girado recebia 50 cm de apoio em
    vez de 20, e com eles a ancoragem, o arredondamento do momento sobre o
    apoio e a posição dos estribos.
    """
    from .core.montagem import preparar_barras

    secao = modelo.secoes[modelo.barras[barra].secao]
    d = np.array(direcao, dtype=float)[:2]
    d = d / (float(np.linalg.norm(d)) or 1.0)
    R = preparar_barras(modelo)[barra].R
    ey, ez = np.asarray(R[1], float)[:2], np.asarray(R[2], float)[:2]
    ao_longo = abs(float(d @ ey)) * secao.b + abs(float(d @ ez)) * secao.h
    perp = np.array([-d[1], d[0]])
    atravessado = abs(float(perp @ ey)) * secao.b + \
        abs(float(perp @ ez)) * secao.h
    return ao_longo * 100.0, atravessado * 100.0


def nos_viga_pilar(modelo: Modelo, verificacoes_vigas: list) -> list[No]:
    """Os nós em que uma viga encontra um pilar, com o que dá para conferir
    sem modelo de bielas."""
    from .continuidade import _eh_vertical, vigas_continuas

    pilares_no: dict[str, dict[str, str]] = {}
    for nome, b in modelo.barras.items():
        if not _eh_vertical(modelo, b):
            continue
        baixo, alto = (b.no_i, b.no_j) if modelo.ponto(b.no_i)[2] <= \
            modelo.ponto(b.no_j)[2] else (b.no_j, b.no_i)
        pilares_no.setdefault(alto, {})["abaixo"] = nome
        pilares_no.setdefault(baixo, {})["acima"] = nome

    por_nome = {v.nome: v for v in verificacoes_vigas}
    nos: dict[str, No] = {}
    for viga in vigas_continuas(modelo):
        verif = por_nome.get(viga.nome)
        d = np.array(viga.direcao, dtype=float)
        rotulo = ("X" if abs(d[0]) > 0.999 else "Y" if abs(d[1]) > 0.999
                  else "oblíqua")
        secao = modelo.secoes[modelo.barras[viga.barras[0]].secao]
        suportes = viga.suportes
        for k in viga.apoios:
            no = viga.nos[k]
            pil = pilares_no.get(no, {})
            ref = pil.get("abaixo") or pil.get("acima")
            if ref is None:
                continue
            ao_longo, atravessado = largura_do_pilar(modelo, ref, d)
            primeiro_ou_ultimo = k in (suportes[0], suportes[-1])
            sem_balanco = ((k == suportes[0] and viga.balanco_inicial <= TOL)
                           or (k == suportes[-1]
                               and viga.balanco_final <= TOL))
            e = EncontroDeViga(viga.nome, rotulo,
                               primeiro_ou_ultimo and sem_balanco,
                               secao.b * 100.0, ao_longo, atravessado)
            if e.extremo and verif is not None and verif.passou:
                # o motor verifica os apoios de extremidade em ordem: o
                # primeiro é o do começo da viga, o último o do fim
                extremos = sorted(getattr(verif.resultado,
                                          "apoios_extremos", []),
                                  key=lambda a: a.apoio)
                if extremos:
                    a = extremos[0] if k == suportes[0] else extremos[-1]
                    e.ancoragem_ok = bool(a.ok)
                    e.ancoragem = (f"disponível {a.l_disponivel:.1f} cm, "
                                   f"exigido {a.lb_nec:.1f} cm")
            n = nos.setdefault(no, No(no, float(modelo.ponto(no)[2]),
                                      pil.get("abaixo", ""),
                                      pil.get("acima", "")))
            n.vigas.append(e)

    for n in nos.values():
        for e in n.vigas:
            if e.bw > e.largura_transversal + 1e-6:
                n.avisos.append(
                    f"{e.viga} (bw = {e.bw:.0f} cm) é mais larga que o pilar "
                    f"({e.largura_transversal:.0f} cm): as barras de canto "
                    "da viga passam fora do pilar")
            if e.ancoragem_ok is False:
                n.avisos.append(
                    f"{e.viga}: a armadura positiva não ancora dentro do "
                    f"pilar ({e.ancoragem}) — 18.3.2.4")
        if not n.pilar_acima and any(e.extremo for e in n.vigas):
            # O nó de joelho: a viga termina e o pilar também. O momento da
            # viga muda de direção e passa inteiro para o pilar, e a armadura
            # negativa de um tem de se ancorar no outro.
            n.avisos.append(
                "nó de joelho (sem pilar acima): região D (Figura 22.1, a2) — "
                "a armadura negativa da viga desce no pilar e a do pilar entra "
                "na viga; detalhar o laço (21.4)")
    return sorted(nos.values(), key=lambda n: (n.cota, n.no))


# ---------------------------------------------------------------------------
# Relatório
# ---------------------------------------------------------------------------

def resumo(lista_prumadas: list[Prumada], lista_nos: list[No]) -> str:
    linhas = []
    if lista_prumadas:
        transicoes = [t for p in lista_prumadas for t in p.transicoes]
        problemas = [t for t in transicoes if not t.ok]
        linhas.append(
            f"Continuidade dos pilares — {len(lista_prumadas)} prumadas, "
            f"{len(transicoes)} emendas: "
            + ("todas atendem 17.3.5.3.2 e 18.4.2.2" if not problemas
               else f"{len(problemas)} com problema"))
        for p in lista_prumadas:
            for t in p.transicoes:
                if t.avisos:
                    linhas.append(
                        f"  {p.nome} z = {t.cota:g} m ({t.abaixo} → "
                        f"{t.acima}): espera {t.l0c:.0f} cm, taxa na emenda "
                        f"{100 * t.taxa_emenda:.1f} %")
                    linhas += [f"    {a}" for a in t.avisos]
    if lista_nos:
        ruins = [n for n in lista_nos if not n.ok]
        tipos: dict[str, int] = {}
        for n in lista_nos:
            tipos[n.tipo] = tipos.get(n.tipo, 0) + 1
        linhas.append(
            f"Nós viga–pilar — {len(lista_nos)} nós ("
            + ", ".join(f"{q} {t}" for t, q in sorted(tipos.items()))
            + "): " + ("ancoragem e largura atendem" if not ruins
                       else f"{len(ruins)} com problema"))
        for n in lista_nos:
            for a in n.avisos:
                if a.startswith("nó de joelho"):
                    continue
                linhas.append(f"  {n.no} (z = {n.cota:g} m, {n.tipo}): {a}")
        joelhos = [n.no for n in lista_nos
                   if any(a.startswith("nó de joelho") for a in n.avisos)]
        if joelhos:
            linhas.append(
                f"  {len(joelhos)} nó(s) de joelho na cobertura — região D "
                "(21.4, Figura 22.1 a2): detalhar o laço da armadura negativa "
                "entre viga e pilar")
    return "\n".join(linhas)
