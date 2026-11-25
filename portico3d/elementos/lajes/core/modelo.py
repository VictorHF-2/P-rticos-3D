# -*- coding: utf-8 -*-
"""
modelo.py
Modelo de dados de entrada do pavimento: as lajes, os vínculos dos bordos, as
cargas, os materiais e as opções de cálculo. Nada aqui calcula esforços -- é a
descrição do problema, consumida pelos módulos de análise e dimensionamento.

Convenções:
    vãos ........ em metros, ``a`` sempre o menor e ``b`` o maior;
    espessura ... em centímetros;
    cargas ...... superficiais em kN/m², lineares em kN/m, positivas para
                  baixo (gravidade);
    bordos ...... numerados 1 a 4 no contorno, começando por um de
                  comprimento ``a``. Assim os bordos 1 e 3 medem ``a`` e os
                  bordos 2 e 4 medem ``b``.

O pavimento é uma lista de lajes mais uma lista de continuidades. Cada
continuidade diz que o bordo *i* da laje X é a mesma borda que o bordo *j* da
laje Y -- é ela que faz o engaste ser recíproco e que dá origem à armadura
única de continuidade sobre a viga comum.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from .materiais import Aco, Ambiente, Concreto
from .tabelas import APOIADO, ENGASTADO, LIVRE
from .alveolar_modelo import LajeAlveolar
from .nervurada_modelo import LajeNervuradaBi
from .trelicada_modelo import LajeTrelicada

# ---------------------------------------------------------------------------
# Vínculos de bordo
# ---------------------------------------------------------------------------

TIPOS_BORDO = ("livre", "apoiado", "engastado")

#: Texto -> código numérico das tabelas.
CODIGO_BORDO = {"livre": LIVRE, "apoiado": APOIADO, "engastado": ENGASTADO}
TEXTO_BORDO = {v: k for k, v in CODIGO_BORDO.items()}

#: Grau de engastamento recomendado pela NBR 6118 para o regime rígido-plástico
#: (apostila §3.2: entre 0,7 e 2,0, com a norma recomendando i <= 1,5).
GRAU_ENGASTAMENTO_PADRAO = 1.5
GRAU_ENGASTAMENTO_MINIMO = 0.7
GRAU_ENGASTAMENTO_MAXIMO = 2.0

#: Altura padrão da viga de bordo no modelo 3D, cm -- só estética (ver o
#: campo ``h_viga`` de :class:`Bordo`), não entra em nenhum cálculo.
H_VIGA_PADRAO = 40.0

#: Destino da laje, que fixa a espessura mínima do item 13.2.4.1.
DESTINOS = ("piso", "cobertura", "balanco", "veiculo <= 30 kN",
            "veiculo > 30 kN")

#: Tipo de laje que a planta pode atribuir a cada retângulo. ``macica`` é a
#: laje de placa dos capítulos 1 a 3 (charneiras e tabelas); os demais são os
#: sistemas de nervura e painel -- nesses a planta dá a geometria (vãos,
#: apoios, cargas) e o **perfil** dá a seção, a treliça, a protensão etc.
TIPOS_LAJE = ("macica", "trelicada", "alveolar", "nervurada_uni",
              "nervurada_bi")

ROTULO_TIPO = {"macica": "Maciça", "trelicada": "Treliçada",
               "alveolar": "Alveolar", "nervurada_uni": "Nervurada uni",
               "nervurada_bi": "Nervurada bi"}

#: Atributo do :class:`Pavimento` que guarda os perfis de cada tipo.
LISTA_DO_TIPO = {"trelicada": "trelicadas", "alveolar": "alveolares",
                 "nervurada_uni": "nervuradas_uni",
                 "nervurada_bi": "nervuradas_bi"}

#: Tipos em que as nervuras (ou os painéis) vencem **um** vão: a laje tem
#: direção de armação, e só os dois bordos das pontas do vão recebem carga.
TIPOS_UNIDIRECIONAIS = ("trelicada", "alveolar", "nervurada_uni")

#: Face da planta que cada bordo ocupa, por orientação da laje.
#:
#: O número do bordo é convenção de cálculo -- 1 e 3 medem ``a``, 2 e 4 medem
#: ``b`` -- e a face é o que se vê no desenho. Girar a laje troca a face de
#: cada número, e é esta tabela que faz a tradução.
FACES_DO_BORDO = {
    "X": {1: "esquerda", 3: "direita", 2: "baixo", 4: "cima"},
    "Y": {1: "baixo", 3: "cima", 2: "esquerda", 4: "direita"},
}


@dataclass
class Bordo:
    """Um dos quatro bordos da laje.

    ``vinculo`` é ``livre``, ``apoiado`` ou ``engastado``. ``grau`` é o grau de
    engastamento *i* do regime rígido-plástico, usado só quando o bordo é
    engastado. ``vizinha`` guarda o nome da laje do outro lado, quando o
    engaste vem de continuidade; vazio significa engaste em elemento rígido
    (viga de borda com torção impedida, parede, laje que morre num apoio
    contínuo).

    ``t`` é a largura do apoio, cm, usada no vão efetivo do item 14.7.2.2.
    Numa borda comum entre duas lajes é a mesma viga vista dos dois lados, e
    :meth:`Pavimento.aplicar_continuidades` sincroniza os dois valores pelo
    maior -- editar um dos lados não deixa os dois desencontrados.

    ``h_viga`` é a altura da viga, cm, só para desenhar o modelo 3D
    (``saidas/vista3d.py``) -- nenhum cálculo usa esse valor, é puramente
    estético. Sincronizada pelo maior junto com ``t`` na mesma borda comum,
    pelo mesmo motivo.
    """

    vinculo: str = "apoiado"
    grau: float = GRAU_ENGASTAMENTO_PADRAO
    vizinha: str = ""
    t: float = 20.0
    h_viga: float = H_VIGA_PADRAO

    def __post_init__(self) -> None:
        if self.vinculo not in TIPOS_BORDO:
            raise ValueError(f"Vínculo de bordo desconhecido: "
                             f"{self.vinculo!r}")

    @property
    def codigo(self) -> int:
        return CODIGO_BORDO[self.vinculo]

    @property
    def i(self) -> float:
        """Grau de engastamento efetivo: zero se o bordo não é engastado."""
        return self.grau if self.vinculo == "engastado" else 0.0


@dataclass
class Parede:
    """Carga linear de alvenaria apoiada sobre a laje.

    ``direcao`` é ``"a"`` ou ``"b"`` e diz a qual vão a parede é **paralela**.
    ``posicao`` é a distância do eixo da parede ao bordo de referência, em
    metros, medida na direção perpendicular a ela; ``None`` coloca a parede no
    meio do vão, que é a posição mais desfavorável.

    A carga sai do peso específico, da espessura e da altura -- e é assim, e
    não em kN/m direto, porque é a espessura que também define a largura da
    faixa de influência ``b = t + h`` da laje armada em uma direção
    (apostila §2.1).
    """

    espessura: float = 15.0            # cm
    altura: float = 2.80               # m
    peso_especifico: float = 13.0      # kN/m³
    direcao: str = "a"
    posicao: float | None = None       # m
    descricao: str = ""

    def __post_init__(self) -> None:
        if self.direcao not in ("a", "b"):
            raise ValueError(f"Direção de parede desconhecida: "
                             f"{self.direcao!r}")

    @property
    def carga(self) -> float:
        """Carga linear da parede, kN/m."""
        return self.espessura / 100.0 * self.altura * self.peso_especifico


@dataclass
class CargaLinearBorda:
    """Carga variável de parapeito na borda livre da laje (§1.5).

    A NBR 6120 pede 2 kN/m vertical na borda livre e 0,8 kN/m horizontal na
    altura do corrimão -- esta última produz momento na laje pelo braço
    ``altura_corrimao``.
    """

    vertical: float = 2.0              # kN/m
    horizontal: float = 0.8            # kN/m
    altura_corrimao: float = 1.10      # m
    descricao: str = "Parapeito na borda livre"


@dataclass
class CargaConcentrada:
    """Carga concentrada (ou de pequena área) sobre a laje maciça (R11).

    ``x`` e ``y`` são a posição do **centro** da carga, em metros, medida a
    partir do canto inferior esquerdo da laje na planta (o mesmo canto de
    ``Laje.x``/``Laje.y``); ``None`` põe a carga no centro da laje, a posição
    mais desfavorável para o momento positivo. ``dx`` e ``dy`` são as
    dimensões da área carregada nas direções X e Y da planta, cm (a base de
    um equipamento, o pé de um pilarete, a roda de um veículo). ``g`` e
    ``q`` são as parcelas permanente e variável, kN.

    Como entra no cálculo (Souza & Cunha, §1.5.1 e Cap. 5; NBR 6118:2026
    14.7.3 e 19.5):

    * laje em cruz, linhas de ruptura: o maior entre a carga espalhada na
      área com o fator 1,2 do efeito localizado (eq. 1.11) e o leque de
      charneiras em volta da carga, m = P(1 - 2c/3r)/2π, somado ao momento
      da carga uniforme;
    * laje em uma direção: uma faixa de largura colaborante bw (Tabela
      A.1.5, as mesmas expressões do §2.1 para paredes), com a carga na
      posição mais desfavorável do vão;
    * elementos finitos: carga distribuída na área (dx + h) x (dy + h);
    * punção (19.5) nos contornos C e C', com a armadura inferior adotada.
    """

    x: float | None = None             # m, centro da carga na laje
    y: float | None = None
    dx: float = 20.0                   # cm, dimensão em X
    dy: float = 20.0                   # cm, dimensão em Y
    g: float = 0.0                     # kN, permanente
    q: float = 0.0                     # kN, variável
    descricao: str = ""

    @property
    def total(self) -> float:
        return self.g + self.q


@dataclass
class Laje:
    """Uma laje maciça retangular do pavimento."""

    nome: str = "L1"
    a: float = 4.0                     # m, menor vão livre
    b: float = 5.0                     # m, maior vão livre
    h: float = 10.0                    # cm
    destino: str = "piso"
    #: Canto inferior esquerdo da laje na planta, em metros. Serve ao desenho
    #: da planta de formas e à detecção automática das bordas comuns.
    x: float = 0.0
    y: float = 0.0
    #: Direção global do maior vão: ``"X"`` ou ``"Y"``.
    orientacao: str = "X"
    bordos: list[Bordo] = field(default_factory=lambda: [Bordo()
                                                         for _ in range(4)])
    # -- cargas -------------------------------------------------------------
    revestimento: float = 0.0          # kN/m², permanente
    reboco: float = 0.0                # kN/m², permanente
    enchimento: float = 0.0            # cm de enchimento (14 kN/m³)
    permanente_extra: float = 0.0      # kN/m², permanente
    variavel: float = 1.5              # kN/m²
    paredes: list[Parede] = field(default_factory=list)
    borda_livre: CargaLinearBorda | None = None
    #: cargas concentradas (R11) -- ver ``CargaConcentrada``
    cargas_concentradas: list[CargaConcentrada] = field(
        default_factory=list)
    descricao: str = ""
    # -- tipo de laje (R09) -------------------------------------------------
    #: ``macica`` (padrão) ou um dos sistemas de ``TIPOS_LAJE``. Nos demais
    #: tipos ``perfil`` é o **nome** de um item da lista correspondente do
    #: pavimento (treliçadas, alveolares, nervuradas_uni, nervuradas_bi) e
    #: ``direcao`` -- ``"a"`` ou ``"b"`` -- é o vão que a nervura (ou o
    #: painel) vence. Projetos gravados antes da R09 não trazem os três
    #: campos e carregam como maciças.
    tipo: str = "macica"
    perfil: str = ""
    direcao: str = "a"

    def __post_init__(self) -> None:
        if self.destino not in DESTINOS:
            raise ValueError(f"Destino desconhecido: {self.destino!r}")
        if self.tipo not in TIPOS_LAJE:
            raise ValueError(f"Tipo de laje desconhecido: {self.tipo!r}")
        if self.direcao not in ("a", "b"):
            raise ValueError(f"Direção de armação desconhecida: "
                             f"{self.direcao!r}")
        if len(self.bordos) != 4:
            raise ValueError("A laje tem exatamente quatro bordos.")
        self.bordos = [b if isinstance(b, Bordo) else Bordo(**b)
                       for b in self.bordos]
        self.paredes = [p if isinstance(p, Parede) else Parede(**p)
                        for p in self.paredes]
        self.cargas_concentradas = [
            c if isinstance(c, CargaConcentrada) else CargaConcentrada(**c)
            for c in self.cargas_concentradas]
        if isinstance(self.borda_livre, dict):
            self.borda_livre = CargaLinearBorda(**self.borda_livre)
        if self.a > self.b:
            # a é, por definição, o menor vão; trocar os vãos obriga a trocar
            # também os bordos, senão o bordo 1 deixa de medir "a"
            self.a, self.b = self.b, self.a
            self.bordos = [self.bordos[1], self.bordos[2],
                           self.bordos[3], self.bordos[0]]

    @property
    def especial(self) -> bool:
        """A laje não é maciça: é treliçada, alveolar ou nervurada."""
        return self.tipo != "macica"

    @property
    def rotulo_tipo(self) -> str:
        return ROTULO_TIPO[self.tipo]

    # -- geometria ----------------------------------------------------------
    @property
    def vinculos(self) -> tuple[int, int, int, int]:
        return tuple(b.codigo for b in self.bordos)      # type: ignore

    @property
    def codigo_vinculacao(self) -> str:
        return "".join(str(c) for c in self.vinculos)

    @property
    def graus(self) -> tuple[float, float, float, float]:
        return tuple(b.i for b in self.bordos)           # type: ignore

    @property
    def em_balanco(self) -> bool:
        """A laje é em balanço: um bordo engastado e os três outros livres."""
        v = self.vinculos
        return sorted(v) == [LIVRE, LIVRE, LIVRE, ENGASTADO]

    @property
    def n_livres(self) -> int:
        return sum(1 for c in self.vinculos if c == LIVRE)

    @property
    def balanco(self) -> bool:
        """A laje é um balanço, pela destinação ou pelos vínculos (R12):
        ``destino="balanco"`` ou três bordos livres -- o quarto, o do apoio,
        pode ainda estar apoiado antes de a detecção engastá-lo.
        :attr:`em_balanco` é o caso estrito (o quarto já engastado)."""
        return self.destino == "balanco" or self.n_livres == 3

    def aceita_continuidade(self, bordo: int) -> bool:
        """O bordo pode virar borda comum com uma vizinha (R12): num
        balanço, só o bordo do apoio -- os livres continuam livres mesmo
        encostados noutra laje (duas sacadas lado a lado, partidas por uma
        viga que chega por dentro)."""
        return not (self.balanco
                    and self.bordos[bordo - 1].vinculo == "livre")

    def vao_efetivo(self, direcao: str) -> float:
        """Vão efetivo do item 14.7.2.2, em metros.

        ``lef = l0 + a1 + a2``, com ``ai = min(ti/2 ; 0,3 h)`` em cada apoio.
        No balanço o vão efetivo é o livre acrescido de 0,3 h no apoio, como
        pede o segundo parágrafo do item -- e não a soma dos dois lados, que
        ali não existe.
        """
        l0 = self.a if direcao == "a" else self.b
        # os bordos 1 e 3 medem ``a`` e distam ``b`` um do outro: quem vence
        # o vão ``a`` apoia-se nos bordos 2 e 4 (os de comprimento ``b``), e
        # o vão ``b`` nos bordos 1 e 3 -- é a mesma convenção de
        # ``esforcos.BORDOS_DA_DIRECAO``
        indices = (1, 3) if direcao == "a" else (0, 2)
        soma = 0.0
        for k in indices:
            bordo = self.bordos[k]
            if bordo.vinculo == "livre":
                continue
            soma += min(bordo.t / 2.0, 0.3 * self.h) / 100.0
        return l0 + soma

    @property
    def a_ef(self) -> float:
        return self.vao_efetivo("a")

    @property
    def b_ef(self) -> float:
        return self.vao_efetivo("b")

    @property
    def area(self) -> float:
        """Área da laje pelos vãos efetivos, m²."""
        return self.a_ef * self.b_ef

    # -- posição na planta --------------------------------------------------
    # O retângulo da planta é o dos **vãos livres**, e não o dos vãos
    # efetivos: é ele que o usuário lança, e é entre dois retângulos livres
    # que passa a viga. Usar o vão efetivo aqui faria as lajes vizinhas se
    # sobreporem por alguns centímetros e embaralharia a detecção das bordas
    # comuns.
    @property
    def largura_x(self) -> float:
        """Dimensão da laje na direção X global, m."""
        return self.b if self.orientacao == "X" else self.a

    @property
    def largura_y(self) -> float:
        """Dimensão da laje na direção Y global, m."""
        return self.a if self.orientacao == "X" else self.b

    #: Mantido como atributo de classe por compatibilidade com quem já
    #: escrevia ``Laje.FACES``; a tabela em si vive no módulo.
    FACES = FACES_DO_BORDO

    def bordo_da_face(self, face: str) -> int:
        """Número do bordo que ocupa a face dada da planta."""
        return {v: k for k, v in
                FACES_DO_BORDO[self.orientacao].items()}[face]

    def face_do_bordo(self, bordo: int) -> str:
        """Face da planta que o bordo ocupa: esquerda, direita, baixo, cima."""
        return FACES_DO_BORDO[self.orientacao][bordo]

    @property
    def retangulo(self) -> tuple[float, float, float, float]:
        """Retângulo da laje na planta: ``(x0, y0, x1, y1)`` em metros."""
        return (self.x, self.y, self.x + self.largura_x,
                self.y + self.largura_y)

    def segmento_do_bordo(self, bordo: int
                          ) -> tuple[float, float, float, float]:
        """Segmento do bordo na planta: ``(x0, y0, x1, y1)`` em metros.

        Em coordenadas locais o bordo 1 é a aresta ``u = 0``, o bordo 3 é
        ``u = b``, o bordo 2 é ``v = 0`` e o bordo 4 é ``v = a`` -- com
        ``u`` correndo ao longo do maior vão e ``v`` ao longo do menor. É a
        mesma convenção usada na repartição das reações.
        """
        x0, y0, x1, y1 = self.retangulo
        if self.orientacao == "X":     # u -> X, v -> Y
            arestas = {1: (x0, y0, x0, y1), 3: (x1, y0, x1, y1),
                       2: (x0, y0, x1, y0), 4: (x0, y1, x1, y1)}
        else:                          # u -> Y, v -> X
            arestas = {1: (x0, y0, x1, y0), 3: (x0, y1, x1, y1),
                       2: (x0, y0, x0, y1), 4: (x1, y0, x1, y1)}
        return arestas[bordo]

    def centro_da_carga(self, c: "CargaConcentrada"
                        ) -> tuple[float, float]:
        """Centro da carga na planta (X, Y), m -- o centro da laje quando a
        posição não foi dada."""
        x0, y0, x1, y1 = self.retangulo
        return (x0 + (c.x if c.x is not None else (x1 - x0) / 2.0),
                y0 + (c.y if c.y is not None else (y1 - y0) / 2.0))

    def carga_local(self, c: "CargaConcentrada"
                    ) -> tuple[float, float, float, float]:
        """``(u, v, du, dv)``: centro da carga nas coordenadas da laje (m) --
        ``u`` ao longo de ``b``, a partir do bordo 1; ``v`` ao longo de
        ``a``, a partir do bordo 2 -- e as dimensões da área carregada ao
        longo de ``u`` e de ``v`` (cm)."""
        x0, y0, _x1, _y1 = self.retangulo
        X, Y = self.centro_da_carga(c)
        if self.orientacao == "X":     # u -> X, v -> Y
            return X - x0, Y - y0, c.dx, c.dy
        return Y - y0, X - x0, c.dy, c.dx

    def direcao_global(self, direcao: str) -> str:
        """Eixo global em que a direção ``a`` ou ``b`` da laje corre."""
        if self.orientacao == "X":
            return "X" if direcao == "b" else "Y"
        return "Y" if direcao == "b" else "X"

    # -- cargas -------------------------------------------------------------
    @property
    def peso_proprio(self) -> float:
        """Peso próprio da laje, kN/m²."""
        return self.h / 100.0 * 25.0

    @property
    def carga_enchimento(self) -> float:
        """Peso do enchimento da laje rebaixada, kN/m² (14 kN/m³)."""
        return self.enchimento / 100.0 * 14.0

    @property
    def g_superficial(self) -> float:
        """Carga permanente superficial, kN/m², sem as paredes."""
        return (self.peso_proprio + self.revestimento + self.reboco
                + self.carga_enchimento + self.permanente_extra)

    def g_paredes_distribuida(self) -> float:
        """Paredes espalhadas na área da laje, kN/m².

        Vale na laje armada em duas direções, em que a apostila trata a carga
        linear pelo formulário de linhas de ruptura com alfa e beta, e serve
        também de referência de comparação na memória. Uma parede paralela a
        ``a`` distribui o peso dela na largura ``b`` e vice-versa.
        """
        total = 0.0
        for p in self.paredes:
            vao_transversal = self.b_ef if p.direcao == "a" else self.a_ef
            total += p.carga / vao_transversal
        return total

    @property
    def g_total(self) -> float:
        """Carga permanente total espalhada, kN/m²."""
        return self.g_superficial + self.g_paredes_distribuida()

    def resumo_cargas(self) -> list[tuple[str, float]]:
        """Composição de cargas, para a memória de cálculo."""
        itens = [(f"Peso próprio - {self.h:g} cm x 25 kN/m³",
                  self.peso_proprio)]
        if self.enchimento:
            itens.append((f"Enchimento - {self.enchimento:g} cm x 14 kN/m³",
                          self.carga_enchimento))
        if self.revestimento:
            itens.append(("Revestimento", self.revestimento))
        if self.reboco:
            itens.append(("Reboco", self.reboco))
        if self.permanente_extra:
            itens.append(("Permanente adicional", self.permanente_extra))
        for p in self.paredes:
            vao = self.b_ef if p.direcao == "a" else self.a_ef
            rotulo = p.descricao or (
                f"Parede {p.espessura:g} cm x {p.altura:g} m "
                f"x {p.peso_especifico:g} kN/m³, paralela a {p.direcao}")
            itens.append((f"{rotulo} ({p.carga:.2f} kN/m / {vao:.2f} m)",
                          p.carga / vao))
        itens.append(("Carga variável", self.variavel))
        return itens


@dataclass
class Continuidade:
    """Borda comum a duas lajes.

    ``laje_a``/``bordo_a`` e ``laje_b``/``bordo_b`` identificam o mesmo
    segmento de viga visto de cada lado. Os bordos são 1 a 4, como o usuário
    os numera. É desta ligação que sai a compatibilização do item 14.7.6.2:
    as duas lajes são calculadas isoladas e depois recebem **uma** armadura
    negativa, dimensionada para o maior dos dois momentos.

    ``parcial_a``/``parcial_b`` (R11) marcam o lado em que a vizinha cobre
    menos de 2/3 do bordo -- a continuidade parcial de Souza & Cunha
    (§3.7.2, Fig. 3.31): só vale engaste no bordo que tem contato em pelo
    menos 2/3 do seu comprimento. O lado parcial fica **apoiado** (com a
    vizinha anotada), o outro engastado; a negativa da borda é a do lado
    engastado, ancorada por cima da viga na laje maior. Os dois lados
    parciais não chegam a formar borda comum
    (:meth:`Pavimento.detectar_continuidades` descarta o par).
    """

    laje_a: str = ""
    bordo_a: int = 1
    laje_b: str = ""
    bordo_b: int = 1
    parcial_a: bool = False
    parcial_b: bool = False

    def __post_init__(self) -> None:
        for n in (self.bordo_a, self.bordo_b):
            if n not in (1, 2, 3, 4):
                raise ValueError(f"Bordo fora de 1..4: {n}")

    def par(self) -> tuple[tuple[str, int], tuple[str, int]]:
        return (self.laje_a, self.bordo_a), (self.laje_b, self.bordo_b)

    def parcial(self, laje: str, bordo: int) -> bool:
        """O lado ``(laje, bordo)`` é o de contato parcial (fica apoiado)."""
        if (self.laje_a, self.bordo_a) == (laje, bordo):
            return self.parcial_a
        if (self.laje_b, self.bordo_b) == (laje, bordo):
            return self.parcial_b
        return False

    @property
    def unilateral(self) -> bool:
        """Só um dos lados engasta (o outro é de contato parcial)."""
        return self.parcial_a != self.parcial_b

    def outro(self, laje: str, bordo: int) -> tuple[str, int] | None:
        """O lado oposto da borda, ou None se o par não é este."""
        if (self.laje_a, self.bordo_a) == (laje, bordo):
            return self.laje_b, self.bordo_b
        if (self.laje_b, self.bordo_b) == (laje, bordo):
            return self.laje_a, self.bordo_a
        return None


def _continuidades_geometricas(la: "Laje", lb: "Laje", folga: float,
                               minimo: float) -> list[Continuidade]:
    """As bordas comuns entre duas lajes, só pela posição na planta -- sem
    considerar espessura nenhuma. Usada por
    :meth:`Pavimento.detectar_continuidades` (que filtra o resultado pela
    diferença de espessura) e por
    :meth:`Pavimento.continuidades_rejeitadas_por_desnivel` (que quer
    justamente os pares que encostam e foram filtrados)."""
    achadas: list[Continuidade] = []
    ax0, ay0, ax1, ay1 = la.retangulo
    bx0, by0, bx1, by1 = lb.retangulo

    def parciais(sobrepos: float, comp_a: float, comp_b: float
                 ) -> dict[str, bool]:
        # §3.7.2 de Souza & Cunha: engaste só com contato >= 2/3 do bordo
        return {"parcial_a": sobrepos < FRACAO_CONTINUIDADE * comp_a - 1e-6,
                "parcial_b": sobrepos < FRACAO_CONTINUIDADE * comp_b - 1e-6}

    # -- vizinhança horizontal: uma à direita da outra ----------------------
    sobrepos_y = min(ay1, by1) - max(ay0, by0)
    if sobrepos_y > minimo:
        flags = parciais(sobrepos_y, ay1 - ay0, by1 - by0)
        if abs(bx0 - ax1) <= folga:
            achadas.append(Continuidade(
                la.nome, la.bordo_da_face("direita"),
                lb.nome, lb.bordo_da_face("esquerda"), **flags))
        elif abs(ax0 - bx1) <= folga:
            achadas.append(Continuidade(
                la.nome, la.bordo_da_face("esquerda"),
                lb.nome, lb.bordo_da_face("direita"), **flags))
    # -- vizinhança vertical: uma acima da outra -----------------------------
    sobrepos_x = min(ax1, bx1) - max(ax0, bx0)
    if sobrepos_x > minimo:
        flags = parciais(sobrepos_x, ax1 - ax0, bx1 - bx0)
        if abs(by0 - ay1) <= folga:
            achadas.append(Continuidade(
                la.nome, la.bordo_da_face("cima"),
                lb.nome, lb.bordo_da_face("baixo"), **flags))
        elif abs(ay0 - by1) <= folga:
            achadas.append(Continuidade(
                la.nome, la.bordo_da_face("baixo"),
                lb.nome, lb.bordo_da_face("cima"), **flags))
    return achadas


#: Fração mínima do bordo em contato com a vizinha para valer engaste
#: (Souza & Cunha, §3.7.2: x >= 2L/3).
FRACAO_CONTINUIDADE = 2.0 / 3.0
#: Vão (menor, livre) da laje rebaixada até o qual um rebaixo r > h deixa a
#: borda apoiada (Souza & Cunha, §1.3.3, Fig. 1.15), cm.
VAO_LIMITE_REBAIXO = 300.0


def rebaixo_entre(la: "Laje", lb: "Laje") -> tuple[float, "Laje"]:
    """Desnível ``r`` (cm) entre as faces superiores das lajes de concreto e
    a laje rebaixada. O programa não tem cota por laje: o rebaixo é medido
    pelo enchimento -- quem tem mais enchimento está mais baixa, e o piso
    acabado das duas fica no mesmo nível."""
    r = abs(la.enchimento - lb.enchimento)
    rebaixada = la if la.enchimento >= lb.enchimento else lb
    return r, rebaixada


def rebaixo_apoia(la: "Laje", lb: "Laje") -> bool:
    """A regra da Fig. 1.15 de Souza & Cunha (lajes sobre viga): o bordo
    comum é engaste se r <= h, ou se r > h e o vão da rebaixada passa de
    300 cm; é apoio simples se r > h e o vão da rebaixada é de até 300 cm."""
    r, reb = rebaixo_entre(la, lb)
    return r > reb.h + 1e-9 and reb.a * 100.0 <= VAO_LIMITE_REBAIXO + 1e-9


# ---------------------------------------------------------------------------
# Critérios de cálculo
# ---------------------------------------------------------------------------

@dataclass
class Config:
    """Coeficientes e critérios de cálculo."""

    gamma_g: float = 1.4
    gamma_q: float = 1.4
    psi_0: float = 0.5                 # combinação rara / frequente
    psi_1: float = 0.4
    psi_2: float = 0.3                 # quase permanente
    #: Coeficiente de fluência do item 17.3.2.1.2 na hipótese da apostila
    #: (t0 = 1 mês, t = infinito, sem armadura de compressão): 1 + alfa_f =
    #: 2,32. Fica configurável porque a hipótese de t0 é do projetista.
    fator_fluencia: float = 2.32
    #: Limite de flecha: L/250 para aceitabilidade visual (Tabela 13.3) e
    #: L/125 nos balanços, como a apostila adota.
    divisor_flecha: int = 250
    divisor_flecha_balanco: int = 125
    #: Como compatibilizar os momentos negativos das bordas comuns (14.7.6.2):
    #: ``"nenhuma"`` deixa cada laje com o momento dela; ``"maior"`` adota o
    #: maior dos dois, que é a simplificação que o item permite de forma
    #: explícita; ``"iterativa"`` altera os graus de engastamento até os dois
    #: lados se igualarem, que é o procedimento que o item recomenda.
    compatibilizacao: str = "maior"
    #: Iterações e tolerância (kN·m/m) da compatibilização iterativa.
    iteracoes_compatibilizacao: int = 40
    tolerancia_compatibilizacao: float = 0.005
    #: Razão mínima entre momento de borda e momento de vão exigida no ELU
    #: pela apostila §1.7 ("1,5:1 entre momentos de borda e momentos no vão").
    razao_minima_borda_vao: float = 1.5
    #: Verificar o cisalhamento pelo item 19.4.
    verificar_cisalhamento: bool = True
    #: Espaçamento máximo da armadura principal: min(2h ; 20 cm) (20.1).
    espacamento_maximo_principal: float = 20.0
    #: Espaçamento máximo da armadura de distribuição, cm (20.1).
    espacamento_maximo_distribuicao: float = 33.0
    #: Espaçamento mínimo construtivo, cm.
    espacamento_minimo: float = 7.5
    #: Faixas de bitola preferidas, por face (apostila §1.8).
    bitola_minima_positiva: float = 4.2
    bitola_minima_negativa: float = 5.0
    #: Faixa de bitola **desejada** pelo projetista, em mm. Zero desliga o
    #: limite: o piso volta a ser o do §1.8 por face e o teto, o h/8 do item
    #: 20.1. Não é limite normativo -- é preferência de obra (o que há no
    #: estoque, o que a armadura vizinha usa, o que o ferreiro dobra sem
    #: gabarito). Por isso, quando a faixa não couber, o programa entrega o
    #: dimensionamento com os limites da norma e **avisa** em vez de recusar.
    bitola_desejada_minima: float = 0.0
    bitola_desejada_maxima: float = 0.0
    #: Bitolas que o programa pode escolher, mm. Vazio usa a lista inteira do
    #: módulo de materiais. Tirar a Ø4,2 e a Ø5,0 restringe a escolha às
    #: bitolas que a NBR 7480 fabrica como **barra** em CA-50.
    bitolas_disponiveis: tuple = ()
    #: Bitola imposta por armadura, em mm, com a chave
    #: ``"<laje>|<armadura>"`` -- por exemplo ``"L1|vão a"``. É o que a tabela
    #: de detalhamento troca quando o usuário escolhe outra bitola: a escolha
    #: automática é boa, mas quem detalha às vezes quer uniformizar a prancha
    #: numa bitola só, e isso não é erro -- é decisão de projeto.
    bitolas_impostas: dict = field(default_factory=dict)
    #: Pré-dimensionar a espessura pelo roteiro do §1.6, subindo de 1 cm até a
    #: flecha caber no limite.
    predimensionar_espessura: bool = False
    #: Espessura máxima que o pré-dimensionamento aceita antes de desistir.
    espessura_maxima: float = 30.0
    #: Arredondar o diagrama de momentos fletores negativos sobre o apoio
    #: (item 14.6.3): reduz o momento calculado no eixo teórico do apoio em
    #: ΔM = R·t/8, onde R é a reação de cálculo do bordo e t a largura do
    #: apoio -- o resultado clássico de tratar a reação como uma pressão
    #: distribuída ao longo do apoio, em vez de concentrada no eixo. Não é
    #: coberto pela apostila de referência deste programa (é item de vigas,
    #: aplicado aqui à laje pela mesma lógica); fica desligado por padrão, e
    #: quem liga decide abrir mão dessa reserva de segurança em troca de
    #: economia de aço.
    arredondar_momento_apoio: bool = False
    #: Como se obtêm os momentos de cálculo (ELU) da laje armada em cruz:
    #: ``"charneiras"`` (padrão: linhas de ruptura, regime rígido-plástico) ou
    #: ``"mef"`` (elementos finitos de placa, regime elástico, e Wood-Armer).
    metodo_esforcos: str = "charneiras"
    #: Lado máximo do elemento da malha do ``mef``, m.
    mef_elemento: float = 0.125
    #: K de Wood-Armer: parcela do volvente na direção x (1 = mínimo de aço).
    mef_k: float = 1.0
    #: Descontar do volvente a parcela que o concreto resiste (Mxyc, NB-1).
    mef_mxyc: bool = False
    #: Redistribuição dos momentos negativos da análise elástica (14.6.4.3):
    #: 1 não redistribui; 0,75 é o mínimo que a norma admite em laje contínua.
    mef_delta: float = 1.0
    #: Lado da zona de canto, em fração do menor vão da laje.
    mef_zona_canto: float = 0.2
    #: (R11) Armadura superior de canto nas lajes em cruz das linhas de
    #: ruptura, nos cantos de dois bordos apoiados: m' = m numa zona de
    #: max(0,414·√(6m/p) ; 0,2·lmenor) -- Souza & Cunha §5.9 e NB-1/78
    #: (``core/cantos.py``). Sem ela o canto levanta e as charneiras
    #: superestimam a resistência em ~13 %.
    armadura_canto: bool = True
    #: (R11) Alternância da sobrecarga ("xadrez") na análise por elementos
    #: finitos: os positivos saem da envoltória entre a carga cheia e os
    #: dois xadrezes; negativos e cantos, da carga cheia.
    mef_alternancia: bool = False
    #: Comprimento comercial da barra de aço, cm (item 9.5.2, emenda por
    #: traspasse). Uma posição mais longa que isso precisa de emenda; o
    #: padrão é 12 m, a vara mais comum em CA-50.
    comprimento_comercial_barra: float = 1200.0


# ---------------------------------------------------------------------------
# Pavimento
# ---------------------------------------------------------------------------

@dataclass
class Pavimento:
    """Conjunto de lajes de um pavimento, com as bordas comuns entre elas."""

    nome: str = "Pavimento tipo"
    projeto: str = ""
    lajes: list[Laje] = field(default_factory=list)
    continuidades: list[Continuidade] = field(default_factory=list)
    concreto: Concreto = field(default_factory=Concreto)
    aco: Aco = field(default_factory=Aco)
    ambiente: Ambiente = field(default_factory=Ambiente)
    config: Config = field(default_factory=Config)
    #: Faixas de laje treliçada (nervura contínua), calculadas à parte das
    #: lajes maciças -- ver ``trelicada.py``.
    trelicadas: list[LajeTrelicada] = field(default_factory=list)
    #: Painéis de laje alveolar protendida -- ver ``alveolar.py``.
    alveolares: list[LajeAlveolar] = field(default_factory=list)
    #: Faixas de laje nervurada unidirecional (moldada no local) -- são
    #: ``LajeTrelicada`` com ``sistema = "nervurada"``, calculadas pelo mesmo
    #: motor -- e painéis de nervurada bidirecional (``nervurada.py``).
    nervuradas_uni: list[LajeTrelicada] = field(default_factory=list)
    nervuradas_bi: list[LajeNervuradaBi] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.lajes = [x if isinstance(x, Laje) else Laje(**x)
                      for x in self.lajes]
        self.trelicadas = [x if isinstance(x, LajeTrelicada)
                           else LajeTrelicada(**x) for x in self.trelicadas]
        self.alveolares = [x if isinstance(x, LajeAlveolar)
                           else LajeAlveolar(**x) for x in self.alveolares]
        self.nervuradas_uni = [x if isinstance(x, LajeTrelicada)
                               else LajeTrelicada(**x)
                               for x in self.nervuradas_uni]
        self.nervuradas_bi = [x if isinstance(x, LajeNervuradaBi)
                              else LajeNervuradaBi(**x)
                              for x in self.nervuradas_bi]
        self.continuidades = [x if isinstance(x, Continuidade)
                              else Continuidade(**x)
                              for x in self.continuidades]
        for campo, tipo in (("concreto", Concreto), ("aco", Aco),
                            ("ambiente", Ambiente), ("config", Config)):
            valor = getattr(self, campo)
            if isinstance(valor, dict):
                setattr(self, campo, tipo(**valor))

    # -- consulta -----------------------------------------------------------
    def laje(self, nome: str) -> Laje | None:
        for x in self.lajes:
            if x.nome == nome:
                return x
        return None

    @property
    def lajes_macicas(self) -> list[Laje]:
        """As lajes de placa -- as que o cálculo por charneiras e tabelas
        trata e que entram na compatibilização dos negativos."""
        return [x for x in self.lajes if not x.especial]

    @property
    def lajes_especiais(self) -> list[Laje]:
        """As lajes treliçadas, alveolares e nervuradas atribuídas na
        planta."""
        return [x for x in self.lajes if x.especial]

    def perfil_da(self, laje: Laje):
        """O item da lista de perfis que a laje usa, ou ``None``.

        Perfil em branco vale como o primeiro da lista -- é o que o
        usuário espera ao trocar o tipo na tabela sem escolher um nome.
        """
        if not laje.especial:
            return None
        itens = getattr(self, LISTA_DO_TIPO[laje.tipo])
        for it in itens:
            if it.nome == laje.perfil:
                return it
        if not laje.perfil and itens:
            return itens[0]
        return None

    def perfis_em_uso(self) -> dict[tuple[str, str], list[str]]:
        """``(tipo, nome do perfil) -> lajes da planta que o usam``."""
        uso: dict[tuple[str, str], list[str]] = {}
        for laje in self.lajes_especiais:
            p = self.perfil_da(laje)
            if p is not None:
                uso.setdefault((laje.tipo, p.nome), []).append(laje.nome)
        return uso

    def vizinha_de(self, nome: str, bordo: int) -> tuple[Laje, int] | None:
        """A laje e o bordo do outro lado da borda comum, se houver."""
        for c in self.continuidades:
            outro = c.outro(nome, bordo)
            if outro is not None:
                laje = self.laje(outro[0])
                if laje is not None:
                    return laje, outro[1]
        return None

    def detectar_continuidades(self, folga: float = 0.40,
                               minimo: float = 0.30,
                               tolerancia_desnivel: float = 2.0,
                               regra_rebaixo: bool = True
                               ) -> list[Continuidade]:
        """Descobre as bordas comuns pela posição das lajes na planta.

        Duas lajes são contínuas quando estão de lados opostos da mesma viga.
        Na planta isso é a face direita de uma encostando na face esquerda da
        outra (ou a de cima na de baixo), com sobreposição real ao longo da
        borda.

        ``folga`` é o vão que pode existir entre os dois retângulos de vãos
        livres -- a largura da viga que passa no meio. ``minimo`` é a
        sobreposição mínima para valer como borda comum, e serve para não
        transformar dois cantos que se tocam em continuidade.

        Desde a R12, num balanço (:attr:`Laje.balanco`) só o bordo do apoio
        aceita continuidade: os bordos livres continuam livres, mesmo
        encostados noutra laje (:meth:`Laje.aceita_continuidade`).

        A sobreposição não precisa ser total, mas desde a R11 só engasta o
        lado que tem contato em pelo menos 2/3 do bordo (Souza & Cunha,
        §3.7.2): laje pequena encostando no meio da borda de uma grande
        engasta o seu bordo, e o da grande fica apoiado
        (``Continuidade.parcial_*``). Se nenhum dos dois lados chega a 2/3, o
        par é descartado.

        Também desde a R11 vale a regra das lajes rebaixadas sobre viga
        (Fig. 1.15 do mesmo livro), com o rebaixo medido pelo enchimento
        (:func:`rebaixo_entre`): r > h com vão da rebaixada de até 300 cm
        deixa a borda apoiada (``regra_rebaixo=False`` desliga).

        ``tolerancia_desnivel`` (cm) é o quanto as espessuras das duas lajes
        podem diferir para a borda ainda valer como engaste. Duas lajes de
        espessuras muito diferentes não fecham um engaste de verdade -- há um
        desnível entre elas, e acima de um certo desnível o concreto não fica
        contínuo o bastante para se comportar como um engaste (regra prática
        de projeto, não item literal da NBR: uma laje "rebaixada" ao lado de
        uma normal, por exemplo). Encostar não basta então: a borda fica de
        fora da lista, e o bordo continua apoiado -- exatamente como dois
        cantos que só se tocam.

        Não altera o pavimento -- devolve a lista para quem chamou decidir.
        """
        achadas: list[Continuidade] = []
        # só as maciças: uma laje de nervura ou painel não fecha engaste com
        # a vizinha -- a continuidade entre faixas treliçadas é da própria
        # faixa (``atribuicao.py``), e com uma maciça o bordo fica apoiado
        macicas = self.lajes_macicas
        for i, la in enumerate(macicas):
            for lb in macicas[i + 1:]:
                if abs(la.h - lb.h) > tolerancia_desnivel:
                    continue
                if regra_rebaixo and rebaixo_apoia(la, lb):
                    continue
                achadas.extend(c for c in _continuidades_geometricas(
                    la, lb, folga, minimo)
                    if not (c.parcial_a and c.parcial_b)
                    and la.aceita_continuidade(c.bordo_a)
                    and lb.aceita_continuidade(c.bordo_b))
        return achadas

    def continuidades_rejeitadas(self, folga: float = 0.40,
                                 minimo: float = 0.30,
                                 tolerancia_desnivel: float = 2.0
                                 ) -> list[tuple[str, str, str]]:
        """Todos os pares que encostam na planta e não viraram borda comum,
        com o motivo em texto: desnível de espessura, rebaixo (Fig. 1.15) ou
        contato parcial dos dois lados (< 2/3, §3.7.2). Devolve
        ``(laje_a, laje_b, motivo)``. Para a tela e a memória."""
        saida: list[tuple[str, str, str]] = []
        macicas = self.lajes_macicas
        for i, la in enumerate(macicas):
            for lb in macicas[i + 1:]:
                geo = _continuidades_geometricas(la, lb, folga, minimo)
                if not geo:
                    continue
                desnivel = abs(la.h - lb.h)
                if desnivel > tolerancia_desnivel:
                    saida.append((la.nome, lb.nome,
                                  f"Δh = {desnivel:.0f} cm"))
                elif rebaixo_apoia(la, lb):
                    r, reb = rebaixo_entre(la, lb)
                    saida.append((la.nome, lb.nome,
                                  f"rebaixo r = {r:.0f} cm > h = "
                                  f"{reb.h:g} cm com vão de "
                                  f"{reb.a * 100:.0f} cm ≤ 300 cm"))
                elif all(c.parcial_a and c.parcial_b for c in geo):
                    saida.append((la.nome, lb.nome,
                                  "contato < 2/3 dos dois bordos"))
                elif not any(la.aceita_continuidade(c.bordo_a)
                             and lb.aceita_continuidade(c.bordo_b)
                             for c in geo):
                    saida.append((la.nome, lb.nome,
                                  "bordo livre de laje em balanço"))
        return saida

    def continuidades_rejeitadas_por_desnivel(
            self, folga: float = 0.40, minimo: float = 0.30,
            tolerancia_desnivel: float = 2.0
            ) -> list[tuple[str, str, float]]:
        """Pares de lajes que encostam na planta, mas cuja diferença de
        espessura passa da tolerância de :meth:`detectar_continuidades` --
        ficam apoiadas em vez de engastadas. Devolve ``(laje_a, laje_b,
        diferença de h em cm)``, só para explicar ao usuário por que um par
        que claramente encosta não virou borda comum.
        """
        saida: list[tuple[str, str, float]] = []
        macicas = self.lajes_macicas
        for i, la in enumerate(macicas):
            for lb in macicas[i + 1:]:
                desnivel = abs(la.h - lb.h)
                if desnivel <= tolerancia_desnivel:
                    continue
                if _continuidades_geometricas(la, lb, folga, minimo):
                    saida.append((la.nome, lb.nome, desnivel))
        return saida

    def aplicar_continuidades(self, achadas: list[Continuidade]) -> int:
        """Adota as continuidades dadas e engasta os bordos correspondentes.

        Devolve quantas bordas foram acrescentadas. As já existentes não são
        duplicadas, e os bordos envolvidos passam a ``engastado`` com a
        vizinha anotada -- é o que o cálculo por tabelas precisa.

        A largura ``t`` do apoio também é sincronizada entre os dois lados:
        é a mesma viga vista de cada laje, então não faz sentido que cada
        lado declare uma largura diferente. Fica valendo o maior dos dois
        valores lançados -- a favor da segurança, e sem exigir que o usuário
        edite a mesma viga duas vezes.
        """
        existentes = {frozenset(c.par()) for c in self.continuidades}
        novas = 0
        for c in achadas:
            if frozenset(c.par()) in existentes:
                continue
            self.continuidades.append(c)
            existentes.add(frozenset(c.par()))
            novas += 1
        for c in self.continuidades:
            for nome, bordo in c.par():
                laje = self.laje(nome)
                outro = c.outro(nome, bordo)
                if laje is None or outro is None:
                    continue
                laje_outro = self.laje(outro[0])
                b = laje.bordos[bordo - 1]
                # o lado de contato parcial (< 2/3 do bordo) fica apoiado
                b.vinculo = "apoiado" if c.parcial(nome, bordo) \
                    else "engastado"
                b.vizinha = outro[0]
                if laje_outro is not None:
                    b_outro = laje_outro.bordos[outro[1] - 1]
                    b.t = max(b.t, b_outro.t)
                    b.h_viga = max(b.h_viga, b_outro.h_viga)
        return novas

    def conferir(self) -> list[str]:
        """Confere a coerência da entrada; devolve a lista de problemas."""
        problemas: list[str] = []
        if not self.lajes:
            problemas.append("O pavimento não tem nenhuma laje.")
        nomes = [x.nome for x in self.lajes]
        for nome in set(nomes):
            if nomes.count(nome) > 1:
                problemas.append(f"Há {nomes.count(nome)} lajes chamadas "
                                 f"{nome}.")
        for c in self.continuidades:
            for nome, bordo in c.par():
                laje = self.laje(nome)
                if laje is None:
                    problemas.append(f"A continuidade cita a laje {nome!r}, "
                                     f"que não existe.")
                    continue
                if c.parcial(nome, bordo):
                    continue
                if laje.bordos[bordo - 1].vinculo != "engastado":
                    problemas.append(
                        f"{nome}, bordo {bordo}: a borda é comum com outra "
                        f"laje, mas o vínculo está "
                        f"{laje.bordos[bordo - 1].vinculo!r} em vez de "
                        f"engastado.")
        # lajes de nervura e painel: perfil e vinculação coerentes
        for laje in self.lajes_especiais:
            if self.perfil_da(laje) is None:
                itens = getattr(self, LISTA_DO_TIPO[laje.tipo])
                problemas.append(
                    f"{laje.nome}: o perfil {laje.perfil!r} da laje "
                    f"{laje.rotulo_tipo.lower()} não existe"
                    + ("." if itens else
                       f" -- cadastre um na aba de laje "
                       f"{laje.rotulo_tipo.lower()}."))
            if laje.tipo in TIPOS_UNIDIRECIONAIS:
                fim = (2, 4) if laje.direcao == "a" else (1, 3)
                for k in fim:
                    if laje.bordos[k - 1].vinculo == "livre":
                        problemas.append(
                            f"{laje.nome}: o bordo {k} é uma ponta do vão "
                            f"{laje.direcao} e está livre -- a laje "
                            f"{laje.rotulo_tipo.lower()} precisa de apoio "
                            f"nos dois (balanço puro só na maciça).")
            elif any(b.vinculo == "livre" for b in laje.bordos):
                problemas.append(
                    f"{laje.nome}: laje {laje.rotulo_tipo.lower()} com "
                    f"bordo livre -- os quatro bordos precisam de apoio.")
            if laje.tipo == "nervurada_bi" and any(
                    b.vinculo == "engastado" and b.vizinha
                    for b in laje.bordos):
                problemas.append(
                    f"{laje.nome}: engaste por continuidade com outra laje "
                    f"não vale na nervurada bidirecional -- deixe o bordo "
                    f"apoiado ou engastado sem vizinha.")
        # bordo engastado apontando para vizinha inexistente
        for laje in self.lajes:
            for k, bordo in enumerate(laje.bordos, start=1):
                if bordo.vinculo != "engastado" or not bordo.vizinha:
                    continue
                if self.laje(bordo.vizinha) is None:
                    problemas.append(
                        f"{laje.nome}, bordo {k}: a vizinha "
                        f"{bordo.vizinha!r} não existe.")
                elif self.vizinha_de(laje.nome, k) is None:
                    problemas.append(
                        f"{laje.nome}, bordo {k}: engaste em "
                        f"{bordo.vizinha!r} sem a continuidade "
                        f"correspondente na lista de bordas comuns.")
        return problemas

    # -- persistência -------------------------------------------------------
    def para_dicionario(self) -> dict:
        return asdict(self)

    def salvar(self, caminho: str) -> str:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(self.para_dicionario(), f, ensure_ascii=False, indent=2)
        return caminho

    @classmethod
    def carregar(cls, caminho: str) -> "Pavimento":
        with open(caminho, encoding="utf-8") as f:
            return cls(**json.load(f))
