# -*- coding: utf-8 -*-
"""
opensees_ponte.py
Script-ponte autocontido para rodar OpenSeesPy sob Python 3.12.

Este arquivo NÃO importa nada do pacote ``portico3d`` — ele roda num
interpretador separado (``py -3.12``), porque o ``openseespy`` (binário
``openseespywin`` no Windows) só está disponível para a ABI do CPython 3.12
nesta máquina; o resto do programa roda em Python 3.14. A ponte entre os dois
mundos é só texto: este script lê um JSON pela entrada padrão (a descrição de
um modelo, já traduzida para a convenção do OpenSeesPy pelo lado 3.14 — ver
``validacao._opensees_payload_do_modelo``) e devolve outro JSON pela saída
padrão (deslocamentos, reações, esforços de barra e, no modo modal,
frequências e modos).

Convenção de eixo local confirmada empiricamente (não suposta) contra este
programa: o ``vecxz`` que o OpenSeesPy pede é exatamente o eixo local z deste
programa (``matriz_rotacao(...)[2]``, em coordenadas globais) — passado assim,
o ``Iy``/``Iz`` do OpenSeesPy bate com o ``Iy``/``Iz`` deste programa SEM
troca nenhuma, ao contrário do PyNiteFEA (que troca Iy/Iz e os rótulos
My/Mz em barra vertical). Medido com um balanço vertical (bar ao longo de Z,
``vecxz=(0,1,0)``) e um balanço horizontal (bar ao longo de X,
``vecxz=(0,0,1)``), carga lateral na ponta nos dois, comparando a flecha do
OpenSeesPy com ``PL³/3EI`` usando ``Iy`` e ``Iz`` nas duas ordens possíveis —
só a ordem sem troca bateu, nos dois casos, a 1e-12. O caso vertical é o que
teste de verdade porque é o único em que os eixos locais do OpenSeesPy não
coincidem trivialmente com os globais (no horizontal, com essa escolha de
``vecxz``, local e global já saem iguais por coincidência de geometria).

**Pegadinha achada na marra, não documentada com clareza nos manuais**:
``ops.eleForce(tag)`` devolve a força resistente do elemento em coordenadas
GLOBAIS, não locais — por isso tem nome de "force" sem qualificativo, ao
contrário de ``globalForce``/``localForce``/``basicForce`` que o
``eleResponse`` também aceita. Ficou claro comparando o caso trivial vertical:
``eleForce`` devolveu, ponta a ponta, o mesmo vetor da reação de apoio (zero
rotação nenhuma aplicada), e só ``ops.eleResponse(tag, "localForce")`` deu o
vetor nos eixos locais de verdade (``N, Vy, Vz, T, My, Mz``), que é o que
``_momento_opensees``/``esforcos`` usam. Quem copiar este script sem essa
troca mede esforço errado em qualquer barra que não esteja alinhada com um
eixo global.

Modo de uso (linha de comando, mas o uso real é via ``subprocess`` a partir do
Python 3.14):

    py -3.12 opensees_ponte.py < entrada.json > saida.json

ou, com o JSON pela entrada padrão diretamente (é o que
``validacao._opensees_rodar`` faz, via ``subprocess.run(..., input=...)``).
"""

from __future__ import annotations

import json
import sys


def _checar_disponibilidade() -> dict:
    try:
        import openseespy.opensees as ops  # noqa: F401
    except Exception as exc:  # pragma: no cover - só roda fora desta máquina
        return {"disponivel": False, "erro": f"{type(exc).__name__}: {exc}"}
    return {"disponivel": True}


def _montar_modelo(ops, payload: dict) -> dict:
    """Monta o modelo no OpenSeesPy a partir do payload traduzido.

    Devolve um dicionário auxiliar (nomes -> tags inteiras) para a leitura de
    resultados depois da análise.
    """
    ops.wipe()
    ops.model("basic", "-ndm", 3, "-ndf", 6)

    nos = payload["nos"]
    tag_do_no = {nome: i + 1 for i, nome in enumerate(nos)}
    for nome, (x, y, z) in nos.items():
        ops.node(tag_do_no[nome], float(x), float(y), float(z))

    # Apoios (1 = restringido, 0 = livre — mesma convenção do payload).
    for nome, flags in payload.get("apoios", {}).items():
        ops.fix(tag_do_no[nome], *[int(f) for f in flags])

    # Molas (apoio elástico): um nó fantasma preso no mesmo ponto, ligado ao
    # nó real por um elemento ``zeroLength`` com material elástico só nas
    # direções em que a mola tem rigidez; as demais direções ficam livres
    # (o ``zeroLength`` não acopla nada nelas), exatamente como a ``Mola``
    # deste programa não restringe grau de liberdade nenhum por conta
    # própria — só acrescenta rigidez onde ``k != 0``.
    # Tags de elemento ``zeroLength`` começam bem acima das tags das barras
    # (1..len(barras)) para nunca colidir com elas — ``add_member``/
    # ``add_element`` do OpenSees não aceita duas vezes a mesma tag de
    # elemento, mesmo que sejam tipos diferentes (``zeroLength`` x
    # ``elasticBeamColumn`` partilham o mesmo espaço de tags).
    prox_tag_no = len(nos) + 1
    prox_tag_mat = 1
    prox_tag_ele_zl = len(payload["barras"]) + 1
    for nome, k in payload.get("molas", {}).items():
        x, y, z = nos[nome]
        no_fantasma = prox_tag_no
        prox_tag_no += 1
        ops.node(no_fantasma, float(x), float(y), float(z))
        ops.fix(no_fantasma, 1, 1, 1, 1, 1, 1)
        direcoes, materiais = [], []
        for dof, kval in enumerate(k, start=1):
            if kval != 0.0:
                ops.uniaxialMaterial("Elastic", prox_tag_mat, float(kval))
                materiais.append(prox_tag_mat)
                direcoes.append(dof)
                prox_tag_mat += 1
        if materiais:
            ops.element("zeroLength", prox_tag_ele_zl,
                        tag_do_no[nome], no_fantasma,
                        "-mat", *materiais, "-dir", *direcoes)
            prox_tag_ele_zl += 1

    # Diafragma rígido: um nó-mestre no centro de cada pavimento, preso em
    # uz, rx e ry (os graus que o diafragma não governa), e o
    # ``rigidDiaphragm`` com a normal em Z amarrando ux, uy e rz dos nós do
    # pavimento a ele — a mesma cinemática de ``core.diafragma``, por outra
    # implementação (o handler ``Transformation`` do OpenSees).
    for d in payload.get("diafragmas", []):
        mestre = prox_tag_no
        prox_tag_no += 1
        x, y, z = d["centro"]
        ops.node(mestre, float(x), float(y), float(z))
        ops.fix(mestre, 0, 0, 1, 1, 1, 0)
        ops.rigidDiaphragm(3, mestre, *[tag_do_no[n] for n in d["nos"]])

    # Barras: uma ``geomTransf`` própria por barra (mais simples que
    # deduplicar), com ``vecxz`` = eixo local z deste programa em
    # coordenadas globais (ver docstring do módulo) e, quando houver, o
    # trecho rígido via ``-jntOffset``.
    tag_do_elemento = {}
    modal = payload.get("modo") == "modal"
    for i, (nome, b) in enumerate(payload["barras"].items(), start=1):
        transf_tag = i
        args_transf = ["Linear", transf_tag, *b["vecxz"]]
        off_i = b.get("offset_i")
        off_j = b.get("offset_j")
        if off_i is not None or off_j is not None:
            off_i = off_i or [0.0, 0.0, 0.0]
            off_j = off_j or [0.0, 0.0, 0.0]
            args_transf += ["-jntOffset", *off_i, *off_j]
        ops.geomTransf(*args_transf)

        args_ele = ["elasticBeamColumn", i, tag_do_no[b["ni"]], tag_do_no[b["nj"]],
                    b["A"], b["E"], b["G"], b["J"], b["Iy"], b["Iz"], transf_tag]
        if modal:
            args_ele += ["-mass", b["massa_por_comprimento"], "-cMass"]
        ops.element(*args_ele)
        tag_do_elemento[nome] = i

    return {"tag_do_no": tag_do_no, "tag_do_elemento": tag_do_elemento}


def _rodar_estatica(ops, payload: dict, aux: dict) -> dict:
    tag_do_no = aux["tag_do_no"]
    tag_do_elemento = aux["tag_do_elemento"]

    ops.timeSeries("Constant", 1)
    ops.pattern("Plain", 1, 1)

    for nome, vetor in payload.get("cargas_nodais", {}).items():
        if any(v != 0.0 for v in vetor):
            ops.load(tag_do_no[nome], *[float(v) for v in vetor])

    for nome, (wx, wy, wz) in payload.get("cargas_distribuidas", {}).items():
        if wx != 0.0 or wy != 0.0 or wz != 0.0:
            ops.eleLoad("-ele", tag_do_elemento[nome], "-type", "-beamUniform",
                        float(wy), float(wz), float(wx))

    ops.system("BandGeneral")
    ops.numberer("RCM")
    ops.constraints("Transformation")
    ops.test("NormUnbalance", 1.0e-10, 25)
    ops.algorithm("Linear")
    ops.integrator("LoadControl", 1.0)
    ops.analysis("Static")
    codigo = ops.analyze(1)
    if codigo != 0:
        raise RuntimeError(f"ops.analyze() devolveu código {codigo}")

    deslocamentos = {nome: list(ops.nodeDisp(tag)) for nome, tag in tag_do_no.items()}
    reacoes = {}
    ops.reactions()
    for nome in payload.get("apoios", {}):
        reacoes[nome] = list(ops.nodeReaction(tag_do_no[nome]))

    # ``ops.eleForce`` devolve em coordenadas GLOBAIS (confirmado
    # empiricamente: para um elemento com a ponta presa, bate exatamente com
    # a reação, o que só acontece se não houver rotação nenhuma aplicada).
    # O que bate com a convenção LOCAL deste programa (N, Vy, Vz, T, My, Mz
    # nos eixos locais da barra) é ``eleResponse(tag, "localForce")`` — é
    # esse que ``_momento_opensees`` espera. Ver ``_autoteste_eixo_vertical``
    # para o caso trivial que achou essa pegadinha.
    esforcos = {}
    for nome, tag in tag_do_elemento.items():
        f = ops.eleResponse(tag, "localForce")
        esforcos[nome] = {"i": list(f[0:6]), "j": list(f[6:12])}

    return {"deslocamentos": deslocamentos, "reacoes": reacoes,
            "esforcos": esforcos}


def _rodar_modal(ops, payload: dict, aux: dict) -> dict:
    n_modos = int(payload.get("n_modos", 6))
    ops.constraints("Transformation")
    ops.numberer("RCM")
    ops.system("FullGeneral")
    autovalores = ops.eigen(n_modos)
    import math
    frequencias = [math.sqrt(max(w, 0.0)) / (2.0 * math.pi) for w in autovalores]

    tag_do_no = aux["tag_do_no"]
    modos = []
    for m in range(1, n_modos + 1):
        modo = {}
        for nome, tag in tag_do_no.items():
            modo[nome] = [ops.nodeEigenvector(tag, m, d) for d in range(1, 7)]
        modos.append(modo)

    return {"frequencias": frequencias, "modos": modos}


def processar(payload: dict) -> dict:
    disp = _checar_disponibilidade()
    if not disp["disponivel"]:
        return disp
    import openseespy.opensees as ops

    try:
        aux = _montar_modelo(ops, payload)
        if payload.get("modo") == "modal":
            resultado = _rodar_modal(ops, payload, aux)
        else:
            resultado = _rodar_estatica(ops, payload, aux)
        resultado["disponivel"] = True
        return resultado
    except Exception as exc:
        return {"disponivel": True, "erro": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    bruto = sys.stdin.read()
    if not bruto.strip():
        # Sem entrada: só reporta disponibilidade (uso do checador rápido).
        print(json.dumps(_checar_disponibilidade()))
        return
    payload = json.loads(bruto)
    resultado = processar(payload)
    print(json.dumps(resultado))


if __name__ == "__main__":
    main()
