# -*- coding: utf-8 -*-
"""
armadura3d.py
A armadura do pavimento no espaço: pilares, vigas e laje, um nível por vez.

Aqui não se dimensiona nada de novo. Os três motores de elemento já resolveram
a armadura — quantas barras, de que bitola, onde começam e onde acabam — e
este módulo só **põe essa armadura no lugar dela dentro do edifício**:
converte a coordenada de seção de cada programa para os eixos locais da barra
do pórtico, e daí para o sistema global.

## Por que um pavimento por vez

Medido no exemplo de quatro pavimentos: 1 724 barras longitudinais e 964
estribos, que dão cerca de 10 000 segmentos de reta. O matplotlib desenha isso
em 560 ms por rotação — a vista abre, mas não gira. Um pavimento fica na casa
dos 2 000 segmentos, que é 106 ms, e aí a vista responde ao arrasto do mouse.

O recorte é o pavimento, e não outro qualquer, porque é o recorte que o
projeto já usa: planta de fôrma, planta de armação e o próprio dimensionamento
das lajes são todos por pavimento.

## Qual pilar é "do pavimento"

O lance **abaixo** da cota, o que termina nela. É o lance que entrega carga à
laje e às vigas que estão sendo mostradas, de modo que o que aparece na tela é
um caminho de carga fechado. O lance de cima pertence ao pavimento de cima.

## As três conversões de coordenada

**Pilar.** O ``Arranjo`` dá ``(x, y)`` de cada barra em centímetros a partir
do CG da seção, e ``hx`` acompanha o eixo local y da barra do pórtico enquanto
``hy`` acompanha o local z — a mesma correspondência que a ponte de
dimensionamento usa para montar a seção. Então ``x`` vira deslocamento ao
longo de ``ey`` e ``y`` ao longo de ``ez``.

**Viga.** A seção do programa de Vigas é desenhada com a origem no canto
inferior esquerdo: ``u`` de 0 a ``bw`` e ``v`` de 0 a ``h``, medido da face
inferior. O eixo local y do pórtico acompanha o lado ``b`` da seção e o local
z acompanha ``h``, com origem no **centro**; a translação é, portanto, de meia
seção em cada direção.

**Laje.** O programa de Lajes já entrega a geometria da barra no sistema
**global da planta**, em centímetros, porque o pavimento vai inteiro para ele
com as coordenadas do modelo. Só falta a cota: a laje é desenhada centrada no
plano dos nós, **com o topo no topo das vigas**, como na vista de sólido
(``core.lajes.deslocamento_do_centro``), e a barra fica a um cobrimento da
face de baixo (positiva) ou da face de cima (negativa).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .core.modelo import ErroDeModelo, Modelo

CM = 0.01
TOL = 1.0e-6

#: As famílias de armadura, na ordem em que entram na legenda. O nome é o da
#: camada do DXF sem o prefixo, de propósito: uma família, um nome, uma cor.
FAMILIAS = ("pilar longitudinal", "pilar estribo",
            "viga longitudinal", "viga estribo",
            "laje positiva", "laje negativa")


@dataclass
class Fio:
    """Uma barra de aço desenhada: a polilinha do seu eixo, em metros."""

    pontos: np.ndarray               # (n, 3), sistema global, metros
    familia: str                     # uma de FAMILIAS
    elemento: str                    # o pilar, a viga contínua ou a laje
    phi: float = 0.0                 # mm

    @property
    def comprimento(self) -> float:
        if len(self.pontos) < 2:
            return 0.0
        return float(np.sum(np.linalg.norm(np.diff(self.pontos, axis=0),
                                           axis=1)))

    @property
    def segmentos(self) -> int:
        return max(len(self.pontos) - 1, 0)


@dataclass
class ArmaduraDoPavimento:
    """O que foi possível desenhar de um pavimento, e o que não foi."""

    cota: float
    fios: list[Fio] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def segmentos(self) -> int:
        return sum(f.segmentos for f in self.fios)

    @property
    def aco(self) -> float:
        """Comprimento total de barra desenhada, em metros."""
        return sum(f.comprimento for f in self.fios)

    def por_familia(self) -> dict[str, list[Fio]]:
        saida: dict[str, list[Fio]] = {}
        for familia in FAMILIAS:
            achados = [f for f in self.fios if f.familia == familia]
            if achados:
                saida[familia] = achados
        return saida

    def resumo(self) -> str:
        linhas = [f"Armadura da cota {self.cota:g} m — {len(self.fios)} "
                  f"barras, {self.segmentos} segmentos, "
                  f"{self.aco:.1f} m de aço"]
        for familia, fios in self.por_familia().items():
            linhas.append(f"  {familia}: {len(fios)} barras, "
                          f"{sum(f.comprimento for f in fios):.1f} m")
        linhas.extend(f"  ! {a}" for a in self.avisos)
        return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Quem é do pavimento
# ---------------------------------------------------------------------------

def _z(modelo: Modelo, no: str) -> float:
    return float(modelo.ponto(no)[2])


def lances_do_pavimento(modelo: Modelo, cota: float) -> list[str]:
    """Os pilares que terminam na cota — o lance de baixo, o que a sustenta."""
    from .dimensionamento import barras_verticais

    saida = []
    for nome in barras_verticais(modelo):
        barra = modelo.barras[nome]
        topo = max(_z(modelo, barra.no_i), _z(modelo, barra.no_j))
        if abs(topo - cota) < 1e-6:
            saida.append(nome)
    return saida


def vigas_do_pavimento(modelo: Modelo, cota: float) -> list:
    """As vigas contínuas cujos nós estão todos na cota."""
    from .continuidade import vigas_continuas

    return [v for v in vigas_continuas(modelo)
            if v.nos and all(abs(_z(modelo, n) - cota) < 1e-6 for n in v.nos)]


# ---------------------------------------------------------------------------
# Pilares
# ---------------------------------------------------------------------------

def fios_do_pilar(modelo: Modelo, barra: str, resultado,
                  estribos: bool = True, espera: float = 0.0) -> list[Fio]:
    """Longitudinais e estribos de um lance, no lugar em que ele está.

    ``espera`` (m) é o quanto as barras sobem acima do topo do lance para a
    emenda com o de cima (o ``ℓ0c`` do 9.5.2.3); zero no último lance.
    """
    from .core.montagem import preparar_barras

    arranjo = getattr(resultado, "arranjo", None)
    if arranjo is None or not arranjo.barras:
        return []

    preparada = preparar_barras(modelo)[barra]
    b = modelo.barras[barra]
    pi, pj = modelo.ponto(b.no_i), modelo.ponto(b.no_j)
    if pi[2] > pj[2]:                       # sempre da base para o topo
        pi, pj = pj, pi
    ey, ez = preparada.R[1], preparada.R[2]

    fios = []
    acima = np.array([0.0, 0.0, max(espera, 0.0)])
    for aco in arranjo.barras:
        desvio = aco.x * CM * ey + aco.y * CM * ez
        fios.append(Fio(np.array([pi + desvio, pj + desvio + acima]),
                        "pilar longitudinal", barra, aco.phi))

    est = getattr(resultado, "estribos", None)
    if not estribos or est is None or est.s <= 0.0:
        return fios

    secao = modelo.secoes[b.secao]
    # o eixo do estribo corre a um cobrimento mais meia bitola da face
    recuo = (arranjo.cobrimento + est.phi / 20.0) * CM
    meia_y = max(secao.b / 2.0 - recuo, 1e-3)
    meia_z = max(secao.h / 2.0 - recuo, 1e-3)
    cantos = [(-meia_y, -meia_z), (meia_y, -meia_z),
              (meia_y, meia_z), (-meia_y, meia_z), (-meia_y, -meia_z)]

    altura = float(np.linalg.norm(pj - pi))
    passo = max(est.s * CM, 1e-3)
    # meio espaçamento nas pontas: é onde o estribo real começa, e evita
    # desenhá-lo em cima do nó, onde ele sumiria dentro do encontro com a viga
    n = max(int(math.floor((altura - passo) / passo)) + 1, 1)
    direcao = (pj - pi) / altura if altura > TOL else np.zeros(3)
    for k in range(n):
        centro = pi + direcao * (passo / 2.0 + k * passo)
        fios.append(Fio(np.array([centro + u * ey + v * ez
                                  for u, v in cantos]),
                        "pilar estribo", barra, est.phi))
    return fios


# ---------------------------------------------------------------------------
# Vigas
# ---------------------------------------------------------------------------

def intervalos_da_viga(resultado, comprimento: float
                       ) -> list[tuple[float, float]]:
    """Trechos em que o conjunto de barras longitudinais não muda.

    Dentro de um trecho a seção armada é a mesma em toda parte, e por isso
    cada barra pode ser desenhada como uma reta só. Nas fronteiras — onde uma
    barra começa ou termina — o conjunto muda, e é lá que o desenho recorta.
    Recortar assim dispensa casar barra com barra entre estações: cada trecho
    devolve o seu próprio conjunto, e as retas saem colineares.
    """
    cortes = {0.0, comprimento}
    for p in resultado.posicoes:
        if p.tipo in ("longitudinal", "porta"):
            cortes.add(min(max(p.x_ini, 0.0), comprimento))
            cortes.add(min(max(p.x_fim, 0.0), comprimento))
    ordenados = sorted(cortes)
    return [(a, b) for a, b in zip(ordenados, ordenados[1:]) if b - a > 1e-4]


def _lados_com_laje(modelo: Modelo, viga, ey: np.ndarray):
    """``f(x) -> +1, -1 ou 0``: de que lado da viga (no sentido do ``ey``
    local) há laje na abscissa ``x`` da cadeia — 0 quando há dos dois lados
    ou de nenhum, que é quando a mesa simétrica do motor já está certa."""
    from .dimensionamento import _lajes_ao_lado
    from .core.lajes import retangulo

    ao_lado = _lajes_ao_lado(modelo)
    trechos = []
    for barra in viga.barras:
        b = modelo.barras[barra]
        meio = (modelo.ponto(b.no_i) + modelo.ponto(b.no_j)) / 2.0
        sinais = set()
        for laje, _, _ in ao_lado.get(barra, []):
            x0, y0, x1, y1, _ = retangulo(modelo, laje)
            centro = np.array([(x0 + x1) / 2.0, (y0 + y1) / 2.0])
            s = float((centro - meio[:2]) @ np.asarray(ey, float)[:2])
            sinais.add(1 if s > 0.0 else -1)
        pos = dict(zip(viga.nos, viga.posicoes))
        a, c = sorted((pos[b.no_i], pos[b.no_j]))
        trechos.append((a, c, sinais.pop() if len(sinais) == 1 else 0))

    def lado(x: float) -> int:
        for a, c, s in trechos:
            if a - 1e-9 <= x <= c + 1e-9:
                return s
        return 0
    return lado


def fios_da_viga(modelo: Modelo, viga, resultado,
                 estribos: bool = True) -> list[Fio]:
    """Longitudinais e estribos de uma viga contínua, no lugar dela."""
    from .core.montagem import preparar_barras
    from .elementos.vigas.saidas import geometria as geo

    if not viga.barras or viga.comprimento <= 0.0:
        return []
    from .core.lajes import desnivel_da_viga

    preparada = preparar_barras(modelo)[viga.barras[0]]
    ey, ez = preparada.R[1], preparada.R[2]
    secao = modelo.secoes[modelo.barras[viga.barras[0]].secao]
    # o topo da viga no nível do pavimento, como o sólido e a laje
    origem = modelo.ponto(viga.nos[0]) + np.array(
        [0.0, 0.0, desnivel_da_viga(modelo, viga.barras[0])])
    eixo = np.array(viga.direcao, dtype=float)
    comprimento = viga.comprimento

    def ponto(x_m: float, u_cm: float, v_cm: float) -> np.ndarray:
        """Da coordenada da viga (m ao longo, cm na seção) para o global."""
        return (origem + eixo * x_m
                + (u_cm * CM - secao.b / 2.0) * ey
                + (v_cm * CM - secao.h / 2.0) * ez)

    lados = _lados_com_laje(modelo, viga, ey)
    # os trechos também se cortam nos nós: é ali que a laje pode trocar de
    # lado (a sacada que começa no fim da laje de dentro), e a mesa com ela
    nos_internos = [s for s in viga.posicoes if 1e-4 < s < comprimento - 1e-4]
    trechos = []
    for x0, x1 in intervalos_da_viga(resultado, comprimento):
        cortes = [x0] + [s for s in nos_internos if x0 + 1e-4 < s
                         < x1 - 1e-4] + [x1]
        trechos += list(zip(cortes, cortes[1:]))
    fios = []
    for x0, x1 in trechos:
        meio = (x0 + x1) / 2.0
        try:
            corte = geo.montar_secao(resultado, meio)
        except (IndexError, KeyError, ValueError):
            continue
        # A mesa da seção T: o motor a trata simétrica, metade de cada lado
        # da alma. Na viga de borda a laje está de um lado só, e metade das
        # barras do laço da mesa ficava no ar, do lado de fora. Ali a mesa
        # vai inteira para o lado da laje (seção L): as barras fora da alma
        # andam (bf − bw)/2 para esse lado — a ponta da mesa cai na ponta da
        # laje, e as do canto de fora, junto à face da alma.
        lado = lados(meio)
        sec = resultado.viga.secao_em(meio)
        desvio = (lado * (sec.bf - sec.bw) / 2.0
                  if lado and sec.tipo != "retangular" and sec.bf > sec.bw
                  else 0.0)
        for circulo in corte.barras:
            u, v = circulo.centro
            if desvio and not -1e-6 <= u <= secao.b / CM + 1e-6:
                u += desvio
            fios.append(Fio(np.array([ponto(x0, u, v), ponto(x1, u, v)]),
                            "viga longitudinal", viga.nome,
                            circulo.raio * 20.0))

    if not estribos:
        return fios

    cob = resultado.viga.ambiente.cobrimento_nominal
    for p in resultado.posicoes:
        if p.tipo != "estribo" or p.s <= 0.0:
            continue
        recuo = cob + p.phi / 20.0
        u0, v0 = recuo, recuo
        u1 = secao.b / CM - recuo
        v1 = secao.h / CM - recuo
        if u1 <= u0 or v1 <= v0:
            continue
        cantos = [(u0, v0), (u1, v0), (u1, v1), (u0, v1), (u0, v0)]
        passo = p.s * CM
        # o estribo entra no apoio: a zona vai de −t/2 a L + t/2, e é assim
        # que ele é executado. Truncá-la no eixo do pilar cortaria justamente
        # o estribo da face, que é o mais solicitado
        n = max(int(math.floor((p.x_fim - p.x_ini) / passo)) + 1, 1)
        for k in range(n):
            x = p.x_ini + k * passo
            if x > p.x_fim + TOL:
                break
            fios.append(Fio(np.array([ponto(x, u, v) for u, v in cantos]),
                            "viga estribo", viga.nome, p.phi))
    return fios


# ---------------------------------------------------------------------------
# Lajes
# ---------------------------------------------------------------------------

def fios_das_lajes(modelo: Modelo, cota: float, resultado) -> list[Fio]:
    """As barras do pavimento de lajes, já em coordenada global de planta.

    O programa de Lajes recebe o pavimento com as coordenadas do modelo, e por
    isso devolve ``inicio``/``fim`` e a faixa de repetição já no sistema
    global, em centímetros. Aqui só se acrescenta a cota e se repete a barra
    ao longo da faixa, no espaçamento adotado.
    """
    from .core.lajes import deslocamento_do_centro

    ambiente = getattr(getattr(resultado, "pavimento", None), "ambiente", None)
    faces: dict[str, tuple[float, float]] = {}

    def topo_e_fundo(nome: str) -> tuple[float, float]:
        """Topo e fundo da laje acima do plano dos nós, m.

        O negativo sobre a viga entre duas lajes vem com o nome das duas
        ("L1 / L2"): ele fica sob o topo mais alto, e não no de uma laje que
        não existe com esse nome — que o mandava para o plano dos nós, dentro
        da viga.
        """
        if nome not in faces:
            lajes = [modelo.lajes[n.strip()] for n in nome.split(" / ")
                     if n.strip() in modelo.lajes]
            if not lajes:
                faces[nome] = (0.05, -0.05)
            else:
                # o plano médio da laje fica acima dos nós: o topo dela é o
                # das vigas
                pares = [(deslocamento_do_centro(modelo, l),
                          max(l.altura, 0.01) / 2.0) for l in lajes]
                faces[nome] = (max(c + h for c, h in pares),
                               min(c - h for c, h in pares))
        return faces[nome]

    fios = []
    for p in resultado.todas_posicoes:
        if p.quantidade <= 0 or p.espacamento <= 0.0:
            continue
        topo, fundo = topo_e_fundo(p.laje)
        # a face de cima e a de baixo não levam o mesmo cobrimento: a superior
        # tem a ressalva do item 7.4.7.5, e é a própria classe de ambiente do
        # programa de Lajes que decide qual vale
        if ambiente is None:
            cob = 2.5 * CM
        elif p.face == "inferior":
            cob = ambiente.cobrimento_nominal * CM
        else:
            cob = ambiente.cobrimento_superior(p.phi) * CM
        # a laje é desenhada centrada no plano dos nós, como na vista sólida
        z = (cota + fundo + cob if p.face == "inferior"
             else cota + topo - cob)
        a, b = p.inicio * CM, p.fim * CM
        f0, f1 = p.faixa_inicio * CM, p.faixa_fim * CM
        passo = p.espacamento * CM
        for k in range(max(p.quantidade, 1)):
            t = f0 + k * passo
            if t > f1 + passo / 2.0:
                break
            if p.eixo == "X":
                pontos = np.array([[a, t, z], [b, t, z]])
            else:
                pontos = np.array([[t, a, z], [t, b, z]])
            fios.append(Fio(pontos,
                            "laje positiva" if p.face == "inferior"
                            else "laje negativa", p.laje, p.phi))
    return fios


# ---------------------------------------------------------------------------
# O pavimento inteiro
# ---------------------------------------------------------------------------

def armadura_do_pavimento(modelo: Modelo, cota: float,
                          envoltorias: dict | None = None,
                          fck: float | None = None,
                          estribos: bool = True) -> ArmaduraDoPavimento:
    """Dimensiona o pavimento e devolve a armadura já posicionada no espaço.

    ``envoltorias`` é o que os pilares exigem: sem ela não há esforço de
    lance, e os pilares saem do desenho com um aviso em vez de sumirem sem
    explicação — vigas e laje continuam, porque cada motor é independente.

    Cada falha vira aviso, e não exceção: num edifício, uma viga que o motor
    reprova não pode apagar a armadura de todo o resto do pavimento.
    """
    from . import dimensionamento as dim

    saida = ArmaduraDoPavimento(cota=cota)

    # -- pilares -----------------------------------------------------------
    lances = lances_do_pavimento(modelo, cota)
    if lances and not envoltorias:
        saida.avisos.append(
            f"{len(lances)} pilares sem armadura: a envoltória de esforços "
            "ainda não foi montada (Dimensionar pilares, F7)")
    else:
        for barra in lances:
            verificacoes = dim.verificar_pilares(modelo, envoltorias, fck,
                                                 barras=[barra])
            # Duas peneiras, e a ordem entre elas importa. A boa é
            # ``aprovado``: o motor terminou e deu o lance por bom. Faltando
            # essa, ainda serve o lance **reprovado que tem arranjo** — o
            # desenho é justamente onde se vê por que ele não coube, e apagá-lo
            # esconderia o problema. O que não dá para desenhar é o lance sem
            # arranjo nenhum, e esse vira aviso em vez de sumir calado.
            comuns = [v for v in verificacoes if _n_barras(v) > 0]
            aprovadas = [v for v in comuns if v.aprovado] or comuns
            if not aprovadas:
                motivos = [m for v in verificacoes for m in v.motivos]
                motivo = (motivos[0] if motivos
                          else "sem esforço na envoltória")
                saida.avisos.append(f"pilar {barra}: {motivo}")
                continue
            if not any(v.aprovado for v in aprovadas):
                saida.avisos.append(
                    f"pilar {barra}: desenhado com o arranjo da combinação "
                    f"mais armada, mas o motor o REPROVOU — "
                    + (aprovadas[0].motivos or ["sem motivo declarado"])[0])
            # o lance é armado uma vez só: entre as combinações vale a de
            # maior armadura, que é a que governa o arranjo executado
            melhor = max(aprovadas, key=_n_barras)
            anc = getattr(melhor.resultado, "ancoragem", None)
            espera = (getattr(anc, "l0c", 0.0) / 100.0
                      if anc is not None and _tem_lance_acima(modelo, barra)
                      else 0.0)
            saida.fios.extend(fios_do_pilar(modelo, barra, melhor.resultado,
                                            estribos, espera))

    # -- vigas -------------------------------------------------------------
    # Pelas mesmas contas do "Dimensionar vigas": inclusive a viga apoiada em
    # outra viga, em que uma entra como apoio e a outra como carga.
    cadeias = []
    for v in vigas_do_pavimento(modelo, cota):
        if len(v.suportes) >= 2:
            cadeias.append(v)
        else:
            # sem dois apoios não há viga contínua para o motor armar; sumir
            # do desenho sem dizer nada parece armadura esquecida
            saida.avisos.append(
                f"viga {v.nome}: sem armadura — tem {len(v.suportes)} apoio(s) "
                "em pilar ou viga, e o motor precisa de pelo menos dois")
    por_nome = {v.nome: v for v in cadeias}
    # A envoltória vai junto: com ela a viga é armada pelos esforços do
    # pórtico, e a armadura desenhada é a mesma do "Dimensionar vigas".
    for verificacao in dim.dimensionar_cadeias(
            modelo, cadeias, fck=fck, envoltorias=envoltorias,
            conferir_aviso_de_envoltoria=False):
        if not verificacao.passou:
            saida.avisos.append(
                f"viga {verificacao.nome}: {verificacao.erro}")
            continue
        saida.fios.extend(fios_da_viga(modelo, por_nome[verificacao.nome],
                                       verificacao.resultado, estribos))

    # -- lajes -------------------------------------------------------------
    from .elementos.lajes.core.dimensionar import dimensionar as dim_laje

    trelicadas = [l.nome for l in modelo.lajes.values()
                  if l.trelicada and abs(modelo.ponto(l.no_a)[2] - cota) < 1e-6]
    if trelicadas:
        saida.avisos.append(
            f"lajes treliçadas da cota {cota:g} m ({', '.join(trelicadas)}) "
            "não entram no desenho 3D da armadura: o detalhamento delas sai "
            "no Dimensionar lajes")
    try:
        resultado = dim_laje(dim.montar_pavimento(modelo, cota, fck))
    except (ErroDeModelo, ValueError, ZeroDivisionError, KeyError) as erro:
        if not trelicadas or "maciça" not in str(erro):
            saida.avisos.append(f"lajes da cota {cota:g} m: {erro}")
    else:
        saida.fios.extend(fios_das_lajes(modelo, cota, resultado))

    return saida


def _tem_lance_acima(modelo: Modelo, barra: str) -> bool:
    """Se há outro pilar nascendo no topo deste lance."""
    from .continuidade import _eh_vertical

    b = modelo.barras[barra]
    topo = b.no_j if modelo.ponto(b.no_j)[2] >= modelo.ponto(b.no_i)[2] \
        else b.no_i
    for nome, outra in modelo.barras.items():
        if nome == barra or not _eh_vertical(modelo, outra):
            continue
        baixo = outra.no_i if modelo.ponto(outra.no_i)[2] <= \
            modelo.ponto(outra.no_j)[2] else outra.no_j
        if baixo == topo:
            return True
    return False


def _n_barras(verificacao) -> int:
    arranjo = getattr(verificacao.resultado, "arranjo", None)
    return int(getattr(arranjo, "n_barras", 0) or 0)
