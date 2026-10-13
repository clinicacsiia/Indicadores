"""Gera 'portal_csi.ico' (icone do Indicadores CSI.exe): quadrado azul com um grafico de barras. Usado por 'Gerar EXE.bat'."""
from pathlib import Path

from PIL import Image, ImageDraw

TAMANHOS = [16, 24, 32, 48, 64, 128, 256]
AZUL, LARANJA, VERDE, BRANCO = (42, 120, 214, 255), (235, 104, 52, 255), (27, 175, 122, 255), (255, 255, 255, 255)


def desenhar(n: int) -> Image.Image:
    s = 4   # desenha 4x maior e reduz: bordas suaves
    t = n * s
    img = Image.new("RGBA", (t, t), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, t - 1, t - 1], radius=t // 5, fill=AZUL)
    base, largura, vao = t * 0.78, t * 0.15, t * 0.07
    x0 = t * 0.5 - (3 * largura + 2 * vao) / 2
    for i, (altura, cor) in enumerate([(0.30, BRANCO), (0.48, LARANJA), (0.62, VERDE)]):
        x = x0 + i * (largura + vao)
        d.rounded_rectangle([x, base - t * altura, x + largura, base], radius=largura / 5, fill=cor)
    return img.resize((n, n), Image.LANCZOS)


if __name__ == "__main__":
    destino = Path(__file__).parent / "portal_csi.ico"
    desenhar(256).save(destino, format="ICO", sizes=[(n, n) for n in TAMANHOS], append_images=[desenhar(n) for n in TAMANHOS if n != 256])
    print("Icone gerado:", destino)
