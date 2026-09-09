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
    from .elementos.pilares.core.dimensionar import dimensionar

    alvos = barras if barras is not None else barras_verticais(modelo)
    saida = []
    for barra in alvos:
        if barra not in envoltorias:
            continue
        for esforcos in esforcos_do_lance(modelo, envoltorias[barra], barra):
            try:
                pilar = montar_pilar(modelo, barra, esforcos, fck)
                resultado = dimensionar(pilar)
            except (ErroDeModelo, ValueError, ZeroDivisionError) as erro:
                saida.append(VerificacaoDePilar(barra, esforcos.combinacao,
                                                esforcos, erro=str(erro)))
                continue
            saida.append(VerificacaoDePilar(barra, esforcos.combinacao,
                                            esforcos, resultado=resultado))
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


def rigidez_dos_pilares(modelo: Modelo, viga, indice: int) -> float:
    """Rigidez à rotação que os pilares dão à viga naquele apoio, kN·m/rad.

    É a peça que faltava. O programa de Vigas **já previa** isto — o seu
    ``Apoio`` tem o tipo ``mola`` com ``k_mola``, e o próprio docstring dele
    diz "útil para representar a rigidez dos pilares" —, e a ponte vinha
    passando ``simples``, jogando fora a solidariedade viga-pilar que o
    pórtico conhece. É o modelo simplificado de viga contínua da NBR 6118:
    apoio que não é rótula, e sim mola com a rigidez dos lances que chegam.

    A conta é a clássica ``4EI/ℓ`` somada sobre os lances que chegam ao nó, de
    baixo e de cima. O que exige cuidado é **qual** inércia: o pilar resiste
    girando no plano vertical que contém a viga, e a inércia que vale é a do
    eixo horizontal perpendicular a esse plano. Decompondo esse eixo nos eixos
    locais do lance,

        k = 4E/ℓ · (Iy·(n·ey)² + Iz·(n·ez)²),   n = versor(direção × ẑ)

    o que, no caso corrente — viga em X, pilar prumado —, dá ``4E·Iz/ℓ``, com
    Iz medindo a dimensão do pilar **na direção da viga**. É o resultado que se
    espera: pilar 20×60 com os 60 cm no rumo da viga trava muito mais que o
    mesmo pilar virado.
    """
    from .continuidade import _eh_vertical

    if indice >= len(viga.apoios):
        return 0.0
    no = viga.nos[viga.apoios[indice]]
    direcao = np.array(viga.direcao, dtype=float)
    n = np.cross(direcao, np.array([0.0, 0.0, 1.0]))
    norma = float(np.linalg.norm(n))
    if norma < 1e-9:                       # viga vertical não existe aqui
        return 0.0
    n = n / norma

    from .core.montagem import preparar_barras
    preparadas = preparar_barras(modelo)

    k = 0.0
    for nome, barra in modelo.barras.items():
        if not _eh_vertical(modelo, barra) or no not in (barra.no_i, barra.no_j):
            continue
        secao = modelo.secoes.get(barra.secao)
        material = modelo.materiais.get(barra.material)
        comprimento = modelo.comprimento(nome)
        if secao is None or material is None or comprimento <= 0.0:
            continue
        p = preparadas.get(nome)
        if p is None:
            continue
        ey, ez = p.R[1], p.R[2]
        inercia = secao.Iy * float(n @ ey) ** 2 + secao.Iz * float(n @ ez) ** 2
        k += 4.0 * material.E * inercia / comprimento
    return k


def montar_viga(modelo: Modelo, viga, casos: dict[str, str] | None = None,
                fck: float | None = None, molas: bool = True,
                avisos: list | None = None):
    """Monta a ``Viga`` do outro programa a partir da cadeia detectada.

    ``molas`` liga a rigidez dos pilares nos apoios — ver
    :func:`rigidez_dos_pilares`. ``avisos``, quando dado, recebe o que a
    tradução tem a dizer sem que isso interrompa o lote."""
    from .elementos.vigas.core import modelo as mv

    if len(viga.apoios) < 2:
        raise ErroDeModelo(
            f"{viga.nome}: a cadeia tem {len(viga.apoios)} apoio(s) de pilar. "
            "Sem dois apoios não há viga contínua a dimensionar — é viga "
            "apoiada em outras vigas, e o pórtico já a resolveu")

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
    if viga.balanco_inicial > 1e-9:
        tramos.append(mv.Tramo(L=viga.balanco_inicial, secao=secao_deles))
        apoios.append(mv.Apoio(tipo="livre"))
    # ``i`` conta os apoios **de pilar**, e não as entradas da lista: com
    # balanço inicial a lista já começa com um "livre", e usar o tamanho dela
    # como índice pegava a largura do pilar seguinte.
    for i, vao in enumerate(viga.vaos):
        tramos.append(mv.Tramo(L=vao, secao=secao_deles))
        apoios.append(_apoio_de_pilar(modelo, viga, i, molas, secao_deles))
    if viga.balanco_final > 1e-9:
        tramos.append(mv.Tramo(L=viga.balanco_final, secao=secao_deles))
        apoios.append(mv.Apoio(tipo="livre"))
    else:
        apoios.append(_apoio_de_pilar(modelo, viga, len(viga.vaos), molas,
                                      secao_deles))

    # A origem da viga do outro programa é o primeiro apoio, não a ponta do
    # balanço; a coordenada das cargas segue a mesma origem.
    deslocamento = 0.0 if viga.balanco_inicial > 1e-9 else -0.0
    cargas = _cargas_da_viga(modelo, viga, casos)
    for c in cargas:
        c.x_ini += deslocamento
        c.x_fim += deslocamento

    deles = mv.Viga(nome=viga.nome, tramos=tramos, apoios=apoios,
                    distribuidas=cargas, concreto=mv.Concreto(fck=classe))

    # **O peso próprio já veio do pórtico.** O motor de Vigas gera o dele
    # sozinho (``Config.peso_proprio``), e como a ponte repassa todas as
    # distribuídas do caso permanente — inclusive as que ``peso_proprio``
    # criou lá atrás —, deixá-lo ligado somava a mesma carga duas vezes. Na
    # viga 20×50 do exemplo isso dava 2,5 kN/m sobre 10,4 kN/m: 24 % a mais
    # de carga permanente, que ninguém veria na memória de cálculo.
    deles.config.peso_proprio = False
    _conferir_peso_proprio(modelo, viga, deles, secao, avisos)

    return deles


def _apoio_de_pilar(modelo: Modelo, viga, indice: int, molas: bool, secao):
    """O apoio de pilar, com a rigidez à rotação quando ela é conhecida."""
    from .elementos.vigas.core import modelo as mv

    largura = _largura_do_pilar(modelo, viga, indice)
    if not molas:
        return mv.Apoio(tipo="simples", largura=largura)
    k = rigidez_dos_pilares(modelo, viga, indice)
    if k <= 0.0:
        return mv.Apoio(tipo="simples", largura=largura)
    return mv.Apoio(tipo="mola", largura=largura, k_mola=k)


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


def _largura_do_pilar(modelo: Modelo, viga, indice: int) -> float:
    """Largura do pilar que apoia a viga naquele nó, em cm."""
    from .continuidade import _eh_vertical

    if indice >= len(viga.apoios):
        return 20.0
    no = viga.nos[viga.apoios[indice]]
    for barra in modelo.barras.values():
        if _eh_vertical(modelo, barra) and no in (barra.no_i, barra.no_j):
            secao = modelo.secoes[barra.secao]
            if secao.b > 0.0:
                return secao.b * M_PARA_CM
    return 20.0


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


def _As_para(momento: float, deles, resultado) -> float:
    """Área de aço para o momento dado, pela flexão do próprio motor.

    Usa a mesma função, a mesma seção e o mesmo ``d`` do dimensionamento, de
    modo que a diferença entre o exigido e o obtido seja **só** a solicitação.
    """
    from .elementos.vigas.core import flexao as fl

    if abs(momento) < 1e-9:
        return 0.0
    secao = deles.tramos[0].secao
    cob = deles.ambiente.cobrimento_nominal
    d_linha = cob + deles.config.phi_estribo / 10.0 + 1.0
    try:
        res = fl.dimensionar(secao, deles.concreto, deles.aco, abs(momento),
                             d_linha, d_linha, delta=1.0)
    except (ValueError, ZeroDivisionError):
        return float("inf")
    return float(res.As_adotado + max(getattr(res, "As_linha", 0.0), 0.0))


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
            As_e = _As_para(exigido, deles, resultado)
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
    """
    from .continuidade import vigas_continuas
    from .elementos.vigas.core.dimensionar import dimensionar

    saida = []
    for viga in vigas_continuas(modelo):
        if len(viga.apoios) < 2:
            continue
        avisos: list[str] = []
        try:
            deles = montar_viga(modelo, viga, fck=fck, avisos=avisos)
            resultado = dimensionar(deles)
        except (ErroDeModelo, ValueError, ZeroDivisionError, IndexError) as e:
            saida.append(VerificacaoDeViga(viga.nome, list(viga.barras),
                                           list(viga.vaos), erro=str(e),
                                           avisos=avisos))
            continue

        conferencia = None
        if envoltorias:
            conferencia = conferir_contra_o_portico(
                modelo, viga, resultado, deles, envoltorias)
        else:
            avisos.append(
                f"{viga.nome}: dimensionada sem a envoltória do pórtico — o "
                "efeito das ações laterais não entrou. Rode as combinações "
                "antes, ou use 'Dimensionar vigas', que já as monta")

        v = VerificacaoDeViga(viga.nome, list(viga.barras), list(viga.vaos),
                              resultado=resultado, viga=deles,
                              portico=conferencia, avisos=avisos)
        if pasta_desenhos is not None:
            v.desenhos = gravar_desenhos(resultado, viga.nome, pasta_desenhos)
        saida.append(v)
    return saida


def gravar_desenhos(resultado, nome: str, pasta,
                    com_dxf: bool = True) -> list[str]:
    """Grava a elevação e as seções da viga dimensionada, em PNG e em DXF.

    O desenho é o do programa de Vigas — armadura, estribos, cotas e todo o
    detalhamento que ele produz. Aqui só se escolhe onde gravar.

    **DXF, e não DWG.** O DWG é formato proprietário e fechado da Autodesk; a
    biblioteca que escreve CAD aqui (ezdxf) grava DXF, que é o formato de
    troca publicado e que AutoCAD, BricsCAD, QCAD e afins abrem sem conversão
    nenhuma. Para chegar a DWG é preciso o ODA File Converter, instalado à
    parte, e essa conversão fica de fora deste programa.
    """
    from pathlib import Path

    from .elementos.vigas.saidas import desenho

    destino = Path(pasta)
    destino.mkdir(parents=True, exist_ok=True)
    arquivos = []
    for figura, sufixo in ((desenho.figura_elevacao(resultado), "elevacao"),
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
    for v in verificacoes:
        if not v.passou:
            linhas.append(f"  {v.nome}: {v.erro}")
            continue
        vaos = " + ".join(f"{x:.2f}" for x in v.vaos)
        aco = v.resultado.quantitativo.get("massa_total", 0.0)
        linhas.append(f"  {v.nome}: vãos {vaos} m, {aco:.1f} kg de aço"
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
class VerificacaoDePavimento:
    """O veredito do programa de Lajes para um pavimento inteiro."""

    cota: float
    paineis: list[str]
    resultado: object = None
    pavimento: object = None
    continuidades: int = 0
    erro: str = ""
    desenhos: list[str] = field(default_factory=list)

    @property
    def passou(self) -> bool:
        return self.erro == "" and self.resultado is not None


def _largura_das_vigas(modelo: Modelo, laje) -> list[float]:
    """Largura, em cm, de cada viga de contorno do painel, na ordem dos bordos."""
    from .core.lajes import arestas_da_laje

    arestas, _, _ = arestas_da_laje(modelo, laje)
    larguras = []
    for aresta in arestas:
        secao = modelo.secoes[modelo.barras[aresta.barra].secao]
        larguras.append(secao.b * M_PARA_CM if secao.b > 0.0 else 20.0)
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

    paineis = [l for l in modelo.lajes.values()
               if abs(modelo.ponto(l.no_a)[2] - cota) < 1e-6]
    if not paineis:
        raise ErroDeModelo(f"não há laje na cota {cota:.3f} m")

    classe = fck
    lajes = []
    for laje in paineis:
        cantos, lx, ly = _cantos(modelo, laje)
        larguras = _largura_das_vigas(modelo, laje)
        # Bordos 1 e 3 correm ao longo de X; 2 e 4 ao longo de Y. O vão livre
        # desconta meia largura da viga de cada lado.
        livre_x = lx - (larguras[1] + larguras[3]) / 2.0 / M_PARA_CM
        livre_y = ly - (larguras[0] + larguras[2]) / 2.0 / M_PARA_CM
        canto = modelo.ponto(cantos[0])

        material = modelo.materiais.get(laje.material)
        if classe is None and material is not None and material.fck > 0.0:
            classe = material.fck

        bordos = [ml.Bordo(vinculo="apoiado", t=t) for t in larguras]
        lajes.append(ml.Laje(
            nome=laje.nome, a=livre_x, b=livre_y,
            h=max(laje.espessura, 0.01) * M_PARA_CM,
            x=float(canto[0]) + larguras[3] / 2.0 / M_PARA_CM,
            y=float(canto[1]) + larguras[0] / 2.0 / M_PARA_CM,
            orientacao="X" if livre_x >= livre_y else "Y",
            bordos=bordos, permanente_extra=laje.permanente,
            variavel=laje.acidental))

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
    pav.aplicar_continuidades(pav.detectar_continuidades())
    return pav


def cotas_com_laje(modelo: Modelo) -> list[float]:
    return sorted({round(float(modelo.ponto(l.no_a)[2]), 6)
                   for l in modelo.lajes.values()})


def verificar_lajes(modelo: Modelo, pasta_desenhos=None,
                    fck: float | None = None) -> list[VerificacaoDePavimento]:
    """Dimensiona as lajes de cada pavimento e grava os desenhos."""
    from .elementos.lajes.core.dimensionar import dimensionar

    saida = []
    for cota in cotas_com_laje(modelo):
        paineis = [l.nome for l in modelo.lajes.values()
                   if abs(modelo.ponto(l.no_a)[2] - cota) < 1e-6]
        try:
            pav = montar_pavimento(modelo, cota, fck)
            resultado = dimensionar(pav)
        except (ErroDeModelo, ValueError, ZeroDivisionError, KeyError) as e:
            saida.append(VerificacaoDePavimento(cota, paineis, erro=str(e)))
            continue

        v = VerificacaoDePavimento(cota, paineis, resultado=resultado,
                                   pavimento=pav,
                                   continuidades=len(pav.continuidades))
        if pasta_desenhos is not None:
            v.desenhos = gravar_desenhos_de_laje(resultado, cota,
                                                 pasta_desenhos)
        saida.append(v)
    return saida


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
        if not v.passou:
            linhas.append(f"  cota {v.cota:g} m: {v.erro}")
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
