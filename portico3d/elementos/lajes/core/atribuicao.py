# -*- coding: utf-8 -*-
"""
atribuicao.py
Lajes treliçadas, alveolares e nervuradas **atribuídas** aos retângulos da
planta do pavimento.

Até a R08 esses sistemas só existiam como "extras" -- uma faixa ou um painel
lançado à parte, nas abas 10 a 13, com vão, apoios e cargas digitados de novo.
Na R09 o tipo é um atributo da laje da planta (``Laje.tipo``) e o motor de
cada sistema continua sendo o mesmo; o que muda é de onde vêm os dados:

====================  =====================================================
da planta (a laje)    posição, vãos livres, largura dos apoios (``t`` do
                      bordo), vinculação dos bordos, revestimento, reboco,
                      permanente adicional, variável, paredes
do perfil (a aba)     seção da nervura ou do painel, treliça, protensão,
                      armadura escolhida, critérios, materiais do sistema
====================  =====================================================

O perfil é um item da lista do pavimento (``trelicadas``, ``alveolares``,
``nervuradas_uni``, ``nervuradas_bi``) e a laje o escolhe pelo nome
(``Laje.perfil``). Vários retângulos podem usar o mesmo perfil.

Hipóteses declaradas (cada uma vira observação na memória de cálculo):

* **faixas contínuas** -- lajes treliçadas ou nervuradas unidirecionais de
  mesmo perfil e mesma direção, alinhadas e com a mesma largura, encostadas
  numa viga comum, formam **uma** faixa de vários vãos (o mesmo motor de
  viga contínua, três momentos com alternância de sobrecarga). Com largura ou
  perfil diferentes a continuidade não é suposta: cada laje vira uma faixa
  biapoiada;
* **maciça vizinha** -- não há engaste entre uma laje de nervura (ou painel)
  e uma maciça: o bordo da maciça fica apoiado (``Pavimento.
  detectar_continuidades`` só relaciona maciças entre si);
* **engaste de ponta** -- numa laje de nervura unidirecional ou alveolar o
  bordo engastado de ponta de vão é tratado como apoio simples (a faixa
  contínua do motor não modela o momento de engastamento da ponta);
* **paredes** -- a alvenaria sobre a laje entra espalhada na área
  (``Laje.g_paredes_distribuida``), sem a carga concentrada na nervura sob a
  parede -- que continua a ser verificada à parte, como carga linear, nas
  abas dos sistemas;
* **reações nas vigas** -- das faixas e dos painéis saem só nos dois bordos
  das pontas do vão; da nervurada bidirecional saem nos quatro, pela mesma
  partição geométrica da laje maciça (``reacoes.py``).
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

from . import avisos as av
from . import reacoes as rc
from .alveolar import resolver as resolver_alveolar
from .modelo import (LISTA_DO_TIPO, ROTULO_TIPO, TIPOS_UNIDIRECIONAIS,
                     Laje, Pavimento, _continuidades_geometricas)
from .nervurada import dimensionar_nervurada
from .trelicada import dimensionar_trelicada
from .trelicada_modelo import ApoioTrelicado, VaoTrelicado

#: Folga máxima, m, entre dois retângulos de vão livre que dividem uma viga
#: (a largura dela) -- a mesma de ``Pavimento.detectar_continuidades``.
FOLGA_VIGA = 0.40

#: Tolerância, m, para duas lajes valerem como "alinhadas e da mesma largura"
#: na formação da faixa contínua.
TOLERANCIA_ALINHAMENTO = 0.15


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class ResultadoEspecial:
    """Um sistema calculado a partir de uma ou mais lajes da planta.

    ``lajes`` tem mais de um nome só na faixa contínua. ``modelo`` é o item
    derivado (a faixa, o painel) que o motor recebeu, e ``resultado`` o que
    ele devolveu -- do mesmo tipo que as abas dos extras mostram.
    """

    tipo: str
    nome: str
    lajes: list[str] = field(default_factory=list)
    perfil: str = ""
    modelo: object = None
    resultado: object = None
    reacoes: dict[str, rc.ReacoesLaje] = field(default_factory=dict)
    area: float = 0.0                  # m², em planta (vãos livres)
    aco_kg: float = 0.0                # armadura passiva + ativa
    concreto_m3: float = 0.0           # moldado no local
    premoldado_m3: float = 0.0         # painéis alveolares
    n_paineis: int = 0
    avisos: list[av.Aviso] = field(default_factory=list)
    erro: str = ""

    @property
    def rotulo_tipo(self) -> str:
        return ROTULO_TIPO[self.tipo]

    @property
    def rotulo(self) -> str:
        return f"{self.nome} ({self.rotulo_tipo.lower()})"

    @property
    def vaos_texto(self) -> str:
        """Os vãos do sistema, para tabela: eixo a eixo, em metros."""
        m = self.modelo
        if m is None:
            return "—"
        if self.tipo in ("trelicada", "nervurada_uni"):
            return " + ".join(f"{v.L / 100.0:.2f}" for v in m.vaos) + " m"
        if self.tipo == "alveolar":
            return f"{m.vao:.2f} m"
        return f"{m.lx:.2f} x {m.ly:.2f} m"

    @property
    def atende(self) -> bool:
        if self.erro or self.resultado is None:
            return False
        return bool(self.resultado.atende)


# ---------------------------------------------------------------------------
# Geometria e cargas a partir da planta
# ---------------------------------------------------------------------------

@dataclass
class _GeoUni:
    """Geometria de uma laje de nervura (ou painel) de um só vão."""

    laje: Laje
    eixo: str              # eixo global em que o vão corre ("X" ou "Y")
    l0: float              # m, vão livre
    largura: float         # m, dimensão transversal ao vão
    ini: float             # m, coordenada do início do vão ao longo do eixo
    fim: float
    cruz0: float           # m, início da faixa na direção transversal
    cruz1: float
    b_ini: int             # bordo na ponta de menor coordenada
    b_fim: int
    t_ini: float           # cm
    t_fim: float

    @property
    def livre(self) -> bool:
        return any(self.laje.bordos[k - 1].vinculo == "livre"
                   for k in (self.b_ini, self.b_fim))


def _geo_uni(laje: Laje) -> _GeoUni:
    d = laje.direcao
    fim_k = (2, 4) if d == "a" else (1, 3)
    eixo = laje.direcao_global(d)
    x0, y0, x1, y1 = laje.retangulo
    ini, fim = (x0, x1) if eixo == "X" else (y0, y1)
    cruz0, cruz1 = (y0, y1) if eixo == "X" else (x0, x1)
    face_ini = "esquerda" if eixo == "X" else "baixo"
    b_ini = next(k for k in fim_k if laje.face_do_bordo(k) == face_ini)
    b_fim = fim_k[0] if b_ini == fim_k[1] else fim_k[1]
    return _GeoUni(
        laje=laje, eixo=eixo, l0=laje.a if d == "a" else laje.b,
        largura=laje.b if d == "a" else laje.a, ini=ini, fim=fim,
        cruz0=cruz0, cruz1=cruz1, b_ini=b_ini, b_fim=b_fim,
        t_ini=laje.bordos[b_ini - 1].t, t_fim=laje.bordos[b_fim - 1].t)


def cargas_da_laje(laje: Laje) -> tuple[float, float]:
    """``(g, q)`` em kN/m² que a planta entrega ao sistema.

    ``g`` é só o que vem **além do peso próprio do sistema** -- que o motor
    calcula da própria seção: revestimento, reboco, enchimento da laje
    rebaixada, permanente adicional e as paredes espalhadas.
    """
    g = (laje.revestimento + laje.reboco + laje.carga_enchimento
         + laje.permanente_extra + laje.g_paredes_distribuida())
    return g, laje.variavel


def altura_do_perfil(tipo: str, modelo) -> float:
    """Altura total da laje que o perfil define, cm."""
    if tipo == "alveolar":
        return modelo.sec.h + modelo.capa
    return modelo.h


def sincronizar_alturas(pav: Pavimento) -> int:
    """Faz a espessura ``h`` de cada laje especial valer a do perfil dela.

    Só a apresentação (tabela, vista 3D, espessura mínima) lê ``h`` dessas
    lajes -- os motores usam a seção do perfil. Devolve quantas mudaram.
    """
    mudou = 0
    for laje in pav.lajes_especiais:
        p = pav.perfil_da(laje)
        if p is None:
            continue
        h = round(altura_do_perfil(laje.tipo, p), 3)
        if abs(laje.h - h) > 1e-9:
            laje.h = h
            mudou += 1
    return mudou


def _aviso(texto: str, laje: str = "", erro: bool = False) -> av.Aviso:
    return av.Aviso(texto, av.ERRO if erro else av.CONSTRUTIVO, laje)


def _avisos_do_motor(res, laje: str) -> list[av.Aviso]:
    """Os avisos ``(classe, texto)`` dos motores como :class:`Aviso`."""
    return [av.Aviso(t, av.ERRO if c == "erro" else av.CONSTRUTIVO, laje)
            for c, t in res.avisos]


def _reacoes_uni(laje: Laje, b_ini: int, b_fim: int, v_ini: tuple,
                 v_fim: tuple) -> rc.ReacoesLaje:
    """Monta as reações de uma laje de um só vão a partir de ``(v_g, v_q,
    v_d)`` em kN/m nas duas pontas; os outros dois bordos ficam sem carga."""
    r = rc.ReacoesLaje(laje=laje.nome, carga_total=0.0, carga_total_d=0.0)
    dados = {b_ini: v_ini, b_fim: v_fim}
    for k in (1, 2, 3, 4):
        bordo = laje.bordos[k - 1]
        comp = laje.a if rc.COMPRIMENTO_DO_BORDO[k] == "a" else laje.b
        rb = rc.ReacaoBordo(bordo=k, vinculo=bordo.vinculo, comprimento=comp,
                            fracao=0.0, fonte="faixa" if k in dados
                            else "paralelo ao vão")
        if k in dados:
            v_g, v_q, v_d = dados[k]
            rb.v_g, rb.v_q, rb.v_d = v_g, v_q, v_d
            rb.v_k = v_g + v_q
            r.carga_total += rb.v_k * comp
            r.carga_total_d += v_d * comp
        r.bordos.append(rb)
    for rb in r.bordos:
        if r.carga_total > 0.0:
            rb.fracao = rb.v_k * rb.comprimento / r.carga_total
            rb.area = rb.fracao * laje.area
    return r


def _parcelas(v_d: float, g: float, q: float, cfg) -> tuple:
    """Separa uma reação de cálculo em ``(v_g, v_q, v_d)`` pela proporção
    das cargas características ``g`` e ``q`` (kN/m² quaisquer, só importa a
    razão)."""
    gg, gq = cfg.gamma_g * g, cfg.gamma_q * q
    soma = gg + gq
    if soma <= 0.0:
        return 0.0, 0.0, v_d
    return (v_d * gg / soma / cfg.gamma_g, v_d * gq / soma / cfg.gamma_q,
            v_d)


# ---------------------------------------------------------------------------
# Faixas treliçadas e nervuradas unidirecionais
# ---------------------------------------------------------------------------

def _agrupar_faixas(geos: list[_GeoUni]) -> list[list[_GeoUni]]:
    """Encadeia as lajes de mesmo perfil e direção que formam uma faixa
    contínua: mesmo eixo, mesma posição e largura transversais, e a ponta de
    uma encostando (a menos da viga) no começo da seguinte."""
    ordem = sorted(geos, key=lambda g: (g.eixo, round(g.cruz0, 1), g.ini))
    usados: set[str] = set()
    grupos: list[list[_GeoUni]] = []
    for g in ordem:
        if g.laje.nome in usados:
            continue
        cadeia = [g]
        usados.add(g.laje.nome)
        while True:
            ult = cadeia[-1]
            prox = None
            for c in ordem:
                if c.laje.nome in usados or c.eixo != ult.eixo:
                    continue
                if abs(c.cruz0 - ult.cruz0) > TOLERANCIA_ALINHAMENTO or \
                        abs(c.cruz1 - ult.cruz1) > TOLERANCIA_ALINHAMENTO:
                    continue
                if -0.05 <= c.ini - ult.fim <= FOLGA_VIGA:
                    prox = c
                    break
            if prox is None:
                break
            cadeia.append(prox)
            usados.add(prox.laje.nome)
        grupos.append(cadeia)
    return grupos


def _derivar_faixa(cadeia: list[_GeoUni], perfil, nome: str):
    """A faixa de vários vãos (``LajeTrelicada``) que a cadeia de lajes
    forma, a partir do perfil."""
    n = len(cadeia)
    lt = copy.deepcopy(perfil)
    lt.nome = nome
    # larguras de apoio: nas pontas, a do bordo; nas juntas, a maior das duas
    # (a mesma viga vista dos dois lados)
    ts = [cadeia[0].t_ini]
    for i in range(n - 1):
        ts.append(max(cadeia[i].t_fim, cadeia[i + 1].t_ini))
    ts.append(cadeia[-1].t_fim)
    vaos, apoios = [], []
    for i, g in enumerate(cadeia):
        gx, q = cargas_da_laje(g.laje)
        tv = perfil.vaos[min(i, len(perfil.vaos) - 1)]
        vaos.append(VaoTrelicado(
            L=g.l0 * 100.0 + (ts[i] + ts[i + 1]) / 2.0, g=gx, q=q,
            carga_linear=0.0, n_adicional=tv.n_adicional,
            phi_adicional=tv.phi_adicional, aco_adicional=tv.aco_adicional))
    for j in range(n + 1):
        ta = perfil.apoios[min(j, len(perfil.apoios) - 1)]
        apoios.append(ApoioTrelicado(t=ts[j], macico=ta.macico,
                                     n_negativa=ta.n_negativa,
                                     phi_negativa=ta.phi_negativa))
    lt.vaos, lt.apoios = vaos, apoios
    lt.balanco_esq = lt.balanco_dir = 0.0
    lt.parapeito_esq = lt.parapeito_dir = 0.0
    lt.largura_laje = cadeia[0].largura
    return lt


def _calcular_faixa(pav: Pavimento, cadeia: list[_GeoUni], tipo: str,
                    perfil) -> ResultadoEspecial:
    cfg = pav.config
    nomes = [g.laje.nome for g in cadeia]
    nome = "+".join(nomes)
    re = ResultadoEspecial(tipo=tipo, nome=nome, lajes=nomes,
                           perfil=perfil.nome)
    lt = _derivar_faixa(cadeia, perfil, nome)
    re.modelo = lt
    try:
        r = dimensionar_trelicada(lt, pav.concreto, pav.ambiente, cfg)
    except ValueError as e:
        re.erro = str(e)
        re.avisos.append(_aviso(f"{nome}: {e} -- não pôde ser calculada.",
                                nome, erro=True))
        return re
    re.resultado = r
    re.avisos.extend(_avisos_do_motor(r, nome))
    q = r.quantitativo
    re.area = sum(g.l0 * g.largura for g in cadeia)
    re.aco_kg = q.get("aco_kg", 0.0)
    re.concreto_m3 = q.get("volume_concreto", 0.0)
    if len(cadeia) > 1:
        re.avisos.append(_aviso(
            f"{nome}: {len(cadeia)} lajes de mesmo perfil, alinhadas e da "
            f"mesma largura formam uma faixa contínua de {len(cadeia)} "
            f"vãos (três momentos, alternância de sobrecarga); os negativos "
            f"sobre as vigas comuns saem da faixa.", nome))

    # -- reações nas vigas: R_j por nervura, dividida entre as duas lajes ---
    inter_m = lt.intereixo / 100.0
    wd = r.cargas["w_d"]
    for i, g in enumerate(cadeia):
        peso_i = wd[i] * lt.vaos[i].L
        if i == 0:
            f_ini = 1.0
        else:
            peso_ant = wd[i - 1] * lt.vaos[i - 1].L
            f_ini = peso_i / (peso_ant + peso_i) if peso_ant + peso_i else .5
        if i == len(cadeia) - 1:
            f_fim = 1.0
        else:
            peso_prox = wd[i + 1] * lt.vaos[i + 1].L
            f_fim = peso_i / (peso_i + peso_prox) if peso_i + peso_prox \
                else .5
        gx, qv = cargas_da_laje(g.laje)
        v_i = r.reacoes[i] * f_ini / inter_m
        v_f = r.reacoes[i + 1] * f_fim / inter_m
        gk = r.geo["pp"] / inter_m + gx       # kN/m² (pp é por nervura)
        re.reacoes[g.laje.nome] = _reacoes_uni(
            g.laje, g.b_ini, g.b_fim,
            _parcelas(v_i, gk, qv, cfg), _parcelas(v_f, gk, qv, cfg))
    return re


# ---------------------------------------------------------------------------
# Painéis alveolares
# ---------------------------------------------------------------------------

def _calcular_alveolar(pav: Pavimento, g: _GeoUni, perfil
                       ) -> ResultadoEspecial:
    cfg = pav.config
    laje = g.laje
    re = ResultadoEspecial(tipo="alveolar", nome=laje.nome,
                           lajes=[laje.nome], perfil=perfil.nome)
    gx, q = cargas_da_laje(laje)
    la = copy.deepcopy(perfil)
    la.nome = laje.nome
    L = g.l0 + (g.t_ini + g.t_fim) / 200.0
    la.vao = L
    la.g2 = gx
    la.q = q
    re.modelo = la
    try:
        r = resolver_alveolar(la, cfg.gamma_g, cfg.gamma_q)
    except ValueError as e:
        re.erro = str(e)
        re.avisos.append(_aviso(f"{laje.nome}: {e} -- não pôde ser "
                                f"calculada.", laje.nome, erro=True))
        return re
    re.resultado = r
    re.avisos.extend(_avisos_do_motor(r, laje.nome))
    b = r.laje.b
    n = max(1, math.ceil(g.largura / b - 1e-9))
    re.n_paineis = n
    qt = r.quantitativo
    re.area = g.l0 * g.largura
    re.aco_kg = qt["massa_aco"] * n
    re.premoldado_m3 = qt["volume_painel"] * n
    re.concreto_m3 = qt["volume_capa"] * n
    folga = n * b - g.largura
    re.avisos.append(_aviso(
        f"{laje.nome}: {n} painéis de {b * 100:.0f} cm cobrem a largura de "
        f"{g.largura:.2f} m"
        + (f"; sobram {folga * 100:.0f} cm, que o fabricante resolve com "
           f"corte longitudinal de um painel ou com faixa moldada."
           if folga > 0.02 else ".") +
        " Cada painel é verificado isolado, biapoiado; o capeamento sobre "
        "os apoios intermediários, quando houver, não entra.", laje.nome))
    cg = r.cargas
    cp = cg["g0"] + cg["g1c"] + cg["g2"]
    v_g = cp * L / 2.0 / cg["b"]
    v_q = cg["q"] * L / 2.0 / cg["b"]
    v_d = cfg.gamma_g * v_g + cfg.gamma_q * v_q
    re.reacoes[laje.nome] = _reacoes_uni(laje, g.b_ini, g.b_fim,
                                         (v_g, v_q, v_d), (v_g, v_q, v_d))
    return re


# ---------------------------------------------------------------------------
# Nervurada bidirecional
# ---------------------------------------------------------------------------

def _calcular_nervurada_bi(pav: Pavimento, laje: Laje, perfil
                           ) -> ResultadoEspecial:
    cfg = pav.config
    re = ResultadoEspecial(tipo="nervurada_bi", nome=laje.nome,
                           lajes=[laje.nome], perfil=perfil.nome)
    gx, q = cargas_da_laje(laje)
    lb = copy.deepcopy(perfil)
    lb.nome = laje.nome
    t = [b.t for b in laje.bordos]
    # x é o maior vão (bordos 1 e 3 da planta), y o menor (bordos 2 e 4)
    lb.lx = laje.b + (t[0] + t[2]) / 200.0
    lb.ly = laje.a + (t[1] + t[3]) / 200.0
    lb.bordos = [laje.bordos[0].vinculo, laje.bordos[2].vinculo,
                 laje.bordos[1].vinculo, laje.bordos[3].vinculo]
    lb.t_apoio = max(t)
    lb.g2 = gx
    lb.q = q
    re.modelo = lb
    try:
        r = dimensionar_nervurada(lb, pav.concreto, pav.ambiente, cfg)
    except ValueError as e:
        re.erro = str(e)
        re.avisos.append(_aviso(f"{laje.nome}: {e} -- não pôde ser "
                                f"calculada.", laje.nome, erro=True))
        return re
    re.resultado = r
    re.avisos.extend(_avisos_do_motor(r, laje.nome))
    qt = r.quantitativo
    re.area = laje.a * laje.b
    re.aco_kg = qt["aco_kg"]
    re.concreto_m3 = qt["volume_concreto"]
    # as reações saem pela partição geométrica da maciça, com a carga que a
    # grelha de fato carrega (peso próprio da seção nervurada + g + q)
    clone = copy.deepcopy(laje)
    clone.tipo, clone.perfil = "macica", ""
    clone.h = lb.h
    clone.enchimento = clone.revestimento = clone.reboco = 0.0
    clone.paredes = []
    clone.permanente_extra = r.cargas["g"] - clone.h / 100.0 * 25.0
    re.reacoes[laje.nome] = rc.calcular(clone, None, cfg)
    return re


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

def calcular_especiais(pav: Pavimento) -> list[ResultadoEspecial]:
    """Calcula todas as lajes especiais da planta.

    Devolve um :class:`ResultadoEspecial` por faixa (uma ou mais lajes),
    painel ou laje nervurada bidirecional, na ordem em que as lajes
    aparecem na planta.
    """
    especiais = pav.lajes_especiais
    saida: list[ResultadoEspecial] = []
    sem_perfil: set[str] = set()
    uni: dict[tuple[str, str], list[_GeoUni]] = {}

    for laje in especiais:
        perfil = pav.perfil_da(laje)
        if perfil is None:
            sem_perfil.add(laje.nome)
            re = ResultadoEspecial(tipo=laje.tipo, nome=laje.nome,
                                   lajes=[laje.nome], perfil=laje.perfil)
            re.erro = f"o perfil {laje.perfil!r} não existe"
            re.avisos.append(_aviso(
                f"{laje.nome}: o perfil {laje.perfil!r} da laje "
                f"{laje.rotulo_tipo.lower()} não existe -- cadastre-o na aba "
                f"correspondente.", laje.nome, erro=True))
            saida.append(re)
            continue
        if laje.tipo in TIPOS_UNIDIRECIONAIS:
            g = _geo_uni(laje)
            if g.livre:
                re = ResultadoEspecial(tipo=laje.tipo, nome=laje.nome,
                                       lajes=[laje.nome], perfil=perfil.nome)
                re.erro = "ponta de vão livre"
                re.avisos.append(_aviso(
                    f"{laje.nome}: uma ponta do vão {laje.direcao} está "
                    f"livre -- a laje {laje.rotulo_tipo.lower()} precisa de "
                    f"apoio nos dois bordos das pontas e não pôde ser "
                    f"calculada.", laje.nome, erro=True))
                saida.append(re)
                continue
            uni.setdefault((laje.tipo, perfil.nome), []).append(g)
        else:
            saida.append(_calcular_nervurada_bi(pav, laje, perfil))

    for (tipo, nome_perfil), geos in uni.items():
        perfil = pav.perfil_da(geos[0].laje)
        if tipo == "alveolar":
            for g in geos:
                saida.append(_calcular_alveolar(pav, g, perfil))
        else:
            # as faixas se formam entre lajes de mesmo perfil -- e a direção
            # global é parte da chave: duas lajes na mesma direção local mas
            # giradas na planta correm em eixos diferentes
            for cadeia in _agrupar_faixas(geos):
                saida.append(_calcular_faixa(pav, cadeia, tipo, perfil))

    # -- observações de vinculação, uma por laje ----------------------------
    for re in saida:
        for nome in re.lajes:
            laje = pav.laje(nome)
            if laje is None or re.resultado is None:
                continue
            re.avisos.extend(_avisos_de_vinculacao(pav, laje, re))

    ordem = {x.nome: i for i, x in enumerate(pav.lajes)}
    saida.sort(key=lambda r: ordem.get(r.lajes[0], 0))
    return saida


def _avisos_de_vinculacao(pav: Pavimento, laje: Laje,
                          re: ResultadoEspecial) -> list[av.Aviso]:
    obs: list[av.Aviso] = []
    if laje.tipo in TIPOS_UNIDIRECIONAIS:
        fim = (2, 4) if laje.direcao == "a" else (1, 3)
        for k in fim:
            if laje.bordos[k - 1].vinculo == "engastado":
                obs.append(_aviso(
                    f"{laje.nome}, bordo {k}: engastado, mas a laje "
                    f"{laje.rotulo_tipo.lower()} o trata como apoio simples "
                    f"-- o motor da faixa não modela o momento de "
                    f"engastamento da ponta (a positiva sai a favor da "
                    f"segurança; a negativa de ponta é construtiva).",
                    laje.nome))
    # laje encostada que não faz parte da faixa: o bordo fica apoiado
    for outra in pav.lajes:
        if outra.nome == laje.nome or outra.nome in re.lajes:
            continue
        for c in _continuidades_geometricas(laje, outra, FOLGA_VIGA, 0.30):
            obs.append(_aviso(
                f"{laje.nome}, bordo {c.bordo_a}: divide a viga com "
                f"{outra.nome} ({ROTULO_TIPO[outra.tipo].lower()}); a "
                f"continuidade entre as duas não é suposta e o bordo segue "
                f"como lançado ({laje.bordos[c.bordo_a - 1].vinculo}) -- as "
                f"reações dos dois lados somam na viga.", laje.nome))
    return obs


def vizinhas_com_especial(pav: Pavimento
                          ) -> dict[tuple[str, int], tuple[str, int]]:
    """``(laje, bordo) -> (laje, bordo)`` do outro lado da viga, para os
    pares em que ao menos uma das lajes é especial. É o que o consolidador
    de apoios usa para somar as reações dos dois lados da mesma viga -- os
    pares de maciças continuam vindo de ``Pavimento.continuidades``."""
    mapa: dict[tuple[str, int], tuple[str, int]] = {}
    lajes = pav.lajes
    for i, la in enumerate(lajes):
        for lb in lajes[i + 1:]:
            if not (la.especial or lb.especial):
                continue
            for c in _continuidades_geometricas(la, lb, FOLGA_VIGA, 0.30):
                mapa[(c.laje_a, c.bordo_a)] = (c.laje_b, c.bordo_b)
                mapa[(c.laje_b, c.bordo_b)] = (c.laje_a, c.bordo_a)
    return mapa


def modelos_efetivos(pav: Pavimento, especiais: list[ResultadoEspecial],
                     tipo: str) -> list:
    """Modelos do ``tipo`` que a memória e o quantitativo devem tratar:
    os extras que nenhuma laje usa mais os derivados da planta."""
    em_uso = {nome for (t, nome) in pav.perfis_em_uso() if t == tipo}
    extras = [x for x in getattr(pav, LISTA_DO_TIPO[tipo])
              if x.nome not in em_uso]
    derivados = [e.modelo for e in especiais
                 if e.tipo == tipo and e.modelo is not None]
    return extras + derivados
