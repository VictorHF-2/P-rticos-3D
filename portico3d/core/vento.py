# -*- coding: utf-8 -*-
"""
vento.py
Forças de vento sobre o pórtico, pela ABNT NBR 6123.

Este módulo **não recalcula a norma do vento**: ele importa o
``nbr6123_core.py`` do programa NBR-6123 que já existe na pasta de programas,
e que é biblioteca de funções puras. O que se faz aqui é a parte que só o
modelo do pórtico sabe fazer — descobrir os pavimentos, a altura de cada um, a
largura frontal na direção do vento, e repartir a força resultante pelos nós.

É a primeira peça de integração entre programas, e antecipa o formato da fase
4: o solver não reimplementa o que outro programa já resolve; ele o chama.

Unidades: o ``nbr6123_core`` devolve a pressão dinâmica em N/m², e o solver
trabalha em kN. A conversão acontece num ponto só, marcado no código.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .modelo import CasoDeCarga, ErroDeModelo, Modelo

PASTA_NBR6123 = Path("NBR-6123") / "App"
NEWTON_POR_KN = 1000.0


def carregar_nbr6123():
    """Encontra e importa o motor de cálculo do programa NBR-6123.

    A busca sobe pelos diretórios acima deste arquivo até achar a pasta de
    programas que contém o NBR-6123. Falhando, o erro diz onde se procurou —
    integração que quebra em silêncio é pior do que integração que não existe.
    """
    tentativas = []
    for pasta in Path(__file__).resolve().parents:
        candidato = pasta / PASTA_NBR6123 / "nbr6123_core.py"
        tentativas.append(candidato)
        if candidato.exists():
            destino = str(candidato.parent)
            if destino not in sys.path:
                sys.path.insert(0, destino)
            import nbr6123_core
            return nbr6123_core

    procurado = "\n  ".join(str(t) for t in tentativas[:6])
    raise ErroDeModelo(
        "não encontrei o motor de cálculo do NBR-6123. Procurei em:\n  "
        f"{procurado}")


@dataclass
class Nivel:
    z: float
    altura_tributaria: float
    s2: float
    vk: float
    q: float
    area: float
    forca: float
    nos: list[str] = field(default_factory=list)


@dataclass
class RelatorioVento:
    """O caminho inteiro do cálculo, para a memória."""

    v0: float
    s1: float
    s3: float
    categoria: str
    classe: str
    altura: float
    largura_frontal: float
    profundidade: float
    ca: float
    ca_extrapolado: bool
    altura_para_a_fundacao: float = 0.0
    niveis: list[Nivel] = field(default_factory=list)

    @property
    def forca_total(self) -> float:
        """Força efetivamente aplicada na estrutura.

        É menor que ``Ca·q·ℓ1·h`` pela faixa de meio pé-direito junto ao chão,
        cuja carga vai direto para a fundação sem solicitar a estrutura. A
        altura dessa faixa está em ``altura_para_a_fundacao``, declarada e não
        omitida.
        """
        return sum(n.forca for n in self.niveis)

    def __str__(self) -> str:
        linhas = [
            f"vento V0={self.v0:.1f} m/s  S1={self.s1:.3f}  S3={self.s3:.3f}  "
            f"categoria {self.categoria}  classe {self.classe}",
            f"  h={self.altura:.2f} m  frontal={self.largura_frontal:.2f} m  "
            f"profundidade={self.profundidade:.2f} m  Ca={self.ca:.3f}"
            + ("  (fora do ábaco, extrapolado)" if self.ca_extrapolado else ""),
        ]
        for n in self.niveis:
            linhas.append(
                f"  z={n.z:6.2f}  htrib={n.altura_tributaria:5.2f}  "
                f"S2={n.s2:.3f}  Vk={n.vk:6.2f}  q={n.q:.4f}  "
                f"A={n.area:7.2f}  F={n.forca:8.3f}")
        linhas.append(
            f"  força total aplicada = {self.forca_total:.3f}  "
            f"(a faixa de {self.altura_para_a_fundacao:.2f} m junto ao chão "
            "vai direto para a fundação)")
        return "\n".join(linhas)


def _niveis_do_modelo(modelo: Modelo, tolerancia: float = 1e-6
                      ) -> tuple[float, list[tuple[float, list[str]]]]:
    """Agrupa os nós por cota e devolve a base e os níveis acima dela."""
    por_cota: dict[float, list[str]] = {}
    for nome, no in modelo.nos.items():
        chave = round(no.z / tolerancia) * tolerancia if tolerancia else no.z
        por_cota.setdefault(chave, []).append(nome)

    cotas = sorted(por_cota)
    base = cotas[0]
    return base, [(z, por_cota[z]) for z in cotas if z > base + tolerancia]


def _dimensoes_em_planta(modelo: Modelo, direcao: tuple[float, float]
                         ) -> tuple[float, float]:
    """Largura frontal e profundidade da caixa envolvente, na direção dada.

    Para uma caixa de lados Lx e Ly e vento na direção ``d``, a projeção sobre
    o plano perpendicular ao vento vale ``Lx·|dy| + Ly·|dx|``, e a profundidade
    na direção do vento vale ``Lx·|dx| + Ly·|dy|``. Com vento em X isso devolve
    Ly e Lx, como se espera.
    """
    xs = [no.x for no in modelo.nos.values()]
    ys = [no.y for no in modelo.nos.values()]
    Lx, Ly = max(xs) - min(xs), max(ys) - min(ys)
    dx, dy = abs(direcao[0]), abs(direcao[1])
    return Lx * dy + Ly * dx, Lx * dx + Ly * dy


def _conferir_abaco(razao_planta: float, razao_altura: float, largura: float,
                    profundidade: float, altura: float) -> None:
    """Confere que o ábaco foi consultado nos eixos que a norma manda.

    O ábaco da Figura 4 tem abscissa ℓ1/ℓ2 e ordenada h/ℓ1, com ℓ1 a largura
    frontal. Se a chamada inverter os dois primeiros argumentos, as duas
    relações saem trocadas e o Ca vem de outro ponto do gráfico.
    """
    esperado_planta = largura / profundidade
    esperado_altura = altura / largura
    if (abs(razao_planta - esperado_planta) > 1e-9 * max(esperado_planta, 1.0)
            or abs(razao_altura - esperado_altura)
            > 1e-9 * max(esperado_altura, 1.0)):
        raise ErroDeModelo(
            "o ábaco de arrasto foi consultado com as relações trocadas: "
            f"veio ℓ1/ℓ2={razao_planta:.4f} e h/ℓ1={razao_altura:.4f}, mas a "
            f"norma pede {esperado_planta:.4f} e {esperado_altura:.4f}, com "
            "ℓ1 a largura frontal (NBR 6123:2023, item 3.2)")


def forcas_de_vento(modelo: Modelo, destino: CasoDeCarga, v0: float,
                    direcao: tuple[float, float], categoria: str = "II",
                    grupo_s3: str = "3", s1: float = 1.0,
                    vedacao: bool = False, alta_turbulencia: bool = False,
                    ca: float | None = None) -> RelatorioVento:
    """Acrescenta ao caso ``destino`` as forças de arrasto do vento.

    ``v0`` é a velocidade básica em m/s, tirada das isopletas; ``direcao`` é um
    versor horizontal; ``categoria`` é a de rugosidade do terreno (I a V) e
    ``grupo_s3`` o grupo do fator estatístico. ``ca`` permite impor o
    coeficiente de arrasto em vez de tirá-lo do ábaco.

    A força de cada pavimento vale ``Ca·q(z)·Ae``, com ``Ae`` a área frontal
    tributária daquele nível, e é repartida igualmente entre os nós da cota que
    ainda podem se deslocar na horizontal.
    """
    C = carregar_nbr6123()

    norma = math.hypot(float(direcao[0]), float(direcao[1]))
    if norma < 1e-12:
        raise ErroDeModelo("a direção do vento não pode ser nula")
    d = (float(direcao[0]) / norma, float(direcao[1]) / norma)

    base, niveis = _niveis_do_modelo(modelo)
    if not niveis:
        raise ErroDeModelo(
            "não há nó acima da base: o vento precisa de uma estrutura com "
            "altura")

    altura = max(no.z for no in modelo.nos.values()) - base
    largura_frontal, profundidade = _dimensoes_em_planta(modelo, d)
    if largura_frontal <= 0.0 or profundidade <= 0.0:
        raise ErroDeModelo(
            "a projeção em planta é degenerada: um pórtico plano precisa da "
            "largura frontal informada por outro caminho")

    classe = C.classe_por_dimensao(max(largura_frontal, altura))
    s3 = C.calc_s3(grupo_s3, vedacao)

    extrapolado = False
    if ca is None:
        # ATENÇÃO à ordem dos dois primeiros argumentos: o primeiro é
        # sempre a largura frontal (perpendicular ao vento) e o segundo a
        # profundidade (na direção do vento), conforme ``nbr6123_core.
        # coef_arrasto`` e a NBR 6123:2023, item 3.2 (ℓ1 = largura,
        # ℓ2 = profundidade) — os dois já concordam entre si desde que o
        # docstring daquele módulo foi corrigido (estava trocado antes). A
        # conferência ``vento: as relações do ábaco`` logo abaixo continua
        # existindo como trava independente contra uma futura inversão.
        ca, razao_planta, razao_altura, extrapolado = C.coef_arrasto(
            largura_frontal, profundidade, altura, alta_turbulencia)
        _conferir_abaco(razao_planta, razao_altura, largura_frontal,
                        profundidade, altura)

    cotas = [z for z, _ in niveis]
    relatorio = RelatorioVento(v0, s1, s3, categoria, classe, altura,
                               largura_frontal, profundidade, ca, extrapolado,
                               altura_para_a_fundacao=(cotas[0] - base) / 2.0)

    for i, (z, nos) in enumerate(niveis):
        inferior = cotas[i - 1] if i > 0 else base
        superior = cotas[i + 1] if i + 1 < len(cotas) else z
        altura_tributaria = (z - inferior) / 2.0 + (superior - z) / 2.0

        s2 = C.calc_s2(categoria, classe, z - base)
        vk = C.calc_vk(v0, s1, s2, s3)
        q = C.calc_q(vk) / NEWTON_POR_KN          # N/m² para kN/m²
        area = largura_frontal * altura_tributaria
        forca = C.calc_forca(q, ca, area)

        moveis = [no for no in nos
                  if not (modelo.apoios.get(no) is not None
                          and modelo.apoios[no].ux and modelo.apoios[no].uy)]
        if moveis:
            quinhao = forca / len(moveis)
            for no in moveis:
                destino.nodal(no, fx=quinhao * d[0], fy=quinhao * d[1])

        relatorio.niveis.append(Nivel(z, altura_tributaria, s2, vk, q, area,
                                      forca, moveis))

    return relatorio
