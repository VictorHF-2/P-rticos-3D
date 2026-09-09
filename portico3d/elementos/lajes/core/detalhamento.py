# -*- coding: utf-8 -*-
"""
detalhamento.py
Escolha de bitola e espaçamento, comprimento das barras e posições da laje.

A armadura de laje não é "um número de barras": é uma **bitola com um
espaçamento**, e a escolha tem de passar por quatro filtros do item 20.1 e do
§1.8 da apostila:

    phi <= h/8 ....................... bitola máxima
    s <= min(2h ; 20 cm) ............. armadura principal de flexão
    s <= 33 cm ....................... armadura de distribuição
    As(phi, s) >= As,nec ............. resistência

Dentro do que sobra o programa escolhe o par mais leve, com desempate na
faixa recomendada -- 10 a 15 cm na armadura positiva e 15 a 20 cm na
negativa (§1.8). É uma preferência construtiva, não normativa: espaçamento
muito aberto deixa a laje sem apoio para caminhar durante a concretagem, e
muito fechado atrapalha o vibrador.

Os comprimentos seguem regra construtiva, e não a escolha caso a caso de uma
viga -- com uma exceção, na positiva, que é a ancoragem no apoio:

    positiva ....................... **reta** de um extremo da laje ao
                                     outro, entrando em cada apoio até onde
                                     o cobrimento permitir (t/2 do apoio
                                     menos o cobrimento), **com gancho a 90°
                                     só na extremidade em que o trecho reto
                                     não fecha lb,nec** -- é remédio de
                                     apoio apertado, por ponta, não regra
                                     geral (ver ``ancoragem.py``);
    negativa de continuidade ....... um quarto do maior dos vãos menores das
                                     duas lajes, para cada lado do eixo, e
                                     **sempre** com gancho a 90° nas duas
                                     pontas -- ela não termina num apoio de
                                     verdade em nenhuma delas (atravessa
                                     para a laje vizinha);
    negativa de contorno/engaste
    em elemento rígido .............um quinto do vão menor da laje, e
                                     **sempre** com gancho a 90° nas duas
                                     pontas, mesmo só uma delas terminando
                                     num apoio de verdade.

    Nos dois casos a ponta do gancho é a mesma: a espessura da laje menos os
    dois cobrimentos (o que cabe entre as duas faces sem aflorar em nenhuma
    delas) -- regra construtiva fixa (9.4.2.5), e não uma resposta a haver
    ou não apoio na ponta.

Na **negativa** o gancho não é escolhido para fechar a ancoragem: a
geometria é sempre a mesma, e o módulo ``ancoragem`` só confere se ela
fecha, avisando quando não fecha. Na **positiva** é o contrário -- ali o
gancho existe justamente para fechar a ancoragem, e só aparece na ponta em
que ela não fechava reta. Ver o docstring de ``ancoragem.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import ancoragem as anc
from .esforcos import BORDOS_DA_DIRECAO
from .materiais import (BITOLAS, ESPACAMENTOS, Aco, Ambiente, Concreto,
                        area_por_metro, massa_linear)
from .modelo import Config, Laje

#: Faixa de espaçamento recomendada por face (§1.8), cm.
FAIXA_RECOMENDADA = {"inferior": (10.0, 15.0), "superior": (15.0, 20.0)}

#: Folga de consumo dentro da qual a escolha prefere o espaçamento maior.
TOLERANCIA_CONSUMO = 0.05

#: Excesso de área acima da necessária a partir do qual a escolha é tratada
#: como **extremo**: a bitola imposta obrigou a entregar meia vez mais
#: armadura do que a seção pede.
LIMITE_SOBRA = 0.50

#: Excesso de consumo, em relação ao que a escolha livre gastaria, a partir do
#: qual a faixa desejada é reportada como caro.
LIMITE_EXCESSO = 0.25


# ---------------------------------------------------------------------------
# Escolha de bitola e espaçamento
# ---------------------------------------------------------------------------

@dataclass
class Escolha:
    """Par bitola/espaçamento escolhido para uma armadura."""

    phi: float = 0.0                # mm
    espacamento: float = 0.0        # cm
    As_efetiva: float = 0.0         # cm²/m
    As_necessaria: float = 0.0      # cm²/m
    massa: float = 0.0              # kg/m² de laje
    espacamento_maximo: float = 0.0
    espacamento_minimo: float = 0.0
    phi_maxima: float = 0.0         # mm, o h/8 do item 20.1
    phi_minima: float = 0.0         # mm, o piso efetivamente aplicado
    recomendada: bool = True
    # -- faixa desejada pelo projetista ------------------------------------
    #: ``(mín, máx)`` em mm **como o projetista informou**: zero é limite
    #: aberto. Guardado assim, e não já resolvido contra os limites da norma,
    #: para o aviso poder dizer "Ø16 ou maior" em vez de inventar um teto que
    #: o usuário não pediu.
    faixa_desejada: tuple = ()
    faixa_ignorada: str = ""        # qual limite desejado teve de ser solto
    extremo: str = ""               # por que a escolha é um extremo
    #: Os mesmos motivos do ``extremo``, mas normalizados e **sem números**.
    #: É por eles que os avisos se agrupam: seis armaduras que caíram no
    #: mesmo extremo têm números diferentes e um diagnóstico só, e é o
    #: diagnóstico que o projetista precisa ler uma vez.
    extremos: tuple = ()
    massa_livre: float = 0.0        # kg/m² que a escolha sem faixa gastaria
    livre: str = ""                 # a escolha sem faixa, em texto
    erro: str = ""

    @property
    def sobra(self) -> float:
        if self.As_necessaria <= 0.0:
            return 0.0
        return self.As_efetiva / self.As_necessaria - 1.0

    @property
    def excesso(self) -> float:
        """Quanto de aço a mais que a escolha livre gastaria."""
        if self.massa_livre <= 0.0:
            return 0.0
        return self.massa / self.massa_livre - 1.0

    @property
    def no_espacamento_maximo(self) -> bool:
        return (self.espacamento > 0.0
                and self.espacamento >= self.espacamento_maximo - 1e-9)

    @property
    def no_espacamento_minimo(self) -> bool:
        return (self.espacamento > 0.0
                and self.espacamento <= self.espacamento_minimo + 1e-9)

    def texto(self) -> str:
        return f"Ø{self.phi:g} c/{self.espacamento:g}"

    def texto_faixa(self) -> str:
        """A faixa desejada em palavras, respeitando os limites abertos."""
        if not self.faixa_desejada:
            return "sem faixa desejada"
        minimo, maximo = self.faixa_desejada
        if minimo and maximo:
            return f"Ø{minimo:g} a Ø{maximo:g} mm"
        if minimo:
            return f"Ø{minimo:g} mm ou maior"
        return f"Ø{maximo:g} mm ou menor"


def _limites(h: float, face: str, cfg: Config,
             principal: bool) -> tuple[float, float, float, float]:
    """Limites de espaçamento e de bitola: ``(s_min, s_max, phi_min, phi_max)``.

    Só os limites **normativos** e os pisos recomendados por face; a faixa
    desejada pelo projetista entra depois, e por cima destes.
    """
    s_max = (min(2.0 * h, cfg.espacamento_maximo_principal) if principal
             else cfg.espacamento_maximo_distribuicao)
    phi_max = h / 8.0 * 10.0                        # mm, item 20.1
    phi_min = (cfg.bitola_minima_negativa if face == "superior"
               else cfg.bitola_minima_positiva)
    return cfg.espacamento_minimo, s_max, phi_min, phi_max


def _candidatos(As_necessaria: float, face: str, cfg: Config, s_min: float,
                s_max: float, phi_min: float, phi_max: float,
                phi_imposta: float | None,
                espacamento_imposto: float | None) -> list[Escolha]:
    """Todos os pares (bitola, espaçamento) que atendem, dentro dos limites."""
    faixa = FAIXA_RECOMENDADA[face]
    disponiveis = cfg.bitolas_disponiveis or BITOLAS
    saida: list[Escolha] = []
    for phi in disponiveis:
        if phi_imposta is not None:
            if abs(phi - phi_imposta) > 1e-9:
                continue
        elif phi < phi_min - 1e-9 or phi > phi_max + 1e-9:
            continue
        for s in ESPACAMENTOS:
            if espacamento_imposto is not None and \
                    abs(s - espacamento_imposto) > 1e-9:
                continue
            if s < s_min - 1e-9 or s > s_max + 1e-9:
                continue
            As = area_por_metro(phi, s)
            if As < As_necessaria - 1e-9:
                continue
            saida.append(Escolha(
                phi=phi, espacamento=s, As_efetiva=As,
                As_necessaria=As_necessaria,
                massa=massa_linear(phi) * 100.0 / s,
                espacamento_maximo=s_max, espacamento_minimo=s_min,
                phi_maxima=phi_max, phi_minima=phi_min,
                recomendada=faixa[0] - 1e-9 <= s <= faixa[1] + 1e-9))
    return saida


def _melhor(candidatos: list[Escolha]) -> Escolha:
    """O par preferido entre os que atendem.

    O critério é o consumo de aço, mas com uma folga: dentro de
    ``TOLERANCIA_CONSUMO`` do mais leve, prefere-se o **espaçamento maior**,
    porque menos barras é menos mão de obra e menos ponto de amarração -- e a
    diferença de aço, ali, é ruído. Foi assim que a apostila escolheu Ø5 c/14
    onde a Ø4,2 c/10 pesava o mesmo. A faixa de espaçamento recomendada do
    §1.8 é o primeiro corte; se ninguém couber nela, vale a lista toda.
    """
    leve = min(c.massa for c in candidatos)
    curta = [c for c in candidatos
             if c.massa <= leve * (1.0 + TOLERANCIA_CONSUMO)]
    na_faixa = [c for c in curta if c.recomendada]
    escolhidos = na_faixa or curta
    escolhidos.sort(key=lambda c: (-c.espacamento, c.phi))
    return escolhidos[0]


def escolher(As_necessaria: float, h: float, face: str, cfg: Config,
             principal: bool = True, phi_imposta: float | None = None,
             espacamento_imposto: float | None = None) -> Escolha:
    """Escolhe bitola e espaçamento para a armadura pedida.

    ``principal`` distingue a armadura de flexão -- limitada a
    ``min(2h ; 20 cm)`` -- da de distribuição, que o item 20.1 solta até
    33 cm.

    A **faixa de bitola desejada** do projetista (``cfg`` de
    ``bitola_desejada_minima`` a ``bitola_desejada_maxima``) é preferência, e
    não limite normativo. Por isso ela é tratada em três tempos:

    1. tenta-se dentro da faixa desejada;
    2. se nada couber, solta-se o limite desejado que estava barrando e
       registra-se qual foi -- entregar o dimensionamento com os limites da
       norma e avisar é mais útil que recusar a calcular;
    3. couber ou não, compara-se com a escolha **livre**. Quando a faixa
       obriga a gastar muito mais aço, ou empurra o espaçamento para o
       máximo entregando meia vez mais armadura do que a seção pede, a
       escolha é marcada como **extremo** -- que é o caso da bitola mínima de
       Ø20 numa seção que pedia Ø8.
    """
    s_min, s_max, phi_min_norma, phi_max_norma = _limites(h, face, cfg,
                                                          principal)
    res = Escolha(As_necessaria=As_necessaria, espacamento_maximo=s_max,
                  espacamento_minimo=s_min, phi_maxima=phi_max_norma,
                  phi_minima=phi_min_norma)
    if As_necessaria <= 0.0:
        return res

    desejada_min = cfg.bitola_desejada_minima or 0.0
    desejada_max = cfg.bitola_desejada_maxima or 0.0
    tem_faixa = (desejada_min > 0.0 or desejada_max > 0.0) \
        and phi_imposta is None
    faixa_desejada = (desejada_min, desejada_max) if tem_faixa else ()

    # -- 1. escolha livre, que serve de referência -------------------------
    livres = _candidatos(As_necessaria, face, cfg, s_min, s_max,
                         phi_min_norma, phi_max_norma, phi_imposta,
                         espacamento_imposto)
    if not livres:
        res.erro = (
            f"não há bitola e espaçamento comerciais para "
            f"{As_necessaria:.2f} cm²/m com Ø <= h/8 = "
            f"{phi_max_norma:.1f} mm e s <= {s_max:.0f} cm: engrosse a laje")
        return res
    escolha_livre = _melhor(livres)

    if not tem_faixa:
        return escolha_livre

    # -- 2. escolha dentro da faixa desejada -------------------------------
    phi_min = max(phi_min_norma, desejada_min)
    phi_max = min(phi_max_norma, desejada_max or phi_max_norma)
    ignorada = ""
    if phi_min > phi_max + 1e-9:
        # a faixa desejada não cabe entre os limites da norma
        res.faixa_desejada = faixa_desejada
        ignorada = (f"a faixa desejada de {res.texto_faixa()} não cabe entre "
                    f"o piso de Ø{phi_min_norma:g} e o teto h/8 = "
                    f"{phi_max_norma:.1f} mm")
        dentro: list[Escolha] = []
    else:
        dentro = _candidatos(As_necessaria, face, cfg, s_min, s_max, phi_min,
                             phi_max, phi_imposta, espacamento_imposto)
    if not dentro and not ignorada:
        ignorada = (f"nenhuma bitola de Ø{phi_min:g} a Ø{phi_max:g} mm "
                    f"atende {As_necessaria:.2f} cm²/m com s de "
                    f"{s_min:g} a {s_max:.0f} cm")

    if not dentro:
        escolha = escolha_livre
        escolha.faixa_desejada = faixa_desejada
        escolha.faixa_ignorada = (
            f"{ignorada}; valeram os limites da norma e a escolha foi "
            f"{escolha_livre.texto()}")
        escolha.massa_livre = escolha_livre.massa
        escolha.livre = escolha_livre.texto()
        return escolha

    escolha = _melhor(dentro)
    escolha.faixa_desejada = faixa_desejada
    escolha.massa_livre = escolha_livre.massa
    escolha.livre = escolha_livre.texto()

    # -- 3. a faixa custou caro? -------------------------------------------
    if escolha.phi != escolha_livre.phi or \
            abs(escolha.espacamento - escolha_livre.espacamento) > 1e-9:
        motivos, tags = [], []
        if escolha.no_espacamento_maximo and escolha.sobra > LIMITE_SOBRA:
            tags.append(f"o espaçamento chega ao máximo de {s_max:.0f} cm e "
                        f"a armadura ainda passa de meia vez o necessário")
            motivos.append(
                f"o espaçamento chegou ao máximo de {s_max:.0f} cm e ainda "
                f"assim a faixa entrega {escolha.As_efetiva:.2f} cm²/m onde "
                f"bastavam {As_necessaria:.2f} "
                f"({escolha.sobra * 100:.0f} % a mais)")
        if escolha.excesso > LIMITE_EXCESSO:
            tags.append(f"o consumo passa de {LIMITE_EXCESSO * 100:.0f} % "
                        f"acima do que a escolha livre gastaria")
            motivos.append(
                f"o consumo sobe {escolha.excesso * 100:.0f} % em relação a "
                f"{escolha_livre.texto()}, que a escolha livre adotaria")
        if escolha.no_espacamento_minimo:
            tags.append(f"o espaçamento desce ao mínimo de {s_min:g} cm, "
                        f"deixando a malha congestionada")
            motivos.append(
                f"o espaçamento desceu ao mínimo de {s_min:g} cm, deixando a "
                f"malha congestionada")
        escolha.extremo = "; ".join(motivos)
        escolha.extremos = tuple(tags)
    return escolha


# ---------------------------------------------------------------------------
# Posições
# ---------------------------------------------------------------------------

@dataclass
class Posicao:
    """Uma posição de armadura da laje: N1, N2, ...

    A geometria é dada no sistema global da planta, em centímetros, e é o
    bastante para desenhar: ``eixo`` diz por qual eixo a barra corre,
    ``inicio``/``fim`` onde ela começa e acaba nesse eixo, e
    ``faixa_inicio``/``faixa_fim`` a extensão transversal em que as barras se
    repetem.
    """

    numero: int = 0
    laje: str = ""
    tipo: str = ""                  # positiva / negativa / distribuição / contorno
    face: str = "inferior"
    direcao: str = "a"              # direção da laje em que a barra corre
    eixo: str = "X"                 # eixo global em que a barra corre
    phi: float = 0.0                # mm
    espacamento: float = 0.0        # cm
    quantidade: int = 0
    comprimento: float = 0.0        # cm, por barra, já com os ganchos
    trecho_reto: float = 0.0        # cm, sem os ganchos
    #: Ponta reta do gancho a 90° em cada extremidade, cm; 0 = sem gancho
    #: ali. Por extremidade, e não uma contagem só, porque as duas pontas de
    #: uma barra podem ter apoios de larguras diferentes -- uma pede gancho,
    #: a outra não -- e quem desenha precisa saber qual é qual.
    gancho_inicio: float = 0.0
    gancho_fim: float = 0.0
    As_necessaria: float = 0.0      # cm²/m
    As_efetiva: float = 0.0         # cm²/m
    # geometria na planta, cm
    inicio: float = 0.0
    fim: float = 0.0
    faixa_inicio: float = 0.0
    faixa_fim: float = 0.0
    #: Emenda por traspasse (9.5.2), quando a barra passa da vara comercial.
    #: Preenchido por ``dimensionar._conferir_traspasse``, depois que a
    #: posição já existe -- é ele quem conhece o comprimento comercial. As
    #: estações são a abscissa **absoluta** de cada emenda no eixo da barra,
    #: em cm, para o desenho não precisar refazer a conta.
    emendas: int = 0
    l0t: float = 0.0                # cm, traspasse de cada emenda
    estacoes_emenda: list[float] = field(default_factory=list)
    rotulo: str = ""
    observacoes: list[str] = field(default_factory=list)

    @property
    def tem_gancho(self) -> bool:
        return self.gancho_inicio > 0.0 or self.gancho_fim > 0.0

    @property
    def massa(self) -> float:
        """Massa da posição, kg."""
        return (self.quantidade * self.comprimento / 100.0
                * massa_linear(self.phi))

    @property
    def comprimento_total(self) -> float:
        """Comprimento total de barra da posição, m."""
        return self.quantidade * self.comprimento / 100.0

    def descricao(self) -> str:
        return (f"N{self.numero}  {self.quantidade} Ø{self.phi:g} "
                f"c/{self.espacamento:g}  C={self.comprimento:.0f} cm")


def _quantidade(extensao_cm: float, espacamento: float) -> int:
    """Número de barras que cobrem a extensão dada.

    Uma barra em cada extremidade e as demais no espaçamento: o número é o
    de intervalos mais um. Arredonda para cima, porque faltar barra é erro e
    sobrar é centímetro de aço.
    """
    if espacamento <= 0.0:
        return 0
    return int(math.ceil(extensao_cm / espacamento - 1e-9)) + 1


def _eixo_e_intervalos(laje: Laje, direcao: str
                       ) -> tuple[str, tuple[float, float]]:
    """Eixo global da direção e o intervalo da faixa, em cm.

    Devolve ``(eixo, (ini, fim) da faixa em que as barras se repetem)``, no
    sistema global da planta. É a extensão livre da laje na direção
    transversal -- onde a barra propriamente dita começa e acaba vem de
    :func:`_face_bordo_cm` e :func:`_avanco_desenho`, não daqui.
    """
    x0, y0, x1, y1 = (v * 100.0 for v in laje.retangulo)
    eixo = laje.direcao_global(direcao)
    if eixo == "X":
        return "X", (y0, y1)
    return "Y", (x0, x1)


def _face_bordo_cm(laje: Laje, bordo: int) -> float:
    """Posição, em cm, da face física do bordo -- sem nenhum deslocamento de
    apoio. É o que a negativa de continuidade usa como centro: a borda comum
    de verdade, não a face externa da viga que fica só de um lado."""
    x0, y0, x1, y1 = (v * 100.0 for v in laje.retangulo)
    face = laje.face_do_bordo(bordo)
    return {"esquerda": x0, "direita": x1, "baixo": y0, "cima": y1}[face]


def _t_apoio(laje: Laje, bordo: int) -> float:
    """Largura do apoio, cm -- zero no bordo livre, mesmo que a tabela
    guarde outro número (ele fica sem uso quando o bordo é livre)."""
    b = laje.bordos[bordo - 1]
    return 0.0 if b.vinculo == "livre" else b.t


def _avanco_ancoragem(laje: Laje, bordo: int, cobrimento: float) -> float:
    """Trecho reto disponível para a ancoragem (lb,nec), a partir da face da
    laje -- a largura **toda** do apoio conta, porque a barra ancora no
    concreto da viga onde quer que ele esteja, inclusive na parte que já
    fica sob a própria laje (metade da largura, na representação em planta).
    É só para a conferência de ancoragem: não é até aqui que a barra é
    **desenhada** -- ver :func:`_avanco_desenho`.
    """
    return _t_apoio(laje, bordo) - cobrimento


def _avanco_desenho(laje: Laje, bordo: int, cobrimento: float) -> float:
    """Até onde a barra é desenhada, a partir da face da laje -- só a metade
    da largura do apoio que fica **para fora** da laje (a viga é desenhada
    centrada na face, metade para dentro e metade para fora), menos o
    cobrimento. É menos do que a ancoragem credita (ver
    :func:`_avanco_ancoragem`), porque a outra metade da largura já é
    percorrida antes de chegar na face -- não desloca a ponta desenhada,
    só entra na conta de quanto trecho reto existe.

    Num bordo livre o avanço fica negativo, puxando a barra para dentro da
    laje pelo cobrimento -- ela também não pode aflorar na borda livre.
    """
    return _t_apoio(laje, bordo) / 2.0 - cobrimento


# ---------------------------------------------------------------------------
# Montagem das posições de uma laje
# ---------------------------------------------------------------------------

def posicoes_positivas(laje: Laje, direcao: str, escolha: Escolha,
                       numero: int, ambiente: Ambiente,
                       ancoragens: "dict[int, anc.ResultadoAncoragem] | None"
                       = None) -> Posicao:
    """Armadura positiva: reta de um extremo ao outro, com gancho só onde a
    ancoragem reta não fecha.

    É **desenhada** até a face externa da viga (metade da largura do apoio,
    que é a metade que fica para fora da laje), menos o cobrimento -- não
    afunda no meio da viga só porque a ancoragem credita a largura toda (ver
    :func:`_avanco_desenho`). Não escalona (20.1).

    ``ancoragens`` é o resultado de :func:`ancorar_positiva`, por bordo. A
    barra sai reta nas duas pontas quando as duas fecham a ancoragem reta --
    que é o caso corrente da laje. Onde o trecho reto dentro do apoio não
    fecha ``lb,nec``, aquela ponta ganha gancho a 90° (ver
    :func:`anc.verificar_positiva`): é remédio de aperto de apoio, e por
    isso é **por extremidade** -- uma laje pode sair com gancho num bordo e
    reta no outro, e é isso que o desenho mostra.
    """
    eixo, (f0, f1) = _eixo_e_intervalos(laje, direcao)
    bordo_ini, bordo_fim = BORDOS_DA_DIRECAO[direcao]
    c = ambiente.cobrimento_nominal
    ini_barra = _face_bordo_cm(laje, bordo_ini) - \
        _avanco_desenho(laje, bordo_ini, c)
    fim_barra = _face_bordo_cm(laje, bordo_fim) + \
        _avanco_desenho(laje, bordo_fim, c)
    pos = Posicao(
        numero=numero, laje=laje.nome, tipo=f"positiva {direcao}",
        face="inferior", direcao=direcao, eixo=eixo, phi=escolha.phi,
        espacamento=escolha.espacamento,
        As_necessaria=escolha.As_necessaria, As_efetiva=escolha.As_efetiva,
        inicio=ini_barra, fim=fim_barra, faixa_inicio=f0, faixa_fim=f1)
    pos.trecho_reto = fim_barra - ini_barra

    anc_ini = (ancoragens or {}).get(bordo_ini)
    anc_fim = (ancoragens or {}).get(bordo_fim)
    if anc_ini is not None and anc_ini.com_gancho:
        pos.gancho_inicio = anc_ini.ponta_gancho
    if anc_fim is not None and anc_fim.com_gancho:
        pos.gancho_fim = anc_fim.ponta_gancho
    pos.comprimento = pos.trecho_reto + pos.gancho_inicio + pos.gancho_fim
    pos.quantidade = _quantidade(f1 - f0, escolha.espacamento)

    if pos.tem_gancho:
        onde = [f"bordo {b}" for b, a in ((bordo_ini, anc_ini),
                                          (bordo_fim, anc_fim))
                if a is not None and a.com_gancho]
        pos.rotulo = (f"positiva na direção {direcao} — reta de um extremo "
                      f"da laje ao outro, com gancho a 90° em "
                      f"{' e '.join(onde)}, onde o trecho reto dentro do "
                      f"apoio não fechava lb,nec")
        pos.observacoes.append(
            f"gancho a 90° de {max(pos.gancho_inicio, pos.gancho_fim):.0f} "
            f"cm (h - 2c) só na(s) ponta(s) apertada(s): a ancoragem reta "
            f"não fechava ali, e o alfa cai a 0,7 (9.4.2.5)")
    else:
        pos.rotulo = (f"positiva na direção {direcao} — reta de um extremo "
                      f"da laje ao outro, sem gancho, respeitando o "
                      f"cobrimento dentro do apoio")
    return pos


def ponta_gancho_construtiva(h: float, phi: float, ambiente: Ambiente) -> float:
    """Ponta reta do gancho a 90° da armadura negativa: a espessura da laje
    menos os dois cobrimentos -- o que cabe entre as duas faces sem aflorar
    em nenhuma delas (9.3.2.1, 9.4.2.5, 18.3.2.4.1). É regra construtiva
    fixa: o mesmo valor vale numa ponta apoiada numa viga de verdade e numa
    ponta que só termina dentro do próprio concreto da laje -- não depende
    de haver ali algo em que ancorar.
    """
    c_sup = ambiente.cobrimento_superior(phi)
    return max(0.0, h - c_sup - ambiente.cobrimento_nominal)


def ancorar_negativa(laje: Laje, bordo: int, escolha: Escolha,
                     As_calculada: float, concreto: Concreto, aco: Aco,
                     ambiente: Ambiente) -> "anc.ResultadoAncoragem":
    """Ancoragem da negativa que termina num apoio real, não numa vizinha.

    A armadura negativa de continuidade não precisa disto -- ela atravessa a
    borda comum e continua reta dentro da laje vizinha, exatamente como o
    momento fletor positivo de um apoio interno de viga contínua não precisa
    de ancoragem ali. Mas a negativa de contorno e a de engaste em elemento
    rígido **terminam** num apoio de verdade (viga, parede), e esta função
    confere se o trecho reto mais o gancho fecham lb,nec -- o gancho em si
    (:func:`ponta_gancho_construtiva`) é o mesmo, com apoio ou sem ele; o que
    muda é só se há ancoragem para conferir.
    """
    c_sup = ambiente.cobrimento_superior(escolha.phi)
    disponivel = _avanco_ancoragem(laje, bordo, c_sup)
    ponta_gancho = ponta_gancho_construtiva(laje.h, escolha.phi, ambiente)
    return anc.verificar_com_gancho_fixo(
        f"{laje.nome}, bordo {bordo} (negativa)", escolha.phi, As_calculada,
        escolha.As_efetiva, disponivel, ponta_gancho, concreto, aco)


def posicao_negativa(laje: Laje, bordo: int, escolha: Escolha, numero: int,
                     extensao_cada_lado: float, continua: bool,
                     rotulo_extra: str = "",
                     ancoragem: "anc.ResultadoAncoragem | None" = None,
                     tipo: str | None = None,
                     ponta_gancho_continuidade: float = 0.0) -> Posicao:
    """Armadura negativa de um bordo.

    A barra corre perpendicular ao bordo -- na direção que o bordo apoia --,
    e se distribui ao longo do bordo. Na borda de continuidade ela atravessa
    o apoio e vai para as duas lajes; na borda sem continuidade ela entra só
    na laje, e aí o lado do apoio precisa fechar a ancoragem -- ``ancoragem``
    é o resultado de :func:`ancorar_negativa` para essa extremidade. O
    gancho a 90° é regra construtiva fixa **nas duas pontas** da barra
    (9.4.2.5), em qualquer dos dois casos: quando ``continua`` é falso,
    ``ancoragem`` carrega a ponta do gancho (a mesma nas duas pontas, com
    apoio de verdade só numa delas); quando é verdadeiro, não há apoio de
    verdade em nenhuma ponta, e ``ponta_gancho_continuidade`` (ver
    :func:`ponta_gancho_construtiva`) vale para as duas. ``tipo`` decide a
    camada de desenho (o padrão é inferido de ``continua``, e existe para o
    engaste em elemento rígido: ele não continua para uma vizinha, mas é
    armadura calculada como as outras, não o mínimo construtivo do contorno
    -- por isso pede ``tipo="negativa"`` explícito).
    """
    if tipo is None:
        tipo = "negativa" if continua else "contorno"
    direcao = "b" if bordo in BORDOS_DA_DIRECAO["b"] else "a"
    # a barra corre na direção que o bordo apoia, e se distribui ao longo do
    # próprio bordo -- que é a extensão transversal ``(g0, g1)``
    eixo, (g0, g1) = _eixo_e_intervalos(laje, direcao)
    # o bordo 1 e o 2 ficam no início do respectivo eixo; o 3 e o 4, no fim
    no_inicio = bordo in (1, 2)
    face_val = _face_bordo_cm(laje, bordo)

    if continua:
        # a barra atravessa para a laje vizinha: o centro é a borda comum de
        # verdade (a face física), não a face externa de uma viga -- não há
        # apoio a embutir, e por isso nenhum cobrimento a respeitar aqui
        p_ini, p_fim = face_val - extensao_cada_lado, face_val + \
            extensao_cada_lado
    else:
        # desenhada só até a face externa da viga (metade da largura do
        # apoio) menos o cobrimento -- ancoragem.disponivel credita a
        # largura toda (ver _avanco_ancoragem), então tira de volta a
        # metade que fica sob a própria laje para achar o ponto de desenho
        # (a mesma conta de _avanco_desenho, sem repetir o cobrimento)
        avanco = (ancoragem.disponivel - _t_apoio(laje, bordo) / 2.0
                 if ancoragem is not None else 0.0)
        if no_inicio:
            p_ini, p_fim = face_val - avanco, face_val + extensao_cada_lado
        else:
            p_ini, p_fim = face_val - extensao_cada_lado, face_val + avanco

    pos = Posicao(
        numero=numero, laje=laje.nome, tipo=tipo, face="superior",
        direcao=direcao, eixo=eixo, phi=escolha.phi,
        espacamento=escolha.espacamento,
        As_necessaria=escolha.As_necessaria, As_efetiva=escolha.As_efetiva,
        inicio=p_ini, fim=p_fim, faixa_inicio=g0, faixa_fim=g1)
    pos.trecho_reto = p_fim - p_ini
    # o gancho a 90° com a ponta h - 2c é regra construtiva fixa da negativa
    # (9.4.2.5) nas duas pontas da barra -- com apoio de verdade numa delas
    # (contorno, engaste isolado) ou sem apoio de verdade em nenhuma
    # (continuidade, que atravessa para a laje vizinha): o valor muda de
    # onde vem, mas as duas pontas sempre levam o mesmo gancho
    if continua:
        ponta = ponta_gancho_continuidade
    elif ancoragem is not None:
        ponta = ancoragem.ponta_gancho
    else:
        ponta = 0.0
    pos.gancho_inicio = pos.gancho_fim = ponta
    pos.comprimento = pos.trecho_reto + pos.gancho_inicio + pos.gancho_fim
    pos.quantidade = _quantidade(g1 - g0, escolha.espacamento)
    prefixo = {"negativa": "negativa" if continua else "engaste isolado",
              "contorno": "contorno"}.get(tipo, tipo)
    base = f"{prefixo} do bordo {bordo}"
    pos.rotulo = f"{base}{(' — ' + rotulo_extra) if rotulo_extra else ''}"
    if ponta > 0.0:
        pos.observacoes.append(
            f"gancho a 90° de {ponta:.0f} cm (h - 2c) nas duas pontas -- "
            f"regra construtiva da negativa (9.4.2.5), "
            f"{'mesmo sem apoio de verdade em nenhuma delas' if continua else 'a que termina no apoio também confere lb,nec à parte'}")
    return pos


def posicao_distribuicao(laje: Laje, direcao_principal: str,
                         escolha: Escolha, numero: int, ambiente: Ambiente,
                         motivo: str = "") -> Posicao:
    """Armadura de distribuição da laje armada em uma só direção.

    É armadura de face inferior como a positiva, e segue a mesma regra:
    reta, sem gancho, entrando em cada apoio até onde o cobrimento permitir.
    """
    transversal = "b" if direcao_principal == "a" else "a"
    eixo, (f0, f1) = _eixo_e_intervalos(laje, transversal)
    bordo_ini, bordo_fim = BORDOS_DA_DIRECAO[transversal]
    c = ambiente.cobrimento_nominal
    ini_barra = _face_bordo_cm(laje, bordo_ini) - \
        _avanco_desenho(laje, bordo_ini, c)
    fim_barra = _face_bordo_cm(laje, bordo_fim) + \
        _avanco_desenho(laje, bordo_fim, c)
    pos = Posicao(
        numero=numero, laje=laje.nome, tipo="distribuição", face="inferior",
        direcao=transversal, eixo=eixo, phi=escolha.phi,
        espacamento=escolha.espacamento,
        As_necessaria=escolha.As_necessaria, As_efetiva=escolha.As_efetiva,
        inicio=ini_barra, fim=fim_barra, faixa_inicio=f0, faixa_fim=f1)
    pos.trecho_reto = fim_barra - ini_barra
    pos.comprimento = pos.trecho_reto
    pos.quantidade = _quantidade(f1 - f0, escolha.espacamento)
    pos.rotulo = f"distribuição na direção {transversal}"
    if motivo:
        pos.observacoes.append(f"governada por {motivo}")
    return pos


def conferir_posicao(pos: Posicao, laje: Laje, cfg: Config) -> list[str]:
    """Confere uma posição contra os limites do item 20.1."""
    problemas: list[str] = []
    limite_phi = laje.h / 8.0 * 10.0
    if pos.phi > limite_phi + 1e-9:
        problemas.append(
            f"{laje.nome} / N{pos.numero}: Ø{pos.phi:g} mm passa do máximo de "
            f"h/8 = {limite_phi:.1f} mm (20.1)")
    principal = pos.tipo != "distribuição"
    s_max = (min(2.0 * laje.h, cfg.espacamento_maximo_principal) if principal
             else cfg.espacamento_maximo_distribuicao)
    if pos.espacamento > s_max + 1e-9:
        problemas.append(
            f"{laje.nome} / N{pos.numero}: c/{pos.espacamento:g} cm passa do "
            f"máximo de {s_max:.0f} cm (20.1)")
    if pos.As_efetiva < pos.As_necessaria - 1e-6:
        problemas.append(
            f"{laje.nome} / N{pos.numero}: {pos.As_efetiva:.2f} cm²/m não "
            f"cobrem os {pos.As_necessaria:.2f} cm²/m necessários")
    if pos.quantidade <= 0:
        problemas.append(f"{laje.nome} / N{pos.numero}: sem barras")
    return problemas


def ancorar_positiva(laje: Laje, direcao: str, escolha: Escolha,
                     As_calculada: float, concreto: Concreto, aco: Aco,
                     ambiente: Ambiente
                     ) -> dict[int, anc.ResultadoAncoragem]:
    """Ancoragem da armadura positiva nos dois apoios da direção.

    Devolve um dicionário por **bordo**, e não uma lista: as duas pontas
    podem ter apoios de larguras diferentes, e uma pode precisar de gancho
    enquanto a outra sai reta -- é por bordo que a decisão se toma, e é por
    bordo que o desenho precisa saber dela.

    O trecho reto creditado é a largura **toda** do apoio menos o cobrimento
    (mais do que a barra é desenhada, ver :func:`_avanco_desenho`: a barra
    ancora no concreto da viga onde quer que ele esteja). Quando ele não
    fecha ``lb,nec``, aquela ponta ganha gancho a 90° com a ponta que cabe
    entre as duas faces (:func:`ponta_gancho_construtiva`) -- ver
    :func:`anc.verificar_positiva`, que é quem decide reta ou gancho.
    """
    saida = {}
    c = ambiente.cobrimento_nominal
    ponta = ponta_gancho_construtiva(laje.h, escolha.phi, ambiente)
    for bordo in BORDOS_DA_DIRECAO[direcao]:
        b = laje.bordos[bordo - 1]
        if b.vinculo == "livre":
            continue
        disponivel = _avanco_ancoragem(laje, bordo, c)
        saida[bordo] = anc.verificar_positiva(
            f"{laje.nome}, direção {direcao}, bordo {bordo}", escolha.phi,
            As_calculada, escolha.As_efetiva, disponivel, ponta, concreto,
            aco)
    return saida
