# -*- coding: utf-8 -*-
"""
dimensionar.py
Orquestra o cálculo do pavimento e devolve o :class:`ResultadoPavimento`.

A sequência é a do projeto, e a ordem importa:

1. **conferir a entrada** -- vinculação, nomes, bordas comuns declaradas;
2. **pré-dimensionar a espessura**, quando pedido, pelo laço do §1.6;
3. **momentos de cada laje isolada**, nos dois regimes;
4. **compatibilizar** os momentos negativos das bordas comuns (14.7.6.2) --
   e é aqui que o cálculo deixa de ser laje por laje e passa a ser do
   pavimento;
5. **flexão** de cada seção, com a altura útil da face e o mínimo do tipo;
6. **serviço**: flecha e, quando pedida, fissuração;
7. **cortante** de cada bordo pelo item 19.4, com o As1 que a armadura
   positiva escolhida entrega;
8. **detalhamento**: bitola, espaçamento, comprimentos e posições -- com a
   armadura da borda comum saindo **uma só vez**, para o maior momento e a
   menor altura útil;
9. **reações**, que é o que as vigas vão receber;
10. **quantitativo** e **avisos**.

O passo 5 depende do 4 e o 7 depende do 8: a armadura negativa da borda comum
não existe antes da compatibilização, e o VRd1 não existe antes de saber
quantos centímetros quadrados de armadura positiva chegam ao apoio.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from . import ancoragem as anc
from . import atribuicao as atr
from . import avisos as av
from . import cisalhamento as cis
from . import cantos as cnt
from . import compatibilizacao as compat
from . import puncao as pun
from . import detalhamento as det
from . import els as els_mod
from . import emenda as em
from . import esforcos as esf_mod
from . import flexao as fx
from . import formas as fm
from . import mef_pavimento as mef
from . import materiais as mt
from . import reacoes as rc
from .esforcos import BORDOS_DA_DIRECAO, Esforcos
from .modelo import Config, Laje, Pavimento


# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------

@dataclass
class ResultadoLaje:
    """Tudo o que o programa apurou sobre uma laje."""

    laje: Laje
    esforcos: Esforcos
    flexoes: list[fx.ResultadoFlexao] = field(default_factory=list)
    els: els_mod.ResultadoELS | None = None
    cortantes: list[cis.ResultadoCortante] = field(default_factory=list)
    reacoes: rc.ReacoesLaje | None = None
    posicoes: list[det.Posicao] = field(default_factory=list)
    escolhas: dict[str, det.Escolha] = field(default_factory=dict)
    formas: fm.FormasLaje | None = None
    ancoragens: list[anc.ResultadoAncoragem] = field(default_factory=list)
    #: (R11) punção sob as cargas concentradas (19.5)
    puncoes: list[pun.ResultadoPuncao] = field(default_factory=list)
    fissuracoes: list[els_mod.ResultadoFissuracao] = field(
        default_factory=list)
    predimensionamento: els_mod.Predimensionamento | None = None
    avisos: list[av.Aviso] = field(default_factory=list)

    @property
    def nome(self) -> str:
        return self.laje.nome

    @property
    def massa(self) -> float:
        return sum(p.massa for p in self.posicoes)

    def flexao_de(self, rotulo: str) -> fx.ResultadoFlexao | None:
        for f in self.flexoes:
            if f.rotulo == rotulo:
                return f
        return None

    @property
    def erros(self) -> list[av.Aviso]:
        return [a for a in self.avisos if a.erro]


@dataclass
class VerificacaoCobrimento:
    """Prova de que o ``d`` usado na flexão cobre a bitola de fato adotada.

    Só a face superior tem esta pendência: o cobrimento dela pode cair a
    15 mm quando é revestida (7.4.7.5), mas nunca menos que a bitola da
    barra -- e a bitola só é conhecida **depois** que a armadura foi
    calculada, que depende de ``d``, que depende do cobrimento. É um ciclo, e
    ``_negativa_convergente`` fecha esse ciclo; este registro é a prova de
    que fechou, para a memória de cálculo poder mostrar o resultado.
    """

    rotulo: str
    cobrimento_usado: float         # cm, o que gerou o d desta armadura
    bitola_adotada: float           # mm
    cobrimento_exigido: float       # cm, para a bitola de fato adotada
    convergiu: bool

    @property
    def atende(self) -> bool:
        return self.cobrimento_usado >= self.cobrimento_exigido - 1e-6


@dataclass
class SegmentoApoio:
    """Trecho de viga que recebe carga -- o que a laje entrega à estrutura."""

    rotulo: str
    x0: float                       # m
    y0: float
    x1: float
    y1: float
    comprimento: float              # m
    lajes: list[str] = field(default_factory=list)
    v_g: float = 0.0                # kN/m
    v_q: float = 0.0
    v_k: float = 0.0
    v_d: float = 0.0
    continuidade: bool = False


@dataclass
class ResultadoPavimento:
    """Resultado do pavimento inteiro."""

    pavimento: Pavimento
    lajes: list[ResultadoLaje] = field(default_factory=list)
    compatibilizacao: compat.Compatibilizacao | None = None
    posicoes_continuidade: list[det.Posicao] = field(default_factory=list)
    apoios: list[SegmentoApoio] = field(default_factory=list)
    quantitativo: dict = field(default_factory=dict)
    cobrimentos: list[VerificacaoCobrimento] = field(default_factory=list)
    traspasses: list[em.ResultadoTraspasse] = field(default_factory=list)
    avisos: list[av.Aviso] = field(default_factory=list)
    #: Lajes treliçadas, alveolares e nervuradas atribuídas na planta (R09).
    #: ``lajes`` continua só com as maciças -- é o que a compatibilização, a
    #: armação e o desenho de barras esperam.
    especiais: list[atr.ResultadoEspecial] = field(default_factory=list)
    #: Análise por elementos finitos de placa e Wood-Armer (R10), quando o
    #: método dos esforços é ``"mef"``; ``None`` com as linhas de ruptura.
    mef: "mef.ResultadoMEF | None" = None
    #: Armadura superior de canto das linhas de ruptura (R11, ``cantos.py``)
    #: -- vazia com o ``mef``, que tem os cantos dele.
    cantos: list[cnt.CantoCharneira] = field(default_factory=list)

    # -- consulta -----------------------------------------------------------
    def resultado(self, nome: str) -> ResultadoLaje | None:
        for r in self.lajes:
            if r.nome == nome:
                return r
        return None

    def especial_da_laje(self, nome: str) -> atr.ResultadoEspecial | None:
        """O sistema (faixa, painel) que calculou a laje da planta."""
        for e in self.especiais:
            if nome in e.lajes:
                return e
        return None

    @property
    def todas_posicoes(self) -> list[det.Posicao]:
        saida: list[det.Posicao] = []
        for r in self.lajes:
            saida.extend(r.posicoes)
        saida.extend(self.posicoes_continuidade)
        return sorted(saida, key=lambda p: p.numero)

    @property
    def erros(self) -> list[av.Aviso]:
        return [a for a in self.todos_avisos if a.erro]

    @property
    def todos_avisos(self) -> list[av.Aviso]:
        saida = list(self.avisos)
        for r in self.lajes:
            saida.extend(r.avisos)
        for e in self.especiais:
            saida.extend(e.avisos)
        return saida

    @property
    def area_total(self) -> float:
        """Área das lajes maciças pelos vãos efetivos, m²."""
        return sum(r.laje.area for r in self.lajes)

    @property
    def area_especiais(self) -> float:
        """Área em planta das lajes especiais (vãos livres), m²."""
        return sum(e.area for e in self.especiais)

    def contorno(self) -> tuple[float, float, float, float]:
        """Retângulo que contém o pavimento, em metros."""
        if not self.pavimento.lajes:
            return (0.0, 0.0, 1.0, 1.0)
        cantos = [x.retangulo for x in self.pavimento.lajes]
        return (min(c[0] for c in cantos), min(c[1] for c in cantos),
                max(c[2] for c in cantos), max(c[3] for c in cantos))


# ---------------------------------------------------------------------------
# Flexão de uma laje
# ---------------------------------------------------------------------------

def _negativa_convergente(md: float, alturas: tuple[float, ...], amb,
                          concreto, aco, cfg, rotulo: str,
                          phi_imposta: float | None = None,
                          maximo: int = 4, limite_xd: float | None = None
                          ) -> tuple[fx.ResultadoFlexao, float,
                                    det.Escolha | None, bool]:
    """Dimensiona uma negativa iterando bitola × cobrimento até fechar.

    O cobrimento da face superior cai a 15 mm quando ela é revestida
    (7.4.7.5), mas nunca menos que a bitola da barra -- e a bitola só sai
    **depois** que a armadura foi calculada, que depende de ``d``, que
    depende do cobrimento: um ciclo. A primeira volta assume o cobrimento da
    bitola mínima da face (ou da imposta, se houver); a cada volta seguinte,
    refaz com o cobrimento que a bitola escolhida na volta anterior de fato
    exige, e para quando a bitola parar de mudar. Como o cobrimento só sobe
    acima de Ø15 mm -- incomum na laje, mas possível nas mais espessas --, a
    maioria das armaduras converge na primeira volta, sem custo extra.

    ``alturas`` é uma altura só (bordo isolado) ou as duas de uma borda
    comum, caso em que ``d`` é o menor dos dois, com o menor ``h`` (§3.3).
    Devolve ``(resultado da flexão, d final, escolha final ou None, se
    convergiu)``.
    """
    h_governa = min(alturas)
    phi = phi_imposta if phi_imposta else cfg.bitola_minima_negativa
    f = None
    d = 0.0
    for _ in range(maximo):
        c_sup = amb.cobrimento_superior(phi)
        d = min(fx.altura_util(h, c_sup, "superior") for h in alturas)
        f = fx.dimensionar_secao(md, h_governa, d, c_sup, concreto, aco,
                                 "negativa", rotulo, limite_xd)
        if f.erro or f.As <= 0.0:
            return f, d, None, True
        candidata = det.escolher(f.As, h_governa, "superior", cfg, True,
                                 phi_imposta)
        if candidata.erro or abs(candidata.phi - phi) < 1e-9:
            return f, d, candidata, True
        phi = candidata.phi
    return f, d, candidata, False


def _arredondar_momento_apoio(md: float, v_d: float, t_cm: float,
                              cfg: Config) -> tuple[float, float, bool]:
    """Reduz o momento negativo pelo arredondamento do item 14.6.3.

    ``ΔM = R·t/8`` -- R é a reação de cálculo (kN/m) do bordo e t a largura
    do apoio (cm). É o resultado clássico de tratar a reação como uma
    pressão distribuída ao longo do apoio, e não concentrada no eixo
    teórico: o momento no eixo superestima o que a seção realmente vê.

    A redução nunca passa de metade do momento original -- um apoio largo
    o bastante para "comer" mais que isso não é um caso de arredondar o
    diagrama, é um caso de repensar a razão entre vão e apoio, e o programa
    prefere avisar a entregar uma armadura otimista demais.

    Devolve ``(momento reduzido, ΔM aplicado, se o limite de metade entrou
    em jogo)``.
    """
    if not cfg.arredondar_momento_apoio or v_d <= 0.0 or t_cm <= 0.0 \
            or md <= 0.0:
        return md, 0.0, False
    delta = v_d * (t_cm / 100.0) / 8.0
    limite = md * 0.5
    capado = delta > limite
    delta_aplicado = min(delta, limite)
    return md - delta_aplicado, delta_aplicado, capado


def _dimensionar_flexao(rl: ResultadoLaje, pav: Pavimento,
                        comp: compat.Compatibilizacao
                        ) -> list[VerificacaoCobrimento]:
    """Roda a flexão de todas as seções da laje.

    Devolve as provas de cobrimento das negativas isoladas -- as de borda
    comum saem depois, em :func:`_detalhar_continuidades`, porque só ali a
    armadura única das duas lajes é de fato decidida.
    """
    laje, esf, cfg = rl.laje, rl.esforcos, pav.config
    concreto, aco, amb = pav.concreto, pav.aco, pav.ambiente
    c_inf = amb.cobrimento_nominal
    em_cruz = esf.classificacao.em_cruz
    cobrimentos: list[VerificacaoCobrimento] = []
    #: momentos vindos da análise elástica: o limite de x/d é o de quem
    #: redistribui delta (ou não redistribui), e não o rígido-plástico
    el = (concreto.x_sobre_d_limite_redistribuido(esf.delta_mef)
          if esf.metodo == "mef" else None)

    # -- armaduras positivas -------------------------------------------------
    # a face inferior usa o cobrimento nominal da Tabela 7.2, que não depende
    # da bitola (só a face revestida tem essa dependência -- 7.4.7.5), então
    # não há ciclo a fechar aqui
    if em_cruz:
        for direcao, md in (("a", esf.ma), ("b", esf.mb)):
            d = fx.altura_util(laje.h, c_inf, "inferior",
                               direcao_inferior=(direcao == "a"))
            rl.flexoes.append(fx.dimensionar_secao(
                md, laje.h, d, c_inf, concreto, aco, "positiva em cruz",
                f"vão {direcao}", el))
    else:
        direcao = esf.classificacao.direcao
        d = fx.altura_util(laje.h, c_inf, "inferior", True)
        # o balanço não tem momento de vão -- não há o que calcular na face
        # inferior --, mas um balanço comprido não pode ficar com a face de
        # baixo sem nenhuma armadura na direção do vão: acima de 3 m ela leva
        # o mínimo construtivo mesmo assim, como armadura de pele (regra
        # prática de projeto, não item literal da NBR)
        vao_balanco = laje.a if direcao == "a" else laje.b
        pele_balanco = esf.classificacao.balanco and vao_balanco > 3.0
        for faixa in esf.faixas:
            if faixa.m_vao <= 0.0 and esf.classificacao.balanco \
                    and not pele_balanco:
                continue
            rl.flexoes.append(fx.dimensionar_secao(
                faixa.m_vao, laje.h, d, c_inf, concreto, aco,
                "positiva principal", f"vão {direcao} — {faixa.nome}"))

    # -- armaduras negativas -------------------------------------------------
    for bordo in (1, 2, 3, 4):
        b = laje.bordos[bordo - 1]
        if b.vinculo != "engastado":
            continue
        md = comp.momento_do_bordo(laje.nome, bordo)
        origem = "compatibilizado" if md is not None else "isolado"
        if md is None:
            md = esf.m_neg.get(bordo, 0.0)
        borda = comp.borda_de(laje.nome, bordo)
        rotulo = f"bordo {bordo} ({origem})"
        if borda is not None and borda.d_adotado > 0.0:
            # a armadura de fato sai de _detalhar_continuidades; esta
            # entrada só acompanha o cálculo isolado da laje na aba de
            # flexão, então o cobrimento genérico da face basta
            c_sup = amb.cobrimento_superior(cfg.bitola_minima_negativa)
            d = borda.d_adotado           # a menor das duas alturas úteis
            rl.flexoes.append(fx.dimensionar_secao(
                md, laje.h, d, c_sup, concreto, aco, "negativa", rotulo,
                el))
        else:
            # engaste em elemento rígido: esta É a armadura detalhada, e o
            # cobrimento tem de fechar com a bitola que sai da escolha
            phi_imp = cfg.bitolas_impostas.get(f"{laje.nome}|bordo {bordo}")
            r = rl.reacoes.do_bordo(bordo) if rl.reacoes else None
            md_original = md
            if r is not None:
                md, delta, capado = _arredondar_momento_apoio(
                    md, r.v_d, b.t, cfg)
                if delta > 0.0:
                    texto = (f"{laje.nome}, {rotulo}: momento arredondado "
                             f"de {md_original:.2f} para {md:.2f} kN·m/m "
                             f"pelo item 14.6.3 (ΔM = {r.v_d:.1f} × "
                             f"{b.t / 100.0:.2f} / 8 = {delta:.2f})")
                    if capado:
                        texto += " -- limitado à metade do momento original"
                    rl.avisos.append(av.Aviso(texto, av.CONSTRUTIVO,
                                              laje.nome))
            f, _, escolha_final, convergiu = _negativa_convergente(
                md, (laje.h,), amb, concreto, aco, cfg, rotulo, phi_imp,
                limite_xd=el)
            rl.flexoes.append(f)
            if not convergiu:
                rl.avisos.append(av.Aviso(
                    f"{laje.nome}, {rotulo}: a bitola e o cobrimento da "
                    f"face superior não convergiram em algumas voltas; "
                    f"ficou em Ø{f.As:.2f} cm²/m com c' = {f.cobrimento:g} "
                    f"cm -- confira a bitola adotada.", av.CONSTRUTIVO,
                    laje.nome))
            if escolha_final is not None and not escolha_final.erro:
                cobrimentos.append(VerificacaoCobrimento(
                    rotulo=f"{laje.nome}, {rotulo}",
                    cobrimento_usado=f.cobrimento,
                    bitola_adotada=escolha_final.phi,
                    cobrimento_exigido=amb.cobrimento_superior(
                        escolha_final.phi),
                    convergiu=convergiu))
    return cobrimentos


def _conferir_fissuracao(rl: ResultadoLaje, laje: Laje, concreto, aco, amb,
                         escolha: det.Escolha,
                         f: fx.ResultadoFlexao | None, m_ser: float,
                         rotulo: str) -> None:
    """Abertura de fissuras (17.3.3.2) da armadura que acabou de ser escolhida.

    Usa a armadura **efetiva** -- a que de fato entra, não a calculada -- e o
    momento de serviço (quase permanente): é essa dupla que decide se a peça
    fissura no dia a dia, não o par do ELU. O limite vem da Tabela 13.4, pela
    classe de agressividade do ambiente, e não é fixo em 0,3 mm.
    """
    if escolha.erro or f is None:
        return
    res = els_mod.verificar_fissuracao(
        f"{laje.nome}, {rotulo}", m_ser, escolha.As_efetiva, escolha.phi,
        f.d, laje.h, concreto, aco, amb.wk_limite)
    rl.fissuracoes.append(res)
    if not res.atende:
        rl.avisos.append(av.classificar(
            f"{res.rotulo}: abertura de fissura wk = {res.wk:.3f} mm passa "
            f"do limite de {res.wk_limite:.3f} mm (Tabela 13.4, CAA "
            f"{amb.caa} — item 17.3.3.2).", laje.nome))


# ---------------------------------------------------------------------------
# Detalhamento de uma laje
# ---------------------------------------------------------------------------

def _detalhar(rl: ResultadoLaje, pav: Pavimento,
              comp: compat.Compatibilizacao, contador: list[int]) -> None:
    """Escolhe as armaduras e monta as posições da laje."""
    laje, esf, cfg = rl.laje, rl.esforcos, pav.config
    concreto, aco, amb = pav.concreto, pav.aco, pav.ambiente
    em_cruz = esf.classificacao.em_cruz

    def proximo() -> int:
        contador[0] += 1
        return contador[0]

    def imposta(chave: str) -> float | None:
        return cfg.bitolas_impostas.get(f"{laje.nome}|{chave}")

    # As queixas sobre a faixa de bitola são acumuladas por **diagnóstico**, e
    # não emitidas armadura por armadura: uma faixa que não cabe não cabe em
    # nenhuma das armaduras da laje, e repetir a mesma frase seis vezes
    # transforma a aba de avisos em ruído. O flush no fim do detalhamento
    # emite cada diagnóstico uma vez, listando as armaduras que ele atingiu.
    queixas: dict[tuple[str, str], list[str]] = {}

    def registrar(escolha: det.Escolha, chave: str) -> None:
        rl.escolhas[chave] = escolha
        onde = f"{laje.nome}, {chave}"
        if escolha.erro:
            rl.avisos.append(av.classificar(f"{onde}: {escolha.erro}",
                                            laje.nome))
            return

        # A faixa de bitola desejada é preferência do projetista, não limite
        # da norma: quando ela não cabe ou sai caro, o aviso é construtivo --
        # a laje está dimensionada e verificada, o que está em questão é a
        # escolha da bitola.
        if escolha.faixa_ignorada:
            queixas.setdefault(("faixa", escolha.faixa_ignorada.split(";")[0]),
                               []).append(f"{chave} ({escolha.texto()})")
        elif escolha.extremos:
            queixas.setdefault(("extremo", "; ".join(escolha.extremos)),
                               []).append(
                f"{chave} ({escolha.texto()} com "
                f"{escolha.sobra * 100:.0f} % de sobra, em vez de "
                f"{escolha.livre})")

        if not escolha.recomendada:
            face = ("superior" if "bordo" in chave or "contorno" in chave
                    else "inferior")
            minimo, maximo = det.FAIXA_RECOMENDADA[face]
            queixas.setdefault(
                ("espacamento",
                 f"espaçamento fora da faixa recomendada de {minimo:g} a "
                 f"{maximo:g} cm do §1.8 para a face {face} — é preferência "
                 f"construtiva, não limite normativo"),
                []).append(f"{chave} (c/{escolha.espacamento:g})")

    def emitir_queixas() -> None:
        for (tipo, diagnostico), armaduras in queixas.items():
            lista = "; ".join(armaduras)
            if tipo == "faixa":
                texto = (f"{laje.nome}: {diagnostico}; valeram os limites da "
                         f"norma em {lista}.")
            elif tipo == "extremo":
                faixa = next((e.texto_faixa() for e in rl.escolhas.values()
                              if e.faixa_desejada), "")
                texto = (f"{laje.nome}: a faixa de bitola desejada "
                         f"({faixa}) leva a um extremo — {diagnostico}. "
                         f"Em {lista}.")
            else:
                texto = f"{laje.nome}: {diagnostico}. Em {lista}."
            rl.avisos.append(av.Aviso(texto, av.CONSTRUTIVO, laje.nome))

    # -- positivas -----------------------------------------------------------
    if em_cruz:
        for direcao in ("a", "b"):
            f = rl.flexao_de(f"vão {direcao}")
            if f is None:
                continue
            escolha = det.escolher(f.As, laje.h, "inferior", cfg, True,
                                   imposta(f"vão {direcao}"))
            registrar(escolha, f"vão {direcao}")
            if escolha.erro:
                continue
            m_ser = esf.ma_ser if direcao == "a" else esf.mb_ser
            _conferir_fissuracao(rl, laje, concreto, aco, amb, escolha, f,
                                 m_ser, f"vão {direcao}")
            ancoragens = det.ancorar_positiva(
                laje, direcao, escolha, f.As_calculada, concreto, aco, amb)
            rl.ancoragens.extend(ancoragens.values())
            for a in ancoragens.values():
                if not a.atende:
                    rl.avisos.append(av.classificar(
                        f"{a.rotulo}: {a.observacao}", laje.nome))
            rl.posicoes.append(det.posicoes_positivas(
                laje, direcao, escolha, proximo(), amb, ancoragens))
    else:
        direcao = esf.classificacao.direcao
        _, (f0, f1) = det._eixo_e_intervalos(laje, direcao)
        restante = f1 - f0
        principais: list[tuple[det.Escolha, fx.ResultadoFlexao,
                               esf_mod.Faixa]] = []
        for faixa in esf.faixas:
            f = rl.flexao_de(f"vão {direcao} — {faixa.nome}")
            if f is None:
                continue
            escolha = det.escolher(f.As, laje.h, "inferior", cfg, True,
                                   imposta(f"vão {direcao} — {faixa.nome}"))
            registrar(escolha, f"vão {direcao} — {faixa.nome}")
            if escolha.erro:
                continue
            principais.append((escolha, f, faixa))
            if faixa.nome != "sem parede":
                restante -= faixa.bw_vao

        for escolha, f, faixa in principais:
            _conferir_fissuracao(rl, laje, concreto, aco, amb, escolha, f,
                                 faixa.m_vao_ser,
                                 f"vão {direcao} — {faixa.nome}")
            ancoragens = det.ancorar_positiva(
                laje, direcao, escolha, f.As_calculada, concreto, aco, amb)
            rl.ancoragens.extend(ancoragens.values())
            for a in ancoragens.values():
                if not a.atende:
                    rl.avisos.append(av.classificar(
                        f"{a.rotulo}: {a.observacao}", laje.nome))
            pos = det.posicoes_positivas(laje, direcao, escolha, proximo(),
                                         amb, ancoragens)
            # a faixa da parede ocupa a largura bw dela; a faixa sem parede
            # cobre o que resta da laje (§2.1)
            if faixa.nome == "sem parede":
                largura = max(restante, 0.0)
                if esf.classificacao.balanco:
                    vao_cm = (laje.a if direcao == "a" else laje.b) * 100.0
                    pos.observacoes.append(
                        f"armadura de pele inferior: o balanço tem "
                        f"{vao_cm:.0f} cm de vão livre, mais de 3 m, e a "
                        f"face inferior não pode ficar sem nenhuma armadura "
                        f"na direção do vão -- mínimo construtivo, sem "
                        f"momento de vão calculado (o balanço não tem "
                        f"momento positivo)")
                else:
                    pos.observacoes.append(
                        f"cobre os {largura:.0f} cm de laje fora das faixas "
                        f"de parede")
            else:
                largura = faixa.bw_vao
                pos.observacoes.append(
                    f"reforço na faixa de bw = {largura:.0f} cm sob a "
                    f"parede ({faixa.descricao})")
            pos.faixa_fim = pos.faixa_inicio + max(largura, 0.0)
            pos.quantidade = det._quantidade(max(largura, 0.0),
                                             escolha.espacamento)
            rl.posicoes.append(pos)

        # -- distribuição ---------------------------------------------------
        # Vale em toda laje armada em uma direção, balanço incluído: o item
        # 20.1 pede armadura transversal de pelo menos 20 % da principal, e o
        # balanço é justamente onde a retração e a variação térmica mais
        # aparecem, porque ele tem borda livre.
        principal = max((e.As_efetiva for e, _, _ in principais), default=0.0)
        faixa_parede = next((fa for fa in esf.faixas
                             if fa.nome != "sem parede"), None)
        As_dist, motivo = fx.armadura_distribuicao(
            principal, concreto, laje.h,
            faixa_parede.bw_vao if faixa_parede else 100.0,
            faixa_parede.b_difusao if faixa_parede else 0.0)
        escolha = det.escolher(As_dist, laje.h, "inferior", cfg, False,
                               imposta("distribuição"))
        registrar(escolha, "distribuição")
        if not escolha.erro:
            rl.posicoes.append(det.posicao_distribuicao(
                laje, direcao, escolha, proximo(), amb, motivo))

    # -- negativas de bordo sem continuidade (contorno) ---------------------
    for bordo in (1, 2, 3, 4):
        b = laje.bordos[bordo - 1]
        if b.vinculo != "apoiado":
            continue
        As, extensao = fx.armadura_contorno(concreto, laje.h, laje.a_ef)
        escolha = det.escolher(As, laje.h, "superior", cfg, True,
                               imposta(f"contorno do bordo {bordo}"))
        registrar(escolha, f"contorno do bordo {bordo}")
        if escolha.erro:
            continue
        ancoragem = det.ancorar_negativa(laje, bordo, escolha, As, concreto,
                                         aco, amb)
        rl.ancoragens.append(ancoragem)
        if not ancoragem.atende:
            rl.avisos.append(av.classificar(
                f"{ancoragem.rotulo}: {ancoragem.observacao}", laje.nome))
        rl.posicoes.append(det.posicao_negativa(
            laje, bordo, escolha, proximo(), extensao, False,
            f"0,67 rho_mín com piso de 1,0 cm²/m, estendida "
            f"{extensao:.0f} cm (um quinto do vão menor) — §3.3",
            ancoragem=ancoragem))

    # -- negativas de bordo engastado sem laje vizinha ----------------------
    for bordo in (1, 2, 3, 4):
        b = laje.bordos[bordo - 1]
        if b.vinculo != "engastado":
            continue
        if comp.borda_de(laje.nome, bordo) is not None:
            continue                    # sai como posição de continuidade
        f = rl.flexao_de(f"bordo {bordo} (isolado)") or \
            rl.flexao_de(f"bordo {bordo} (compatibilizado)")
        if f is None:
            continue
        escolha = det.escolher(f.As, laje.h, "superior", cfg, True,
                               imposta(f"bordo {bordo}"))
        registrar(escolha, f"bordo {bordo}")
        if escolha.erro:
            continue
        _conferir_fissuracao(rl, laje, concreto, aco, amb, escolha, f,
                             esf.m_neg_ser.get(bordo, 0.0), f"bordo {bordo}")
        ancoragem = det.ancorar_negativa(laje, bordo, escolha,
                                         f.As_calculada, concreto, aco, amb)
        rl.ancoragens.append(ancoragem)
        if not ancoragem.atende:
            rl.avisos.append(av.classificar(
                f"{ancoragem.rotulo}: {ancoragem.observacao}", laje.nome))
        if esf.classificacao.balanco:
            # a negativa do engaste é a única armadura do balanço -- se
            # parasse onde o momento nominalmente decai, o resto do
            # balanço, entre ali e a ponta livre, ficaria sem armadura
            # nenhuma. Ela vai até a extremidade, menos o cobrimento da
            # própria borda livre (a mesma regra da positiva num bordo
            # livre -- ver _avanco_desenho).
            direcao_bordo = "b" if bordo in BORDOS_DA_DIRECAO["b"] else "a"
            vao_bordo = (laje.a if direcao_bordo == "a" else laje.b) * 100.0
            extensao = vao_bordo - amb.cobrimento_nominal
            motivo = "até a extremidade livre do balanço"
        else:
            extensao = 0.25 * laje.a_ef * 100.0
            motivo = "um quarto do vão menor"
        rl.posicoes.append(det.posicao_negativa(
            laje, bordo, escolha, proximo(), extensao, False,
            f"engaste em elemento rígido, estendida {extensao:.0f} cm "
            f"({motivo})", ancoragem=ancoragem, tipo="negativa"))

    emitir_queixas()


# ---------------------------------------------------------------------------
# Armadura única das bordas comuns
# ---------------------------------------------------------------------------

def _limite_da_borda(pav: Pavimento, ea: Esforcos, eb: Esforcos
                     ) -> float | None:
    """x/d da armadura única de uma borda comum: o da análise elástica só
    quando os dois lados vêm dela; senão o rígido-plástico, que é o mais
    severo."""
    if ea.metodo == "mef" and eb.metodo == "mef":
        return pav.concreto.x_sobre_d_limite_redistribuido(
            min(ea.delta_mef, eb.delta_mef))
    return None


def _detalhar_continuidades(res: ResultadoPavimento, pav: Pavimento,
                            comp: compat.Compatibilizacao,
                            contador: list[int]) -> None:
    """Uma armadura por borda comum, para o maior momento e a menor d (§3.3)."""
    cfg = pav.config
    # como no detalhamento das lajes, as queixas sobre a faixa de bitola são
    # agrupadas por diagnóstico e emitidas uma vez ao fim
    queixas: dict[tuple, list[str]] = {}
    for borda in comp.bordas:
        la, lb = pav.laje(borda.laje_a), pav.laje(borda.laje_b)
        rla, rlb = res.resultado(borda.laje_a), res.resultado(borda.laje_b)
        if la is None or lb is None or rla is None or rlb is None:
            continue
        # o cobrimento da negativa depende da bitola que a escolha devolve,
        # e a escolha depende da armadura, que depende do cobrimento: o
        # mesmo ciclo do bordo isolado, fechado da mesma forma
        phi_imp = cfg.bitolas_impostas.get(f"borda comum|{borda.rotulo}")
        md = borda.m_adotado
        ra = rla.reacoes.do_bordo(borda.bordo_a) if rla.reacoes else None
        rb = rlb.reacoes.do_bordo(borda.bordo_b) if rlb.reacoes else None
        if ra is not None and rb is not None:
            # a viga da borda comum recebe as duas lajes -- a reação que
            # arredonda o diagrama é a soma das duas, não a de um lado só
            t_viga = la.bordos[borda.bordo_a - 1].t
            md, delta, capado = _arredondar_momento_apoio(
                md, ra.v_d + rb.v_d, t_viga, cfg)
            if delta > 0.0:
                texto = (f"borda comum {borda.rotulo}: momento arredondado "
                         f"de {borda.m_adotado:.2f} para {md:.2f} kN·m/m "
                         f"pelo item 14.6.3 (ΔM = "
                         f"{(ra.v_d + rb.v_d):.1f} × {t_viga / 100.0:.2f} "
                         f"/ 8 = {delta:.2f})")
                if capado:
                    texto += " -- limitado à metade do momento original"
                res.avisos.append(av.Aviso(texto, av.CONSTRUTIVO))
        f, d_final, escolha, convergiu = _negativa_convergente(
            md, (la.h, lb.h), pav.ambiente, pav.concreto,
            pav.aco, cfg, f"borda comum {borda.rotulo}", phi_imp,
            limite_xd=_limite_da_borda(pav, rla.esforcos, rlb.esforcos))
        borda.d_adotado = d_final
        if escolha is None:
            escolha = det.escolher(f.As, min(la.h, lb.h), "superior", cfg,
                                   True, phi_imp)
        if not convergiu:
            res.avisos.append(av.Aviso(
                f"borda comum {borda.rotulo}: a bitola e o cobrimento da "
                f"face superior não convergiram em algumas voltas; ficou em "
                f"c' = {f.cobrimento:g} cm -- confira a bitola adotada.",
                av.CONSTRUTIVO))
        if escolha.erro:
            res.avisos.append(av.classificar(
                f"borda comum {borda.rotulo}: {escolha.erro}"))
            continue
        if f.erro:
            res.avisos.append(av.classificar(
                f"borda comum {borda.rotulo}: {f.erro}"))
        else:
            res.cobrimentos.append(VerificacaoCobrimento(
                rotulo=f"borda comum {borda.rotulo}",
                cobrimento_usado=f.cobrimento, bitola_adotada=escolha.phi,
                cobrimento_exigido=pav.ambiente.cobrimento_superior(
                    escolha.phi),
                convergiu=convergiu))
            # o momento de serviço não é compatibilizado como o do ELU (só
            # o item 14.7.6.2 pede isso); a fissuração usa o maior dos dois
            # lados, a favor da segurança, sobre a mesma armadura instalada
            m_neg_ser = max(rla.esforcos.m_neg_ser.get(borda.bordo_a, 0.0),
                            rlb.esforcos.m_neg_ser.get(borda.bordo_b, 0.0))
            fis = els_mod.verificar_fissuracao(
                f"borda comum {borda.rotulo}", m_neg_ser,
                escolha.As_efetiva, escolha.phi, d_final, min(la.h, lb.h),
                pav.concreto, pav.aco, pav.ambiente.wk_limite)
            rla.fissuracoes.append(fis)
            rlb.fissuracoes.append(fis)
            if not fis.atende:
                res.avisos.append(av.classificar(
                    f"{fis.rotulo}: abertura de fissura wk = {fis.wk:.3f} "
                    f"mm passa do limite de {fis.wk_limite:.3f} mm (Tabela "
                    f"13.4, CAA {pav.ambiente.caa} — item 17.3.3.2)."))
        if escolha.faixa_ignorada:
            queixas.setdefault(
                ("faixa", escolha.faixa_ignorada.split(";")[0],
                 escolha.texto_faixa()),
                []).append(f"{borda.rotulo} ({escolha.texto()})")
        elif escolha.extremos:
            queixas.setdefault(
                ("extremo", "; ".join(escolha.extremos),
                 escolha.texto_faixa()),
                []).append(f"{borda.rotulo} ({escolha.texto()} com "
                           f"{escolha.sobra * 100:.0f} % de sobra, em vez de "
                           f"{escolha.livre})")

        contador[0] += 1
        rotulo_momento = (f"maior dos dois momentos ({borda.m_adotado:.2f} "
                          f"kN·m/m)")
        if md != borda.m_adotado:
            rotulo_momento += (f", arredondado para {md:.2f} kN·m/m "
                               f"(14.6.3)")
        ponta_gancho = det.ponta_gancho_construtiva(
            min(la.h, lb.h), escolha.phi, pav.ambiente)
        pos = det.posicao_negativa(
            la, borda.bordo_a, escolha, contador[0], borda.extensao, True,
            f"armadura única de continuidade: {rotulo_momento} e menor "
            f"altura útil ({borda.d_adotado:.1f} cm), estendida "
            f"{borda.extensao:.0f} cm para cada lado do eixo (§3.3)",
            ponta_gancho_continuidade=ponta_gancho)
        pos.laje = f"{borda.laje_a} / {borda.laje_b}"
        # a faixa é a sobreposição real das duas bordas
        seg_a = la.segmento_do_bordo(borda.bordo_a)
        seg_b = lb.segmento_do_bordo(borda.bordo_b)
        vertical = abs(seg_a[2] - seg_a[0]) < 1e-6
        if vertical:
            ini = max(min(seg_a[1], seg_a[3]), min(seg_b[1], seg_b[3]))
            fim = min(max(seg_a[1], seg_a[3]), max(seg_b[1], seg_b[3]))
        else:
            ini = max(min(seg_a[0], seg_a[2]), min(seg_b[0], seg_b[2]))
            fim = min(max(seg_a[0], seg_a[2]), max(seg_b[0], seg_b[2]))
        pos.faixa_inicio, pos.faixa_fim = ini * 100.0, fim * 100.0
        pos.quantidade = det._quantidade(pos.faixa_fim - pos.faixa_inicio,
                                         escolha.espacamento)
        res.posicoes_continuidade.append(pos)
        rla.escolhas[f"borda comum bordo {borda.bordo_a}"] = escolha
        rlb.escolhas[f"borda comum bordo {borda.bordo_b}"] = escolha
        rla.flexoes.append(f)

    for (tipo, diagnostico, faixa), bordas in queixas.items():
        lista = "; ".join(bordas)
        if tipo == "faixa":
            texto = (f"Armaduras de continuidade: {diagnostico}; valeram os "
                     f"limites da norma em {lista}.")
        else:
            texto = (f"Armaduras de continuidade: a faixa de bitola desejada "
                     f"({faixa}) leva a um extremo — {diagnostico}. "
                     f"Em {lista}.")
        res.avisos.append(av.Aviso(texto, av.CONSTRUTIVO))


# ---------------------------------------------------------------------------
# Cortante
# ---------------------------------------------------------------------------

def _verificar_cortante(rl: ResultadoLaje, pav: Pavimento) -> None:
    """Item 19.4 em cada bordo vinculado da laje."""
    laje, esf, cfg = rl.laje, rl.esforcos, pav.config
    if not cfg.verificar_cisalhamento or rl.reacoes is None:
        return
    c_inf = pav.ambiente.cobrimento_nominal
    em_cruz = esf.classificacao.em_cruz

    for r in rl.reacoes.bordos:
        if r.vinculo == "livre":
            continue
        # a direção que o bordo apoia é a que traz a armadura positiva ao
        # apoio, e é o As1 dela que entra no VRd1
        direcao = "b" if r.bordo in BORDOS_DA_DIRECAO["b"] else "a"
        if em_cruz:
            escolha = rl.escolhas.get(f"vão {direcao}")
        else:
            escolha = next((e for chave, e in rl.escolhas.items()
                            if chave.startswith(f"vão {direcao}")), None)
        As1 = escolha.As_efetiva if escolha is not None else 0.0
        d = fx.altura_util(laje.h, c_inf, "inferior",
                           direcao_inferior=(direcao == "a"))
        res = cis.verificar(
            f"{laje.nome}, bordo {r.bordo}", r.v_d, laje.h, d, As1,
            pav.concreto, pav.aco, p_d=esf.p_d,
            t_apoio=laje.bordos[r.bordo - 1].t, reduzir=not em_cruz)
        rl.cortantes.append(res)
        if res.erro:
            rl.avisos.append(av.classificar(
                f"{laje.nome}, bordo {r.bordo}: {res.erro}", laje.nome))
        elif res.precisa_armadura:
            rl.avisos.append(av.classificar(
                f"{laje.nome}, bordo {r.bordo}: VSd = {res.v_sd:.1f} kN/m "
                f"passa do VRd1 = {res.v_rd1:.1f} kN/m (19.4.1); a laje "
                f"precisa de armadura transversal de "
                f"{res.asw_por_m2:.2f} cm²/m por metro, com fywd limitado a "
                f"{res.fywd:.0f} MPa pela espessura (19.4.2).", laje.nome))


# ---------------------------------------------------------------------------
# Reações consolidadas
# ---------------------------------------------------------------------------

def _consolidar_apoios(res: ResultadoPavimento, pav: Pavimento) -> None:
    """Junta as reações num segmento por borda, somando os dois lados.

    Entram as maciças e as lajes especiais (R09). Duas maciças dividem a
    viga pela lista de continuidades; quando uma das lajes é especial a
    vizinha vem da posição na planta (``atribuicao.vizinhas_com_especial``).
    Os bordos de uma laje especial paralelos ao vão não carregam nada e não
    geram segmento.
    """
    vistos: set[frozenset] = set()
    fontes: list[tuple] = []
    for rl in res.lajes:
        if rl.reacoes is not None:
            fontes.append((rl.laje, rl.reacoes))
    for e in res.especiais:
        for nome, rr in e.reacoes.items():
            laje = pav.laje(nome)
            if laje is not None:
                fontes.append((laje, rr))
    por_nome = {laje.nome: rr for laje, rr in fontes}
    mistas = atr.vizinhas_com_especial(pav)

    for laje, reacoes in fontes:
        for r in reacoes.bordos:
            if r.vinculo == "livre":
                continue
            if laje.especial and r.v_k <= 1e-12 and r.v_d <= 1e-12:
                continue
            chave = frozenset({(laje.nome, r.bordo)})
            viz = pav.vizinha_de(laje.nome, r.bordo)
            outro = (viz[0].nome, viz[1]) if viz is not None \
                else mistas.get((laje.nome, r.bordo))
            if outro is not None:
                chave = frozenset({(laje.nome, r.bordo), outro})
            if chave in vistos:
                continue
            vistos.add(chave)
            x0, y0, x1, y1 = laje.segmento_do_bordo(r.bordo)
            seg = SegmentoApoio(
                rotulo=f"{laje.nome} bordo {r.bordo}", x0=x0, y0=y0, x1=x1,
                y1=y1, comprimento=r.comprimento, lajes=[laje.nome],
                v_g=r.v_g, v_q=r.v_q, v_k=r.v_k, v_d=r.v_d,
                continuidade=outro is not None)
            if outro is not None:
                rr_o = por_nome.get(outro[0])
                ro = rr_o.do_bordo(outro[1]) if rr_o is not None else None
                if ro is not None:
                    seg.rotulo = (f"{laje.nome} bordo {r.bordo} + "
                                  f"{outro[0]} bordo {outro[1]}")
                    seg.lajes.append(outro[0])
                    seg.v_g += ro.v_g
                    seg.v_q += ro.v_q
                    seg.v_k += ro.v_k
                    seg.v_d += ro.v_d
            res.apoios.append(seg)
    res.apoios.sort(key=lambda s: s.rotulo)


# ---------------------------------------------------------------------------
# Emenda por traspasse
# ---------------------------------------------------------------------------

def _conferir_traspasse(res: ResultadoPavimento, pav: Pavimento) -> None:
    """Emenda por traspasse (9.5.2) das posições mais longas que a vara.

    Roda sobre :attr:`ResultadoPavimento.todas_posicoes`, depois que a
    armadura das bordas comuns já saiu -- é ali que a barra mais comprida
    aparece, atravessando duas lajes em linha.
    """
    cfg = pav.config
    vara = cfg.comprimento_comercial_barra
    for pos in res.todas_posicoes:
        if pos.comprimento <= vara + 1e-6:
            continue
        r = em.verificar(f"{pos.laje}, N{pos.numero}", pos.phi,
                         pos.comprimento, vara,
                         pav.concreto, pav.aco)
        res.traspasses.append(r)
        # a posição carrega a emenda daqui para frente: é o desenho que
        # precisa saber onde ela cai, e a memória e o quantitativo que
        # precisam saber quanto de aço ela consome
        pos.emendas = r.numero_emendas
        pos.l0t = r.l0t
        pos.estacoes_emenda = [
            min(pos.inicio + k * vara, pos.fim)
            for k in range(1, r.numero_emendas + 1)]
        res.avisos.append(av.Aviso(
            f"{r.rotulo}: barra de {r.comprimento_barra / 100.0:.1f} m "
            f"passa da vara comercial de "
            f"{r.comprimento_comercial / 100.0:.0f} m -- precisa de "
            f"{r.numero_emendas} emenda(s) por traspasse de l0t = "
            f"{r.l0t:.0f} cm cada (9.5.2.3, alfa_0t = {r.alfa_0t:g} "
            f"supondo até 20 % das barras emendadas na mesma seção -- "
            f"escalone as emendas na prancha; se mais de 20 % ficarem na "
            f"mesma seção, recalcule com um alfa_0t maior, Tabela 9.4).",
            av.CONSTRUTIVO))


# ---------------------------------------------------------------------------
# Quantitativo
# ---------------------------------------------------------------------------

def _quantitativo(res: ResultadoPavimento, pav: Pavimento) -> None:
    """Aço (com o traspasse das emendas), concreto, forma e taxas.

    O aço aparece em dois números que não são o mesmo: ``massa_total`` é o
    que as barras medem no desenho, e ``massa_emendas`` é o aço a mais que
    o traspasse consome -- cada emenda de uma barra sobrepõe ``l0t`` de
    comprimento, e esse pedaço é comprado mesmo sem aparecer como barra
    nova na tabela de posições. Quem faz orçamento precisa dos dois somados
    (é o ``massa_com_perdas``, que ainda leva os 10 % de pontas); quem
    confere a prancha precisa do primeiro, que é o que ele mede com a
    escala na mão.
    """
    por_bitola: dict[float, dict] = {}
    massa_emendas = 0.0
    for p in res.todas_posicoes:
        d = por_bitola.setdefault(p.phi, {"comprimento": 0.0, "massa": 0.0,
                                          "posicoes": 0, "emendas": 0,
                                          "massa_emendas": 0.0})
        d["comprimento"] += p.comprimento_total
        d["massa"] += p.massa
        d["posicoes"] += 1
        if p.emendas:
            # o traspasse é por barra: cada uma das `quantidade` barras da
            # posição sobrepõe l0t em cada uma das suas emendas
            extra = (p.quantidade * p.emendas * p.l0t / 100.0
                     * mt.massa_linear(p.phi))
            d["emendas"] += p.quantidade * p.emendas
            d["massa_emendas"] += extra
            massa_emendas += extra

    formas = [rl.formas for rl in res.lajes if rl.formas is not None]
    volume = sum(r.laje.area * r.laje.h / 100.0 for r in res.lajes)
    massa = sum(d["massa"] for d in por_bitola.values())
    area = res.area_total
    res.quantitativo = {
        "por_bitola": dict(sorted(por_bitola.items())),
        "massa_total": massa,
        "massa_emendas": massa_emendas,
        "massa_com_perdas": (massa + massa_emendas) * 1.10,
        "volume_concreto": volume,
        "area_total": area,
        "taxa_por_m2": massa / area if area > 0 else 0.0,
        "taxa_por_m3": massa / volume if volume > 0 else 0.0,
        "peso_proprio_medio": (volume * pav.concreto.peso_especifico / area
                               if area > 0 else 0.0),
        **fm.total(formas),
    }
    # -- lajes especiais: o que a planta atribuiu a treliçada, alveolar e
    # nervurada soma ao pavimento sem tocar nos números da maciça
    linhas = []
    for e in res.especiais:
        linhas.append({
            "nome": e.nome, "tipo": e.rotulo_tipo, "tipo_chave": e.tipo,
            "perfil": e.perfil,
            "area": e.area, "aco_kg": e.aco_kg,
            "concreto_m3": e.concreto_m3, "premoldado_m3": e.premoldado_m3,
            "n_paineis": e.n_paineis, "atende": e.atende})
    massa_esp = sum(x["aco_kg"] for x in linhas)
    area_esp = sum(x["area"] for x in linhas)
    massa_canto = 0.0
    if res.mef is not None:
        massa_canto = sum(c.massa for lm in res.mef.lajes.values()
                          for c in lm.cantos if c.exige and not c.erro)
    massa_canto_ch = sum(c.massa for c in res.cantos if not c.erro)
    q = res.quantitativo
    q["massa_canto_mef"] = massa_canto
    q["massa_canto_charneiras"] = massa_canto_ch
    massa_canto += massa_canto_ch
    q["especiais"] = linhas
    q["massa_especiais"] = massa_esp
    q["area_especiais"] = area_esp
    q["concreto_especiais"] = sum(x["concreto_m3"] for x in linhas)
    q["premoldado_especiais"] = sum(x["premoldado_m3"] for x in linhas)
    q["massa_geral"] = massa + massa_esp + massa_canto
    q["area_geral"] = area + area_esp
    q["taxa_geral_por_m2"] = ((massa + massa_esp + massa_canto)
                              / (area + area_esp)
                              if area + area_esp > 0 else 0.0)


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------

def dimensionar(pav: Pavimento) -> ResultadoPavimento:
    """Calcula e detalha o pavimento inteiro."""
    cfg = pav.config
    res = ResultadoPavimento(pavimento=pav)

    for problema in pav.conferir():
        res.avisos.append(av.classificar(problema))
    atr.sincronizar_alturas(pav)
    macicas = pav.lajes_macicas

    # -- 2. pré-dimensionamento da espessura --------------------------------
    predim: dict[str, els_mod.Predimensionamento] = {}
    if cfg.predimensionar_espessura:
        for laje in macicas:
            predim[laje.nome] = els_mod.predimensionar(laje, pav.concreto, cfg)

    # -- 3. momentos das lajes isoladas -------------------------------------
    esforcos = {laje.nome: esf_mod.calcular(laje, cfg) for laje in macicas}

    # -- 3b. alternativa: elementos finitos de placa e Wood-Armer (R10) -----
    cfg_compat = cfg
    if cfg.metodo_esforcos == "mef" and macicas:
        try:
            res.mef = mef.aplicar(pav, esforcos, cfg)
        except Exception as erro:                        # noqa: BLE001
            res.mef = None
            res.avisos.append(av.Aviso(
                f"A análise por elementos finitos não pôde ser concluída "
                f"({erro}); ficaram as linhas de ruptura.", av.CONSTRUTIVO))
        else:
            mef.dimensionar_cantos(res.mef, pav)
            for texto in res.mef.avisos:
                res.avisos.append(av.classificar(texto))
            for lm in res.mef.lajes.values():
                for c in lm.cantos:
                    if c.erro:
                        res.avisos.append(av.classificar(
                            f"{c.rotulo}: a armadura superior de canto não "
                            f"fecha -- {c.erro}", lm.nome))
            if cfg.compatibilizacao == "iterativa":
                # a malha única já dá o mesmo momento dos dois lados; o ajuste
                # iterativo dos graus de engastamento refaria as linhas de
                # ruptura por cima do resultado
                cfg_compat = dataclasses.replace(
                    cfg, compatibilizacao="maior")
                res.avisos.append(av.Aviso(
                    "Com a análise por elementos finitos a compatibilização "
                    "iterativa não se aplica: a malha única já iguala o "
                    "momento dos dois lados da viga; adotado o maior.",
                    av.CONSTRUTIVO))

    # -- 4. compatibilização ------------------------------------------------
    comp, esforcos = compat.compatibilizar(pav, esforcos, cfg_compat)
    res.compatibilizacao = comp
    for texto in comp.avisos:
        res.avisos.append(av.classificar(texto))

    # -- 5 a 7 --------------------------------------------------------------
    contador = [0]
    for laje in macicas:
        rl = ResultadoLaje(laje=laje, esforcos=esforcos[laje.nome])
        rl.predimensionamento = predim.get(laje.nome)
        if rl.predimensionamento is not None:
            classe = (av.CONSTRUTIVO if rl.predimensionamento.convergiu
                      else av.ERRO)
            rl.avisos.append(av.Aviso(
                f"{laje.nome}: espessura pré-dimensionada em "
                f"{rl.predimensionamento.h_final:g} cm a partir de "
                f"{rl.predimensionamento.h_inicial:g} cm — "
                f"{rl.predimensionamento.mensagem}", classe, laje.nome))
        for texto in rl.esforcos.avisos:
            rl.avisos.append(av.classificar(texto, laje.nome))

        # as reações vêm antes da flexão porque o arredondamento do momento
        # sobre o apoio (14.6.3), quando ligado, precisa da reação de
        # cálculo do bordo para reduzir o momento do eixo teórico
        rl.reacoes = rc.calcular(laje, rl.esforcos, cfg)
        for texto in rl.reacoes.avisos:
            rl.avisos.append(av.classificar(texto, laje.nome))

        res.cobrimentos.extend(_dimensionar_flexao(rl, pav, comp))
        for f in rl.flexoes:
            if f.erro:
                rl.avisos.append(av.classificar(
                    f"{laje.nome}, {f.rotulo}: {f.erro}", laje.nome))

        rl.els = els_mod.verificar(laje, rl.esforcos, pav.concreto, cfg)
        if not rl.els.atende:
            rl.avisos.append(av.classificar(
                f"{laje.nome}: a flecha de longa duração de "
                f"{rl.els.f_diferida:.2f} cm passa do limite de "
                f"{rl.els.f_admissivel:.2f} cm (L/{rl.els.divisor}, "
                f"Tabela 13.3) — flecha excessiva.", laje.nome))

        _detalhar(rl, pav, comp, contador)
        _verificar_cortante(rl, pav)
        rl.puncoes = pun.verificar_laje(rl, pav)
        for pu in rl.puncoes:
            if not pu.atende:
                rl.avisos.append(av.classificar(
                    f"{pu.rotulo}: punção (19.5) -- τSd = "
                    f"{pu.tau_sd1:.2f} MPa em C' contra τRd1 = "
                    f"{pu.tau_rd1:.2f} MPa; τSd = {pu.tau_sd0:.2f} MPa em C "
                    f"contra τRd2 = {pu.tau_rd2:.2f} MPa -- "
                    f"{pu.observacao}.", laje.nome))
            elif not pu.verificada:
                rl.avisos.append(av.Aviso(
                    f"{pu.rotulo}: punção -- {pu.observacao}.",
                    av.CONSTRUTIVO, laje.nome))
        rl.formas = fm.calcular(laje)

        for p in rl.posicoes:
            for problema in det.conferir_posicao(p, laje, cfg):
                rl.avisos.append(av.classificar(problema, laje.nome))
        res.lajes.append(rl)

    # -- 8. armadura única das bordas comuns --------------------------------
    _detalhar_continuidades(res, pav, comp, contador)
    for p in res.posicoes_continuidade:
        laje = pav.laje(p.laje.split(" / ")[0])
        if laje is not None:
            for problema in det.conferir_posicao(p, laje, cfg):
                res.avisos.append(av.classificar(problema))

    _conferir_traspasse(res, pav)

    # -- 8b. armadura superior de canto das linhas de ruptura (R11) ---------
    if cfg.armadura_canto and res.mef is None:
        res.cantos = cnt.dimensionar(res, pav)
        for c in res.cantos:
            if c.erro:
                res.avisos.append(av.classificar(
                    f"{c.rotulo}: a armadura superior de canto não fecha "
                    f"-- {c.erro}", c.laje))
    elif not cfg.armadura_canto and res.mef is None:
        sem = [c.rotulo for rl in res.lajes if rl.esforcos is not None
               for c in cnt.cantos_da_laje(rl.laje, rl.esforcos)]
        if sem:
            res.avisos.append(av.Aviso(
                f"Armadura de canto desligada: {len(sem)} canto(s) de "
                f"bordos apoiados ficam sem armadura superior. Sem ela o "
                f"canto levanta e as linhas de ruptura superestimam a "
                f"resistência em cerca de "
                f"{(cnt.fator_bifurcacao() - 1) * 100:.0f} % (Souza & "
                f"Cunha, §5.9).", av.CONSTRUTIVO))

    # -- lajes especiais (treliçada, alveolar, nervurada) -------------------
    res.especiais = atr.calcular_especiais(pav)

    # -- 9 e 10 -------------------------------------------------------------
    _consolidar_apoios(res, pav)
    _quantitativo(res, pav)
    return res
