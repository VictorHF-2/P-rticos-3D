# -*- coding: utf-8 -*-
"""
projeto.py
Um projeto reúne várias vigas e o estado em que o usuário as deixou.

**Salva-se a ENTRADA, não o resultado.** O que o usuário edita -- bitolas,
ganchos, distribuição dos estribos, a armadura lateral -- já vive dentro da
própria :class:`~vigas.core.modelo.Viga` (em ``Config``), e
:func:`vigas.core.dimensionar.dimensionar` é determinista e não altera o que
recebe (medido: 84 a 744 ms por viga, entrada intacta). Guardar só a entrada
e recalcular ao abrir reproduz a configuração final **exatamente**, sem o
risco de um resultado guardado ficar diferente do que o motor devolveria. O
que a entrada não cobre é o que mora só na interface -- a lista de seções
transversais que o usuário editou e as opções de exibição --, e isso vai em
:class:`EstadoVista`.

O módulo é puro de Qt: o ``--autoteste`` exercita o projeto inteiro sem
interface.

Formato do arquivo (``_formato = "projeto-vigas"``)::

    {"_formato": "projeto-vigas", "_versao": 1, "nome": "...", "ativa": 0,
     "vigas": [{"viga": {...}, "vista": {...}, "calculada": true}, ...]}

Um arquivo de **viga avulsa** (``_formato = "viga-nbr6118"``, o que o programa
gravava antes e o que os projetos de referência ainda são) abre como um
projeto de uma viga só: nenhum arquivo antigo deixa de abrir.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

import numpy as np

from .analise import combinar, resolver
from .modelo import CargaConcentrada, Viga

FORMATO = "projeto-vigas"
VERSAO = 1

_AUSENTE = object()


@dataclass
class EstadoVista:
    """O que a interface guarda por viga e que não está na ``Viga``."""

    #: lista editável de seções transversais desenhadas: ``[{"x": m, "nome": s}]``
    secoes: list = field(default_factory=list)
    #: "Vista", "Seções" ou "Completo" (seletor da aba de detalhamento)
    modo: str = "Vista"
    desenhar_estribos: bool = True
    #: 0 = automático
    exagero_vertical: float = 0.0

    @staticmethod
    def de_dict(d: dict | None) -> "EstadoVista":
        d = d or {}
        padrao = EstadoVista()
        return EstadoVista(
            secoes=[{"x": float(s["x"]), "nome": str(s.get("nome", ""))}
                    for s in d.get("secoes", [])],
            modo=str(d.get("modo", padrao.modo)),
            desenhar_estribos=bool(d.get("desenhar_estribos",
                                         padrao.desenhar_estribos)),
            exagero_vertical=float(d.get("exagero_vertical",
                                         padrao.exagero_vertical)))


@dataclass
class EntradaViga:
    """Uma viga do projeto: a entrada, o estado de vista e o que se calculou.

    Os campos ``resultado``, ``instantaneo``, ``base_painel`` e ``erro`` vivem
    só na memória: são derivados, e o arquivo guarda apenas ``calculada``, que
    diz se a viga deve ser recalculada ao abrir.
    """

    viga: Viga
    vista: EstadoVista = field(default_factory=EstadoVista)
    calculada: bool = False
    #: ResultadoViga do último cálculo bem-sucedido, se estiver em memória
    resultado: object | None = field(default=None, repr=False, compare=False)
    #: ``para_dict`` da entrada no momento em que o resultado foi calculado --
    #: a régua para saber se o resultado ficou desatualizado
    instantaneo: dict | None = field(default=None, repr=False, compare=False)
    #: ``para_dict`` do que o painel de entrada devolve logo depois de
    #: carregar esta viga -- a linha de base de "o usuário não mexeu"
    base_painel: dict | None = field(default=None, repr=False, compare=False)
    erro: str = field(default="", compare=False)
    #: ``para_dict`` da viga **como foi calculada** -- com as reações das
    #: vigas apoiadas nela e a altura da viga em que ela se apoia. Muda quando
    #: outra viga do projeto muda, e é por ele que se sabe que o resultado
    #: desta ficou desatualizado por causa da outra
    instantaneo_calculo: dict | None = field(default=None, repr=False,
                                             compare=False)

    @property
    def nome(self) -> str:
        return self.viga.nome

    def desatualizada(self) -> bool:
        """A entrada mudou depois do último cálculo?"""
        return (self.resultado is not None and self.instantaneo is not None
                and self.viga.para_dict() != self.instantaneo)

    def para_dict(self) -> dict:
        return {"viga": self.viga.para_dict(), "vista": asdict(self.vista),
                "calculada": bool(self.calculada)}


class Projeto:
    """Lista de vigas com uma delas ativa."""

    def __init__(self, entradas: list[EntradaViga] | None = None,
                 nome: str = "", ativa: int = 0) -> None:
        self.entradas: list[EntradaViga] = entradas or []
        self.nome = nome
        self.ativa = ativa
        #: veio de um arquivo de viga avulsa (``viga-nbr6118``), e não de um
        #: arquivo de projeto. Salvar por cima dele trocaria o formato do
        #: arquivo de quem só queria gravar -- por isso a interface pergunta
        #: onde salvar na primeira vez
        self.de_viga_avulsa = False

    # -- acesso -------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.entradas)

    @property
    def atual(self) -> EntradaViga:
        return self.entradas[self.ativa]

    def nomes(self) -> list[str]:
        return [e.nome for e in self.entradas]

    def nome_unico(self, base: str, ignorar: int | None = None) -> str:
        """``base`` se estiver livre; senão ``base 2``, ``base 3``...

        Ignora a entrada ``ignorar``, para renomear uma viga para o próprio
        nome não contar como conflito.
        """
        usados = {e.nome for i, e in enumerate(self.entradas) if i != ignorar}
        base = base.strip() or "V"
        if base not in usados:
            return base
        raiz = re.sub(r"\s+\d+$", "", base)
        n = 2
        while f"{raiz} {n}" in usados:
            n += 1
        return f"{raiz} {n}"

    # -- edição -------------------------------------------------------------
    def adicionar(self, viga: Viga, vista: EstadoVista | None = None,
                  calculada: bool = False) -> int:
        viga.nome = self.nome_unico(viga.nome)
        self.entradas.append(EntradaViga(viga, vista or EstadoVista(),
                                         calculada))
        return len(self.entradas) - 1

    def duplicar(self, i: int) -> int:
        """Cópia da viga ``i`` -- entrada e vista, sem o resultado."""
        origem = self.entradas[i]
        copia = Viga.de_dict(json.loads(json.dumps(origem.viga.para_dict())))
        copia.nome = self.nome_unico(f"{origem.nome} cópia")
        vista = EstadoVista.de_dict(asdict(origem.vista))
        self.entradas.insert(i + 1, EntradaViga(copia, vista, False))
        # a inserção empurra para a frente tudo o que estava depois de `i`;
        # sem este ajuste a viga ativa passaria a apontar para outra entrada
        if i + 1 <= self.ativa:
            self.ativa += 1
        return i + 1

    def remover(self, i: int) -> EntradaViga:
        """Tira a viga ``i`` do projeto e a devolve (para poder desfazer)."""
        if len(self.entradas) <= 1:
            raise ValueError("O projeto precisa de pelo menos uma viga.")
        retirada = self.entradas.pop(i)
        if i < self.ativa:
            self.ativa -= 1
        self.ativa = min(self.ativa, len(self.entradas) - 1)
        return retirada

    def inserir(self, i: int, entrada: EntradaViga) -> int:
        """Põe ``entrada`` na posição ``i`` (ou o mais perto que couber).

        É o desfazer de :meth:`remover`: a entrada volta com tudo o que tinha,
        inclusive o resultado. A viga que estava ativa continua ativa. Se o
        nome da entrada foi tomado enquanto ela esteve fora, ganha um novo.
        """
        i = max(0, min(i, len(self.entradas)))
        entrada.viga.nome = self.nome_unico(entrada.viga.nome)
        self.entradas.insert(i, entrada)
        if i <= self.ativa:
            self.ativa += 1
        return i

    def mover(self, i: int, j: int) -> None:
        """Leva a viga da posição ``i`` para a ``j``. A ativa continua a mesma."""
        if not (0 <= i < len(self.entradas) and 0 <= j < len(self.entradas)):
            raise IndexError("posição fora do projeto")
        if i == j:
            return
        ativa = self.atual
        self.entradas.insert(j, self.entradas.pop(i))
        self.ativa = next(k for k, e in enumerate(self.entradas)
                          if e is ativa)

    # -- persistência -------------------------------------------------------
    def para_dict(self) -> dict:
        return {"_formato": FORMATO, "_versao": VERSAO, "nome": self.nome,
                "ativa": self.ativa,
                "vigas": [e.para_dict() for e in self.entradas]}

    @staticmethod
    def de_dict(d: dict) -> "Projeto":
        if d.get("_formato") != FORMATO:
            # viga avulsa: o formato de antes dos projetos
            avulso = Projeto([EntradaViga(Viga.de_dict(d))])
            avulso.de_viga_avulsa = True
            return avulso
        entradas = [EntradaViga(Viga.de_dict(v["viga"]),
                                EstadoVista.de_dict(v.get("vista")),
                                bool(v.get("calculada", False)))
                    for v in d.get("vigas", [])]
        if not entradas:
            raise ValueError("O arquivo de projeto não contém nenhuma viga.")
        ativa = int(d.get("ativa", 0))
        return Projeto(entradas, str(d.get("nome", "")),
                       ativa if 0 <= ativa < len(entradas) else 0)

    def salvar(self, caminho: str) -> None:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(self.para_dict(), f, ensure_ascii=False, indent=2)

    @staticmethod
    def carregar(caminho: str) -> "Projeto":
        with open(caminho, encoding="utf-8") as f:
            return Projeto.de_dict(json.load(f))

    # -- vigas apoiadas em vigas (18.3.6) -------------------------------------
    def viga_para_calculo(self, i: int) -> Viga:
        """A viga ``i`` como ela é calculada dentro do projeto.

        Uma cópia, com duas coisas que vêm das outras vigas:

        * nos apoios desta que estão noutra viga do projeto, a **altura** e a
          **largura** da viga de apoio no cruzamento -- é a largura dela que é
          a do apoio, e é a altura dela que reduz a suspensão e define a viga
          pendurada;
        * para cada viga do projeto apoiada nesta, a **reação** dela, como
          carga concentrada **indireta** no ponto do cruzamento: a parcela
          permanente e a variável, característica, a variável na alternância
          que dá a maior reação. É o que leva a carga de uma viga para a outra
          sem digitar, e o que obriga a suspensão dos dois lados.

        Uma viga apoiada em outra que também está apoiada recebe a cadeia
        inteira; apoio em círculo é erro.
        """
        return self._efetiva(i, ())

    def _efetiva(self, i: int, pilha: tuple[str, ...]) -> Viga:
        e = self.entradas[i]
        nome = e.viga.nome
        if nome in pilha:
            cadeia = " → ".join(pilha + (nome,))
            raise ValueError(f"Vigas apoiadas em círculo: {cadeia}. Uma delas "
                             f"tem de se apoiar em pilar.")
        v = Viga.de_dict(json.loads(json.dumps(e.viga.para_dict())))
        por_nome = {en.viga.nome: j for j, en in enumerate(self.entradas)}
        for ap in v.apoios:
            j = por_nome.get(ap.viga_apoio)
            if j is None or j == i:
                continue
            apoio = self.entradas[j].viga
            secao = apoio.secao_em(min(max(ap.x_na_viga_apoio, 0.0),
                                       apoio.comprimento))
            ap.h_viga_apoio = secao.h
            ap.largura = secao.bw
        for j, en in enumerate(self.entradas):
            if j == i:
                continue
            for k, ap in enumerate(en.viga.apoios):
                if ap.viga_apoio != nome or ap.tipo == "livre":
                    continue
                apoiada = self._efetiva(j, pilha + (nome,))
                Rg, Rq = reacoes_caracteristicas(apoiada, k)
                h_ap = apoiada.secao_de_apoio(k).h
                for P, acao in ((Rg, "g"), (Rq, "q")):
                    if abs(P) <= 1e-9:
                        continue
                    v.concentradas.append(CargaConcentrada(
                        P=P, x=ap.x_na_viga_apoio, acao=acao,
                        indireta=P > 0.0, h_apoiada=h_ap,
                        topos_alinhados=ap.topos_alinhados,
                        origem=f"{en.viga.nome}, apoio {k + 1}",
                        descricao=f"reação de {en.viga.nome} (apoio {k + 1})"))
        return v

    def calculo_desatualizado(self, i: int) -> bool:
        """O resultado da viga ``i`` deixou de valer por causa de outra viga?"""
        e = self.entradas[i]
        if e.resultado is None or e.instantaneo_calculo is None:
            return False
        try:
            return self.viga_para_calculo(i).para_dict() != e.instantaneo_calculo
        except ValueError:
            return True

    def assinatura(self) -> str:
        """Impressão digital do que vai para o arquivo, menos ``calculada``.

        Serve a "há alterações não salvas?". ``calculada`` fica de fora de
        propósito: calcular uma viga não muda nada do que o usuário decidiu, e
        perguntar "salvar?" só porque ele olhou os resultados seria ruído.
        """
        d = self.para_dict()
        for v in d["vigas"]:
            v.pop("calculada", None)
        texto = json.dumps(d, sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(texto.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Fusão em três vias: só o que o usuário editou substitui o original
# ---------------------------------------------------------------------------

def fundir(original, base, atual):
    """Devolve ``original`` com **apenas** o que mudou de ``base`` para ``atual``.

    Existe por causa do painel de entrada, que é um canal **com perda**:
    carregar uma viga nele e montá-la de volta descarta os nomes dos apoios e
    dos vãos, as observações da capa da memória de cálculo, e arredonda o
    ``k_mola`` (medido: 6996,01 volta como 6996,0). Guardar o que o painel
    devolve, a cada troca de viga, apagaria isso sem que o usuário tivesse
    tocado em nada.

    ``base`` é o que o painel devolveu logo depois de carregar ``original``:
    o "usuário não mexeu". Onde ``atual`` é igual a ``base`` nada foi editado e
    vale o ``original`` -- inteiro, sem arredondamento nem perda; onde
    diferem, o usuário editou e vale ``atual``. Os três são dicionários de
    ``Viga.para_dict()``. Listas alinham por posição: se o usuário
    acrescentou um vão, os vãos que já existiam guardam os nomes.
    """
    if isinstance(atual, dict) and isinstance(base, dict):
        o = original if isinstance(original, dict) else {}
        saida = {}
        for k in {*atual, *base}:
            if k not in atual:               # o painel deixou de produzir a chave
                continue
            saida[k] = fundir(o.get(k, _AUSENTE), base.get(k, _AUSENTE),
                              atual[k])
        for k in o:                          # chave que o painel nunca produz
            if k not in atual and k not in base:
                saida[k] = o[k]
        return saida
    if isinstance(atual, list) and isinstance(base, list):
        o = original if isinstance(original, list) else []
        saida = []
        for i, a in enumerate(atual):
            b = base[i] if i < len(base) else _AUSENTE
            saida.append(fundir(o[i] if i < len(o) else _AUSENTE, b, a))
        return saida
    if atual == base and original is not _AUSENTE:
        return original                      # não editado: o original manda
    return atual


def reacoes_caracteristicas(viga: Viga, k: int) -> tuple[float, float]:
    """Reação característica do apoio ``k``: ``(permanente, variável)``, kN.

    A permanente com todos os tramos carregados; a variável é a soma das
    contribuições **positivas** de cada tramo carregado sozinho -- a
    alternância que dá a maior reação, por superposição.
    """
    est = resolver(viga)
    nt = len(viga.tramos)
    Rg = float(combinar(est, np.ones(nt), np.zeros(nt)).reacoes[k])
    Rq = 0.0
    for t in range(nt):
        so = np.zeros(nt)
        so[t] = 1.0
        Rq += max(0.0, float(combinar(est, np.zeros(nt), so).reacoes[k]))
    return Rg, Rq
