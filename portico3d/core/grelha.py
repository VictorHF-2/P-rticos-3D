# -*- coding: utf-8 -*-
"""
grelha.py
A laje como grelha de barras, ligada às vigas de contorno.

Sem esta opção a laje é só carga: o painel se reparte às quatro vigas pelas
áreas a 45° e não tem rigidez nenhuma. Com ela, cada painel vira uma
**grelha** — a analogia de grelha de Hambly, que é o que os programas de
edifício usam —, e a carga chega às vigas pela rigidez relativa de laje e
viga, e não por uma regra geométrica.

## O modelo de cálculo

O modelo do usuário não muda. Na hora de calcular, monta-se um **modelo de
cálculo** a partir dele:

* cada painel é dividido em ``nx × ny`` faixas, com espaçamento próximo de
  ``malha_grelha`` (no mínimo 2 por lado);
* as vigas de contorno são **partidas** nos pontos onde as faixas chegam, e
  cada pedaço herda seção, material, giro, liberação e trecho rígido da sua
  ponta;
* cada faixa interna vira uma barra de seção ``b × e`` — ``b`` a largura de
  influência da faixa, ``e`` a espessura —, com ``I = b·e³/12`` e a rigidez à
  torção da placa, ``J = b·e³/6`` (Hambly), num material sem peso: o peso da
  laje já está na carga;
* a carga da laje — a que ``lajes.distribuir`` pôs nas vigas, marcada com
  ``origem = "laje:..."`` — sai das vigas, vira carga por área de novo
  (o total se conserva exatamente) e é aplicada nas faixas, metade em cada
  direção, cada faixa com a sua largura de influência. As faixas de borda são
  as próprias vigas.

O resultado volta ao modelo do usuário: deslocamentos e reações dos nós dele,
e cada viga partida **remontada numa barra só**, com as forças que as faixas
da laje lhe aplicam entrando como ações concentradas ao longo dela
(``Resultado.pontuais``). Diagrama, envoltória e dimensionamento leem a viga
como sempre leram.

## O que fica de fora, de propósito

* **Excentricidade laje–viga.** As barras da grelha ficam no plano dos nós,
  que é o eixo das vigas; a laje real está meia altura de viga acima. A
  contribuição da laje como mesa colaborante não entra.
* **Laje sem espessura ou sem material** fica fora da grelha, com aviso: sem
  espessura não há rigidez a dar.
* **Modelo antigo**, com a carga de laje nas vigas sem a marca de origem: a
  grelha entra só com a rigidez, e a carga continua chegando às vigas pela
  regra das áreas — também com aviso.
* O **dimensionamento da laje** continua sendo do programa de Lajes, pelas
  tabelas; os momentos da grelha ficam no resultado de cálculo
  (``Resultado.calculo``), não vão para a armadura.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from .carregamento import Segmento
from .modelo import (Apoio, CargaDistribuida, CasoDeCarga, ErroDeModelo,
                     Modelo, Secao)

TOLERANCIA = 1.0e-6

#: Separador dos nomes gerados: não aparece em nome digitado de propósito.
SEP = "~"


@dataclass
class Pedaco:
    """Um pedaço de viga partida, no modelo de cálculo."""

    barra: str            # nome no modelo de cálculo
    inicio: float         # distância do nó i da barra original ao nó i dele
    fim: float            # idem ao nó j
    offset_i: float
    offset_j: float

    @property
    def flexivel(self) -> tuple[float, float]:
        """O vão flexível do pedaço, em distância desde o nó i original."""
        return self.inicio + self.offset_i, self.fim - self.offset_j


@dataclass
class LajeEmGrelha:
    nome: str
    xs: np.ndarray
    ys: np.ndarray
    cota: float
    #: As vigas de contorno: embaixo (y0), à direita (x1), em cima (y1) e à
    #: esquerda (x0), na ordem de ``lajes.arestas_da_laje``.
    bordas: list
    #: (j, i) -> nome da faixa em X no modelo de cálculo, e (i, j) -> em Y.
    faixas_x: dict[tuple[int, int], str] = field(default_factory=dict)
    faixas_y: dict[tuple[int, int], str] = field(default_factory=dict)

    @property
    def area(self) -> float:
        return float((self.xs[-1] - self.xs[0]) * (self.ys[-1] - self.ys[0]))


@dataclass
class ModeloDeCalculo:
    original: Modelo
    calc: Modelo
    pedacos: dict[str, list[Pedaco]]
    lajes: dict[str, LajeEmGrelha]
    avisos: list[str] = field(default_factory=list)
    _preparadas: dict | None = None

    @property
    def preparadas_originais(self) -> dict:
        if self._preparadas is None:
            from .montagem import preparar_barras
            self._preparadas = preparar_barras(self.original)
        return self._preparadas


# ---------------------------------------------------------------------------
# Montagem do modelo de cálculo
# ---------------------------------------------------------------------------

def _assinatura(modelo: Modelo) -> str:
    """O que, mudando, obriga a remontar a grelha (as cargas não entram)."""
    return repr((modelo.calculo, list(modelo.nos.values()),
                 list(modelo.barras.values()), list(modelo.lajes.values()),
                 list(modelo.materiais.values()), list(modelo.secoes.values()),
                 list(modelo.apoios.values()), list(modelo.molas.values())))


def modelo_de_calculo(modelo: Modelo) -> ModeloDeCalculo:
    """O modelo de cálculo da grelha, montado uma vez por geometria."""
    assinatura = _assinatura(modelo)
    guardado = modelo.__dict__.get("_grelha")
    if guardado is not None and guardado[0] == assinatura:
        return guardado[1]
    mc = _montar(modelo)
    modelo.__dict__["_grelha"] = (assinatura, mc)
    return mc


def _divisoes(comprimento: float, malha: float) -> int:
    return max(2, int(math.ceil(comprimento / malha - 1e-9)))


def _montar(modelo: Modelo) -> ModeloDeCalculo:
    from .lajes import arestas_da_laje

    calc = Modelo(modelo.nome + SEP + "grelha",
                  materiais=dict(modelo.materiais),
                  secoes=dict(modelo.secoes),
                  nos=dict(modelo.nos),
                  apoios=dict(modelo.apoios),
                  molas=dict(modelo.molas),
                  lajes=dict(modelo.lajes),
                  cargas_de_laje=dict(modelo.cargas_de_laje),
                  calculo=replace(modelo.calculo, grelha=False))
    avisos: list[str] = []

    por_posicao = {(round(n.x, 6), round(n.y, 6), round(n.z, 6)): nome
                   for nome, n in modelo.nos.items()}
    contador = [0]

    def no_em(x: float, y: float, z: float) -> str:
        chave = (round(x, 6), round(y, 6), round(z, 6))
        nome = por_posicao.get(chave)
        if nome is None:
            while True:
                contador[0] += 1
                nome = f"G{SEP}{contador[0]}"
                if nome not in calc.nos:
                    break
            calc.add_no(nome, x, y, z)
            por_posicao[chave] = nome
        return nome

    # -- 1. as lajes, a malha de cada uma e onde ela corta as vigas ----------
    lajes: dict[str, LajeEmGrelha] = {}
    cortes: dict[str, list[np.ndarray]] = {}
    for laje in modelo.lajes.values():
        if laje.em_balanco:
            avisos.append(
                f"laje {laje.nome}: em balanço — fica fora da grelha, e a "
                "carga dela segue para a viga do lado apoiado")
            continue
        if laje.altura <= 0.0 or laje.material not in modelo.materiais:
            avisos.append(
                f"laje {laje.nome}: sem espessura ou sem material — fica fora "
                "da grelha, e a carga dela segue para as vigas pelas áreas")
            continue
        arestas, _, _ = arestas_da_laje(modelo, laje)
        a, c = modelo.ponto(laje.no_a), modelo.ponto(laje.no_c)
        x0, x1 = min(a[0], c[0]), max(a[0], c[0])
        y0, y1 = min(a[1], c[1]), max(a[1], c[1])
        malha = modelo.calculo.malha_grelha
        xs = np.linspace(x0, x1, _divisoes(x1 - x0, malha) + 1)
        ys = np.linspace(y0, y1, _divisoes(y1 - y0, malha) + 1)
        z = float(a[2])
        lajes[laje.nome] = LajeEmGrelha(laje.nome, xs, ys, z, arestas)
        for aresta, pontos in (
                (arestas[0], [(x, y0) for x in xs[1:-1]]),
                (arestas[1], [(x1, y) for y in ys[1:-1]]),
                (arestas[2], [(x, y1) for x in xs[1:-1]]),
                (arestas[3], [(x0, y) for y in ys[1:-1]])):
            # cada ponto vai para a barra do lado que o contém; o que cai
            # num nó entre duas barras já tem nó, e não corta nada
            inicio = modelo.ponto(aresta.inicio)
            for px, py in pontos:
                ponto = np.array([px, py, z])
                s_ponto = float(np.linalg.norm(ponto - inicio))
                for barra, s0, s1 in aresta.trechos:
                    if s0 + TOLERANCIA < s_ponto < s1 - TOLERANCIA:
                        cortes.setdefault(barra, []).append(ponto)
                        break

    # -- 2. as barras: as de contorno partidas, as outras como estão ---------
    pedacos: dict[str, list[Pedaco]] = {}
    for nome, barra in modelo.barras.items():
        if nome not in cortes:
            calc.barras[nome] = barra
            continue
        pi, pj = modelo.ponto(barra.no_i), modelo.ponto(barra.no_j)
        L = float(np.linalg.norm(pj - pi))
        u = (pj - pi) / L
        distancias = sorted({round(float(np.dot(p - pi, u)), 9)
                             for p in cortes[nome]})
        for d in distancias:
            if d <= barra.offset_i + TOLERANCIA or \
                    d >= L - barra.offset_j - TOLERANCIA:
                raise ErroDeModelo(
                    f"grelha: a faixa da laje chega à viga '{nome}' a "
                    f"{d:.3f} m do nó {barra.no_i}, dentro do trecho rígido; "
                    "mude a malha da grelha")
        pontos = [0.0] + distancias + [L]
        nos = [barra.no_i] + [no_em(*(pi + d * u)) for d in distancias] + \
            [barra.no_j]
        lista = []
        for k in range(len(pontos) - 1):
            primeiro, ultimo = k == 0, k == len(pontos) - 2
            nome_k = f"{nome}{SEP}{k + 1}"
            calc.barras[nome_k] = replace(
                barra, nome=nome_k, no_i=nos[k], no_j=nos[k + 1],
                liberacoes_i=barra.liberacoes_i if primeiro else (),
                liberacoes_j=barra.liberacoes_j if ultimo else (),
                offset_i=barra.offset_i if primeiro else 0.0,
                offset_j=barra.offset_j if ultimo else 0.0)
            lista.append(Pedaco(nome_k, pontos[k], pontos[k + 1],
                                barra.offset_i if primeiro else 0.0,
                                barra.offset_j if ultimo else 0.0))
        pedacos[nome] = lista

    # -- 3. as faixas internas de cada laje ---------------------------------
    for g in lajes.values():
        laje = modelo.lajes[g.nome]
        mat = modelo.materiais[laje.material]
        nome_mat = f"{mat.nome}{SEP}grelha"
        if nome_mat not in calc.materiais:
            calc.materiais[nome_mat] = replace(mat, nome=nome_mat,
                                               peso_especifico=0.0)
        nx, ny = len(g.xs) - 1, len(g.ys) - 1

        fr = modelo.calculo.fator_rigidez_laje

        def secao(largura: float, rotulo: str, direcao: str) -> str:
            """Faixa de ``largura`` correndo na ``direcao`` (``"x"``/``"y"``).

            Maciça: o retângulo ``largura × e``. Treliçada: na direção das
            nervuras, a seção T de uma nervura (mesa = intereixo × capa),
            repartida pela largura da faixa; na outra direção, só a capa —
            é por ela que a laje unidirecional ainda reparte alguma coisa.
            """
            nome_s = f"{g.nome}{SEP}{rotulo}"
            if laje.trelicada and direcao == laje.direcao:
                A, Iy, J = _nervura_por_largura(laje, largura)
                Iz = laje.capa * largura ** 3 / 12.0
            else:
                e = laje.capa if laje.trelicada else laje.espessura
                A, Iy = largura * e, largura * e ** 3 / 12.0
                Iz, J = e * largura ** 3 / 12.0, largura * e ** 3 / 6.0
            calc.secoes[nome_s] = Secao(nome_s, A, fr * Iy, fr * Iz, fr * J)
            return nome_s

        for j in range(1, ny):
            s = secao((g.ys[j + 1] - g.ys[j - 1]) / 2.0, f"x{j}", "x")
            for i in range(nx):
                nome_b = f"{g.nome}{SEP}gx{j}.{i}"
                calc.add_barra(nome_b, no_em(g.xs[i], g.ys[j], g.cota),
                               no_em(g.xs[i + 1], g.ys[j], g.cota),
                               nome_mat, s)
                g.faixas_x[(j, i)] = nome_b
        for i in range(1, nx):
            s = secao((g.xs[i + 1] - g.xs[i - 1]) / 2.0, f"y{i}", "y")
            for j in range(ny):
                nome_b = f"{g.nome}{SEP}gy{i}.{j}"
                calc.add_barra(nome_b, no_em(g.xs[i], g.ys[j], g.cota),
                               no_em(g.xs[i], g.ys[j + 1], g.cota),
                               nome_mat, s)
                g.faixas_y[(i, j)] = nome_b

        # As faixas de borda: meia largura de laje ao longo de cada viga de
        # contorno, em paralelo com ela. Sem elas falta perto do bordo a
        # rigidez à torção da placa — é onde ela mais trabalha, nos cantos —,
        # e a grelha converge para a placa só linearmente com a malha, e não
        # com o quadrado dela. Ficam como barras à parte, e não somadas à
        # seção da viga, para que o esforço da viga continue sendo só dela.
        for j, rotulo in ((0, "bx0"), (ny, f"bx{ny}")):
            largura = abs(g.ys[1 if j == 0 else ny] -
                          g.ys[0 if j == 0 else ny - 1]) / 2.0
            s = secao(largura, rotulo, "x")
            for i in range(nx):
                calc.add_barra(f"{g.nome}{SEP}{rotulo}.{i}",
                               no_em(g.xs[i], g.ys[j], g.cota),
                               no_em(g.xs[i + 1], g.ys[j], g.cota),
                               nome_mat, s)
        for i, rotulo in ((0, "by0"), (nx, f"by{nx}")):
            largura = abs(g.xs[1 if i == 0 else nx] -
                          g.xs[0 if i == 0 else nx - 1]) / 2.0
            s = secao(largura, rotulo, "y")
            for j in range(ny):
                calc.add_barra(f"{g.nome}{SEP}{rotulo}.{j}",
                               no_em(g.xs[i], g.ys[j], g.cota),
                               no_em(g.xs[i], g.ys[j + 1], g.cota),
                               nome_mat, s)

    return ModeloDeCalculo(modelo, calc, pedacos, lajes, avisos)


def _nervura_por_largura(laje, largura: float) -> tuple[float, float, float]:
    """``(A, I, J)`` da treliçada na direção das nervuras, para uma faixa de
    ``largura`` m: a seção T bruta de uma nervura (bw, intereixo, capa e
    enchimento), vezes o número de nervuras que cabem na faixa.

    A torção é a da capa (como placa, ``b·capa³/6``) mais a da alma das
    nervuras (retângulo estreito, ``h·bw³/3``) — pequena, e é por isso que a
    treliçada reparte pouco na direção transversal.
    """
    from .lajes import nervura

    bw, inter = nervura(laje)
    hf, he = laje.capa, laje.altura_enchimento
    A = inter * hf + bw * he
    yc = (inter * hf * hf / 2.0 + bw * he * (hf + he / 2.0)) / A
    I = (inter * hf ** 3 / 12.0 + inter * hf * (yc - hf / 2.0) ** 2
         + bw * he ** 3 / 12.0 + bw * he * (hf + he / 2.0 - yc) ** 2)
    n = largura / inter
    J = largura * hf ** 3 / 6.0 + n * he * bw ** 3 / 3.0
    return A * n, I * n, J


# ---------------------------------------------------------------------------
# Cargas no modelo de cálculo
# ---------------------------------------------------------------------------

def _vao_flexivel(modelo: Modelo, barra: str) -> tuple[float, float, float]:
    b = modelo.barras[barra]
    L = modelo.comprimento(barra)
    return L, b.offset_i, L - b.offset_j


def _repartir(mc: ModeloDeCalculo, c: CargaDistribuida,
              caso: CasoDeCarga) -> None:
    """Passa a carga de uma viga partida para os pedaços dela."""
    _, a_flex, b_flex = _vao_flexivel(mc.original, c.barra)
    Lf = b_flex - a_flex
    d0 = a_flex + c.inicio * Lf
    d1 = a_flex + c.fim * Lf
    qa, qb = c.vetor_inicio, c.vetor_fim

    def intensidade(d: float) -> np.ndarray:
        return qa + (qb - qa) * (d - d0) / (d1 - d0)

    for p in mc.pedacos[c.barra]:
        f0, f1 = p.flexivel
        a, b = max(d0, f0), min(d1, f1)
        if b - a <= TOLERANCIA:
            continue
        va, vb = intensidade(a), intensidade(b)
        caso.distribuidas.append(replace(
            c, barra=p.barra, qx=float(va[0]), qy=float(va[1]),
            qz=float(va[2]), qx_fim=float(vb[0]), qy_fim=float(vb[1]),
            qz_fim=float(vb[2]), inicio=(a - f0) / (f1 - f0),
            fim=(b - f0) / (f1 - f0)))


def _carregar_trecho(mc: ModeloDeCalculo, caso: CasoDeCarga, aresta,
                     pa: np.ndarray, pb: np.ndarray, qz: float,
                     origem: str) -> None:
    """Carga vertical uniforme ``qz`` entre dois pontos de um lado da laje.

    O lado pode ter várias barras, e cada uma pode estar partida (no cálculo)
    ou não — a barra curta em que nenhuma faixa chega fica inteira. A carga
    vai a cada pedaço de vão flexível que o trecho ``[pa, pb]`` cobre.
    """
    for barra in aresta.barras:
        b = mc.original.barras[barra]
        pi = mc.original.ponto(b.no_i)
        pj = mc.original.ponto(b.no_j)
        u = (pj - pi) / float(np.linalg.norm(pj - pi))
        da, db = sorted((float(np.dot(pa - pi, u)),
                         float(np.dot(pb - pi, u))))
        pedacos = mc.pedacos.get(barra)
        if pedacos is None:
            L, f0, f1 = _vao_flexivel(mc.original, barra)
            alvos = [(barra, f0, f1)]
        else:
            alvos = [(p.barra, *p.flexivel) for p in pedacos]
        for nome, f0, f1 in alvos:
            a, b_ = max(da, f0), min(db, f1)
            if b_ - a <= TOLERANCIA:
                continue
            caso.distribuida(nome, qz=qz, sistema="global",
                             inicio=max((a - f0) / (f1 - f0), 0.0),
                             fim=min((b_ - f0) / (f1 - f0), 1.0),
                             origem=origem)


def _total_vertical(mc: ModeloDeCalculo, c: CargaDistribuida) -> float:
    """A força vertical global total da carga, em kN (negativa para baixo)."""
    _, a, b = _vao_flexivel(mc.original, c.barra)
    comprimento = (c.fim - c.inicio) * (b - a)
    if c.sistema == "global":
        return 0.5 * (c.vetor_inicio[2] + c.vetor_fim[2]) * comprimento
    R = mc.preparadas_originais[c.barra].R
    qa, qb = R.T @ c.vetor_inicio, R.T @ c.vetor_fim
    return 0.5 * float(qa[2] + qb[2]) * comprimento


def converter_caso(mc: ModeloDeCalculo, caso: CasoDeCarga,
                   avisos: list[str] | None = None) -> CasoDeCarga:
    """O caso de carga no modelo de cálculo.

    A carga de laje (``origem = "laje:..."``) sai das vigas e volta para a
    grelha como carga por área — o total se conserva: ``q = W / (lx·ly)``.
    """
    novo = CasoDeCarga(caso.nome, natureza=caso.natureza,
                       categoria=caso.categoria, grupo=caso.grupo)
    novo.nodais = list(caso.nodais)
    novo.recalques = list(caso.recalques)
    peso_da_laje: dict[str, float] = {}

    for c in caso.distribuidas:
        laje = c.origem[len("laje:"):] if c.origem.startswith("laje:") else ""
        if laje in mc.lajes:
            peso_da_laje[laje] = peso_da_laje.get(laje, 0.0) + \
                _total_vertical(mc, c)
            continue
        if c.barra in mc.pedacos:
            _repartir(mc, c, novo)
        else:
            novo.distribuidas.append(c)

    for nome, W in peso_da_laje.items():
        g = mc.lajes[nome]
        q = W / g.area
        origem = f"laje:{nome}"
        nx, ny = len(g.xs) - 1, len(g.ys) - 1
        # Na maciça, metade da carga vai pelas faixas em X e metade pelas
        # faixas em Y; na treliçada, que é armada numa direção só, ela vai
        # inteira pelas faixas da direção das nervuras. Cada faixa leva a sua
        # largura de influência — a de borda, metade.
        laje = mc.original.lajes[nome]
        if laje.trelicada:
            parte_x = 1.0 if laje.direcao == "x" else 0.0
        else:
            parte_x = 0.5
        for j in range(ny + 1):
            largura = ((g.ys[min(j + 1, ny)] - g.ys[max(j - 1, 0)]) / 2.0)
            qz = q * largura * parte_x
            if qz == 0.0:
                continue
            for i in range(nx):
                if j in (0, ny):
                    borda = g.bordas[0] if j == 0 else g.bordas[2]
                    _carregar_trecho(
                        mc, novo, borda,
                        np.array([g.xs[i], g.ys[j], g.cota]),
                        np.array([g.xs[i + 1], g.ys[j], g.cota]), qz, origem)
                else:
                    novo.distribuida(g.faixas_x[(j, i)], qz=qz,
                                     sistema="global", origem=origem)
        for i in range(nx + 1):
            largura = ((g.xs[min(i + 1, nx)] - g.xs[max(i - 1, 0)]) / 2.0)
            qz = q * largura * (1.0 - parte_x)
            if qz == 0.0:
                continue
            for j in range(ny):
                if i in (0, nx):
                    borda = g.bordas[3] if i == 0 else g.bordas[1]
                    _carregar_trecho(
                        mc, novo, borda,
                        np.array([g.xs[i], g.ys[j], g.cota]),
                        np.array([g.xs[i], g.ys[j + 1], g.cota]), qz, origem)
                else:
                    novo.distribuida(g.faixas_y[(i, j)], qz=qz,
                                     sistema="global", origem=origem)

    if avisos is not None:
        sem_marca = [n for n in mc.lajes if n not in peso_da_laje]
        if sem_marca and caso.natureza == "permanente" and caso.distribuidas:
            avisos.append(
                f"caso {caso.nome}: nenhuma carga marcada como das lajes "
                f"{', '.join(sorted(sem_marca)[:6])}"
                + ("…" if len(sem_marca) > 6 else "")
                + " — se a carga delas estiver nas vigas (modelo antigo), ela "
                "segue pelas áreas, e a grelha entra só com a rigidez")
    return novo


# ---------------------------------------------------------------------------
# De volta ao modelo do usuário
# ---------------------------------------------------------------------------

def _mapa_de_graus(mc: ModeloDeCalculo) -> tuple[np.ndarray, np.ndarray]:
    """Os graus do modelo original e os mesmos graus no de cálculo."""
    indice_calc = {nome: k for k, nome in enumerate(mc.calc.nos)}
    origem, destino = [], []
    for k, nome in enumerate(mc.original.nos):
        origem.extend(range(6 * k, 6 * k + 6))
        base = 6 * indice_calc[nome]
        destino.extend(range(base, base + 6))
    return np.array(origem, int), np.array(destino, int)


def ao_original(mc: ModeloDeCalculo, r):
    """O resultado no modelo de cálculo, lido no modelo do usuário."""
    from .montagem import particionar
    from .resultados import Resultado

    original = mc.original
    graus, graus_calc = _mapa_de_graus(mc)
    D = np.zeros(original.n_gdl)
    D[graus] = r.deslocamentos[graus_calc]
    reacoes = np.zeros(original.n_gdl)
    reacoes[graus] = r.reacoes[graus_calc]

    esforcos, segmentos, pontuais = {}, {}, {}
    for nome, barra in original.barras.items():
        lista = mc.pedacos.get(nome)
        if lista is None:
            esforcos[nome] = r.esforcos[nome]
            segmentos[nome] = r.segmentos[nome]
            if nome in r.pontuais:
                pontuais[nome] = list(r.pontuais[nome])
            continue
        esforcos[nome] = np.concatenate([r.esforcos[lista[0].barra][:6],
                                         r.esforcos[lista[-1].barra][6:]])
        segs, juncoes = [], []
        for k, p in enumerate(lista):
            desloca = p.inicio + p.offset_i - barra.offset_i
            segs.extend(Segmento(s.a + desloca, s.b + desloca, s.qa, s.qb)
                        for s in r.segmentos[p.barra])
            if k + 1 < len(lista):
                f = (r.esforcos[p.barra][6:]
                     + r.esforcos[lista[k + 1].barra][:6])
                juncoes.append((p.fim - barra.offset_i, f))
        segmentos[nome] = segs
        pontuais[nome] = juncoes

    _, restritos = particionar(original)
    return Resultado(modelo=original, caso=r.caso, deslocamentos=D,
                     reacoes=reacoes, esforcos=esforcos,
                     preparadas=mc.preparadas_originais, segmentos=segmentos,
                     gdl_restritos=restritos,
                     reacoes_mola=dict(r.reacoes_mola),
                     iteracoes=r.iteracoes, segunda_ordem=r.segunda_ordem,
                     pontuais=pontuais, calculo=(mc, r))


def _modo_no_original(mc: ModeloDeCalculo, vetor: np.ndarray) -> np.ndarray:
    graus, graus_calc = _mapa_de_graus(mc)
    saida = np.zeros(mc.original.n_gdl)
    saida[graus] = vetor[graus_calc]
    return saida


def resolver_com_grelha(modelo: Modelo, caso: CasoDeCarga, resolver_fn):
    """Resolve o caso no modelo de cálculo e traz o resultado de volta."""
    mc = modelo_de_calculo(modelo)
    return ao_original(mc, resolver_fn(mc.calc, converter_caso(mc, caso)))


def flambagem_com_grelha(modelo: Modelo, caso: CasoDeCarga, n_modos: int):
    from .segunda_ordem import Flambagem, flambagem

    mc = modelo_de_calculo(modelo)
    f = flambagem(mc.calc, converter_caso(mc, caso), n_modos)
    return Flambagem(caso.nome, f.fatores,
                     [_modo_no_original(mc, m) for m in f.modos], modelo)


def modal_com_grelha(modelo: Modelo, n_modos: int,
                     casos_de_massa: tuple[str, ...]):
    from .dinamica import Modal, analisar_modal

    mc = modelo_de_calculo(modelo)
    temporarios = []
    try:
        for nome in casos_de_massa:
            if nome not in modelo.casos:
                raise ErroDeModelo(
                    f"caso de carga '{nome}' não existe: não há como tirar "
                    "massa adicional dele")
            mc.calc.casos[nome] = converter_caso(mc, modelo.casos[nome])
            temporarios.append(nome)
        m = analisar_modal(mc.calc, n_modos, casos_de_massa)
    finally:
        for nome in temporarios:
            mc.calc.casos.pop(nome, None)
    return Modal(m.frequencias, m.periodos,
                 [_modo_no_original(mc, v) for v in m.modos], modelo)


def avisos_da_grelha(modelo: Modelo) -> list[str]:
    """O que a grelha deste modelo tem a dizer — para o relatório."""
    if not (modelo.calculo.grelha and modelo.lajes):
        return []
    mc = modelo_de_calculo(modelo)
    avisos = list(mc.avisos)
    for caso in modelo.casos.values():
        converter_caso(mc, caso, avisos)
    n_faixas = sum(len(g.faixas_x) + len(g.faixas_y) for g in mc.lajes.values())
    avisos.insert(0, f"grelha: {len(mc.lajes)} lajes, {n_faixas} barras de "
                     f"laje, {len(mc.calc.nos) - len(modelo.nos)} nós novos, "
                     f"{len(mc.pedacos)} vigas partidas — "
                     f"{mc.calc.n_gdl} graus de liberdade no cálculo")
    return avisos
