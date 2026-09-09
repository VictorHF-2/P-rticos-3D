# -*- coding: utf-8 -*-
"""
nbr6123_core.py
Motor de cálculo da ABNT NBR 6123:2023 (Seções 4, 5 e 6).
Funções puras, sem dependência de interface gráfica.
"""
import math
import nbr6123_data as D


# ===========================================================================
# Utilidades de interpolação
# ===========================================================================
def _interp_linear(x, x0, x1, y0, y1):
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def interp1d(x, xs, ys):
    """Interpolação linear 1D com clamp nos extremos. xs crescente."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            return _interp_linear(x, xs[i], xs[i + 1], ys[i], ys[i + 1])
    return ys[-1]


def interp2d(x, y, xs, ys, grid):
    """
    Interpolação bilinear com clamp. grid[i][j] no ponto (ys[i], xs[j]).
    Retorna (valor, extrapolado_bool).
    """
    extrap = x < xs[0] or x > xs[-1] or y < ys[0] or y > ys[-1]
    xc = min(max(x, xs[0]), xs[-1])
    yc = min(max(y, ys[0]), ys[-1])
    # índice em x
    jx = 0
    for j in range(len(xs) - 1):
        if xs[j] <= xc <= xs[j + 1]:
            jx = j
            break
    else:
        jx = len(xs) - 2
    iy = 0
    for i in range(len(ys) - 1):
        if ys[i] <= yc <= ys[i + 1]:
            iy = i
            break
    else:
        iy = len(ys) - 2
    x0, x1 = xs[jx], xs[jx + 1]
    y0, y1 = ys[iy], ys[iy + 1]
    q11 = grid[iy][jx]
    q12 = grid[iy][jx + 1]
    q21 = grid[iy + 1][jx]
    q22 = grid[iy + 1][jx + 1]
    r1 = _interp_linear(xc, x0, x1, q11, q12)
    r2 = _interp_linear(xc, x0, x1, q21, q22)
    val = _interp_linear(yc, y0, y1, r1, r2)
    return val, extrap


# ===========================================================================
# 5.2 - Fator topográfico S1
# ===========================================================================
def calc_s1_plano():
    return 1.0


def calc_s1_vale():
    return 0.9


def calc_s1_talude(theta_t_graus, z, dt):
    """
    Ponto B de talude/morro (5.2-b). Interpola linearmente para
    3° < theta_t < 6° e 17° < theta_t < 45°.
    z: altura acima da superfície; dt: desnível base-topo.
    """
    if dt <= 0:
        raise ValueError("dt (desnível) deve ser > 0.")
    t = theta_t_graus
    razao = z / dt

    def s1_6a17(tt):
        return 1.0 + (2.5 - razao) * math.tan(math.radians(tt - 3.0))

    def s1_45():
        return 1.0 + (2.5 - razao) * 0.31

    if t <= 3.0:
        s1 = 1.0
    elif t < 6.0:
        # interpola entre theta=3 (S1=1,0) e theta=6 (fórmula 6-17 em t=6)
        s1 = _interp_linear(t, 3.0, 6.0, 1.0, s1_6a17(6.0))
    elif t <= 17.0:
        s1 = s1_6a17(t)
    elif t < 45.0:
        # interpola entre theta=17 (fórmula 6-17) e theta=45 (fórmula 45)
        s1 = _interp_linear(t, 17.0, 45.0, s1_6a17(17.0), s1_45())
    else:
        s1 = s1_45()
    return max(s1, 1.0)


# ===========================================================================
# 5.3 - Fator S2
# ===========================================================================
def classe_por_dimensao(maior_dimensao_m):
    """Classe A/B/C a partir da maior dimensão da superfície frontal (m)."""
    if maior_dimensao_m <= 20.0:
        return "A"
    elif maior_dimensao_m <= 50.0:
        return "B"
    return "C"


def calc_s2(categoria, classe, z):
    """
    S2 = bm * Fr * (z/10)^p  (eq. 5.3.3).
    Constante até 10 m para categoria V (recomendação da norma 5.3.3).
    """
    if categoria not in D.TAB1_PARAMETROS:
        raise ValueError("Categoria inválida.")
    if classe not in D.CLASSES:
        raise ValueError("Classe inválida.")
    par = D.TAB1_PARAMETROS[categoria]
    bm, p = par[classe]
    fr = D.TAB2_FR[classe]
    z_calc = z
    if categoria == "V" and z < 10.0:
        z_calc = 10.0
    return bm * fr * (z_calc / 10.0) ** p


def perfil_s2(categoria, classe, z_topo, passo=None, alturas=None):
    """Lista de (z, S2) do solo ao topo."""
    if alturas is None:
        if passo is None:
            passo = max(1.0, round(z_topo / 15.0, 1))
        alturas = []
        z = passo
        while z < z_topo - 1e-9:
            alturas.append(round(z, 3))
            z += passo
        alturas.append(round(z_topo, 3))
    return [(z, calc_s2(categoria, classe, z)) for z in alturas]


# ===========================================================================
# 5.4 - Fator estatístico S3
# ===========================================================================
def calc_s3(grupo, vedacao=False):
    s3, tp, _ = D.TAB4_S3[str(grupo)]
    if vedacao:
        return s3 * D.S3_VEDACAO_FATOR
    return s3


# ===========================================================================
# 4.2 / 5 - Velocidade característica e pressão dinâmica
# ===========================================================================
def calc_vk(v0, s1, s2, s3):
    """Vk = V0 * S1 * S2 * S3  (m/s)."""
    return v0 * s1 * s2 * s3


def calc_q(vk):
    """q = 0,613 * Vk^2  (N/m2)."""
    return D.Q_COEF * vk ** 2


def calc_forca(q, C, A, fv=1.0):
    """F = q * C * A * fv  (N).  q em N/m2, A em m2."""
    return q * C * A * fv


# ===========================================================================
# 6.1.1 - Tabela 6 (paredes)
# ===========================================================================
def _banda_hb(hb):
    if hb <= 0.5:
        return "hb<=0.5"
    elif hb <= 1.5:
        return "hb_0.5_1.5"
    return "hb_1.5_6"


def coef_paredes(a, b, h):
    """
    Coeficientes de forma/pressão externos para paredes (Tabela 6).
    a, b: dimensões em planta (b = menor); h: altura.
    Retorna dict com zonas (0° e 90°), cpe_medio, A3/B3, e metadados.
    Interpola em a/b entre 3/2 e 2 (Nota 2).
    """
    if b > a:
        a, b = b, a  # garante b = menor dimensão
    if b <= 0 or h <= 0:
        raise ValueError("Dimensões devem ser positivas.")
    hb = h / b
    ab = a / b
    banda_h = _banda_hb(hb)
    avisos = []
    if hb > 6.0:
        avisos.append("h/b > 6: fora do intervalo da Tabela 6 (valores da faixa 3/2<h/b≤6 usados).")
    if ab > 4.0:
        avisos.append("a/b > 4: fora do intervalo da Tabela 6 (valores da faixa 2≤a/b≤4 usados).")

    baixa = D.TAB6_PAREDES[(banda_h, "ab_1_1.5")]
    alta = D.TAB6_PAREDES[(banda_h, "ab_2_4")]

    # fator de interpolação em a/b: <=1.5 usa baixa; >=2 usa alta; entre interpola
    if ab <= 1.5:
        f = 0.0
    elif ab >= 2.0:
        f = 1.0
    else:
        f = (ab - 1.5) / (2.0 - 1.5)

    zonas = {}
    for k in baixa:
        zonas[k] = round(baixa[k] + f * (alta[k] - baixa[k]), 3)

    # A3/B3 (Nota 3) para vento 0°: a/b=1 -> igual A2/B2; a/b>=2 -> -0.2; interpola
    a2b2 = zonas["A2B2"]
    if ab <= 1.0:
        a3b3 = a2b2
    elif ab >= 2.0:
        a3b3 = -0.2
    else:
        a3b3 = _interp_linear(ab, 1.0, 2.0, a2b2, -0.2)
    zonas["A3B3"] = round(a3b3, 3)

    return {
        "a": a, "b": b, "h": h, "h_b": hb, "a_b": ab,
        "banda_h": banda_h, "zonas": zonas, "avisos": avisos,
        "largura_cpe": min(0.2 * b, h),  # faixa de barlavento (Nota 4)
    }


# ===========================================================================
# 6.1.1 - Tabela 7 (telhado duas águas)
# ===========================================================================
def coef_telhado_duas_aguas(b, h, theta):
    """
    Coeficientes de forma/pressão externos para telhado 2 águas simétrico
    (Tabela 7). b = menor dimensão em planta; h = altura (detalhe I);
    theta = inclinação do telhado (graus). Interpola em theta.
    """
    if b <= 0 or h <= 0:
        raise ValueError("Dimensões devem ser positivas.")
    hb = h / b
    banda = _banda_hb(hb)
    linhas = D.TAB7_TELHADO[banda]
    thetas = [ln[0] for ln in linhas]
    avisos = []
    if theta < thetas[0] or theta > thetas[-1]:
        avisos.append(f"θ fora do intervalo tabelado ({thetas[0]}°–{thetas[-1]}°); "
                      "valor extrapolado por clamp.")

    def col(idx):
        ys = [ln[idx] for ln in linhas]
        # ignora None: usa interpolação apenas entre valores definidos vizinhos
        xs2, ys2 = [], []
        for t, v in zip(thetas, ys):
            if v is not None:
                xs2.append(t); ys2.append(v)
        if not ys2:
            return None
        return round(interp1d(theta, xs2, ys2), 3)

    res = {}
    for i, nome in enumerate(D.TAB7_COLUNAS):
        res[nome] = col(i + 1)
    return {
        "b": b, "h": h, "h_b": hb, "theta": theta,
        "banda_h": banda, "coef": res, "avisos": avisos,
    }


# ===========================================================================
# 6.1.2 - Coeficiente de arrasto Ca (Figuras 4 e 5)
# ===========================================================================
def coef_arrasto(l1, l2, h, alta_turbulencia=False):
    """
    Coeficiente de arrasto Ca para edificação paralelepipédica.
    l1 = largura, dimensão horizontal PERPENDICULAR ao vento (a fachada
    atingida pelo vento); l2 = profundidade, dimensão horizontal NA DIREÇÃO
    do vento; h = altura (NBR 6123:2023, item 3.2).
    Usa Figura 5 (alta turbulência) ou Figura 4 (baixa).
    Retorna (Ca, l1/l2, h/l1, extrapolado_bool).
    Valores lidos de digitalização aproximada do ábaco - CONFERIR no gráfico.
    """
    if l1 <= 0 or l2 <= 0 or h <= 0:
        raise ValueError("Dimensões devem ser positivas.")
    x = l1 / l2
    y = h / l1
    if alta_turbulencia:
        ca, extrap = interp2d(x, y, D.CA_X, D.CA_FIG5_Y, D.CA_FIG5)
    else:
        ca, extrap = interp2d(x, y, D.CA_X, D.CA_FIG4_Y, D.CA_FIG4)
    return round(ca, 3), x, y, extrap


def criterio_alta_turbulencia(h, l1_planta_maior):
    """
    6.1.3: uma edificação pode ser considerada em vento de alta turbulência
    quando sua altura não excede duas vezes a altura média das edificações
    vizinhas... (critério simplificado: h <= 1,8 * altura média vizinhança).
    Aqui apenas retornamos texto orientativo (decisão do projetista).
    """
    return ("Vento de alta turbulência (Fig. 5) pode ser adotado se a altura da "
            "edificação não exceder 1,8 vez a altura média das edificações "
            "vizinhas, dentro dos limites de 6.1.3. Caso contrário, use Fig. 4.")


# ===========================================================================
# 6.3 - Coeficiente de pressão interna cpi (método simplificado)
# ===========================================================================
def cpi_duas_faces(vento_para_permeavel=True):
    return D.CPI_2FACES["perp_permeavel"] if vento_para_permeavel else D.CPI_2FACES["perp_impermeavel"]


def cpi_quatro_faces():
    """Retorna os dois valores; usar o mais nocivo no dimensionamento."""
    return D.CPI_4FACES


def cpi_dominante_barlavento(razao_areas):
    """Abertura dominante na face de barlavento (razão barlavento/total)."""
    xs = [p[0] for p in D.CPI_DOMINANTE_BARLAVENTO]
    ys = [p[1] for p in D.CPI_DOMINANTE_BARLAVENTO]
    return round(interp1d(razao_areas, xs, ys), 3)


def cpi_dominante_alta_succao(razao_areas):
    """Abertura dominante em zona de alta sucção externa."""
    xs = [p[0] for p in D.CPI_DOMINANTE_ALTA_SUCCAO]
    ys = [p[1] for p in D.CPI_DOMINANTE_ALTA_SUCCAO]
    return round(interp1d(razao_areas, xs, ys), 3)


def cpi_estanque():
    return D.CPI_ESTANQUE


def pressao_efetiva(cpe, cpi, q):
    """
    Δp = Δpe - Δpi = (cpe - cpi) * q   (N/m2).
    Convenção: pressão positiva = sobrepressão (empurra a superfície para dentro).
    """
    dpe = cpe * q
    dpi = cpi * q
    return dpe - dpi, dpe, dpi


# ===========================================================================
# Reynolds (6.2) - auxiliar informativo
# ===========================================================================
def reynolds(vk, dim):
    """Re = 70000 * Vk * dim  (dim em m)."""
    return 70000.0 * vk * dim


# ===========================================================================
# Anexo A - S2 generalizado (qualquer categoria, altura z e intervalo t)
# ===========================================================================
def calc_s2_generalizado(categoria, z, t):
    """
    S2 = bm(t) * Fr(t) * (z/10)^p(t)  (Anexo A, eq. A.1/A.2), com bm, p e Fr
    interpolados em log10(t) a partir da Tabela A.1 (t entre 3 s e 3600 s).
    Equivale à Tabela A.2 mas válido para qualquer t (não só 3/5/10 s).
    """
    if categoria not in D.ANEXO_A_TAB1:
        raise ValueError("Categoria inválida.")
    if t <= 0 or z <= 0:
        raise ValueError("t e z devem ser positivos.")
    ts = D.ANEXO_A_T
    logt = math.log10(min(max(t, ts[0]), ts[-1]))
    logts = [math.log10(x) for x in ts]
    par = D.ANEXO_A_TAB1[categoria]
    bm = interp1d(logt, logts, par["bm"])
    p = interp1d(logt, logts, par["p"])
    fr = interp1d(logt, logts, D.ANEXO_A_FR)
    return bm * fr * (z / 10.0) ** p


def calc_t_edificacao(v0, s1, categoria, h_topo, lt, t_inicial=600.0, tol=1e-3, max_iter=50):
    """
    Anexo A.2: t = 7,5*Lt / Vt(h), com Vt(h) = S1*S2(t)*V0 no topo da
    edificação. Resolvido por aproximações sucessivas (recomendado pela norma).
    Retorna (t, Vt_h).
    """
    if lt <= 0:
        raise ValueError("Lt deve ser > 0.")
    t = t_inicial
    for _ in range(max_iter):
        s2 = calc_s2_generalizado(categoria, h_topo, t)
        vt = s1 * s2 * v0
        if vt <= 0:
            break
        t_novo = 7.5 * lt / vt
        if abs(t_novo - t) < tol:
            t = t_novo
            break
        t = t_novo
    return t, vt


# ===========================================================================
# Anexo B - Fator estatístico S3 (probabilidade Pm, vida útil ma)
# ===========================================================================
def calc_s3_anexo_b(pm, ma):
    """S3 = 0,54 * [-ln(1-Pm)/ma]^(-0,157)  (Anexo B)."""
    if not (0.0 < pm < 1.0):
        raise ValueError("Pm deve estar entre 0 e 1 (exclusive).")
    if ma <= 0:
        raise ValueError("ma (vida útil) deve ser > 0.")
    return 0.54 * (-math.log(1.0 - pm) / ma) ** (-0.157)


# ===========================================================================
# Seção 8.1.1 - Tabela 26 (Cx, Cy para barras prismáticas de faces planas)
# ===========================================================================
def coef_barra_prismatica(shape_key, alpha):
    """Cx, Cy por interpolação linear em alpha (Tabela 26)."""
    if shape_key not in D.TAB26_BARRAS:
        raise ValueError("Forma de barra inválida.")
    dados = D.TAB26_BARRAS[shape_key]
    xs, cxs, cys = [], [], []
    for a, cx, cy in zip(D.TAB26_ALPHAS, dados["Cx"], dados["Cy"]):
        if cx is not None:
            xs.append(a)
            cxs.append(cx)
            cys.append(cy)
    cx = interp1d(alpha, xs, cxs)
    cy = interp1d(alpha, xs, cys)
    return round(cx, 3), round(cy, 3)


def forca_barra_prismatica(cx, cy, q, k, comprimento, c):
    """Fx = Cx*q*K*l*c ;  Fy = Cy*q*K*l*c   (8.1.1)."""
    fx = cx * q * k * comprimento * c
    fy = cy * q * k * comprimento * c
    return fx, fy


# ===========================================================================
# Seção 8.1.2 - Tabela 27 (Ca para barras prismáticas de seção circular)
# ===========================================================================
def coef_arrasto_circular(re):
    """Ca em função de Re = 70000*Vk*d (Tabela 27)."""
    for limite, ca, _desc in D.TAB27_CA_CIRCULAR:
        if re < limite:
            return ca
    return D.TAB27_CA_CIRCULAR[-1][1]


# ===========================================================================
# Seção 8.1.3 - Tabela 28 (fator de redução K para barras de compr. finito)
# ===========================================================================
def fator_k_reducao(l_sobre_c, regime="faces_planas"):
    """K em função de l/c (ou l/d) e do regime (Tabela 28)."""
    if regime not in D.TAB28_K:
        raise ValueError("Regime inválido.")
    return round(interp1d(l_sobre_c, D.TAB28_L_C, D.TAB28_K[regime]), 3)


# ===========================================================================
# Seção 8.2 - Tabela 29 (Ca para fios e cabos, l/d > 60)
# ===========================================================================
def coef_arrasto_cabo(re, tipo):
    """Ca interpolado (log Re) entre os dois pontos tabelados (Tabela 29)."""
    if tipo not in D.TAB29_CA_CABOS:
        raise ValueError("Tipo de cabo inválido.")
    t = D.TAB29_CA_CABOS[tipo]
    lo, hi = math.log10(t["re_lo"]), math.log10(t["re_hi"])
    logre = math.log10(max(re, 1.0))
    return round(interp1d(logre, [min(lo, hi), max(lo, hi)],
                          [t["ca_lo"], t["ca_hi"]] if lo <= hi else [t["ca_hi"], t["ca_lo"]]), 3)


def forca_cabo(ca, q, comprimento, d, alpha_graus=90.0):
    """
    Fa = Ca*q*l*d (vento perpendicular). Para vento a ângulo alpha com a
    corda do cabo: Fy = Fa*sen²(alpha) (8.2); Fx (na corda) desprezível.
    """
    fa = ca * q * comprimento * d
    fy = fa * math.sin(math.radians(alpha_graus)) ** 2
    return fa, fy


# ===========================================================================
# Seção 9.2 - Velocidade de projeto para análise dinâmica
# ===========================================================================
def calc_vp(v0, s1, s3):
    """Vp = 0,69 * V0 * S1 * S3  (média 10 min a 10 m, Categoria II)."""
    return 0.69 * v0 * s1 * s3


# ===========================================================================
# Seção 9.3.1 - Tabela 31 (parâmetros dinâmicos por tipo de edificação)
# ===========================================================================
def freq_fundamental(tipo, h):
    """f1 = 1/T1(h) usando a fórmula da Tabela 31 (quando disponível)."""
    if tipo not in D.TAB31_DINAMICA:
        raise ValueError("Tipo de edificação inválido.")
    fT1 = D.TAB31_DINAMICA[tipo]["T1"]
    if fT1 is None:
        raise ValueError("Tabela 31 não fornece fórmula de T1 para este tipo; informe f1 diretamente.")
    t1 = fT1(h)
    if t1 <= 0:
        raise ValueError("T1 calculado não positivo — verifique a altura h.")
    return 1.0 / t1


# ===========================================================================
# Seção 9.3.2 - q(z): pressão dinâmica com resposta flutuante (modelo contínuo)
# ===========================================================================
def calc_q_dinamico(categoria, q0_barra, h, z, gamma, zeta_pct_nao_usado, xi):
    """
    q(z) = q0_barra * bm² * [ (z/zr)^(2p) + (h/zr)^p * (z/h)^gamma *
                               (1+2*gamma)/(1+gamma+p) * xi ]
    q0_barra = 0,613 * Vp²  (N/m²);  zr = 10 m;  xi = fator dinâmico (Fig. 20-24).
    """
    if categoria not in D.TAB32_P_BM:
        raise ValueError("Categoria inválida.")
    par = D.TAB32_P_BM[categoria]
    p, bm = par["p"], par["bm"]
    zr = 10.0
    termo_medio = (z / zr) ** (2 * p)
    termo_flutuante = (h / zr) ** p * (z / h) ** gamma * (1 + 2 * gamma) / (1 + gamma + p) * xi
    return q0_barra * bm ** 2 * (termo_medio + termo_flutuante)


def q0_barra(vp):
    """q0_barra = 0,613 * Vp²  (N/m²; Vp em m/s)."""
    return 0.613 * vp ** 2


# ===========================================================================
# Seção 10.2/10.3 - Critério de dispensa e velocidade crítica de vórtices
# ===========================================================================
def calc_vcr_vortice(fn, dim_l, st):
    """Vcr = fn*L / St  (10.3)."""
    if st <= 0:
        raise ValueError("St deve ser > 0.")
    return fn * dim_l / st


def strouhal_retangulo(l2_sobre_l1):
    return interp1d(l2_sobre_l1, D.TAB33_STROUHAL["retangulo"]["x"],
                    D.TAB33_STROUHAL["retangulo"]["St"])


def dispensa_vortice(vcr, v0, s1, s2_600, s3, fator=1.25):
    """
    Critério de dispensa: verificação NÃO é necessária se
    Vcr > fator*V0*S1*S2(t=600s)*S3.
    fator = 1,25 (vórtices/vórtices em pontes) ou 2,0 (flutter/divergência
    torcional) ou 1,25 (galope) — ver 10.2 e 11.5.3 a 11.5.6.
    Retorna (dispensado: bool, limite: float).
    """
    limite = fator * v0 * s1 * s2_600 * s3
    return vcr > limite, limite


# ===========================================================================
# Seção 10.4 - Resposta dinâmica de estruturas esbeltas de seção circular
# ===========================================================================
def tabela34_c_ka0(re, vcr):
    """Retorna (C, Ka0) conforme Tabela 34, em função de Re e Vcr (m/s)."""
    baixa = vcr < 11.0
    if re < 2e5:
        t = D.TAB34["Re<2e5"]
        c = t["C_baixa"] if baixa else t["C_alta"]
        ka0 = t["Ka0_baixa"] if baixa else t["Ka0_alta"]
    elif re <= 1e6:
        logre = math.log10(re)
        c = (0.1840 - 0.0286 * logre) if baixa else (0.0867 - 0.0135 * logre)
        t = D.TAB34["2e5<=Re<=1e6"]
        ka0 = t["Ka0_baixa"] if baixa else t["Ka0_alta"]
    else:
        t = D.TAB34["Re>1e6"]
        c = t["C_baixa"] if baixa else t["C_alta"]
        ka0 = t["Ka0_baixa"] if baixa else t["Ka0_alta"]
    return round(c, 4), ka0


def parametro_k_vortice(mm, zeta, d0, ka0, rho=1.226):
    """K = mm*zeta / (rho*d0²*Ka0)  (10.4)."""
    return (mm * zeta) / (rho * d0 ** 2 * ka0)


def sigma_y_sobre_d0(k, alpha_l, c, rho, d0, mm, h, ka0, st):
    """
    Desvio-padrão do deslocamento no topo (10.4), fórmula geral válida para
    qualquer K; simplificações (K<=0,95 e K>1,05) aplicadas automaticamente
    dentro da tolerância indicada pela norma.
    """
    if k <= 0.95:
        return math.sqrt(alpha_l ** 2 * (1 - k))
    if k > 1.05:
        return math.sqrt((c ** 2 * rho * d0 ** 3) / (mm * h * ka0 * st ** 4 * (k - 1)))
    termo1 = (alpha_l ** 2 / 2.0) * (1 - k)
    termo2 = math.sqrt((alpha_l ** 4 / 4.0) * (1 - k) ** 2 +
                       (alpha_l ** 2 * c ** 2 * rho * d0 ** 3) / (mm * h * ka0 * st ** 4))
    return math.sqrt(termo1 + termo2)


def fator_pico_gy(k):
    """gy = 1,4 + 1,6*arctan(0,75*K^4)  (10.4)."""
    return 1.4 + 1.6 * math.atan(0.75 * k ** 4)


def numero_scruton(me, zeta, l1, rho=1.226):
    """Sc = 4*pi*me*zeta / (rho*l1²)  (10.5). Sc < 20: provável vibração de grande amplitude."""
    return (4 * math.pi * me * zeta) / (rho * l1 ** 2)


# ===========================================================================
# Seção 11.2.2 - Parâmetro de susceptibilidade à excitação aerodinâmica Pae
# ===========================================================================
def calc_vae_barra(v0, s1, s3, categoria, z):
    """Vae = 0,65*V0*S1*S3*bm*(z/10)^p  (Tabela 35)."""
    if categoria not in D.TAB35_PAE:
        raise ValueError("Categoria inválida.")
    par = D.TAB35_PAE[categoria]
    return 0.65 * v0 * s1 * s3 * par["bm"] * (z / 10.0) ** par["p"]

def calc_pae(b, m, vae, lp, fv, rho=1.226):
    """Pae = (rho*B²/m) * (16*Vae² / (B*Lp*fv²))  (11.2.2)."""
    if m <= 0 or lp <= 0 or fv <= 0 or b <= 0:
        raise ValueError("B, m, Lp e fv devem ser positivos.")
    return (rho * b ** 2 / m) * (16.0 * vae ** 2 / (b * lp * fv ** 2))


def classificar_ponte_pae(pae):
    """Classe 1 (Pae<0,04): dispensa; Classe 2 (0,04-1,0): avaliar; Classe 3 (>1,0): muito susceptível."""
    if pae < 0.04:
        return 1, "Classe 1: Pae < 0,04 — efeitos dinâmicos podem ser desconsiderados."
    if pae <= 1.0:
        return 2, "Classe 2: 0,04 ≤ Pae ≤ 1,0 — avaliar efeitos dinâmicos; análise aeroelástica se necessário."
    return 3, "Classe 3: Pae > 1,0 — ponte muito susceptível; análise aeroelástica requerida."


# ===========================================================================
# Seção 11.3 - Forças estáticas em tabuleiros de pontes (Classe 1)
# ===========================================================================
def cx_ponte(b, heq):
    """Cx = 0,21 + 1,9304*(B/Heq)^(-1,279)  (11.3.2)."""
    if heq <= 0:
        raise ValueError("Heq deve ser > 0.")
    return 0.21 + 1.9304 * (b / heq) ** (-1.279)


def cz_ponte(b, heq, sinal=1.0):
    """Cz = -0,0428*(B/Heq) ± 0,7472  (11.3.3). sinal=+1 (para cima) ou -1."""
    if heq <= 0:
        raise ValueError("Heq deve ser > 0.")
    return -0.0428 * (b / heq) + sinal * 0.7472


def fx_tabuleiro(cx, q, b):
    """Fx por unidade de comprimento = 1/2*rho*Vk²*B*Cx = q*B*Cx (q já com rho/2)."""
    return q * b * cx


def fz_tabuleiro(cz, q, b):
    return q * b * cz


def fy_tabuleiro(fx, faces_solidas=True):
    """Fy (atrito, direção do eixo) = 25% de Fx (faces sólidas) ou 50% (longarinas treliçadas)."""
    return fx * (0.25 if faces_solidas else 0.50)


# ===========================================================================
# Seção 11.5 - Critérios de estabilidade dinâmica do tabuleiro
# ===========================================================================
def limite_vortice_ponte(v0, s1, s2_600, s3):
    """Vcr > 1,25*V0*S1*S2(600s)*S3  (11.5.3-b / 10.2)."""
    return 1.25 * v0 * s1 * s2_600 * s3


def limite_flutter_ponte(v0, s1, s2_600, s3):
    """Vdiv > 2,0*V0*S1*S2(600s)*S3  (11.5.4, drapejamento/flutter)."""
    return 2.0 * v0 * s1 * s2_600 * s3


def limite_divergencia_torcional(v0, s1, s2_600, s3):
    """Vdiv > 2,0*V0*S1*S2(600s)*S3  (11.5.5, divergência torcional)."""
    return 2.0 * v0 * s1 * s2_600 * s3


def limite_galope(v0, s1, s2_600, s3):
    """Vcrit > 1,25*V0*S1*S2(600s)*S3  (11.5.6, galope)."""
    return 1.25 * v0 * s1 * s2_600 * s3


# ===========================================================================
# Seção 5.5 - Mudança de rugosidade do terreno
# ===========================================================================
def transicao_categoria_maior(z01, z02, x):
    """
    5.5.1 (z01<z02): retorna (zx, zi). Acima de zx usa-se S2 do terreno
    mais afastado (z01); abaixo de zi usa-se S2 do terreno próximo (z02);
    entre zi e zx, varia linearmente.
    """
    if not (z01 < z02):
        raise ValueError("Esta transição requer z01 < z02.")
    a = 0.63 - 0.03 * math.log(z02 / z01)
    zx = a * z02 * (x / z02) ** 0.8
    zi = 0.36 * z02 * (x / z02) ** 0.75
    return zx, zi


def transicao_categoria_menor(z01, z02, x):
    """
    5.5.2 (z01>z02): retorna zx. Acima de zx usa-se S2 do terreno mais
    afastado (z01); abaixo de zx usa-se S2 do terreno próximo (z02), sem
    ultrapassar o S2 do terreno z01 calculado em zx.
    """
    if not (z01 > z02):
        raise ValueError("Esta transição requer z01 > z02.")
    a = 0.73 - 0.03 * math.log(z01 / z02)
    zx = a * z02 * (x / z02) ** 0.8
    return zx


def s2_com_mudanca_rugosidade(cat01, cat02, classe, z, x):
    """
    S2 na altura z, a uma distância x a sotavento de uma mudança de
    rugosidade de categoria cat01 (terreno mais afastado/barlavento) para
    cat02 (terreno que circunda a edificação/sotavento).
    Retorna (s2, regime_txt).
    """
    z01 = D.TAB5_ZG_Z0[cat01]["z0"]
    z02 = D.TAB5_ZG_Z0[cat02]["z0"]
    if z01 < z02:
        zx, zi = transicao_categoria_maior(z01, z02, x)
        if z >= zx:
            return calc_s2(cat01, classe, z), f"z ≥ zx={zx:.1f} m: usa categoria {cat01} (mais afastada)"
        if z <= zi:
            return calc_s2(cat02, classe, z), f"z ≤ zi={zi:.1f} m: usa categoria {cat02} (mais próxima)"
        s2_i = calc_s2(cat02, classe, zi)
        s2_x = calc_s2(cat01, classe, zx)
        s2 = _interp_linear(z, zi, zx, s2_i, s2_x)
        return s2, f"zi={zi:.1f} m < z < zx={zx:.1f} m: interpolação linear"
    elif z01 > z02:
        zx = transicao_categoria_menor(z01, z02, x)
        if z >= zx:
            return calc_s2(cat01, classe, z), f"z ≥ zx={zx:.1f} m: usa categoria {cat01} (mais afastada)"
        s2_z02 = calc_s2(cat02, classe, z)
        s2_lim = calc_s2(cat01, classe, zx)
        s2 = min(s2_z02, s2_lim)
        return s2, f"z < zx={zx:.1f} m: usa categoria {cat02}, limitado ao S2({cat01}) em zx"
    else:
        return calc_s2(cat01, classe, z), "z01 = z02: sem mudança de rugosidade"


# ===========================================================================
# Seção 6.2.1 - Tabela 13 (distribuição de pressão externa em cilindros)
# ===========================================================================
def coef_pressao_cilindro(beta_graus, h_d, superficie="lisa"):
    """
    cpe em torno de um cilindro (Tabela 13), interpolado em beta (0-180°).
    h_d: 10 ou <=2,5 (usa a coluna mais próxima; interpola linearmente
    entre as colunas h/d=2,5 e h/d=10 quando 2,5<h/d<10).
    superficie: "lisa" ou "rugosa".
    """
    beta = abs(beta_graus) % 360
    if beta > 180:
        beta = 360 - beta
    xs = D.TAB13_BETA
    idx = 0 if superficie == "rugosa" else 2
    ys_10 = [D.TAB13_CILINDRO[b][idx] for b in xs]
    ys_25 = [D.TAB13_CILINDRO[b][idx + 1] for b in xs]
    c10 = interp1d(beta, xs, ys_10)
    c25 = interp1d(beta, xs, ys_25)
    if h_d >= 10:
        return round(c10, 3)
    if h_d <= 2.5:
        return round(c25, 3)
    return round(_interp_linear(h_d, 2.5, 10, c25, c10), 3)


# ===========================================================================
# Seção 6.2.2 - Tabela 14 (Ca para corpos de seção constante)
# ===========================================================================
def coef_arrasto_secao_constante(forma, h_l1, re):
    """
    Ca para corpos de seção constante (Tabela 14), interpolado em h/l1 e,
    quando aplicável, em log(Re) entre as duas faixas tabeladas.
    re: número de Reynolds (adimensional, não em unidades de 1e5).
    """
    if forma not in D.TAB14_FORMAS:
        raise ValueError("Forma inválida.")
    faixas = D.TAB14_FORMAS[forma]["faixas"]
    xs = D.TAB14_H_L1
    if len(faixas) == 1:
        ca = interp1d(h_l1, xs, faixas[0][1])
        return round(ca, 3)
    (re_lo, lista_lo), (re_hi, lista_hi) = faixas
    ca_lo = interp1d(h_l1, xs, lista_lo)
    ca_hi = interp1d(h_l1, xs, lista_hi)
    re_1e5 = re / 1e5
    if re_1e5 <= re_lo:
        return round(ca_lo, 3)
    if re_1e5 >= re_hi:
        return round(ca_hi, 3)
    return round(interp1d(math.log10(re_1e5), [math.log10(re_lo), math.log10(re_hi)],
                          [ca_lo, ca_hi]), 3)


# ===========================================================================
# Seção 7.1 - Tabela 23 (muros e placas retangulares)
# ===========================================================================
def coef_forca_muro(condicao, l_ha):
    """
    Cf, alpha (ângulo crítico) e e (excentricidade, fração de l) para
    muros/placas (Tabela 23). condicao: "bidimensional", "apoiado_solo"
    ou "elevado_solo". l_ha: razão l/ha (comprimento/altura).
    """
    if condicao == "bidimensional":
        if l_ha >= 60:
            d = D.TAB23_MUROS[("bidimensional", "l_ha_60")]
        elif l_ha >= 10:
            d = D.TAB23_MUROS[("bidimensional", "l_ha_10")]
        else:
            d = D.TAB23_MUROS[("bidimensional", "l_ha_1")]
        return d["Cf"], d["alpha"], d["e"]
    # apoiado_solo / elevado_solo: Cf a 90° sempre; casos intermediários
    # (l/ha=10 e 1) também têm um Cf alternativo para vento oblíquo (50°/40°)
    chave = "l_ha_60" if l_ha >= 60 else ("l_ha_10" if l_ha >= 10 else "l_ha_1")
    d = D.TAB23_MUROS[(condicao, chave)]
    return d["Cf"], d["alpha"], d.get("e")


# ===========================================================================
# Seção 6.4.4 - Fator de vizinhança fv
# ===========================================================================
def dist_d_estrela(a, b):
    """d* = menor entre o lado menor b e a semidiagonal (Fig. 11)."""
    semidiag = 0.5 * math.sqrt(a ** 2 + b ** 2)
    return min(b, semidiag)


def fator_vizinhanca(s, d_estrela, caso="paredes"):
    """fv por interpolação linear entre os 2 pontos tabelados (6.4.4)."""
    if caso not in D.TAB_VIZINHANCA_FV:
        raise ValueError("Caso inválido (use 'paredes' ou 'cobertura').")
    par = D.TAB_VIZINHANCA_FV[caso]
    sd = s / d_estrela
    if sd <= par["s_d_baixo"]:
        return par["fv_baixo"]
    if sd >= par["s_d_alto"]:
        return par["fv_alto"]
    return round(_interp_linear(sd, par["s_d_baixo"], par["s_d_alto"],
                                par["fv_baixo"], par["fv_alto"]), 3)


# ===========================================================================
# Seção 6.3.3 - Pressão interna, método detalhado (solver iterativo)
# ===========================================================================
def cpi_metodo_detalhado(aberturas, tol=1e-5, max_iter=100):
    """
    Resolve sum(± Aj * sqrt(|Ce*_j - Ci*|)) = 0 para Ci* (6.3.3), por
    bisseção (a função é monótona decrescente em Ci*).
    aberturas: lista de (Aj, Ce_j). Retorna Ci* (equivalente a cpi).
    """
    if not aberturas:
        raise ValueError("Informe ao menos uma abertura.")
    ces = [ce for _, ce in aberturas]

    def f(ci):
        total = 0.0
        for aj, ce in aberturas:
            diff = ce - ci
            sinal = 1.0 if diff > 0 else (-1.0 if diff < 0 else 0.0)
            total += sinal * aj * math.sqrt(abs(diff))
        return total

    lo, hi = min(ces) - 1e-6, max(ces) + 1e-6
    flo, fhi = f(lo), f(hi)
    if flo == 0:
        return lo
    if fhi == 0:
        return hi
    if (flo > 0) == (fhi > 0):
        raise ValueError("Não foi possível isolar a raiz — verifique as áreas/Ce informados.")
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        fm = f(mid)
        if abs(fm) < tol or (hi - lo) < tol:
            return mid
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi, fhi = mid, fm
    return (lo + hi) / 2.0


# ===========================================================================
# Seção 6.1.1 - Tabelas 8 a 12 (telhados 1 água e múltiplos)
# ===========================================================================
def coef_telhado_uma_agua(theta):
    """Ce (10 colunas) e cpe médio (6 zonas) por interpolação em theta (Tabela 8)."""
    thetas = D.TAB8_THETAS
    ce_cols = list(zip(*[D.TAB8_CE[t] for t in thetas]))
    ce = {nome: round(interp1d(theta, thetas, vals), 3)
          for nome, vals in zip(D.TAB8_CE_COLS, ce_cols)}
    cpe_cols = list(zip(*[D.TAB8_CPE_MEDIO[t] for t in thetas]))
    cpe = {nome: round(interp1d(theta, thetas, vals), 3)
           for nome, vals in zip(D.TAB8_CPE_COLS, cpe_cols)}
    return ce, cpe


def coef_telhado_multiplo_simetrico(theta):
    """Zonas a*..z* (alpha=0°) por interpolação em theta (Tabela 10)."""
    thetas = sorted(D.TAB10_MULTIPLOS_SIMETRICOS.keys())
    cols = list(zip(*[D.TAB10_MULTIPLOS_SIMETRICOS[t] for t in thetas]))
    nomes = ["a*", "b*", "c*", "d*", "m*", "n*", "x*", "z*"]
    return {nome: round(interp1d(theta, thetas, vals), 3) for nome, vals in zip(nomes, cols)}


def coef_telhado_multiplo_assimetrico(alpha):
    """Zonas a*..z* para água menor a 60° (Tabela 11); alpha em {0,180}."""
    if alpha not in D.TAB11_MULTIPLOS_ASSIMETRICOS_60:
        alpha = 0 if alpha < 90 else 180
    nomes = ["a*", "b*", "c*", "d*", "m*", "n*", "x*", "z*"]
    vals = D.TAB11_MULTIPLOS_ASSIMETRICOS_60[alpha]
    return dict(zip(nomes, vals))


def coef_telhado_multiplo_uma_agua_vertical(theta, alpha):
    """Zonas a*..z* (Tabela 12); theta em {10,15,30}, alpha em {0,180}."""
    thetas = sorted(set(k[0] for k in D.TAB12_MULTIPLOS_UMA_AGUA))
    theta_prox = min(thetas, key=lambda t: abs(t - theta))
    alpha_c = 0 if alpha < 90 else 180
    nomes = ["a*", "b*", "c*", "d*", "m*", "n*", "x*", "z*"]
    vals = D.TAB12_MULTIPLOS_UMA_AGUA[(theta_prox, alpha_c)]
    return dict(zip(nomes, vals)), theta_prox


# ===========================================================================
# Seção 6.2.3 - Abóbadas cilíndricas (Tabelas 15 a 20)
# ===========================================================================
def coef_abobada_perpendicular_baixa(f_l2, h_l2):
    """Tabela 15 — busca a combinação mais próxima de (f/l2, h/l2)."""
    chaves = list(D.TAB15_ABOBADA_PERP.keys())
    f_chave = min(set(k[0] for k in chaves), key=lambda f: abs(_frac(f) - _frac(f_l2)))
    disponiveis = [k[1] for k in chaves if k[0] == f_chave]
    h_chave = min(disponiveis, key=lambda h: abs(_frac(h) - _frac(h_l2)))
    return D.TAB15_ABOBADA_PERP[(f_chave, h_chave)], f_chave, h_chave


def _frac(v):
    """Converte '1/5', '1/8' etc. (ou número) em float."""
    if isinstance(v, str):
        if "/" in v:
            num, den = v.split("/")
            return float(num) / float(den)
        return float(v)
    return float(v)


def coef_cupula_terreno(f_d):
    """Tabela 21 — interpola cpe (sobrepressão/sucção) e Cs por f/d."""
    chaves = list(D.TAB21_CUPULA_TERRENO.keys())
    xs = sorted(chaves, key=_frac)
    xs_num = [_frac(x) for x in xs]
    sobre = [D.TAB21_CUPULA_TERRENO[x][0] for x in xs]
    succ = [D.TAB21_CUPULA_TERRENO[x][1] for x in xs]
    cs = [D.TAB21_CUPULA_TERRENO[x][2] for x in xs]
    fd = _frac(f_d)
    return (round(interp1d(fd, xs_num, sobre), 3),
            round(interp1d(fd, xs_num, succ), 3),
            round(interp1d(fd, xs_num, cs), 3))


def forca_sustentacao_cupula(cs, q, d):
    """Fs = Cs * q * pi*d^2/4  (6.2.4.1)."""
    return cs * q * math.pi * d ** 2 / 4.0


def coef_cupula_parede(f_d, h_d):
    """Tabela 22 — busca a combinação mais próxima de (f/d, h/d)."""
    chaves = list(D.TAB22_CUPULA_PAREDE.keys())
    f_chave = min(set(k[0] for k in chaves), key=lambda f: abs(_frac(f) - _frac(f_d)))
    disponiveis = [k[1] for k in chaves if k[0] == f_chave]
    h_chave = min(disponiveis, key=lambda h: abs(_frac(h) - _frac(h_d)))
    return D.TAB22_CUPULA_PAREDE[(f_chave, h_chave)], f_chave, h_chave


# ===========================================================================
# Seção 7.2 - Coberturas isoladas a uma água (Tabela 24) e forças auxiliares
# ===========================================================================
def coef_cobertura_uma_agua(tg_theta, caso="carregamento1"):
    """
    Tabela 24: retorna (cp_borda_alta, cp_borda_baixa). Valores lineares
    em tg(theta); usar a média para a força global e os dois extremos
    para o gradiente ao longo de l2.
    """
    d = D.TAB24_UMA_AGUA[caso]
    sinal = d.get("sinal", 1)
    borda_alta = d["borda_alta"] if not isinstance(d["borda_alta"], str) else _eval_tgtheta(d["borda_alta"], tg_theta)
    borda_baixa = _eval_tgtheta(d["borda_baixa"], tg_theta) if isinstance(d["borda_baixa"], str) else d["borda_baixa"]
    return sinal * borda_alta, sinal * borda_baixa


def _eval_tgtheta(expr, tg_theta):
    if expr == "tgtheta":
        return tg_theta
    if expr == "6-20tgtheta":
        return 6 - 20 * tg_theta
    if expr == "0.6-2tgtheta":
        return 0.6 - 2 * tg_theta
    raise ValueError(f"Expressão desconhecida: {expr}")


# ===========================================================================
# Seção 7.2.1 - Tabela 25 (coberturas isoladas a duas águas planas simétricas)
# ===========================================================================
def coef_cobertura_duas_aguas(tg_theta, carregamento="carregamento1"):
    """
    cpb (água de barlavento) e cps (água de sotavento), Tabela 25.
    carregamento: "carregamento1" ou "carregamento2". Válido para
    0,07 <= tg(theta) <= 0,6.
    """
    if not (0.07 <= tg_theta <= 0.6):
        raise ValueError("tg(θ) deve estar entre 0,07 e 0,6 (Tabela 25).")
    if carregamento == "carregamento1":
        if tg_theta <= 0.4:
            cpb = 2.4 * tg_theta + 0.6
            cps = 3.0 * tg_theta - 0.5
        else:
            cpb = min(2.4 * tg_theta + 0.6, 2.0)
            cps = 0.7
    elif carregamento == "carregamento2":
        if tg_theta <= 0.4:
            cpb = 0.6 * tg_theta - 0.74
            cps = -1.0
        else:
            cpb = 6.5 * tg_theta - 3.1
            cps = 5.0 * tg_theta - 3.0
    else:
        raise ValueError("carregamento deve ser 'carregamento1' ou 'carregamento2'.")
    return round(cpb, 3), round(cps, 3)


def forca_atrito_cobertura_isolada(q, a, b):
    """Ft = 0,5*q*a*b  (7.2.2, vento paralelo à geratriz)."""
    return D.FT_COBERTURA_ISOLADA_COEF * q * a * b


def forca_aba_cobertura(q, ae, barlavento=True):
    """F = 1,3*q*Ae (aba de barlavento) ou 0,8*q*Ae (sotavento)  (7.2.5.1)."""
    coef = D.FA_ABA_BARLAVENTO_COEF if barlavento else D.FA_ABA_SOTAVENTO_COEF
    return coef * q * ae
