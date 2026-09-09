# -*- coding: utf-8 -*-
"""
dimensionar.py
Orquestra o cálculo completo do lance de pilar: esbeltez, segunda ordem local,
situações de cálculo, dimensionamento da seção, escolha do arranjo de barras,
armadura transversal, ancoragem e a verificação final da flexão composta
oblíqua.

É o único módulo que conhece todos os demais; a interface gráfica e os módulos
de saída consomem apenas o :class:`ResultadoPilar` daqui.

A cadeia de decisão, em ordem:

1. **Esbeltez** por direção decide se a segunda ordem local entra;
2. **segunda ordem** dá ``e2`` por direção, pelos métodos aproximados;
3. as **situações de cálculo** combinam ``e1``, o momento mínimo e ``e2`` nas
   seções de extremidade e do meio;
4. o **roteiro dos casos fechados** dá a armadura de partida em cada direção,
   na seção retangular;
5. a **busca do arranjo** percorre os candidatos em ordem crescente de área e
   fica no primeiro que atende ao item 18.4.2 e à interação do item 17.2.5 em
   **todas** as situações;
6. o **motor seccional** confere o arranjo escolhido contra a envoltória de
   momentos resistentes, sem o expoente aproximado.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import ancoragem as anc
from . import arranjo as arr_mod
from . import avisos as av
from . import cisalhamento as cis_mod
from . import esbeltez as esb_mod
from . import estribos as est_mod
from . import flexocompressao as fc
from . import seccional as sc
from . import segunda_ordem as so_mod
from .arranjo import Arranjo
from .esbeltez import Esbeltez
from .materiais import RHO_MAXIMO, area_barra, rho_minimo
from .modelo import Pilar
from .segunda_ordem import SegundaOrdem, Situacao

#: Bitolas usadas para estimar ``d'`` antes de o arranjo estar escolhido.
PHI_ESTIMADO = 16.0
PHI_ESTRIBO_ESTIMADO = 6.3

#: Fatias na varredura de candidatos e na verificação final.
FATIAS_BUSCA = 60
FATIAS_FINAL = 160


# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------

@dataclass
class VerificacaoSituacao:
    """Verificação da seção armada contra uma situação de cálculo."""

    situacao: Situacao
    MRd_xx: float = 0.0          # kN·cm, flexão composta normal em x
    MRd_yy: float = 0.0
    razao_x: float = 0.0
    razao_y: float = 0.0
    interacao: float = 0.0       # soma da expressão do item 17.2.5
    MSd: float = 0.0             # kN·cm, módulo do momento solicitante
    #: kN·cm, resistente na mesma direção do momento solicitante. Com dois
    #: limites (fig. 6.1b de CADAMURO JÚNIOR, 1997 -- possível em seção
    #: assimétrica sob normal alta), este é o **superior**; o inferior fica
    #: em ``MRd_envoltoria_inferior``.
    MRd_envoltoria: float = 0.0
    MRd_envoltoria_inferior: float = 0.0
    razao_envoltoria: float = 0.0
    #: a direção do momento solicitante está fora do alcance da envoltória:
    #: nenhuma linha neutra, para esta normal, produz momento resistente
    #: naquela direção (item 5.5 do mesmo trabalho). Não é uma verificação
    #: sem resposta -- é reprovação: a seção não tem como equilibrar
    #: **nenhum** momento naquela direção com essa força normal.
    envoltoria_inatingivel: bool = False
    dominio: str = ""
    theta_ln: float = 0.0        # rad, direção da linha neutra no ELU

    @property
    def ok_interacao(self) -> bool:
        return self.interacao <= 1.0 + 1e-6

    @property
    def ok_envoltoria(self) -> bool:
        if self.envoltoria_inatingivel:
            return False
        if self.MRd_envoltoria_inferior > 0.0:
            return (self.MRd_envoltoria_inferior - 1e-6 <= self.MSd
                    <= self.MRd_envoltoria + 1e-6)
        return self.razao_envoltoria <= 1.0 + 1e-6

    @property
    def ok(self) -> bool:
        return self.ok_interacao and self.ok_envoltoria

    @property
    def fs(self) -> float:
        """Fator de segurança MRd/MSd -- o inverso de ``razao_envoltoria``.

        Reprovada por não ter momento resistente algum naquela direção
        (``envoltoria_inatingivel``), o fator é zero: não é um número grande
        que ninguém vai ler como "seguro", é a reprovação mesma. Sem momento
        solicitante (``MSd`` nulo), não há risco a medir, e o fator sobe a
        infinito -- caso raro, de compressão praticamente centrada.

        Havendo **dois ramos** de envoltória na mesma direção (fig. 6.1b de
        CADAMURO JÚNIOR, 1997 -- possível em seção assimétrica sob normal
        alta), a seção só resiste **entre** eles, e a margem é a distância ao
        ramo mais próximo, não só ao superior: um ``MSd`` abaixo do ramo
        inferior reprova, e o fator tem de acompanhar. Sem isso a linha
        reprovava exibindo folga confortável.
        """
        if self.envoltoria_inatingivel:
            return 0.0
        if self.razao_envoltoria <= 1e-12:
            return float("inf")
        folga = 1.0 / self.razao_envoltoria
        if self.MRd_envoltoria_inferior > 0.0 and self.MSd > 1e-9:
            folga = min(folga, self.MSd / self.MRd_envoltoria_inferior)
        return folga


@dataclass
class Conferencia:
    """Confronto entre o roteiro dos casos fechados e o motor seccional."""

    grandeza: str
    fechado: float
    seccional: float
    tolerancia: float = 0.03

    @property
    def divergencia(self) -> float:
        ref = max(abs(self.fechado), abs(self.seccional), 1e-9)
        return abs(self.fechado - self.seccional) / ref

    @property
    def ok(self) -> bool:
        return self.divergencia <= self.tolerancia


@dataclass
class VerificacaoMomentoMinimo:
    """Verificação isolada do momento mínimo (item 11.3.3.4.3), pelo método
    da envoltória mínima do item 3.1 da apostila de referência: duas
    análises independentes à flexão composta normal, uma por direção, com o
    momento mínimo de 1ª ordem (amplificado pela 2ª ordem quando a esbeltez
    pedir) confrontado com o momento resistente **naquela direção apenas**
    -- sem combinar com a outra direção nem com o momento real.

    Só existe quando ``pilar.config.momento_minimo_metodo == "envoltoria"``;
    no método "planilha" o momento mínimo já entra como piso das situações
    de cálculo, e esta verificação fica de fora.
    """

    Msd_x: float = 0.0    # kN·cm, Md,tot,min na direção x
    MRd_x: float = 0.0    # kN·cm, resistente à flexão composta normal em x
    Msd_y: float = 0.0
    MRd_y: float = 0.0

    @property
    def ok_x(self) -> bool:
        return self.Msd_x <= self.MRd_x + 1e-6

    @property
    def ok_y(self) -> bool:
        return self.Msd_y <= self.MRd_y + 1e-6

    @property
    def ok(self) -> bool:
        return self.ok_x and self.ok_y

    @property
    def fs_x(self) -> float:
        return self.MRd_x / self.Msd_x if self.Msd_x > 1e-9 else float("inf")

    @property
    def fs_y(self) -> float:
        return self.MRd_y / self.Msd_y if self.Msd_y > 1e-9 else float("inf")


@dataclass
class ResultadoPilar:
    """Tudo o que o cálculo do lance produziu."""

    pilar: Pilar
    esbeltez: dict[str, Esbeltez] = field(default_factory=dict)
    segunda_ordem: dict[str, SegundaOrdem] = field(default_factory=dict)
    #: As situações que a verificação final de fato conferiu -- os três
    #: pontos do item 15.8.3.3.5 ou, com a varredura contínua ligada, os
    #: pontos varridos ao longo da altura.
    situacoes: list[Situacao] = field(default_factory=list)
    #: As situações que deram a **armadura de partida** (sempre os três
    #: pontos, mesmo com a varredura ligada: a busca do arranjo é um palpite
    #: barato de propósito). Iguais a ``situacoes`` no critério dos três
    #: pontos; guardadas à parte só para a varredura não apagar a
    #: procedência da escolha do arranjo.
    situacoes_partida: list[Situacao] = field(default_factory=list)
    governante: Situacao | None = None
    dim_fechado: dict[str, fc.Dimensionamento] = field(default_factory=dict)
    As_necessaria: float = 0.0
    As_minima: float = 0.0
    camadas_necessarias: dict[str, float] = field(default_factory=dict)
    nu: float = 0.0
    arranjo: Arranjo | None = None
    estribos: est_mod.Estribos | None = None
    ancoragem: anc.Ancoragem | None = None
    verificacoes: list[VerificacaoSituacao] = field(default_factory=list)
    #: Fator de segurança em três cotas físicas do lance -- "topo", "meio"
    #: e "base" --, para leitura rápida. É um recorte informativo de
    #: ``verificacoes``: a reprovação do lance continua vindo de lá, e não
    #: daqui.
    verificacoes_z: dict[str, VerificacaoSituacao] = field(
        default_factory=dict)
    #: Verificação isolada do momento mínimo pela envoltória do item 3.1 da
    #: apostila (``None`` quando ``momento_minimo_metodo == "planilha"``).
    momento_minimo: VerificacaoMomentoMinimo | None = None
    #: Verificação à força cortante por direção (item 17.4, modelo I).
    #: Sempre presente; com Vd = 0 ela apenas declara que o item não se
    #: aplica e que o estribo saiu do 18.4.3.
    cisalhamento: dict = field(default_factory=dict)
    conferencias: list[Conferencia] = field(default_factory=list)
    secao_discreta: sc.SecaoDiscreta | None = None
    avisos: list[str] = field(default_factory=list)

    # -- sínteses -----------------------------------------------------------
    @property
    def erros(self) -> list[str]:
        return av.separar(self.avisos)[0]

    @property
    def construtivos(self) -> list[str]:
        return av.separar(self.avisos)[1]

    @property
    def ok(self) -> bool:
        """Verdadeiro quando nada foi classificado como erro.

        Deliberadamente não é uma lista curada de verificações: qualquer aviso
        de nível ``erro``, venha de onde vier, reprova o lance. Uma lista
        curada não acompanha verificação nova, e é assim que um pilar passa
        aprovado com uma checagem recém-escrita reprovando em silêncio.
        """
        return not self.erros

    @property
    def verificacao_critica(self) -> VerificacaoSituacao | None:
        if not self.verificacoes:
            return None
        return max(self.verificacoes, key=lambda v: v.interacao)

    @property
    def taxa(self) -> float:
        return self.arranjo.As / self.pilar.secao.area if self.arranjo else 0.0

    @property
    def massa_total(self) -> float:
        """Massa de aço do lance, kg."""
        m = 0.0
        if self.arranjo:
            m += self.arranjo.massa(self.pilar.lance.altura
                                    + (self.ancoragem.l0c
                                       if self.ancoragem else 0.0))
        if self.estribos:
            m += self.estribos.massa
        return m


# ---------------------------------------------------------------------------
# Etapas
# ---------------------------------------------------------------------------

def _secao_direcao(pilar: Pilar, direcao: str, d_linha: float
                   ) -> fc.Retangular:
    """Seção retangular vista da direção pedida."""
    h = pilar.secao.altura(direcao)
    b = pilar.secao.altura("y" if direcao == "x" else "x")
    return fc.Retangular(b=b, h=h, d_linha=d_linha, concreto=pilar.concreto,
                         aco=pilar.aco)


def _armadura_necessaria(pilar: Pilar, situacoes: list[Situacao],
                         d_linha: float
                         ) -> tuple[dict[str, float],
                                    dict[str, fc.Dimensionamento],
                                    list[str]]:
    """Armadura de partida pelo roteiro dos casos fechados.

    Percorre **todas** as situações e as duas direções, e não apenas a
    governante: o critério do maior módulo de excentricidade escolhe bem a
    situação para o croqui, mas as duas direções têm alturas diferentes e a
    situação de maior módulo não é sempre a que pede mais aço.

    A armadura devolvida é a de **uma camada por direção**, e não um total.
    A distinção importa na hora de filtrar arranjos: a camada da flexão em x
    é formada pelas barras das faces verticais -- ``ny`` delas --, e a da
    flexão em y pelas ``nx`` das faces horizontais. Somar tudo num total só
    perderia essa correspondência e deixaria passar arranjo com barras demais
    de um lado e de menos do outro.
    """
    avisos: list[str] = []
    melhores: dict[str, fc.Dimensionamento] = {}
    camadas: dict[str, float] = {"x": 0.0, "y": 0.0}
    if not pilar.secao.tem_casos_fechados:
        avisos.append(av.construtivo(
            f"A seção {pilar.secao.tipo} não tem solução fechada de "
            f"flexo-compressão: o roteiro FC1-FC4 / FT1-FT4 pressupõe seção "
            f"retangular com duas camadas de armadura. O dimensionamento aqui "
            f"é feito **inteiramente pelo motor seccional**, que integra o "
            f"diagrama parábola-retângulo sobre o contorno real."))
        return camadas, melhores, avisos

    for s in situacoes:
        for direcao, Md in (("x", s.Mx), ("y", s.My)):
            sec = _secao_direcao(pilar, direcao, d_linha)
            if pilar.config.armadura_simetrica:
                d = fc.dimensionar_simetrica(sec, pilar.Nd, Md, direcao)
            else:
                d = fc.dimensionar_assimetrica(sec, pilar.Nd, Md, direcao)
            d.avisos = [av.prefixar(a, f"{s.nome}, direção {direcao}: ")
                        for a in d.avisos]
            camada = max(d.As1, d.As2)
            anterior = melhores.get(direcao)
            if anterior is None or camada > max(anterior.As1, anterior.As2):
                melhores[direcao] = d
            camadas[direcao] = max(camadas[direcao], camada)
            avisos.extend(d.avisos)
    return camadas, melhores, avisos


def _situacao_extremo_real(pilar: Pilar, esb: dict[str, Esbeltez],
                           nome: str, mx_bruto: float, my_bruto: float
                           ) -> Situacao:
    """Situação num extremo físico do lance, com o sinal real do momento.

    É diferente das situações de ``segunda_ordem.situacoes``: aquelas usam
    ``M1d,A`` -- o maior módulo entre topo e base, sem ligar para qual
    extremo é -- porque é o que o item 15.8.2 pede para o alfa_b. Para
    reportar o fator de segurança **por cota física** (topo e base, cada
    um com o momento que de fato atua ali), a situação tem de vir do
    momento daquela ponta específica, não do maior dos dois.
    """
    Nd = pilar.Nd
    f = pilar.fator_esforcos
    ex = (f * mx_bruto) / Nd if abs(Nd) > 1e-9 else 0.0
    ey = (f * my_bruto) / Nd if abs(Nd) > 1e-9 else 0.0
    # No método "envoltoria" o momento mínimo é verificado à parte (ver
    # _verificar_momento_minimo), e não como piso destas cotas físicas; no
    # método "planilha" o piso continua entrando aqui, como sempre entrou.
    planilha = pilar.config.momento_minimo_metodo == "planilha"
    Mx = so_mod.momento_com_piso(Nd, ex, esb["x"].M1d_min if planilha else 0.0)
    My = so_mod.momento_com_piso(Nd, ey, esb["y"].M1d_min if planilha else 0.0)
    return Situacao(nome=nome, posicao="extremo", ex=ex, ey=ey, Mx=Mx, My=My,
                    descricao=f"{nome} do pilar, momento real da entrada "
                    f"(não o M1d,A)")


def _verificar(secao: sc.SecaoDiscreta, pilar: Pilar, s: Situacao,
               rigorosa: bool) -> VerificacaoSituacao:
    """Verifica a seção armada contra uma situação de cálculo.

    A verificação de projeto é a expressão de interação do item 17.2.5, com
    ``MRd,xx`` e ``MRd,yy`` obtidos do equilíbrio da seção com o arranjo real.
    A verificação **rigorosa** vai além: acha o momento resistente na própria
    direção do momento solicitante, sem expoente nenhum, e é a que responde à
    exigência do item 3.3.3.4 da apostila -- que a composição dos momentos
    caia dentro da envoltória de momentos resistentes.
    """
    Nd = pilar.Nd
    v = VerificacaoSituacao(situacao=s)
    v.MRd_xx = sc.momento_resistente_uniaxial(secao, Nd, "x",
                                              1.0 if s.Mx >= 0 else -1.0)
    v.MRd_yy = sc.momento_resistente_uniaxial(secao, Nd, "y",
                                              1.0 if s.My >= 0 else -1.0)
    alfa = pilar.alfa_interacao
    v.razao_x = abs(s.Mx) / v.MRd_xx if v.MRd_xx > 1e-9 else float("inf")
    v.razao_y = abs(s.My) / v.MRd_yy if v.MRd_yy > 1e-9 else float("inf")
    v.interacao = (v.razao_x ** alfa + v.razao_y ** alfa
                   if math.isfinite(v.razao_x) and math.isfinite(v.razao_y)
                   else float("inf"))
    v.MSd = math.hypot(s.Mx, s.My)

    if rigorosa and v.MSd > 1e-9:
        estados = sc.estados_na_direcao(secao, Nd, math.atan2(s.My, s.Mx))
        if not estados:
            # Nenhuma linha neutra produz momento resistente nessa direção
            # para esta normal -- item 5.5: a seção assimétrica sob essa
            # curvatura tem a direção do momento resistente restrita a uma
            # faixa que não inclui a do momento solicitante. Não é "sem
            # dado" -- é reprovação.
            v.envoltoria_inatingivel = True
            v.razao_envoltoria = float("inf")
        else:
            maior = estados[-1]
            v.MRd_envoltoria = maior.M
            v.dominio = maior.plano.dominio
            v.theta_ln = maior.theta
            if len(estados) > 1:
                # fig. 6.1b: duas direções de linha neutra alcançam a mesma
                # direção de momento; a seção só resiste entre as duas.
                v.MRd_envoltoria_inferior = estados[0].M
            v.razao_envoltoria = (v.MSd / maior.M if maior.M > 1e-9
                                  else float("inf"))
    return v


def _momento_total_minimo(pilar: Pilar, esb: Esbeltez) -> float:
    """``Md,tot,min`` numa direção: o mínimo de 1ª ordem, amplificado pela 2ª
    ordem quando a esbeltez pedir.

    Sempre pelo método da curvatura aproximada (15.8.3.3.2), com
    ``alfa_b = 1`` -- é o que o item 3.1 da apostila manda quando "o pilar
    apresentar momentos menores do que o momento mínimo": aqui a peça inteira
    *é* o caso, MA = MB = MC = M1d,min, sem variação ao longo do lance.
    """
    if not esb.considerar_2a_ordem:
        return esb.M1d_min
    prop = pilar.secao.propriedades()
    nu = so_mod.forca_normal_adimensional(abs(pilar.Nd), prop.area,
                                          pilar.concreto.fcd_kNcm2)
    curv = so_mod.curvatura_aproximada(esb.h, nu)
    e2 = so_mod.e2_por_curvatura(esb.le, curv)
    return esb.M1d_min + abs(pilar.Nd) * e2


def _verificar_momento_minimo(secao: sc.SecaoDiscreta, pilar: Pilar,
                              esb: dict[str, Esbeltez]
                              ) -> VerificacaoMomentoMinimo:
    """Verificação isolada do momento mínimo pela envoltória mínima (item 3.1
    da apostila): duas análises à flexão composta normal, uma por direção,
    sem combinar com o momento real nem com a outra direção -- é o que a
    apostila descreve como "duas análises à flexão composta normal,
    calculadas de forma isolada e com momentos fletores mínimos de 1ª ordem
    atuantes nos extremos do pilar, nas suas direções principais".
    """
    Nd = pilar.Nd
    v = VerificacaoMomentoMinimo()
    v.Msd_x = _momento_total_minimo(pilar, esb["x"])
    v.Msd_y = _momento_total_minimo(pilar, esb["y"])
    v.MRd_x = sc.momento_resistente_uniaxial(secao, Nd, "x", 1.0)
    v.MRd_y = sc.momento_resistente_uniaxial(secao, Nd, "y", 1.0)
    return v


def _testar_arranjo(pilar: Pilar, a: Arranjo, situacoes: list[Situacao],
                    nu: float, As_necessaria: float, fatias: int
                    ) -> tuple[bool, list[VerificacaoSituacao], list[str]]:
    """Roda as verificações de um arranjo candidato. Barato de propósito."""
    avisos = arr_mod.verificar(a, pilar, nu, As_necessaria)
    if any(av.nivel_de(x) == av.ERRO for x in avisos):
        return False, [], avisos
    secao = sc.montar(pilar.secao, a.barras, pilar.concreto, pilar.aco,
                      fatias)
    verifs = [_verificar(secao, pilar, s, rigorosa=False) for s in situacoes]
    return all(v.ok_interacao for v in verifs), verifs, avisos


def _escolher_arranjo(pilar: Pilar, situacoes: list[Situacao], nu: float,
                      As_necessaria: float, camadas: dict[str, float]
                      ) -> tuple[Arranjo | None, list[str]]:
    """Percorre os candidatos e devolve o primeiro que atende a tudo.

    Os candidatos vêm ordenados por área total de aço, de modo que o primeiro
    aprovado é o mais econômico do conjunto -- não o de menos barras nem o de
    menor bitola.
    """
    cfg = pilar.config
    ultimo: list[str] = []
    for phi, nx, ny, n in arr_mod.candidatos(pilar.secao,
                                             cfg.bitolas_permitidas):
        area = area_barra(phi)
        As = n * area
        if As < As_necessaria - 1e-9:
            continue
        if As / pilar.secao.area > RHO_MAXIMO + 1e-9:
            continue
        # A camada da flexão em x são as ny barras das faces verticais; a da
        # flexão em y, as nx das faces horizontais. Só vale na retangular --
        # nas demais o roteiro fechado não roda e camadas vem zerado.
        if nx and ny:
            if (ny * area < camadas.get("x", 0.0) - 1e-9
                    or nx * area < camadas.get("y", 0.0) - 1e-9):
                continue
        phi_t = pilar.armadura.phi_estribo or est_mod.bitola_minima(phi)
        a = arr_mod.montar(pilar.secao, pilar.cobrimento(phi, phi_t),
                           phi_t, phi, nx, ny, n)
        if not a.cabe:
            continue
        passou, _, avisos = _testar_arranjo(pilar, a, situacoes, nu,
                                            As_necessaria, FATIAS_BUSCA)
        ultimo = avisos
        if passou:
            return a, []
    return None, ultimo


def arranjo_imposto(pilar: Pilar) -> Arranjo:
    """Monta o arranjo diretamente do que foi informado, sem buscar nada.

    Público porque a pré-visualização da aba de entrada usa a mesma conta
    para desenhar as barras no modo "Verificar" antes mesmo de calcular --
    duplicar essa lógica ali divergiria da primeira vez que uma delas
    mudasse.
    """
    a = pilar.armadura
    phi_t = a.phi_estribo or est_mod.bitola_minima(a.phi)
    return arr_mod.montar(pilar.secao, pilar.cobrimento(a.phi, phi_t),
                          phi_t, a.phi, a.nx, a.ny,
                          a.n_barras or pilar.numero_de_barras())


# ---------------------------------------------------------------------------
# Cálculo completo
# ---------------------------------------------------------------------------

def dimensionar(pilar: Pilar) -> ResultadoPilar:
    """Calcula o lance de pilar por inteiro."""
    res = ResultadoPilar(pilar=pilar)
    res.avisos.extend(pilar.validar())

    # -- 1. esbeltez e segunda ordem ---------------------------------------
    for direcao in ("x", "y"):
        e = esb_mod.analisar(pilar, direcao)
        res.esbeltez[direcao] = e
        res.avisos.extend(av.prefixar(a, f"Direção {direcao}: ")
                          for a in e.avisos)
    for direcao in ("x", "y"):
        s = so_mod.analisar(pilar, res.esbeltez[direcao])
        res.segunda_ordem[direcao] = s
        res.avisos.extend(av.prefixar(a, f"Direção {direcao}: ")
                          for a in s.avisos)

    # -- 2. situações de cálculo -------------------------------------------
    res.situacoes = so_mod.situacoes(pilar, res.esbeltez, res.segunda_ordem)
    res.situacoes_partida = res.situacoes
    res.governante = so_mod.governante(res.situacoes)

    prop = pilar.secao.propriedades()
    res.nu = so_mod.forca_normal_adimensional(abs(pilar.Nd), prop.area,
                                              pilar.concreto.fcd_kNcm2)
    rho_min = rho_minimo(res.nu, pilar.concreto, pilar.aco)
    res.As_minima = rho_min * prop.area

    # -- 3. armadura de partida pelos casos fechados -----------------------
    phi_est = pilar.armadura.phi or PHI_ESTIMADO
    phi_t_est = pilar.armadura.phi_estribo or PHI_ESTRIBO_ESTIMADO
    d_linha = (pilar.armadura.d_linha_x
               or arr_mod.recuo_da_barra(
                   pilar.cobrimento(phi_est, phi_t_est), phi_t_est,
                   phi_est))
    camadas, dim_fechado, avisos_fc = _armadura_necessaria(
        pilar, res.situacoes, d_linha)
    res.dim_fechado = dim_fechado
    res.camadas_necessarias = camadas
    res.avisos.extend(avisos_fc)
    res.As_necessaria = max(2.0 * max(camadas.values(), default=0.0),
                            res.As_minima)

    # -- 4. arranjo das barras ---------------------------------------------
    if pilar.armadura.modo == "imposto":
        res.arranjo = arranjo_imposto(pilar)
    else:
        escolhido, avisos_busca = _escolher_arranjo(
            pilar, res.situacoes, res.nu, res.As_necessaria, camadas)
        if escolhido is None:
            res.avisos.append(av.erro(
                "Nenhum arranjo de barras atendeu a todas as verificações "
                "com as bitolas permitidas. Aumente a seção, a classe do "
                "concreto ou libere bitolas maiores nos critérios."))
            res.avisos.extend(avisos_busca)
            return res
        res.arranjo = escolhido

    a = res.arranjo
    res.avisos.extend(arr_mod.verificar(a, pilar, res.nu, res.As_necessaria))

    # -- 5. recálculo dos casos fechados com o d' definitivo ---------------
    if pilar.secao.tem_casos_fechados:
        camadas_f, dim_final, _ = _armadura_necessaria(pilar,
                                                       res.situacoes_partida,
                                                       a.d_linha_x)
        if dim_final:
            res.dim_fechado = dim_final
            res.camadas_necessarias = camadas_f

    # -- 6. verificação final com o motor seccional ------------------------
    secao = sc.montar(pilar.secao, a.barras, pilar.concreto, pilar.aco,
                      FATIAS_FINAL)
    res.secao_discreta = secao
    # A busca do arranjo (passos 3 a 5, acima) usa sempre os três pontos do
    # item 15.8.3.3.5 -- ``situacoes_partida`` --, mesmo com a varredura
    # contínua ligada: ela é só um palpite inicial de armadura, barato de
    # propósito, e quem dá o veredito é esta verificação final. Ligada a
    # varredura, ``res.situacoes`` passa a ser o que de fato foi verificado,
    # e com ela a situação governante -- do contrário o relatório apontaria
    # como governante um ponto que a verificação final nem olhou.
    if pilar.config.verificacao_altura == "continua":
        res.situacoes = so_mod.situacoes_altura(pilar, res.esbeltez,
                                                res.segunda_ordem)
        res.governante = so_mod.governante(res.situacoes)
    res.verificacoes = [_verificar(secao, pilar, s, rigorosa=True)
                        for s in res.situacoes]
    for v in res.verificacoes:
        if not v.ok_interacao:
            res.avisos.append(av.erro(
                f"{v.situacao.nome}: a expressão de interação do item 17.2.5 "
                f"dá {v.interacao:.3f} > 1 -- "
                f"(MSd,x/MRd,xx)^{pilar.alfa_interacao:g} + "
                f"(MSd,y/MRd,yy)^{pilar.alfa_interacao:g} com "
                f"MSd,x = {v.situacao.Mx / 100:.1f} kN·m contra "
                f"MRd,xx = {v.MRd_xx / 100:.1f} kN·m e "
                f"MSd,y = {v.situacao.My / 100:.1f} kN·m contra "
                f"MRd,yy = {v.MRd_yy / 100:.1f} kN·m."))
        elif v.envoltoria_inatingivel:
            res.avisos.append(av.erro(
                f"{v.situacao.nome}: nenhuma linha neutra produz momento "
                f"resistente na direção do momento solicitante "
                f"({v.MSd / 100:.1f} kN·m) para Nd = {pilar.Nd:.0f} kN. Isso "
                f"acontece perto da compressão quase uniforme -- o momento "
                f"resistente tende a zero em toda direção -- e, em seção "
                f"assimétrica, também longe dali: a direção do momento "
                f"resistente pode ficar restrita a uma faixa que não cobre "
                f"os 360° (CADAMURO JÚNIOR, 1997, item 5.5). A expressão "
                f"aproximada do item 17.2.5 deu {v.interacao:.3f} sem "
                f"acusar isso, mas a seção não tem como equilibrar momento "
                f"algum nessa direção com essa força normal."))
        elif not v.ok_envoltoria:
            if v.MRd_envoltoria_inferior > 0.0:
                res.avisos.append(av.erro(
                    f"{v.situacao.nome}: o momento solicitante resultante "
                    f"({v.MSd / 100:.1f} kN·m) cai fora do intervalo "
                    f"[{v.MRd_envoltoria_inferior / 100:.1f}; "
                    f"{v.MRd_envoltoria / 100:.1f}] kN·m em que a envoltória "
                    f"admite momento naquela direção -- há duas linhas "
                    f"neutras que produzem momento resistente na mesma "
                    f"direção (CADAMURO JÚNIOR, 1997, fig. 6.1b), e a seção "
                    f"só resiste entre as duas."))
            else:
                res.avisos.append(av.erro(
                    f"{v.situacao.nome}: o momento solicitante resultante "
                    f"({v.MSd / 100:.1f} kN·m) está fora da envoltória de "
                    f"momentos resistentes ({v.MRd_envoltoria / 100:.1f} "
                    f"kN·m na mesma direção), embora a expressão aproximada "
                    f"do item 17.2.5 tenha dado {v.interacao:.3f}. Vale a "
                    f"envoltória: ela vem do equilíbrio da seção, e o "
                    f"expoente 1,2 é uma aproximação que aqui ficou contra "
                    f"a segurança."))

    # -- 6a. momento mínimo, verificado à parte (item 3.1 da apostila) -----
    if pilar.config.momento_minimo_metodo == "envoltoria":
        mm = _verificar_momento_minimo(secao, pilar, res.esbeltez)
        res.momento_minimo = mm
        if not mm.ok:
            lados = []
            if not mm.ok_x:
                lados.append(
                    f"x (Md,tot,min = {mm.Msd_x / 100:.1f} kN·m contra "
                    f"MRd,xx = {mm.MRd_x / 100:.1f} kN·m)")
            if not mm.ok_y:
                lados.append(
                    f"y (Md,tot,min = {mm.Msd_y / 100:.1f} kN·m contra "
                    f"MRd,yy = {mm.MRd_y / 100:.1f} kN·m)")
            res.avisos.append(av.erro(
                "Momento mínimo (item 11.3.3.4.3): a envoltória mínima do "
                "item 3.1 da apostila não está contida na envoltória "
                "resistente em " + " e ".join(lados) + ". É a verificação "
                "isolada da imperfeição geométrica local, à flexão composta "
                "normal em cada direção -- independente do momento real."))

    # -- 6b. fator de segurança em três cotas físicas -----------------------
    # "topo" e "base" são novas -- o momento real de cada ponta, não o
    # M1d,A que decide o alfa_b -- e "meio" é a pior das situações já
    # verificadas naquela posição: reaproveitada, não recalculada.
    topo = _situacao_extremo_real(pilar, res.esbeltez, "Topo",
                                  pilar.esforcos.Mx_topo,
                                  pilar.esforcos.My_topo)
    base = _situacao_extremo_real(pilar, res.esbeltez, "Base",
                                  pilar.momento_base("x"),
                                  pilar.momento_base("y"))
    meios = [v for v in res.verificacoes if v.situacao.posicao == "meio"]
    res.verificacoes_z = {
        "Topo": _verificar(secao, pilar, topo, rigorosa=True),
        "Meio": max(meios, key=lambda v: v.razao_envoltoria),
        "Base": _verificar(secao, pilar, base, rigorosa=True),
    }

    # -- 7. armadura transversal e ancoragem -------------------------------
    res.estribos = est_mod.dimensionar(pilar, a, secao)
    res.avisos.extend(res.estribos.avisos)
    res.ancoragem = anc.analisar(pilar, a.phi, res.As_necessaria, a.As)
    res.avisos.extend(res.ancoragem.avisos)

    # -- 7b. força cortante (item 17.4, modelo I) --------------------------
    # Depois dos estribos, porque a parcela Vsw depende do espaçamento
    # adotado; e com o momento **total** de cada direção, que é o que entra
    # na razão M0/MSd,max do item 17.4.2.2.
    momentos = {
        d: max((abs(v.situacao.Mx if d == "x" else v.situacao.My)
                for v in res.verificacoes), default=0.0)
        for d in ("x", "y")}
    res.cisalhamento = cis_mod.verificar(pilar, a, res.estribos, secao,
                                        momentos)
    for c in res.cisalhamento.values():
        res.avisos.extend(c.avisos)

    # -- 8. conferência cruzada --------------------------------------------
    res.conferencias = _conferir(pilar, res, secao)
    for c in res.conferencias:
        if not c.ok:
            res.avisos.append(av.construtivo(
                f"Conferência de {c.grandeza}: o roteiro dos casos fechados "
                f"dá {c.fechado:.1f} e o motor seccional {c.seccional:.1f}, "
                f"{c.divergencia * 100:.1f} % de diferença. A divergência é "
                f"esperada e tem duas causas conhecidas -- o modelo de duas "
                f"camadas ignora as barras intermediárias das faces, que "
                f"contam na força normal, e o diagrama retangular simplificado "
                f"afasta-se do parábola-retângulo quando a seção fica quase "
                f"toda comprimida. Vale o motor seccional."))
    return res


def _conferir(pilar: Pilar, res: ResultadoPilar,
              secao: sc.SecaoDiscreta) -> list[Conferencia]:
    """Confronta ``MRd`` dos casos fechados com o do motor seccional."""
    if not (pilar.config.conferir_com_motor_seccional
            and pilar.secao.tem_casos_fechados and res.arranjo):
        return []
    saida: list[Conferencia] = []
    tol = pilar.config.tolerancia_conferencia
    a = res.arranjo
    for direcao in ("x", "y"):
        sec = _secao_direcao(pilar, direcao, a.d_linha_x)
        As_camada = a.barras_por_camada(direcao) * area_barra(a.phi)
        M, _, _ = fc.momento_resistente(sec, pilar.Nd, As_camada, As_camada)
        Mn = sc.momento_resistente_uniaxial(secao, pilar.Nd, direcao)
        saida.append(Conferencia(grandeza=f"MRd,{direcao}{direcao} (kN·cm)",
                                 fechado=M, seccional=Mn, tolerancia=tol))
    return saida
