# -*- coding: utf-8 -*-
"""
continuidade.py
Reconhece vigas contínuas dentro do pórtico.

No modelo do pórtico não existe "viga de três vãos": existem três barras
alinhadas, uma atrás da outra. Quem lê o desenho vê uma viga contínua; o
programa precisa ser ensinado a ver o mesmo, e é isso que este módulo faz.

## A regra

Duas barras entram na mesma viga quando são **horizontais**, **colineares** e
se **encontram num nó**. A cadeia cresce enquanto isso valer, e para quando o
alinhamento muda de direção ou o nó seguinte não continua.

Dentro da cadeia, os nós se dividem em dois tipos, e a distinção é o que
define os vãos:

* **apoio** — o nó em que chega um pilar. É ali que a viga descarrega;
* **passagem** — o nó que existe só porque a malha foi dividida ali, por uma
  carga concentrada ou por um encontro com outra viga. Ele **não** é apoio, e
  tratá-lo como tal inventaria um vão que não existe.

Uma cadeia sem nenhum pilar não é viga contínua para este fim: é viga apoiada
em outras vigas, e o programa a declara em vez de fingir que tem apoio.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .core.modelo import ErroDeModelo, Modelo

TOL_ANGULO = 1.0e-6      # tolerância de colinearidade, em seno do ângulo
TOL_VERTICAL = 1.0e-3
TOL_POSICAO = 1.0e-6       # m, para dizer que um nó está dentro dos vãos


@dataclass
class ApoioEmViga:
    """Um nó em que esta viga **se apoia em outra viga**, e não em pilar.

    A viga de apoio entra como apoio na viga que se apoia, e a viga que se
    apoia entra como carga concentrada na de apoio — são duas faces da mesma
    relação, e ela mora aqui para que as duas sejam lidas do mesmo lugar.
    """

    indice_no: int            # índice, em ``VigaContinua.nos``, do nó
    no: str
    viga_de_apoio: str        # nome da cadeia que serve de apoio
    posicao_na_de_apoio: float  # m, do primeiro nó da viga de apoio
    #: Seção da viga de apoio, em cm: a largura é a do apoio que a viga
    #: apoiada enxerga, e a altura decide se ela fica pendurada (18.3.6).
    largura_cm: float = 20.0
    altura_cm: float = 0.0
    #: o nó é a ponta de um balanço da viga de apoio: o apoio desloca, e a
    #: viga que repousa nele só é tratada assim por não ter pilar nenhum
    na_ponta_de_balanco: bool = False


@dataclass
class VigaContinua:
    """Uma cadeia de barras colineares que forma uma viga contínua."""

    nome: str
    barras: list[str] = field(default_factory=list)
    nos: list[str] = field(default_factory=list)
    #: Índices, dentro de ``nos``, dos nós em que chega um pilar.
    apoios: list[int] = field(default_factory=list)
    #: Posição de cada nó ao longo da viga, em metros a partir do primeiro.
    posicoes: list[float] = field(default_factory=list)
    direcao: tuple[float, float, float] = (1.0, 0.0, 0.0)
    #: Nós em que esta viga repousa noutra viga (ver :class:`ApoioEmViga`).
    apoios_em_viga: list[ApoioEmViga] = field(default_factory=list)
    #: Quem manda: 0 é a viga mais "principal" do edifício. Uma viga só se
    #: apoia em outra de prioridade menor (número menor), e por isso a relação
    #: de apoio nunca dá ciclo — V1 em V2 e V2 em V1 ao mesmo tempo.
    prioridade: int = 0
    #: ``(nó, outra viga)``: pontas livres que encontram outra viga sem que
    #: ela possa servir de apoio — duas pontas em balanço que se tocam.
    encontros_sem_apoio: list[tuple[str, str]] = field(default_factory=list)

    @property
    def suportes(self) -> list[int]:
        """Todos os nós de apoio, de pilar **ou** de outra viga, em ordem."""
        return sorted(set(self.apoios)
                      | {a.indice_no for a in self.apoios_em_viga})

    def apoio_em_viga(self, indice_no: int) -> ApoioEmViga | None:
        for a in self.apoios_em_viga:
            if a.indice_no == indice_no:
                return a
        return None

    @property
    def comprimento(self) -> float:
        return self.posicoes[-1] if self.posicoes else 0.0

    @property
    def vaos(self) -> list[float]:
        """Os vãos entre apoios consecutivos, em metros."""
        s = self.suportes
        return [self.posicoes[b] - self.posicoes[a] for a, b in zip(s, s[1:])]

    @property
    def balanco_inicial(self) -> float:
        s = self.suportes
        return self.posicoes[s[0]] if s else 0.0

    @property
    def balanco_final(self) -> float:
        s = self.suportes
        return self.comprimento - self.posicoes[s[-1]] if s else 0.0

    def __str__(self) -> str:
        vaos = " + ".join(f"{v:.2f}" for v in self.vaos) or "sem vão"
        extras = []
        if self.balanco_inicial > 1e-9:
            extras.append(f"balanço inicial {self.balanco_inicial:.2f} m")
        if self.balanco_final > 1e-9:
            extras.append(f"balanço final {self.balanco_final:.2f} m")
        if self.apoios_em_viga:
            extras.append("apoiada em " + ", ".join(
                sorted({a.viga_de_apoio for a in self.apoios_em_viga})))
        return (f"{self.nome}: {len(self.barras)} barras, "
                f"{len(self.suportes)} apoios, vãos {vaos} m"
                + ("  (" + ", ".join(extras) + ")" if extras else ""))


def _eh_vertical(modelo: Modelo, barra) -> bool:
    d = modelo.ponto(barra.no_j) - modelo.ponto(barra.no_i)
    return (abs(d[2]) > 1e-9
            and float(np.hypot(d[0], d[1])) < TOL_VERTICAL * abs(d[2]))


def _eh_horizontal(modelo: Modelo, barra) -> bool:
    d = modelo.ponto(barra.no_j) - modelo.ponto(barra.no_i)
    comprimento = float(np.linalg.norm(d))
    return comprimento > 1e-9 and abs(d[2]) < TOL_ANGULO * comprimento


def nos_com_pilar(modelo: Modelo) -> set[str]:
    """Os nós em que chega alguma barra vertical."""
    apoiados = set()
    for barra in modelo.barras.values():
        if _eh_vertical(modelo, barra):
            apoiados.add(barra.no_i)
            apoiados.add(barra.no_j)
    return apoiados


def _direcao(modelo: Modelo, barra) -> np.ndarray:
    d = modelo.ponto(barra.no_j) - modelo.ponto(barra.no_i)
    return d / float(np.linalg.norm(d))


def vigas_continuas(modelo: Modelo) -> list[VigaContinua]:
    """Agrupa as barras horizontais em vigas contínuas."""
    horizontais = {nome: b for nome, b in modelo.barras.items()
                   if _eh_horizontal(modelo, b)}
    if not horizontais:
        return []

    # Quais barras horizontais chegam a cada nó.
    incidentes: dict[str, list[str]] = {}
    for nome, b in horizontais.items():
        incidentes.setdefault(b.no_i, []).append(nome)
        incidentes.setdefault(b.no_j, []).append(nome)

    def continua(atual: str, no: str) -> str | None:
        """A barra que segue reto a partir de ``no``, se houver só uma."""
        eixo = _direcao(modelo, horizontais[atual])
        candidatas = []
        for outra in incidentes.get(no, []):
            if outra == atual:
                continue
            eixo_outra = _direcao(modelo, horizontais[outra])
            if float(np.linalg.norm(np.cross(eixo, eixo_outra))) < TOL_ANGULO:
                candidatas.append(outra)
        # Duas barras seguindo reto do mesmo nó seriam sobreposição; nesse
        # caso a cadeia para, em vez de escolher uma por sorteio.
        return candidatas[0] if len(candidatas) == 1 else None

    pilares = nos_com_pilar(modelo)
    vistas: set[str] = set()
    vigas = []

    for nome in horizontais:
        if nome in vistas:
            continue

        # Anda para trás até o começo da cadeia, depois para a frente.
        cadeia = [nome]
        vistas.add(nome)
        atual, no = nome, horizontais[nome].no_i
        while (proxima := continua(atual, no)) is not None and proxima not in vistas:
            cadeia.insert(0, proxima)
            vistas.add(proxima)
            b = horizontais[proxima]
            no = b.no_j if b.no_i == no else b.no_i
            atual = proxima
        atual, no = nome, horizontais[nome].no_j
        while (proxima := continua(atual, no)) is not None and proxima not in vistas:
            cadeia.append(proxima)
            vistas.add(proxima)
            b = horizontais[proxima]
            no = b.no_j if b.no_i == no else b.no_i
            atual = proxima

        vigas.append(_montar(modelo, cadeia, pilares, len(vigas) + 1))

    vigas.sort(key=lambda v: (-len(v.barras), v.nome))
    _resolver_apoios_em_viga(modelo, vigas, pilares)
    return vigas


def _altura(modelo: Modelo, viga: VigaContinua) -> float:
    secao = modelo.secoes.get(modelo.barras[viga.barras[0]].secao)
    return float(secao.h) if secao is not None else 0.0


def _resolver_apoios_em_viga(modelo: Modelo, vigas: list[VigaContinua],
                             pilares: set[str]) -> None:
    """Decide, onde duas vigas se encontram sem pilar, qual apoia qual.

    Onde duas cadeias de direções diferentes dividem um nó em que **não**
    chega pilar, uma pode repousar na outra: a de apoio entra como apoio na
    que se apoia, e esta entra como carga concentrada naquela.

    **Só serve de apoio a viga que está de fato segura naquele ponto**: o nó
    tem de cair *dentro* dos vãos dela, entre o primeiro e o último apoio.
    Fora disso — no balanço — o nó é a ponta de uma viga em balanço, que
    deforma, e tratá-lo como apoio indeslocável faria a viga que chega ali se
    comportar como se tivesse um apoio firme que não existe. Foi o que
    aconteceu quando se retirava um pilar de canto: as duas vigas que o
    tinham viravam balanços, mas uma "se apoiava" na ponta da outra e saía
    dimensionada como viga apoiada qualquer. Sem apoio válido, as duas ficam
    em balanço, e o encontro vira aviso (ver ``encontros_sem_apoio``).

    Quando mais de uma viga pode servir de apoio no mesmo nó, vale a de maior
    prioridade da viga inteira: mais apoios de pilar, depois a maior altura de
    seção, depois a mais comprida, e o nome só para desempatar. A relação só
    cresce — um par que já se relacionou não inverte —, e as vigas que dão
    apoio a outras, elas mesmas apoiadas em vigas, entram aos poucos: a
    resolução repete até nada mudar. Se ainda assim três vigas se apoiarem em
    ciclo, o ciclo é desfeito, porque uma reação não pode ser conhecida antes
    de si mesma.
    """
    if not vigas:
        return
    ordem = sorted(vigas, key=lambda v: (-len(v.apoios), -_altura(modelo, v),
                                         -v.comprimento, v.nome))
    for i, v in enumerate(ordem):
        v.prioridade = i
        v.apoios_em_viga = []
        v.encontros_sem_apoio = []

    por_no: dict[str, list[tuple[VigaContinua, int]]] = {}
    for v in vigas:
        for i, no in enumerate(v.nos):
            if no not in pilares:
                por_no.setdefault(no, []).append((v, i))

    def dentro_dos_vaos(v: VigaContinua, i: int) -> bool:
        s = v.suportes
        if len(s) < 2:
            return False
        return (v.posicoes[s[0]] + TOL_POSICAO < v.posicoes[i]
                < v.posicoes[s[-1]] - TOL_POSICAO)

    relacionadas: set[frozenset] = set()
    for _ in range(len(vigas) + 1):
        mudou = False
        for no, presentes in por_no.items():
            if len(presentes) < 2:
                continue
            validas = [(v, i) for v, i in presentes if dentro_dos_vaos(v, i)]
            if not validas:
                continue
            dominante, i_dom = min(validas, key=lambda p: p[0].prioridade)
            secao = modelo.secoes.get(
                modelo.barras[dominante.barras[0]].secao)
            largura = (float(secao.b) * 100.0
                       if secao and secao.b > 0.0 else 20.0)
            altura = float(secao.h) * 100.0 if secao else 0.0
            for v, i in presentes:
                par = frozenset((v.nome, dominante.nome))
                if (v is dominante or par in relacionadas
                        or v.apoio_em_viga(i) is not None):
                    continue
                v.apoios_em_viga.append(ApoioEmViga(
                    indice_no=i, no=no, viga_de_apoio=dominante.nome,
                    posicao_na_de_apoio=dominante.posicoes[i_dom],
                    largura_cm=largura, altura_cm=altura))
                relacionadas.add(par)
                mudou = True
        if not mudou:
            break

    _apoiar_nas_pontas_de_balanco(modelo, por_no)
    _desfazer_ciclos(vigas)
    for v in vigas:
        v.apoios_em_viga.sort(key=lambda a: a.indice_no)

    # Onde a viga termina num nó que não é pilar nem apoio, e há outra viga
    # ali, o encontro fica registrado: são duas pontas em balanço que se
    # tocam, e quem projeta precisa saber.
    for no, presentes in por_no.items():
        if len(presentes) < 2:
            continue
        for v, i in presentes:
            if v.apoio_em_viga(i) is None and i in (0, len(v.nos) - 1):
                for outra, k in presentes:
                    apoio = outra.apoio_em_viga(k)
                    # a outra repousa na ponta deste balanço: não é encontro
                    # sem apoio, é a viga de borda que ele carrega
                    if outra is not v and not (
                            apoio is not None
                            and apoio.viga_de_apoio == v.nome):
                        v.encontros_sem_apoio.append((no, outra.nome))


def _apoiar_nas_pontas_de_balanco(
        modelo: Modelo,
        por_no: dict[str, list[tuple[VigaContinua, int]]]) -> None:
    """A viga sem pilar nenhum repousa nas pontas dos balanços que a recebem.

    É a viga de borda de uma sacada: V1 e V2 avançam em balanço além dos
    pilares, e a V5 fecha as duas pontas. A V5 não tem outro apoio — sem este
    passo ela ficava sem dimensionamento ("sem apoio em pilar nem em viga"),
    e a reação dela não chegava como carga na ponta dos balanços.

    A regra de ``_resolver_apoios_em_viga`` (ponta de balanço não é apoio)
    continua valendo para quem tem pilar: no pilar de canto retirado, as duas
    vigas têm os seus pilares e seguem em balanço. Aqui só entra a viga que
    **não tem pilar algum**, e só quando ganha pelo menos dois apoios — senão
    ela seria um balanço preso na ponta de outro balanço, que não se resolve
    como viga contínua. O apoio desloca junto com a ponta: o modelo isolado
    da viga o trata como indeslocável, e por isso a viga vai com aviso; pelos
    esforços do pórtico, o deslocamento da ponta já está nas contas.
    """
    novos: dict[str, list[ApoioEmViga]] = {}
    sem_pilar: dict[str, VigaContinua] = {}
    for no, presentes in por_no.items():
        if len(presentes) < 2:
            continue
        for v, i in presentes:
            if v.apoios or v.apoio_em_viga(i) is not None:
                continue
            pontas = [(w, j) for w, j in presentes
                      if w is not v and w.apoios and w.prioridade < v.prioridade
                      and j in (0, len(w.nos) - 1)
                      and w.apoio_em_viga(j) is None and j not in w.apoios]
            if not pontas:
                continue
            w, j = min(pontas, key=lambda p: p[0].prioridade)
            secao = modelo.secoes.get(modelo.barras[w.barras[0]].secao)
            novos.setdefault(v.nome, []).append(ApoioEmViga(
                indice_no=i, no=no, viga_de_apoio=w.nome,
                posicao_na_de_apoio=w.posicoes[j],
                largura_cm=(float(secao.b) * 100.0
                            if secao and secao.b > 0.0 else 20.0),
                altura_cm=float(secao.h) * 100.0 if secao else 0.0,
                na_ponta_de_balanco=True))
            sem_pilar[v.nome] = v
    for nome, apoios in novos.items():
        v = sem_pilar[nome]
        if len(v.suportes) + len(apoios) >= 2:
            v.apoios_em_viga.extend(apoios)


def _desfazer_ciclos(vigas: list[VigaContinua]) -> None:
    """Corta as relações de apoio que formam ciclo (A em B, B em C, C em A)."""
    pendentes = {v.nome: {a.viga_de_apoio for a in v.apoios_em_viga}
                 for v in vigas}
    resolvidas: set[str] = set()
    while True:
        avancou = False
        for nome, deps in pendentes.items():
            if nome not in resolvidas and deps <= resolvidas | (
                    deps - set(pendentes)):
                resolvidas.add(nome)
                avancou = True
        if not avancou:
            break
    em_ciclo = set(pendentes) - resolvidas
    for v in vigas:
        if v.nome in em_ciclo:
            v.apoios_em_viga = [a for a in v.apoios_em_viga
                                if a.viga_de_apoio not in em_ciclo]


def _montar(modelo: Modelo, cadeia: list[str], pilares: set[str],
            indice: int) -> VigaContinua:
    """Ordena os nós da cadeia e mede as posições ao longo dela."""
    # Sequência de nós, seguindo as barras encadeadas.
    primeira = modelo.barras[cadeia[0]]
    if len(cadeia) == 1:
        nos = [primeira.no_i, primeira.no_j]
    else:
        segunda = modelo.barras[cadeia[1]]
        comum = {primeira.no_i, primeira.no_j} & {segunda.no_i, segunda.no_j}
        inicio = (primeira.no_j if primeira.no_i in comum else primeira.no_i)
        nos = [inicio]
        atual = inicio
        for nome in cadeia:
            b = modelo.barras[nome]
            atual = b.no_j if b.no_i == atual else b.no_i
            nos.append(atual)

    origem = modelo.ponto(nos[0])
    eixo = modelo.ponto(nos[-1]) - origem
    eixo = eixo / float(np.linalg.norm(eixo))
    posicoes = [float(np.dot(modelo.ponto(n) - origem, eixo)) for n in nos]

    # A cadeia pode ter sido montada de trás para a frente.
    if posicoes[-1] < 0.0:
        nos.reverse()
        cadeia = list(reversed(cadeia))
        origem = modelo.ponto(nos[0])
        eixo = -eixo
        posicoes = [float(np.dot(modelo.ponto(n) - origem, eixo)) for n in nos]

    apoios = [i for i, n in enumerate(nos) if n in pilares]
    return VigaContinua(nome=f"V{indice}", barras=cadeia, nos=nos,
                        apoios=apoios, posicoes=posicoes,
                        direcao=tuple(float(c) for c in eixo))


def viga_que_contem(vigas: list[VigaContinua], barra: str) -> VigaContinua:
    for viga in vigas:
        if barra in viga.barras:
            return viga
    raise ErroDeModelo(f"a barra '{barra}' não está em nenhuma viga contínua")
