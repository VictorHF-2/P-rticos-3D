# -*- coding: utf-8 -*-
"""
auditoria.py
Roteiro de verificações da memória de cálculo.

A memória precisa se sustentar sozinha: quem a lê depois -- outro projetista,
o cliente, uma revisão -- tem de conseguir dizer **o que foi verificado, com
que critério e qual foi o resultado**, sem abrir o programa. E, sobretudo, tem
de conseguir ver **o que não foi verificado**: é a omissão declarada que
distingue uma memória auditável de uma lista de números.

Cada linha do roteiro é montada a partir do :class:`ResultadoViga` -- não é
texto fixo. Se a verificação não rodou, a linha diz isso.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core import alinhamento as al
from ..core.dimensionar import ResultadoViga

#: situações possíveis de uma verificação
ATENDIDO = "Atendido"
NAO_ATENDIDO = "Não atendido"
NAO_APLICAVEL = "Não aplicável"
NAO_VERIFICADO = "Não verificado"
APLICADO = "Aplicado"


@dataclass
class Verificacao:
    """Uma linha do roteiro: item, o que exige, situação e o número que decide."""

    item: str
    exigencia: str
    situacao: str
    observacao: str = ""


def _sit(ok: bool) -> str:
    return ATENDIDO if ok else NAO_ATENDIDO


def _juntas(res: ResultadoViga, v: list[Verificacao]) -> None:
    """Uma linha do roteiro por junta de mudança de seção.

    O que o alinhamento decide não aparece em nenhuma fórmula, então precisa
    aparecer aqui: quem lê a memória tem de saber por que existe gancho no meio
    da viga, e em que face.
    """
    for j in al.juntas(res.viga):
        interrompidas = [f for f in al.FACES if j.lado_com_gancho(f)]
        v.append(Verificacao(
            "18.3.2.4.1", f"Ancoragem na junta do apoio {j.k + 1}", APLICADO,
            f"alinhamento “{j.alinhamento}”: "
            + (f"face(s) {', '.join(interrompidas)} ancorada(s) com gancho no "
               f"eixo do apoio" if interrompidas
               else "as duas faces atravessam sem interrupção")))


def roteiro(res: ResultadoViga) -> list[Verificacao]:
    """Roteiro completo, na ordem em que o cálculo acontece."""
    viga = res.viga
    cfg = viga.config
    v: list[Verificacao] = []

    # -- geometria e durabilidade ------------------------------------------
    larguras = [t.secao.bw for t in viga.tramos]
    v.append(Verificacao(
        "13.2.2", "Largura da alma ≥ 12 cm (15 cm em viga-parede)",
        _sit(min(larguras) >= 12.0 or cfg.largura_reduzida_excepcional),
        f"bw mínimo adotado = {min(larguras):g} cm"))
    paredes = [i + 1 for i in range(len(viga.tramos)) if viga.eh_viga_parede(i)]
    v.append(Verificacao(
        "22.4.1", "Viga-parede (l/h < 2 biapoiada, < 3 contínua) exige "
                  "bielas e tirantes",
        NAO_APLICAVEL if not paredes else NAO_ATENDIDO,
        "nenhum tramo é viga-parede" if not paredes
        else f"tramos {paredes} caem na definição"))
    d_ref = max((c.d for c in res.cortantes), default=0.0)
    laje = [t.secao.bw for t in viga.tramos if d_ref and t.secao.bw > 5 * d_ref]
    v.append(Verificacao(
        "17.4.1.1.2 a", "Elemento com bw > 5d sai do modelo de viga",
        NAO_APLICAVEL if not laje else NAO_ATENDIDO,
        "nenhuma seção tem bw > 5d" if not laje
        else "há seção que deve ser verificada como laje (19.4)"))
    cob = viga.ambiente.cobrimento_nominal
    phis = sorted({p.phi for p in res.posicoes if p.tipo != "estribo"})
    v.append(Verificacao(
        "7.4.7", "c,nom da Tabela 7.2, ≥ Ø da barra e "
                 "d,agregado ≤ 1,2 c,nom",
        _sit(cob >= max(phis or [0]) / 10.0
             and cfg.d_agregado <= 1.2 * cob),
        f"c,nom = {cob:g} cm, maior bitola Ø{max(phis or [0]):g}, "
        f"agregado {cfg.d_agregado:g} cm"))

    # -- análise estrutural -------------------------------------------------
    v.append(Verificacao(
        "14.6.2.4", "Vão efetivo lef = l0 + a1 + a2",
        APLICADO, "modelo entre eixos de apoio, que é ≥ lef — conservador; "
                  "o lef é listado na tabela de geometria"))
    v.append(Verificacao(
        "11.7.1 e 14.6.7", "Coeficiente único da ação permanente e "
                           "alternância da variável",
        APLICADO,
        f"γg = {cfg.gamma_g:g} em toda a viga; "
        f"{'com' if cfg.alternancia else 'sem'} alternância de carregamento"))
    v.append(Verificacao(
        "14.6.4.3", "Redistribuição δ ≥ 0,75 e x/d limitado",
        NAO_APLICAVEL if cfg.redistribuicao >= 1.0 else _sit(
            cfg.redistribuicao >= 0.75),
        "sem redistribuição" if cfg.redistribuicao >= 1.0
        else f"δ = {cfg.redistribuicao:g}"))
    v.append(Verificacao(
        "14.6.6.1", "Momentos mínimos pela solidariedade viga–pilar",
        NAO_VERIFICADO,
        "os apoios extremos são modelados como rótulas; o critério de "
        "engastamento parcial "
        + ("está ligado em "
           f"{cfg.engastamento_minimo_extremidade:.0%} do momento do vão"
           if cfg.engastamento_minimo_extremidade
           else "está desligado — verifique à parte se a viga é monolítica "
                "com o pilar")))
    v.append(Verificacao(
        "15.10", "Estabilidade lateral de vigas esbeltas",
        NAO_VERIFICADO, "fora do escopo do programa; conferir à parte em viga "
                        "alta e estreita"))

    # -- flexão -------------------------------------------------------------
    reais = [r for r in res.regioes if not r.construtiva]
    if reais:
        pior = max(reais, key=lambda r: r.flexao.x_d / max(r.flexao.x_lim_d,
                                                           1e-9))
        v.append(Verificacao(
            "17.2.2 e 14.6.4.3", "Bloco retangular e ductilidade x/d ≤ limite",
            _sit(all(r.flexao.x_d <= r.flexao.x_lim_d + 1e-9 for r in reais)),
            f"pior caso {pior.nome}: x/d = {pior.flexao.x_d:.3f} contra "
            f"{pior.flexao.x_lim_d:.3f} ({pior.flexao.origem_limite})"))
        v.append(Verificacao(
            "17.3.5.2.1", "Armadura mínima de tração",
            APLICADO,
            reais[0].flexao.memoria.get("As,min obtida por", "")))
        pior_taxa = max(reais, key=lambda r: r.arranjo.As_ef / r.secao.area)
        v.append(Verificacao(
            "17.3.5.2.4", "As + A's ≤ 4 % de Ac fora da zona de emendas",
            _sit(all(r.arranjo.As_ef
                     + (r.arranjo_comprimido.As_ef
                        if r.arranjo_comprimido else 0.0)
                     <= 0.04 * r.secao.area + 1e-9 for r in reais)),
            f"maior taxa: {pior_taxa.nome} com "
            f"{100 * pior_taxa.arranjo.As_ef / pior_taxa.secao.area:.2f} % "
            f"de Ac"))
    v.append(Verificacao(
        "18.3.2.2", "Espaçamento livre mínimo entre barras (ah e av)",
        APLICADO, "governa quantas barras cabem por camada e quantas camadas "
                  "cabem na altura"))

    # -- cisalhamento e torção ---------------------------------------------
    if res.cortantes:
        pior_c = max(res.cortantes, key=lambda c: c.razao_biela)
        v.append(Verificacao(
            "17.4.2.2 / 17.4.2.3",
            f"Biela comprimida: Vsd ≤ VRd2 (Modelo "
            f"{cfg.modelo_cisalhamento})",
            _sit(all(c.biela_ok for c in res.cortantes)),
            f"pior caso x = {pior_c.x:.2f} m: Vsd/VRd2 = "
            f"{pior_c.razao_biela:.2f}"))
        v.append(Verificacao(
            "17.4.1.1.1", "Armadura transversal mínima ρsw ≥ 0,2 fctm/fywk",
            APLICADO, f"asw,mín = {pior_c.asw_min:.2f} cm²/m"))
        v.append(Verificacao(
            "17.4.1.2.1 a", "Redução do cortante junto ao apoio",
            APLICADO if cfg.reducao_apoio else NAO_APLICAVEL,
            "só a alínea (a), de carga distribuída; cargas concentradas a "
            "menos de 2d não são reduzidas — a favor da segurança"))
    if res.zonas_estribo:
        v.append(Verificacao(
            "18.3.3.2", "Bitola do estribo entre 5 mm e bw/10, s,máx e st,máx",
            _sit(all(z.asw_ef >= z.asw_req - 1e-6
                     for z in res.zonas_estribo)),
            f"{len(res.zonas_estribo)} faixas de estribo; "
            f"{max(z.n_ramos for z in res.zonas_estribo)} ramos no máximo"))
    if res.torcoes:
        pior_t = max(res.torcoes, key=lambda t: t.interacao)
        v.append(Verificacao(
            "17.5 e 17.7.2.2", "Torção pela treliça espacial e interação "
                               "com o cortante",
            _sit(all(t.biela_ok for t in res.torcoes)),
            f"pior caso x = {pior_t.x:.2f} m: Tsd/TRd2 + Vsd/VRd2 = "
            f"{pior_t.interacao:.3f}"))
    else:
        v.append(Verificacao(
            "17.5", "Torção", NAO_APLICAVEL if not viga.torcores
            else NAO_VERIFICADO,
            "nenhum torçor lançado" if not viga.torcores
            else "torçor lançado com a verificação desligada nos critérios"))

    # -- serviço ------------------------------------------------------------
    if res.flechas:
        pior_v = max(res.flechas,
                     key=lambda f: abs(f.f_total) / max(f.limite_visual, 1e-9))
        v.append(Verificacao(
            "17.3.2 e Tabela 13.3", "Deformação excessiva",
            _sit(all(f.ok_visual for f in res.flechas)),
            f"pior caso tramo {pior_v.tramo + 1}: "
            f"{abs(pior_v.f_total):.2f} cm contra "
            f"{pior_v.limite_visual:.2f} cm (L/"
            f"{cfg.limite_flecha_visual:g})"))
        pior_a = max(res.flechas,
                     key=lambda f: abs(f.f_apos_alvenaria)
                     / max(f.limite_alvenaria, 1e-9))
        v.append(Verificacao(
            "Tabela 13.3", f"Deslocamento após a construção "
                           f"({cfg.parede_apoiada})",
            NAO_APLICAVEL if cfg.parede_apoiada == "nenhuma"
            else _sit(all(f.ok_alvenaria for f in res.flechas)),
            f"pior caso tramo {pior_a.tramo + 1}: "
            f"{abs(pior_a.f_apos_alvenaria):.2f} cm contra "
            f"{pior_a.limite_alvenaria:.2f} cm (limite por vão e absoluto, o "
            f"mais restritivo)"))
        v.append(Verificacao(
            "Tabela 13.3", "Vibrações sentidas no piso",
            _sit(all(f.ok_vibracao for f in res.flechas))
            if cfg.verificar_vibracao else NAO_VERIFICADO,
            "critério opcional, ligado nos dados" if cfg.verificar_vibracao
            else "critério desligado — depende do uso da estrutura"))
    fiss = [r.fissuracao for r in res.regioes if r.fissuracao is not None]
    if fiss:
        pior_w = max(fiss, key=lambda w: w.wk / max(w.wk_limite, 1e-9))
        v.append(Verificacao(
            "17.3.3.2 e Tabela 13.4", "Abertura de fissuras wk",
            _sit(all(w.ok for w in fiss)),
            f"pior caso {pior_w.regiao}: wk = {pior_w.wk:.3f} mm contra "
            f"{pior_w.wk_limite:.2f} mm"))
        v.append(Verificacao(
            "17.3.3.2", "Armadura de pele no controle de fissuração",
            NAO_VERIFICADO,
            "o wk considera só a armadura de flexão — conservador"))

    # -- detalhamento -------------------------------------------------------
    if res.apoios_extremos:
        pior_ap = max(res.apoios_extremos,
                      key=lambda a: a.lb_nec / max(a.l_disponivel, 1e-9))
        # o apoio em que o trecho reto não basta **não** é reprovado quando os
        # grampos completam a ancoragem: era a mesma assimetria já corrigida em
        # `ResultadoViga.ok`, e aqui a memória dizia "não atendido" logo acima
        # da tabela que mostrava os grampos resolvendo
        def _resolvido(a) -> bool:
            return a.ok or any(g.apoio == a.apoio and g.ok and g.n > 0
                               for g in res.grampos)

        com_grampo = [g.apoio for g in res.grampos if g.n > 0 and g.ok]
        v.append(Verificacao(
            "18.3.2.4.1", "Ancoragem da armadura positiva no apoio extremo",
            _sit(all(_resolvido(a) for a in res.apoios_extremos)),
            f"maior valor entre lb,nec, r + 5,5 Ø e 60 mm. Pior caso apoio "
            f"{pior_ap.apoio}: exige {pior_ap.lb_nec:.1f} cm e há "
            f"{pior_ap.l_disponivel:.1f} cm"
            + (f"; completada por grampos "
               f"{', '.join(f'no apoio {k}' for k in com_grampo)}"
               if com_grampo else "")))
    v.append(Verificacao(
        "9.4.2.4 e 9.4.2.5", "Comprimento de ancoragem e efeito do gancho",
        APLICADO,
        ("gancho no apoio permitido pelos critérios"
         if cfg.ancoragem_gancho else
         "gancho no apoio não permitido pelos critérios")
        + "; α = 0,7 só com cobrimento de 3 Ø no plano normal ao gancho"))
    v.append(Verificacao(
        "18.3.2.3.1 e 17.4.2.2", "Decalagem aℓ e prolongamento de lb,nec",
        APLICADO, "escalonamento aos pares, com o diagrama de As decalado"))
    emendas = sum(len(p.emendas_x) + len(p.emendas_vizinhas)
                  for p in res.posicoes)
    costuras = [p for p in res.posicoes if p.tipo == "costura"]
    v.append(Verificacao(
        "9.5.2.2.1 e 9.5.2.4", "Traspasse e armadura transversal da emenda",
        APLICADO if emendas else NAO_APLICAVEL,
        f"{emendas} emenda(s); {len(costuras)} receberam costura"
        if emendas else "nenhuma emenda no detalhamento"))
    pele = [p for p in res.posicoes if p.tipo == "pele"]
    v.append(Verificacao(
        "17.3.5.2.3 e 18.3.5", "Armadura de pele em viga com h > 60 cm",
        APLICADO if pele else NAO_APLICAVEL,
        f"{len(pele)} posição(ões) de pele" if pele
        else "dispensada: nenhum tramo passa de 60 cm de altura"))
    susp = [p for p in res.posicoes if p.tipo == "suspensao"]
    indiretas = [c for c in viga.concentradas if getattr(c, "indireta", False)]
    v.append(Verificacao(
        "18.3.6", "Armadura de suspensão sob carga indireta",
        APLICADO if susp else NAO_APLICAVEL,
        f"{len(susp)} posição(ões) para {len(indiretas)} carga(s) indireta(s)"
        if susp else "nenhuma carga foi declarada como indireta"))

    # -- fadiga -------------------------------------------------------------
    if res.fadigas or res.fadigas_estribo:
        reprova = ([f"{f.regiao} (Δσs = {f.delta_sigma_s:.0f} contra "
                    f"{f.delta_fsd_fad:.0f} MPa)"
                    for f in res.fadigas if not f.ok_armadura]
                   + [f"concreto em {f.regiao}"
                      for f in res.fadigas if not f.ok_concreto_comprimido]
                   + [f"estribo em x = {f.x:.2f} m "
                      f"(Δσ = {f.delta_sigma_s:.0f} contra "
                      f"{f.delta_fsd_fad:.0f} MPa)"
                      for f in res.fadigas_estribo if not f.ok])
        v.append(Verificacao(
            "23.5", "Estado-limite último de fadiga",
            _sit(not reprova),
            f"{len(res.fadigas)} seções e {len(res.fadigas_estribo)} faixas "
            f"verificadas" + ("; reprovaram: " + "; ".join(reprova[:3])
                              if reprova else "")))
    else:
        v.append(Verificacao(
            "23.5", "Estado-limite último de fadiga", NAO_VERIFICADO,
            "critério desligado; só se aplica a estruturas com ações "
            "cíclicas relevantes (23.5.1)"))

    # -- o que o programa não cobre ----------------------------------------
    for item, exig in (
            ("13.2.5 e 21.3", "Aberturas e furos na alma"),
            ("17.6", "Fissuração inclinada da alma"),
            ("23.3",
             "Estado-limite de vibrações excessivas (fn > 1,2 fcrit)"),
            ("9.4.2.6",
             "Armadura transversal na ancoragem (25 % da força de uma barra; "
             "duas direções e s <= 5 Ø acima de Ø32)")):
        v.append(Verificacao(item, exig, NAO_VERIFICADO,
                             "fora do escopo do programa"))
    _juntas(res, v)
    for g in res.grampos:
        v.append(Verificacao(
            "18.3.2.4.1", f"Ancoragem com grampos no apoio {g.apoio}",
            _sit(g.ok),
            f"trecho reto de {g.lb_disp:.1f} cm contra lanc = {g.lanc:.1f} cm; "
            f"{g.n} grampo(s) Ø{g.phi:g} assumem {g.fracao * 100:.0f}% da "
            f"força (teto da bitola: Ø{g.phi_max:.1f} mm)"))
    return v


def resumo(verificacoes: list[Verificacao]) -> dict[str, int]:
    """Contagem por situação, para o parágrafo de fechamento."""
    contagem: dict[str, int] = {}
    for x in verificacoes:
        contagem[x.situacao] = contagem.get(x.situacao, 0) + 1
    return contagem
