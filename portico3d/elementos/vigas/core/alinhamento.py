# -*- coding: utf-8 -*-
"""
alinhamento.py
==============

Alinhamento entre tramos de seções diferentes, e o que ele decide.

Quando dois tramos consecutivos têm a mesma seção, a armadura atravessa o apoio
sem pensar: as faces são as mesmas dos dois lados. Quando a seção muda, a
pergunta passa a ser **por onde os tramos se encostam**, e a resposta não está
na geometria da seção — é decisão de projeto. Uma viga de 50 que vira 70 pode
estar alinhada pelo topo (as duas lajes no mesmo nível), pelo fundo (o forro
contínuo) ou pelo meio; são três detalhamentos diferentes para a mesma tabela de
esforços.

A regra que este módulo aplica é uma só, e vale igual para altura e largura:

    **onde a face é contínua, a barra passa; onde a face termina, a barra
    ancora com gancho, como se estivesse numa extremidade da viga.**

Daí sai a assimetria que confunde quem detalha à mão: numa junta 50 → 70
alinhada pelo topo, a armadura superior é contínua nos dois sentidos, a
armadura inferior do tramo de 50 entra normalmente no tramo de 70 (o nível dela
existe dentro da seção maior), mas a armadura inferior do tramo de 70 **não**
tem para onde ir — o fundo dela morre na junta, e ali ela recebe gancho. Quem
vem da seção menor passa; quem vem da maior, na face que não está alinhada,
para.

Alinhamento pelo meio desalinha as duas faces horizontais, e por isso as duas
recebem gancho no lado da seção maior. Para a largura o raciocínio é o mesmo em
planta: da seção mais estreita para a mais larga há continuidade; no sentido
inverso, as barras do tramo mais largo não encontram concreto adiante.
"""

from __future__ import annotations

from dataclasses import dataclass

from .modelo import Secao, Viga

#: alinhamento pela altura -- por onde as faces horizontais se encostam
VERTICAL = ("Topo", "Meio", "Fundo")
#: alinhamento pela largura -- por onde as faces laterais se encostam, em planta
LATERAL = ("Esquerda", "Centro", "Direita")
#: separador das duas metades quando a altura **e** a largura mudam na junta
SEP = " / "

FACES = ("inferior", "superior")


# ---------------------------------------------------------------------------
# Opções de entrada
# ---------------------------------------------------------------------------

def difere(a: Secao, b: Secao) -> tuple[bool, bool]:
    """(a altura mudou?, a largura mudou?) entre duas seções vizinhas."""
    return abs(a.h - b.h) > 1e-6, abs(a.bw - b.bw) > 1e-6


def opcoes(a: Secao, b: Secao) -> tuple[str, ...]:
    """Alinhamentos que fazem sentido nesta junta.

    Vazio quando as duas seções coincidem em altura e largura: aí não há
    escolha a fazer, e o campo não deve aceitar entrada. Quando as duas
    dimensões mudam, a junta tem duas decisões independentes, e as opções são
    os pares -- não dá para alinhar pelo topo sem dizer também por qual lado.
    """
    dh, db = difere(a, b)
    if dh and db:
        return tuple(f"{v}{SEP}{lat}" for v in VERTICAL for lat in LATERAL)
    if dh:
        return VERTICAL
    if db:
        return LATERAL
    return ()


def padrao(a: Secao, b: Secao) -> str:
    """Alinhamento adotado quando o usuário não escolheu.

    Topo pela altura, porque é o caso corrente: a viga sobe até o nível da
    laje, e é o fundo que varia. Centro pela largura, porque uma viga
    normalmente é centrada no eixo do projeto.
    """
    dh, db = difere(a, b)
    if dh and db:
        return f"Topo{SEP}Centro"
    if dh:
        return "Topo"
    if db:
        return "Centro"
    return ""


def normalizar(texto: str, a: Secao, b: Secao) -> str:
    """Devolve um alinhamento válido para esta junta.

    Texto que não serve mais -- porque a seção foi editada e a junta deixou de
    ter aquela dimensão diferente -- é substituído pelo padrão, e não mantido
    como lixo silencioso.
    """
    validas = opcoes(a, b)
    if not validas:
        return ""
    escolha = (texto or "").strip()
    return escolha if escolha in validas else padrao(a, b)


def partes(texto: str) -> tuple[str, str]:
    """Separa o alinhamento em (vertical, lateral); "" onde não se aplica."""
    vertical = lateral = ""
    for pedaco in (texto or "").split("/"):
        pedaco = pedaco.strip()
        if pedaco in VERTICAL:
            vertical = pedaco
        elif pedaco in LATERAL:
            lateral = pedaco
    return vertical, lateral


def descrever(a: Secao, b: Secao, texto: str) -> str:
    """Frase curta do alinhamento, para relatório e avisos."""
    vertical, lateral = partes(normalizar(texto, a, b))
    ditos = []
    if vertical:
        ditos.append({"Topo": "topos no mesmo nível",
                      "Meio": "meias-alturas no mesmo nível",
                      "Fundo": "fundos no mesmo nível"}[vertical])
    if lateral:
        ditos.append({"Esquerda": "faces laterais esquerdas coincidentes",
                      "Centro": "eixos coincidentes",
                      "Direita": "faces laterais direitas coincidentes"}[
                          lateral])
    return " e ".join(ditos)


# ---------------------------------------------------------------------------
# O que o alinhamento decide
# ---------------------------------------------------------------------------

@dataclass
class Desalinhamento:
    """Uma face que morre na junta, e de que lado dela."""

    face: str                 # 'inferior' ou 'superior'
    lado: str                 # 'esquerda' ou 'direita': o tramo que para ali
    motivo: str


def _maior(a: float, b: float) -> str:
    return "esquerda" if a > b else "direita"


def desalinhamentos(a: Secao, b: Secao, texto: str) -> list[Desalinhamento]:
    """Faces que não atravessam a junta entre os tramos ``a`` e ``b``.

    ``lado`` é o tramo cujas barras param na junta e ganham gancho -- sempre o
    da seção maior naquela dimensão, porque é ele que tem face onde o vizinho
    não tem concreto. As barras do outro lado atravessam e seguem normalmente.
    """
    vertical, lateral = partes(normalizar(texto, a, b))
    fora: list[Desalinhamento] = []

    if vertical:
        lado = _maior(a.h, b.h)
        maior, menor = max(a.h, b.h), min(a.h, b.h)
        degrau = maior - menor
        faces = {"Topo": ("inferior",),
                 "Fundo": ("superior",),
                 "Meio": ("inferior", "superior")}[vertical]
        for face in faces:
            desnivel = degrau / 2.0 if vertical == "Meio" else degrau
            fora.append(Desalinhamento(
                face, lado,
                f"alinhamento em altura “{vertical}” com alturas de "
                f"{menor:g} e {maior:g} cm: a face {face} do tramo mais alto "
                f"está {desnivel:g} cm fora da seção vizinha"))

    if lateral:
        lado = _maior(a.bw, b.bw)
        maior, menor = max(a.bw, b.bw), min(a.bw, b.bw)
        lados_fora = 1 if lateral in ("Esquerda", "Direita") else 2
        recuo = (maior - menor) / lados_fora
        for face in FACES:
            fora.append(Desalinhamento(
                face, lado,
                f"alinhamento lateral “{lateral}” com larguras de "
                f"{menor:g} e {maior:g} cm: {lados_fora} face(s) lateral(is) "
                f"do tramo mais largo recua(m) {recuo:g} cm"))

    return fora


# ---------------------------------------------------------------------------
# Geometria do desenho
# ---------------------------------------------------------------------------

def _base(viga: Viga, dim: str) -> list[float]:
    """Cota da face de referência de cada **trecho**, cm, num datum comum.

    ``dim`` é ``"h"`` (faces horizontais, elevação) ou ``"bw"`` (faces
    laterais, planta). As duas contas são a mesma: parte-se do primeiro trecho
    e, a cada mudança de seção, desloca-se conforme o alinhamento declarado.

    Uma só função para as duas porque elas erravam juntas -- quando a base
    vertical passou a existir, a lateral continuou implícita, e a seção
    transversal espalhava as barras de um trecho estreito pela largura do
    trecho largo. Deixá-las com corpos separados era manter duas chances de
    divergir.
    """
    atributo = "h" if dim == "h" else "bw"
    #: o modo que encosta pela face de cota mais alta, e o que encosta no meio
    pela_alta, pelo_meio = (("Topo", "Meio") if dim == "h"
                            else ("Direita", "Centro"))
    trechos = viga.trechos
    bases = [0.0]
    for t in trechos[1:]:
        ant, atual = trechos[t.k - 1].secao, t.secao
        vert, lat = partes(normalizar(t.alinhamento, ant, atual))
        modo = vert if dim == "h" else lat
        degrau = getattr(ant, atributo) - getattr(atual, atributo)
        if modo == pela_alta:
            base = bases[-1] + degrau
        elif modo == pelo_meio:
            base = bases[-1] + degrau / 2.0
        else:                            # Fundo / Esquerda, ou sem mudança
            base = bases[-1]
        bases.append(base)
    piso = min(bases)
    return [b - piso for b in bases]


def bases_verticais(viga: Viga) -> list[float]:
    """Cota da face inferior de cada trecho, cm, num datum comum.

    O desenho da elevação encostava todos os tramos em y = 0, o que equivale a
    supor alinhamento pelo fundo sempre. Com o alinhamento declarado, cada
    trecho tem a sua base, e a menor delas vira o zero -- assim o desenho não
    tem cota negativa e a viga aparece como vai ser executada.
    """
    return _base(viga, "h")


def bases_laterais(viga: Viga) -> list[float]:
    """Cota da face lateral esquerda de cada trecho, cm, num datum comum.

    O irmão em planta de :func:`bases_verticais`.
    """
    return _base(viga, "bw")


# ---------------------------------------------------------------------------
# As juntas da viga
# ---------------------------------------------------------------------------

@dataclass
class Junta:
    """Uma fronteira onde a seção muda, entre dois trechos prismáticos.

    Pode estar **num apoio** -- e aí há um pilar, cuja largura o trecho de
    seção maior tem de ocupar inteira -- ou **dentro de um tramo**, onde não há
    pilar nenhum e o degrau acontece exatamente na abscissa declarada. A
    diferença viaja em :attr:`largura`: zero significa junta interna, e as
    contas de geometria caem no caso degenerado certo sem um `if` a mais --
    :attr:`x_face` devolve o próprio x, e o gancho de cada lado recua o
    cobrimento para dentro do seu concreto, que é o que se quer nos dois casos.
    """

    k: int                    # índice do apoio, ou -1 na junta interna
    trecho_esq: int
    trecho_dir: int
    x: float                  # m, eixo do apoio ou abscissa da mudança
    largura: float            # cm, largura do pilar; 0 na junta interna
    dominante: int            # trecho de seção maior, que ocupa o pilar todo
    alinhamento: str
    fora: list[Desalinhamento]
    #: tramo de cada lado, para os textos: na junta interna são o mesmo
    tramo_esq: int = 0
    tramo_dir: int = 0

    @property
    def interna(self) -> bool:
        """Está dentro de um tramo, sem pilar para ocupar?"""
        return self.k < 0

    @property
    def x_face(self) -> float:
        """x, m, da face do pilar oposta ao trecho dominante.

        É ali que o degrau acontece, e não no eixo. O trecho de seção maior tem
        de se apoiar na **largura toda** do pilar da divisa: interromper o
        concreto no eixo deixaria meio pilar sem a viga que ele sustenta.

        Na junta interna a largura é zero e isto devolve o próprio ``x``, que é
        exatamente o certo: sem pilar, o degrau é onde o projeto disse.
        """
        meia = self.largura / 200.0
        return (self.x + meia if self.dominante == self.trecho_esq
                else self.x - meia)

    def x_gancho_de(self, trecho: int, cobrimento: float) -> float:
        """x, m, onde a barra do trecho ``trecho`` dobra nesta junta.

        Os dois lados dobram na mesma face -- a do degrau --, mas cada um
        recuando o cobrimento **para dentro do seu próprio concreto**. O trecho
        dominante recua do fim do pilar para trás; o trecho menor, que começa
        naquela face, recua para a frente. Usar o mesmo ponto para os dois
        punha a barra do trecho menor dentro do concreto do maior, onde ela não
        cabe lateralmente: numa junta 20x75 -> 35x50 alinhada "Topo / Centro",
        a barra do trecho de 35 cm aparecia 3,4 cm fora da seção de 20 cm.
        """
        c = cobrimento / 100.0
        para_dentro = -c if self.dominante == self.trecho_esq else c
        if trecho != self.dominante:
            para_dentro = -para_dentro
        return self.x_face + para_dentro

    def x_gancho(self, cobrimento: float) -> float:
        """x, m, onde dobra a barra do trecho dominante."""
        return self.x_gancho_de(self.dominante, cobrimento)

    @property
    def nome(self) -> str:
        if self.interna:
            return f"T{self.tramo_esq + 1} x={self.x:.2f} m"
        return f"P{self.k + 1}"

    def lado_com_gancho(self, face: str) -> set[str]:
        """Lados cujas barras desta face param na junta."""
        return {d.lado for d in self.fora if d.face == face}


def trecho_da(viga: Viga, posicao) -> int:
    """Trecho prismático a que uma posição de armadura pertence.

    Uma barra sempre acaba dentro de um trecho -- a junta corta ou ancora tudo
    que a atravessa --, mas *qual* trecho não se lê da geometria em todos os
    casos: a armadura negativa de um apoio nasce atribuída ao tramo da esquerda
    por convenção de numeração, e o nível dela é o da seção que governa. Quando
    o cálculo sabe, ele grava em ``posicao.trecho``; aqui fica a dedução para
    os outros casos, que é o meio da barra.

    Seis lugares deduziam isto por conta própria, com a expressão
    ``viga.tramos[min(p.tramo, len(viga.tramos) - 1)].secao``. Enquanto o tramo
    era prismático dava no mesmo; com a seção variável dentro do tramo, seis
    respostas diferentes para a mesma pergunta é o defeito que esta função
    existe para não permitir.
    """
    if getattr(posicao, "trecho", -1) >= 0:
        return min(posicao.trecho, len(viga.trechos) - 1)
    do_tramo = viga.trechos_do_tramo(
        min(getattr(posicao, "tramo", 0), len(viga.tramos) - 1))
    xm = (posicao.x_ini + posicao.x_fim) / 2.0
    for t in do_tramo:
        if t.x_ini - 1e-9 <= xm <= t.x_fim + 1e-9:
            return t.k
    return do_tramo[0].k


def cota_da_face(viga: Viga, trecho: int, face: str) -> float:
    """Cota da face pedida do trecho, cm, no datum comum da elevação."""
    base = bases_verticais(viga)[trecho]
    return base if face == "inferior" else base + viga.trechos[trecho].secao.h


def no_nivel_da_face(viga: Viga, posicao, trecho: int, face: str) -> bool:
    """A barra está exatamente no nível daquela face daquele trecho?

    É o que decide se uma barra **cobre** o canto do estribo de um trecho. Uma
    barra do trecho vizinho pode atravessar a junta e passar por cima daquele
    x -- e por isso a contagem por face a tomava como cobertura --, mas se o
    nível dela não é o da face, o canto do estribo continua vazio: numa junta
    60 -> 85 alinhada pelo topo, as barras de fundo do trecho de 60 seguem
    dentro do de 85 a 25 cm acima do fundo dele, e o fundo do trecho de 85
    ficava sem barra nenhuma num pedaço de 32 cm.
    """
    return abs(cota_da_face(viga, trecho_da(viga, posicao), face)
               - cota_da_face(viga, trecho, face)) < 1e-6


def secao_da(viga: Viga, posicao) -> Secao:
    """Seção do trecho em que a posição está."""
    return viga.trechos[trecho_da(viga, posicao)].secao


def trecho_em(viga: Viga, x: float) -> int:
    """Índice do trecho em ``x``, com o degrau na **face** do pilar.

    ``Viga.trecho_em`` troca de trecho no eixo do apoio, que é onde o modelo de
    barras troca de elemento. O concreto troca antes ou depois: o trecho de
    seção maior ocupa a largura toda do pilar da divisa. Entre o eixo e essa
    face as duas respostas divergem, e quem desenha a seção transversal precisa
    da segunda -- senão desenha a seção estreita num ponto onde o concreto já é
    o do trecho largo, e as barras dele aparecem fora do contorno.

    Na junta interna as duas respostas coincidem: não há pilar, e o degrau está
    no próprio x.
    """
    i = viga.trecho_em(x)
    for j in juntas(viga):
        if j.dominante == j.trecho_esq and j.x < x <= j.x_face + 1e-9:
            i = j.trecho_esq
        elif j.dominante == j.trecho_dir and j.x_face - 1e-9 <= x < j.x:
            i = j.trecho_dir
    return i


def tramo_em(viga: Viga, x: float) -> int:
    """Tramo em ``x``, com o degrau na face do pilar."""
    return viga.trechos[trecho_em(viga, x)].tramo


def secao_em(viga: Viga, x: float) -> Secao:
    """Seção do concreto em ``x``, com o degrau na face do pilar."""
    return viga.trechos[trecho_em(viga, x)].secao


def juntas(viga: Viga) -> list[Junta]:
    """Fronteiras de trecho com mudança de seção, e o que cada uma decide.

    Só entram as juntas que **mudam** de seção: onde a seção é a mesma, não há
    junta a detalhar, e listá-la só encheria o relatório de linhas sem conteúdo.

    A lista percorre os **trechos**, não os apoios: é assim que a mudança de
    seção no meio do vão entra sem caso especial. O que a distingue é não haver
    pilar, e isso viaja na largura zero.
    """
    saida: list[Junta] = []
    trechos = viga.trechos
    xs = viga.x_apoios
    for t in trechos[1:]:
        ant = trechos[t.k - 1]
        alinhado = normalizar(t.alinhamento, ant.secao, t.secao)
        if not alinhado:
            continue
        no_apoio = ant.tramo != t.tramo
        # o dominante é o de seção maior: a altura decide, a largura desempata
        dominante = (ant.k if (ant.secao.h, ant.secao.bw)
                     >= (t.secao.h, t.secao.bw) else t.k)
        saida.append(Junta(
            k=t.tramo if no_apoio else -1,
            trecho_esq=ant.k, trecho_dir=t.k,
            x=xs[t.tramo] if no_apoio else t.x_ini,
            largura=viga.apoios[t.tramo].largura if no_apoio else 0.0,
            dominante=dominante, alinhamento=alinhado,
            fora=desalinhamentos(ant.secao, t.secao, alinhado),
            tramo_esq=ant.tramo, tramo_dir=t.tramo))
    return saida
