# -*- coding: utf-8 -*-
"""
omml.py
Equações nativas do Word (Office Math, OMML) para a memória de cálculo.

Um construtor pequeno, sem conversão de LaTeX nem folha XSL do Office: cada
função devolve um elemento ``m:*`` e aceita como argumento texto, elemento
ou lista dos dois. O texto segue a convenção tipográfica de grandezas
(ISO 80000-2, a que o editor de equações do Word também segue):

* uma letra só (latina ou grega) é **variável**, em itálico -- ``h``, ``e``,
  ``λ``, ``α``;
* o resto -- números, operadores, palavras e índices descritivos de mais de
  uma letra (``cd``, ``Sd,x``, ``mín``) -- sai em tipo **reto**.

Exemplo, a esbeltez limite do item 15.8.2::

    eq = [sub("λ", "1"), " = ",
          fr(["25 + 12,5 ", fr(sub("e", "1"), "h")], sub("α", "b"))]
"""

from __future__ import annotations

import copy

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

#: Fonte das equações: a do editor de equações do Word.
FONTE_EQUACAO = "Cambria Math"


def _m(tag: str, *filhos) -> OxmlElement:
    el = OxmlElement(f"m:{tag}")
    for f in filhos:
        if f is not None:
            el.append(f)
    return el


def _prop(tag: str, **atributos) -> OxmlElement:
    el = OxmlElement(f"m:{tag}")
    for k, v in atributos.items():
        el.set(qn(f"m:{k}"), v)
    return el


def _variavel(texto: str) -> bool:
    t = texto.strip()
    return len(t) == 1 and t.isalpha()


def r(texto: str, italico: bool | None = None) -> OxmlElement:
    """Um trecho de texto da equação. ``italico=None`` segue a convenção
    (variável de uma letra em itálico, o resto reto)."""
    if italico is None:
        italico = _variavel(texto)
    run = _m("r")
    rpr = _m("rPr")
    if not italico:
        rpr.append(_prop("sty", val="p"))
    run.append(rpr)
    wrpr = OxmlElement("w:rPr")
    fontes = OxmlElement("w:rFonts")
    for att in ("ascii", "hAnsi", "cs", "eastAsia"):
        fontes.set(qn(f"w:{att}"), FONTE_EQUACAO)
    wrpr.append(fontes)
    run.append(wrpr)
    t = OxmlElement("m:t")
    t.set(qn("xml:space"), "preserve")
    t.text = texto
    run.append(t)
    return run


def _itens(x) -> list:
    """Normaliza o argumento: texto, elemento ou lista deles."""
    if x is None:
        return []
    if isinstance(x, str):
        return [r(x)]
    if isinstance(x, (list, tuple)):
        saida = []
        for y in x:
            saida.extend(_itens(y))
        return saida
    # um elemento XML só tem um lugar: reaproveitado numa segunda fórmula,
    # ele sairia da primeira -- vai uma cópia
    if x.getparent() is not None:
        return [copy.deepcopy(x)]
    return [x]


def _e(tag: str, x) -> OxmlElement:
    return _m(tag, *_itens(x))


def fr(numerador, denominador, linear: bool = False) -> OxmlElement:
    """Fração; ``linear=True`` escreve a/b na mesma linha."""
    pr = _m("fPr", _prop("type", val="lin")) if linear else None
    return _m("f", pr, _e("num", numerador), _e("den", denominador))


def sub(base, indice) -> OxmlElement:
    """Base com índice inferior: ``sub("f", "cd")`` é f com cd embaixo."""
    return _m("sSub", _e("e", base), _e("sub", indice))


def sup(base, expoente) -> OxmlElement:
    return _m("sSup", _e("e", base), _e("sup", expoente))


def subsup(base, indice, expoente) -> OxmlElement:
    return _m("sSubSup", _e("e", base), _e("sub", indice),
              _e("sup", expoente))


def raiz(x) -> OxmlElement:
    return _m("rad", _m("radPr", _prop("degHide", val="1")), _m("deg"),
              _e("e", x))


def par(x, abre: str = "(", fecha: str = ")") -> OxmlElement:
    """Delimitador que cresce com o conteúdo: parênteses, colchetes…"""
    pr = _m("dPr", _prop("begChr", val=abre), _prop("endChr", val=fecha))
    return _m("d", pr, _e("e", x))


def func(nome: str, argumento) -> OxmlElement:
    """Função com nome reto: exp, ln, sen, cos…"""
    return _m("func", _m("funcPr"), _m("fName", r(nome, italico=False)),
              _e("e", argumento))


def equacao(x) -> OxmlElement:
    """O objeto de equação (``m:oMath``) pronto para entrar num parágrafo."""
    return _e("oMath", x)
