# -*- coding: utf-8 -*-
"""
formato.py
Números em texto, do jeito que uma memória de cálculo brasileira se lê:
vírgula decimal e ponto de milhar.

Todo texto que o programa mostra ou grava -- avisos, roteiro de auditoria,
rótulos de figura, planilha, DXF -- passa por :func:`num`. Um ``f"{x:.2f}"``
solto era o que deixava "1.316,0 kN·m" numa tabela e "F.S. = 1.57" no aviso
logo abaixo dela.
"""

from __future__ import annotations

import math


def num(valor, casas: int | None = None, sinal: bool = False,
        sig: int | None = None) -> str:
    """Número com vírgula decimal e ponto de milhar.

    * ``casas``: decimais fixas (``num(2.5, 2)`` -> ``2,50``);
    * ``casas=None`` (padrão): o ``:g`` do Python -- o número "como ele é",
      sem zeros à direita (``num(120.0)`` -> ``120``, ``num(3.05)`` -> ``3,05``);
    * ``sig``: algarismos significativos;
    * ``sinal``: força o ``+`` nos não negativos (deformações, tensões).

    ``None`` e ``nan`` saem como travessão; infinito, como ``∞``.
    """
    if valor is None:
        return "—"
    if isinstance(valor, str):
        return valor
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    if math.isnan(v):
        return "—"
    if math.isinf(v):
        return "∞" if v > 0 else "−∞"
    if sig is not None:
        texto = f"{v:,.{sig}g}"
    elif casas is None:
        texto = f"{v:,g}"
    else:
        texto = f"{v:,.{casas}f}"
    texto = texto.replace(",", "\0").replace(".", ",").replace("\0", ".")
    if sinal and v >= 0:
        texto = "+" + texto
    return texto
