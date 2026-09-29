"""Fiş logosu — 58 mm termal yazıcı için siyah-beyaz.

Site logosu koyu mor zeminli ve renkli; olduğu gibi basılırsa termal kafa
zemini siyah bir blok olarak basar. Burada zemin rengi köşeden okunur ve
zeminden belirgin biçimde ayrılan her piksel siyah, gerisi beyaz yapılır:
mevcut logoda halka, yazı ve dolu daire siyah, "BB" harfleri beyaz çıkar.

Gri ton bırakılmaz: yazıcı sürücüsü griyi noktalarla taklit eder (dither) ve
halkadaki ince yazı okunmaz hale gelir.
"""

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops

from .niimbot import mm_to_px

WIDTH_MM = 30
#: Zeminden en büyük kanal farkı bunu aşan piksel basılır. Mevcut logoda
#: gradyanın en koyu (mor) ucu zeminden ~80 ayrışır; zemindeki sıkıştırma
#: gürültüsü birkaç birimi geçmez.
THRESHOLD = 50


def monochrome_logo(path) -> bytes:
    """Logoyu 1-bit PNG'ye çevirir. Dosya değişince önbellek kendiliğinden düşer."""
    path = Path(path)
    return _render(str(path), path.stat().st_mtime_ns, mm_to_px(WIDTH_MM))


@lru_cache(maxsize=4)
def _render(path: str, mtime_ns: int, width: int) -> bytes:
    with Image.open(path) as source:
        rgba = source.convert("RGBA")
    # Şeffaf zeminli logo beyaza oturtulur; köşe pikseli o zaman beyazdır.
    flat = Image.new("RGB", rgba.size, "white")
    flat.paste(rgba, mask=rgba.getchannel("A"))

    background = Image.new("RGB", flat.size, flat.getpixel((0, 0)))
    r, g, b = ImageChops.difference(flat, background).split()
    distance = ImageChops.lighter(ImageChops.lighter(r, g), b)

    # Önce küçült, sonra eşikle: tersi ince çizgileri kırık kırık bırakır.
    height = max(1, round(flat.height * width / flat.width))
    distance = distance.resize((width, height), Image.Resampling.LANCZOS)
    mono = distance.point(lambda v: 0 if v > THRESHOLD else 255).convert(
        "1", dither=Image.Dither.NONE)

    buffer = io.BytesIO()
    mono.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
