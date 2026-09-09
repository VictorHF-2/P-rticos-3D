"""Desenha o ícone do Pórticos 3D em ``portico3d/recursos``.

Gera dois arquivos:

* ``porticos.ico`` — o ícone do executável e da janela, nos tamanhos do
  Windows;
* ``porticos_logo.png`` — a mesma arte em 512 px, para a janela "Sobre".

Diferente do Hidra, aqui não há um ``Logo.jpg`` de onde recortar: a arte é
**desenhada**, e é de propósito. O desenho é o próprio assunto do programa —
um pórtico de dois vãos com os apoios engastados — e desenhá-lo em código
significa que ele nasce nítido em qualquer tamanho, sem depender de um arquivo
que alguém precise manter.

O que cabe num ícone de 16 px é pouco, e isso governou o traço: duas prumadas,
uma travessa e os apoios. Sem cotas, sem diagrama, sem terceira dimensão — o
que se lê a 16 px é a silhueta, e silhueta de pórtico é isso.

Rode depois de mexer nas cores; ``construir.py`` já chama este script.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parent
DESTINO = RAIZ / "portico3d" / "recursos"

TAMANHOS_ICONE = [16, 24, 32, 48, 64, 128, 256]

#: A paleta é a mesma de ``portico3d.ui.tema`` — o ícone e a janela têm de
#: parecer o mesmo programa.
AZUL = (31, 78, 121)
AZUL_CLARO = (46, 117, 182)
BRANCO = (255, 255, 255)

#: Lado em que a arte é desenhada antes de reduzir. Desenhar grande e reduzir
#: com LANCZOS é o que dá borda limpa nos tamanhos pequenos; desenhar direto a
#: 16 px daria escada.
LADO = 1024


def _arredondado(desenho: ImageDraw.ImageDraw, caixa, raio: int,
                 cor) -> None:
    desenho.rounded_rectangle(caixa, radius=raio, fill=cor)


def desenhar(lado: int = LADO) -> Image.Image:
    """A arte em ``lado`` × ``lado``, com fundo transparente fora do quadro."""
    img = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = lado / 100.0                       # unidade: 1 % do lado

    # fundo: quadrado de cantos arredondados, no azul do tema
    _arredondado(d, (0, 0, lado - 1, lado - 1), int(18 * u), AZUL)

    # medidas do pórtico, em percentagem do lado
    esq, dir_ = 16 * u, 84 * u
    meio = (esq + dir_) / 2.0
    topo, base = 26 * u, 78 * u
    espessura = int(7.5 * u)

    # travessa (a viga) e as três prumadas (os pilares)
    d.rectangle((esq - espessura / 2, topo,
                 dir_ + espessura / 2, topo + espessura), fill=BRANCO)
    for x in (esq, meio, dir_):
        d.rectangle((x - espessura / 2, topo,
                     x + espessura / 2, base), fill=BRANCO)

    # apoios engastados: a linha de base e as hachuras
    d.rectangle((esq - 6 * u, base, dir_ + 6 * u, base + espessura * 0.8),
                fill=AZUL_CLARO)
    passo = 6 * u
    x = esq - 5 * u
    while x < dir_ + 6 * u:
        d.line((x, base + espessura * 0.8 + 5 * u, x + 4 * u, base + espessura * 0.8),
               fill=AZUL_CLARO, width=max(int(1.6 * u), 1))
        x += passo
    return img


def gerar() -> tuple[Path, Path]:
    DESTINO.mkdir(parents=True, exist_ok=True)
    arte = desenhar()

    logo = DESTINO / "porticos_logo.png"
    arte.resize((512, 512), Image.LANCZOS).save(logo)

    icone = DESTINO / "porticos.ico"
    arte.save(icone, sizes=[(n, n) for n in TAMANHOS_ICONE])
    return icone, logo


def main() -> int:
    icone, logo = gerar()
    print(f"ícone gravado em {icone}")
    print(f"logo  gravado em {logo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
