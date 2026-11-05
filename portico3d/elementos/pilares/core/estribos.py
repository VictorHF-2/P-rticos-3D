# -*- coding: utf-8 -*-
"""
estribos.py
Armadura transversal do pilar: bitola, espaçamento, estribos suplementares
contra a flambagem das barras longitudinais e o comprimento das peças.

Base normativa: item 18.4.3 (armaduras transversais de pilares) e item 18.2.4
(proteção contra flambagem das barras).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import avisos as av
from . import cisalhamento as cis
from .arranjo import Arranjo
from .materiais import Aco, BITOLAS_ESTRIBOS, massa_linear
from .modelo import Pilar, SecaoPilar
from .formato import num

#: Espaçamento longitudinal máximo absoluto entre estribos, cm (18.4.3).
ESPACAMENTO_MAXIMO = 20.0

#: Espaçamento longitudinal mínimo executável, cm. O item 18.3.3.2 não dá
#: número: exige que caiba o vibrador. Cinco centímetros é o mínimo
#: praticável, e serve de piso à redução por cortante -- abaixo disso o
#: problema não é de detalhe, é de seção insuficiente.
ESPACAMENTO_MINIMO = 5.0

#: Bitola mínima absoluta do estribo, mm (18.4.3).
BITOLA_MINIMA = 5.0

#: Múltiplos da bitola longitudinal que limitam o espaçamento, por aço.
MULTIPLO_ESPACAMENTO = {"CA-25": 24.0, "CA-50": 12.0, "CA-60": 12.0}

#: Alcance da proteção do estribo poligonal, em múltiplos de phi_t (18.2.4).
ALCANCE_PROTECAO = 20.0

#: Número máximo de barras protegidas em cada trecho de 20 phi_t, além da
#: barra de canto (18.2.4).
BARRAS_PROTEGIDAS_POR_CANTO = 2


@dataclass
class Estribos:
    """Armadura transversal resolvida para o lance."""

    phi: float = 0.0             # mm
    s: float = 0.0               # cm, espaçamento adotado
    s_maximo: float = 0.0        # cm, o limite normativo que governou
    motivo_s: str = ""
    n_suplementares: int = 0     # por nível de estribo
    #: grampos que travam as barras das faces horizontais (nx) -- e que,
    #: por isso, cruzam a seção na direção **y**
    suplementares_x: int = 0
    suplementares_y: int = 0
    alcance: float = 0.0         # cm, 20 phi_t
    comprimento: float = 0.0     # cm, de um estribo fechado
    comprimento_suplementar: float = 0.0
    #: Estribo do contorno interno (seção vazada com armadura junto ao furo),
    #: cm; 0 quando não há camada interna.
    comprimento_interno: float = 0.0
    #: Grampos que amarram a camada interna à externa, por nível.
    grampos_internos: int = 0
    niveis: int = 0              # estribos ao longo do lance
    massa: float = 0.0           # kg
    avisos: list[str] = field(default_factory=list)

    def descricao(self) -> str:
        base = f"ø{num(self.phi)} c/{num(self.s)} cm"
        if self.comprimento_interno > 0:
            base += " + estribo interno"
        grampos = self.n_suplementares + self.grampos_internos
        if grampos:
            base += f" + {grampos} grampo(s) por nível"
        return base


# ---------------------------------------------------------------------------
# Bitola e espaçamento
# ---------------------------------------------------------------------------

def bitola_minima(phi_longitudinal: float) -> float:
    """Bitola mínima do estribo, mm (item 18.4.3): 5 mm e ``phi_l/4``."""
    return max(BITOLA_MINIMA, phi_longitudinal / 4.0)


def bitola_comercial(phi_longitudinal: float) -> float:
    """A bitola de estribo que o programa adota quando o projetista não impõe
    nenhuma: a menor comercial (NBR 7480) que atende ao mínimo do item
    18.4.3. Com barras de 25 mm o mínimo é 6,25 mm -- e o estribo é o ø6,3,
    não um "ø6,25" que não existe para comprar."""
    minimo = bitola_minima(phi_longitudinal)
    return next((b for b in BITOLAS_ESTRIBOS if b >= minimo - 1e-9),
                BITOLAS_ESTRIBOS[-1])


def espacamento_maximo(secao: SecaoPilar, phi_longitudinal: float,
                       aco: Aco) -> tuple[float, str]:
    """Espaçamento longitudinal máximo, cm, e o limite que governou.

    O item 18.4.3 dá o menor entre 200 mm, a menor dimensão da seção (a
    espessura da parede nas seções L, T, U e vazadas) e
    ``24 phi`` no CA-25 ou ``12 phi`` no CA-50 -- onde ``phi`` é a bitola da
    barra **longitudinal**, porque é a flambagem dela que o estribo impede.
    """
    mult = MULTIPLO_ESPACAMENTO.get(aco.categoria, 12.0)
    candidatos = [
        (ESPACAMENTO_MAXIMO, "20 cm (18.4.3)"),
        (secao.menor_dimensao, "menor dimensão da seção"),
        (mult * phi_longitudinal / 10.0,
         f"{num(mult)} ø da barra longitudinal"),
    ]
    valor, motivo = min(candidatos, key=lambda t: t[0])
    return valor, motivo


def espacamento_bitola_reduzida(phi_t: float, phi_l: float,
                                fyk_t: float) -> float:
    """Espaçamento máximo quando se adota ``phi_t < phi_l/4``, cm (18.4.3).

    A norma admite a bitola reduzida desde que o aço seja o mesmo e
    ``s <= 90000 phi_t²/(phi_l fyk)``, com as bitolas em mm e ``fyk`` em MPa;
    o resultado sai em mm e é convertido para cm.
    """
    if phi_l <= 0 or fyk_t <= 0:
        return 0.0
    return 90000.0 * phi_t * phi_t / (phi_l * fyk_t) / 10.0


# ---------------------------------------------------------------------------
# Proteção contra flambagem das barras (18.2.4)
# ---------------------------------------------------------------------------

def suplementares_na_face(n_barras_face: int, passo: float, phi_t: float
                          ) -> int:
    """Barras da face que ficam **sem** proteção do estribo poligonal.

    O item 18.2.4 protege a barra de canto e as abrangidas pelo estribo
    "situadas no máximo à distância de 20 phi_t do canto, se nesse trecho de
    comprimento 20 phi_t não houver mais de duas barras, não contando a de
    canto". Ou seja: de cada canto, alcançam-se as barras dentro de 20 phi_t,
    até o máximo de duas. O que sobra no meio da face precisa de estribo
    suplementar.
    """
    interiores = max(n_barras_face - 2, 0)
    if interiores == 0 or passo <= 0:
        return 0
    alcance = ALCANCE_PROTECAO * phi_t / 10.0        # cm
    dentro = int(alcance / passo + 1e-9)
    protegidas_por_canto = min(BARRAS_PROTEGIDAS_POR_CANTO, dentro)
    return max(interiores - 2 * protegidas_por_canto, 0)


def grampos_retangular(secao: SecaoPilar, arr: Arranjo, phi_t: float
                       ) -> list:
    """Segmentos dos grampos na seção retangular, cm a partir do CG.

    Cada grampo liga uma barra **desprotegida** de uma face à sua espelhada
    na face oposta -- as do meio da face, além do alcance de 20 øt de cada
    canto (18.2.4). Antes o desenho pegava as primeiras barras interiores,
    junto ao canto, que já estão protegidas pelo estribo."""
    if secao.tipo != "retangular" or not (arr.nx and arr.ny):
        return []
    lx = secao.hx / 2.0 - arr.recuo
    ly = secao.hy / 2.0 - arr.recuo
    alcance = ALCANCE_PROTECAO * phi_t / 10.0
    segmentos = []
    for n_face, comprimento, vertical in ((arr.nx, 2.0 * lx, True),
                                          (arr.ny, 2.0 * ly, False)):
        interiores = n_face - 2
        if interiores <= 0:
            continue
        passo = comprimento / (n_face - 1)
        p = min(BARRAS_PROTEGIDAS_POR_CANTO, int(alcance / passo + 1e-9))
        for k in range(1 + p, n_face - 1 - p):
            c = -comprimento / 2.0 + k * passo
            segmentos.append(((c, -ly), (c, ly)) if vertical
                             else ((-lx, c), (lx, c)))
    return segmentos


def suplementares_no_contorno(arr: Arranjo, phi_t: float) -> int:
    """Quantas barras do contorno L, T, U ou vazado ficam sem proteção do
    estribo (item 18.2.4). Ver :func:`desprotegidas_no_contorno`."""
    return len(desprotegidas_no_contorno(arr, phi_t))


def desprotegidas_no_contorno(arr: Arranjo, phi_t: float) -> set[int]:
    """Barras sem proteção do estribo num contorno poligonal L, T ou U.

    Mesma regra do item 18.2.4, aplicada ao contorno real em vez de a uma
    face reta: a partir de **cada vértice** caminha-se ao longo do perímetro
    da armadura enquanto a distância acumulada não passar de 20 phi_t,
    protegendo no máximo duas barras de cada lado. O que sobra no meio dos
    lados longos precisa de estribo suplementar.

    Percorrer o contorno, e não a corda, é o que faz diferença no L: o
    vértice reentrante tem barras dos dois lados dele, e medir em linha reta
    daria por protegida uma barra que o estribo não abraça.
    """
    # só a camada externa: os passos do contorno não incluem a interna
    n = len(arr.passos_contorno)
    if n == 0 or not arr.indices_vertices:
        return set()
    alcance = ALCANCE_PROTECAO * phi_t / 10.0
    protegidas = set(arr.indices_vertices)
    for v in arr.indices_vertices:
        for sentido in (1, -1):
            percorrido = 0.0
            contadas = 0
            i = v
            while contadas < BARRAS_PROTEGIDAS_POR_CANTO:
                passo = (arr.passos_contorno[i] if sentido > 0
                         else arr.passos_contorno[(i - 1) % n])
                percorrido += passo
                if percorrido > alcance + 1e-9:
                    break
                i = (i + sentido) % n
                if i in arr.indices_vertices:
                    break
                protegidas.add(i)
                contadas += 1
    return set(range(n)) - protegidas


# ---------------------------------------------------------------------------
# Comprimentos
# ---------------------------------------------------------------------------

def comprimento_estribo(secao: SecaoPilar, cobrimento: float, phi_t: float,
                        aco_estribo: Aco) -> float:
    """Comprimento desenvolvido de um estribo fechado, cm.

    Perímetro da linha média do estribo mais os dois ganchos de extremidade.
    O gancho a 135° do estribo tem ponta reta de 5 ``phi_t``, não menor que
    5 cm (item 9.4.6.1), e o desenvolvimento da dobra sai do pino da Tabela
    9.2.
    """
    recuo = cobrimento + phi_t / 20.0
    if secao.tipo in ("circular", "circular vazada"):
        perimetro = math.pi * (secao.diametro - 2.0 * recuo)
    else:
        from . import geometria as geo
        linha = geo.deslocar_para_dentro(secao.contornos()[0], recuo)
        perimetro = geo.perimetro_poligono(linha)
    r = aco_estribo.pino_dobramento_estribo(phi_t) / 2.0 + phi_t / 20.0
    ponta = max(5.0 * phi_t / 10.0, 5.0)
    gancho = 3.0 * math.pi / 4.0 * r + ponta          # dobra de 135° + ponta
    return perimetro + 2.0 * gancho


def comprimento_estribo_interno(secao: SecaoPilar, cobrimento: float,
                                phi_t: float, aco_estribo: Aco) -> float:
    """Estribo fechado do contorno do furo, cm: a linha média a
    ``cobrimento + phi_t/2`` da face do furo, para dentro da parede, mais os
    dois ganchos."""
    from .arranjo import linha_do_furo
    from . import geometria as geo
    tipo, linha = linha_do_furo(secao, cobrimento + phi_t / 20.0)
    perimetro = (math.pi * linha if tipo == "circulo"
                 else geo.perimetro_poligono(linha))
    r = aco_estribo.pino_dobramento_estribo(phi_t) / 2.0 + phi_t / 20.0
    ponta = max(5.0 * phi_t / 10.0, 5.0)
    return perimetro + 2.0 * (3.0 * math.pi / 4.0 * r + ponta)


def comprimento_suplementar(secao: SecaoPilar, cobrimento: float,
                            phi_t: float, direcao: str,
                            aco_estribo: Aco) -> float:
    """Comprimento de um grampo suplementar reto, cm.

    O item 18.2.4 exige que o estribo suplementar reto "atravesse a seção do
    elemento estrutural e os seus ganchos envolvam a barra longitudinal" --
    daí ele medir a dimensão inteira da seção descontados os cobrimentos, mais
    dois ganchos. Na seção retangular é a dimensão da seção; nas L, T, U e
    vazadas, o grampo atravessa só a **parede** em que está a barra que ele
    trava -- a espessura dela, e não a caixa envolvente (com paredes de
    espessuras diferentes, a maior, do lado seguro).
    """
    recuo = cobrimento + phi_t / 10.0
    if secao.tipo in ("L", "T", "U", "retangular vazada", "circular vazada"):
        espessura = (max(secao.e1, secao.e2) if secao.tipo != "circular vazada"
                     else secao.menor_dimensao)
        largura = espessura - 2.0 * recuo
    else:
        largura = (secao.hx if direcao == "x" else secao.hy) - 2.0 * recuo
    r = aco_estribo.pino_dobramento_estribo(phi_t) / 2.0 + phi_t / 20.0
    ponta = max(5.0 * phi_t / 10.0, 5.0)
    gancho = 3.0 * math.pi / 4.0 * r + ponta
    return max(largura, 0.0) + 2.0 * gancho


# ---------------------------------------------------------------------------
# Resolução completa
# ---------------------------------------------------------------------------

def dimensionar(pilar: Pilar, arr: Arranjo, secao_discreta=None,
                momentos: dict | None = None,
                ln_fora: bool = False) -> Estribos:
    """Resolve a armadura transversal do lance.

    ``secao_discreta``, quando dado, permite fechar o espaçamento pela
    força cortante (item 17.4) além dos critérios construtivos do item
    18.4.3: é dela que saem a altura útil pela posição real das barras e
    a largura resistente da seção.
    """
    avisos: list[str] = []
    secao = pilar.secao
    aco_t = pilar.aco_estribo
    phi_l = arr.phi

    phi_min = bitola_minima(phi_l)
    phi_t = pilar.armadura.phi_estribo
    if phi_t <= 0:
        phi_t = bitola_comercial(phi_l)
        engrossado = _engrossar_para_dispensar_grampos(secao, arr, phi_t)
        economico = (_engrossar_por_economia(pilar, arr, phi_t)
                     if engrossado <= phi_t else phi_t)
        if economico > phi_t:
            n0 = len(desprotegidas_no_contorno(arr, phi_t))
            n1 = len(desprotegidas_no_contorno(arr, economico))
            avisos.append(av.construtivo(
                f"Estribo engrossado de ø{num(phi_t)} para ø{num(economico)} mm: "
                f"o alcance de 20 øt passa de {num(2.0 * phi_t, 1)} para "
                f"{num(2.0 * economico, 1)} cm e os grampos do contorno caem de "
                f"{n0} para {n1} por nível (item 18.2.4) -- a bitola que dá a "
                f"menor massa de aço transversal por nível, estribo e grampos "
                f"somados."))
            phi_t = economico
        if engrossado > phi_t:
            avisos.append(av.construtivo(
                f"Estribo engrossado de ø{num(phi_t)} para ø{num(engrossado)} mm "
                f"para dispensar os grampos suplementares do contorno: o alcance de "
                f"20 øt passa de {num(2.0 * phi_t, 1)} para "
                f"{num(2.0 * engrossado, 1)} cm e cobre as barras das faces "
                f"(item 18.2.4). Uma bitola a mais no estribo custa menos que "
                f"um grampo por nível ao longo do lance inteiro."))
            phi_t = engrossado
    elif phi_t < phi_min - 1e-9:
        s_reduzida = espacamento_bitola_reduzida(phi_t, phi_l, aco_t.fyk)
        if aco_t.categoria != pilar.aco.categoria:
            avisos.append(av.erro(
                f"Estribo ø{num(phi_t)} mm abaixo de øl/4 = {num(phi_min, 2)} mm. O "
                f"item 18.4.3 só admite a bitola reduzida quando as armaduras "
                f"são do **mesmo tipo de aço**, e aqui a longitudinal é "
                f"{pilar.aco.categoria} e o estribo {aco_t.categoria}."))
        else:
            avisos.append(av.construtivo(
                f"Estribo ø{num(phi_t)} mm abaixo de øl/4 = {num(phi_min, 2)} mm, "
                f"admitido pelo item 18.4.3 com o espaçamento adicionalmente "
                f"limitado a 90000 øt²/(øl fyk) = {num(s_reduzida, 1)} cm."))

    s_max, motivo = espacamento_maximo(secao, phi_l, pilar.aco)
    if phi_t < phi_min - 1e-9 and aco_t.categoria == pilar.aco.categoria:
        s_extra = espacamento_bitola_reduzida(phi_t, phi_l, aco_t.fyk)
        if s_extra < s_max:
            s_max, motivo = s_extra, "bitola de estribo reduzida (18.4.3)"

    # A cortante, quando existe, tem voz no espaçamento: o item 18.3.3.2
    # impõe um teto próprio e o 17.4.2.2 exige que ``Vc + Vsw`` alcance
    # ``VSd``. O menor dos limites manda -- e é aqui que ele entra, antes de
    # o espaçamento ser arredondado, para o estribo já sair dimensionado e
    # não só reprovado adiante.
    s_cortante, motivo_cortante = _limite_por_cortante(
        pilar, phi_t, secao_discreta, momentos, ln_fora)
    if s_cortante < s_max:
        s_max, motivo = s_cortante, motivo_cortante
    if s_max < ESPACAMENTO_MINIMO:
        avisos.append(av.erro(
            f"A força cortante exigiria estribos a cada {num(s_max, 1)} cm "
            f"({motivo}), abaixo do mínimo executável de "
            f"{num(ESPACAMENTO_MINIMO)} cm -- não cabe vibrador. A seção, a "
            f"classe do concreto ou a bitola do estribo têm de mudar."))
        s_max, motivo = ESPACAMENTO_MINIMO, "mínimo executável"

    s = pilar.armadura.s_estribo
    passo = pilar.config.passo_estribo
    if s <= 0:
        s = math.floor(s_max / passo) * passo
        s = max(s, passo)
    elif s > s_max + 1e-9:
        avisos.append(av.erro(
            f"Espaçamento de estribos de {num(s)} cm acima do máximo de "
            f"{num(s_max, 1)} cm, governado por {motivo}."))
    if s_cortante < float("inf") and s_cortante <= s_max + 1e-9:
        avisos.append(av.construtivo(
            f"Espaçamento fechado em {num(s)} cm pela força cortante "
            f"({motivo_cortante}), e não pelo critério construtivo do item "
            f"18.4.3."))

    alcance = ALCANCE_PROTECAO * phi_t / 10.0
    if secao.tipo in ("circular", "circular vazada"):
        sup_x = sup_y = 0
        avisos.append(av.construtivo(
            "Seção circular com estribo curvilíneo de concavidade voltada "
            "para o interior do concreto: o item 18.2.4 dispensa estribos "
            "suplementares."))
    elif secao.tipo == "retangular" and arr.nx and arr.ny:
        lx, ly = (secao.hx - 2.0 * arr.recuo, secao.hy - 2.0 * arr.recuo)
        passo_x = lx / (arr.nx - 1) if arr.nx > 1 else lx
        passo_y = ly / (arr.ny - 1) if arr.ny > 1 else ly
        sup_x = suplementares_na_face(arr.nx, passo_x, phi_t)
        sup_y = suplementares_na_face(arr.ny, passo_y, phi_t)
        if sup_x or sup_y:
            avisos.append(av.construtivo(
                f"Entraram {sup_x + sup_y} grampo(s) suplementar(es) por nível "
                f"de estribo: o alcance de 20 øt = {num(alcance, 1)} cm a partir "
                f"do canto, com o máximo de duas barras por trecho, não cobre "
                f"todas as barras das faces (item 18.2.4)."))
    else:
        sup_x = suplementares_no_contorno(arr, phi_t)
        if sup_x and secao.tipo in ("L", "T", "U", "retangular vazada"):
            # barras frente a frente dividem o mesmo grampo (nas seções em
            # que o grampo é posicionado; na retangular em lista de barras a
            # contagem continua a do 18.2.4)
            grampos = grampos_do_contorno(pilar, arr, phi_t)
            sup_x = max(0, len(grampos) - arr.n_internas)
        sup_y = 0
        if sup_x:
            avisos.append(av.construtivo(
                f"Entraram {sup_x} grampo(s) suplementar(es) por nível: no "
                f"contorno da seção {secao.tipo} há barras a mais de "
                f"20 øt = {num(alcance, 1)} cm do vértice mais próximo, medidos "
                f"ao longo do perímetro da armadura (item 18.2.4). O "
                f"programa **conta** esses grampos e os inclui no "
                f"quantitativo, mas não define a posição de cada um: numa "
                f"seção composta a peça pode ser um grampo reto atravessando "
                f"a alma ou um estribo interno fechado, e a escolha é do "
                f"detalhamento. O desenho traz apenas o estribo externo."))

    altura = pilar.lance.altura
    niveis = int(altura / s) + 1 if s > 0 else 0
    cobrimento = arr.cobrimento or pilar.cobrimento(arr.phi, phi_t)
    c_estribo = comprimento_estribo(secao, cobrimento, phi_t, aco_t)
    c_sup_x = comprimento_suplementar(secao, cobrimento, phi_t, "x", aco_t)
    c_sup_y = comprimento_suplementar(secao, cobrimento, phi_t, "y", aco_t)
    # Camada interna da seção vazada: estribo fechado no contorno do furo e
    # um grampo por barra interna. O estribo do furo não trava a barra
    # contra a flambagem para o lado do furo -- ela empurra o estribo para
    # dentro do laço, que só resiste a pressão para fora --, e a proteção do
    # 18.2.4 sai do grampo que atravessa a parede até a camada externa.
    c_interno = 0.0
    grampos_int = 0
    if arr.n_internas > 0:
        c_interno = comprimento_estribo_interno(secao, cobrimento, phi_t,
                                                aco_t)
        grampos_int = arr.n_internas
        avisos.append(av.construtivo(
            f"Armadura junto ao furo ({arr.n_internas} barras): estribo "
            f"fechado no contorno interno e um grampo por barra interna, "
            f"atravessando a parede até a camada externa. O estribo do furo "
            f"não protege a barra contra a flambagem para o lado do furo "
            f"(item 18.2.4) -- quem protege é o grampo. Os dois entram no "
            f"quantitativo."))
    comprimento_total = niveis * (c_estribo + c_interno + sup_x * c_sup_y
                                  + sup_y * c_sup_x + grampos_int * c_sup_x)
    massa = massa_linear(phi_t) * comprimento_total / 100.0

    if s > secao.menor_dimensao + 1e-9:
        avisos.append(av.erro(
            f"Espaçamento de {num(s)} cm maior que a menor dimensão da seção "
            f"({num(secao.menor_dimensao)} cm), contra o item 18.4.3."))

    avisos.append(av.construtivo(
        "Os estribos são obrigatórios em toda a altura do lance, **inclusive "
        "na região de cruzamento com vigas e lajes** (item 18.4.3); o "
        "quantitativo acima já conta esse trecho."))

    return Estribos(phi=phi_t, s=s, s_maximo=s_max, motivo_s=motivo,
                    n_suplementares=sup_x + sup_y, suplementares_x=sup_x,
                    suplementares_y=sup_y, alcance=alcance,
                    comprimento=c_estribo,
                    comprimento_suplementar=max(c_sup_x, c_sup_y),
                    comprimento_interno=c_interno,
                    grampos_internos=grampos_int,
                    niveis=niveis, massa=massa, avisos=avisos)


def _limite_por_cortante(pilar: Pilar, phi_t: float, secao_discreta,
                         momentos: dict | None = None, ln_fora: bool = False
                         ) -> tuple[float, str]:
    """Espaçamento máximo imposto pela força cortante, cm, e o motivo.

    Devolve ``inf`` -- sem limite -- quando não há cortante informada, que é
    o caso do pilar de edifício corrente, ou quando falta a seção discreta
    para medir ``bw`` e ``d``. Dos dois limites possíveis fica o menor: o teto
    do item 18.3.3.2 e o espaçamento que faz ``Vc + Vsw`` alcançar ``VSd``
    (item 17.4.2.2-b).
    """
    if secao_discreta is None:
        return float("inf"), ""
    contornos = pilar.secao.contornos()
    Asw = cis.RAMOS * math.pi * (phi_t / 10.0) ** 2 / 4.0
    N_servico = cis.normal_de_servico(pilar)
    props = secao_discreta.propriedades
    limite, motivo = float("inf"), ""
    for direcao in ("x", "y"):
        Vd = abs(pilar.esforcos.Vd(direcao)) * pilar.fator_esforcos
        if Vd <= 1e-9:
            continue
        bw = cis.largura_minima(
            contornos, direcao,
            faixa=cis.faixa_das_barras(secao_discreta.barras, direcao))
        d = cis.altura_util(secao_discreta.barras, contornos, direcao)
        if bw <= 0.0 or d <= 0.0:
            continue
        vrd2 = cis.VRd2(pilar.concreto, bw, d)
        I = props.Ix if direcao == "x" else props.Iy
        W1 = cis.modulo_tracionado(contornos, I, direcao)
        M0 = (N_servico / props.area) * W1 if props.area > 0 else 0.0
        Msd = abs((momentos or {}).get(direcao, 0.0))
        if Msd <= 0.0:
            Msd = max((abs(pilar.momento_base(direcao)),
                       abs(pilar.esforcos.topo(direcao)))) * pilar.fator_esforcos
        if pilar.Nd > 0.0:
            fator = min(1.0 + M0 / Msd, 2.0) if Msd > 1e-9 else 2.0
        else:
            # flexo-tração: Vc0 com a linha neutra na seção, 0 fora dela
            fator = 0.0 if ln_fora else 1.0
        vc = cis.Vc0(pilar.concreto, bw, d) * fator
        s_nec = cis.espacamento_necessario(Vd, vc, Asw, d, pilar.aco_estribo)
        candidatos = []
        # O teto do item 18.3.3.2 vale para o estribo que **resiste** à
        # cortante. Enquanto a alínea c) do 17.4.1.1.2 dispensa a armadura de
        # cisalhamento -- VSd <= Vc e seção sem fissurar --, quem manda no
        # espaçamento continua sendo o critério construtivo de pilar.
        tracao = ((Msd / W1 if W1 > 0 else 0.0)
                  - pilar.Nd / props.area) * 10.0
        dispensado = (Vd <= vc + 1e-9
                      and tracao <= pilar.concreto.fctk_inf + 1e-9)
        if not dispensado:
            s_max_norma, texto = cis.espacamento_maximo(Vd, vrd2, d)
            candidatos.append((s_max_norma, f"item 18.3.3.2, {texto}, "
                                            f"direção {direcao}"))
            # sem a dispensa da alínea c), vale a taxa mínima do 17.4.1.1.1
            minimo = cis.asw_s_minimo(pilar.concreto, pilar.aco_estribo, bw)
            if minimo > 0:
                candidatos.append((Asw / minimo,
                                   f"item 17.4.1.1.1, taxa mínima ρsw, "
                                   f"direção {direcao}"))
        if s_nec < float("inf"):
            candidatos.append(
                (s_nec, f"item 17.4.2.2-b: Vc + Vsw >= VSd na direção "
                        f"{direcao}"))
        for valor, texto_motivo in candidatos:
            if valor < limite:
                limite, motivo = valor, texto_motivo
    return limite, motivo


def _cruzar(px: float, py: float, dx: float, dy: float, poligonos
            ) -> tuple[float, float] | None:
    """Primeiro ponto em que o raio ``p + t d`` (t > 0) corta os lados dos
    polígonos."""
    melhor = None
    for pol in poligonos:
        n = len(pol)
        for i in range(n):
            ax, ay = pol[i]
            bx, by = pol[(i + 1) % n]
            ex, ey = bx - ax, by - ay
            den = dx * ey - dy * ex
            if abs(den) < 1e-12:
                continue
            t = ((ax - px) * ey - (ay - py) * ex) / den
            u = ((ax - px) * dy - (ay - py) * dx) / den
            if t > 1e-6 and -1e-9 <= u <= 1.0 + 1e-9:
                if melhor is None or t < melhor:
                    melhor = t
    if melhor is None:
        return None
    return px + melhor * dx, py + melhor * dy


def _normal_do_lado(px: float, py: float, pol) -> tuple[float, float]:
    """Normal **para dentro** do lado de ``pol`` (anti-horário) mais próximo
    do ponto."""
    melhor, normal = float("inf"), (0.0, 0.0)
    n = len(pol)
    for i in range(n):
        ax, ay = pol[i]
        bx, by = pol[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        comp2 = ex * ex + ey * ey
        if comp2 <= 0:
            continue
        t = max(0.0, min(1.0, ((px - ax) * ex + (py - ay) * ey) / comp2))
        d = math.hypot(px - (ax + t * ex), py - (ay + t * ey))
        if d < melhor - 1e-9:
            comp = math.sqrt(comp2)
            melhor, normal = d, (-ey / comp, ex / comp)
    return normal


def posicoes_grampos(pilar: Pilar, arr: Arranjo, est) -> list:
    """Ver :func:`grampos_do_contorno` -- aqui com o ``est`` resolvido."""
    if est is None:
        return []
    return grampos_do_contorno(pilar, arr, est.phi)


def grampos_do_contorno(pilar: Pilar, arr: Arranjo, phi_t: float) -> list:
    """Segmentos ``((x0, y0), (x1, y1))`` dos grampos nas seções L, T, U e
    vazadas, cm a partir do CG.

    Cada barra do contorno externo sem proteção do estribo (18.2.4) leva um
    grampo reto perpendicular à face em que está, atravessando a parede até
    a linha de armadura do outro lado -- ou, na vazada, até a linha junto ao
    furo. Cada barra da camada interna leva um grampo até a camada externa,
    no sentido contrário ao do furo. O comprimento que entra no quantitativo
    é o da espessura da parede (:func:`comprimento_suplementar`)."""
    from . import geometria as geo
    from .arranjo import linha_do_furo
    secao = pilar.secao
    if secao.tipo not in ("L", "T", "U", "retangular vazada",
                          "circular vazada"):
        return []
    externa = geo.deslocar_para_dentro(secao.contornos()[0], arr.recuo)
    alvos = [externa]
    if secao.tipo in ("retangular vazada", "circular vazada"):
        tipo, furo = linha_do_furo(secao, arr.recuo)
        if tipo == "circulo":
            furo = [(furo / 2.0 * math.cos(2 * math.pi * k / 72),
                     furo / 2.0 * math.sin(2 * math.pi * k / 72))
                    for k in range(72)]
        alvos.append(furo)
    segmentos = []
    n_ext = len(arr.barras) - arr.n_internas
    # Um grampo reto com gancho nas duas pontas trava as duas barras que
    # liga: a barra desprotegida em frente à ponta de outro grampo já está
    # servida, e não leva grampo próprio.
    servidas: set[int] = set()

    def servir(fim):
        """A barra espelhada na outra face da parede, se houver uma a até
        2 cm do pé do grampo: o grampo termina nela (liga as duas barras) e
        ela fica servida. Sem espelhada, o grampo termina no estribo."""
        perto = min(((math.hypot(c.x - fim[0], c.y - fim[1]), j)
                     for j, c in enumerate(arr.barras)), default=(None, None))
        if perto[0] is not None and perto[0] <= max(arr.phi / 10.0, 2.0):
            servidas.add(perto[1])
            c = arr.barras[perto[1]]
            return (c.x, c.y)
        return fim

    if secao.tipo != "circular vazada":
        for i in sorted(desprotegidas_no_contorno(arr, phi_t)):
            if i in servidas:
                continue
            b = arr.barras[i]
            nx_, ny_ = _normal_do_lado(b.x, b.y, externa)
            fim = _cruzar(b.x, b.y, nx_, ny_, alvos)
            if fim is not None:
                segmentos.append(((b.x, b.y), servir(fim)))
    for b in arr.barras[n_ext:]:
        # da camada interna para fora do furo, até a camada externa
        r = math.hypot(b.x, b.y) or 1.0
        if secao.tipo == "circular vazada":
            dx_, dy_ = b.x / r, b.y / r
        else:
            nx_, ny_ = _normal_do_lado(b.x, b.y, alvos[1])
            dx_, dy_ = -nx_, -ny_            # para fora do furo
        fim = _cruzar(b.x, b.y, dx_, dy_, [externa])
        if fim is not None:
            segmentos.append(((b.x, b.y), fim))
    return segmentos


def _engrossar_por_economia(pilar: Pilar, arr: Arranjo, phi_t: float
                            ) -> float:
    """Nas L, T, U e retangular vazada, a bitola de estribo (até a da barra
    longitudinal) que dá a **menor massa de aço transversal por nível** --
    estribo externo mais grampos do contorno. Engrossar raramente dispensa
    todos os grampos nessas seções (os lados longos pedem grampo de qualquer
    modo), mas reduz o número deles; a troca só vale se a massa cair."""
    secao = pilar.secao
    if secao.tipo not in ("L", "T", "U", "retangular vazada"):
        return phi_t
    aco_t = pilar.aco_estribo
    cob = arr.cobrimento or pilar.cobrimento(arr.phi, phi_t)

    def massa_nivel(b: float) -> float:
        n = len(desprotegidas_no_contorno(arr, b))
        comp = (comprimento_estribo(secao, cob, b, aco_t)
                + n * comprimento_suplementar(secao, cob, b, "x", aco_t))
        return massa_linear(b) * comp
    melhor, m_melhor = phi_t, massa_nivel(phi_t)
    if not desprotegidas_no_contorno(arr, phi_t):
        return phi_t
    for b in BITOLAS_ESTRIBOS:
        if b <= phi_t or b > arr.phi:
            continue
        m = massa_nivel(b)
        if m < m_melhor - 1e-9:
            melhor, m_melhor = b, m
    return melhor


def _engrossar_para_dispensar_grampos(secao: SecaoPilar, arr: Arranjo,
                                      phi_t: float) -> float:
    """Menor bitola de estribo que dispensa os grampos suplementares, mm.

    O alcance da proteção é ``20 phi_t`` (item 18.2.4): engrossar o estribo
    aumenta o alcance e pode fazer as barras intermediárias das faces caírem
    dentro dele. Devolve a bitola de entrada quando não há grampo a dispensar
    ou quando nenhuma bitola disponível resolve.

    Vale na retangular e nas L, T, U e retangular vazada (contorno externo).
    Na circular não há grampo a dispensar; a camada junto ao furo das
    vazadas pede grampo sempre, e engrossar não a dispensa.
    """
    if secao.tipo in ("L", "T", "U", "retangular vazada"):
        if not desprotegidas_no_contorno(arr, phi_t):
            return phi_t
        for candidata in BITOLAS_ESTRIBOS:
            if candidata <= phi_t:
                continue
            if candidata > arr.phi:      # estribo mais grosso que a barra
                break
            if not desprotegidas_no_contorno(arr, candidata):
                return candidata
        return phi_t
    if secao.tipo != "retangular" or not (arr.nx and arr.ny):
        return phi_t
    lx = secao.hx - 2.0 * arr.recuo
    ly = secao.hy - 2.0 * arr.recuo
    passo_x = lx / (arr.nx - 1) if arr.nx > 1 else lx
    passo_y = ly / (arr.ny - 1) if arr.ny > 1 else ly
    if not (suplementares_na_face(arr.nx, passo_x, phi_t)
            or suplementares_na_face(arr.ny, passo_y, phi_t)):
        return phi_t
    for candidata in BITOLAS_ESTRIBOS:
        if candidata <= phi_t:
            continue
        if candidata > arr.phi:          # estribo mais grosso que a barra
            break
        if not (suplementares_na_face(arr.nx, passo_x, candidata)
                or suplementares_na_face(arr.ny, passo_y, candidata)):
            return candidata
    return phi_t
