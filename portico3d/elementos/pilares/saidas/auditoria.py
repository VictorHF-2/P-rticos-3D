# -*- coding: utf-8 -*-
"""
auditoria.py
Roteiro de verificações da memória de cálculo.

A memória precisa se sustentar sozinha: quem a lê depois -- outro projetista,
o cliente, uma revisão -- tem de conseguir dizer **o que foi verificado, com
que critério e qual foi o resultado**, sem abrir o programa. E, sobretudo, tem
de conseguir ver **o que não foi verificado**: é a omissão declarada que
distingue uma memória auditável de uma lista de números.

Cada linha do roteiro é montada a partir do :class:`ResultadoPilar` -- não é
texto fixo. Se a verificação não rodou, a linha diz isso.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core import esbeltez as esb_mod
from ..core.dimensionar import ResultadoPilar
from ..core.materiais import (DESCRICAO_COMBINACAO, ESBELTEZ_FLUENCIA,
                              ESBELTEZ_MAXIMA, ESBELTEZ_METODO_EXATO,
                              RHO_MAXIMO, RHO_MAXIMO_CORRENTE,
                              RHO_MAXIMO_EMENDA)
from ..core.formato import num

#: situações possíveis de uma verificação
ATENDIDO = "Atendido"
NAO_ATENDIDO = "Não atendido"
DISPENSADO = "Dispensado"
NAO_VERIFICADO = "Não verificado"
INFORMATIVO = "Informativo"


@dataclass
class Verificacao:
    """Uma linha do roteiro de auditoria."""

    item: str                    # item da NBR 6118
    descricao: str
    criterio: str
    resultado: str
    situacao: str


def _sit(ok: bool) -> str:
    return ATENDIDO if ok else NAO_ATENDIDO


def roteiro(res: ResultadoPilar) -> list[Verificacao]:
    """Monta o roteiro completo de verificações do lance."""
    v: list[Verificacao] = []
    _geometria(res, v)
    _esbeltez(res, v)
    _segunda_ordem(res, v)
    _flexao(res, v)
    _detalhamento(res, v)
    _servico(res, v)
    _fadiga(res, v)
    _tabeladas(res, v)
    _omissoes(res, v)
    return v


def _geometria(res: ResultadoPilar, v: list[Verificacao]) -> None:
    p = res.pilar
    secao = p.secao
    menor = secao.menor_dimensao
    v.append(Verificacao(
        "13.2.3", "Dimensão mínima da seção transversal",
        "menor dimensão >= 19 cm; entre 19 e 14 cm com γn",
        f"menor dimensão = {num(menor)} cm; γn = {num(p.gamma_n, 2)}",
        _sit(menor >= 14.0)))
    v.append(Verificacao(
        "13.2.3", "Área mínima da seção transversal", "Ac >= 360 cm²",
        f"Ac = {num(secao.area, 0)} cm²", _sit(secao.area >= 360.0)))
    v.append(Verificacao(
        "14.4.1", "Elemento linear (barra)",
        "comprimento >= 3 vezes a maior dimensão da seção",
        f"L = {num(p.lance.altura)} cm contra 3 × {num(secao.maior_dimensao)} = "
        f"{num(3 * secao.maior_dimensao)} cm",
        _sit(p.eh_elemento_linear)))
    v.append(Verificacao(
        "18.4 / 18.5", "Classificação como pilar ou pilar-parede",
        "maior dimensão <= 5 vezes a menor",
        (f"{num(secao.maior_dimensao)} / {num(min(secao.hx, secao.hy))} = "
         f"{num(secao.maior_dimensao / max(min(secao.hx, secao.hy), 1e-9), 2)}"),
        INFORMATIVO if not secao.eh_pilar_parede else
        "Pilar-parede: aplicar o item 18.5"))
    a = res.arranjo
    phi = a.phi if a is not None else 0.0
    phi_t = a.phi_estribo if a is not None else 0.0
    c_adotado = (a.cobrimento if a is not None and a.cobrimento > 0
                 else p.ambiente.cobrimento_adotado)
    c_min = p.ambiente.cobrimento_minimo(phi, phi_t)
    v.append(Verificacao(
        "7.4.7", "Cobrimento nominal da armadura",
        f"o maior entre a Tabela 7.2 (CAA {p.ambiente.caa}: "
        f"{num(p.ambiente.cobrimento_tabelado)} cm), a bitola da barra "
        f"(7.4.7.5) e dmáx/1,2 (7.4.7.6)",
        f"c adotado = {num(c_adotado)} cm contra o mínimo de {num(c_min, 2)} cm; "
        f"governa {p.ambiente.governante(phi, phi_t)}",
        _sit(c_adotado >= c_min - 1e-9)))


def _esbeltez(res: ResultadoPilar, v: list[Verificacao]) -> None:
    p = res.pilar
    for direcao in ("x", "y"):
        e = res.esbeltez.get(direcao)
        if e is None:
            continue
        v.append(Verificacao(
            "15.8.2", f"Comprimento equivalente na direção {direcao}",
            "le = min(l0 + h; l), com h medido no plano da direção; em "
            "balanço, le = 2 l",
            f"le = {num(e.le, 0)} cm — {p.le_memoria(direcao)}", INFORMATIVO))
        v.append(Verificacao(
            "15.8.1", f"Índice de esbeltez na direção {direcao}",
            f"λ <= {num(ESBELTEZ_MAXIMA)}, salvo elemento pouco "
            f"comprimido (Nd < 0,10 fcd Ac)",
            f"λ = le/i = {num(e.le)}/{num(e.i, 2)} = {num(e.lam, 1)}",
            _sit(e.lam <= ESBELTEZ_MAXIMA
                 or esb_mod.pilar_pouco_comprimido(p))))
        v.append(Verificacao(
            "15.8.2", f"Esbeltez limite na direção {direcao}",
            "λ₁ = (25 + 12,5 e1/h)/αb, com 35 <= λ₁ <= 90",
            f"λ₁ = {num(e.lam_1, 1)} (αb = {num(e.alfa_b, 2)}); "
            f"{e.veredito}", INFORMATIVO))
        if e.imposta and e.lam <= e.lam_1:
            v.append(Verificacao(
                "15.8.2", f"2ª ordem imposta na direção {direcao}",
                "critério de projeto: considerar a 2ª ordem mesmo com "
                "λ <= λ₁ (a norma só a dispensa)",
                f"λ = {num(e.lam, 1)} <= λ₁ = {num(e.lam_1, 1)}; "
                f"considerada", INFORMATIVO))
        geral = p.config.metodo_2a_ordem == "geral"
        v.append(Verificacao(
            "15.8.3.2", f"Método geral obrigatório na direção {direcao}",
            f"obrigatório para λ > {num(ESBELTEZ_METODO_EXATO)}",
            f"λ = {num(e.lam, 1)}"
            + ("; calculado pelo método geral" if geral else ""),
            DISPENSADO if e.lam <= ESBELTEZ_METODO_EXATO
            else (ATENDIDO if geral else NAO_VERIFICADO)))
        v.append(Verificacao(
            "11.3.3.4.3", f"Momento mínimo de 1ª ordem na direção {direcao}",
            "e1,min = 1,5 + 0,03 h",
            f"e1,min = {num(e.e1_min, 2)} cm; M1d,min = {num(e.M1d_min / 100, 1)} kN·m "
            f"contra M1d,A = {num(e.M1d_A / 100, 1)} kN·m", INFORMATIVO))
        mm = res.momento_minimo
        if mm is None:
            v.append(Verificacao(
                "11.3.3.4.3", f"Envoltória mínima na direção {direcao}",
                "envoltória resistente contendo a envoltória mínima "
                "(item 3.1 da apostila de referência)",
                "o critério adotado impõe o mínimo como piso das situações "
                "de cálculo (método \"planilha\"); não há verificação "
                "isolada a relatar", DISPENSADO))
        else:
            Msd = mm.Msd_x if direcao == "x" else mm.Msd_y
            MRd = mm.MRd_x if direcao == "x" else mm.MRd_y
            ok = mm.ok_x if direcao == "x" else mm.ok_y
            v.append(Verificacao(
                "11.3.3.4.3", f"Envoltória mínima na direção {direcao}",
                "Md,tot,min <= MRd da direção, em análise isolada à flexão "
                "composta normal (item 3.1 da apostila de referência)",
                f"Md,tot,min = {num(Msd / 100, 1)} kN·m contra "
                f"MRd = {num(MRd / 100, 1)} kN·m", _sit(ok)))
            if direcao == "y":
                if mm.pontos_elipse:
                    v.append(Verificacao(
                        "11.3.3.4.3 / 15.3.2",
                        "Envoltória mínima: pontos intermediários da elipse",
                        "elipse (Mx/Md,tot,mín,x)² + (My/Md,tot,mín,y)² = 1 "
                        "contida na envoltória resistente (Figuras 11.3 e "
                        "15.2)",
                        f"{len(mm.pontos_elipse)} ponto(s) conferidos entre as "
                        f"direções principais; menor margem MRd/MSd = "
                        f"{num(mm.fs_elipse, 2)}", _sit(mm.ok_elipse)))
                else:
                    v.append(Verificacao(
                        "11.3.3.4.3 / 15.3.2",
                        "Envoltória mínima: pontos intermediários da elipse",
                        "elipse contida na envoltória resistente (Figuras "
                        "11.3 e 15.2)",
                        "desligado nos critérios: só as duas análises "
                        "isoladas nas direções principais, que a norma "
                        "admite (15.3.2)", INFORMATIVO))


def _segunda_ordem(res: ResultadoPilar, v: list[Verificacao]) -> None:
    for direcao in ("x", "y"):
        s = res.segunda_ordem.get(direcao)
        e = res.esbeltez.get(direcao)
        if s is None or e is None:
            continue
        if not s.aplicavel:
            v.append(Verificacao(
                "15.8.2", f"Efeitos locais de 2ª ordem na direção {direcao}",
                "dispensados quando λ <= λ₁",
                f"λ = {num(e.lam, 1)} <= λ₁ = {num(e.lam_1, 1)}",
                DISPENSADO))
            continue
        from ..core.segunda_ordem import metodo_efetivo
        metodo = metodo_efetivo(res.pilar)
        if metodo == "diagrama":
            v.append(Verificacao(
                "15.8.3.3.4",
                f"Pilar-padrão acoplado a diagramas M, N, 1/r ({direcao})",
                "M_tot = αb M1d,A / (1 - Nd le²/(10 (EI)sec)), (EI)sec da "
                "Figura 15.1 (1,10 fcd, Nd/γf3); λ <= 140",
                f"(EI)sec = {num(s.EI_sec / 1e4, 1)} kN·m²; e2 = {num(s.e2, 2)} cm",
                _sit(e.lam <= ESBELTEZ_METODO_EXATO and s.e2 < float("inf"))))
        elif metodo == "geral":
            g = s.geral
            v.append(Verificacao(
                "15.8.3.2", f"Método geral ({direcao})",
                "análise não linear com a barra discretizada, momento-"
                "curvatura real em cada seção e não linearidade geométrica",
                (f"{len(g.z)} seções, {g.iteracoes} iterações; braço de 2ª "
                 f"ordem máximo {num(s.e2, 2)} cm") if g and g.convergiu
                else f"não convergiu: {g.motivo if g else '—'}",
                _sit(bool(g and g.convergiu))))
        v.append(Verificacao(
            "15.8.3.3.2", f"Pilar-padrão com curvatura aproximada ({direcao})",
            "e2 = le²/10 . 1/r, com 1/r = 0,005/[h(ν+0,5)] <= 0,005/h",
            f"ν = {num(s.nu, 3)}; 1/r = {num(s.curvatura, 6)} cm⁻¹; "
            f"e2 = {num(s.e2_curvatura, 2)} cm", INFORMATIVO))
        v.append(Verificacao(
            "15.8.3.3.3", f"Pilar-padrão com rigidez aproximada ({direcao})",
            "raiz da quadrática A M² + B M + C = 0 do item 15.8.3.3.3",
            f"e2 = {num(s.e2_rigidez, 2)} cm (κ = {num(s.kappa, 0)})",
            INFORMATIVO))
        v.append(Verificacao(
            "15.8.3.3", f"Efeito local de 2ª ordem adotado ({direcao})",
            f"critério de projeto: {res.pilar.config.metodo_2a_ordem}",
            f"e2 = {num(s.e2, 2)} cm por {s.metodo}", INFORMATIVO))
        if e.gamma_n1 > 1.0:
            v.append(Verificacao(
                "15.8.1", f"Coeficiente γn1 ({direcao})",
                "λ > 140: efeitos locais de 2ª ordem majorados por "
                "γn1 = 1 + (λ - 140)/140",
                f"γn1 = {num(e.gamma_n1, 3)}", ATENDIDO))
        v.append(Verificacao(
            "15.8.4", f"Fluência na direção {direcao}",
            f"obrigatória para λ > {num(ESBELTEZ_FLUENCIA)}",
            (f"e_cc = {num(s.e_cc, 2)} cm (φ = "
             f"{num(res.pilar.phi_fluencia, 2)})")
            if res.pilar.config.considerar_fluencia
            else f"λ = {num(e.lam, 1)}",
            ATENDIDO if res.pilar.config.considerar_fluencia
            else (DISPENSADO if e.lam <= ESBELTEZ_FLUENCIA
                  else NAO_VERIFICADO)))


def _flexao(res: ResultadoPilar, v: list[Verificacao]) -> None:
    p = res.pilar
    for direcao, d in sorted(res.dim_fechado.items()):
        cl = d.classificacao
        v.append(Verificacao(
            "17.2.2", f"Flexão composta normal na direção {direcao} "
                      f"(casos fechados)",
            f"roteiro FC1-FC4 / FT1-FT4, armadura "
            f"{'simétrica' if d.simetrica else 'assimétrica'}",
            f"caso {d.caso} — {cl.excentricidade.lower() or 'n/d'} "
            f"excentricidade, domínio {d.dominio}; "
            f"As por camada = {num(max(d.As1, d.As2), 2)} cm²", INFORMATIVO))
    for vf in res.verificacoes:
        v.append(Verificacao(
            "17.2.5", f"Flexão composta oblíqua — {vf.situacao.nome}",
            f"(MSd,x/MRd,xx)^a + (MSd,y/MRd,yy)^a <= 1, "
            f"a = {num(p.alfa_interacao)}",
            f"{num(vf.razao_x, 3)}^a + {num(vf.razao_y, 3)}^a = {num(vf.interacao, 3)}"
            + ("" if vf.interacao_exigida else
               " (informativa: o critério de projeto adota a envoltória)"),
            _sit(vf.ok_interacao) if vf.interacao_exigida or vf.ok_interacao
            else INFORMATIVO))
        if vf.envoltoria_inatingivel:
            v.append(Verificacao(
                "15.8.3.3.5", f"Envoltória de resistência — "
                              f"{vf.situacao.nome}",
                "composição dos momentos dentro da envoltória de MRd, obtida "
                "do equilíbrio da seção",
                f"nenhuma linha neutra produz momento resistente na direção "
                f"solicitada (MSd = {num(vf.MSd / 100, 1)} kN·m) para "
                f"Nd = {num(p.Nd, 0)} kN", NAO_ATENDIDO))
        elif vf.MRd_envoltoria_inferior > 0:
            v.append(Verificacao(
                "15.8.3.3.5", f"Envoltória de resistência — "
                              f"{vf.situacao.nome}",
                "composição dos momentos dentro da envoltória de MRd, obtida "
                "do equilíbrio da seção — duas linhas neutras alcançam essa "
                "direção",
                f"MSd = {num(vf.MSd / 100, 1)} kN·m contra o intervalo "
                f"[{num(vf.MRd_envoltoria_inferior / 100, 1)}; "
                f"{num(vf.MRd_envoltoria / 100, 1)}] kN·m (domínio {vf.dominio})",
                _sit(vf.ok_envoltoria)))
        elif vf.MRd_envoltoria > 0:
            v.append(Verificacao(
                "15.8.3.3.5", f"Envoltória de resistência — "
                              f"{vf.situacao.nome}",
                "composição dos momentos dentro da envoltória de MRd, obtida "
                "do equilíbrio da seção",
                f"MSd = {num(vf.MSd / 100, 1)} kN·m contra MRd = "
                f"{num(vf.MRd_envoltoria / 100, 1)} kN·m na mesma direção "
                f"(domínio {vf.dominio})", _sit(vf.ok_envoltoria)))


def _detalhamento(res: ResultadoPilar, v: list[Verificacao]) -> None:
    p = res.pilar
    a = res.arranjo
    if a is None:
        v.append(Verificacao(
            "18.4.2", "Arranjo da armadura longitudinal", "-",
            "nenhum arranjo foi escolhido", NAO_VERIFICADO))
        return
    from ..core import arranjo as arr_mod
    from ..core.materiais import rho_minimo
    rho = res.taxa
    rho_min = rho_minimo(res.nu, p.concreto, p.aco)
    v.append(Verificacao(
        "17.3.5.3.1", "Taxa mínima de armadura longitudinal",
        "As >= 0,15 Nd/fyd >= 0,4 % Ac (ρ >= 0,15 ν fcd/fyd >= 0,4 %)",
        f"ρ = {num(rho * 100, 3)} % contra ρ,min = {num(rho_min * 100, 3)} %",
        _sit(rho >= rho_min - 1e-9)))
    v.append(Verificacao(
        "17.3.5.3.2", "Taxa máxima de armadura longitudinal",
        f"ρ <= {num(RHO_MAXIMO_CORRENTE * 100)} % na seção corrente e "
        f"<= {num(RHO_MAXIMO_EMENDA * 100)} % na região de emenda",
        f"ρ = {num(rho * 100, 3)} % na seção corrente; na emenda, "
        f"{num(rho * 200, 3)} %",
        _sit(rho <= RHO_MAXIMO_CORRENTE + 1e-9
             and 2.0 * rho <= RHO_MAXIMO_EMENDA + 1e-9)))
    v.append(Verificacao(
        "18.4.2.1", "Bitola da armadura longitudinal",
        f"10 mm <= ø <= 1/8 da menor dimensão "
        f"({num(arr_mod.bitola_maxima(p.secao), 1)} mm)",
        f"{a.descricao_bitolas()} mm",
        _sit(10.0 <= a.phi_min
             and a.phi <= arr_mod.bitola_maxima(p.secao) + 1e-9)))
    s_min = arr_mod.espacamento_livre_minimo(a.phi, p.ambiente.dmax_agregado)
    v.append(Verificacao(
        "18.4.2.2", "Espaçamento livre entre barras longitudinais",
        f"s >= max(2 cm; ø; 1,2 d_max) = {num(s_min, 1)} cm",
        f"s = {num(a.espacamento_livre, 1)} cm",
        _sit(a.espacamento_livre >= s_min - 1e-6)))
    s_max = arr_mod.espacamento_eixos_maximo(p.secao)
    v.append(Verificacao(
        "18.4.2.2", "Espaçamento entre eixos de barras",
        f"s <= min(2 . menor dimensão; 40 cm) = {num(s_max, 1)} cm",
        f"s = {num(a.espacamento_eixos, 1)} cm",
        _sit(a.espacamento_eixos <= s_max + 1e-6)))
    v.append(Verificacao(
        "18.4.2.2", "Número mínimo de barras",
        "uma por vértice em seção poligonal; seis em seção circular",
        f"{a.n_barras} barras", _sit(True)))

    e = res.estribos
    if e is not None:
        from ..core import estribos as est_mod
        v.append(Verificacao(
            "18.4.3", "Bitola do estribo",
            f"øt >= max(5 mm; øl/4) = "
            f"{num(est_mod.bitola_minima(a.phi), 2)} mm",
            f"øt = {num(e.phi)} mm",
            _sit(e.phi >= est_mod.bitola_minima(a.phi) - 1e-9)))
        v.append(Verificacao(
            "18.4.3", "Espaçamento longitudinal dos estribos",
            f"s <= min(20 cm; menor dimensão; 12 øl) = {num(e.s_maximo, 1)} cm "
            f"(governa: {e.motivo_s})",
            f"s = {num(e.s)} cm", _sit(e.s <= e.s_maximo + 1e-9)))
        v.append(Verificacao(
            "18.2.4", "Proteção contra flambagem das barras",
            f"barras a mais de 20 øt = {num(e.alcance, 1)} cm do canto, ou "
            f"além de duas por trecho, exigem estribo suplementar",
            f"{e.n_suplementares} grampo(s) suplementar(es) por nível",
            ATENDIDO))
    anc = res.ancoragem
    if anc is not None:
        v.append(Verificacao(
            anc.item, "Comprimento de espera das barras longitudinais"
            + (" — emenda de barras tracionadas" if anc.tracionada else ""),
            anc.regra,
            f"lb = {num(anc.lb, 0)} cm; {anc.simbolo} = {num(anc.l0c, 0)} cm "
            f"(piso {num(anc.l0c_min, 0)} cm)"
            + (f"; {anc.motivo}" if anc.tracionada else
               "; nenhuma barra tracionada nas solicitações de cálculo"),
            ATENDIDO))


def _tabeladas(res: ResultadoPilar, v: list[Verificacao]) -> None:
    """As grandezas que o programa buscou em tabela em vez de pedir."""
    p = res.pilar
    cfg = p.config
    if cfg.ponderacao_automatica:
        v.append(Verificacao(
            "Tabela 12.1", "Coeficientes de ponderação das resistências",
            f"combinações {DESCRICAO_COMBINACAO[cfg.combinacao].lower()}"
            + (", com condições desfavoráveis de execução"
               if cfg.execucao_desfavoravel else "")
            + (", com CA-25 sem controle de qualidade"
               if cfg.ca25_sem_controle else ""),
            f"γc = {num(p.concreto.gamma_c, 2)}; "
            f"γs = {num(p.aco.gamma_s, 2)}", ATENDIDO))
    else:
        v.append(Verificacao(
            "Tabela 12.1", "Coeficientes de ponderação das resistências",
            "impostos pelo projetista",
            f"γc = {num(p.concreto.gamma_c, 2)}; "
            f"γs = {num(p.aco.gamma_s, 2)}", INFORMATIVO))
    v.append(Verificacao(
        "17.2.5", "Expoente da expressão de interação",
        "1,2 em seção retangular; 1,0 nas demais",
        f"α = {num(p.alfa_interacao)}"
        + (" (adotado pelo programa)" if p.alfa_automatico
           else " (imposto pelo projetista)"), INFORMATIVO))
    if cfg.considerar_fluencia:
        origem = ("Tabela 8.1, por interpolação"
                  if cfg.phi_fluencia <= 0 else "imposto pelo projetista")
        v.append(Verificacao(
            "Tabela 8.1", "Coeficiente de fluência",
            f"umidade {num(cfg.umidade_ambiente)} %, 2Ac/u = "
            f"{num(p.espessura_ficticia, 1)} cm, t0 = "
            f"{num(cfg.idade_carregamento)} dias",
            f"φ = {num(p.phi_fluencia, 2)} ({origem})", ATENDIDO))


def _omissoes(res: ResultadoPilar, v: list[Verificacao]) -> None:
    """As verificações que este programa **não** faz, ditas por extenso."""
    p = res.pilar
    v.append(Verificacao(
        "15.7 / 15.6", "Efeitos globais de 2ª ordem",
        "parâmetro α ou coeficiente γz da estrutura",
        "fora do escopo: o programa calcula um lance isolado e recebe os "
        "esforços de 1ª ordem já apurados no modelo global",
        NAO_VERIFICADO))
    balancos = [d for d in ("x", "y") if p.lance.vinculo(d) == 3]
    if balancos and p.config.desaprumo_balanco:
        v.append(Verificacao(
            "11.3.3.4.1", "Desaprumo de pilar isolado em balanço",
            "θ1 = 1/200; M = Nd . θ1 . l somado ao momento de base",
            "somado em " + " e ".join(balancos) + ": "
            + "; ".join(f"{d}: {num(p.desaprumo_balanco(d) * p.fator_esforcos / 100, 1)} kN·m"
                        for d in balancos), ATENDIDO))
    elif balancos:
        v.append(Verificacao(
            "11.3.3.4.1", "Desaprumo de pilar isolado em balanço",
            "θ1 = 1/200; M = Nd . θ1 . l somado ao momento de base",
            "desligado nos critérios: o desaprumo foi declarado como já "
            "contido nos esforços informados", NAO_VERIFICADO))
    else:
        v.append(Verificacao(
            "11.3.3.4.1", "Imperfeições geométricas globais (desaprumo)",
            "theta_a = 1/(100 sqrt(H))",
            "fora do escopo: entra nos esforços do modelo global",
            NAO_VERIFICADO))
    v.append(Verificacao(
        "16.2.3", "Combinações de ações",
        "combinação última normal com γf e ψ",
        f"fora do escopo: os esforços de entrada são tomados como de "
        f"cálculo (γf de entrada = {num(p.config.gamma_f)})",
        NAO_VERIFICADO))
    for direcao, c in (res.cisalhamento or {}).items():
        if c.Vd <= 0.0:
            v.append(Verificacao(
                "17.4", f"Força cortante, direção {direcao}",
                "VSd <= VRd2 e VSd <= Vc + Vsw (modelo I)",
                "não aplicável: cortante de cálculo não informada nesta "
                "direção; o estribo sai dos critérios construtivos do item "
                "18.4.3",
                DISPENSADO))
            continue
        v.append(Verificacao(
            "17.4.2.2-a", f"Biela comprimida, direção {direcao}",
            f"VSd <= VRd2 = 0,27 αv2 fcd bw d = {num(c.VRd2, 1)} kN; d até o "
            f"centroide de todas as barras da metade tracionada (conservador)",
            f"VSd = {num(c.Vd, 1)} kN ({num(c.razao_biela * 100, 0)} % de VRd2); "
            f"bw = {num(c.bw, 1)} cm, d = {num(c.d, 1)} cm",
            ATENDIDO if c.razao_biela <= 1.0 + 1e-6 else NAO_ATENDIDO))
        v.append(Verificacao(
            "17.4.2.2-b", f"Tração diagonal, direção {direcao}",
            f"VSd <= Vc + Vsw = {num(c.Vc, 1)} + {num(c.Vsw, 1)} = {num(c.VRd3, 1)} kN",
            f"VSd = {num(c.Vd, 1)} kN ({num(c.razao_tracao * 100, 0)} % de VRd3)",
            ATENDIDO if c.razao_tracao <= 1.0 + 1e-6 else NAO_ATENDIDO))
        v.append(Verificacao(
            "17.4.1.1.2-c", f"Armadura mínima de cisalhamento, direção "
                            f"{direcao}",
            f"dispensada se VSd <= Vc e a tração em estádio I <= fctk = "
            f"{num(c.fctk, 2)} MPa",
            (f"dispensada: VSd = {num(c.Vd, 1)} kN <= Vc = {num(c.Vc, 1)} kN e "
             f"tração = {num(c.tracao_estadio_1, 2)} MPa"
             if c.dispensa_minima else
             f"exigida: VSd = {num(c.Vd, 1)} kN, Vc = {num(c.Vc, 1)} kN, tração = "
             f"{num(c.tracao_estadio_1, 2)} MPa"),
            ATENDIDO))
        if not c.dispensa_minima:
            v.append(Verificacao(
                "18.3.3.2", f"Espaçamento do estribo pela cortante, direção "
                            f"{direcao}",
                f"s <= {num(c.s_maximo, 1)} cm",
                f"s = {num(c.s)} cm",
                ATENDIDO if c.s <= c.s_maximo + 1e-9 else NAO_ATENDIDO))
    v.append(Verificacao(
        "17.4.2.3 / 17.5", "Modelo II e torção",
        "bielas de inclinação variável; torção e sua interação com a cortante",
        "não verificado: a cortante é verificada pelo modelo I, que é o mais "
        "conservador dos dois; torção fica fora do escopo",
        NAO_VERIFICADO))
    if res.fadiga is None or not res.fadiga.obra:
        v.append(Verificacao(
            "23", "Fadiga",
            "variação de tensão sob carga cíclica",
            "não verificado: pilar de edifício corrente não é peça de fadiga. "
            "Em pilar de ponte, escolha a obra nos critérios (6118, 23.5, com "
            "o ψ1,fad da NBR 8681, Tabela 7)",
            NAO_VERIFICADO))
    v.append(Verificacao(
        "13.2.3 / 18.5", "Pilar-parede",
        "disposições próprias do item 18.5",
        "não verificado" if p.secao.eh_pilar_parede
        else "não aplicável: a seção não é pilar-parede",
        NAO_VERIFICADO if p.secao.eh_pilar_parede else DISPENSADO))
    if not p.secao.tem_casos_fechados:
        v.append(Verificacao(
            "17.2.2", "Roteiro dos casos fechados de flexo-compressão",
            "FC1-FC4 / FT1-FT4, válido em seção retangular",
            f"não aplicável à seção {p.secao.tipo}: o dimensionamento saiu "
            f"inteiramente do motor seccional", DISPENSADO))
    elif not res.dim_fechado:
        v.append(Verificacao(
            "17.2.2", "Roteiro dos casos fechados de flexo-compressão",
            "FC1-FC4 / FT1-FT4 (modelo de duas camadas), informativo",
            "desligado nos critérios: o dimensionamento e o veredito saíram "
            "inteiramente do motor seccional", DISPENSADO))


def _fadiga(res: ResultadoPilar, v: list[Verificacao]) -> None:
    f = res.fadiga
    if f is None or not f.obra:
        return
    if not f.aplicavel:
        dispensa = f.psi1 == 0.0 and "ψ1,fad = 0" in f.motivo
        v.append(Verificacao(
            "23.5 / NBR 8681 T.7", "Fadiga do pilar de ponte",
            "Δσs <= Δfsd,fad (Tabela 23.2) e σc,máx <= 0,45 fcd",
            ("dispensada: " if dispensa else "não verificada: ") + f.motivo,
            DISPENSADO if dispensa else NAO_VERIFICADO))
        return
    gov = max(f.cotas, key=lambda c: c.barra_critica[3] / c.barra_critica[4])
    b = gov.barra_critica
    v.append(Verificacao(
        "23.5.5", "Fadiga da armadura longitudinal",
        f"γf Δσs <= Δfsd,fad (Tabela 23.2, 2 × 10⁶ ciclos), ψ1,fad = "
        f"{num(f.psi1, 1)}",
        f"Δσs = {num(b[3], 0)} MPa contra {num(b[4], 0)} MPa (cota {gov.nome}, "
        f"ø{num(b[2])})", _sit(f.ok_aco)))
    v.append(Verificacao(
        "23.5.4.1", "Fadiga do concreto em compressão",
        "ηc γf σc,máx <= fcd,fad = 0,45 fcd (ηc = 1, do lado seguro)",
        f"σc,máx = {num(max(c.sigma_c_max for c in f.cotas), 1)} MPa contra "
        f"{num(f.fcd_fad, 1)} MPa", _sit(f.ok_concreto)))


def _servico(res: ResultadoPilar, v: list[Verificacao]) -> None:
    s = res.servico
    if s is None:
        return
    if not s.aplicavel:
        v.append(Verificacao(
            "13.4.2 / 17.3.3", "Abertura de fissuras (ELS-W)",
            "wk <= limite da Tabela 13.4 na combinação frequente",
            f"não verificado: {s.motivo}", NAO_VERIFICADO))
        return
    gov = s.governante
    b = gov.critica if gov else None
    v.append(Verificacao(
        "13.4.2 / 17.3.3.2", "Abertura de fissuras (ELS-W)",
        f"wk = min(wk1; wk2) <= {num(s.wk_limite, 2)} mm ({s.origem_limite}); "
        f"σs no estádio II, αe = {num(s.alfa_e)}",
        (f"wk = {num(b.wk, 3)} mm na cota {gov.nome}, σs = {num(b.sigma, 0)} "
         f"MPa" if b else "seção inteiramente comprimida em serviço nas "
         "duas cotas: sem fissura de flexão"),
        _sit(s.ok)))
    if s.tabela_17_2 is not None:
        phi_max, s_max = s.tabela_17_2
        v.append(Verificacao(
            "17.3.3.3", "Controle da fissuração pela Tabela 17.2",
            "bitola e espaçamento máximos para a maior σs (informativo)",
            f"ø ≤ {num(phi_max)} mm e s ≤ "
            f"{num(s_max) + ' cm' if s_max else '—'}; arranjo com "
            f"ø{num(res.arranjo.phi)} e s = {num(s.espacamento_barras, 1)} cm",
            INFORMATIVO))


def resumo(verificacoes: list[Verificacao]) -> dict[str, int]:
    """Contagem por situação, para o quadro-resumo da memória."""
    saida: dict[str, int] = {}
    for v in verificacoes:
        chave = v.situacao if v.situacao in (
            ATENDIDO, NAO_ATENDIDO, DISPENSADO, NAO_VERIFICADO,
            INFORMATIVO) else NAO_ATENDIDO
        saida[chave] = saida.get(chave, 0) + 1
    return saida
