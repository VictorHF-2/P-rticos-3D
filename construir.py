"""Monta os executáveis do Pórticos 3D e publica em "Exe atual".

O que faz, em ordem:

1. confere que o PyInstaller e as dependências estão instalados;
2. regenera o ícone;
3. roda o PyInstaller com ``Porticos.spec``;
4. verifica os dois executáveis com ``--autoteste``;
5. **publica** a versão em pasta e a portátil em ``Pórticos 3D/Exe atual``;
6. compacta a versão em pasta em ``dist/Porticos-R02-windows.zip``.

O passo 5 é o que difere do ``construir.py`` do Hidra, onde o executável era
levado à mão para a raiz. "Exe atual" quer dizer o que está escrito: a pasta
guarda **o build corrente**, e quem a abre não precisa saber de qual revisão
ele saiu nem procurar dentro de ``dist``. Ela é limpa e reescrita a cada
construção, de propósito — duas versões convivendo ali seria justamente o que
o nome promete que não acontece.

A verificação do passo 4 não é rápida: são as 418 conferências mais o
autoteste da janela, umas quatro minutos por executável. É o preço de saber
que o que foi empacotado calcula igual ao que roda em Python — que é a única
pergunta que interessa num executável.

Uso:
    py construir.py
    py construir.py --sem-teste     pula a verificação (mais rápido)
    py construir.py --sem-zip       não compacta o pacote de envio
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DIST = RAIZ / "dist"
#: ``Pórticos 3D/Exe atual`` — irmã das pastas de revisão.
PUBLICACAO = RAIZ.parent.parent / "Exe atual"


def executar(descricao: str, comando: list[str], tempo: int | None = None
             ) -> None:
    print(f"\n=== {descricao} ===")
    inicio = time.time()
    resultado = subprocess.run(comando, cwd=RAIZ, timeout=tempo)
    if resultado.returncode != 0:
        raise SystemExit(f"FALHOU: {descricao} (código {resultado.returncode})")
    print(f"--- concluído em {time.time() - inicio:.1f} s")


def conferir_dependencias() -> None:
    """As de cálculo, as de interface e as de saída — as três famílias.

    As de saída (docx, openpyxl, ezdxf) entram aqui porque o pacote monta sem
    elas e só falha na hora de gravar o primeiro arquivo. Faltar uma tem de
    parar a construção, não estragar a entrega.
    """
    modulos = {
        "PyInstaller": "pyinstaller",
        "PIL": "pillow",
        "numpy": "numpy",
        "scipy": "scipy",
        "PySide6": "PySide6",
        "matplotlib": "matplotlib",
        "docx": "python-docx",
        "openpyxl": "openpyxl",
        "ezdxf": "ezdxf",
    }
    faltando = []
    for modulo, pacote in modulos.items():
        try:
            __import__(modulo)
        except ImportError:
            faltando.append(pacote)
    if faltando:
        raise SystemExit(
            "Instale antes de construir: " + ", ".join(faltando) + "\n"
            "  py -m pip install -r requirements.txt pyinstaller pillow")


def verificar(executavel: Path) -> None:
    """Roda o autoteste do executável e exige que ele passe.

    O relatório não aparece: o executável é montado sem console, e a saída
    não tem para onde ir. O que se lê é o código de retorno, e ele é o
    bastante — ``main.py`` devolve 1 se qualquer conferência falhar.
    """
    if not executavel.exists():
        raise SystemExit(f"não encontrei {executavel}")
    destino = RAIZ / "autoteste-exe" / executavel.stem
    destino.mkdir(parents=True, exist_ok=True)
    executar(f"verificando {executavel.name} (418 conferências, demora)",
             [str(executavel), "--autoteste", str(destino)], tempo=1800)


def publicar() -> Path:
    """Copia o build para ``Exe atual``, limpando o que estava lá."""
    print(f"\n=== publicando em {PUBLICACAO} ===")
    if PUBLICACAO.exists():
        shutil.rmtree(PUBLICACAO, ignore_errors=True)
    PUBLICACAO.mkdir(parents=True, exist_ok=True)

    shutil.copytree(DIST / "Porticos", PUBLICACAO, dirs_exist_ok=True)
    shutil.copy2(DIST / "Porticos-portatil.exe",
                 PUBLICACAO / "Porticos-portatil.exe")
    leiame = RAIZ / "LEIAME-DISTRIBUICAO.md"
    if leiame.exists():
        shutil.copy2(leiame, PUBLICACAO / "LEIA-ME.md")

    tamanho = sum(a.stat().st_size for a in PUBLICACAO.rglob("*")
                  if a.is_file())
    print(f"--- {tamanho / 1e6:.0f} MB")
    return PUBLICACAO


def compactar() -> Path:
    from portico3d import __version__

    destino = DIST / f"Porticos-{__version__}-windows.zip"
    origem = DIST / "Porticos"
    print(f"\n=== compactando {destino.name} ===")
    if destino.exists():
        destino.unlink()
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6) as pacote:
        for arquivo in sorted(origem.rglob("*")):
            if arquivo.is_file():
                pacote.write(arquivo,
                             Path("Porticos") / arquivo.relative_to(origem))
        leiame = RAIZ / "LEIAME-DISTRIBUICAO.md"
        if leiame.exists():
            pacote.write(leiame, "Porticos/LEIA-ME.md")
    print(f"--- {destino.stat().st_size / 1e6:.0f} MB")
    return destino


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--sem-teste", action="store_true")
    analisador.add_argument("--sem-zip", action="store_true")
    argumentos = analisador.parse_args()

    sys.path.insert(0, str(RAIZ))
    conferir_dependencias()

    executar("gerando o ícone", [sys.executable, "criar_icone.py"])

    if DIST.exists():
        shutil.rmtree(DIST, ignore_errors=True)
    executar("empacotando com PyInstaller",
             [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
              "Porticos.spec"])

    if not argumentos.sem_teste:
        verificar(DIST / "Porticos" / "Porticos.exe")
        verificar(DIST / "Porticos-portatil.exe")

    publicado = publicar()
    pacote = compactar() if not argumentos.sem_zip else None

    pasta = DIST / "Porticos"
    tamanho = sum(a.stat().st_size for a in pasta.rglob("*") if a.is_file())
    portatil = DIST / "Porticos-portatil.exe"
    print("\n================ pronto ================")
    print(f"pasta do programa : {pasta}  ({tamanho / 1e6:.0f} MB)")
    print(f"arquivo único     : {portatil}  "
          f"({portatil.stat().st_size / 1e6:.0f} MB)")
    print(f"publicado em      : {publicado}")
    if pacote is not None:
        print(f"pacote para envio : {pacote}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
