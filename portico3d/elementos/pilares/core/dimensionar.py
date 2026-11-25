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

import contextlib
import math
from dataclasses import dataclass, field

from . import acoes as acoes_mod
from . import ancoragem as anc
from . import arranjo as arr_mod
from . import avisos as av
from . import busca
from . import cisalhamento as cis_mod
from . import esbeltez as esb_mod
from . import estribos as est_mod
from . import flexocompressao as fc
from . import metodo_geral as mg
from . import momento_curvatura as mc
from . import seccional as sc
from . import segunda_ordem as so_mod
from .arranjo import Arranjo
from .esbeltez import Esbeltez
from .materiais import (ESBELTEZ_FLUENCIA, ESBELTEZ_METODO_EXATO, RHO_MAXIMO,
                        RHO_MAXIMO_CORRENTE, area_barra, rho_minimo)
from .modelo import METODOS_COM_SECAO, Pilar
from .formato import num

try:                                                         # COMPAT-PCALC
    from .. import compat_pcalc                              # COMPAT-PCALC
except ImportError:                                          # COMPAT-PCALC
    compat_pcalc = None                                      # COMPAT-PCALC
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
    #: a expressão do item 17.2.5 entra na aprovação (``Config``)
    interacao_exigida: bool = True
    #: F.S. truncado nesta casa decimal (o PCalc trunca na 2ª) -- só o modo
    #: compatível o liga; ``None`` é o valor exato.
    casas_fs: int | None = None                              # COMPAT-PCALC
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
    def ok_interacao_exigida(self) -> bool:
        """A interação reprova só se o critério de projeto a exige
        (``Config.exigir_interacao_17_2_5``); senão é informativa."""
        return self.ok_interacao or not self.interacao_exigida

    @property
    def ok(self) -> bool:
        return self.ok_interacao_exigida and self.ok_envoltoria

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
        if self.casas_fs is not None:                        # COMPAT-PCALC
            k = 10.0 ** self.casas_fs
            folga = math.floor(folga * k) / k
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
    #: Pontos da elipse intermediários entre as direções principais (Figuras
    #: 11.3 e 15.2): ``(Mx, My, razao, ok)``, com ``razao = MSd/MRd`` na
    #: direção do ponto, pela envoltória de equilíbrio. Vazio quando
    #: ``config.elipse_minima`` está desligado -- só as duas análises
    #: isoladas, que a norma admite.
    pontos_elipse: list = field(default_factory=list)
    #: F.S. truncado nesta casa decimal (modo compatível com o PCalc).
    casas_fs: int | None = None                              # COMPAT-PCALC
    #: Seção sem simetria: a elipse está nos eixos principais, e os campos
    #: "x" e "y" acima são as direções principais 1 (``phi``, rad, a partir
    #: de x) e 2 (``phi + pi/2``). ``None``: x e y.
    phi: float | None = None

    @property
    def rotulos(self) -> tuple[str, str]:
        """Nome das duas direções nas saídas."""
        if self.phi is None:
            return "x", "y"
        g = math.degrees(self.phi)
        return (f"1 ({num(g, 1)}°)", f"2 ({num(g + 90.0, 1)}°)")

    def _truncar(self, v: float) -> float:                   # COMPAT-PCALC
        if self.casas_fs is None or not math.isfinite(v):
            return v
        k = 10.0 ** self.casas_fs
        return math.floor(v * k) / k

    @property
    def ok_x(self) -> bool:
        return self.Msd_x <= self.MRd_x + 1e-6

    @property
    def ok_y(self) -> bool:
        return self.Msd_y <= self.MRd_y + 1e-6

    @property
    def ok_elipse(self) -> bool:
        return all(p[3] for p in self.pontos_elipse)

    @property
    def fs_elipse(self) -> float:
        """Menor margem ``MRd/MSd`` entre os pontos da elipse."""
        razoes = [p[2] for p in self.pontos_elipse if p[2] > 1e-12]
        return self._truncar(1.0 / max(razoes) if razoes else float("inf"))

    @property
    def ok(self) -> bool:
        return self.ok_x and self.ok_y and self.ok_elipse

    @property
    def fs_x(self) -> float:
        return self._truncar(self.MRd_x / self.Msd_x if self.Msd_x > 1e-9
                             else float("inf"))

    @property
    def fs_y(self) -> float:
        return self._truncar(self.MRd_y / self.Msd_y if self.Msd_y > 1e-9
                             else float("inf"))


@dataclass
class ResumoCombinacao:
    """Uma linha da tabela de combinações (kN e kN·m, de cálculo)."""

    nome: str
    Nd: float
    Mx_topo: float
    Mx_base: float
    My_topo: float
    My_base: float
    fs: float              # menor F.S. das situações
    fs_minimo: float       # F.S. da envoltória mínima (inf sem ela)
    ok: bool
    erro: str = ""
    governante: bool = False
    descricao: str = ""    # fórmula, quando gerada das ações


@dataclass
class VerificacaoNormal:
    """A força normal contra a normal resistente da seção armada.

    Compressão: a reta b do item 17.2.2 g) -- compressão uniforme em
    ``eps_c2``, o concreto na tensão de pico ``0,85 eta_c fcd`` do 17.2.2 e) e
    cada barra na tensão do seu diagrama na mesma deformação (17.2.2 f)),
    descontada a área de concreto que ela ocupa. ``Nd`` acima de ``NRd,máx``
    é o esmagamento do concreto: nenhum plano de deformação equilibra essa
    normal, com momento nenhum. Tração: a reta a, toda a armadura escoando;
    o concreto tracionado não entra (17.2.2 d)).

    Até 10/11/2026 o caso caía só como consequência -- ``MRd = 0`` em toda
    direção e a expressão de interação infinita --, sem dizer a causa.
    """

    Nd: float = 0.0              # kN, compressão positiva
    area_concreto: float = 0.0   # cm², bruta (as barras são descontadas abaixo)
    area_aco: float = 0.0        # cm²
    eps_c2: float = 0.0          # ‰
    sigma_cd: float = 0.0        # kN/cm², 0,85 eta_c fcd
    sigma_s: float = 0.0         # kN/cm², aço em eps_c2
    fyd: float = 0.0             # kN/cm²
    N_concreto: float = 0.0      # kN, sigma_cd · Ac
    N_aco: float = 0.0           # kN, soma de As (sigma_s - sigma_cd)
    NRd_max: float = 0.0         # kN
    NRd_min: float = 0.0         # kN (negativa), -As fyd

    @property
    def compressao(self) -> bool:
        return self.Nd >= 0.0

    @property
    def ok(self) -> bool:
        return self.NRd_min - 1e-6 <= self.Nd <= self.NRd_max + 1e-6

    @property
    def fs(self) -> float:
        """``NRd/Nd`` no sentido da normal (infinito com Nd nulo)."""
        if abs(self.Nd) < 1e-9:
            return float("inf")
        return (self.NRd_max / self.Nd if self.compressao
                else self.NRd_min / self.Nd)

    @property
    def tensao_media(self) -> float:
        """``Nd/Ac``, kN/cm² -- a conta de mão que o esmagamento lembra."""
        return self.Nd / self.area_concreto if self.area_concreto > 0 else 0.0


def verificar_normal(secao: sc.SecaoDiscreta, Nd: float) -> VerificacaoNormal:
    """Normal resistente máxima e mínima da seção armada
    (:class:`VerificacaoNormal`)."""
    c, aco = secao.concreto, secao.aco
    e = c.eps_c2_mil
    v = VerificacaoNormal(Nd=Nd, area_concreto=secao.area_concreto,
                          area_aco=secao.area_aco, eps_c2=e,
                          sigma_cd=c.sigma_c(e), sigma_s=sc.tensao_aco(aco, e),
                          fyd=aco.fyd_kNcm2)
    v.N_concreto = v.sigma_cd * v.area_concreto
    v.N_aco = sum((sc.tensao_aco(aco, e) - c.sigma_c(e)) * b.area
                  for b in secao.barras)
    v.NRd_max = sc.normal_resistente_maxima(secao)
    v.NRd_min = sc.normal_resistente_minima(secao)
    return v


def _causa_normal(pilar: Pilar) -> str:
    """Quando a busca não acha arranjo: a normal passa do que a seção
    resiste mesmo com a taxa máxima de 4 % (17.3.5.3.2)? É a explicação que
    o "nenhum arranjo" não dava -- esmagamento, não falta de bitola."""
    c, aco = pilar.concreto, pilar.aco
    Ac = pilar.secao.area
    As = RHO_MAXIMO_CORRENTE * Ac
    e = c.eps_c2_mil
    if pilar.Nd >= 0.0:
        teto = c.sigma_c(e) * Ac + As * (sc.tensao_aco(aco, e) - c.sigma_c(e))
        if pilar.Nd <= teto:
            return ""
        return (f" A causa é a normal: Nd = {num(pilar.Nd, 1)} kN passa da "
                f"normal resistente máxima mesmo com a taxa máxima de "
                f"{num(RHO_MAXIMO_CORRENTE * 100, 0)} % (17.3.5.3.2) -- "
                f"{num(teto, 1)} kN em compressão uniforme (17.2.2 g), reta "
                f"b): concreto {num(c.sigma_c(e) * 10, 2)} MPa × "
                f"{num(Ac, 1)} cm² mais {num(As, 1)} cm² de aço a "
                f"{num(sc.tensao_aco(aco, e) * 10, 0)} MPa. É esmagamento do "
                f"concreto: só uma seção maior ou um fck maior resolvem.")
    teto = As * aco.fyd_kNcm2
    if -pilar.Nd <= teto:
        return ""
    return (f" A causa é a normal: |Nd| = {num(-pilar.Nd, 1)} kN de tração "
            f"passa de As·fyd mesmo com a taxa máxima de "
            f"{num(RHO_MAXIMO_CORRENTE * 100, 0)} % ({num(teto, 1)} kN, "
            f"17.2.2 g), reta a). Só uma seção maior resolve.")


def mensagem_normal(v: VerificacaoNormal) -> str:
    """O erro de normal acima da resistente, com a conta."""
    if v.compressao:
        return (
            f"Esmagamento do concreto (item 17.2.2 g), reta b): Nd = "
            f"{num(v.Nd, 1)} kN > NRd,máx = {num(v.NRd_max, 1)} kN, a normal "
            f"resistente da seção armada em compressão uniforme a "
            f"εc2 = {num(v.eps_c2, 2)} ‰ -- concreto "
            f"{num(v.sigma_cd * 10, 2)} MPa × {num(v.area_concreto, 1)} cm² "
            f"= {num(v.N_concreto, 1)} kN, mais o aço a "
            f"{num(v.sigma_s * 10, 0)} MPa, descontado o concreto que ele "
            f"ocupa, {num(v.area_aco, 2)} cm² → {num(v.N_aco, 1)} kN. Nenhum "
            f"plano de deformação equilibra essa normal, com momento nenhum: "
            f"é preciso aumentar a seção, o fck ou a armadura. (Nd/Ac = "
            f"{num(v.tensao_media * 10, 2)} MPa, contra os "
            f"{num(v.sigma_cd * 10, 2)} MPa que o concreto sozinho resiste.)")
    return (
        f"Normal de tração acima da resistente (item 17.2.2 g), reta a): "
        f"|Nd| = {num(-v.Nd, 1)} kN > As·fyd = {num(-v.NRd_min, 1)} kN "
        f"({num(v.area_aco, 2)} cm² a {num(v.fyd * 10, 0)} MPa; o concreto "
        f"tracionado não entra, 17.2.2 d)). É preciso aumentar a armadura.")


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
    #: Topo, meio e base sempre, com o momento real nas pontas -- para
    #: comparação com o PCalc; a tabela mostrada é ``verificacoes_z``.
    verificacoes_cotas: dict = field(default_factory=dict)
    verificacoes_z: dict[str, VerificacaoSituacao] = field(
        default_factory=dict)
    #: Verificação isolada do momento mínimo pela envoltória do item 3.1 da
    #: apostila (``None`` quando ``momento_minimo_metodo == "planilha"``).
    momento_minimo: VerificacaoMomentoMinimo | None = None
    #: A normal contra a normal resistente (esmagamento / reta a).
    normal: VerificacaoNormal | None = None
    #: Verificação à força cortante por direção (item 17.4, modelo I).
    #: Sempre presente; com Vd = 0 ela apenas declara que o item não se
    #: aplica e que o estribo saiu do 18.4.3.
    cisalhamento: dict = field(default_factory=dict)
    conferencias: list[Conferencia] = field(default_factory=list)
    #: ELS-W, abertura de fissuras (``core.servico``).
    servico: object = None
    #: ELU de fadiga do pilar de ponte (``core.fadiga``).
    fadiga: object = None
    #: Situação de incêndio, NBR 15200 (``core.incendio``).
    incendio: object = None
    #: Critério "caso mais conservador": os métodos que rodaram (vazio fora
    #: dele). As linhas de ``combinacoes`` são então método × combinação.
    metodos_pior: list = field(default_factory=list)
    secao_discreta: sc.SecaoDiscreta | None = None
    avisos: list[str] = field(default_factory=list)
    #: Com mais de uma combinação de esforços: uma linha por combinação, e
    #: o nome da que governa (é a deste resultado).
    combinacoes: list["ResumoCombinacao"] = field(default_factory=list)
    combinacao_governante: str = ""
    #: O resultado completo de cada combinação, na ordem de ``combinacoes``
    #: -- é o que o seletor de combinação da janela mostra.
    resultados_combinacoes: list = field(default_factory=list, repr=False)

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
    # No método "planilha" com piso bidirecional o mínimo entra aqui nas
    # duas direções; com o unidirecional ele entra pelas situações 1 e 2 (uma
    # direção de cada vez), que a varredura contínua também verifica.
    planilha = (pilar.config.momento_minimo_metodo == "planilha"
                and pilar.config.piso_minimo_bidirecional)
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
    v = VerificacaoSituacao(situacao=s,
                            interacao_exigida=pilar.config.exigir_interacao_17_2_5)
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

    # sem a interação exigida, a envoltória é o único critério -- também na
    # busca do arranjo, que de outro modo só olha a interação
    if (rigorosa or not v.interacao_exigida) and v.MSd > 1e-9:
        _preencher_envoltoria(v, secao, Nd, s)
    return v


def _preencher_envoltoria(v: VerificacaoSituacao, secao: sc.SecaoDiscreta,
                          Nd: float, s: Situacao) -> None:
    """Confronta o momento solicitante com a envoltória de equilíbrio, na
    própria direção dele, e grava o resultado em ``v``."""
    estados = sc.estados_na_direcao(secao, Nd, math.atan2(s.My, s.Mx))
    if not estados:
        # Nenhuma linha neutra produz momento resistente nessa direção
        # para esta normal -- item 5.5: a seção assimétrica sob essa
        # curvatura tem a direção do momento resistente restrita a uma
        # faixa que não inclui a do momento solicitante. Não é "sem
        # dado" -- é reprovação.
        v.envoltoria_inatingivel = True
        v.razao_envoltoria = float("inf")
        return
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


def _excentricidades_entrada(pilar: Pilar) -> dict[str, tuple[float, float]]:
    """Excentricidades de 1ª ordem ``(base, topo)`` da entrada, cm, na
    convenção interna (mesmo sinal nas duas pontas = curvatura simples)."""
    f = pilar.fator_esforcos
    Nd = pilar.Nd
    if abs(Nd) < 1e-9:              # normal nula: já é erro de entrada
        return {d: (0.0, 0.0) for d in ("x", "y")}
    return {d: (f * pilar.momento_base(d) / Nd, f * pilar.esforcos.topo(d) / Nd)
            for d in ("x", "y")}


def _analise_geral(pilar: Pilar, esb: dict[str, Esbeltez],
                   secao: sc.SecaoDiscreta,
                   e1: dict[str, tuple[float, float]] | None = None,
                   so_direcao: str | None = None,
                   forcar: bool = False) -> mg.ResultadoGeral:
    """Roda o método geral (15.8.3.2) no lance, com a armadura de ``secao``.

    ``e1`` (excentricidades de 1ª ordem ``(base, topo)`` por direção, cm)
    substitui as da entrada -- é como a envoltória mínima passa o mínimo;
    ``so_direcao`` deixa a 2ª ordem só nessa direção, e ``forcar`` a liga ali
    mesmo que a dispensa da situação real (lambda <= lambda_1) valesse -- a
    envoltória mínima decide a própria 2ª ordem. Barra biarticulada de
    comprimento ``le`` em cada direção, ou engastada na base e livre no topo
    (balanço), com o comprimento do lance.
    """
    cfg = pilar.config
    Nd = pilar.Nd
    entrada = e1 is None
    if e1 is None:
        e1 = _excentricidades_entrada(pilar)
    L, bal, ativa = [], [], []
    for d in ("x", "y"):
        balanco = pilar.lance.vinculo(d) == 3
        L.append(pilar.lance.altura if balanco else pilar.le(d))
        bal.append(balanco)
        ativa.append(Nd > 0.0 and so_direcao in (None, d)
                     and (esb[d].considerar_2a_ordem or forcar))
    # Fluência (15.8.4): pela e_cc -- com a forma da deformada, somada à linha
    # de 1ª ordem -- ou pela curva de deformabilidade esticada
    pela_curva = cfg.considerar_fluencia and cfg.fluencia_metodo == "diagrama"
    fator_fluencia = (1.0 + pilar.phi_fluencia * cfg.Nsg_sobre_Nd
                      if pela_curva else 1.0)
    ecc = [0.0, 0.0]
    if cfg.considerar_fluencia and not pela_curva and Nd > 0.0:
        prop = pilar.secao.propriedades()
        for k, d in enumerate(("x", "y")):
            if not ativa[k]:
                continue
            eb, et = e1[d]
            # Msg/Nsg = o maior e1 de 1ª ordem (o mais desfavorável; a norma
            # não diz qual; 13/11/2026 -- antes alfa_b e1), ou e1,mín na
            # envoltória
            e_ref = (so_mod.e1_quase_permanente(pilar, esb[d].e1)
                     if entrada else max(abs(eb), abs(et)))
            Ic = prop.Ix if d == "x" else prop.Iy
            v, _ = so_mod.excentricidade_fluencia(pilar, d, e_ref, Ic)
            sinal = 1.0 if (eb + et if abs(eb + et) > 1e-12
                            else (et if abs(et) >= abs(eb) else eb)) >= 0 \
                else -1.0
            ecc[k] = sinal * v
    return mg.analisar(secao, abs(Nd) / pilar.gamma_n, e1["x"], e1["y"],
                       tuple(L), tuple(bal),
                       (esb["x"].gamma_n1, esb["y"].gamma_n1),
                       n=cfg.metodo_geral_secoes,
                       rigidez=cfg.metodo_geral_rigidez,
                       acoplado=cfg.metodo_geral_acoplado,
                       fator_final=pilar.gamma_n,
                       segunda_ordem=tuple(ativa),
                       fator_fluencia=fator_fluencia, ecc=tuple(ecc))


def _situacoes_geral(pilar: Pilar, esb: dict[str, Esbeltez],
                     secao: sc.SecaoDiscreta
                     ) -> tuple[list[Situacao] | None, dict[str, SegundaOrdem]]:
    """Situações de cálculo pelo método geral: uma por seção da barra."""
    r = _analise_geral(pilar, esb, secao)
    e1 = _excentricidades_entrada(pilar)
    Nd = pilar.Nd
    so: dict[str, SegundaOrdem] = {}
    for d in ("x", "y"):
        ativa = Nd > 0.0 and esb[d].considerar_2a_ordem
        avisos = []
        braco = float("inf")
        if not r.convergiu:
            avisos.append(av.erro(
                f"Método geral (15.8.3.2): {r.motivo}. A barra não encontra "
                f"equilíbrio de 2ª ordem com essa armadura."))
        else:
            M = r.Mx if d == "x" else r.My
            e0, e1_ = e1[d]
            braco = max((abs(m - Nd * (e0 + (e1_ - e0) * t))
                         for m, t in zip(M, r.z)), default=0.0)                 / Nd if abs(Nd) > 1e-9 else 0.0
        so[d] = SegundaOrdem(
            direcao=d, aplicavel=ativa, e2=braco,
            e_cc=abs(r.ecc[0 if d == "x" else 1]),
            metodo=(f"método geral (15.8.3.2), {len(r.z)} seções, rigidez "
                    f"{pilar.config.metodo_geral_rigidez}"
                    + ("" if pilar.config.metodo_geral_acoplado
                       else ", direções separadas")),
            geral=r, avisos=avisos)
    if not r.convergiu:
        return None, so
    L = pilar.lance.altura
    n = len(r.z)
    lista = []
    for i, t in enumerate(r.z):
        lista.append(Situacao(
            nome=f"z = {num(t * L, 0)} cm",
            posicao=("extremo" if i in (0, n - 1) else "meio"),
            ex=r.Mx[i] / Nd if abs(Nd) > 1e-9 else 0.0,
            ey=r.My[i] / Nd if abs(Nd) > 1e-9 else 0.0,
            Mx=r.Mx[i], My=r.My[i],
            descricao=f"método geral, seção {i + 1} de {n} (z/L = {num(t, 2)})",
            z_rel=t))
    return lista, so


def _momento_total_minimo(pilar: Pilar, esb: Esbeltez,
                          secao: sc.SecaoDiscreta | None = None) -> float:
    """``Md,tot,min`` numa direção: o mínimo de 1ª ordem, amplificado pela 2ª
    ordem quando a esbeltez pedir.

    Pelo mesmo método de 2ª ordem da situação real (curvatura, rigidez kappa
    ou o menor dos dois; até a R05 era sempre a curvatura), com
    ``alfa_b = 1`` -- é o que o item 3.1 da apostila manda quando "o pilar
    apresentar momentos menores do que o momento mínimo": aqui a peça inteira
    *é* o caso, MA = MB = MC = M1d,min, sem variação ao longo do lance.

    A **decisão** de somar a 2ª ordem é da própria análise do mínimo, e não
    a da situação real: com ``alfa_b = 1`` e ``e1 = e1,min`` o limite
    ``lambda_1`` cai no piso de 35, e todo pilar com ``lambda > 35`` leva 2ª
    ordem sobre o mínimo -- mesmo quando o momento real, de ``alfa_b``
    menor ou ``e1`` maior, tem um ``lambda_1`` alto e a dispensa. Até a R05
    a decisão era herdada da situação real, e a envoltória mínima saía sem
    2ª ordem em pilar esbelto (o PCalc a aplica: F.S. de 1,78 contra 4,94 num
    25x50, C30, le = 450 cm).
    """
    # Normal de tração não tem 2ª ordem de pilar (o mesmo corte de
    # ``segunda_ordem.analisar``): sem isto, a decisão nova somava e2 ao mínimo
    # numa flexo-tração esbelta -- achado pela bateria de 224 casos contra o
    # PCalc (F.S. do mínimo 94 % abaixo do dele em flexo-tração com λ = 140).
    lam_1_min, _ = esb_mod.esbeltez_limite(esb.e1_min, esb.h, 1.0)
    if pilar.Nd <= 0.0 or (esb.lam <= lam_1_min and not esb.imposta):
        return esb.M1d_min
    prop = pilar.secao.propriedades()
    cfg = pilar.config
    metodo = so_mod.metodo_efetivo(pilar)
    # fluência (15.8.4) na envoltória mínima também: e_cc com e1 = e1,mín,
    # somada ao e1 que a 2ª ordem amplifica -- ou pela curva esticada
    pela_curva = (cfg.considerar_fluencia and cfg.fluencia_metodo == "diagrama"
                  and metodo in ("diagrama", "geral"))
    e_cc = 0.0
    if cfg.considerar_fluencia and not pela_curva:
        Ic = prop.Ix if esb.direcao == "x" else prop.Iy
        e_cc, _ = so_mod.excentricidade_fluencia(pilar, esb.direcao,
                                                 esb.e1_min, Ic)
    fator_fluencia = (1.0 + pilar.phi_fluencia * cfg.Nsg_sobre_Nd
                      if pela_curva else 1.0)
    e1a = esb.e1_min + e_cc
    nu = so_mod.forca_normal_adimensional(abs(pilar.Nd) / pilar.gamma_n,
                                          prop.area, pilar.concreto.fcd_kNcm2)
    curv = so_mod.curvatura_aproximada(esb.h, nu)
    e2_curv = so_mod.e2_por_curvatura(esb.le, curv)
    # Mesmo método da situação real (o PCalc faz igual): com a rigidez kappa,
    # a quadrática do 15.8.3.3.3 com alfa_b = 1 e e1 = e1,mín.
    e_rig, _ = so_mod.e2_por_rigidez(esb.le, esb.h, e1a)
    e2_rig = max(e_rig - e1a, 0.0)
    if metodo == "geral" and secao is not None:
        # o mínimo constante ao longo do lance (alfa_b = 1), só nesta direção
        outra = "y" if esb.direcao == "x" else "x"
        esbs = {esb.direcao: esb, outra: esb_mod.analisar(pilar, outra)}
        # a decisão de somar a 2ª ordem já foi tomada acima, pelo lambda_1 do
        # próprio mínimo -- não a da situação real; com armadura assimétrica
        # os dois sentidos do mínimo dão flechas diferentes, e vale o pior
        sentidos = ((1.0,) if arr_mod.barras_simetricas(secao.barras)
                    else (1.0, -1.0))
        pior = 0.0
        for s_ in sentidos:
            e = s_ * esb.e1_min
            e1 = {esb.direcao: (e, e), outra: (0.0, 0.0)}
            r = _analise_geral(pilar, esbs, secao, e1=e1,
                               so_direcao=esb.direcao, forcar=True)
            if not r.convergiu:
                return float("inf")
            M = r.Mx if esb.direcao == "x" else r.My
            pior = max(pior, max(abs(m) for m in M))
        return pior
    if metodo == "diagrama" and secao is not None:
        # a mesma (EI)sec da situação real, com M1 = M1d,mín e alfa_b = 1
        Nd_2 = abs(pilar.Nd) / pilar.gamma_n
        sentidos = ((1.0,) if arr_mod.barras_simetricas(secao.barras)
                    else (1.0, -1.0))
        e2 = 0.0
        for s_ in sentidos:
            rs = mc.rigidez_secante(secao, Nd_2, esb.direcao, s_,
                                    fator_fluencia=fator_fluencia)
            e2 = max(e2, so_mod.e2_por_diagrama(
                so_mod.normal_amplificacao(pilar, Nd_2), esb.le, rs.EI, e1a)
                if rs is not None else float("inf"))
    elif metodo == "rigidez":
        e2 = e2_rig
    elif metodo == "menor":
        e2 = min(e2_curv, e2_rig)
    else:
        e2 = e2_curv
    return esb.M1d_min + abs(pilar.Nd) * (e_cc + e2 * esb.gamma_n1)


def _minimo_total_principal(pilar: Pilar, d, secao: sc.SecaoDiscreta | None
                            = None) -> float:
    """``Md,tot,min`` numa direção principal ``d``
    (:class:`principais.DirecaoPrincipal`) da seção sem simetria: o mesmo de
    :func:`_momento_total_minimo`, com ``h``, ``le`` e lambda da direção
    principal e a 2ª ordem do mínimo pela flexão naquela direção."""
    if pilar.Nd <= 0.0:
        return d.M1d_min
    lam_1_min, _ = esb_mod.esbeltez_limite(d.e1_min, d.h, 1.0)
    if d.lam <= lam_1_min and not pilar.config.sempre_2a_ordem:
        return d.M1d_min
    prop = pilar.secao.propriedades()
    cfg = pilar.config
    metodo = so_mod.metodo_efetivo(pilar)
    pela_curva = (cfg.considerar_fluencia and cfg.fluencia_metodo == "diagrama"
                  and metodo in ("diagrama", "geral"))
    e_cc = 0.0
    if cfg.considerar_fluencia and not pela_curva:
        e_cc, _ = so_mod.excentricidade_fluencia(
            pilar, f"na direção principal {d.indice}", d.e1_min, d.I, le=d.le)
    fator_fluencia = (1.0 + pilar.phi_fluencia * cfg.Nsg_sobre_Nd
                      if pela_curva else 1.0)
    e1a = d.e1_min + e_cc
    nu = so_mod.forca_normal_adimensional(abs(pilar.Nd) / pilar.gamma_n,
                                          prop.area, pilar.concreto.fcd_kNcm2)
    e2_curv = so_mod.e2_por_curvatura(d.le,
                                      so_mod.curvatura_aproximada(d.h, nu))
    e_rig, _ = so_mod.e2_por_rigidez(d.le, d.h, e1a)
    e2_rig = max(e_rig - e1a, 0.0)
    sentidos = ((1.0,) if secao is None
                or arr_mod.barras_simetricas(secao.barras) else (1.0, -1.0))
    if metodo == "geral" and secao is not None:
        # o mínimo constante ao longo do lance, na direção principal: as
        # componentes em x e y, com a 2ª ordem acoplada nas duas
        esbs = {k: esb_mod.analisar(pilar, k) for k in ("x", "y")}
        pior = 0.0
        for s_ in sentidos:
            e = s_ * d.e1_min
            e1 = {"x": (e * d.ux, e * d.ux), "y": (e * d.uy, e * d.uy)}
            r = _analise_geral(pilar, esbs, secao, e1=e1, forcar=True)
            if not r.convergiu:
                return float("inf")
            pior = max(pior, max(abs(mx * d.ux + my * d.uy)
                                 for mx, my in zip(r.Mx, r.My)))
        return pior
    if metodo == "diagrama" and secao is not None:
        Nd_2 = abs(pilar.Nd) / pilar.gamma_n
        e2 = 0.0
        for s_ in sentidos:
            rs = mc.rigidez_secante(secao, Nd_2, d.phi, s_,
                                    fator_fluencia=fator_fluencia)
            e2 = max(e2, so_mod.e2_por_diagrama(
                so_mod.normal_amplificacao(pilar, Nd_2), d.le, rs.EI, e1a)
                if rs is not None else float("inf"))
    elif metodo == "rigidez":
        e2 = e2_rig
    elif metodo == "menor":
        e2 = min(e2_curv, e2_rig)
    else:
        e2 = e2_curv
    return d.M1d_min + abs(pilar.Nd) * (e_cc + e2 * d.gamma_n1)


def _semi_eixos_minimo(pilar: Pilar, esb: dict[str, Esbeltez],
                       secao: sc.SecaoDiscreta | None = None
                       ) -> tuple[float, float, float | None]:
    """``(A1, A2, phi)``: semi-eixos da elipse mínima e a direção do
    primeiro (``None`` = x e y). Na seção sem simetria, nas direções
    principais -- é onde o item 11.3.3.4.3 e a Figura 11.3 a põem."""
    ep = esb["x"].principal
    if ep is None:
        return (_momento_total_minimo(pilar, esb["x"], secao),
                _momento_total_minimo(pilar, esb["y"], secao), None)
    d1, d2 = ep.direcoes
    return (_minimo_total_principal(pilar, d1, secao),
            _minimo_total_principal(pilar, d2, secao), d1.phi)


def _mrd_minimo(secao: sc.SecaoDiscreta, pilar: Pilar, k: int,
                phi: float | None) -> float:
    """Momento resistente de um vértice da elipse mínima (``k`` = 0 ou 1),
    no sentido mais fraco quando a armadura não é simétrica. Em x/y, a
    flexão composta normal; numa direção principal, a envoltória de
    equilíbrio naquela direção (o momento resultante sai nela)."""
    Nd = pilar.Nd
    sentidos = ((1.0,) if arr_mod.barras_simetricas(secao.barras)
                else (1.0, -1.0))
    if phi is None:
        d = "x" if k == 0 else "y"
        return min(sc.momento_resistente_uniaxial(secao, Nd, d, s)
                   for s in sentidos)
    ang = phi + k * math.pi / 2.0
    valores = []
    for s in sentidos:
        estados = sc.estados_na_direcao(secao, Nd,
                                        ang + (math.pi if s < 0 else 0.0))
        valores.append(estados[-1].M if estados else 0.0)
    return min(valores)


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
    Ax, Ay, phi = _semi_eixos_minimo(pilar, esb, secao)
    return _verificar_minimo_secao(secao, pilar, Ax, Ay, phi)


#: Ângulos da elipse da envoltória mínima (``Mx = Ax cos f``, ``My = Ay sin
#: f``) conferidos entre as direções principais. Na seção retangular, de
#: armadura simétrica, o primeiro quadrante representa os quatro; nas demais
#: o círculo inteiro, de 30 em 30 graus, porque a envoltória resistente de
#: uma L, T ou U não é simétrica -- nem sequer o sentido oposto ao dos eixos
#: vale o mesmo.
#: Em ordem de probabilidade de reprovar (a diagonal é onde os dois mínimos
#: mais se somam), para a busca do arranjo parar cedo.
ANGULOS_ELIPSE_QUADRANTE = (45.0, 30.0, 60.0, 15.0, 75.0)
ANGULOS_ELIPSE_CIRCULO = (45.0, 135.0, 225.0, 315.0, 30.0, 60.0, 120.0,
                          150.0, 210.0, 240.0, 300.0, 330.0, 0.0, 90.0,
                          180.0, 270.0)
#: Conjuntos finos, usados na verificação final e no relatório. O grosso só
#: serve à busca do arranjo parar cedo; como o F.S. é o mínimo sobre os pontos
#: conferidos, amostrar pouco o *superestima* -- 3 % a mais que o PCalc (98
#: pontos) num retangular vazado; o fino leva isso a < 1 %. Retângulo: de 10
#: em 10 graus no quadrante (11 pontos com os do grosso). Retangular vazada:
#: o círculo grosso mais os ângulos finos do primeiro quadrante (armadura
#: simétrica). Circulares (cheia e vazada) ficam no grosso -- 36 pontos não
#: mudaram o F.S. nos casos testados. L, T e U: círculo de 10 em 10 graus.
ANGULOS_ELIPSE_QUADRANTE_FINO = ANGULOS_ELIPSE_QUADRANTE + tuple(
    float(a) for a in range(10, 90, 10)
    if float(a) not in ANGULOS_ELIPSE_QUADRANTE)
ANGULOS_ELIPSE_RET_VAZADA_FINO = ANGULOS_ELIPSE_CIRCULO + tuple(
    a for a in ANGULOS_ELIPSE_QUADRANTE_FINO
    if a not in ANGULOS_ELIPSE_CIRCULO)
ANGULOS_ELIPSE_CIRCULO_FINO = ANGULOS_ELIPSE_CIRCULO + tuple(
    float(a) for a in range(0, 360, 10)
    if float(a) not in ANGULOS_ELIPSE_CIRCULO)


def _verificar_minimo_secao(secao: sc.SecaoDiscreta, pilar: Pilar,
                            Ax: float, Ay: float, phi: float | None = None,
                            parar_no_primeiro: bool = False,
                            fino: bool = True) -> VerificacaoMomentoMinimo:
    """Envoltória mínima com 2ª ordem (Figura 15.2) contra a seção armada.

    ``Ax`` e ``Ay`` são os semi-eixos da elipse -- ``Md,tot,mín`` em cada
    direção principal. As duas análises à flexão composta normal que a norma
    admite conferem os dois vértices; com ``config.elipse_minima`` ligado
    (padrão), conferem-se também os pontos intermediários da elipse, em que
    a combinação dos dois mínimos é a de flexão oblíqua.

    ``parar_no_primeiro``: a busca do arranjo só precisa saber se passa; o
    relatório precisa de todos os pontos. ``fino``: conjunto fino de ângulos
    (verificação final) ou o grosso (varredura dos candidatos).

    ``phi``: seção sem simetria -- ``Ax`` e ``Ay`` são os semi-eixos nas
    direções principais 1 (``phi``) e 2 (``phi + pi/2``), e a elipse é girada
    para x e y antes de ir à envoltória.
    """
    Nd = pilar.Nd
    v = VerificacaoMomentoMinimo(Msd_x=Ax, Msd_y=Ay, phi=phi)
    simetrico = arr_mod.barras_simetricas(secao.barras)
    # a elipse mínima tem os dois sentidos; só a armadura simétrica deixa um
    # representar o outro
    v.MRd_x = _mrd_minimo(secao, pilar, 0, phi)
    v.MRd_y = _mrd_minimo(secao, pilar, 1, phi)
    if not pilar.config.elipse_minima or (
            parar_no_primeiro and not (v.ok_x and v.ok_y)):
        return v
    retang = pilar.secao.tipo == "retangular" and simetrico
    if (fino and simetrico
            and pilar.secao.tipo in ("circular", "circular vazada")):
        fino = False
    if fino:
        angulos = (ANGULOS_ELIPSE_QUADRANTE_FINO if retang
                   else ANGULOS_ELIPSE_RET_VAZADA_FINO
                   if pilar.secao.tipo == "retangular vazada" and simetrico
                   else ANGULOS_ELIPSE_CIRCULO_FINO)
    else:
        angulos = ANGULOS_ELIPSE_QUADRANTE if retang else ANGULOS_ELIPSE_CIRCULO
    if phi is not None:
        angulos = ANGULOS_ELIPSE_CIRCULO_FINO if fino else ANGULOS_ELIPSE_CIRCULO
    if phi is not None and not (math.isfinite(Ax) and math.isfinite(Ay)):
        # semi-eixo infinito (instabilidade do mínimo): os vértices já
        # reprovam, e girar ∞ daria NaN (∞ - ∞·0) em todos os pontos --
        # direção indefinida, que nem o cache da envoltória reconhece. Um
        # ponto de razão infinita deixa o F.S. da elipse em zero.
        v.pontos_elipse.append((0.0, 0.0, float("inf"), False))
        return v
    c1, s1 = (1.0, 0.0) if phi is None else (math.cos(phi), math.sin(phi))
    for graus in angulos:
        f = math.radians(graus)
        a1, a2 = Ax * math.cos(f), Ay * math.sin(f)
        # componentes nas direções 1 e 2, giradas para x e y (em x/y, sem
        # conta nenhuma: o resultado é o mesmo de antes, bit a bit)
        Mx, My = ((a1, a2) if phi is None
                  else (a1 * c1 - a2 * s1, a1 * s1 + a2 * c1))
        if math.hypot(Mx, My) <= 1e-9:
            continue
        s = Situacao(nome="elipse mínima", posicao="extremo",
                     ex=Mx / Nd if abs(Nd) > 1e-9 else 0.0,
                     ey=My / Nd if abs(Nd) > 1e-9 else 0.0, Mx=Mx, My=My)
        ve = VerificacaoSituacao(situacao=s, MSd=math.hypot(Mx, My))
        _preencher_envoltoria(ve, secao, Nd, s)
        v.pontos_elipse.append((Mx, My, ve.razao_envoltoria, ve.ok_envoltoria))
        if parar_no_primeiro and not ve.ok_envoltoria:
            break
    return v


def _testar_arranjo(pilar: Pilar, a: Arranjo, situacoes: list[Situacao],
                    nu: float, As_necessaria: float, fatias: int,
                    minimo: tuple[float, float] | None = None,
                    esb: dict[str, Esbeltez] | None = None
                    ) -> tuple[bool, list[VerificacaoSituacao], list[str]]:
    """Roda as verificações de um arranjo candidato.

    ``minimo`` são os semi-eixos ``(Md,tot,mín,x; Md,tot,mín,y)`` da
    envoltória mínima, quando esse é o método do momento mínimo: o candidato
    precisa passar nela também, e não só nas situações de cálculo.
    """
    avisos = arr_mod.verificar(a, pilar, nu, As_necessaria)
    if any(av.nivel_de(x) == av.ERRO for x in avisos):
        return False, [], avisos
    secao = sc.montar(pilar.secao, a.barras, pilar.concreto, pilar.aco,
                      fatias)
    if so_mod.metodo_efetivo(pilar) in METODOS_COM_SECAO and esb is not None:
        # 2ª ordem que depende da armadura: refeita com as barras do candidato
        if pilar.config.metodo_2a_ordem == "geral":
            situacoes, so = _situacoes_geral(pilar, esb, secao)
            if situacoes is None:
                return False, [], avisos
        else:
            so = {d: so_mod.analisar(pilar, esb[d], secao)
                  for d in ("x", "y")}
            if any(not math.isfinite(so[d].e2) for d in so):
                return False, [], avisos
            situacoes = so_mod.situacoes(pilar, esb, so)
    # Os dois vértices da envoltória mínima antes das situações (25/11/2026),
    # quando o mínimo já vem pronto (2ª ordem que não depende da armadura):
    # custam duas flexões compostas normais, contra a varredura de direções
    # de linha neutra das situações. O veredito do candidato é o "e" de
    # todas as verificações, e a ordem não o muda; o teste é o mesmo
    # ``ok_x``/``ok_y`` de _verificar_minimo_secao, com os mesmos MRd, que
    # ficam no cache da seção para ela.
    if minimo is not None and not (
            esb is not None
            and so_mod.metodo_efetivo(pilar) in METODOS_COM_SECAO):
        phi_m = minimo[2] if len(minimo) > 2 else None
        if (minimo[0] > _mrd_minimo(secao, pilar, 0, phi_m) + 1e-6
                or minimo[1] > _mrd_minimo(secao, pilar, 1, phi_m) + 1e-6):
            return False, [], avisos
    # Para na primeira situação reprovada (25/11/2026): quem chama só lê
    # ``passou`` e os avisos, e as verificações de um candidato reprovado
    # não são usadas -- conferir as situações seguintes dele não mudava
    # nada, só custava as buscas de direção delas.
    verifs = []
    for s in situacoes:
        v = _verificar(secao, pilar, s, rigorosa=False)
        verifs.append(v)
        if not v.ok:
            return False, verifs, avisos
    if (minimo is not None and esb is not None
            and so_mod.metodo_efetivo(pilar) in METODOS_COM_SECAO):
        # O mínimo com a 2ª ordem do candidato (no método geral, uma análise
        # da barra por direção e sentido -- ~70 % do custo do candidato) só
        # depois das situações: o candidato que já reprova nelas não precisa
        # dele. O veredito é o mesmo nas duas ordens; quem chama só lê
        # ``passou`` e os avisos.
        #
        # E o vértice x da elipse é conferido assim que o mínimo em x sai:
        # se já passa do MRd,x (o ``ok_x`` de VerificacaoMomentoMinimo, com
        # o mesmo MRd,x que _verificar_minimo_secao usa), o candidato reprova
        # de qualquer jeito, e a análise da barra em y fica sem fazer.
        ep = esb["x"].principal
        phi = None if ep is None else ep.direcoes[0].phi

        def semi(k):
            if ep is None:
                return _momento_total_minimo(pilar, esb["xy"[k]], secao)
            return _minimo_total_principal(pilar, ep.direcoes[k], secao)
        Ax = semi(0)
        if not math.isfinite(Ax):
            return False, [], avisos
        if Ax > _mrd_minimo(secao, pilar, 0, phi) + 1e-6:
            return False, verifs, avisos
        Ay = semi(1)
        if not math.isfinite(Ay):
            return False, [], avisos
        minimo = (Ax, Ay, phi)
    if minimo is not None:
        # grosso primeiro (barato, reprova cedo); o fino só para quem passou
        for fino in (False, True):
            if not _verificar_minimo_secao(secao, pilar, *minimo,
                                           parar_no_primeiro=True,
                                           fino=fino).ok:
                return False, verifs, avisos
    return True, verifs, avisos


def _escolher_arranjo(pilar: Pilar, situacoes: list[Situacao], nu: float,
                      As_necessaria: float, camadas: dict[str, float],
                      minimo: tuple[float, float] | None = None,
                      esb: dict[str, Esbeltez] | None = None
                      ) -> tuple[Arranjo | None, list[str]]:
    """Percorre os candidatos e devolve o primeiro que atende a tudo.

    Os candidatos vêm ordenados por área total de aço, de modo que o primeiro
    aprovado é o mais econômico do conjunto -- não o de menos barras nem o de
    menor bitola. Passar nas situações de cálculo **e**, no método da
    envoltória mínima, na envoltória mínima: até a R04 a busca ignorava a
    segunda, e o programa escolhia um arranjo que ele mesmo reprovava depois.
    """
    cfg = pilar.config
    ultimo: list[str] = []
    if cfg.metodo_2a_ordem in METODOS_COM_SECAO:
        return _escolher_por_varredura(pilar, situacoes, nu, As_necessaria,
                                       camadas, minimo, esb)
    simetria = _exige_simetria(pilar)
    for phi, nx, ny, n in arr_mod.candidatos(pilar.secao,
                                             cfg.bitolas_permitidas,
                                             peso=cfg.peso_por_barra):
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
        phi_t = pilar.armadura.phi_estribo or est_mod.bitola_comercial(phi)
        a = arr_mod.montar(pilar.secao, pilar.cobrimento(phi, phi_t),
                           phi_t, phi, nx, ny, n, *_internas(pilar))
        if not a.cabe or (simetria and not a.simetrico):
            continue
        passou, _, avisos = _testar_arranjo(pilar, a, situacoes, nu,
                                            As_necessaria, FATIAS_BUSCA,
                                            minimo, esb)
        ultimo = avisos
        if passou:
            return a, []
    return None, ultimo


#: Métodos que só valem com armadura simétrica (15.8.3.3.2 e 15.8.3.3.3).
METODOS_ARMADURA_SIMETRICA = ("curvatura", "rigidez", "menor")
#: Seções que admitem arranjo simétrico nos dois eixos. Nas L, T e U nenhum
#: arranjo é, e filtrar ali só faria a busca não achar nada.
SECOES_DUPLAMENTE_SIMETRICAS = ("retangular", "circular", "circular vazada",
                                "retangular vazada")


def _exige_simetria(pilar: Pilar) -> bool:
    """A busca tem de descartar arranjos assimétricos? -- ex.: número ímpar
    de barras no círculo, que o próprio programa reprovaria depois com os
    métodos aproximados (achado na verificação das OAE da ERS-531)."""
    return (so_mod.metodo_efetivo(pilar) in METODOS_ARMADURA_SIMETRICA
            and pilar.secao.tipo in SECOES_DUPLAMENTE_SIMETRICAS)


def _candidatos_validos(pilar: Pilar, As_necessaria: float,
                        camadas: dict[str, float]) -> list[Arranjo]:
    """Os arranjos que cabem e passam nos filtros de área, em ordem de As."""
    cfg = pilar.config
    saida: list[Arranjo] = []
    for phi, nx, ny, n in arr_mod.candidatos(pilar.secao,
                                             cfg.bitolas_permitidas,
                                             peso=cfg.peso_por_barra):
        area = area_barra(phi)
        As = n * area
        if As < As_necessaria - 1e-9:
            continue
        if As / pilar.secao.area > RHO_MAXIMO + 1e-9:
            continue
        if nx and ny:
            if (ny * area < camadas.get("x", 0.0) - 1e-9
                    or nx * area < camadas.get("y", 0.0) - 1e-9):
                continue
        phi_t = pilar.armadura.phi_estribo or est_mod.bitola_comercial(phi)
        a = arr_mod.montar(pilar.secao, pilar.cobrimento(phi, phi_t),
                           phi_t, phi, nx, ny, n, *_internas(pilar))
        if a.cabe:
            saida.append(a)
    return saida


def _rejeitado_pelo_piso(pilar: Pilar, a: Arranjo,
                        esb: dict[str, Esbeltez]) -> bool:
    """O candidato reprova com certeza, sem a análise de 2ª ordem?

    Piso do momento total: a rigidez secante nunca passa da rigidez inicial
    da curva de deformabilidade (``busca.rigidez_inicial``), e com ela a
    amplificação do pilar-padrão dá menos 2ª ordem do que a verdadeira. Se a
    seção reprova com esse piso nas situações, ou se até a barra mais rígida
    possível é instável, não há o que analisar. A e_cc fica de fora (só
    aumentaria o piso), e a envoltória mínima também -- a verificação dela
    custa mais que o teste inteiro.
    """
    cfg = pilar.config
    if pilar.Nd <= 0.0:
        return False
    secao = sc.montar(pilar.secao, a.barras, pilar.concreto, pilar.aco,
                      FATIAS_BUSCA)
    margem = (busca.MARGEM_GERAL if cfg.metodo_2a_ordem == "geral"
              else busca.MARGEM_DIAGRAMA)
    fator = (1.0 + pilar.phi_fluencia * cfg.Nsg_sobre_Nd
             if cfg.considerar_fluencia and cfg.fluencia_metodo == "diagrama"
             else 1.0)
    Nd2 = abs(pilar.Nd) / pilar.gamma_n
    so_piso: dict[str, SegundaOrdem] = {}
    for d in ("x", "y"):
        e = esb[d]
        if not e.considerar_2a_ordem:
            so_piso[d] = SegundaOrdem(direcao=d, aplicavel=False)
            continue
        amp = busca.amplificacao(Nd2, e.le, busca.rigidez_inicial(secao, d,
                                                                  fator))
        if not math.isfinite(amp):
            return True
        so_piso[d] = SegundaOrdem(direcao=d, aplicavel=True,
                                  e2=margem * (amp - 1.0)
                                  * e.alfa_b * abs(e.e1) * e.gamma_n1)
    return any(not _verificar(secao, pilar, s_, rigorosa=False).ok
               for s_ in so_mod.situacoes(pilar, esb, so_piso))


def _escolher_por_varredura(pilar: Pilar, situacoes: list[Situacao],
                            nu: float, As_necessaria: float,
                            camadas: dict[str, float],
                            minimo: tuple[float, float] | None,
                            esb: dict[str, Esbeltez] | None
                            ) -> tuple[Arranjo | None, list[str]]:
    """Busca **exata** do arranjo nos métodos cuja 2ª ordem depende da
    armadura: o primeiro aprovado na ordem de custo, como na varredura
    linear, sem pagar uma análise de 2ª ordem por candidato.

    1. fora os que reprovam no detalhamento (18.4.2) -- barato;
    2. fora os que reprovam pelo piso da rigidez inicial
       (``_rejeitado_pelo_piso``) -- rigoroso e barato, aplicado à medida
       que a varredura avança;
    3. os que sobram, analisados na ordem de custo, em lotes paralelos
       depois dos primeiros (``busca.primeiro_aprovado``).

    Até a R05 de 29/10 era uma bisseção com 8 vizinhos, que podia perder o
    ótimo porque a aprovação não cresce de forma estrita com o custo.
    """
    lista = [a for a in _candidatos_validos(pilar, As_necessaria, camadas)
             if not any(av.nivel_de(x) == av.ERRO
                        for x in arr_mod.verificar(a, pilar, nu,
                                                   As_necessaria))]
    if esb is not None:
        lista = (a for a in lista if not _rejeitado_pelo_piso(pilar, a, esb))
    return busca.primeiro_aprovado(lista, pilar, situacoes, nu,
                                   As_necessaria, minimo, esb)


def arranjo_imposto(pilar: Pilar) -> Arranjo:
    """Monta o arranjo diretamente do que foi informado, sem buscar nada.

    Público porque a pré-visualização da aba de entrada usa a mesma conta
    para desenhar as barras no modo "Verificar" antes mesmo de calcular --
    duplicar essa lógica ali divergiria da primeira vez que uma delas
    mudasse.
    """
    a = pilar.armadura
    if a.modo == "barras":
        phi = max((b[2] for b in a.barras), default=0.0)
        phi_t = a.phi_estribo or est_mod.bitola_comercial(phi)
        return arr_mod.montar_lista(pilar.secao, a.barras,
                                    pilar.cobrimento(phi, phi_t), phi_t)
    phi_t = a.phi_estribo or est_mod.bitola_comercial(a.phi)
    return arr_mod.montar(pilar.secao, pilar.cobrimento(a.phi, phi_t),
                          phi_t, a.phi, a.nx, a.ny,
                          a.n_barras or pilar.numero_de_barras(),
                          *_internas(pilar))


def _internas(pilar: Pilar) -> tuple[int, float]:
    """Camada interna da seção vazada: ``(n, ø)`` declarados na armadura."""
    a = pilar.armadura
    return a.n_barras_internas, a.phi_interna


# ---------------------------------------------------------------------------
# Cálculo completo
# ---------------------------------------------------------------------------

#: Aviso de ordem de grandeza: compressão tão baixa e F.S. tão alto que o
#: mais provável é a entrada estar na unidade errada (tf lançado como kN) --
#: o caso das memórias das OAE da ERS-531, F.S. de 6,7 a 30.
NU_SUSPEITO = 0.05
FS_SUSPEITO = 5.0


def _contexto_compat(pilar: Pilar):                         # COMPAT-PCALC
    if compat_pcalc is None or not pilar.config.compat_pcalc:
        return contextlib.nullcontext()
    return compat_pcalc.contexto(pilar)


def dimensionar(pilar: Pilar) -> ResultadoPilar:
    """Calcula o lance de pilar por inteiro, em todas as combinações de
    esforços (``Pilar.combinacoes``), com a mesma armadura; o resultado é o
    da combinação que governa."""
    # Ações características informadas: as combinações da Tabela 11.3
    # substituem os esforços de entrada
    pilar = acoes_mod.aplicar(pilar)
    modo = pilar.config.compat_pcalc                         # COMPAT-PCALC
    with _contexto_compat(pilar):                            # COMPAT-PCALC
        if pilar.config.metodo_2a_ordem == "pior":
            res = _dimensionar_pior(pilar)
        elif pilar.combinacoes or _desaprumo_por_direcao(pilar):
            res = _dimensionar_combinacoes(pilar)
        else:
            res = _dimensionar_unico(pilar)
    if modo and compat_pcalc is not None:                    # COMPAT-PCALC
        # O contexto devolve ao pilar a configuração do usuário; o resultado
        # tem de guardar a que o cálculo usou -- desaprumo, convenção da
        # base, gamma_n... --, senão qualquer saída que recalcule a partir de
        # ``res.pilar`` mostra números diferentes dos calculados. Cópias:
        # o pilar do usuário (o da janela) fica como estava.
        from dataclasses import replace
        trocas = compat_pcalc.configuracao(pilar)
        for r in (res.resultados_combinacoes or [res]):
            r.pilar = replace(r.pilar,
                              config=replace(r.pilar.config, **trocas))
        # todas as combinações, não só a que governa: o seletor da janela
        # mostra as outras, e elas também saem truncadas e com o aviso
        for r in (res.resultados_combinacoes or [res]):
            compat_pcalc.ajustar_resultado(r, modo)
            r.avisos.insert(0, av.construtivo(compat_pcalc.aviso(modo)))
        if modo == "total":
            for c in res.combinacoes:
                c.fs = math.floor(c.fs * 100 + 1e-9) / 100 \
                    if math.isfinite(c.fs) else c.fs
    elif modo:                                               # COMPAT-PCALC
        res.avisos.insert(0, av.construtivo(
            "O modo compatível com o PCalc não existe nesta versão do "
            "programa; o cálculo seguiu a NBR 6118:2026."))
    return res


def _dimensionar_unico(pilar: Pilar) -> ResultadoPilar:
    res = _dimensionar_lance(pilar)
    _avisos_finais(pilar, res)
    return res


def _avisos_finais(pilar: Pilar, res: ResultadoPilar) -> None:
    """Desaprumo somado e ordem de grandeza dos esforços."""
    extra = {d: pilar.desaprumo_balanco(d) * pilar.fator_esforcos / 100.0
             for d in ("x", "y")}
    if any(extra.values()):
        res.avisos.append(av.construtivo(
            "Desaprumo do pilar em balanço (item 11.3.3.4.1, θ1 = 1/200) "
            "somado ao momento de base: "
            + "; ".join(f"{d}: {num(v, 1)} kN·m" for d, v in extra.items() if v)
            + ("" if pilar.desaprumo_angulo is None else
               f". Balanço nas duas direções: θ1 é a inclinação do eixo na "
               f"direção mais desfavorável do plano, achada por busca "
               f"(ângulo {num(pilar.desaprumo_angulo, 1)}° na convenção "
               f"interna; acima, as componentes). A norma não fixa a direção "
               f"em flexão oblíqua; somar θ1 nas duas direções daria √2·θ1, "
               f"acima do θ1,máx = 1/200")
            + ". Vale para pilar isolado. Se o lance é parte de um pórtico "
              "cujos esforços já vêm do modelo global -- pilares de OAE com "
              "travessa, por exemplo --, desligue 'Desaprumo do pilar em "
              "balanço' nos critérios de cálculo."))
    fs = [v.fs for v in res.verificacoes if math.isfinite(v.fs)]
    if (pilar.Nd > 0.0 and fs and res.nu < NU_SUSPEITO
            and min(fs) > FS_SUSPEITO):
        res.avisos.append(av.construtivo(
            f"Ordem de grandeza: ν = {num(res.nu, 3)} e o menor F.S. é "
            f"{num(min(fs), 1)} -- esforços muito pequenos para a seção. Confira "
            f"as unidades da entrada (kN e kN·m; 1 tf = 10 kN e 1 tf·m = "
            f"10 kN·m) e se os esforços são mesmo de cálculo."))


def _margem(res: ResultadoPilar) -> float:
    fs = [v.fs for v in res.verificacoes if math.isfinite(v.fs)]
    mm = res.momento_minimo
    if mm is not None:
        fs += [x for x in (mm.fs_x, mm.fs_y, mm.fs_elipse)
               if x is not None and math.isfinite(x)]
    return min(fs, default=float("inf"))


def _linha_neutra_fora(secao: sc.SecaoDiscreta, pilar: Pilar,
                       res: "ResultadoPilar") -> bool:
    """Alguma situação de cálculo deixa a seção de concreto **inteiramente
    tracionada** (linha neutra fora da seção)? É o caso do 17.4.2.2-b em que
    a parcela Vc é nula."""
    from . import metodo_geral as mg
    vertices = [q for c in pilar.secao.contornos() for q in c]
    for v in res.verificacoes:
        est = mg.estado_por_esforcos(secao, pilar.Nd, v.situacao.Mx,
                                     v.situacao.My)
        if not est.ok:
            continue
        if max(est.e0 + est.kx * x + est.ky * y for x, y in vertices) <= 0.0:
            return True
    return False


def barra_tracionada(secao: sc.SecaoDiscreta, pilar: Pilar,
                     res: "ResultadoPilar") -> str:
    """Onde alguma barra fica tracionada sob as solicitações de cálculo, ou
    ``""`` se nenhuma fica.

    Para cada situação verificada -- e para as duas análises isoladas do
    momento mínimo -- resolve o plano de deformações que equilibra
    ``(Nd, Mx, My)`` com a armadura adotada e lê a deformação de cada barra.
    Situação que a seção não equilibra já reprova à parte e não entra aqui.
    """
    from . import metodo_geral as mg
    casos = [(v.situacao.nome, v.situacao.Mx, v.situacao.My)
             for v in res.verificacoes]
    mm = res.momento_minimo
    if mm is not None:
        casos += [("momento mínimo em x", mm.Msd_x, 0.0),
                  ("momento mínimo em y", 0.0, mm.Msd_y)]
    for nome, Mx, My in casos:
        est = mg.estado_por_esforcos(secao, pilar.Nd, Mx, My)
        if not est.ok:
            continue
        # chave explícita: duas barras com a mesma deformação faziam o min()
        # comparar os objetos Barra, que não têm ordem
        pior = min(((est.e0 + est.kx * b.x + est.ky * b.y, b)
                    for b in secao.barras),
                   key=lambda par: par[0]) if secao.barras else None
        if pior is not None and pior[0] < -1e-6:
            eps, b = pior
            return (f"na situação {nome}, a barra em ({num(b.x, 1)}; "
                    f"{num(b.y, 1)}) cm fica com εs = {num(eps, 2)} ‰ "
                    f"de tração")
    return ""


def impor_emenda_tracionada(res: "ResultadoPilar", motivo: str) -> None:
    """Refaz a ancoragem do lance com a emenda de barra tracionada, porque
    outra combinação (ou outro lance do mesmo projeto) a exigiu."""
    a_velho = res.ancoragem
    if a_velho is None or a_velho.tracionada or res.arranjo is None:
        return
    novo = anc.analisar(res.pilar, a_velho.phi, a_velho.As_calc,
                        a_velho.As_efet, tracionada=True, motivo=motivo)
    velhos = set(a_velho.avisos)
    res.avisos = [x for x in res.avisos if x not in velhos] + novo.avisos
    res.ancoragem = novo


def _armadura_de(a: Arranjo, pilar: Pilar):
    """O arranjo como armadura imposta, para conferir nas outras combinações.
    O estribo é o que o projetista impôs (zero = o programa escolhe): o
    ``phi_estribo`` do arranjo é só o suposto ao medir o recuo das barras, e
    passá-lo adiante como imposição fixava um "ø6,25" nas combinações."""
    from .modelo import Armadura
    return Armadura(modo="imposto", phi=a.phi, nx=a.nx, ny=a.ny,
                    n_barras=a.n_barras - a.n_internas,
                    n_barras_internas=a.n_internas,
                    phi_interna=a.phi_interna,
                    phi_estribo=pilar.armadura.phi_estribo,
                    s_estribo=pilar.armadura.s_estribo)


#: Limite de candidatos testados na busca da armadura comum às combinações.
CANDIDATOS_COMBINACOES = 60


def _armadura_comum(pilar: Pilar, variantes: list[Pilar]):
    """A armadura mais barata que atende a **todas** as combinações.

    Cada combinação acha o seu arranjo; o mais caro deles é o ponto de
    partida, conferido nas outras. Se alguma reprova, sobe-se na lista de
    candidatos (ordem de custo) até um que passe em todas."""
    from dataclasses import replace
    arranjos = []
    for v in variantes:
        with _contexto_compat(v):                            # COMPAT-PCALC
            r = _dimensionar_lance(v)
        if r.arranjo is not None:
            arranjos.append(r.arranjo)
    if not arranjos:
        return None, False

    peso = pilar.config.peso_por_barra

    def custo(a):
        return arr_mod.custo(a.phi, a.n_barras, pilar.secao, a.nx, a.ny, peso)
    inicio = max(arranjos, key=custo)

    # Erros de entrada (fck abaixo da CAA, λ fora da faixa
    # do método...) não somem trocando a armadura: uma combinação que os tem
    # nunca fica "ok", e exigir isso fazia a busca testar todos os
    # candidatos para nada -- e depois anunciar "a mais barata que atende a
    # todas". A armadura passa quando só restam esses erros.
    entrada = []
    for v in variantes:
        with _contexto_compat(v):                            # COMPAT-PCALC
            entrada.append({a for a in v.validar()
                            if av.nivel_de(a) == av.ERRO})

    def passa_em_todas(arm):
        for v, fixos in zip(variantes, entrada):
            with _contexto_compat(v):                        # COMPAT-PCALC
                r = _dimensionar_lance(replace(v, armadura=arm))
            if not r.ok and not set(r.erros) <= fixos:
                return False
        return True

    arm = _armadura_de(inicio, pilar)
    if passa_em_todas(arm):
        return arm, True
    simetria = any(_exige_simetria(v) for v in variantes)
    testados = 0
    for phi, nx, ny, n in arr_mod.candidatos(pilar.secao,
                                             pilar.config.bitolas_permitidas,
                                             peso=peso):
        if arr_mod.custo(phi, n, pilar.secao, nx, ny, peso) <= custo(inicio):
            continue
        phi_t = pilar.armadura.phi_estribo or est_mod.bitola_comercial(phi)
        a = arr_mod.montar(pilar.secao, pilar.cobrimento(phi, phi_t), phi_t,
                           phi, nx, ny, n, *_internas(pilar))
        if not a.cabe or (simetria and not a.simetrico):
            continue
        testados += 1
        if testados > CANDIDATOS_COMBINACOES:
            break
        cand = _armadura_de(a, pilar)
        if passa_em_todas(cand):
            return cand, True
    return arm, False   # nenhuma passou em todas: fica a de partida, reprovada


#: Rótulos curtos dos métodos de 2ª ordem, nas variantes do caso mais
#: conservador.
ROTULOS_METODO = {"curvatura": "curvatura aproximada",
                  "rigidez": "rigidez κ aproximada",
                  "diagrama": "M, N, 1/r",
                  "geral": "método geral"}


def metodos_aplicaveis(pilar: Pilar) -> list[str]:
    """Os métodos de 2ª ordem que a norma admite para este lance -- os que o
    critério "caso mais conservador" roda todos:

    * curvatura (15.8.3.3.2) e rigidez κ (15.8.3.3.3): λ <= 90 e armadura
      simétrica -- fora das seções L, T e U e da armadura imposta
      assimétrica; a rigidez só na seção retangular;
    * pilar-padrão com M, N, 1/r (15.8.3.3.4): λ <= 140;
    * método geral (15.8.3.2): sempre.

    O λ é o que governa os limites (o maior dos eixos principais na seção
    sem simetria)."""
    lam = max(esb_mod.analisar(pilar, d).lam_governante for d in ("x", "y"))
    simetrica = pilar.secao.tipo not in ("L", "T", "U")
    if simetrica and pilar.armadura.modo != "automatico":
        simetrica = arr_mod.barras_simetricas(arranjo_imposto(pilar).barras)
    metodos = []
    if lam <= ESBELTEZ_FLUENCIA and simetrica:
        metodos.append("curvatura")
        if pilar.secao.tipo == "retangular":
            metodos.append("rigidez")
    if lam <= ESBELTEZ_METODO_EXATO:
        metodos.append("diagrama")
    metodos.append("geral")
    return metodos


def _dimensionar_pior(pilar: Pilar) -> ResultadoPilar:
    """Critério "caso mais conservador": cada método aplicável em cada
    combinação, todos com a mesma armadura; vale o pior -- a reprovada de
    menor margem ou, sem reprovada, a de menor F.S. A tabela mostra todos."""
    from dataclasses import replace
    metodos = metodos_aplicaveis(pilar)
    bases = ([pilar.com_esforcos(pilar.esforcos, pilar.nome_combinacao)]
             + [pilar.com_combinacao(c) for c in pilar.combinacoes])
    bases = _expandir_desaprumo(pilar, bases)
    variantes = []
    for b in bases:
        for m in metodos:
            nome = (ROTULOS_METODO[m] if len(bases) == 1
                    else f"{b.nome_combinacao} · {ROTULOS_METODO[m]}")
            variantes.append(replace(
                b, nome_combinacao=nome,
                config=replace(b.config, metodo_2a_ordem=m)))
    res = _dimensionar_variantes(pilar, variantes, "verificações")
    for r in (res.resultados_combinacoes or [res]):
        r.metodos_pior = list(metodos)
    res.avisos.append(av.construtivo(
        "Critério de 2ª ordem \"caso mais conservador\": rodaram "
        + ", ".join(ROTULOS_METODO[m] for m in metodos)
        + f"; governa {res.combinacao_governante}."))
    return res


def _desaprumo_por_direcao(pilar: Pilar) -> bool:
    """Balanço nas duas direções e a variante ainda sem o ângulo do
    desaprumo: ele precisa ser buscado."""
    return (pilar.desaprumo_angulo is None
            and len(pilar.direcoes_desaprumo()) > 1)


#: Passo final da busca do ângulo do desaprumo, graus (resolução ~1°).
PASSO_ANGULO_DESAPRUMO = 2.0


def angulo_critico_desaprumo(v: Pilar) -> float:
    """O ângulo do desaprumo theta1 (inclinação do eixo, 11.3.3.4.1) que dá
    o menor F.S. nas cotas do lance, em graus.

    A norma não diz a direção do desaprumo em flexão oblíqua; vale a mais
    desfavorável. No balanço o desaprumo soma à base um vetor de módulo
    ``Nd theta1 l`` (um círculo no plano Mx-My); o F.S. varia suavemente
    com o ângulo. Busca: oito direções a cada 45°, a partir da do momento
    de base, e bissecção em torno da pior até :data:`PASSO_ANGULO_DESAPRUMO`.
    Com armadura automática, a busca usa o arranjo dimensionado na direção
    do momento de base."""
    from dataclasses import replace
    busca = v
    if v.config.metodo_2a_ordem == "pior":
        busca = replace(v, config=replace(
            v.config, metodo_2a_ordem=metodos_aplicaveis(v)[0]))
    bx, by = (busca.momento_base_sem_desaprumo(d) for d in ("x", "y"))
    a0 = math.degrees(math.atan2(by, bx)) if (bx or by) else 0.0
    if busca.armadura.modo == "automatico":
        arm, _ = _armadura_comum(busca, [replace(busca, desaprumo_angulo=a0)])
        if arm is not None:
            busca = replace(busca, armadura=arm)
    cache: dict[float, tuple] = {}

    def chave(a: float) -> tuple:
        a = round(a % 360.0, 6)
        if a not in cache:
            r = _dimensionar_lance(replace(busca, desaprumo_angulo=a))
            fs = min((x.fs for x in r.verificacoes if math.isfinite(x.fs)),
                     default=math.inf)
            cache[a] = (r.ok, fs)
        return cache[a]

    pior = min(((a0 + 45.0 * k) % 360.0 for k in range(8)), key=chave)
    passo = 22.5
    while passo >= PASSO_ANGULO_DESAPRUMO:
        pior = min((pior, (pior - passo) % 360.0, (pior + passo) % 360.0),
                   key=chave)
        passo /= 2.0
    return round(pior % 360.0, 1)


def _expandir_desaprumo(pilar: Pilar, variantes: list[Pilar]) -> list[Pilar]:
    """Com balanço nas duas direções, cada variante recebe o ângulo crítico
    do desaprumo (:func:`angulo_critico_desaprumo`)."""
    from dataclasses import replace
    if not _desaprumo_por_direcao(pilar):
        return variantes
    return [replace(v, desaprumo_angulo=angulo_critico_desaprumo(v))
            for v in variantes]


def _dimensionar_combinacoes(pilar: Pilar) -> ResultadoPilar:
    """Todas as combinações com a mesma armadura; vale a pior."""
    variantes = ([pilar.com_esforcos(pilar.esforcos, pilar.nome_combinacao)]
                 + [pilar.com_combinacao(c) for c in pilar.combinacoes])
    variantes = _expandir_desaprumo(pilar, variantes)
    return _dimensionar_variantes(pilar, variantes, "combinações")


def _dimensionar_variantes(pilar: Pilar, variantes: list[Pilar],
                           rotulo: str) -> ResultadoPilar:
    """Variantes do lance (combinações, métodos) com a mesma armadura; vale
    a pior."""
    from dataclasses import replace
    if len(variantes) == 1:
        with _contexto_compat(variantes[0]):                 # COMPAT-PCALC
            res = _dimensionar_unico(variantes[0])
        res.combinacao_governante = variantes[0].nome_combinacao
        return res
    achou = True
    if pilar.armadura.modo == "automatico":
        arm, achou = _armadura_comum(pilar, variantes)
        if arm is not None:
            variantes = [replace(v, armadura=arm) for v in variantes]
    resultados = []
    for v in variantes:
        with _contexto_compat(v):                            # COMPAT-PCALC
            resultados.append(_dimensionar_unico(v))
    # governa a reprovada de menor margem; sem reprovada, a de menor margem
    i_gov = min(range(len(resultados)),
                key=lambda i: (resultados[i].ok, _margem(resultados[i])))
    res = resultados[i_gov]
    res.combinacao_governante = variantes[i_gov].nome_combinacao
    for i, (v, r) in enumerate(zip(variantes, resultados)):
        e, f = v.esforcos, v.fator_esforcos
        mm = r.momento_minimo
        res.combinacoes.append(ResumoCombinacao(
            nome=v.nome_combinacao, Nd=f * e.Nd,
            Mx_topo=f * e.Mx_topo / 100, Mx_base=f * e.Mx_base / 100,
            My_topo=f * e.My_topo / 100, My_base=f * e.My_base / 100,
            fs=min((x.fs for x in r.verificacoes), default=float("inf")),
            fs_minimo=(min(x for x in (mm.fs_x, mm.fs_y, mm.fs_elipse)
                           if x is not None) if mm else float("inf")),
            ok=r.ok, erro=r.erros[0] if r.erros else "",
            governante=(i == i_gov), descricao=v.descricao_combinacao))
        if i != i_gov and not r.ok:
            res.avisos.append(av.erro(
                f"Combinação {v.nome_combinacao}: {r.erros[0]}"))
    # Emenda tracionada: se alguma combinação traciona alguma barra, todas
    # as combinações (é a mesma armadura, a mesma obra) levam o l0t.
    tracionadas = [(v, r) for v, r in zip(variantes, resultados)
                   if r.ancoragem is not None and r.ancoragem.tracionada]
    if tracionadas:
        v0, r0 = tracionadas[0]
        motivo = f"combinação {v0.nome_combinacao}, {r0.ancoragem.motivo}"
        for r in resultados:
            impor_emenda_tracionada(r, motivo)
    # Um comprimento de espera só: as combinações são o mesmo pilar, e o
    # As,calc de cada uma dava um l0 diferente. Vale o maior.
    com_anc = [r for r in resultados if r.ancoragem is not None]
    if com_anc:
        maior = max(com_anc, key=lambda r: r.ancoragem.l0c).ancoragem
        for r in com_anc:
            if r.ancoragem is not maior:
                velhos = set(r.ancoragem.avisos)
                r.avisos = [x for x in r.avisos if x not in velhos] \
                    + maior.avisos
                r.ancoragem = maior
    # cada resultado conhece a tabela e os demais (o seletor da janela troca
    # de um para outro sem recalcular)
    for r in resultados:
        r.combinacoes = res.combinacoes
        r.combinacao_governante = res.combinacao_governante
        r.resultados_combinacoes = resultados
    automatica = pilar.armadura.modo == "automatico"
    margem = _margem(res)
    res.avisos.append(av.construtivo(
        f"{len(variantes)} {rotulo} com a mesma armadura"
        + ((" (a mais barata que atende a todas)" if achou else
            " (nenhum arranjo testado atende a todas; ficou o de partida, "
            "o mais caro dos que cada combinação pediu sozinha)")
           if automatica else "")
        + f"; governa {res.combinacao_governante}"
        + (f" (menor F.S. = {num(margem, 2)})" if math.isfinite(margem) else "")
        + "."))
    return res


def _dimensionar_lance(pilar: Pilar) -> ResultadoPilar:
    """Calcula o lance de pilar por inteiro, numa combinação."""
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
    # Nos métodos cuja 2ª ordem depende da armadura, a estimativa de partida
    # (curvatura) não serve de piso: daria mais 2ª ordem que o método e
    # impediria a busca de chegar ao arranjo mais leve. O piso é a 1ª ordem.
    sit_piso = res.situacoes
    if so_mod.metodo_efetivo(pilar) in METODOS_COM_SECAO:
        sem = {d: SegundaOrdem(direcao=d, aplicavel=False)
               for d in ("x", "y")}
        sit_piso = so_mod.situacoes(pilar, res.esbeltez, sem)
    # O roteiro de duas camadas é opcional e só informativo: ignora as
    # barras intermediárias das faces e, usado como filtro da busca ou como
    # reprovação, descartava arranjos que o motor seccional aprova.
    usar_fc = pilar.config.metodo_duas_camadas
    if usar_fc:
        camadas, dim_fechado, avisos_fc = _armadura_necessaria(
            pilar, sit_piso, d_linha)
        res.dim_fechado = dim_fechado
        res.camadas_necessarias = camadas
        res.avisos.extend(avisos_fc)
        res.As_necessaria = max(2.0 * max(camadas.values(), default=0.0),
                                res.As_minima)
    else:
        res.As_necessaria = res.As_minima

    # -- 4. arranjo das barras ---------------------------------------------
    if pilar.armadura.modo in ("imposto", "barras"):
        res.arranjo = arranjo_imposto(pilar)
    else:
        minimo = None
        if pilar.config.momento_minimo_metodo == "envoltoria":
            minimo = _semi_eixos_minimo(pilar, res.esbeltez)
        # a busca parte da armadura mínima: quem aprova é o motor seccional
        escolhido, avisos_busca = _escolher_arranjo(
            pilar, res.situacoes, res.nu, res.As_minima, {}, minimo,
            res.esbeltez)
        if escolhido is None:
            res.avisos.append(av.erro(
                "Nenhum arranjo de barras atendeu a todas as verificações "
                "com as bitolas permitidas. Aumente a seção, a classe do "
                "concreto ou libere bitolas maiores nos critérios."
                + _causa_normal(pilar)))
            res.avisos.extend(avisos_busca)
            return res
        res.arranjo = escolhido

    a = res.arranjo
    # a taxa mínima tem conferência própria no arranjo; sem o roteiro de
    # duas camadas não há outra "As necessária" a comparar
    res.avisos.extend(arr_mod.verificar(
        a, pilar, res.nu, res.As_necessaria if res.dim_fechado else 0.0))
    if (not a.simetrico and so_mod.metodo_efetivo(pilar) in
            METODOS_ARMADURA_SIMETRICA):
        res.avisos.append(av.erro(
            "Armadura assimétrica: os métodos do pilar-padrão com curvatura e "
            "com rigidez aproximadas só valem com armadura simétrica (itens "
            "15.8.3.3.2 e 15.8.3.3.3). Use o pilar-padrão acoplado a "
            "diagramas M, N, 1/r ou o método geral."))

    # -- 5. recálculo dos casos fechados com o d' definitivo ---------------
    if usar_fc and pilar.secao.tem_casos_fechados:
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
    if so_mod.metodo_efetivo(pilar) in METODOS_COM_SECAO:
        # 2ª ordem que depende da armadura: agora com as barras definitivas;
        # a da etapa 1 foi só a estimativa de partida da busca
        if pilar.config.metodo_2a_ordem == "geral":
            lista, so = _situacoes_geral(pilar, res.esbeltez, secao)
            res.segunda_ordem.update(so)
            # o erro de convergência sai igual nas duas direções: uma vez só
            vistos = set()
            for d in ("x", "y"):
                for x in so[d].avisos:
                    if x not in vistos:
                        vistos.add(x)
                        res.avisos.append(x)
            if lista is None:
                return res
            res.situacoes = lista
        else:
            for direcao in ("x", "y"):
                s = so_mod.analisar(pilar, res.esbeltez[direcao], secao)
                res.segunda_ordem[direcao] = s
                res.avisos.extend(av.prefixar(x, f"Direção {direcao}: ")
                                  for x in s.avisos)
            if any(not math.isfinite(res.segunda_ordem[d].e2)
                   for d in ("x", "y")):
                return res
            res.situacoes = so_mod.situacoes(pilar, res.esbeltez,
                                             res.segunda_ordem)
        # a estimativa da etapa 1 e o cálculo final repetem avisos iguais
        res.avisos = list(dict.fromkeys(res.avisos))
        res.situacoes_partida = res.situacoes
        res.governante = so_mod.governante(res.situacoes)
    # A busca do arranjo (passos 3 a 5, acima) usa sempre os três pontos do
    # item 15.8.3.3.5 -- ``situacoes_partida`` --, mesmo com a varredura
    # contínua ligada: ela é só um palpite inicial de armadura, barato de
    # propósito, e quem dá o veredito é esta verificação final. Ligada a
    # varredura, ``res.situacoes`` passa a ser o que de fato foi verificado,
    # e com ela a situação governante -- do contrário o relatório apontaria
    # como governante um ponto que a verificação final nem olhou.
    if pilar.config.verificacao_altura == "continua":
        # A varredura carrega alfa_b M1d,A + 2ª ordem: nas pontas isso é
        # menos que o momento real quando alfa_b < 1. Os dois extremos, com
        # o momento de cada ponta (e o piso do mínimo no método "planilha"),
        # entram junto -- antes só apareciam na tabela informativa de F.S.
        # por cota, e um extremo reprovado passava sem erro.
        res.situacoes = [
            _situacao_extremo_real(pilar, res.esbeltez, "Topo",
                                   pilar.esforcos.Mx_topo,
                                   pilar.esforcos.My_topo),
            _situacao_extremo_real(pilar, res.esbeltez, "Base",
                                   pilar.momento_base("x"),
                                   pilar.momento_base("y")),
        ]
        if (pilar.config.momento_minimo_metodo == "planilha"
                and not pilar.config.piso_minimo_bidirecional):
            # o piso de uma direção de cada vez, nos extremos
            res.situacoes += [s for s in so_mod.situacoes(
                pilar, res.esbeltez, res.segunda_ordem)
                if s.posicao == "extremo"]
        res.situacoes += so_mod.situacoes_altura(pilar, res.esbeltez,
                                                 res.segunda_ordem)
        res.governante = so_mod.governante(res.situacoes)
    res.verificacoes = [_verificar(secao, pilar, s, rigorosa=True)
                        for s in res.situacoes]
    # Normal acima da resistente: um erro só, com a causa e a conta. As
    # situações e o mínimo continuam calculados (F.S. = 0, envoltória
    # inatingível), mas os erros deles -- "MRd = 0", interação infinita --
    # são consequência deste e só confundiam a leitura.
    res.normal = verificar_normal(secao, pilar.Nd)
    normal_esgotada = not res.normal.ok
    if normal_esgotada:
        res.avisos.append(av.erro(mensagem_normal(res.normal)))
    for v in (res.verificacoes if not normal_esgotada else ()):
        if not v.ok_interacao and not v.interacao_exigida and v.ok_envoltoria:
            res.avisos.append(av.construtivo(
                f"{v.situacao.nome}: a expressão aproximada do item 17.2.5 dá "
                f"{num(v.interacao, 3)} > 1 (α = {num(pilar.alfa_interacao)}), mas "
                f"o critério de projeto adota a envoltória de equilíbrio, que "
                f"aprova (F.S. = {num(v.fs, 2)}). A expressão fica informativa."))
        if not v.ok_interacao_exigida:
            res.avisos.append(av.erro(
                f"{v.situacao.nome}: a expressão de interação do item 17.2.5 "
                f"dá {num(v.interacao, 3)} > 1 -- "
                f"(MSd,x/MRd,xx)^{num(pilar.alfa_interacao)} + "
                f"(MSd,y/MRd,yy)^{num(pilar.alfa_interacao)} com "
                f"MSd,x = {num(v.situacao.Mx / 100, 1)} kN·m contra "
                f"MRd,xx = {num(v.MRd_xx / 100, 1)} kN·m e "
                f"MSd,y = {num(v.situacao.My / 100, 1)} kN·m contra "
                f"MRd,yy = {num(v.MRd_yy / 100, 1)} kN·m."))
        elif v.envoltoria_inatingivel:
            res.avisos.append(av.erro(
                f"{v.situacao.nome}: nenhuma linha neutra produz momento "
                f"resistente na direção do momento solicitante "
                f"({num(v.MSd / 100, 1)} kN·m) para Nd = {num(pilar.Nd, 0)} kN. Isso "
                f"acontece perto da compressão quase uniforme -- o momento "
                f"resistente tende a zero em toda direção -- e, em seção "
                f"assimétrica, também longe dali: a direção do momento "
                f"resistente pode ficar restrita a uma faixa que não cobre "
                f"os 360° (CADAMURO JÚNIOR, 1997, item 5.5). A expressão "
                f"aproximada do item 17.2.5 deu {num(v.interacao, 3)} sem "
                f"acusar isso, mas a seção não tem como equilibrar momento "
                f"algum nessa direção com essa força normal."))
        elif not v.ok_envoltoria:
            if v.MRd_envoltoria_inferior > 0.0:
                res.avisos.append(av.erro(
                    f"{v.situacao.nome}: o momento solicitante resultante "
                    f"({num(v.MSd / 100, 1)} kN·m) cai fora do intervalo "
                    f"[{num(v.MRd_envoltoria_inferior / 100, 1)}; "
                    f"{num(v.MRd_envoltoria / 100, 1)}] kN·m em que a envoltória "
                    f"admite momento naquela direção -- há duas linhas "
                    f"neutras que produzem momento resistente na mesma "
                    f"direção (CADAMURO JÚNIOR, 1997, fig. 6.1b), e a seção "
                    f"só resiste entre as duas."))
            else:
                res.avisos.append(av.erro(
                    f"{v.situacao.nome}: o momento solicitante resultante "
                    f"({num(v.MSd / 100, 1)} kN·m) está fora da envoltória de "
                    f"momentos resistentes ({num(v.MRd_envoltoria / 100, 1)} "
                    f"kN·m na mesma direção), embora a expressão aproximada "
                    f"do item 17.2.5 tenha dado {num(v.interacao, 3)}. Vale a "
                    f"envoltória: ela vem do equilíbrio da seção, e o "
                    f"expoente 1,2 é uma aproximação que aqui ficou contra "
                    f"a segurança."))

    # -- 6a. momento mínimo, verificado à parte (item 3.1 da apostila) -----
    if pilar.config.momento_minimo_metodo == "envoltoria":
        mm = _verificar_momento_minimo(secao, pilar, res.esbeltez)
        res.momento_minimo = mm
        if not mm.ok and not normal_esgotada:
            lados = []
            if not mm.ok_x:
                lados.append(
                    f"{mm.rotulos[0]} (Md,tot,min = {num(mm.Msd_x / 100, 1)} kN·m contra "
                    f"MRd = {num(mm.MRd_x / 100, 1)} kN·m)")
            if not mm.ok_y:
                lados.append(
                    f"{mm.rotulos[1]} (Md,tot,min = {num(mm.Msd_y / 100, 1)} kN·m contra "
                    f"MRd = {num(mm.MRd_y / 100, 1)} kN·m)")
            if not mm.ok_elipse:
                pior = max((p for p in mm.pontos_elipse if not p[3]),
                           key=lambda p: p[2])
                lados.append(
                    f"um ponto intermediário da elipse "
                    f"(Mx = {num(pior[0] / 100, 1)}; My = {num(pior[1] / 100, 1)} "
                    f"kN·m; MSd/MRd = {num(pior[2], 2)}) -- onde os dois mínimos "
                    f"agem juntos, em flexão oblíqua")
            res.avisos.append(av.erro(
                "Momento mínimo (item 11.3.3.4.3): a envoltória mínima com "
                "2ª ordem (Figuras 11.3 e 15.2) não está contida na "
                "envoltória resistente em " + " e ".join(lados) + ". É a "
                "verificação isolada da imperfeição geométrica local, "
                "independente do momento real."))

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
    v_topo = _verificar(secao, pilar, topo, rigorosa=True)
    v_base = _verificar(secao, pilar, base, rigorosa=True)
    v_meio = max(meios, key=lambda v: v.razao_envoltoria)
    # Método geral: as seções extremas da barra discretizada já trazem a 2ª
    # ordem da cota delas -- no balanço, o engaste (z = 0) é onde ela é
    # máxima. Entram na cota física correspondente, com a pior valendo.
    # (13/11/2026, contraprova independente da 2ª ordem: no CIR-024 a "Base"
    # do balanço saía com F.S. 1,426, a 1ª ordem com o desaprumo, enquanto a
    # seção z = 0 do próprio método geral dava 1,334, o valor da contraprova.)
    for v in res.verificacoes:
        zr = v.situacao.z_rel
        if zr is None:
            continue
        if zr <= 1e-9 and v.razao_envoltoria > v_base.razao_envoltoria:
            v_base = v
        elif zr >= 1.0 - 1e-9 and v.razao_envoltoria > v_topo.razao_envoltoria:
            v_topo = v
    # As três cotas físicas, sempre -- é o que se compara com o topo, o meio
    # e a base do PCalc; a apresentação (``verificacoes_z``) é que junta o
    # meio à base no balanço.
    res.verificacoes_cotas = {"Topo": v_topo, "Meio": v_meio, "Base": v_base}
    if pilar.lance.vinculo_x == 3 and pilar.lance.vinculo_y == 3:
        # Balanço: a seção intermediária do pilar-padrão (αb M1d,A + Nd e2) é
        # fisicamente o engaste -- a 2ª ordem é máxima na base e nula na
        # ponta livre. A cota "Meio" sai e a "Base" fica com a pior das duas,
        # com a 2ª ordem; antes a tabela mostrava a base sem ela, com F.S.
        # maior que o real, e a meia altura física não governa nada.
        res.verificacoes_z = {
            "Topo": v_topo,
            "Base": max((v_base, v_meio), key=lambda v: v.razao_envoltoria),
        }
    else:
        res.verificacoes_z = {"Topo": v_topo, "Meio": v_meio, "Base": v_base}

    # -- 7. armadura transversal e ancoragem -------------------------------
    # O momento **total** de cada direção (com a 2ª ordem) é o MSd,max da
    # razão M0/MSd,max do item 17.4.2.2. Entra no dimensionamento do estribo
    # e na verificação da cortante, os dois: com só o de 1ª ordem no
    # primeiro, o estribo saía dimensionado com um Vc maior e a verificação
    # logo depois o reprovava.
    momentos = {
        d: max((abs(v.situacao.Mx if d == "x" else v.situacao.My)
                for v in res.verificacoes), default=0.0)
        for d in ("x", "y")}
    # Flexo-tração com a linha neutra fora da seção: Vc = 0 (17.4.2.2-b).
    # A posição da linha neutra é a dos esforços de cálculo -- o estado de
    # deformações que equilibra (Nd, Mx, My) --, e não a da ruptura.
    ln_fora = pilar.Nd < 0.0 and _linha_neutra_fora(secao, pilar, res)
    res.estribos = est_mod.dimensionar(pilar, a, secao, momentos, ln_fora)
    res.avisos.extend(res.estribos.avisos)
    # Estribo engrossado (para dispensar grampos): as barras tinham sido
    # posicionadas com o recuo do estribo antigo, alguns milímetros para fora
    # do real, e o cobrimento conferido com a bitola antiga. Refaz-se o lance
    # com o estribo novo imposto e o mesmo arranjo.
    if (pilar.armadura.phi_estribo <= 0.0 and a.phi_estribo > 0.0
            and res.estribos.phi > a.phi_estribo + 1e-9):
        from dataclasses import replace
        if pilar.armadura.modo == "automatico":
            arm = _armadura_de(a, pilar)
        else:
            arm = replace(pilar.armadura)
        arm.phi_estribo = res.estribos.phi
        novo = _dimensionar_lance(replace(pilar, armadura=arm))
        aviso_engrosso = [x for x in res.estribos.avisos
                          if "engrossado" in x]
        novo.pilar = pilar
        novo.avisos = aviso_engrosso + [av.construtivo(
            f"Arranjo reposicionado com o estribo ø{num(res.estribos.phi)} mm "
            f"(recuo das barras e cobrimento conferidos com a bitola final).")
            ] + novo.avisos
        return novo
    tracao = barra_tracionada(secao, pilar, res)
    # As,calc da ancoragem: sem o roteiro de duas camadas não há uma "As
    # necessária" calculada -- fica a efetiva (relação 1, o lado seguro)
    As_calc = min(res.As_necessaria, a.As) if usar_fc else a.As
    res.ancoragem = anc.analisar(pilar, a.phi, As_calc, a.As,
                                 tracionada=bool(tracao), motivo=tracao)
    res.avisos.extend(res.ancoragem.avisos)

    # -- 7b. força cortante (item 17.4, modelo I) --------------------------
    # Depois dos estribos, porque a parcela Vsw depende do espaçamento
    # adotado.
    res.cisalhamento = cis_mod.verificar(pilar, a, res.estribos, secao,
                                        momentos, ln_fora)
    for c in res.cisalhamento.values():
        res.avisos.extend(c.avisos)

    # -- 7c. estado-limite de serviço: abertura de fissuras ----------------
    from . import servico as els
    res.servico = els.verificar(pilar, a)
    res.avisos.extend(res.servico.avisos)
    if pilar.config.obra_ponte:
        res.avisos.extend(els.avisos_ponte(pilar))
    from . import fadiga as fad
    res.fadiga = fad.verificar(pilar, a)
    res.avisos.extend(res.fadiga.avisos)
    # -- 7d. situação de incêndio (NBR 15200) ------------------------------
    # Módulo interno, fora da interface e das saídas: os métodos de pilar da
    # NBR 15200 dependem do gamma_z da estrutura, que este programa não
    # conhece. Fica para quem conhece (o programa de pórticos): liga
    # ``config.incendio`` e lê ``res.incendio`` -- os avisos ficam lá, e não
    # nos do lance, para não reprovar nem aparecer aqui.
    from . import incendio as inc
    res.incendio = inc.verificar(pilar, res)

    # -- 8. conferência cruzada --------------------------------------------
    res.conferencias = _conferir(pilar, res, secao)
    for c in res.conferencias:
        if not c.ok:
            res.avisos.append(av.construtivo(
                f"Conferência de {c.grandeza}: o roteiro dos casos fechados "
                f"dá {num(c.fechado, 1)} e o motor seccional {num(c.seccional, 1)}, "
                f"{num(c.divergencia * 100, 1)} % de diferença. A divergência é "
                f"esperada e tem duas causas conhecidas -- o modelo de duas "
                f"camadas ignora as barras intermediárias das faces, que "
                f"contam na força normal, e o diagrama retangular simplificado "
                f"afasta-se do parábola-retângulo quando a seção fica quase "
                f"toda comprimida. Vale o motor seccional."))
    return res


def _conferir(pilar: Pilar, res: ResultadoPilar,
              secao: sc.SecaoDiscreta) -> list[Conferencia]:
    """Confronta ``MRd`` dos casos fechados com o do motor seccional."""
    if not (pilar.config.metodo_duas_camadas
            and pilar.secao.tem_casos_fechados and res.arranjo
            and pilar.armadura.modo != "barras"):
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


# ---------------------------------------------------------------------------
# Outras opções de armação (a lista que o projetista escolhe)
# ---------------------------------------------------------------------------

@dataclass
class OpcaoArmadura:
    """Um arranjo aprovado, com o resultado completo dele já calculado."""

    descricao: str
    As: float                    # cm²
    taxa: float                  # As/Ac
    n_barras: int
    custo: float                 # relativo ao do arranjo escolhido (1,00)
    fs: float                    # menor F.S. (inf sem momento)
    armadura: object             # modelo.Armadura imposta deste arranjo
    resultado: ResultadoPilar
    escolhida: bool = False


def _descricao_opcao(a) -> str:
    """O arranjo, com a disposição nas faces na seção retangular."""
    if a.nx and a.ny:
        return f"{a.descricao()} — {a.nx} × {a.ny} por face"
    return a.descricao()


#: Teto de candidatos verificados ao montar a lista de opções.
CANDIDATOS_OPCOES = 40


def opcoes_armadura(pilar: Pilar, res: ResultadoPilar, n: int = 6,
                    progresso=None) -> list[OpcaoArmadura]:
    """O arranjo escolhido e os seguintes aprovados, em ordem de custo.

    Parte do arranjo da busca automática (``res``) e percorre os candidatos
    mais caros que ele, na mesma ordem de custo (``Config.peso_por_barra``),
    com os mesmos filtros de detalhamento; cada um é **verificado por
    inteiro** -- ``dimensionar`` com o arranjo imposto, em todas as
    combinações e, no caso mais conservador, em todos os métodos --, e só os
    aprovados entram. O resultado de cada opção fica guardado: escolher uma
    não recalcula. Para em ``n`` opções ou em :data:`CANDIDATOS_OPCOES`
    candidatos verificados. ``progresso(feitos, total, recado)`` é chamado a
    cada candidato.
    """
    from dataclasses import replace
    a0 = res.arranjo
    if pilar.armadura.modo != "automatico" or a0 is None or not res.ok:
        return []
    peso = pilar.config.peso_por_barra
    Ac = pilar.secao.area

    def custo(phi, nb, nx, ny):
        return arr_mod.custo(phi, nb, pilar.secao, nx, ny, peso)

    c0 = custo(a0.phi, a0.n_barras, a0.nx, a0.ny)
    opcoes = [OpcaoArmadura(
        descricao=_descricao_opcao(a0), As=a0.As, taxa=a0.As / Ac,
        n_barras=a0.n_barras, custo=1.0, fs=_margem(res),
        armadura=_armadura_de(a0, pilar), resultado=res, escolhida=True)]
    if pilar.config.metodo_2a_ordem == "pior":
        simetria = any(m in METODOS_ARMADURA_SIMETRICA
                       for m in metodos_aplicaveis(pilar)) and \
            pilar.secao.tipo in SECOES_DUPLAMENTE_SIMETRICAS
    else:
        simetria = _exige_simetria(pilar)
    testados = 0
    # uma opção por (bitola, número de barras): a mesma armadura em outra
    # disposição nas faces não é outra escolha de projeto, e a primeira na
    # ordem de custo já é a de espaçamento mais uniforme (o desempate)
    vistos = {(a0.phi, a0.n_barras)}
    for phi, nx, ny, nb in arr_mod.candidatos(
            pilar.secao, pilar.config.bitolas_permitidas, peso=peso):
        if len(opcoes) >= n or testados >= CANDIDATOS_OPCOES:
            break
        if (phi, nb) in vistos:
            continue
        if custo(phi, nb, nx, ny) < c0 or nb * area_barra(phi) / Ac > \
                RHO_MAXIMO + 1e-9:
            continue
        phi_t = pilar.armadura.phi_estribo or est_mod.bitola_comercial(phi)
        a = arr_mod.montar(pilar.secao, pilar.cobrimento(phi, phi_t), phi_t,
                           phi, nx, ny, nb, *_internas(pilar))
        if not a.cabe or (simetria and not a.simetrico):
            continue
        testados += 1
        vistos.add((phi, nb))
        if progresso is not None:
            progresso(testados, CANDIDATOS_OPCOES,
                      f"{a.descricao()} -- {len(opcoes) - 1} opção(ões) "
                      f"além da escolhida")
        arm = _armadura_de(a, pilar)
        r = dimensionar(replace(pilar, armadura=arm))
        if r.ok and r.arranjo is not None:
            opcoes.append(OpcaoArmadura(
                descricao=_descricao_opcao(r.arranjo), As=r.arranjo.As,
                taxa=r.arranjo.As / Ac, n_barras=r.arranjo.n_barras,
                custo=custo(phi, nb, nx, ny)[0] / c0[0], fs=_margem(r),
                armadura=arm, resultado=r))
    return opcoes
