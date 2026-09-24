"""Niimbot termal etiket görseli (niim-agent ile basılır).

labels.py tarayıcıya SVG verip yazdırma diyaloğuna bırakır. Niimbot ise
Bluetooth'la bağlanır ve sürücüsü yoktur: etiket burada PNG olarak piksel
piksel çizilir, niim-agent onu olduğu gibi basar. Tasarım sunucuda kalır.

niim-agent kuralları (SPEC §4.6, D110'da doğrulandı):
- 203 dpi, 1 nokta = 0.125 mm. 40×12 mm = 320×96 px.
- Yatay çizilir; agent 270° döndürüp basar.
- Kenarlarda 1.2 mm (10 px) boşluk: D110 en uçtaki noktaları basmıyor.
- Beyaz zemin, siyah = basılır.

1D barkod modülleri nokta ızgarasına tam oturur (1 modül = 2 nokta = 0.25 mm).
SVG'yi ya da ImageWriter çıktısını ölçeklemek modülleri tutarsız yuvarlar ve
barkod okunmaz hale gelir.
"""

import io
from functools import cache
from pathlib import Path

import barcode
import segno
from PIL import Image, ImageDraw, ImageFont

from .labels import label_fields, symbology_for

DPI = 203
MARGIN_MM = 1.2
MODULE_PX = 2
#: Barkodun iki yanında boş kalması gereken modül sayısı. EAN-13 solda 11 ister.
QUIET_MODULES = {"ean13": 11, "code128": 10}
QR_QUIET_PX = 8

FONT_DIR = Path(__file__).resolve().parent / "fonts"

#: Etiket boyutları (mm). Yazıcıdaki rulo 40×12.
PRESETS = {"40x12": (40, 12)}
DEFAULT_PRESET = "40x12"


def mm_to_px(mm: float) -> int:
    return round(mm * DPI / 25.4)


@cache
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    # Pillow'un gömülü fontunda Türkçe harfler ve ₺ yok.
    name = "DejaVuSansCondensed-Bold.ttf" if bold else "DejaVuSansCondensed.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), size)


def bar_modules(code: str) -> tuple[str, str] | None:
    """(simge, "1011…" modül dizisi). Değer birebir kodlanır; kodlanamazsa None."""
    symbology = symbology_for(code)
    try:
        return symbology, barcode.get(symbology, code).build()[0]
    except Exception:  # Code128'in kodlayamadığı karakter
        return None


def _bar_left(symbology: str, modules: str, width: int, margin: int) -> int | None:
    """Ortalanmış barkodun sol x'i; sessiz bölgeyle etikete sığmıyorsa None."""
    bar_w = len(modules) * MODULE_PX
    left = (width - bar_w) // 2
    if left < max(margin, QUIET_MODULES[symbology] * MODULE_PX):
        return None
    return left


def _fit(draw: ImageDraw.ImageDraw, text: str, font, max_w: float) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def render_label(code: str, title: str, price: str = "",
                 preset: str = DEFAULT_PRESET) -> Image.Image:
    """Yatay etiket görseli, mod "1".

    Kod 1D barkod olarak sığıyorsa: üstte ad + fiyat, ortada barkod, altta kod.
    Sığmıyorsa (ör. BYC-A-000015 Code128'de 290 px): solda QR, sağda metin.
    """
    w_mm, h_mm = PRESETS[preset]
    width, height, margin = mm_to_px(w_mm), mm_to_px(h_mm), mm_to_px(MARGIN_MM)
    image = Image.new("1", (width, height), 255)
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"  # kenar yumuşatma yok; gri piksel termal kafada gürültü olur

    symbol = bar_modules(code)
    left = _bar_left(*symbol, width, margin) if symbol else None
    if left is not None:
        _barcode_layout(draw, width, height, margin, code, title, price, symbol[1], left)
    else:
        _qr_layout(draw, width, height, margin, code, title, price)
    return image


def _barcode_layout(draw, width, height, margin, code, title, price, modules, left):
    top, bottom = margin, height - margin
    text_font, digit_font = _font(13), _font(12)

    # Üst satır: ad solda, fiyat sağda.
    right = width - margin
    if price:
        price_font = _font(13, bold=True)
        right -= draw.textlength(price, font=price_font)
        draw.text((right, top), price, font=price_font, fill=0)
        right -= 6
    draw.text((margin, top), _fit(draw, title, text_font, right - margin),
              font=text_font, fill=0)
    ascent, descent = text_font.getmetrics()

    # Alt satır: kod, taban çizgisi alt kenarda (rakamların inen kuyruğu yok).
    digit_top = bottom + digit_font.getbbox(code, anchor="ls")[1]
    draw.text((width // 2, bottom), code, font=digit_font, anchor="ms", fill=0)

    # Barkod: her modül tam 2 nokta.
    y0, y1 = top + ascent + descent + 2, digit_top - 3
    for i, bit in enumerate(modules):
        if bit == "1":
            x = left + i * MODULE_PX
            draw.rectangle((x, y0, x + MODULE_PX - 1, y1), fill=0)


def _qr_layout(draw, width, height, margin, code, title, price):
    # make_qr: segno.make kısa veride Micro QR seçebilir; telefonlar onu okumuyor.
    matrix = segno.make_qr(code, error="m").matrix
    size = len(matrix)
    px = (height - 2 * margin) // size
    qr_w = size * px
    x0, y0 = margin, (height - qr_w) // 2
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                draw.rectangle((x0 + c * px, y0 + r * px,
                                x0 + (c + 1) * px - 1, y0 + (r + 1) * px - 1), fill=0)

    x = x0 + qr_w + QR_QUIET_PX
    max_w = width - margin - x
    y = margin
    for text, font in ((title, _font(13)), (code, _font(12)),
                       (price, _font(13, bold=True))):
        if text:
            draw.text((x, y), _fit(draw, text, font, max_w), font=font, fill=0)
            y += sum(font.getmetrics()) + 2


def label_image(obj, *, show_price: bool = True, preset: str = DEFAULT_PRESET) -> Image.Image:
    """Device veya Accessory için Niimbot etiketi."""
    from .templatetags.stock_extras import tl0

    fields = label_fields(obj)
    title = " ".join(filter(None, [fields["brand"], fields["name"]]))
    price = tl0(fields["price"]) if (show_price and fields["price"]) else ""
    return render_label(fields["code"], title, price, preset)


def to_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
