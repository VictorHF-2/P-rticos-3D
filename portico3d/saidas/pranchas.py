# -*- coding: utf-8 -*-
"""
pranchas.py
As pranchas do edifício: folhas no espaço do papel do DXF, com moldura,
carimbo e as vistas em escala — por pavimento, a planta de forma, a armação
das lajes e a armação das vigas; no fim, a armação dos pilares.

## Modelo e papel

O espaço do modelo guarda tudo em verdadeira grandeza, em centímetros: a
planta de forma de cada pavimento, desenhada aqui, e os desenhos que os
motores de elemento já fazem (viga, pavimento de lajes, lance de pilar),
importados inteiros e afastados uns dos outros. Cada folha é um *layout* —
o espaço do papel, em milímetros — com janelas (*viewports*) que mostram um
desenho do modelo na escala dele. É como se monta prancha em CAD, e quem
abre o arquivo pode mover, trocar a escala ou reorganizar as janelas sem
redesenhar nada.

## A escala de cada vista

Os motores escrevem os textos com a altura em centímetros do modelo: 2 cm no
pilar, 5 cm na viga, 8 cm no pavimento de lajes. Cada um supõe uma escala de
impressão, e a vista vai na maior escala de redução em que o texto
predominante do desenho sai com pelo menos :data:`TEXTO_MIN` mm no papel —
1:10 no pilar, 1:25 na viga, 1:50 nas lajes. Quando o desenho não cabe numa
A1 nessa escala, a folha cresce para A0; só se nem a A0 bastar a escala
diminui. Texto ilegível não é prancha.

A planta de forma é desenhada aqui, e por isso a escala vem primeiro (1:50,
ou a menor que caiba) e os textos são feitos para ela: 2,5 mm no papel.

## A planta de forma

Contorno de vigas e pilares em planta, como se vê de cima com a laje
transparente: cada face de viga é recortada onde entra em outra viga ou num
pilar, e o que sobra é o contorno da união — sem a linha da viga passando por
dentro do pilar. Pilar hachurado chega por baixo do pavimento; com um X,
nasce nele. Cada viga leva o nome e a seção ao lado, cada pilar o nome e a
seção junto de um canto, cada laje o nome e a espessura no centro; as cotas
entre eixos de pilar correm por cima e pela esquerda. Os rótulos desviam uns
dos outros e dos pilares (registro de caixas, como nas pranchas do
Protendido).

## O que fica para depois

Cortes, detalhes típicos e a numeração das posições única no edifício (cada
motor numera as suas). As cópias dos motores não são editadas: o que sai de
cada desenho é o que o motor desenhou.
"""

from __future__ import annotations

import datetime as _dt
import math
import re
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

#: Formatos de folha (ABNT NBR 10068), mm.
FORMATOS = {"A1": (841.0, 594.0), "A0": (1189.0, 841.0)}
#: Margens da folha: a da esquerda é a da encadernação.
MARGEM_ESQ, MARGEM = 25.0, 10.0
#: Legenda (carimbo), mm: largura da NBR 10068 e altura das quatro faixas.
CARIMBO_L, CARIMBO_H = 178.0, 64.0
#: Escalas usadas (1:n), da maior para a menor.
ESCALAS = (10, 20, 25, 50, 75, 100, 125, 150, 200, 250)
#: Menor altura, mm de papel, do texto predominante de uma vista.
TEXTO_MIN = 1.6
#: Texto corrente e título, mm de papel.
H_TEXTO, H_TITULO = 2.5, 3.5
#: Folga entre vistas e entre vista e moldura, mm.
FOLGA = 10.0
#: Faixa abaixo de cada vista para o título dela, mm.
FAIXA_TITULO = 8.0
#: Margem da janela em volta do desenho, mm de papel.
PAD = 3.0
#: Folga entre desenhos no espaço do modelo, cm.
FOLGA_MODELO = 500.0
#: Largura média de um caractere, em alturas de texto (Arial).
LARG_CHAR = 0.62

CAMADAS_PAPEL = (("PR-MOLDURA", 7), ("PR-CARIMBO", 7), ("PR-TEXTO", 7),
                 ("PR-JANELA", 8))
CAMADAS_FORMA = (("FORMA-CONTORNO", 7), ("FORMA-PILAR", 7),
                 ("FORMA-HACHURA", 8), ("FORMA-TEXTO", 2),
                 ("FORMA-COTA", 3))


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _n(v: float, casas: int = 2) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def _cm(v: float) -> str:
    """Comprimento em cm para cota: inteiro quando é, senão uma casa."""
    r = round(v, 1)
    return f"{r:.0f}" if abs(r - round(r)) < 1e-6 else _n(r, 1)


def _ordem_natural(nome: str):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", nome)]


def largura_texto(texto: str, altura: float) -> float:
    return len(texto) * LARG_CHAR * altura


def _base(nome: str) -> str:
    """``P1.1PAV`` → ``P1``: o nome sem o pavimento."""
    return nome.split(".")[0]


def altura_dominante(entidades) -> float | None:
    """A altura de texto mais frequente (TEXT e MTEXT) — a do corpo do
    desenho, que é a que tem de ser legível."""
    alturas = Counter()
    for e in entidades:
        tipo = e.dxftype()
        if tipo == "TEXT":
            alturas[round(float(e.dxf.height), 2)] += 1
        elif tipo == "MTEXT":
            alturas[round(float(e.dxf.char_height), 2)] += 1
    if not alturas:
        return None
    return alturas.most_common(1)[0][0]


def escala_legivel(altura_cm: float | None) -> int:
    """A maior redução em que ``altura_cm`` sai com ``TEXTO_MIN`` no papel."""
    if not altura_cm:
        return 50
    boas = [e for e in ESCALAS if altura_cm * 10.0 / e >= TEXTO_MIN - 1e-9]
    return max(boas) if boas else ESCALAS[0]


def area_util(formato: str) -> tuple[float, float, float, float]:
    """``(x0, y0, x1, y1)`` dentro da moldura, já com a folga, mm."""
    W, H = FORMATOS[formato]
    return (MARGEM_ESQ + FOLGA, MARGEM + FOLGA, W - MARGEM - FOLGA,
            H - MARGEM - FOLGA)


def obstaculo(formato: str, altura_notas: float = 0.0
              ) -> tuple[float, float, float, float]:
    """O canto inferior direito ocupado pelo carimbo (e pelas notas logo
    acima dele), mm."""
    W, _ = FORMATOS[formato]
    return (W - MARGEM - CARIMBO_L, MARGEM, W - MARGEM,
            MARGEM + CARIMBO_H + altura_notas)


# ---------------------------------------------------------------------------
# Vistas e folhas
# ---------------------------------------------------------------------------

@dataclass
class Vista:
    """Um desenho do espaço do modelo e a escala em que vai para o papel."""

    titulo: str
    caixa: tuple[float, float, float, float]       # cm, modelo
    escala: int
    formato: str = "A1"

    @property
    def largura(self) -> float:                    # mm de papel, com a margem
        return (self.caixa[2] - self.caixa[0]) * 10.0 / self.escala + 2 * PAD

    @property
    def altura(self) -> float:
        return (self.caixa[3] - self.caixa[1]) * 10.0 / self.escala + 2 * PAD


@dataclass
class Grupo:
    """Vistas que vão juntas para folhas de um mesmo conteúdo."""

    conteudo: str
    vistas: list[Vista] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)


@dataclass
class Folha:
    formato: str
    conteudo: str
    #: ``(vista, x, y)``: canto inferior esquerdo da janela, mm.
    itens: list[tuple[Vista, float, float]] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)
    numero: int = 0
    total: int = 0
    #: Caixas de texto do papel: (x0, y0, x1, y1, texto).
    textos: list[tuple] = field(default_factory=list)
    nome_layout: str = ""

    @property
    def escalas(self) -> str:
        es = sorted({v.escala for v, _, _ in self.itens})
        if len(es) == 1:
            return f"1:{es[0]}"
        return "INDICADAS" if es else "—"


def _altura_notas(notas: list[str]) -> float:
    if not notas:
        return 0.0
    linhas = sum(len(_quebrar(n, CARIMBO_L - 6.0, H_TEXTO)) for n in notas)
    return 8.0 + (linhas + 1) * H_TEXTO * 1.6


def _quebrar(texto: str, largura: float, altura: float) -> list[str]:
    linhas, atual = [], ""
    for palavra in texto.split():
        prova = (atual + " " + palavra).strip()
        if atual and largura_texto(prova, altura) > largura:
            linhas.append(atual)
            atual = palavra
        else:
            atual = prova
    if atual:
        linhas.append(atual)
    return linhas or [""]


def cabe(largura: float, altura: float, formato: str,
         altura_notas: float = 0.0) -> bool:
    """Uma vista (com a faixa do título) cabe sozinha na folha, desviando do
    carimbo — ao lado dele ou acima dele."""
    x0, y0, x1, y1 = area_util(formato)
    ox0, _, _, oy1 = obstaculo(formato, altura_notas)
    h = altura + FAIXA_TITULO
    ao_lado = largura <= ox0 - FOLGA - x0 and h <= y1 - y0
    acima = largura <= x1 - x0 and h <= y1 - (oy1 + FOLGA)
    return ao_lado or acima


def escolher_escala(vista: Vista, altura_notas: float = 0.0) -> Vista:
    """A escala legível na menor folha em que caiba; se nem a A0 der, a
    escala cresce (o desenho encolhe) até caber."""
    inicial = vista.escala
    for e in [e for e in ESCALAS if e >= inicial]:
        vista.escala = e
        for formato in FORMATOS:
            if cabe(vista.largura, vista.altura, formato, altura_notas):
                vista.formato = formato
                return vista
    vista.escala, vista.formato = ESCALAS[-1], "A0"
    return vista


def empacotar(grupo: Grupo) -> list[Folha]:
    """As vistas do grupo em folhas, por linhas de cima para baixo e da
    esquerda para a direita, na ordem dada, desviando do carimbo.

    O formato é o maior que alguma vista do grupo pede: as folhas de um
    mesmo conteúdo saem do mesmo tamanho.
    """
    if not grupo.vistas:
        return []
    formato = "A0" if any(v.formato == "A0" for v in grupo.vistas) else "A1"
    x0, y0, x1, y1 = area_util(formato)
    altura_notas = _altura_notas(grupo.notas)
    ox0, _, _, oy1 = obstaculo(formato, altura_notas)

    folhas = [Folha(formato, grupo.conteudo, notas=list(grupo.notas))]
    topo, x, altura_linha = y1, x0, 0.0
    for v in grupo.vistas:
        w, h = v.largura, v.altura + FAIXA_TITULO
        while True:
            base = topo - h
            limite = x1 if base >= oy1 + FOLGA else ox0 - FOLGA
            if x + w <= limite + 1e-6 and base >= y0 - 1e-6:
                folhas[-1].itens.append((v, x, base + FAIXA_TITULO))
                x += w + FOLGA
                altura_linha = max(altura_linha, h)
                break
            if x > x0 + 1e-6:                      # linha nova
                topo -= altura_linha + FOLGA
                x, altura_linha = x0, 0.0
                if topo - h >= y0 - 1e-6:
                    continue
            if not folhas[-1].itens:               # não cabe nem sozinha
                folhas[-1].itens.append((v, x0, y0 + FAIXA_TITULO))
                topo, x, altura_linha = y0 - FOLGA, x1, 0.0
                break
            folhas.append(Folha(formato, grupo.conteudo,
                                notas=list(grupo.notas)))
            topo, x, altura_linha = y1, x0, 0.0
    for f in folhas:
        if len(f.itens) == 1:
            _centrar(f, altura_notas)
    if len(folhas) > 1:
        for i, f in enumerate(folhas, 1):
            f.conteudo = f"{grupo.conteudo} ({i}/{len(folhas)})"
    return folhas


def _centrar(folha: Folha, altura_notas: float) -> None:
    """A vista sozinha vai para o meio do espaço livre: acima do carimbo, se
    cabe ali na largura toda, senão à esquerda dele."""
    v, _, _ = folha.itens[0]
    x0, y0, x1, y1 = area_util(folha.formato)
    ox0, _, _, oy1 = obstaculo(folha.formato, altura_notas)
    w, h = v.largura, v.altura + FAIXA_TITULO
    if w <= x1 - x0 and h <= y1 - (oy1 + FOLGA):
        xa, xb, ya, yb = x0, x1, oy1 + FOLGA, y1
    else:
        xa, xb, ya, yb = x0, ox0 - FOLGA, y0, y1
    x = xa + max(0.0, (xb - xa - w) / 2.0)
    base = ya + max(0.0, (yb - ya - h) / 2.0)
    folha.itens[0] = (v, x, base + FAIXA_TITULO)


# ---------------------------------------------------------------------------
# Planta de forma
# ---------------------------------------------------------------------------

@dataclass
class Retangulo:
    """Retângulo em planta, cm: centro, eixos unitários e semi-lados."""

    c: np.ndarray
    u: np.ndarray
    v: np.ndarray
    a: float
    b: float

    def cantos(self) -> list[np.ndarray]:
        c, u, v, a, b = self.c, self.u, self.v, self.a, self.b
        return [c - a * u - b * v, c + a * u - b * v, c + a * u + b * v,
                c - a * u + b * v]

    def arestas(self) -> list[tuple[np.ndarray, np.ndarray]]:
        k = self.cantos()
        return [(k[i], k[(i + 1) % 4]) for i in range(4)]

    def intervalo(self, p0: np.ndarray, d: np.ndarray, eps: float
                  ) -> tuple[float, float] | None:
        """O trecho ``[t0, t1]`` do segmento ``p0 + t·d`` (0 ≤ t ≤ 1) dentro
        do retângulo inflado de ``eps``."""
        t0, t1 = 0.0, 1.0
        w = p0 - self.c
        for eixo, semi in ((self.u, self.a + eps), (self.v, self.b + eps)):
            s0, ds = float(w @ eixo), float(d @ eixo)
            if abs(ds) < 1e-12:
                if abs(s0) > semi:
                    return None
                continue
            ta, tb = sorted(((-semi - s0) / ds, (semi - s0) / ds))
            t0, t1 = max(t0, ta), min(t1, tb)
            if t0 > t1:
                return None
        return t0, t1

    def caixa(self) -> tuple[float, float, float, float]:
        k = np.array(self.cantos())
        return (float(k[:, 0].min()), float(k[:, 1].min()),
                float(k[:, 0].max()), float(k[:, 1].max()))


def recortar(p0: np.ndarray, p1: np.ndarray, obstaculos: list[Retangulo],
             eps: float = 0.1) -> list[tuple[np.ndarray, np.ndarray]]:
    """Os trechos do segmento que ficam fora de todos os retângulos."""
    d = p1 - p0
    comprimento = float(np.linalg.norm(d))
    if comprimento < eps:
        return []
    cortes = sorted(i for r in obstaculos
                    if (i := r.intervalo(p0, d, eps)) is not None)
    livres, t = [], 0.0
    for a, b in cortes:
        if a > t:
            livres.append((t, a))
        t = max(t, b)
    if t < 1.0:
        livres.append((t, 1.0))
    return [(p0 + a * d, p0 + b * d) for a, b in livres
            if (b - a) * comprimento > eps]


@dataclass
class PlantaDeForma:
    """A geometria de um pavimento em planta, cm, antes de desenhar."""

    cota: float
    vigas: list[tuple[str, str, Retangulo, float]] = field(
        default_factory=list)      # (barra, viga contínua, retângulo, h cm)
    pilares: list[tuple[str, Retangulo, bool, bool, float, float]] = field(
        default_factory=list)      # (barra, ret., chega por baixo, sai por
                                   # cima, b cm, h cm)
    lajes: list[tuple[str, Retangulo, float]] = field(default_factory=list)
    #: Lajes treliçadas da cota (rótulo com "TR").
    trelicadas: set[str] = field(default_factory=set)
    nomes_vigas: dict[str, tuple[str, float, float]] = field(
        default_factory=dict)      # viga contínua → (barra do rótulo, b, h)

    def caixa(self) -> tuple[float, float, float, float]:
        cx = [r.caixa() for _, _, r, _ in self.vigas] + \
             [r.caixa() for _, r, *_ in self.pilares] + \
             [r.caixa() for _, r, _ in self.lajes]
        if not cx:
            return (0.0, 0.0, 0.0, 0.0)
        a = np.array(cx)
        return (float(a[:, 0].min()), float(a[:, 1].min()),
                float(a[:, 2].max()), float(a[:, 3].max()))


def _xy(modelo, no) -> np.ndarray:
    return np.asarray(modelo.ponto(no), float)[:2] * 100.0


def planta_de_forma(modelo, cota: float, tol: float = 1e-6) -> PlantaDeForma:
    """Vigas, pilares e lajes da cota, em planta e em centímetros."""
    from ..continuidade import _eh_horizontal, _eh_vertical, vigas_continuas
    from ..core.lajes import retangulo
    from ..core.montagem import preparar_barras

    R = preparar_barras(modelo)
    planta = PlantaDeForma(cota)

    def z(no) -> float:
        return float(modelo.ponto(no)[2])

    horizontais = [n for n, b in modelo.barras.items()
                   if _eh_horizontal(modelo, b)
                   and abs(z(b.no_i) - cota) < tol and abs(z(b.no_j) - cota) < tol]

    def largura(nome: str, direcao: np.ndarray) -> float:
        s = modelo.secoes[modelo.barras[nome].secao]
        ey = np.asarray(R[nome].R[1], float)[:2]
        ez = np.asarray(R[nome].R[2], float)[:2]
        p = np.array([-direcao[1], direcao[0]])
        return (abs(float(p @ ey)) * s.b + abs(float(p @ ez)) * s.h) * 100.0

    direcoes, larguras = {}, {}
    for n in horizontais:
        b = modelo.barras[n]
        d = _xy(modelo, b.no_j) - _xy(modelo, b.no_i)
        d = d / (float(np.linalg.norm(d)) or 1.0)
        direcoes[n] = d
        larguras[n] = largura(n, d)

    def avanco(nome: str, no: str) -> float:
        """Quanto a face da viga avança além do nó: meia largura da viga
        transversal mais larga que chega a ele (fecha o canto)."""
        maior = 0.0
        for outra in horizontais:
            if outra == nome:
                continue
            ob = modelo.barras[outra]
            if no not in (ob.no_i, ob.no_j):
                continue
            if abs(float(direcoes[outra] @ direcoes[nome])) > 0.99:
                continue
            maior = max(maior, larguras[outra] / 2.0)
        return maior

    cadeia_de = {}
    for vc in vigas_continuas(modelo):
        for barra in vc.barras:
            cadeia_de[barra] = vc.nome
    for n in horizontais:
        b = modelo.barras[n]
        d = direcoes[n]
        p0 = _xy(modelo, b.no_i) - d * avanco(n, b.no_i)
        p1 = _xy(modelo, b.no_j) + d * avanco(n, b.no_j)
        s = modelo.secoes[b.secao]
        ret = Retangulo((p0 + p1) / 2.0, d, np.array([-d[1], d[0]]),
                        float(np.linalg.norm(p1 - p0)) / 2.0,
                        larguras[n] / 2.0)
        planta.vigas.append((n, cadeia_de.get(n, _base(n)), ret,
                             float(s.h) * 100.0))

    # o rótulo de cada viga contínua vai na barra mais comprida dela
    maior: dict[str, float] = {}
    for n, nome, ret, h in planta.vigas:
        if ret.a > maior.get(nome, -1.0):
            maior[nome] = ret.a
            planta.nomes_vigas[nome] = (n, 2.0 * ret.b, h)

    nos = {}
    for n, b in modelo.barras.items():
        if not _eh_vertical(modelo, b):
            continue
        baixo, cima = sorted((b.no_i, b.no_j), key=z)
        if abs(z(cima) - cota) < tol:
            nos.setdefault(cima, {})["baixo"] = n
        if abs(z(baixo) - cota) < tol:
            nos.setdefault(baixo, {})["cima"] = n
    for no, lados in nos.items():
        n = lados.get("baixo") or lados.get("cima")
        s = modelo.secoes[modelo.barras[n].secao]
        ey = np.asarray(R[n].R[1], float)[:2]
        ez = np.asarray(R[n].R[2], float)[:2]
        ey = ey / (float(np.linalg.norm(ey)) or 1.0)
        ez = ez / (float(np.linalg.norm(ez)) or 1.0)
        ret = Retangulo(_xy(modelo, no), ey, ez, float(s.b) * 50.0,
                        float(s.h) * 50.0)
        # dimensões em X e Y globais, para o rótulo
        bx = 2.0 * (abs(ey[0]) * ret.a + abs(ez[0]) * ret.b)
        by = 2.0 * (abs(ey[1]) * ret.a + abs(ez[1]) * ret.b)
        planta.pilares.append((n, ret, "baixo" in lados, "cima" in lados,
                               bx, by))

    for nome, laje in modelo.lajes.items():
        x0, y0, x1, y1, zl = retangulo(modelo, laje)
        if abs(zl - cota) > tol:
            continue
        x0, y0, x1, y1 = (v * 100.0 for v in (x0, y0, x1, y1))
        ret = Retangulo(np.array([(x0 + x1) / 2, (y0 + y1) / 2]),
                        np.array([1.0, 0.0]), np.array([0.0, 1.0]),
                        (x1 - x0) / 2, (y1 - y0) / 2)
        planta.lajes.append((nome, ret, float(laje.espessura) * 100.0))
        if getattr(laje, "trelicada", False):
            planta.trelicadas.add(nome)
    planta.pilares.sort(key=lambda p: _ordem_natural(p[0]))
    planta.lajes.sort(key=lambda p: _ordem_natural(p[0]))
    return planta


class _Registro:
    """Caixas de texto e de obstáculo já ocupadas, para os rótulos desviarem."""

    def __init__(self):
        self.caixas: list[tuple[float, float, float, float]] = []
        self.textos: list[tuple] = []      # (x0, y0, x1, y1, texto)

    def livre(self, cx, folga: float = 0.0) -> bool:
        x0, y0, x1, y1 = cx
        return all(x1 + folga <= a or a2 + folga <= x0 or y1 + folga <= b
                   or b2 + folga <= y0 for a, b, a2, b2 in self.caixas)

    def ocupar(self, cx, texto: str | None = None) -> None:
        self.caixas.append(cx)
        if texto is not None:
            self.textos.append((*cx, texto))


def _texto(msp, texto, x, y, h, camada, registro=None, girado=False,
           alinhar="MIDDLE_CENTER"):
    from ezdxf.enums import TextEntityAlignment

    e = msp.add_text(texto, height=h, rotation=90.0 if girado else 0.0,
                     dxfattribs={"layer": camada, "style": "PORTICOS"})
    e.set_placement((x, y), align=TextEntityAlignment[alinhar])
    if registro is not None:
        w = largura_texto(texto, h)
        if girado:
            cx = (x - h / 2, y - w / 2, x + h / 2, y + w / 2)
        else:
            cx = (x - w / 2, y - h / 2, x + w / 2, y + h / 2)
        registro.ocupar(cx, texto)
    return e


def desenhar_forma(msp, planta: PlantaDeForma, escala: int,
                   origem: tuple[float, float] = (0.0, 0.0),
                   registro: _Registro | None = None
                   ) -> tuple[float, float, float, float]:
    """Desenha a planta de forma no espaço do modelo, deslocada de
    ``origem``, e devolve a caixa ocupada (cm)."""
    reg = registro if registro is not None else _Registro()
    ox, oy = origem
    desl = np.array([ox, oy])
    ht = H_TEXTO * escala / 10.0           # cm de modelo
    pts_todos: list[np.ndarray] = []

    def linha(a, b, camada="FORMA-CONTORNO"):
        a, b = a + desl, b + desl
        msp.add_line(tuple(a), tuple(b), dxfattribs={"layer": camada})
        pts_todos.extend([a, b])

    rets_vigas = [r for _, _, r, _ in planta.vigas]
    rets_pilares = [r for _, r, *_ in planta.pilares]
    rets_lajes = [r for _, r, _ in planta.lajes]

    # faces das vigas, recortadas pelas outras vigas e pelos pilares
    for i, r in enumerate(rets_vigas):
        outros = rets_vigas[:i] + rets_vigas[i + 1:] + rets_pilares
        for a, b in r.arestas():
            for p, q in recortar(a, b, outros):
                linha(p, q)
    # bordas das lajes que não estão sobre viga (a livre do balanço)
    for i, r in enumerate(rets_lajes):
        outros = rets_vigas + rets_pilares + rets_lajes[:i] + rets_lajes[i + 1:]
        for a, b in r.arestas():
            for p, q in recortar(a, b, outros):
                linha(p, q)
    # pilares: contorno; hachura se chega por baixo, X se nasce aqui
    padrao = 0.2 * escala / 3.175              # ANSI31 a ~2 mm no papel
    for _, r, baixo, _, _, _ in planta.pilares:
        k = [tuple(c + desl) for c in r.cantos()]
        msp.add_lwpolyline(k, close=True, dxfattribs={"layer": "FORMA-PILAR"})
        pts_todos.extend(np.array(k))
        if baixo:
            hachura = msp.add_hatch(dxfattribs={"layer": "FORMA-HACHURA"})
            hachura.set_pattern_fill("ANSI31", scale=padrao)
            hachura.paths.add_polyline_path(k, is_closed=True)
        else:
            msp.add_line(k[0], k[2], dxfattribs={"layer": "FORMA-PILAR"})
            msp.add_line(k[1], k[3], dxfattribs={"layer": "FORMA-PILAR"})
        reg.ocupar(tuple(np.add(r.caixa(), (ox, oy, ox, oy))))

    # rótulos dos pilares: num dos quatro cantos, o primeiro livre
    for barra, r, _, _, bx, by in planta.pilares:
        linhas = [_base(barra), f"{_cm(bx)}x{_cm(by)}"]
        w = max(largura_texto(s, ht) for s in linhas)
        h = 2.4 * ht
        x0, y0, x1, y1 = np.add(r.caixa(), (ox, oy, ox, oy))
        g = 0.4 * ht
        for cx in ((x1 + g, y1 + g), (x0 - g - w, y1 + g),
                   (x1 + g, y0 - g - h), (x0 - g - w, y0 - g - h)):
            caixa = (cx[0], cx[1], cx[0] + w, cx[1] + h)
            if reg.livre(caixa, 0.2 * ht):
                break
        _texto(msp, linhas[0], caixa[0] + w / 2, caixa[1] + 1.8 * ht, ht,
               "FORMA-TEXTO")
        _texto(msp, linhas[1], caixa[0] + w / 2, caixa[1] + 0.6 * ht, ht,
               "FORMA-TEXTO")
        reg.ocupar(caixa, " / ".join(linhas))

    # rótulos das vigas: ao lado da face, na barra mais comprida da cadeia
    por_barra = {n: (nome, r) for n, nome, r, _ in planta.vigas}
    for nome, (barra, b, h) in sorted(planta.nomes_vigas.items(),
                                      key=lambda i: _ordem_natural(i[0])):
        _, r = por_barra[barra]
        texto = f"{nome} {_cm(b)}x{_cm(h)}"
        w = largura_texto(texto, ht)
        vertical = abs(r.u[1]) > abs(r.u[0])
        normal = np.array([1.0, 0.0]) if vertical else np.array([0.0, 1.0])
        if float(normal @ r.v) < 0:
            normal = -normal
        colocado = None
        for frac in (0.0, -0.25, 0.25, -0.4, 0.4):
            for lado in (1.0, -1.0):
                centro = r.c + desl + r.u * frac * r.a * 2 + \
                    normal * lado * (r.b + 0.9 * ht)
                if vertical:
                    caixa = (centro[0] - ht / 2, centro[1] - w / 2,
                             centro[0] + ht / 2, centro[1] + w / 2)
                else:
                    caixa = (centro[0] - w / 2, centro[1] - ht / 2,
                             centro[0] + w / 2, centro[1] + ht / 2)
                if reg.livre(caixa, 0.2 * ht):
                    colocado = (centro, caixa)
                    break
            if colocado:
                break
        if colocado is None:
            centro = r.c + desl + normal * (r.b + 0.9 * ht)
            colocado = (centro, caixa)
        centro, caixa = colocado
        _texto(msp, texto, centro[0], centro[1], ht, "FORMA-TEXTO",
               girado=vertical)
        reg.ocupar(caixa, texto)

    # rótulos das lajes: nome e espessura no centro
    for nome, r, h in planta.lajes:
        linhas = [_base(nome), f"h={_cm(h)}" +
                  (" TR" if nome in planta.trelicadas else "")]
        w = max(largura_texto(s, ht) for s in linhas)
        alt = 2.4 * ht
        for dy in (0.0, 2.5 * ht, -2.5 * ht, 5.0 * ht, -5.0 * ht):
            cx, cy = r.c[0] + ox, r.c[1] + oy + dy
            caixa = (cx - w / 2, cy - alt / 2, cx + w / 2, cy + alt / 2)
            if reg.livre(caixa, 0.2 * ht):
                break
        _texto(msp, linhas[0], cx, cy + 0.6 * ht, ht, "FORMA-TEXTO")
        _texto(msp, linhas[1], cx, cy - 0.6 * ht, ht, "FORMA-TEXTO")
        reg.ocupar(caixa, " / ".join(linhas))

    # cotas entre eixos de pilar, por cima e pela esquerda
    geo = np.array(pts_todos) if pts_todos else np.zeros((1, 2))
    xs = sorted({round(float(r.c[0]) + ox, 1) for _, r, *_ in planta.pilares})
    ys = sorted({round(float(r.c[1]) + oy, 1) for _, r, *_ in planta.pilares})
    xmin, ymin = geo.min(axis=0)
    xmax, ymax = geo.max(axis=0)
    for cx in reg.caixas:
        xmin, ymin = min(xmin, cx[0]), min(ymin, cx[1])
        xmax, ymax = max(xmax, cx[2]), max(ymax, cx[3])
    extremos_x = [round(float(v), 1) for v in
                  (geo[:, 0].min(), geo[:, 0].max())]
    extremos_y = [round(float(v), 1) for v in
                  (geo[:, 1].min(), geo[:, 1].max())]
    tick = 0.5 * ht

    def cadeia(valores, nivel, horizontal):
        valores = sorted(set(valores))
        if len(valores) < 2:
            return
        if horizontal:
            msp.add_line((valores[0], nivel), (valores[-1], nivel),
                         dxfattribs={"layer": "FORMA-COTA"})
        else:
            msp.add_line((nivel, valores[0]), (nivel, valores[-1]),
                         dxfattribs={"layer": "FORMA-COTA"})
        for v in valores:
            if horizontal:
                msp.add_line((v - tick, nivel - tick), (v + tick, nivel + tick),
                             dxfattribs={"layer": "FORMA-COTA"})
            else:
                msp.add_line((nivel - tick, v - tick), (nivel + tick, v + tick),
                             dxfattribs={"layer": "FORMA-COTA"})
        for a, b in zip(valores, valores[1:]):
            meio, texto = (a + b) / 2, _cm(b - a)
            if horizontal:
                _texto(msp, texto, meio, nivel + 0.9 * ht, ht, "FORMA-COTA",
                       reg)
            else:
                _texto(msp, texto, nivel - 0.9 * ht, meio, ht, "FORMA-COTA",
                       reg, girado=True)

    y1 = ymax + 2.0 * ht
    y2 = y1 + 2.6 * ht
    cadeia(xs, y1, True)
    cadeia(extremos_x, y2, True)
    x1 = xmin - 2.0 * ht
    x2 = x1 - 2.6 * ht
    cadeia(ys, x1, False)
    cadeia(extremos_y, x2, False)
    return (float(x2 - 1.5 * ht), float(ymin), float(xmax),
            float(y2 + 1.5 * ht))


def desenhar_quadro(msp, projeto, x: float, y: float, escala: int
                    ) -> tuple[float, float, float, float] | None:
    """O resumo do quadro de quantidades (aço e concreto por peça), em
    tabela, no espaço do modelo; texto de 2,5 mm na escala dada."""
    from .quantitativos import consolidar

    try:
        q = consolidar(projeto)
    except Exception:                                    # noqa: BLE001
        return None
    if not q.get("por_elemento"):
        return None
    ht = H_TEXTO * escala / 10.0
    passo = 2.2 * ht
    colunas = (0.0, 32 * ht, 46 * ht, 60 * ht, 76 * ht)
    linhas = [("peça", "aço (kg)", "aço +10 %", "concreto (m³)")]
    for nome, d in q["por_elemento"].items():
        linhas.append((nome, _n(d["aco"], 1), _n(d["aco_perdas"], 1),
                       _n(d["concreto"], 3)))
    linhas.append(("TOTAL", _n(q["aco"], 1), _n(q["aco_perdas"], 1),
                   _n(q["concreto"], 3)))
    topo = y + (len(linhas) + 1) * passo
    _texto(msp, "QUADRO DE QUANTIDADES", x, topo, 1.4 * ht, "FORMA-TEXTO",
           alinhar="LEFT")
    for i, linha in enumerate(linhas):
        yl = topo - (i + 1) * passo - 0.5 * passo
        for k, (xc, texto) in enumerate(zip(colunas, linha)):
            _texto(msp, texto, x + (xc if k == 0 else colunas[k + 1] - ht),
                   yl, ht, "FORMA-TEXTO",
                   alinhar="LEFT" if k == 0 else "RIGHT")
        msp.add_line((x, yl - 0.55 * passo), (x + colunas[-1], yl - 0.55 * passo),
                     dxfattribs={"layer": "FORMA-CONTORNO"})
    return (x, topo - (len(linhas) + 1) * passo - passo, x + colunas[-1],
            topo + 1.4 * ht)


# ---------------------------------------------------------------------------
# Importação dos desenhos dos motores
# ---------------------------------------------------------------------------

def _importar(alvo, origem_dxf: Path, x: float, y: float
              ) -> tuple[tuple[float, float, float, float], float | None] | None:
    """Traz o desenho do motor para o modelo, com o canto inferior esquerdo
    em ``(x, y)``. Devolve a caixa ocupada e a altura de texto predominante."""
    import ezdxf
    import ezdxf.bbox
    from ezdxf.addons import Importer

    msp = alvo.modelspace()
    fonte = ezdxf.readfile(str(origem_dxf))
    # A cota (DIMENSION) aponta para um bloco anônimo com a geometria, e o
    # importador não o traz: a cota chegaria vazia e o AUDIT do CAD a apaga.
    # Explodida na origem, vira as linhas, setas e textos que ela desenha.
    for cota in list(fonte.modelspace().query("DIMENSION")):
        try:
            cota.explode()
        except Exception:                                # noqa: BLE001
            continue
    antes = {id(e) for e in msp}
    importador = Importer(fonte, alvo)
    importador.import_modelspace()
    importador.finalize()
    novas = [e for e in msp if id(e) not in antes]
    if not novas:
        return None
    caixa = ezdxf.bbox.extents(novas, fast=True)
    if not caixa.has_data:
        return None
    dx, dy = x - caixa.extmin.x, y - caixa.extmin.y
    for e in novas:
        try:
            e.translate(dx, dy, 0.0)
        except (AttributeError, TypeError):
            continue
    return ((x, y, x + caixa.size.x, y + caixa.size.y),
            altura_dominante(novas))


class _Cursor:
    """Onde o próximo desenho entra no espaço do modelo: uma linha por
    grupo, desenhos lado a lado, sem se tocarem."""

    def __init__(self):
        self.x, self.y, self.altura = 0.0, 0.0, 0.0

    def proxima_linha(self):
        # as linhas sobem: a de cima começa acima da mais alta desta
        if self.altura:
            self.y += self.altura + FOLGA_MODELO
        self.x, self.altura = 0.0, 0.0

    def ocupar(self, caixa):
        self.x = caixa[2] + FOLGA_MODELO
        self.altura = max(self.altura, caixa[3] - self.y)


# ---------------------------------------------------------------------------
# Folha: moldura, carimbo, notas e janelas
# ---------------------------------------------------------------------------

def _texto_papel(folha: Folha, lay, texto, x, y, h, alinhar="LEFT",
                 camada="PR-TEXTO"):
    from ezdxf.enums import TextEntityAlignment

    e = lay.add_text(texto, height=h,
                     dxfattribs={"layer": camada, "style": "PORTICOS"})
    e.set_placement((x, y), align=TextEntityAlignment[alinhar])
    w = largura_texto(texto, h)
    x0 = {"LEFT": x, "CENTER": x - w / 2, "RIGHT": x - w}[alinhar]
    folha.textos.append((x0, y, x0 + w, y + h, texto))


def _carimbo(folha: Folha, lay, projeto, revisao: str) -> None:
    W, _ = FORMATOS[folha.formato]
    x1, y0 = W - MARGEM, MARGEM
    x0 = x1 - CARIMBO_L
    faixas = (20.0, 12.0, 16.0, 16.0)      # de baixo para cima
    topo = y0 + sum(faixas)
    at = {"layer": "PR-CARIMBO"}
    lay.add_lwpolyline([(x0, y0), (x1, y0), (x1, topo), (x0, topo)],
                       close=True, dxfattribs={**at, "lineweight": 50})
    y = y0
    for h in faixas[:-1]:
        y += h
        lay.add_line((x0, y), (x1, y), dxfattribs=at)
    rot = 1.8
    # faixa 1 (embaixo): responsável técnico e programa
    _texto_papel(folha, lay, "RESPONSÁVEL TÉCNICO", x0 + 2, y0 + 15.5, rot)
    _texto_papel(folha, lay, "Nome: ______________________   CREA: __________",
                 x0 + 2, y0 + 9.0, H_TEXTO)
    _texto_papel(folha, lay, f"Gerado pelo Pórticos 3D {revisao} — "
                 "ABNT NBR 6118:2026", x0 + 2, y0 + 3.0, rot)
    # faixa 2: escala, folha, data, revisão
    ya = y0 + faixas[0]
    colunas = (x0, x0 + 50, x0 + 90, x0 + 140, x1)
    for xc in colunas[1:-1]:
        lay.add_line((xc, ya), (xc, ya + faixas[1]), dxfattribs=at)
    valores = (("ESCALA", folha.escalas), ("FOLHA",
                                           f"{folha.numero:02d}/{folha.total:02d}"),
               ("DATA", _dt.date.today().strftime("%d/%m/%Y")),
               ("REVISÃO", "0"))
    for (rotulo, valor), xc in zip(valores, colunas):
        _texto_papel(folha, lay, rotulo, xc + 2, ya + 8.0, rot)
        _texto_papel(folha, lay, valor, xc + 2, ya + 2.2, H_TEXTO)
    # faixa 3: conteúdo
    yb = ya + faixas[1]
    _texto_papel(folha, lay, "CONTEÚDO", x0 + 2, yb + 12.0, rot)
    linhas = _quebrar(folha.conteudo, CARIMBO_L - 4, H_TITULO)[:2]
    for i, s in enumerate(linhas):
        _texto_papel(folha, lay, s, x0 + 2,
                     yb + 6.5 - i * (H_TITULO * 1.5) +
                     (0 if len(linhas) == 1 else 1.5), H_TITULO)
    # faixa 4: projeto
    yc = yb + faixas[2]
    _texto_papel(folha, lay, "PROJETO ESTRUTURAL", x0 + 2, yc + 12.0, rot)
    nome = (projeto.modelo.nome or "edifício").upper()
    _texto_papel(folha, lay, _quebrar(nome, CARIMBO_L - 4, H_TITULO)[0],
                 x0 + 2, yc + 4.5, H_TITULO)


def _notas(folha: Folha, lay) -> None:
    if not folha.notas:
        return
    W, _ = FORMATOS[folha.formato]
    x0 = W - MARGEM - CARIMBO_L
    y = MARGEM + CARIMBO_H + _altura_notas(folha.notas) - 6.0
    _texto_papel(folha, lay, "NOTAS", x0 + 2, y, H_TITULO)
    y -= H_TEXTO * 2.2
    for i, nota in enumerate(folha.notas, 1):
        for j, s in enumerate(_quebrar(f"{i}. {nota}", CARIMBO_L - 6.0,
                                       H_TEXTO)):
            _texto_papel(folha, lay, ("   " if j else "") + s, x0 + 2, y,
                         H_TEXTO)
            y -= H_TEXTO * 1.6


def desenhar_folha(doc, folha: Folha, projeto, revisao: str) -> None:
    W, H = FORMATOS[folha.formato]
    nome = re.sub(r'[<>/\\":;?*|=,]', "", f"{folha.numero:02d} {folha.conteudo}")
    folha.nome_layout = nome[:60]
    lay = doc.layouts.new(folha.nome_layout)
    lay.page_setup(size=(W, H), margins=(0, 0, 0, 0), units="mm")
    lay.add_lwpolyline([(MARGEM_ESQ, MARGEM), (W - MARGEM, MARGEM),
                        (W - MARGEM, H - MARGEM), (MARGEM_ESQ, H - MARGEM)],
                       close=True,
                       dxfattribs={"layer": "PR-MOLDURA", "lineweight": 70})
    _carimbo(folha, lay, projeto, revisao)
    _notas(folha, lay)
    for vista, x, y in folha.itens:
        w, h = vista.largura, vista.altura
        x0, y0, x1, y1 = vista.caixa
        janela = lay.add_viewport(
            center=(x + w / 2, y + h / 2), size=(w, h),
            view_center_point=((x0 + x1) / 2, (y0 + y1) / 2),
            view_height=h * vista.escala / 10.0)
        janela.dxf.layer = "PR-JANELA"
        _texto_papel(folha, lay, f"{vista.titulo} — ESC. 1:{vista.escala}",
                     x, y - 6.0, H_TITULO)


# ---------------------------------------------------------------------------
# O conjunto
# ---------------------------------------------------------------------------

def cotas_dos_pavimentos(modelo, tol: float = 1e-6) -> list[float]:
    """As cotas com viga horizontal ou laje — os pavimentos."""
    from ..continuidade import _eh_horizontal

    cotas = set()
    for b in modelo.barras.values():
        if _eh_horizontal(modelo, b):
            cotas.add(round(float(modelo.ponto(b.no_i)[2]), 6))
    for laje in modelo.lajes.values():
        cotas.add(round(float(modelo.ponto(laje.no_a)[2]), 6))
    return sorted(cotas)


def _rotulo_cota(z: float) -> str:
    return f"COTA {_n(z)} m"


def _fck(modelo) -> float | None:
    for b in modelo.barras.values():
        m = modelo.materiais.get(b.material)
        if m is not None and getattr(m, "fck", 0.0) > 0.0:
            return float(m.fck)
    return None


def montar(projeto, doc, temp: Path) -> list[Folha]:
    """Desenha o modelo e monta as folhas (ainda sem layout)."""
    from ..compatibilizacao import _arranjo_adotado
    from ..core.lajes import nivel_do_pavimento
    from ..dimensionamento import gravar_desenhos
    from ..elementos.lajes.saidas import dxf as dxf_laje
    from ..elementos.pilares.saidas import dxf as dxf_pilar

    modelo = projeto.modelo
    msp = doc.modelspace()
    cursor = _Cursor()
    grupos: list[Grupo] = []
    fck = _fck(modelo)

    def vista_importada(arquivo, titulo) -> Vista | None:
        r = _importar(doc, Path(arquivo), cursor.x, cursor.y)
        if r is None:
            return None
        caixa, h = r
        cursor.ocupar(caixa)
        return escolher_escala(Vista(titulo, caixa, escala_legivel(h)))

    for z in cotas_dos_pavimentos(modelo):
        rotulo = _rotulo_cota(z)
        # -- forma ---------------------------------------------------------
        cursor.proxima_linha()
        planta = planta_de_forma(modelo, z)
        if planta.vigas or planta.pilares or planta.lajes:
            topo = nivel_do_pavimento(modelo, z)
            notas = ["Cotas em centímetros, entre eixos de pilar."]
            if topo is not None:
                notas.append(f"Topo das vigas e das lajes no nível "
                             f"{_n(topo)} m (topo da viga mais alta).")
            notas += ["Pilar hachurado: chega por baixo do pavimento. "
                      "Pilar com X: nasce no pavimento.",
                      "Rótulos: nome e seção b x h (cm); lajes: nome e "
                      "espessura h (cm)."]
            if planta.trelicadas:
                notas.append("TR: laje treliçada, verificada por faixa de "
                             "nervura; o detalhamento dela está na memória "
                             "de cálculo (o programa de Lajes não a desenha "
                             "em DXF).")
            if fck:
                notas.append(f"Concreto fck = {_n(fck, 0)} MPa.")
            notas_h = _altura_notas(notas)
            x0, y0, x1, y1 = planta.caixa()
            escala = ESCALAS[-1]
            for e in (50, 75, 100, 125, 150, 200, 250):
                # a cota e os rótulos acrescentam ~9 alturas de texto
                extra = 9 * H_TEXTO + 2 * PAD
                w = (x1 - x0) * 10.0 / e + extra
                h = (y1 - y0) * 10.0 / e + extra
                if any(cabe(w, h, f, notas_h) for f in FORMATOS):
                    escala = e
                    break
            caixa = desenhar_forma(msp, planta, escala,
                                   (cursor.x - x0 + 30 * escala / 10.0,
                                    cursor.y - y0 + 30 * escala / 10.0))
            cursor.ocupar(caixa)
            v = Vista(f"PLANTA DE FORMA — {rotulo}", caixa, escala)
            for f in FORMATOS:
                if cabe(v.largura, v.altura, f, notas_h):
                    v.formato = f
                    break
            else:
                v.formato = "A0"
            grupos.append(Grupo(f"PLANTA DE FORMA — {rotulo}", [v], notas))

        # -- lajes ---------------------------------------------------------
        cursor.proxima_linha()
        lajes = []
        for pav in projeto.lajes:
            if abs(pav.cota - z) > 1e-6 or not pav.passou or pav.resultado is None:
                continue
            destino = temp / "lajes" / f"{z:g}.dxf"
            destino.parent.mkdir(parents=True, exist_ok=True)
            try:
                dxf_laje.exportar(pav.resultado, str(destino))
            except Exception:                                # noqa: BLE001
                continue
            if destino.exists():
                v = vista_importada(destino, f"LAJES — {rotulo}")
                if v is not None:
                    lajes.append(v)
        if lajes:
            grupos.append(Grupo(f"ARMAÇÃO DAS LAJES — {rotulo}", lajes))

        # -- vigas ---------------------------------------------------------
        cursor.proxima_linha()
        vigas = []
        for vv in sorted(projeto.vigas, key=lambda v: _ordem_natural(v.nome)):
            if not vv.passou or not vv.barras:
                continue
            b = modelo.barras.get(vv.barras[0])
            if b is None or abs(float(modelo.ponto(b.no_i)[2]) - z) > 1e-6:
                continue
            try:
                arquivos = gravar_desenhos(vv.resultado, vv.nome, temp / "vigas",
                                           com_dxf=True, com_png=False)
            except Exception:                                # noqa: BLE001
                continue
            for a in arquivos:
                if isinstance(a, str) and a.endswith(".dxf") and Path(a).exists():
                    v = vista_importada(a, f"VIGA {vv.nome}")
                    if v is not None:
                        vigas.append(v)
                    break
        if vigas:
            grupos.append(Grupo(f"ARMAÇÃO DAS VIGAS — {rotulo}", vigas))

    # -- pilares, por prumada e de baixo para cima ---------------------------
    cursor.proxima_linha()
    por_barra: dict[str, list] = {}
    for v in projeto.pilares:
        por_barra.setdefault(v.barra, []).append(v)
    ordem = [l.barra for p in projeto.prumadas for l in p.lances] or \
        sorted(por_barra, key=_ordem_natural)
    pilares = []
    (temp / "pilares").mkdir(parents=True, exist_ok=True)
    for barra in ordem:
        escolhida, _ = _arranjo_adotado(por_barra.get(barra, []))
        if escolhida is None:
            continue
        destino = temp / "pilares" / f"{barra}.dxf"
        try:
            dxf_pilar.exportar(escolhida.resultado, str(destino))
        except Exception:                                    # noqa: BLE001
            continue
        if destino.exists():
            v = vista_importada(destino, f"PILAR {barra}")
            if v is not None:
                pilares.append(v)
    if pilares:
        grupos.append(Grupo("ARMAÇÃO DOS PILARES", pilares))

    # -- quadro de quantidades ---------------------------------------------
    cursor.proxima_linha()
    caixa = desenhar_quadro(msp, projeto, cursor.x, cursor.y, 50)
    if caixa is not None:
        cursor.ocupar(caixa)
        grupos.append(Grupo("QUADRO DE QUANTIDADES",
                            [escolher_escala(Vista("QUADRO DE QUANTIDADES",
                                                   caixa, 50))],
                            ["Detalhe por elemento e por bitola no quadro de "
                             "quantidades em Excel."]))

    folhas = [f for g in grupos for f in empacotar(g)]
    for i, f in enumerate(folhas, 1):
        f.numero, f.total = i, len(folhas)
    return folhas


def documento(projeto):
    """``(doc, folhas)``: o DXF montado, ainda não gravado."""
    try:
        import ezdxf
    except ImportError as erro:                          # pragma: no cover
        raise RuntimeError("para gravar as pranchas é preciso o ezdxf: "
                           "py -m pip install ezdxf") from erro
    from .. import __version__

    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 5                          # centímetros
    if "PORTICOS" not in doc.styles:
        doc.styles.add("PORTICOS", font="arial.ttf")
    for camada, cor in CAMADAS_PAPEL + CAMADAS_FORMA:
        if camada not in doc.layers:
            doc.layers.add(camada, color=cor)
    doc.layers.get("PR-JANELA").dxf.plot = 0

    with tempfile.TemporaryDirectory(prefix="portico3d_pranchas_") as t:
        folhas = montar(projeto, doc, Path(t))
    # camadas que os desenhos usam sem declarar passam a existir
    for e in doc.modelspace():
        camada = e.dxf.get("layer", "0")
        if camada not in doc.layers:
            doc.layers.add(camada)
    for f in folhas:
        desenhar_folha(doc, f, projeto, __version__)
    if folhas and "Layout1" in doc.layouts:
        doc.layouts.delete("Layout1")
    return doc, folhas


def gerar(projeto, caminho) -> Path:
    """Grava o DXF com o modelo em verdadeira grandeza e as folhas."""
    doc, _ = documento(projeto)
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(destino))
    return destino


def sobreposicoes(folhas: list[Folha], folga: float = 0.0) -> list[tuple]:
    """Pares de textos do papel que se sobrepõem, e janelas que se tocam ou
    invadem o carimbo/notas ou saem da moldura — a conferência da prancha."""
    achados = []
    for f in folhas:
        t = f.textos
        for i in range(len(t)):
            for j in range(i + 1, len(t)):
                a, b = t[i], t[j]
                if not (a[2] + folga <= b[0] or b[2] + folga <= a[0]
                        or a[3] + folga <= b[1] or b[3] + folga <= a[1]):
                    achados.append((f.numero, "texto", a[4], b[4]))
        W, H = FORMATOS[f.formato]
        ox0, oy0, ox1, oy1 = obstaculo(f.formato, _altura_notas(f.notas))
        caixas = []
        for v, x, y in f.itens:
            c = (x, y - FAIXA_TITULO, x + v.largura, y + v.altura)
            if c[0] < MARGEM_ESQ - 1e-6 or c[1] < MARGEM - 1e-6 \
                    or c[2] > W - MARGEM + 1e-6 or c[3] > H - MARGEM + 1e-6:
                achados.append((f.numero, "fora da moldura", v.titulo, ""))
            if not (c[2] <= ox0 or ox1 <= c[0] or c[3] <= oy0 or oy1 <= c[1]):
                achados.append((f.numero, "sobre o carimbo", v.titulo, ""))
            for d, nome in caixas:
                if not (c[2] <= d[0] or d[2] <= c[0] or c[3] <= d[1]
                        or d[3] <= c[1]):
                    achados.append((f.numero, "janela", v.titulo, nome))
            caixas.append((c, v.titulo))
    return achados
