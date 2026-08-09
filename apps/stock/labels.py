"""QR ve barkod etiketi üretimi.

Yaklaşım: sunucuda inline SVG üret, tarayıcının yazdırma diyaloğuna bırak.
WeasyPrint sistem Pango/Cairo kütüphaneleri ister (3 bağımlılıklı bir projede
7 transitive paket), ReportLab ise HTML önizlemesi ve ortak CSS vermez.
segno + python-barcode ikisi de saf Python ve bağımlılıksızdır.
"""

import io
import re

import barcode
import segno
from barcode.writer import SVGWriter

#: Etiket biçimleri. mm ölçüleri A4 tabakalara tam bölünür:
#: 2×105=210, 3×70=210, 4×52.5=210, 8×37=296, 10×29.7=297.
LABEL_FORMATS = {
    # --- Termal rulo: bir etiket = bir sayfa ---
    "termal-40x30": dict(
        label="Termal 40×30 mm", kind="roll", page_w=40, page_h=30,
        w=40, h=30, cols=1, rows=1, mt=0, ml=0, qr=15, mod=0.25, bh=6.0, pad=1.5),
    "termal-58x40": dict(
        label="Termal 58×40 mm", kind="roll", page_w=58, page_h=40,
        w=58, h=40, cols=1, rows=1, mt=0, ml=0, qr=20, mod=0.30, bh=8.0, pad=2.0),
    # --- A4 lazer etiket tabakaları ---
    "a4-105x37": dict(
        label="A4 · 16'lı (105×37 mm)", kind="sheet", page_w=210, page_h=297,
        w=105, h=37, cols=2, rows=8, mt=0.5, ml=0, qr=24, mod=0.33, bh=8.0, pad=3.0),
    "a4-70x37": dict(
        label="A4 · 24'lü (70×37 mm)", kind="sheet", page_w=210, page_h=297,
        w=70, h=37, cols=3, rows=8, mt=0.5, ml=0, qr=22, mod=0.30, bh=7.0, pad=2.5),
    "a4-52x30": dict(
        label="A4 · 40'lı (52,5×29,7 mm)", kind="sheet", page_w=210, page_h=297,
        w=52.5, h=29.7, cols=4, rows=10, mt=0, ml=0, qr=17, mod=0.25, bh=6.0, pad=1.8),
    "a4-48x25": dict(
        label="A4 · 44'lü (48,5×25,4 mm)", kind="sheet", page_w=210, page_h=297,
        w=48.5, h=25.4, cols=4, rows=11, mt=8.8, ml=8.0, qr=15, mod=0.25, bh=5.0,
        pad=1.5),
}

DEFAULT_FORMAT = "termal-40x30"
MAX_LABELS = 200          # URL uzunluğu + makul kâğıt sınırı
MAX_COPIES = 10

_SVG_START = re.compile(r"<svg\b")


def qr_svg(value: str, *, border: int = 1) -> str:
    """Ölçüsüz (viewBox'lı) inline SVG döndürür; mm boyutu CSS'ten verilir.

    segno tercih edildi: sıfır bağımlılık ve svg_inline() XML bildirimi/doctype
    olmadan çıplak <svg> döndürür — şablona doğrudan gömülebilir.
    """
    return segno.make(str(value), error="m").svg_inline(
        omitsize=True, border=border, dark="#000000", light=None,
    )


def barcode_svg(value: str, *, symbology="code128", module_width=0.25,
                module_height=7.0) -> str:
    """1D barkod SVG'si.

    module_width MİLİMETREDİR ve 203 dpi termal kafada 0.125 mm'nin katı
    olmalıdır (0.25 mm = tam 2 nokta). Ara değerler tutarsız yuvarlanır ve
    barkod okunmaz hale gelir.

    Dönen SVG kendi mm genişliğini taşır; şablonda ASLA width:100% verilmemeli,
    aksi halde modüller nokta ızgarasından kayar.
    """
    value = str(value)
    try:
        writer = SVGWriter()
        symbol = barcode.get(symbology, value, writer=writer)
        buffer = io.BytesIO()
        symbol.write(buffer, options={
            "module_width": module_width,
            "module_height": module_height,
            "quiet_zone": 1.5,
            "write_text": False,
            "font_size": 0,
            "text_distance": 1,
        })
    except Exception:
        # Geçersiz EAN sağlaması gibi durumlarda etiket üretimi tamamen
        # durmasın; QR yine basılır.
        return ""
    svg = buffer.getvalue().decode("utf-8")
    match = _SVG_START.search(svg)
    return svg[match.start():] if match else ""


def build_label(obj, fmt: dict, *, show_price=True) -> dict:
    """Device veya Accessory için etiket verisini hazırlar."""
    from .models import Accessory, Device
    from .templatetags.stock_extras import tl0

    if isinstance(obj, Device):
        code = obj.stock_code
        brand = obj.device_model.brand.name
        name = obj.label
        price = obj.list_price
        # Cihaz kodu alfanümeriktir (BYC-000123) -> EAN-13 kullanılamaz
        symbology, bar_value = "code128", code
    elif isinstance(obj, Accessory):
        code = obj.barcode or obj.sku
        brand = obj.brand.name if obj.brand_id else ""
        name = str(obj)
        price = obj.price
        # Gerçek EAN-13 varsa onu bas: başka mağazanın kasasında da okunur
        if obj.barcode and obj.barcode.isdigit() and len(obj.barcode) == 13:
            symbology, bar_value = "ean13", obj.barcode
        else:
            symbology, bar_value = "code128", code
    else:
        raise TypeError("Etiket yalnızca Device veya Accessory için üretilir.")

    return {
        "code": code,
        "brand": brand,
        "name": name,
        "price": tl0(price) if (show_price and price) else "",
        # QR içeriği çıplak koddur, URL değil: kısa payload -> az modül ->
        # büyük modül -> telefon kamerasıyla belirgin biçimde daha iyi okuma.
        "qr": qr_svg(code),
        "bar": barcode_svg(bar_value, symbology=symbology,
                           module_width=fmt["mod"], module_height=fmt["bh"]),
    }


def paginate_labels(labels: list, fmt: dict) -> list[list]:
    """Etiketleri sayfalara böler (rulo formatında sayfa başına 1 etiket)."""
    per_page = 1 if fmt["kind"] == "roll" else int(fmt["cols"] * fmt["rows"])
    return [labels[i:i + per_page] for i in range(0, len(labels), per_page)]
