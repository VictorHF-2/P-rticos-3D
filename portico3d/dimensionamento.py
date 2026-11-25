# -*- coding: utf-8 -*-
"""
dimensionamento.py
A ponte entre a envoltória do pórtico e os motores de elemento.

É o que o projeto inteiro perseguia: o solver resolve o edifício, a envoltória
guarda os esforços concomitantes, e daqui eles seguem para o motor que
dimensiona cada peça. O motor não é reimplementado — é a cópia que está em
``portico3d/elementos``.

## As três conversões, que é onde o erro mora

Os dois programas falam línguas parecidas, e é justamente por isso que a
tradução é perigosa. Três coisas mudam, e cada uma tem conferência própria:

**Unidade.** Aqui tudo é kN e metro. O programa de Pilares trabalha em kN e
**centímetro**: momentos em kN·cm, seção e lance em cm.

**Sinal do normal.** Aqui o normal é negativo à compressão, como manda a
convenção de esforço em barra. Lá o ``Nd`` é **positivo à compressão**, que é
como se escreve o dimensionamento de pilar. O sinal troca na fronteira.

**Nome do eixo.** Lá, ``Mx`` é o momento cuja **excentricidade** cai na direção
x — o par natural de ``hx``, que é a altura da seção nessa mesma direção. Aqui,
o momento com excentricidade na direção local y é o ``Mz``. Então **``Mx`` de lá
recebe o ``Mz`` daqui**, e não o ``My``, apesar da coincidência de letras. Numa
barra vertical o eixo local y é o X global e o local z é o Y global, de modo que
a seção do pilar sai alinhada com os eixos do prédio sem giro nenhum.

## O que esta ponte não decide

Armadura, cobrimento, classe de agressividade e arranjo continuam sendo do
programa de Pilares e da sua configuração. Aqui só se entrega geometria,
esforços e material — o veredito é dele.
"""

from __future__ import annotations

import math

from dataclasses import dataclass, field

import numpy as np

from .core.envoltoria import EnvoltoriaBarra
from .core.modelo import ErroDeModelo, Modelo
from .core.resultados import COMPONENTES

M_PARA_CM = 100.0
KNM_PARA_KNCM = 100.0

#: Seno do ângulo com a vertical abaixo do qual a barra é tida como pilar.
TOL_VERTICAL = 1.0e-3


def barras_verticais(modelo: Modelo) -> list[str]:
    """Os nomes das barras que são pilares."""
    verticais = []
    for nome, barra in modelo.barras.items():
        d = modelo.ponto(barra.no_j) - modelo.ponto(barra.no_i)
        if abs(d[2]) > 1e-9 and float(np.hypot(d[0], d[1])) < TOL_VERTICAL * abs(d[2]):
            verticais.append(nome)
    return verticais


@dataclass
class EsforcosDoLance:
    """Os esforços de um lance, já no vocabulário do programa de Pilares."""

    barra: str
    combinacao: str
    Nd: float = 0.0              # kN, positivo à compressão
    Mx_topo: float = 0.0         # kN·cm
    Mx_base: float = 0.0
    My_topo: float = 0.0
    My_base: float = 0.0

    def __str__(self) -> str:
        return (f"{self.barra} · {self.combinacao}: Nd = {self.Nd:.2f} kN   "
                f"Mx = {self.Mx_base:.0f} / {self.Mx_topo:.0f}   "
                f"My = {self.My_base:.0f} / {self.My_topo:.0f} kN·cm")


def esforcos_do_lance(modelo: Modelo, envoltoria: EnvoltoriaBarra,
                      barra: str) -> list[EsforcosDoLance]:
    """Converte os conjuntos governantes da envoltória para o lance.

    Um conjunto por combinação que governa alguma extremidade — são esses os
    trios (N, My, Mz) simultâneos que a flexão composta oblíqua precisa.
    """
    b = modelo.barras[barra]
    # A base é a extremidade de menor cota; a estação 0 do diagrama fica no
    # nó inicial, que nem sempre é o de baixo.
    inicio_embaixo = modelo.ponto(b.no_i)[2] <= modelo.ponto(b.no_j)[2]
    ultima = len(envoltoria.x) - 1

    por_combinacao: dict[str, dict[int, dict]] = {}
    for registro in envoltoria.casos_de_dimensionamento([0, ultima]):
        estacao = 0 if abs(registro["x"] - envoltoria.x[0]) < 1e-9 else ultima
        por_combinacao.setdefault(registro["combinacao"], {})[estacao] = registro

    saida = []
    for combinacao, estacoes in sorted(por_combinacao.items()):
        if 0 not in estacoes or ultima not in estacoes:
            continue                    # governa só uma ponta; não fecha lance
        base = estacoes[0 if inicio_embaixo else ultima]
        topo = estacoes[ultima if inicio_embaixo else 0]
        # O normal do lance é o mais comprimido das duas pontas.
        normal = min(base["N"], topo["N"])
        saida.append(EsforcosDoLance(
            barra=barra, combinacao=combinacao, Nd=-normal * 1.0,
            Mx_base=base["Mz"] * KNM_PARA_KNCM,
            Mx_topo=topo["Mz"] * KNM_PARA_KNCM,
            My_base=base["My"] * KNM_PARA_KNCM,
            My_topo=topo["My"] * KNM_PARA_KNCM))
    return saida


@dataclass
class VerificacaoDePilar:
    """O veredito do programa de Pilares para um lance, numa combinação."""

    barra: str
    combinacao: str
    esforcos: EsforcosDoLance
    resultado: object = None
    erro: str = ""

    @property
    def passou(self) -> bool:
        """O motor chegou a dar veredito — não diz qual."""
        return self.erro == "" and self.resultado is not None

    @property
    def aprovado(self) -> bool:
        """O veredito foi de aprovação, que é outra coisa.

        A distinção não é preciosismo. O programa de Pilares pode concluir a
        verificação inteira e **reprovar** o lance — o caso comum é nenhum
        arranjo de barras caber nas bitolas permitidas, e aí ``arranjo`` volta
        vazio e o erro fica em ``avisos``. Sem separar as duas coisas, o
        relatório contava esse lance entre os verificados e não dizia que ele
        não passou; ficava a impressão de que estava tudo certo, e a armadura
        simplesmente não existia. É o ``ok`` dele que decide.
        """
        return self.passou and bool(getattr(self.resultado, "ok", False))

    @property
    def motivos(self) -> list[str]:
        """Por que o lance foi reprovado, nas palavras do motor."""
        if self.erro:
            return [self.erro]
        return list(getattr(self.resultado, "erros", []) or [])


def montar_pilar(modelo: Modelo, barra: str, esforcos: EsforcosDoLance,
                 fck: float | None = None):
    """Monta o ``Pilar`` do outro programa a partir do nosso modelo."""
    from .elementos.pilares.core import modelo as mp

    b = modelo.barras[barra]
    secao = modelo.secoes[b.secao]
    material = modelo.materiais[b.material]

    if secao.tipo != "retangular" or secao.b <= 0.0 or secao.h <= 0.0:
        raise ErroDeModelo(
            f"barra '{barra}': o dimensionamento de pilar aqui só monta seção "
            f"retangular declarada por lados, e a seção '{secao.nome}' é "
            f"'{secao.tipo}'")

    classe = fck if fck is not None else material.fck
    if classe <= 0.0:
        raise ErroDeModelo(
            f"barra '{barra}': o material '{material.nome}' não declara fck. "
            "Defina-o como concreto por classe, ou informe o fck")

    comprimento = modelo.comprimento(barra) * M_PARA_CM

    return mp.Pilar(
        nome=barra,
        # hx acompanha o lado na direção local y, que na barra vertical é o X
        # global; hy acompanha o local z, que é o Y global.
        secao=mp.SecaoPilar(tipo="retangular", hx=secao.b * M_PARA_CM,
                            hy=secao.h * M_PARA_CM),
        esforcos=mp.Esforcos(
            Nd=esforcos.Nd, Mx_topo=esforcos.Mx_topo,
            Mx_base=esforcos.Mx_base, My_topo=esforcos.My_topo,
            My_base=esforcos.My_base),
        lance=mp.Lance(l=comprimento, comprimento=comprimento),
        concreto=mp.Concreto(fck=classe))


def verificar_pilares(modelo: Modelo, envoltorias: dict[str, EnvoltoriaBarra],
                      fck: float | None = None,
                      barras: list[str] | None = None
                      ) -> list[VerificacaoDePilar]:
    """Roda o programa de Pilares para cada lance vertical do modelo.

    Devolve uma verificação por combinação governante de cada lance. As que
    falharem trazem o motivo em ``erro`` em vez de interromper o lote: num
    edifício, uma seção mal declarada não pode impedir que as outras sejam
    verificadas.
    """
    from .cache_motores import dimensionar_pilares

    alvos = barras if barras is not None else barras_verticais(modelo)
    # Primeiro todos os pilares a dimensionar, depois o motor de uma vez:
    # assim os que não estão no cache vão em paralelo, um lance por núcleo
    # (``cache_motores``), e os que estão nem chegam ao motor.
    itens = []                        # (barra, esforços, Pilar ou erro)
    for barra in alvos:
        if barra not in envoltorias:
            continue
        for esforcos in esforcos_do_lance(modelo, envoltorias[barra], barra):
            try:
                itens.append((barra, esforcos,
                              montar_pilar(modelo, barra, esforcos, fck)))
            except (ErroDeModelo, ValueError, ZeroDivisionError) as erro:
                itens.append((barra, esforcos, str(erro)))
    pilares = [p for _, _, p in itens if not isinstance(p, str)]
    resultados = iter(dimensionar_pilares(pilares))
    saida = []
    for barra, esforcos, pilar in itens:
        if isinstance(pilar, str):
            saida.append(VerificacaoDePilar(barra, esforcos.combinacao,
                                            esforcos, erro=pilar))
            continue
        resultado, erro = next(resultados)
        saida.append(VerificacaoDePilar(barra, esforcos.combinacao,
                                        esforcos, resultado=resultado,
                                        erro=erro))
    return saida


# ---------------------------------------------------------------------------
# Vigas contínuas
# ---------------------------------------------------------------------------

@dataclass
class VerificacaoDeViga:
    """O veredito do programa de Vigas para uma viga contínua."""

    nome: str
    barras: list[str]
    vaos: list[float]
    resultado: object = None
    viga: object = None
    erro: str = ""
    desenhos: list[str] = field(default_factory=list)
    #: Como o dimensionamento se saiu contra a envoltória do pórtico.
    portico: "ConferenciaDoPortico | None" = None
    avisos: list[str] = field(default_factory=list)
    #: Vigas em que esta repousa (esta entra como carga nelas)...
    apoiada_em: list[str] = field(default_factory=list)
    #: ...e as que repousam nesta (elas entram como carga aqui).
    recebe_de: list[str] = field(default_factory=list)
    #: Com que esforços a viga foi armada (``OpcoesDeCalculo.fonte_vigas``):
    #: ``"portico"``, ``"envolvente"`` ou ``"motor"`` — este também quando
    #: o pórtico foi pedido mas não havia envoltória.
    esforcos: str = "motor"

    @property
    def passou(self) -> bool:
        """O motor deu veredito — não diz qual."""
        return self.erro == "" and self.resultado is not None

    @property
    def aprovado(self) -> bool:
        """Aprovado pelo motor **e** cobrindo a envoltória do pórtico.

        As duas coisas são necessárias. O motor pode aprovar a viga para as
        cargas que recebeu e ainda assim ficar aquém do que o pórtico exige —
        era exatamente isso que acontecia com o vento, que não chega ao motor.
        """
        if not self.passou or not bool(getattr(self.resultado, "ok", False)):
            return False
        return self.portico is None or self.portico.cobre


def _cargas_da_viga(modelo: Modelo, viga, casos: dict[str, str]) -> list:
    """Traduz as cargas distribuídas das barras da cadeia para a viga.

    A posição vai para a coordenada da viga, medida do primeiro nó; a
    intensidade vira a componente **vertical global**, positiva para baixo,
    que é a convenção do programa de Vigas. Carga em eixo local de barra
    inclinada não apareceria certa aqui, mas viga de pórtico de edifício é
    horizontal, e a cadeia só admite barra horizontal.
    """
    from .core.montagem import cargas_locais, preparar_barras
    from .elementos.vigas.core import modelo as mv

    preparadas = preparar_barras(modelo)
    posicao_do_no = dict(zip(viga.nos, viga.posicoes))
    cargas = []

    for nome_caso, acao in casos.items():
        caso = modelo.casos[nome_caso]
        segmentos = cargas_locais(caso, preparadas)
        for barra in viga.barras:
            if not segmentos[barra]:
                continue
            p = preparadas[barra]
            # A cadeia pode percorrer a barra no sentido contrário ao dela.
            x_i = posicao_do_no[p.barra.no_i]
            x_j = posicao_do_no[p.barra.no_j]
            sentido = 1.0 if x_j > x_i else -1.0
            base = x_i + sentido * p.barra.offset_i

            for s in segmentos[barra]:
                if s.vazio:
                    continue
                # Componente vertical global de cada ponta do trapézio.
                q1 = -float((p.R.T @ s.qa)[2])
                q2 = -float((p.R.T @ s.qb)[2])
                if q1 == 0.0 and q2 == 0.0:
                    continue
                xa = base + sentido * s.a
                xb = base + sentido * s.b
                cargas.append(mv.CargaDistribuida(
                    q1=q1, q2=q2, x_ini=min(xa, xb), x_fim=max(xa, xb),
                    acao=acao, descricao=f"{nome_caso} · {barra}"))
    return cargas


@dataclass
class ReacaoRecebida:
    """O que uma viga que se apoia nesta lhe entrega, em kN (característico).

    ``g`` e ``q`` vêm separados porque o motor de Vigas combina as duas ações
    com os próprios coeficientes — entregar a reação já majorada seria
    majorar duas vezes.
    """

    x: float                  # m, posição na viga que recebe
    g: float
    q: float
    de: str                   # nome da viga apoiada
    pendurada: bool = False   # face de baixo da apoiada abaixo da de apoio
    #: altura da viga apoiada, cm: com os topos alinhados, o 18.3.6 reduz a
    #: carga de suspensão por (1 − h_susp/h_viga apoio)
    h_apoiada: float = 0.0


def montar_viga(modelo: Modelo, viga, casos: dict[str, str] | None = None,
                fck: float | None = None, molas: bool = True,
                avisos: list | None = None,
                reacoes_recebidas: list[ReacaoRecebida] | None = None):
    """Monta a ``Viga`` do outro programa a partir da cadeia detectada.

    ``molas`` liga a solidariedade com os pilares nos apoios (14.6.6.1) —
    ver :func:`_apoio_de_pilar`. ``avisos``, quando dado, recebe o que a
    tradução tem a dizer sem que isso interrompa o lote.

    **Viga apoiada em viga.** Onde a cadeia repousa noutra viga (ver
    ``continuidade.ApoioEmViga``), a de apoio entra aqui como **apoio simples**
    com a largura da sua seção. E as vigas que repousam *nesta* chegam como
    ``reacoes_recebidas``: carga concentrada **indireta** (18.3.6), o que faz
    o motor armar a suspensão — e, se a de baixo for mais alta que esta
    (``pendurada``), a conta do tirante inteiro."""
    from .elementos.vigas.core import modelo as mv

    suportes = viga.suportes
    if len(suportes) < 2:
        raise ErroDeModelo(
            f"{viga.nome}: a cadeia tem {len(suportes)} apoio(s), entre "
            "pilares e outras vigas. Sem dois apoios não há viga contínua a "
            "dimensionar")

    if casos is None:
        casos = {nome: ("g" if c.natureza == "permanente" else "q")
                 for nome, c in modelo.casos.items()}

    # Seção e material: os da primeira barra da cadeia, com aviso se variarem.
    primeira = modelo.barras[viga.barras[0]]
    secao = modelo.secoes[primeira.secao]
    material = modelo.materiais[primeira.material]
    if secao.tipo != "retangular" or secao.b <= 0.0:
        raise ErroDeModelo(
            f"{viga.nome}: a seção '{secao.nome}' não é retangular declarada "
            "por lados, e a ponte de vigas só monta essa")

    classe = fck if fck is not None else material.fck
    if classe <= 0.0:
        raise ErroDeModelo(
            f"{viga.nome}: o material '{material.nome}' não declara fck")

    secao_deles = mv.Secao(bw=secao.b * M_PARA_CM, h=secao.h * M_PARA_CM)

    tramos, apoios = [], []
    # Em que posição da lista de apoios do motor cada nó de apoio da cadeia
    # caiu — é por aí que a reação de uma viga apoiada volta para quem a recebe.
    apoio_do_no: dict[int, int] = {}

    def apoio_de(indice_no: int):
        em_viga = viga.apoio_em_viga(indice_no)
        if em_viga is None:
            return _apoio_de_pilar(modelo, viga, viga.apoios.index(indice_no),
                                   molas, secao_deles)
        if avisos is not None:
            avisos.append(
                f"{viga.nome}: apoiada em {em_viga.viga_de_apoio} no nó "
                f"{em_viga.no} — apoio simples e indeslocável: a flexibilidade "
                f"e a torção de {em_viga.viga_de_apoio} não entram")
        return mv.Apoio(tipo="simples",
                        largura=_largura_da_viga_de_apoio(modelo, em_viga),
                        viga_apoio=em_viga.viga_de_apoio,
                        x_na_viga_apoio=em_viga.posicao_na_de_apoio,
                        h_viga_apoio=em_viga.altura_cm,
                        topos_alinhados=True)

    # A seção de cada tramo: retangular, ou T com a mesa colaborante das
    # lajes ao lado (14.6.2.2). ``x`` acompanha a posição do tramo na cadeia.
    mesas = _lajes_ao_lado(modelo) if modelo.calculo.mesa_colaborante else {}
    ini, fim = viga.balanco_inicial > 1e-9, viga.balanco_final > 1e-9
    n_vaos = len(viga.vaos)
    x = [0.0]

    def tramo(L: float, momentos: int | None):
        """``momentos``: quantas pontas do tramo têm momento (0, 1 ou 2);
        ``None`` no balanço."""
        a = 2.0 * L if momentos is None else (1.0, 0.75, 0.60)[momentos] * L
        s = _secao_do_tramo(modelo, viga, x[0], x[0] + L, a, secao_deles,
                            mesas, avisos)
        x[0] += L
        return mv.Tramo(L=L, secao=s)

    if ini:
        tramos.append(tramo(viga.balanco_inicial, None))
        apoios.append(mv.Apoio(tipo="livre"))
    # Um apoio por nó de apoio da cadeia — de pilar ou de outra viga —, e a
    # lista do motor só ganha um "livre" por balanço. Usar o tamanho da lista
    # como índice pegaria o apoio errado quando há balanço inicial.
    for posicao, indice_no in enumerate(suportes):
        if posicao > 0:
            k = posicao - 1
            momentos = int(k > 0 or ini) + int(k < n_vaos - 1 or fim)
            tramos.append(tramo(viga.vaos[k], momentos))
        apoio_do_no[indice_no] = len(apoios)
        apoios.append(apoio_de(indice_no))
    if fim:
        tramos.append(tramo(viga.balanco_final, None))
        apoios.append(mv.Apoio(tipo="livre"))

    # A origem da viga do outro programa é o primeiro apoio, não a ponta do
    # balanço; a coordenada das cargas segue a mesma origem.
    deslocamento = 0.0 if viga.balanco_inicial > 1e-9 else -0.0
    cargas = _cargas_da_viga(modelo, viga, casos)
    for c in cargas:
        c.x_ini += deslocamento
        c.x_fim += deslocamento

    concentradas = []
    for r in (reacoes_recebidas or []):
        for acao, valor in (("g", r.g), ("q", r.q)):
            if valor > 1e-9:
                concentradas.append(mv.CargaConcentrada(
                    P=valor, x=r.x + deslocamento, acao=acao,
                    descricao=f"{r.de} apoiada em {viga.nome}",
                    indireta=True, pendurada=r.pendurada,
                    # o desenho do Pórticos nivela os topos das vigas do
                    # pavimento, como na obra
                    h_apoiada=r.h_apoiada, topos_alinhados=True,
                    origem=r.de))

    deles = mv.Viga(nome=viga.nome, tramos=tramos, apoios=apoios,
                    distribuidas=cargas, concentradas=concentradas,
                    concreto=mv.Concreto(fck=classe))
    deles.apoio_do_no = apoio_do_no

    # **O peso próprio já veio do pórtico.** O motor de Vigas gera o dele
    # sozinho (``Config.peso_proprio``), e como a ponte repassa todas as
    # distribuídas do caso permanente — inclusive as que ``peso_proprio``
    # criou lá atrás —, deixá-lo ligado somava a mesma carga duas vezes. Na
    # viga 20×50 do exemplo isso dava 2,5 kN/m sobre 10,4 kN/m: 24 % a mais
    # de carga permanente, que ninguém veria na memória de cálculo.
    deles.config.peso_proprio = False
    _conferir_peso_proprio(modelo, viga, deles, secao, avisos)

    # **Estribos numa distribuição só por tramo, e não escalonados.** O motor
    # já tem o botão pronto (item 18.3.3.2): ``uniformizar_estribos`` funde as
    # faixas do escalonamento na mais conservadora — o menor espaçamento, com
    # a maior bitola — estendida de ponta a ponta do trecho. Sai mais aço do
    # que o escalonamento fino, e sai uma peça só para montar e conferir na
    # obra, que é a troca que o projeto está pedindo aqui.
    deles.config.uniformizar_estribos = True

    # **Solidariedade viga-pilar pelo modelo "rigidez" do 14.6.6.1.** Os
    # pilares entram na viga contínua como molas (ver ``_apoio_de_pilar``),
    # e as correções do modelo clássico (alíneas a, b e c, feitas com a
    # análise da viga isolada) não mexem na envoltória — que, no modo
    # pórtico, é a do pórtico, onde a solidariedade já é exata.
    deles.config.modelo_pilares = "rigidez"

    return deles


def _lajes_ao_lado(modelo: Modelo) -> dict[str, list[tuple]]:
    """Barra de viga -> ``(laje, lado, b2)`` de cada laje que encosta nela.

    ``lado`` é o sinal do lado da barra em que a laje está (+1 à esquerda de
    quem anda de ``no_i`` para ``no_j``, em planta); ``b2`` é a distância
    livre, m, entre esta viga e a viga paralela do outro lado do painel —
    o ``b2`` da Figura 14.2.
    """
    from .core.lajes import arestas_da_laje, retangulo

    mapa: dict[str, list[tuple]] = {}
    for laje in modelo.lajes.values():
        try:
            arestas, lx, ly = arestas_da_laje(modelo, laje)
        except ErroDeModelo:
            continue
        x0, y0, x1, y1, z = retangulo(modelo, laje)
        centro = np.array([(x0 + x1) / 2.0, (y0 + y1) / 2.0, z])
        def largura(aresta) -> float:
            return max(modelo.secoes[modelo.barras[n].secao].b
                       for n in aresta.barras)

        for k, aresta in enumerate(arestas):
            if laje.em_balanco:
                # Figura 14.2: do lado da laje em balanço vale b3 ≤ b4, com
                # b4 a largura do balanço além da face da alma — e não
                # 0,5·b2. Passar b2 = 2·b4 faz o mesmo limite de 0,5·b2
                # dar exatamente b4.
                b2 = 2.0 * max(laje.balanco - largura(aresta) / 2.0, 0.0)
            else:
                oposta = arestas[(k + 2) % 4]
                entre = ly if k in (0, 2) else lx
                b2 = max(entre - largura(aresta) / 2.0
                         - largura(oposta) / 2.0, 0.0)
            for nome in aresta.barras:
                b = modelo.barras[nome]
                pi, pj = modelo.ponto(b.no_i), modelo.ponto(b.no_j)
                lado = 1 if float(np.cross((pj - pi)[:2],
                                           (centro - pi)[:2])) > 0.0 else -1
                mapa.setdefault(nome, []).append((laje, lado, b2))
    return mapa


def _secao_do_tramo(modelo: Modelo, viga, xa: float, xb: float, a: float,
                    retangular, mesas: dict, avisos: list | None):
    """A seção do tramo ``[xa, xb]`` da cadeia: T quando há laje ao lado.

    14.6.2.2: ``bf = bw + Σ b1``, com ``b1 ≤ 0,1·a`` e ``b1 ≤ 0,5·b2`` para
    cada lado da viga em que haja laje colaborante. Um lado só colabora se a
    laje estiver ao longo do tramo inteiro — nas barras da cadeia que o
    compõem —, e a espessura da mesa é a menor das lajes ao lado (na
    treliçada, a capa). O lado sem laje não ganha mesa; o da laje em balanço
    entra com b3 ≤ b4 (ver ``_lajes_ao_lado``). Com laje de um lado só, a
    seção é L (``lado_mesa``).
    """
    from .elementos.vigas.core import modelo as mv

    if not mesas:
        return retangular
    posicao = dict(zip(viga.nos, viga.posicoes))
    direcao = np.array(viga.direcao, dtype=float)[:2]
    barras = []
    for nome in viga.barras:
        b = modelo.barras[nome]
        x0, x1 = sorted((posicao[b.no_i], posicao[b.no_j]))
        if min(x1, xb) - max(x0, xa) > 1e-6:
            barras.append(nome)
    if not barras:
        return retangular

    b1_total, hf = 0.0, float("inf")
    lados = []
    for lado in (1, -1):
        b2s, hfs = [], []
        for nome in barras:
            b = modelo.barras[nome]
            # o lado é medido no sentido da cadeia, não no da barra
            sentido = 1 if float(np.dot(modelo.ponto(b.no_j)[:2]
                                        - modelo.ponto(b.no_i)[:2],
                                        direcao)) >= 0.0 else -1
            daqui = [(l, b2) for l, s, b2 in mesas.get(nome, [])
                     if s * sentido == lado and l.mesa > 0.0]
            if not daqui:
                break
            b2s.append(min(b2 for _, b2 in daqui))
            hfs.append(min(l.mesa for l, _ in daqui))
        else:
            b1_total += min(0.1 * a, 0.5 * min(b2s))
            hf = min(hf, min(hfs))
            lados.append(lado)
    if b1_total <= 1e-9 or hf == float("inf"):
        return retangular
    hf_cm = hf * M_PARA_CM
    if hf_cm >= retangular.h:
        return retangular
    # Viga de borda: a mesa de um lado só (seção L). "Esquerda" no programa
    # de Vigas é a de quem olha a viga entrando no papel — no sentido da
    # cadeia, o lado +1 de ``_lajes_ao_lado``. O lado não muda a flexão em
    # torno do eixo horizontal; muda o laço da mesa e os desenhos.
    lado_mesa = ("ambos" if len(lados) != 1
                 else "esquerda" if lados[0] == 1 else "direita")
    return mv.Secao(bw=retangular.bw, h=retangular.h, tipo="T",
                    bf=retangular.bw + b1_total * M_PARA_CM, hf=hf_cm,
                    lado_mesa=lado_mesa)


def _largura_da_viga_de_apoio(modelo: Modelo, em_viga) -> float:
    """Largura, em cm, que a viga de apoio oferece à que repousa nela."""
    return em_viga.largura_cm if em_viga.largura_cm > 0.0 else 20.0


def _apoio_de_pilar(modelo: Modelo, viga, indice: int, molas: bool, secao):
    """O apoio de pilar, com o pilar descrito para o 14.6.6.1.

    O programa de Vigas faz a solidariedade viga-pilar do item 14.6.6.1. No
    modelo ``rigidez`` (o que a ponte usa, ver ``montar_viga``) cada pilar
    vira mola rotacional ``k = 4·Ecs·(I_sup/(ℓ_sup/2) + I_inf/(ℓ_inf/2))``
    — a rigidez relativa da Figura 14.8 —, com ``I = transversal ·
    largura³/12``. A ponte passa só o que o pórtico sabe e o motor não: a
    largura do pilar **na direção da viga** e a perpendicular (com o giro do
    pilar, ``compatibilizacao.largura_do_pilar``), e o comprimento dos lances
    acima e abaixo do nó. Antes a ponte calculava a mola sozinha, como
    ``4EI/ℓ`` do lance, metade da do item; agora a viga contínua daqui é a
    mesma do programa de Vigas montada à mão.

    O lance de baixo também é onde a negativa do apoio de extremidade desce
    para ancorar (18.3.2.4-d). ``molas = False`` deixa o apoio como rótula,
    sem pilar descrito.
    """
    from .elementos.vigas.core import modelo as mv

    largura, transversal = _dimensoes_do_pilar(modelo, viga, indice)
    if not molas:
        return mv.Apoio(tipo="simples", largura=largura)
    acima, abaixo = lances_do_pilar(modelo, viga, indice)
    return mv.Apoio(tipo="simples", largura=largura,
                    largura_pilar_transversal=transversal,
                    altura_pilar_acima=acima, altura_pilar_abaixo=abaixo)


def lances_do_pilar(modelo: Modelo, viga, indice: int) -> tuple[float, float]:
    """``(acima, abaixo)``: comprimento, cm, do lance de pilar que sai do nó
    da viga para cima e do que chega a ele por baixo; zero onde não há.

    Sem lance por baixo (pilar que nasce na viga) não há onde a negativa
    descer; sem lance por cima (cobertura) a mola é só a de baixo.
    """
    from .continuidade import _eh_vertical

    if indice >= len(viga.apoios):
        return 0.0, 0.0
    no = viga.nos[viga.apoios[indice]]
    z_no = float(modelo.ponto(no)[2])
    acima = abaixo = 0.0
    for nome, barra in modelo.barras.items():
        if not _eh_vertical(modelo, barra) or no not in (barra.no_i, barra.no_j):
            continue
        outro = barra.no_j if barra.no_i == no else barra.no_i
        L = modelo.comprimento(nome) * M_PARA_CM
        if float(modelo.ponto(outro)[2]) < z_no - 1e-6:
            abaixo = max(abaixo, L)
        else:
            acima = max(acima, L)
    return acima, abaixo


def _conferir_peso_proprio(modelo: Modelo, viga, deles, secao,
                           avisos: list | None) -> None:
    """Desligado o peso próprio do motor, o do pórtico tem de estar lá.

    Desligar sem conferir seria trocar uma carga a mais por uma carga a
    menos, que é bem pior. A conferência é grosseira de propósito: basta que a
    carga permanente repassada cubra o peso da própria seção.
    """
    if avisos is None:
        return
    material = modelo.materiais.get(modelo.barras[viga.barras[0]].material)
    peso = (material.peso_especifico if material else 25.0) * secao.A
    if peso <= 0.0:
        return
    meio = viga.comprimento / 2.0
    permanente = sum(c.valor(meio) for c in deles.distribuidas
                     if c.acao == "g" and c.x_ini <= meio <= c.x_fim)
    if permanente < peso * 0.99:
        avisos.append(
            f"{viga.nome}: a carga permanente repassada ({permanente:.2f} "
            f"kN/m) não cobre nem o peso próprio da seção ({peso:.2f} kN/m). "
            "O peso próprio do motor de Vigas fica desligado porque quem o "
            "traz é o pórtico — e aqui o pórtico não o tem. Rode 'peso "
            "próprio' no caso permanente do modelo")


def _dimensoes_do_pilar(modelo: Modelo, viga, indice: int
                        ) -> tuple[float, float]:
    """Dimensões, cm, do pilar que apoia a viga naquele nó: **na direção da
    viga** — o apoio, onde a armadura da viga ancora — e a perpendicular.

    Vêm dos eixos locais do pilar, com o giro dele
    (``compatibilizacao.largura_do_pilar``): uma viga em Y sobre um 20×60
    com os 60 cm em Y tem 60 cm de apoio, e não 20.
    """
    from .compatibilizacao import largura_do_pilar
    from .continuidade import _eh_vertical

    if indice >= len(viga.apoios):
        return 20.0, 20.0
    no = viga.nos[viga.apoios[indice]]
    for nome, barra in modelo.barras.items():
        if _eh_vertical(modelo, barra) and no in (barra.no_i, barra.no_j):
            secao = modelo.secoes[barra.secao]
            if secao.b > 0.0:
                return largura_do_pilar(modelo, nome, viga.direcao)
    return 20.0, 20.0


@dataclass
class ConferenciaDoPortico:
    """O que o pórtico exige da viga, contra o que o motor dimensionou.

    A comparação é feita em **área de aço**, e não em momento, de propósito.
    Momento é grandeza intermediária: dois momentos parecidos podem pedir
    armaduras bem diferentes se caírem em faces opostas, e um momento de sinal
    trocado — o caso do vento revertendo o apoio — não tem razão numérica que
    o descreva. Área de aço na face certa, sim: é o que vai para a obra, e é
    o que o projetista consegue conferir.

    O As exigido sai da mesma função de flexão que o motor usa, com a mesma
    seção e o mesmo d. A diferença entre os dois números é só a solicitação.
    """

    As_exigido_sup: float = 0.0      # cm², pelo pórtico
    As_obtido_sup: float = 0.0       # cm², pelo motor de Vigas
    As_exigido_inf: float = 0.0
    As_obtido_inf: float = 0.0
    x_critico: float = 0.0           # m, onde a folga é menor
    face_critica: str = ""
    momento_portico: float = 0.0     # kN·m no ponto crítico
    momento_motor: float = 0.0
    #: Folga admitida antes de reprovar. O pórtico discretiza em estações e o
    #: motor em malha de elementos; exigir igualdade exata reprovaria viga por
    #: diferença de interpolação.
    TOLERANCIA = 1.05

    @property
    def razao(self) -> float:
        """Quanto o pórtico exige a mais, na face mais apertada."""
        razoes = [e / o for e, o in ((self.As_exigido_sup, self.As_obtido_sup),
                                     (self.As_exigido_inf, self.As_obtido_inf))
                  if o > 1e-9]
        faltando = [e for e, o in ((self.As_exigido_sup, self.As_obtido_sup),
                                   (self.As_exigido_inf, self.As_obtido_inf))
                    if o <= 1e-9 and e > 1e-9]
        if faltando:
            return float("inf")
        return max(razoes) if razoes else 0.0

    @property
    def cobre(self) -> bool:
        return self.razao <= self.TOLERANCIA

    def __str__(self) -> str:
        if self.cobre:
            return f"pórtico: coberto (exige {self.razao:.2f}x do detalhado)"
        quanto = ("armadura ausente na face"
                  if self.razao == float("inf") else f"{self.razao:.2f}x")
        return (f"pórtico: NÃO COBRE — {quanto} na face "
                f"{self.face_critica} em x = {self.x_critico:.2f} m "
                f"(exige {max(self.As_exigido_sup, self.As_exigido_inf):.2f} "
                f"cm², tem {max(self.As_obtido_sup, self.As_obtido_inf):.2f} "
                f"cm²; M = {self.momento_portico:.1f} contra "
                f"{self.momento_motor:.1f} kN·m)")


def envoltoria_da_viga(modelo: Modelo, viga,
                       envoltorias: dict[str, EnvoltoriaBarra]):
    """A envoltória do pórtico ao longo da cadeia, na coordenada da viga.

    Devolve ``(x, M_min, M_max, V_min, V_max)`` em metros e kN. É o que o
    motor de Vigas não tem como calcular, porque ele não conhece vento nem
    desaprumo nem a rigidez do pórtico inteiro — e é o que a memória de
    cálculo do edifício precisa mostrar.
    """
    posicao_do_no = dict(zip(viga.nos, viga.posicoes))
    xs, mn, mx, vn, vx = [], [], [], [], []
    im, iv = COMPONENTES.index("My"), COMPONENTES.index("Vz")

    for barra in viga.barras:
        env = envoltorias.get(barra)
        if env is None:
            continue
        b = modelo.barras[barra]
        x_i, x_j = posicao_do_no[b.no_i], posicao_do_no[b.no_j]
        sentido = 1.0 if x_j > x_i else -1.0
        for k, s_local in enumerate(env.x):
            xs.append(x_i + sentido * float(s_local))
            mn.append(float(env.minimos[im, k]))
            mx.append(float(env.maximos[im, k]))
            vn.append(float(env.minimos[iv, k]))
            vx.append(float(env.maximos[iv, k]))

    if not xs:
        vazio = np.zeros(0)
        return vazio, vazio, vazio, vazio, vazio
    ordem = np.argsort(np.array(xs))
    return (np.array(xs)[ordem], np.array(mn)[ordem], np.array(mx)[ordem],
            np.array(vn)[ordem], np.array(vx)[ordem])


def envoltoria_externa(modelo: Modelo, viga,
                       envoltorias: dict[str, EnvoltoriaBarra] | None,
                       fonte: str):
    """A função que troca a envoltória ELU do motor de Vigas pela do pórtico.

    É o que faz a viga ser armada com os esforços do edifício — vento,
    desaprumo, a rigidez real dos pilares e, com a grelha, a carga que a laje
    entrega pela rigidez —, e não com os de uma viga contínua isolada sob g e
    q. Devolve ``None`` quando não há envoltória ou quando ``fonte`` é
    ``"motor"``: aí o motor segue sozinho, como antes.

    ``"portico"`` substitui momentos e cortantes; ``"envolvente"`` fica com o
    pior dos dois em cada seção. A cortante vai em módulo, simétrica: a
    cadeia pode percorrer uma barra no sentido contrário ao dela, o que troca
    o sinal de V, e o motor só usa o módulo.
    """
    from dataclasses import replace

    if not envoltorias or fonte == "motor":
        return None
    x, mn, mx, vn, vx = envoltoria_da_viga(modelo, viga, envoltorias)
    if len(x) == 0:
        return None
    v_abs = np.maximum(np.abs(vn), np.abs(vx))
    combinacoes = sorted({c for b in viga.barras if b in envoltorias
                          for c in envoltorias[b].combinacoes})

    def aplicar(env):
        M_max = np.interp(env.x, x, mx)
        M_min = np.interp(env.x, x, mn)
        V = np.interp(env.x, x, v_abs)
        if fonte == "envolvente":
            M_max = np.maximum(M_max, env.M_max)
            M_min = np.minimum(M_min, env.M_min)
            V = np.maximum(V, env.V_abs)
            nomes = list(env.combinacoes) + combinacoes
        else:
            nomes = combinacoes
        return replace(env, M_max=M_max, M_min=M_min, V_max=V, V_min=-V,
                       combinacoes=nomes)

    # o que a função aplica, para o cache dos motores reconhecer a mesma
    # envoltória numa outra chamada (``cache_motores.dimensionar_viga``)
    from .cache_motores import impressao
    aplicar.chave = impressao(fonte, x, mn, mx, v_abs, combinacoes)
    return aplicar


def dimensionar_com_envoltoria(deles, externa=None):
    """Roda o motor de Vigas, trocando a envoltória ELU dele por ``externa``.

    O motor é cópia byte a byte do programa de Vigas, e há conferência para
    isso — a troca não pode ser feita editando a cópia. Ela é feita por
    fora: durante a chamada, o ``combinacoes`` que o ``dimensionar`` do motor
    enxerga é um representante que devolve tudo igual, menos a envoltória
    ELU, que passa por ``externa``. O ELS (``envoltoria_servico``) não passa
    por ali e continua sendo o da viga contínua.
    """
    from .cache_motores import dimensionar_viga
    from .elementos.vigas.core import dimensionar as motor

    # a mesma viga com a mesma envoltória não é dimensionada duas vezes na
    # sessão (o "Dimensionar", a armadura 3D, o projeto completo)
    return dimensionar_viga(
        deles, externa,
        lambda d, e: _dimensionar_com_envoltoria(motor, d, e))


def _dimensionar_com_envoltoria(motor, deles, externa):
    if externa is None:
        return motor.dimensionar(deles)

    # Com a envoltória do pórtico, o momento negativo não é reduzido sobre o
    # apoio pelo motor: o pórtico já é a autoridade sobre onde o momento é
    # lido. Quem quer considerar a largura do apoio modela o trecho rígido do
    # nó viga-pilar (``Barra.offset_i/offset_j``, 14.6.2.1), e aí a
    # envoltória já chega com ele. Reduzir de novo aqui deixaria a armadura
    # abaixo do que o pórtico exige — a conferência contra o pórtico acusava
    # isso. No Vigas R03 a redução era "à face" (``momento_face_apoio``); no
    # R04 virou o arredondamento R·t/8 do 14.6.3 (``arredondar_momento_apoio``),
    # que ainda por cima tira o R do modelo isolado da viga, e não do pórtico.
    deles.config.arredondar_momento_apoio = False

    original = motor.cb

    class _Representante:
        def __getattr__(self, nome):
            return getattr(original, nome)

        @staticmethod
        def calcular(*args, **kwargs):
            env, solicitacoes = original.calcular(*args, **kwargs)
            tipos = kwargs.get("tipos", args[2] if len(args) > 2 else ("ELU",))
            if tuple(tipos) == ("ELU",):
                env = externa(env)
            return env, solicitacoes

    motor.cb = _Representante()
    try:
        return motor.dimensionar(deles)
    finally:
        motor.cb = original


def _As_para(momento: float, deles, resultado, x: float | None = None
             ) -> float:
    """Área de aço para o momento dado, pela flexão do próprio motor.

    Usa a mesma função, a mesma seção e o mesmo ``d`` do dimensionamento, de
    modo que a diferença entre o exigido e o obtido seja **só** a solicitação.
    """
    from .elementos.vigas.core import flexao as fl

    if abs(momento) < 1e-9:
        return 0.0
    secao = deles.secao_em(x) if x is not None else deles.tramos[0].secao
    cob = deles.ambiente.cobrimento_nominal
    d_linha = cob + deles.config.phi_estribo / 10.0 + 1.0
    # O momento vai com sinal: é o sinal que diz ao motor qual face está
    # tracionada, e na seção T isso decide se a mesa trabalha (positivo) ou
    # não (negativo). Em módulo, o negativo seria calculado com a mesa
    # comprimida — contra a segurança.
    try:
        res = fl.dimensionar(secao, deles.concreto, deles.aco, momento,
                             d_linha, d_linha, delta=1.0)
    except (ValueError, ZeroDivisionError):
        return float("inf")
    # A exigência do pórtico é o As de **cálculo**, sem a armadura mínima: o
    # mínimo é regra de detalhamento, que o motor já aplica no vão. Com o
    # mínimo dentro, a seção T (mínimo sobre a área da mesa) acusava falta
    # de aço junto ao apoio por um momento de 1 kN·m.
    return float(res.As + max(getattr(res, "As_linha", 0.0), 0.0))


def As_detalhado(resultado, x_m: float, face: str) -> float:
    """Área de aço **desenhada** numa face, na abscissa dada, cm².

    Soma as barras que realmente passam ali — as mesmas posições que vão para
    a planta, o DXF e a vista de armadura. É contra isto que a exigência do
    pórtico tem de ser medida, e não contra o As que o motor calculou para as
    suas próprias cargas: o que segura a viga é a barra desenhada, com a
    armadura mínima e o porta-estribo que ela já traz de bônus.
    """
    total = 0.0
    for p in resultado.posicoes:
        if p.tipo not in ("longitudinal", "porta") or p.face != face:
            continue
        if p.x_ini - 1e-9 <= x_m <= p.x_fim + 1e-9:
            total += p.n * math.pi * (p.phi / 10.0) ** 2 / 4.0
    return total


def conferir_contra_o_portico(modelo: Modelo, viga, resultado, deles,
                              envoltorias: dict[str, EnvoltoriaBarra]
                              ) -> ConferenciaDoPortico:
    """Compara, em área de aço, o que o pórtico exige com o que a viga tem."""
    x, mn, mx, _, _ = envoltoria_da_viga(modelo, viga, envoltorias)
    conf = ConferenciaDoPortico()
    if len(x) == 0:
        return conf

    env = resultado.envoltoria
    pior = -1.0
    for k, xi in enumerate(x):
        # face superior é a tracionada pelo momento negativo
        for face, exigido in (("superior", min(float(mn[k]), 0.0)),
                              ("inferior", max(float(mx[k]), 0.0))):
            if abs(exigido) < 1e-9:
                continue
            As_e = _As_para(exigido, deles, resultado, float(xi))
            As_o = As_detalhado(resultado, float(xi), face)
            razao = float("inf") if As_o <= 1e-9 else As_e / As_o
            if razao > pior:
                pior = razao
                conf.x_critico = float(xi)
                conf.face_critica = face
                conf.momento_portico = exigido
                conf.momento_motor = float(np.interp(
                    xi, env.x, env.M_min if face == "superior" else env.M_max))
                if face == "superior":
                    conf.As_exigido_sup, conf.As_obtido_sup = As_e, As_o
                    conf.As_exigido_inf = conf.As_obtido_inf = 0.0
                else:
                    conf.As_exigido_inf, conf.As_obtido_inf = As_e, As_o
                    conf.As_exigido_sup = conf.As_obtido_sup = 0.0
    return conf


def verificar_vigas(modelo: Modelo, pasta_desenhos=None,
                    fck: float | None = None,
                    envoltorias: dict[str, EnvoltoriaBarra] | None = None
                    ) -> list[VerificacaoDeViga]:
    """Dimensiona cada viga contínua com o que o pórtico sabe.

    O dimensionamento continua sendo do programa de Vigas — é dele a flexão, o
    cisalhamento, o detalhamento, a ancoragem e o traspasse. O que mudou é o
    que ele recebe, e são três coisas que antes se perdiam no caminho:

    **A rigidez dos pilares.** Os apoios vão como mola, e não como rótula. O
    motor já previa isso; a ponte é que não usava.

    **O peso próprio, uma vez só.** Ele vem do pórtico, e o do motor fica
    desligado — antes os dois entravam, 24 % a mais de carga permanente na
    viga do exemplo.

    **As ações laterais.** O motor não tem vento nem desaprumo: só combina G e
    Q. Com ``envoltorias``, a diferença entre o que o pórtico exige no apoio e
    o que a análise dele produziu volta como momento de extremidade, e a viga
    é redimensionada. Sem ``envoltorias`` isso não acontece, e a verificação
    diz que não aconteceu em vez de ficar calada.

    No fim, o resultado é **conferido contra a envoltória do pórtico** ponto a
    ponto. É essa conferência que responde se a armadura cobre o que o
    edifício pede — e é o que faltava: o vento produzia 63 kN·m na viga do
    exemplo, mais que o peso permanente, e não chegava à armadura.

    **O desenho, quando pedido, sai num DXF só — todas as vigas lado a
    lado**, e sem PNG. Antes eram um par de imagens (elevação e seções) mais
    um DXF por viga; num edifício com vinte vigas contínuas isso é sessenta
    arquivos, a metade deles imagem que ninguém abre fora do programa. Uma
    prancha só é o que se leva para a obra, e pular o render em matplotlib do
    par de imagens é o que mais barateia o tempo desta chamada.
    """
    from .continuidade import vigas_continuas

    cadeias = [v for v in vigas_continuas(modelo) if len(v.suportes) >= 2]
    saida = dimensionar_cadeias(modelo, cadeias, fck=fck,
                                envoltorias=envoltorias)
    if pasta_desenhos is not None:
        gravar_pranchas_de_vigas(saida, pasta_desenhos)
    return saida


def _reacao_no_apoio(resultado, indice_apoio: int) -> tuple[float, float]:
    """Reação característica, em kN, que a viga entrega num apoio: ``(g, q)``.

    A permanente é a soma de todos os casos-base de ``g`` (a viga inteira
    carregada). A variável soma só as parcelas **positivas** dos casos-base de
    ``q`` — a reação máxima possível, que é a que a viga de apoio tem de
    aguentar —, e não o valor da viga toda carregada, que pode ser menor num
    apoio de extremidade quando um vão vizinho alivia.
    """
    g = q = 0.0
    for r in resultado.estrutura.respostas:
        valor = float(r.reacoes[indice_apoio])
        if r.acao == "g":
            g += valor
        else:
            q += max(valor, 0.0)
    return max(g, 0.0), q


def dimensionar_cadeias(modelo: Modelo, cadeias: list,
                        fck: float | None = None,
                        envoltorias: dict[str, EnvoltoriaBarra] | None = None,
                        conferir_aviso_de_envoltoria: bool = True
                        ) -> list[VerificacaoDeViga]:
    """Dimensiona as vigas dadas, na ordem em que uma recebe da outra.

    **Viga apoiada em viga.** Se V1 se apoia em V2, em V1 a V2 entra como
    apoio, e em V2 a V1 entra como carga concentrada — a reação de V1 naquele
    nó, que só se conhece depois de V1 dimensionada. Por isso a ordem não é
    qualquer uma: as de menor prioridade (as que repousam nas outras) vão
    primeiro, e cada reação é guardada para a viga que a recebe. A ordem de
    prioridade vem de ``continuidade`` e não dá ciclo.

    O resultado volta na ordem em que as cadeias foram dadas.
    """

    recebidas: dict[str, list[ReacaoRecebida]] = {}
    falhas: dict[str, list[str]] = {}
    feitas: dict[str, VerificacaoDeViga] = {}

    for viga in _ordem_de_projeto(cadeias):
        avisos: list[str] = list(falhas.get(viga.nome, []))
        for no, outra in viga.encontros_sem_apoio:
            avisos.append(
                f"{viga.nome}: a ponta em {no} encontra {outra}, mas {outra} "
                "não está apoiada ali (é balanço, ou o nó fica fora dos vãos "
                "dela) — as duas pontas seguem em balanço, sem apoio mútuo")
        for a in viga.apoios_em_viga:
            if a.na_ponta_de_balanco:
                avisos.append(
                    f"{viga.nome}: sem pilar, apoia-se em {a.no} na ponta do "
                    f"balanço de {a.viga_de_apoio} — apoio deslocável; os "
                    "esforços do pórtico já levam isso em conta, o modelo "
                    "isolado da viga o trata como fixo")
        recebe = recebidas.get(viga.nome, [])
        try:
            deles = montar_viga(modelo, viga, fck=fck, avisos=avisos,
                                reacoes_recebidas=recebe)
            externa = envoltoria_externa(modelo, viga, envoltorias,
                                         modelo.calculo.fonte_vigas)
            resultado = dimensionar_com_envoltoria(deles, externa)
        except (ErroDeModelo, ValueError, ZeroDivisionError, IndexError,
                KeyError) as e:
            feitas[viga.nome] = VerificacaoDeViga(
                viga.nome, list(viga.barras), list(viga.vaos), erro=str(e),
                avisos=avisos,
                apoiada_em=sorted({a.viga_de_apoio
                                   for a in viga.apoios_em_viga}))
            for a in viga.apoios_em_viga:
                falhas.setdefault(a.viga_de_apoio, []).append(
                    f"{viga.nome} se apoia nesta viga e não pôde ser "
                    "dimensionada: a reação dela NÃO entrou como carga aqui")
            continue

        for r in recebe:
            avisos.append(
                f"{viga.nome}: recebe de {r.de} uma reação de g = {r.g:.1f} e "
                f"q = {r.q:.1f} kN em x = {r.x:.2f} m (carga indireta, "
                "18.3.6" + (", viga pendurada" if r.pendurada else "") + ")")

        # A reação de cada apoio em viga vira carga na viga que a recebe.
        h_propria = _altura_da_cadeia(modelo, viga)
        for a in viga.apoios_em_viga:
            g, q = _reacao_no_apoio(resultado, deles.apoio_do_no[a.indice_no])
            recebidas.setdefault(a.viga_de_apoio, []).append(ReacaoRecebida(
                x=a.posicao_na_de_apoio, g=g, q=q, de=viga.nome,
                pendurada=h_propria > a.altura_cm + 1e-6,
                h_apoiada=h_propria))          # já em cm

        conferencia = None
        if envoltorias:
            conferencia = conferir_contra_o_portico(
                modelo, viga, resultado, deles, envoltorias)
        elif conferir_aviso_de_envoltoria:
            avisos.append(
                f"{viga.nome}: dimensionada sem a envoltória do pórtico — o "
                "efeito das ações laterais não entrou. Rode as combinações "
                "antes, ou use 'Dimensionar vigas', que já as monta")

        feitas[viga.nome] = VerificacaoDeViga(
            viga.nome, list(viga.barras), list(viga.vaos),
            resultado=resultado, viga=deles, portico=conferencia,
            avisos=avisos,
            esforcos=(modelo.calculo.fonte_vigas if externa is not None
                      else "motor"),
            apoiada_em=sorted({a.viga_de_apoio for a in viga.apoios_em_viga}),
            recebe_de=sorted({r.de for r in recebe}))

    return [feitas[v.nome] for v in cadeias]


def _ordem_de_projeto(cadeias: list) -> list:
    """As vigas na ordem em que uma recebe da outra.

    Uma viga só pode ser dimensionada depois de todas as que repousam nela,
    porque é a reação delas que vira a sua carga. Não é a ordem de prioridade:
    quem apoia quem sai de onde o nó cai (dentro dos vãos de quem), e não de
    um ranking. Havendo ciclo — já desfeito em ``continuidade`` —, o resto
    segue na ordem dada em vez de travar.
    """
    nomes = {v.nome for v in cadeias}
    apoiadas_nela: dict[str, set[str]] = {v.nome: set() for v in cadeias}
    for v in cadeias:
        for a in v.apoios_em_viga:
            if a.viga_de_apoio in nomes:
                apoiadas_nela[a.viga_de_apoio].add(v.nome)

    ordem, feitas, restantes = [], set(), list(cadeias)
    while restantes:
        proximas = [v for v in restantes if apoiadas_nela[v.nome] <= feitas]
        if not proximas:
            ordem.extend(restantes)
            break
        for v in proximas:
            ordem.append(v)
            feitas.add(v.nome)
            restantes.remove(v)
    return ordem


def _altura_da_cadeia(modelo: Modelo, viga) -> float:
    secao = modelo.secoes.get(modelo.barras[viga.barras[0]].secao)
    return float(secao.h) * M_PARA_CM if secao is not None else 0.0


def gravar_pranchas_de_vigas(verificacoes: list[VerificacaoDeViga],
                             pasta) -> str | None:
    """Grava o DXF único das vigas dimensionadas — todas lado a lado.

    Separado do cálculo de propósito: dimensionar atualiza os modelos, e
    **imprimir** a prancha é uma decisão à parte. Devolve o caminho, ou
    ``None`` se nenhuma viga passou. Aponta ``desenhos`` de cada viga para o
    arquivo — é uma prancha só, e não um desenho por viga.
    """
    from pathlib import Path

    from .saidas.desenho_unico import montar_dxf_de_vigas

    aprovadas = [v for v in verificacoes if v.passou]
    if not aprovadas:
        return None
    caminho = Path(pasta) / "vigas — desenhos.dxf"
    try:
        montar_dxf_de_vigas([(v.nome, v.resultado) for v in aprovadas],
                            caminho)
    except Exception as erro:                            # noqa: BLE001
        for v in aprovadas:
            v.avisos.append(f"{v.nome}: DXF não gerado ({erro})")
        return None
    for v in aprovadas:
        v.desenhos = [str(caminho)]
    return str(caminho)


def gravar_desenhos(resultado, nome: str, pasta,
                    com_dxf: bool = True, com_png: bool = True) -> list[str]:
    """Grava a elevação e as seções da viga dimensionada, em PNG e em DXF.

    O desenho é o do programa de Vigas — armadura, estribos, cotas e todo o
    detalhamento que ele produz. Aqui só se escolhe onde gravar.

    ``com_png=False`` pula os dois ``savefig`` — que é o render inteiro em
    matplotlib de uma elevação com estribos, cotas e cada barra desenhada — e
    grava só o DXF. Vale para quem consome o desenho como CAD e nunca abre o
    PNG: a prancha única e a ação "Dimensionar vigas" fazem isso, e é a maior
    fatia do tempo que se ganha ao não gerar imagem que ninguém vê.

    **DXF, e não DWG.** O DWG é formato proprietário e fechado da Autodesk; a
    biblioteca que escreve CAD aqui (ezdxf) grava DXF, que é o formato de
    troca publicado e que AutoCAD, BricsCAD, QCAD e afins abrem sem conversão
    nenhuma. Para chegar a DWG é preciso o ODA File Converter, instalado à
    parte, e essa conversão fica de fora deste programa.
    """
    from pathlib import Path

    destino = Path(pasta)
    destino.mkdir(parents=True, exist_ok=True)
    arquivos = []

    if com_png:
        from .elementos.vigas.saidas import desenho

        for figura, sufixo in ((desenho.figura_elevacao(resultado),
                                "elevacao"),
                               (desenho.figura_secoes(resultado), "secoes")):
            caminho = destino / f"{nome} - {sufixo}.png"
            figura.savefig(caminho, dpi=150, facecolor="white",
                          bbox_inches="tight")
            arquivos.append(str(caminho))

    if com_dxf:
        from .elementos.vigas.saidas import dxf
        caminho = destino / f"{nome}.dxf"
        try:
            dxf.exportar(resultado, str(caminho))
            arquivos.append(str(caminho))
        except Exception as erro:                    # noqa: BLE001
            arquivos.append(f"(DXF não gerado: {erro})")
    return arquivos


#: Como cada fonte de esforços aparece nos relatórios.
DESCRICAO_DA_FONTE = {
    "portico": "a envoltória ELU do pórtico (o ELS segue da viga contínua "
               "com g e q)",
    "envolvente": "o pior entre a envoltória do pórtico e a viga contínua",
    "motor": "a viga contínua com g e q (o pórtico só confere)",
}


def resumo_de_vigas(verificacoes: list[VerificacaoDeViga]) -> str:
    """Relatório de lote, uma linha por viga contínua.

    Traz os dois vereditos, porque eles respondem coisas diferentes: o do
    motor de Vigas diz se a peça passa nas verificações da NBR para as cargas
    que recebeu, e o do pórtico diz se a armadura detalhada cobre o que o
    edifício inteiro exige — com vento e desaprumo, que o motor não tem.
    """
    if not verificacoes:
        return "Nenhuma viga contínua com dois ou mais apoios de pilar."

    aprovadas = [v for v in verificacoes if v.aprovado]
    reprovadas = [v for v in verificacoes if v.passou and not v.aprovado]
    sem_veredito = [v for v in verificacoes if not v.passou]

    linhas = [f"Dimensionamento de vigas — {len(verificacoes)} vigas "
              f"contínuas: {len(aprovadas)} aprovadas, "
              f"{len(reprovadas)} reprovadas, "
              f"{len(sem_veredito)} sem veredito"]
    fontes = {v.esforcos for v in verificacoes if v.passou}
    if fontes:
        linhas.append("  armadas com: " + ", ".join(
            DESCRICAO_DA_FONTE[f] for f in sorted(fontes)))
    for v in verificacoes:
        if not v.passou:
            linhas.append(f"  {v.nome}: {v.erro}")
            continue
        vaos = " + ".join(f"{x:.2f}" for x in v.vaos)
        aco = v.resultado.quantitativo.get("massa_total", 0.0)
        relacao = ""
        if v.apoiada_em:
            relacao += f", apoiada em {', '.join(v.apoiada_em)}"
        if v.recebe_de:
            relacao += f", recebe {', '.join(v.recebe_de)}"
        linhas.append(f"  {v.nome}: vãos {vaos} m{relacao}, {aco:.1f} kg de aço"
                      + ("" if v.aprovado else "  — REPROVADA"))
        if not getattr(v.resultado, "ok", True):
            for erro in list(getattr(v.resultado, "avisos", []))[:1]:
                linhas.append(f"    motor: {erro}")
        if v.portico is not None:
            linhas.append(f"    {v.portico}")
    for v in verificacoes:
        for aviso in v.avisos[:1]:
            linhas.append(f"  ! {aviso}")
    return "\n".join(linhas)


@dataclass
class FaixaTrelicada:
    """Uma faixa de laje treliçada: os painéis encadeados na direção das
    nervuras, de viga a viga, e o veredito do motor de Lajes para ela."""

    nome: str
    paineis: list[str]
    laje: object = None              # LajeTrelicada do programa de Lajes
    resultado: object = None         # ResultadoTrelicada
    erro: str = ""

    @property
    def passou(self) -> bool:
        return self.erro == "" and self.resultado is not None

    @property
    def atende(self) -> bool:
        return self.passou and bool(getattr(self.resultado, "atende", False))


@dataclass
class VerificacaoDePavimento:
    """O veredito do programa de Lajes para um pavimento inteiro.

    ``resultado`` é o das lajes **maciças** (o ``ResultadoPavimento``), ou
    ``None`` quando o pavimento só tem treliçada; ``trelicadas`` traz as
    faixas treliçadas, cada uma com o seu veredito.
    """

    cota: float
    paineis: list[str]
    resultado: object = None
    pavimento: object = None
    continuidades: int = 0
    erro: str = ""
    desenhos: list[str] = field(default_factory=list)
    trelicadas: list[FaixaTrelicada] = field(default_factory=list)

    @property
    def passou(self) -> bool:
        return self.erro == "" and (self.resultado is not None
                                    or bool(self.trelicadas))

    @property
    def erros(self) -> list:
        """Os erros do pavimento: os das maciças e os das faixas treliçadas.
        O ``ResultadoPavimento`` não tem ``ok`` — o veredito é a lista
        vazia."""
        saida = list(self.resultado.erros) if self.resultado is not None \
            else []
        for f in self.trelicadas:
            if not f.passou:
                saida.append(f"treliçada {f.nome}: {f.erro}")
            else:
                saida += [f"treliçada {f.nome}: {t}"
                          for c, t in f.resultado.avisos if c == "erro"]
        return saida

    @property
    def aprovado(self) -> bool:
        return self.passou and not self.erros


def _largura_das_vigas(modelo: Modelo, laje) -> list[float]:
    """Largura, em cm, de cada viga de contorno do painel, na ordem dos bordos."""
    from .core.lajes import arestas_da_laje

    arestas, _, _ = arestas_da_laje(modelo, laje)
    larguras = []
    for aresta in arestas:
        bs = [modelo.secoes[modelo.barras[n].secao].b for n in aresta.barras]
        b = max(bs)
        larguras.append(b * M_PARA_CM if b > 0.0 else 20.0)
    return larguras


def montar_pavimento(modelo: Modelo, cota: float, fck: float | None = None):
    """Monta o ``Pavimento`` do programa de Lajes com os painéis de uma cota.

    Duas escolhas de tradução que mudam o resultado, e por isso ficam à vista:

    **Os vãos são os livres, não os de eixo a eixo.** O painel do pórtico é
    definido por nós, que estão nos eixos das vigas; o programa de Lajes espera
    o vão livre e a largura do apoio, e monta o vão efetivo do item 14.7.2.2 a
    partir dos dois. Passar eixo a eixo daria uma laje maior do que ela é.

    **A continuidade quem detecta é ele.** ``Pavimento.detectar_continuidades``
    acha as bordas comuns pela posição em planta, e é dele que sai a
    compatibilização do item 14.7.6.2 — as duas lajes recebendo **uma** armadura
    negativa. Por isso o pavimento vai inteiro, e não painel a painel: painel
    sozinho não tem com quem compatibilizar.
    """
    from .core.lajes import _cantos
    from .elementos.lajes.core import modelo as ml

    # Só as maciças: a treliçada vai por faixa (``faixas_trelicadas``).
    paineis = [l for l in modelo.lajes.values()
               if abs(modelo.ponto(l.no_a)[2] - cota) < 1e-6
               and not l.trelicada]
    if not paineis:
        raise ErroDeModelo(f"não há laje maciça na cota {cota:.3f} m")

    classe = fck
    lajes = []
    for laje in paineis:
        material = modelo.materiais.get(laje.material)
        if classe is None and material is not None and material.fck > 0.0:
            classe = material.fck
        if laje.em_balanco:
            lajes.append(_laje_em_balanco(modelo, laje, ml))
            continue
        cantos, lx, ly = _cantos(modelo, laje)
        larguras = _largura_das_vigas(modelo, laje)
        # Bordos 1 e 3 correm ao longo de X; 2 e 4 ao longo de Y. O vão livre
        # desconta meia largura da viga de cada lado.
        livre_x = lx - (larguras[1] + larguras[3]) / 2.0 / M_PARA_CM
        livre_y = ly - (larguras[0] + larguras[2]) / 2.0 / M_PARA_CM
        canto = modelo.ponto(cantos[0])

        deles = ml.Laje(
            nome=laje.nome, a=livre_x, b=livre_y,
            h=max(laje.espessura, 0.01) * M_PARA_CM,
            x=float(canto[0]) + larguras[3] / 2.0 / M_PARA_CM,
            y=float(canto[1]) + larguras[0] / 2.0 / M_PARA_CM,
            orientacao="X" if livre_x >= livre_y else "Y",
            bordos=[ml.Bordo(vinculo="apoiado") for _ in range(4)],
            permanente_extra=laje.permanente, variavel=laje.acidental)
        # A largura de cada bordo vai **pela face que ele ocupa**. As
        # larguras saem na ordem das arestas (embaixo, à direita, em cima, à
        # esquerda), e o programa de Lajes numera os bordos pela orientação
        # da laje — na orientação Y o bordo 2 é a esquerda. Passar a lista
        # na ordem das arestas punha a viga da direita no bordo da esquerda.
        por_face = {"baixo": larguras[0], "direita": larguras[1],
                    "cima": larguras[2], "esquerda": larguras[3]}
        for k, bordo in enumerate(deles.bordos, start=1):
            bordo.t = por_face[deles.face_do_bordo(k)]
        lajes.append(deles)

    if classe is None or classe <= 0.0:
        raise ErroDeModelo(
            f"as lajes da cota {cota:.3f} m não declaram material com fck; "
            "defina-o como concreto por classe, ou informe o fck")

    pav = ml.Pavimento(nome=f"Cota {cota:g} m", lajes=lajes,
                       concreto=ml.Concreto(fck=classe))
    # Detectar não basta: ``aplicar_continuidades`` é o que engasta os bordos
    # e anota a vizinha, que é do que o cálculo por tabelas precisa. Só
    # detectar deixaria os bordos apoiados, e o próprio programa de Lajes
    # acusa a incoerência — foi assim que este passo apareceu.
    # A laje em balanço só se engasta pelo lado apoiado. Duas em balanço lado
    # a lado — a sacada partida onde uma viga chega por dentro — encostam
    # pela borda lateral, que é livre: a placa é contínua ali, mas cada uma
    # trabalha em balanço na direção do vão, e essa continuidade não é
    # engaste para ela. Engastada também pelo lado, ela deixaria de ser
    # balanço para o programa de Lajes (dois bordos engastados e dois
    # livres), e sairia calculada como laje de canto.
    apoiado = {"+y": "baixo", "-y": "cima", "+x": "esquerda",
               "-x": "direita"}
    sentidos = {l.nome: l.sentido for l in paineis if l.em_balanco}

    def pelo_lado_apoiado(c) -> bool:
        for nome, bordo in ((c.laje_a, c.bordo_a), (c.laje_b, c.bordo_b)):
            if nome in sentidos and pav.laje(nome).face_do_bordo(bordo) \
                    != apoiado[sentidos[nome]]:
                return False
        return True

    pav.aplicar_continuidades([c for c in pav.detectar_continuidades()
                               if pelo_lado_apoiado(c)])
    # A laje em balanço só existe engastada na laje de dentro: é ali que o
    # momento dela se equilibra (o pórtico não põe torção na viga — ver
    # ``core.lajes._distribuir_balanco``). Sem vizinha contínua, ou com uma
    # que não fecha engaste (espessuras diferentes demais, contato parcial),
    # o balanço ficaria sem engaste nenhum.
    for laje in paineis:
        if not laje.em_balanco:
            continue
        deles = pav.laje(laje.nome)
        if deles is None or not deles.em_balanco:
            raise ErroDeModelo(
                f"laje {laje.nome}: em balanço sem laje contínua do outro "
                "lado da viga de apoio — o engaste dela dependeria da torção "
                "da viga, que este programa ainda não carrega. Lance a laje "
                "de dentro com a mesma espessura (até 2 cm de diferença) ao "
                "longo de pelo menos 2/3 do lado apoiado")
    return pav


def _laje_em_balanco(modelo: Modelo, laje, ml):
    """A laje em balanço no formato do programa de Lajes.

    O retângulo é o dos **vãos livres**, como nas outras: do balanço sai
    meia largura da viga de apoio (o vão livre vai da face da viga à borda;
    o programa de Lajes soma 0,3·h no engaste, 14.7.2.2), e ao longo do lado
    apoiado sai meia largura das vigas que chegam nas duas pontas — as
    mesmas que limitam a laje de dentro, para que a borda comum coincida e a
    continuidade seja detectada. Os quatro bordos entram livres; o do lado
    apoiado vira engastado na continuidade com a laje de dentro.
    """
    from .core.lajes import arestas_da_laje, retangulo

    arestas, _, _ = arestas_da_laje(modelo, laje)
    t = max(modelo.secoes[modelo.barras[n].secao].b
            for n in arestas[0].barras) * M_PARA_CM
    t = t if t > 0.0 else 20.0
    x0, y0, x1, y1, _ = retangulo(modelo, laje)
    em_x = laje.sentido[1] == "y"      # o lado apoiado corre em X

    def meia_perpendicular(no: str) -> float:
        """Meia largura, m, da viga que chega à ponta do lado apoiado
        perpendicular a ele (a que fecha a laje de dentro)."""
        from .continuidade import _eh_vertical
        maior = 0.0
        p = modelo.ponto(no)
        for nome, b in modelo.barras.items():
            if no not in (b.no_i, b.no_j) or _eh_vertical(modelo, b):
                continue
            outro = modelo.ponto(b.no_j if b.no_i == no else b.no_i)
            d = outro - p
            ao_longo = abs(d[0]) if em_x else abs(d[1])
            if ao_longo < 1e-6:            # perpendicular ao lado apoiado
                maior = max(maior, modelo.secoes[b.secao].b / 2.0)
        return maior

    a, c = modelo.ponto(laje.no_a), modelo.ponto(laje.no_c)
    (n0, n1) = ((laje.no_a, laje.no_c) if (a[0] if em_x else a[1])
                <= (c[0] if em_x else c[1]) else (laje.no_c, laje.no_a))
    meia_t = t / 2.0 / M_PARA_CM
    if em_x:
        x0, x1 = x0 + meia_perpendicular(n0), x1 - meia_perpendicular(n1)
        if laje.sentido == "+y":
            y0 += meia_t
        else:
            y1 -= meia_t
    else:
        y0, y1 = y0 + meia_perpendicular(n0), y1 - meia_perpendicular(n1)
        if laje.sentido == "+x":
            x0 += meia_t
        else:
            x1 -= meia_t
    livre_x, livre_y = x1 - x0, y1 - y0
    if livre_x <= 0.0 or livre_y <= 0.0:
        raise ErroDeModelo(
            f"laje {laje.nome}: o balanço de {laje.balanco:g} m não passa da "
            f"face da viga de apoio ({t:g} cm de largura)")
    # ``destino = "balanco"`` não é só rótulo no programa de Lajes: é por ele
    # que a negativa da borda comum vai até a ponta livre (a única armadura
    # do balanço, ``compatibilizacao._extensao``) e que vale o h mínimo de
    # 10 cm do 13.2.4.1. Os vínculos sozinhos não bastam — sem o destino, a
    # negativa parava a um quarto do vão, antes da borda.
    # O bordo do lado apoiado entra "apoiado" e os outros três livres: desde
    # a R12 o programa de Lajes só aceita continuidade no bordo de um
    # balanço que não é livre (``Laje.aceita_continuidade``), e é a
    # continuidade com a laje de dentro que o engasta.
    deles = ml.Laje(
        nome=laje.nome, a=livre_x, b=livre_y, destino="balanco",
        h=max(laje.espessura, 0.01) * M_PARA_CM, x=x0, y=y0,
        orientacao="X" if livre_x >= livre_y else "Y",
        bordos=[ml.Bordo(vinculo="livre", t=t) for _ in range(4)],
        permanente_extra=laje.permanente, variavel=laje.acidental)
    face = {"+y": "baixo", "-y": "cima", "+x": "esquerda",
            "-x": "direita"}[laje.sentido]
    for k, bordo in enumerate(deles.bordos, start=1):
        if deles.face_do_bordo(k) == face:
            bordo.vinculo = "apoiado"
    return deles


def faixas_trelicadas(modelo: Modelo, cota: float, fck: float | None = None
                      ) -> list[FaixaTrelicada]:
    """As faixas treliçadas de uma cota, montadas para o programa de Lajes.

    Uma faixa é a nervura contínua: os painéis treliçados com a mesma
    direção de nervura, a mesma seção (treliça, enchimento, capa, bloco e
    base) e a mesma largura transversal, encostados um no outro na direção
    das nervuras — cada encontro é uma viga, que vira apoio intermediário.
    Os vãos são de eixo a eixo das vigas, como o programa de Lajes pede, e a
    largura de cada apoio é a da viga que o forma.
    """
    from .core.lajes import arestas_da_laje
    from .elementos.lajes.core import trelicada_modelo as tm

    paineis = [l for l in modelo.lajes.values()
               if l.trelicada and abs(modelo.ponto(l.no_a)[2] - cota) < 1e-6]
    grupos: dict[tuple, list] = {}
    for laje in paineis:
        a, c = modelo.ponto(laje.no_a), modelo.ponto(laje.no_c)
        x0, x1 = sorted((float(a[0]), float(c[0])))
        y0, y1 = sorted((float(a[1]), float(c[1])))
        ao_longo, transversal = ((x0, x1), (y0, y1)) if laje.direcao == "x" \
            else ((y0, y1), (x0, x1))
        chave = (laje.direcao, round(transversal[0], 6),
                 round(transversal[1], 6), laje.trelica, laje.enchimento,
                 round(laje.altura_enchimento, 6), round(laje.capa, 6),
                 round(laje.largura_bloco, 6), round(laje.base_vigota, 6),
                 laje.material)
        grupos.setdefault(chave, []).append((ao_longo, laje))

    def largura_da_viga(aresta) -> float:
        """A largura do apoio, cm: a menor das barras do lado — é por ela que
        a vigota ancora."""
        b = min(modelo.secoes[modelo.barras[n].secao].b
                for n in aresta.barras)
        return b * M_PARA_CM if b > 0.0 else 20.0

    faixas = []
    for chave, lista in grupos.items():
        lista.sort(key=lambda par: par[0][0])
        cadeias, atual = [], [lista[0]]
        for par in lista[1:]:
            if abs(par[0][0] - atual[-1][0][1]) < 1e-6:
                atual.append(par)
            else:
                cadeias.append(atual)
                atual = [par]
        cadeias.append(atual)

        direcao, t0, t1 = chave[0], chave[1], chave[2]
        for cadeia in cadeias:
            lajes = [l for _, l in cadeia]
            nome = "+".join(l.nome for l in lajes)
            try:
                # arestas: 0 embaixo, 1 à direita, 2 em cima, 3 à esquerda
                ini, fim = (3, 1) if direcao == "x" else (0, 2)
                apoios_t = [largura_da_viga(
                    arestas_da_laje(modelo, lajes[0])[0][ini])]
                for l in lajes:
                    apoios_t.append(largura_da_viga(
                        arestas_da_laje(modelo, l)[0][fim]))
                primeira = lajes[0]
                material = modelo.materiais.get(primeira.material)
                lt = tm.LajeTrelicada(
                    nome=nome,
                    base=primeira.base_vigota * M_PARA_CM,
                    largura_bloco=primeira.largura_bloco * M_PARA_CM,
                    altura_enchimento=primeira.altura_enchimento * M_PARA_CM,
                    capa=primeira.capa * M_PARA_CM,
                    enchimento=primeira.enchimento,
                    trelica=primeira.trelica,
                    # A vigota entra na viga o que a viga dá: a largura dela
                    # menos o cobrimento do outro lado (o padrão do motor,
                    # 5 cm, fica como piso). É a entrada que ancora o
                    # positivo no apoio.
                    apoio_vigota=max(5.0, min(apoios_t) - 3.0),
                    largura_laje=t1 - t0,
                    vaos=[tm.VaoTrelicado(L=(fim_ - ini_) * M_PARA_CM,
                                          g=l.permanente, q=l.acidental)
                          for (ini_, fim_), l in cadeia],
                    apoios=[tm.ApoioTrelicado(t=t) for t in apoios_t])
                faixas.append(FaixaTrelicada(nome, [l.nome for l in lajes],
                                             laje=lt))
                faixas[-1].fck = (fck if fck is not None else
                                  (material.fck if material else 0.0))
                faixas[-1].peso_especifico = (material.peso_especifico
                                              if material else 25.0)
            except (ErroDeModelo, ValueError, KeyError) as erro:
                faixas.append(FaixaTrelicada(nome, [l.nome for l in lajes],
                                             erro=str(erro)))
    return faixas


def dimensionar_faixa(faixa: FaixaTrelicada) -> FaixaTrelicada:
    """Roda o motor de laje treliçada do programa de Lajes na faixa."""
    from .elementos.lajes.core.materiais import Ambiente, Concreto
    from .elementos.lajes.core.trelicada import dimensionar_trelicada

    if faixa.erro or faixa.laje is None:
        return faixa
    fck = getattr(faixa, "fck", 0.0)
    if fck <= 0.0:
        faixa.erro = "o material da laje não declara fck"
        return faixa
    try:
        concreto = Concreto(fck=fck, peso_especifico=getattr(
            faixa, "peso_especifico", 25.0))
        faixa.resultado = dimensionar_trelicada(faixa.laje, concreto,
                                                Ambiente())
    except (ValueError, ZeroDivisionError, KeyError, IndexError) as erro:
        faixa.erro = str(erro)
    return faixa


def cotas_com_laje(modelo: Modelo) -> list[float]:
    return sorted({round(float(modelo.ponto(l.no_a)[2]), 6)
                   for l in modelo.lajes.values()})


def verificar_lajes(modelo: Modelo, pasta_desenhos=None,
                    fck: float | None = None) -> list[VerificacaoDePavimento]:
    """Dimensiona as lajes de cada pavimento e grava os desenhos."""
    from .elementos.lajes.core.dimensionar import dimensionar

    saida = []
    for cota in cotas_com_laje(modelo):
        no_nivel = [l for l in modelo.lajes.values()
                    if abs(modelo.ponto(l.no_a)[2] - cota) < 1e-6]
        paineis = [l.nome for l in no_nivel]
        faixas = [dimensionar_faixa(f)
                  for f in faixas_trelicadas(modelo, cota, fck)]
        if not any(not l.trelicada for l in no_nivel):
            saida.append(VerificacaoDePavimento(cota, paineis,
                                                trelicadas=faixas))
            continue
        try:
            pav = montar_pavimento(modelo, cota, fck)
            resultado = dimensionar(pav)
        except (ErroDeModelo, ValueError, ZeroDivisionError, KeyError) as e:
            saida.append(VerificacaoDePavimento(cota, paineis, erro=str(e),
                                                trelicadas=faixas))
            continue

        v = VerificacaoDePavimento(cota, paineis, resultado=resultado,
                                   pavimento=pav,
                                   continuidades=len(pav.continuidades),
                                   trelicadas=faixas)
        saida.append(v)
    if pasta_desenhos is not None:
        gravar_pranchas_de_lajes(saida, pasta_desenhos)
    return saida


def gravar_pranchas_de_lajes(verificacoes: list[VerificacaoDePavimento],
                             pasta) -> list[str]:
    """Grava as plantas de armação dos pavimentos já dimensionados.

    Dimensionar atualiza os modelos; imprimir é uma decisão à parte, e é aqui.
    """
    arquivos = []
    for v in verificacoes:
        if not v.passou or v.resultado is None:
            continue
        v.desenhos = gravar_desenhos_de_laje(v.resultado, v.cota, pasta)
        arquivos.extend(v.desenhos)
    return arquivos


def gravar_desenhos_de_laje(resultado, cota: float, pasta,
                            com_dxf: bool = True) -> list[str]:
    """Grava as plantas de armadura positiva e negativa, em PNG e em DXF."""
    from pathlib import Path

    from .elementos.lajes.saidas import desenho

    destino = Path(pasta)
    destino.mkdir(parents=True, exist_ok=True)
    rotulo = f"Lajes cota {cota:g}m".replace(".", ",")
    arquivos = []
    for funcao, sufixo in ((desenho.figura_armadura_positiva, "positiva"),
                           (desenho.figura_armadura_negativa, "negativa")):
        try:
            figura = funcao(resultado)
        except (ValueError, KeyError, IndexError):
            continue
        caminho = destino / f"{rotulo} - {sufixo}.png"
        figura.savefig(caminho, dpi=150, facecolor="white",
                       bbox_inches="tight")
        arquivos.append(str(caminho))

    if com_dxf:
        from .elementos.lajes.saidas import dxf
        caminho = destino / f"{rotulo}.dxf"
        try:
            dxf.exportar(resultado, str(caminho))
            arquivos.append(str(caminho))
        except Exception as erro:                    # noqa: BLE001
            arquivos.append(f"(DXF não gerado: {erro})")
    return arquivos


def resumo_de_lajes(verificacoes: list[VerificacaoDePavimento]) -> str:
    if not verificacoes:
        return "O modelo não tem lajes."

    linhas = [f"Dimensionamento de lajes — {len(verificacoes)} pavimentos"]
    for v in verificacoes:
        for f in v.trelicadas:
            if not f.passou:
                linhas.append(f"  cota {v.cota:g} m, treliçada {f.nome}: "
                              f"{f.erro}")
                continue
            q = f.resultado.quantitativo or {}
            erros = [t for c, t in f.resultado.avisos if c == "erro"]
            linhas.append(
                f"  cota {v.cota:g} m, treliçada {f.nome}: "
                f"{len(f.laje.vaos)} vão(s), {f.laje.trelica}, h = "
                f"{f.laje.h:.0f} cm, {q.get('aco_kg', 0.0):.1f} kg de aço"
                f" — {'OK' if f.atende else f'{len(erros)} erro(s)'}")
            for erro in erros[:2]:
                linhas.append(f"    erro: {erro}")
        if not v.passou:
            linhas.append(f"  cota {v.cota:g} m: {v.erro}")
            continue
        if v.resultado is None:
            continue
        # O ``ResultadoPavimento`` não tem um ``ok``: o veredito é a lista de
        # erros estar vazia. Perguntar por um campo que não existe devolveria
        # sempre "com ressalva", e o relatório mentiria sem falhar.
        erros = list(v.resultado.erros)
        avisos = [a for a in v.resultado.todos_avisos if not a.erro]
        situacao = ("OK" if not erros
                    else f"{len(erros)} erro(s)")
        linhas.append(
            f"  cota {v.cota:g} m: {len(v.paineis)} painéis, "
            f"{v.continuidades} bordas contínuas, área "
            f"{v.resultado.area_total:.1f} m² — {situacao}"
            + (f", {len(avisos)} aviso(s)" if avisos else ""))
        for erro in erros[:2]:
            linhas.append(f"    erro: {getattr(erro, 'texto', erro)}")
        for arquivo in v.desenhos:
            linhas.append(f"    desenho: {arquivo}")
    return "\n".join(linhas)


def resumo(verificacoes: list[VerificacaoDePilar]) -> str:
    """Relatório de lote, uma linha por lance verificado."""
    if not verificacoes:
        return "Nenhum pilar verificado."

    por_barra: dict[str, list[VerificacaoDePilar]] = {}
    for v in verificacoes:
        por_barra.setdefault(v.barra, []).append(v)

    linhas = [f"Dimensionamento de pilares — {len(por_barra)} lances, "
              f"{len(verificacoes)} combinações"]
    for barra, lista in por_barra.items():
        falhas = [v for v in lista if not v.passou]
        reprovadas = [v for v in lista if v.passou and not v.aprovado]
        estado = f"  {barra}: {len(lista)} combinações"
        if falhas:
            estado += f", {len(falhas)} sem veredito"
        if reprovadas:
            estado += f", {len(reprovadas)} REPROVADAS"
        linhas.append(estado)
        pior = max((v for v in lista if v.aprovado),
                   key=lambda v: v.esforcos.Nd, default=None)
        if pior is not None:
            linhas.append(f"    mais comprimida — {pior.esforcos}")
        elif not falhas:
            linhas.append("    nenhuma combinação foi aprovada")
        for v in falhas[:1]:
            linhas.append(f"    {v.combinacao}: {v.erro}")
        for v in reprovadas[:1]:
            for motivo in v.motivos[:1]:
                linhas.append(f"    {v.combinacao}: {motivo}")
    return "\n".join(linhas)
