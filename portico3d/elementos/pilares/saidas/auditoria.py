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

from ..core.dimensionar import ResultadoPilar
from ..core.materiais import (DESCRICAO_COMBINACAO, ESBELTEZ_FLUENCIA,
                              ESBELTEZ_MAXIMA, ESBELTEZ_METODO_EXATO,
                              RHO_MAXIMO)

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
    _tabeladas(res, v)
    _omissoes(res, v)
    return v


def _geometria(res: ResultadoPilar, v: list[Verificacao]) -> None:
    p = res.pilar
    secao = p.secao
    menor = secao.menor_dimensao
    v.append(Verificacao(
        "13.2.3", "Dimensão mínima da seção transversal",
        "menor dimensão >= 19 cm; entre 19 e 14 cm com gamma_n",
        f"menor dimensão = {menor:g} cm; gamma_n = {p.gamma_n:.2f}",
        _sit(menor >= 14.0)))
    v.append(Verificacao(
        "13.2.3", "Área mínima da seção transversal", "Ac >= 360 cm²",
        f"Ac = {secao.area:.0f} cm²", _sit(secao.area >= 360.0)))
    v.append(Verificacao(
        "18.4 / 18.5", "Classificação como pilar ou pilar-parede",
        "maior dimensão <= 5 vezes a menor",
        (f"{secao.maior_dimensao:g} / {min(secao.hx, secao.hy):g} = "
         f"{secao.maior_dimensao / max(min(secao.hx, secao.hy), 1e-9):.2f}"),
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
        f"{p.ambiente.cobrimento_tabelado:g} cm), a bitola da barra "
        f"(7.4.7.5) e dmáx/1,2 (7.4.7.6)",
        f"c adotado = {c_adotado:g} cm contra o mínimo de {c_min:.2f} cm; "
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
            f"le = {e.le:.0f} cm — {p.le_memoria(direcao)}", INFORMATIVO))
        v.append(Verificacao(
            "15.8.1", f"Índice de esbeltez na direção {direcao}",
            f"lambda <= {ESBELTEZ_MAXIMA:g}",
            f"lambda = le/i = {e.le:g}/{e.i:.2f} = {e.lam:.1f}",
            _sit(e.lam <= ESBELTEZ_MAXIMA)))
        v.append(Verificacao(
            "15.8.2", f"Esbeltez limite na direção {direcao}",
            "lambda_1 = (25 + 12,5 e1/h)/alfa_b, com 35 <= lambda_1 <= 90",
            f"lambda_1 = {e.lam_1:.1f} (alfa_b = {e.alfa_b:.2f}); "
            f"{e.veredito}", INFORMATIVO))
        v.append(Verificacao(
            "15.8.3.2", f"Método exato obrigatório na direção {direcao}",
            f"obrigatório para lambda > {ESBELTEZ_METODO_EXATO:g}",
            f"lambda = {e.lam:.1f}",
            DISPENSADO if e.lam <= ESBELTEZ_METODO_EXATO else NAO_VERIFICADO))
        v.append(Verificacao(
            "11.3.3.4.3", f"Momento mínimo de 1ª ordem na direção {direcao}",
            "e1,min = 1,5 + 0,03 h",
            f"e1,min = {e.e1_min:.2f} cm; M1d,min = {e.M1d_min / 100:.1f} kN·m "
            f"contra M1d,A = {e.M1d_A / 100:.1f} kN·m", INFORMATIVO))
        mm = res.momento_minimo
        if mm is None:
            v.append(Verificacao(
                "11.3.3.4.3", f"Envoltória mínima na direção {direcao}",
                "envoltória resistente contendo a envoltória mínima "
                "(item 3.1 da apostila)",
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
                "composta normal (item 3.1 da apostila)",
                f"Md,tot,min = {Msd / 100:.1f} kN·m contra "
                f"MRd = {MRd / 100:.1f} kN·m", _sit(ok)))


def _segunda_ordem(res: ResultadoPilar, v: list[Verificacao]) -> None:
    for direcao in ("x", "y"):
        s = res.segunda_ordem.get(direcao)
        e = res.esbeltez.get(direcao)
        if s is None or e is None:
            continue
        if not s.aplicavel:
            v.append(Verificacao(
                "15.8.2", f"Efeitos locais de 2ª ordem na direção {direcao}",
                "dispensados quando lambda <= lambda_1",
                f"lambda = {e.lam:.1f} <= lambda_1 = {e.lam_1:.1f}",
                DISPENSADO))
            continue
        v.append(Verificacao(
            "15.8.3.3.2", f"Pilar-padrão com curvatura aproximada ({direcao})",
            "e2 = le²/10 . 1/r, com 1/r = 0,005/[h(nu+0,5)] <= 0,005/h",
            f"nu = {s.nu:.3f}; 1/r = {s.curvatura:.6f} cm⁻¹; "
            f"e2 = {s.e2_curvatura:.2f} cm", INFORMATIVO))
        v.append(Verificacao(
            "15.8.3.3.3", f"Pilar-padrão com rigidez aproximada ({direcao})",
            "raiz da quadrática A M² + B M + C = 0 do item 15.8.3.3.3",
            f"e2 = {s.e2_rigidez:.2f} cm (kappa = {s.kappa:.0f})",
            INFORMATIVO))
        v.append(Verificacao(
            "15.8.3.3", f"Efeito local de 2ª ordem adotado ({direcao})",
            f"critério de projeto: {res.pilar.config.metodo_2a_ordem}",
            f"e2 = {s.e2:.2f} cm por {s.metodo}", INFORMATIVO))
        v.append(Verificacao(
            "15.8.4", f"Fluência na direção {direcao}",
            f"obrigatória para lambda > {ESBELTEZ_FLUENCIA:g}",
            (f"e_cc = {s.e_cc:.2f} cm (phi = "
             f"{res.pilar.phi_fluencia:.2f})")
            if res.pilar.config.considerar_fluencia
            else f"lambda = {e.lam:.1f}",
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
            f"As por camada = {max(d.As1, d.As2):.2f} cm²", INFORMATIVO))
    for vf in res.verificacoes:
        v.append(Verificacao(
            "17.2.5", f"Flexão composta oblíqua — {vf.situacao.nome}",
            f"(MSd,x/MRd,xx)^a + (MSd,y/MRd,yy)^a <= 1, "
            f"a = {p.alfa_interacao:g}",
            f"{vf.razao_x:.3f}^a + {vf.razao_y:.3f}^a = {vf.interacao:.3f}",
            _sit(vf.ok_interacao)))
        if vf.envoltoria_inatingivel:
            v.append(Verificacao(
                "15.8.3.3.5", f"Envoltória de resistência — "
                              f"{vf.situacao.nome}",
                "composição dos momentos dentro da envoltória de MRd, obtida "
                "do equilíbrio da seção",
                f"nenhuma linha neutra produz momento resistente na direção "
                f"solicitada (MSd = {vf.MSd / 100:.1f} kN·m) para "
                f"Nd = {p.Nd:.0f} kN", NAO_ATENDIDO))
        elif vf.MRd_envoltoria_inferior > 0:
            v.append(Verificacao(
                "15.8.3.3.5", f"Envoltória de resistência — "
                              f"{vf.situacao.nome}",
                "composição dos momentos dentro da envoltória de MRd, obtida "
                "do equilíbrio da seção — duas linhas neutras alcançam essa "
                "direção",
                f"MSd = {vf.MSd / 100:.1f} kN·m contra o intervalo "
                f"[{vf.MRd_envoltoria_inferior / 100:.1f}; "
                f"{vf.MRd_envoltoria / 100:.1f}] kN·m (domínio {vf.dominio})",
                _sit(vf.ok_envoltoria)))
        elif vf.MRd_envoltoria > 0:
            v.append(Verificacao(
                "15.8.3.3.5", f"Envoltória de resistência — "
                              f"{vf.situacao.nome}",
                "composição dos momentos dentro da envoltória de MRd, obtida "
                "do equilíbrio da seção",
                f"MSd = {vf.MSd / 100:.1f} kN·m contra MRd = "
                f"{vf.MRd_envoltoria / 100:.1f} kN·m na mesma direção "
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
        "rho >= 0,15 nu fcd/fyd >= 0,4 %",
        f"rho = {rho * 100:.3f} % contra rho,min = {rho_min * 100:.3f} %",
        _sit(rho >= rho_min - 1e-9)))
    v.append(Verificacao(
        "17.3.5.3.2", "Taxa máxima de armadura longitudinal",
        f"rho <= {RHO_MAXIMO * 100:g} %, incluída a emenda",
        f"rho = {rho * 100:.3f} % (na emenda, {rho * 200:.3f} %)",
        _sit(rho <= RHO_MAXIMO + 1e-9)))
    v.append(Verificacao(
        "18.4.2.1", "Bitola da armadura longitudinal",
        f"10 mm <= ø <= 1/8 da menor dimensão "
        f"({arr_mod.bitola_maxima(p.secao):.1f} mm)",
        f"ø = {a.phi:g} mm", _sit(10.0 <= a.phi
                                  <= arr_mod.bitola_maxima(p.secao) + 1e-9)))
    s_min = arr_mod.espacamento_livre_minimo(a.phi, p.ambiente.dmax_agregado)
    v.append(Verificacao(
        "18.4.2.2", "Espaçamento livre entre barras longitudinais",
        f"s >= max(2 cm; ø; 1,2 d_max) = {s_min:.1f} cm",
        f"s = {a.espacamento_livre:.1f} cm",
        _sit(a.espacamento_livre >= s_min - 1e-6)))
    s_max = arr_mod.espacamento_eixos_maximo(p.secao)
    v.append(Verificacao(
        "18.4.2.2", "Espaçamento entre eixos de barras",
        f"s <= min(2 . menor dimensão; 40 cm) = {s_max:.1f} cm",
        f"s = {a.espacamento_eixos:.1f} cm",
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
            f"ø_t >= max(5 mm; ø_l/4) = "
            f"{est_mod.bitola_minima(a.phi):.2f} mm",
            f"ø_t = {e.phi:g} mm",
            _sit(e.phi >= est_mod.bitola_minima(a.phi) - 1e-9)))
        v.append(Verificacao(
            "18.4.3", "Espaçamento longitudinal dos estribos",
            f"s <= min(20 cm; menor dimensão; 12 ø_l) = {e.s_maximo:.1f} cm "
            f"(governa: {e.motivo_s})",
            f"s = {e.s:g} cm", _sit(e.s <= e.s_maximo + 1e-9)))
        v.append(Verificacao(
            "18.2.4", "Proteção contra flambagem das barras",
            f"barras a mais de 20 ø_t = {e.alcance:.1f} cm do canto, ou "
            f"além de duas por trecho, exigem estribo suplementar",
            f"{e.n_suplementares} grampo(s) suplementar(es) por nível",
            ATENDIDO))
    anc = res.ancoragem
    if anc is not None:
        v.append(Verificacao(
            "9.5.2.3", "Comprimento de espera das barras longitudinais",
            "l0c = lb As,calc/As,ef >= max(0,6 lb; 15 ø; 20 cm)",
            f"lb = {anc.lb:.0f} cm; l0c = {anc.l0c:.0f} cm "
            f"(piso {anc.l0c_min:.0f} cm)", ATENDIDO))


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
            f"gamma_c = {p.concreto.gamma_c:.2f}; "
            f"gamma_s = {p.aco.gamma_s:.2f}", ATENDIDO))
    else:
        v.append(Verificacao(
            "Tabela 12.1", "Coeficientes de ponderação das resistências",
            "impostos pelo projetista",
            f"gamma_c = {p.concreto.gamma_c:.2f}; "
            f"gamma_s = {p.aco.gamma_s:.2f}", INFORMATIVO))
    v.append(Verificacao(
        "17.2.5", "Expoente da expressão de interação",
        "1,2 em seção retangular; 1,0 nas demais",
        f"alfa = {p.alfa_interacao:g}"
        + (" (adotado pelo programa)" if p.alfa_automatico
           else " (imposto pelo projetista)"), INFORMATIVO))
    if cfg.considerar_fluencia:
        origem = ("Tabela 8.1, por interpolação"
                  if cfg.phi_fluencia <= 0 else "imposto pelo projetista")
        v.append(Verificacao(
            "Tabela 8.1", "Coeficiente de fluência",
            f"umidade {cfg.umidade_ambiente:g} %, 2Ac/u = "
            f"{p.espessura_ficticia:.1f} cm, t0 = "
            f"{cfg.idade_carregamento:g} dias",
            f"phi = {p.phi_fluencia:.2f} ({origem})", ATENDIDO))


def _omissoes(res: ResultadoPilar, v: list[Verificacao]) -> None:
    """As verificações que este programa **não** faz, ditas por extenso."""
    p = res.pilar
    v.append(Verificacao(
        "15.7 / 15.6", "Efeitos globais de 2ª ordem",
        "parâmetro alfa ou coeficiente gamma_z da estrutura",
        "fora do escopo: o programa calcula um lance isolado e recebe os "
        "esforços de 1ª ordem já apurados no modelo global",
        NAO_VERIFICADO))
    v.append(Verificacao(
        "11.3.3.4.1", "Imperfeições geométricas globais (desaprumo)",
        "theta_a = 1/(100 sqrt(H))",
        "fora do escopo: entra nos esforços do modelo global",
        NAO_VERIFICADO))
    v.append(Verificacao(
        "16.2.3", "Combinações de ações",
        "combinação última normal com gamma_f e psi",
        f"fora do escopo: os esforços de entrada são tomados como de "
        f"cálculo (gamma_f de entrada = {p.config.gamma_f:g})",
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
            f"VSd <= VRd2 = 0,27 alfa_v2 fcd bw d = {c.VRd2:.1f} kN",
            f"VSd = {c.Vd:.1f} kN ({c.razao_biela * 100:.0f} % de VRd2)",
            ATENDIDO if c.razao_biela <= 1.0 + 1e-6 else NAO_ATENDIDO))
        v.append(Verificacao(
            "17.4.2.2-b", f"Tração diagonal, direção {direcao}",
            f"VSd <= Vc + Vsw = {c.Vc:.1f} + {c.Vsw:.1f} = {c.VRd3:.1f} kN",
            f"VSd = {c.Vd:.1f} kN ({c.razao_tracao * 100:.0f} % de VRd3)",
            ATENDIDO if c.razao_tracao <= 1.0 + 1e-6 else NAO_ATENDIDO))
        v.append(Verificacao(
            "17.4.1.1.2-c", f"Armadura mínima de cisalhamento, direção "
                            f"{direcao}",
            f"dispensada se VSd <= Vc e a tração em estádio I <= fctk = "
            f"{c.fctk:.2f} MPa",
            (f"dispensada: VSd = {c.Vd:.1f} kN <= Vc = {c.Vc:.1f} kN e "
             f"tração = {c.tracao_estadio_1:.2f} MPa"
             if c.dispensa_minima else
             f"exigida: VSd = {c.Vd:.1f} kN, Vc = {c.Vc:.1f} kN, tração = "
             f"{c.tracao_estadio_1:.2f} MPa"),
            ATENDIDO))
        if not c.dispensa_minima:
            v.append(Verificacao(
                "18.3.3.2", f"Espaçamento do estribo pela cortante, direção "
                            f"{direcao}",
                f"s <= {c.s_maximo:.1f} cm",
                f"s = {c.s:g} cm",
                ATENDIDO if c.s <= c.s_maximo + 1e-9 else NAO_ATENDIDO))
    v.append(Verificacao(
        "17.4.2.3 / 17.5", "Modelo II e torção",
        "bielas de inclinação variável; torção e sua interação com a cortante",
        "não verificado: a cortante é verificada pelo modelo I, que é o mais "
        "conservador dos dois; torção fica fora do escopo",
        NAO_VERIFICADO))
    v.append(Verificacao(
        "23", "Fadiga",
        "variação de tensão sob carga cíclica",
        "não verificado: pilar de edifício corrente não é peça de fadiga. Em "
        "pilar de ponte ou de estrutura de máquina, verifique à parte",
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


def resumo(verificacoes: list[Verificacao]) -> dict[str, int]:
    """Contagem por situação, para o quadro-resumo da memória."""
    saida: dict[str, int] = {}
    for v in verificacoes:
        chave = v.situacao if v.situacao in (
            ATENDIDO, NAO_ATENDIDO, DISPENSADO, NAO_VERIFICADO,
            INFORMATIVO) else NAO_ATENDIDO
        saida[chave] = saida.get(chave, 0) + 1
    return saida
