"""POS58 termal fiş görseli.

Fiş burada 1-bit görsel olarak çizilir; fiş sayfası (templates/stock/receipt.html)
onu 48 mm genişlikte gösterir ve tarayıcının yazdırma penceresiyle POS58'in
Windows sürücüsüne basar. Görsel yazıcının nokta ızgarasına birebir oturur:
sürücü griyi noktalarla taklit etmez (dither), ince yazı bozulmaz.

Yazıcı (STMicroelectronics "POS58 Printer USB", USB 0416):
- 58 mm rulo, kafa 48 mm = 384 nokta, 203 dpi (1 nokta = 0.125 mm).
- Kafadan yırtma dişine ~15 mm var; fişin altına o kadar boşluk eklenir.

Donanımda doğrulandı (2026-10-04, ham ESC/POS baskı): 384 noktanın tamamı
basılıyor, varsayılan koyuluk yeterli, 15 mm boşluk son satırı dişten geçiriyor.
"""

from dataclasses import dataclass

from django.utils import dateformat, timezone
from PIL import Image, ImageDraw

from apps.sitecore.models import SiteSettings

from .niimbot import DPI, _font, mm_to_px
from .receipt_logo import current_logo
from .templatetags.stock_extras import tl

WIDTH = 384
#: Kenarda boş bırakılan nokta. Kafa 384 noktanın hepsini basıyor; bu yalnızca
#: rulo yana kaydığında yazının kâğıttan taşmaması için.
PAD = 8
#: Fişin altındaki boşluk: kâğıt bu kadar ilerlemezse son satır yazıcının içinde
#: kalır, yırtınca kesilir.
FEED_MM = 15

SIZES = {"title": 32, "info": 28, "total": 28, "body": 23, "small": 21, "foot": 20}


# ---------------------------------------------------------------------------
# İçerik: fişte ne yazacağı. Çizimden ayrı; testler buradan okur.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Line:
    """Fişin bir satırı.

    kind: "logo" | "center" | "row" | "text" | "rule" | "gap" | "image"
    """

    kind: str
    text: str = ""
    right: str = ""
    size: str = "body"
    bold: bool = False
    dashed: bool = True  # rule
    space: int = 0       # gap: nokta
    image: Image.Image | None = None  # image: ortalanır (servis fişindeki QR)


def _row(left, right, size="body", bold=False):
    return Line("row", text=left, right=right, size=size, bold=bold)


def receipt_lines(sale, site=None) -> list[Line]:
    site = site or SiteSettings.load()
    items = list(sale.items.filter(returned_at__isnull=True))
    # Fişte giriş sırasıyla: "Nakit 500, Kredi Kartı 500" kasada yazıldığı gibi.
    payments = sale.payments.order_by("paid_at", "id")

    lines = [
        Line("logo"),
        Line("gap", space=8),
        Line("center", site.brand_name or "BAYÇO TEKNOLOJİ", size="title", bold=True),
    ]
    if site.phone:
        lines.append(Line("center", site.phone, size="small"))
    if site.address:
        lines.append(Line("center", site.address, size="small"))

    lines += [
        Line("rule"),
        _row("Fiş No", sale.receipt_no),
        _row("Tarih", dateformat.format(timezone.localtime(sale.sold_at), "d.m.Y H:i")),
    ]
    if sale.customer:
        lines.append(_row("Müşteri", sale.customer.full_name))
    lines += [
        Line("rule", dashed=False),
        Line("center", "BİLGİ FİŞİ", size="info", bold=True),
        Line("rule", dashed=False),
    ]

    for item in items:
        detail = (f"{item.quantity} × {tl(item.unit_price)}" if item.quantity > 1
                  else item.item_code)
        lines += [
            Line("text", item.item_name),
            _row(detail, tl(item.line_total), size="small"),
        ]
        if item.item_imei:
            lines.append(Line("text", f"IMEI: {item.item_imei}", size="small"))
        lines.append(Line("gap", space=6))

    lines += [Line("rule"), _row("Ara Toplam", tl(sale.grand_total))]
    for trade in sale.trade_ins.all():
        lines.append(_row(f"Takas ({trade.device.stock_code})", f"- {tl(trade.amount)}"))
    lines.append(_row("TOPLAM", tl(sale.payable_total), size="total", bold=True))

    for payment in payments:
        refund = payment.kind == "iade"
        lines.append(_row(payment.get_method_display() + (" (iade)" if refund else ""),
                          ("-" if refund else "") + tl(payment.amount)))
    if sale.balance > 0:
        lines.append(_row("KALAN", tl(sale.balance), size="total", bold=True))
        if sale.due_date:
            lines.append(_row("Vade", dateformat.format(sale.due_date, "d.m.Y")))

    lines.append(Line("rule"))
    for item in items:
        if item.item_imei:
            lines.append(Line("center", f"{item.item_name} — garanti kapsamı için "
                                        "bu fişi saklayınız.", size="foot"))
    lines += [
        Line("center", "Bizi tercih ettiğiniz için teşekkürler.", size="foot"),
        Line("gap", space=8),
        Line("center", "Mali değeri yoktur.", size="small", bold=True),
    ]
    return lines


# ---------------------------------------------------------------------------
# Çizim
# ---------------------------------------------------------------------------

def _wrap(draw, text: str, font, max_w: float) -> list[str]:
    """Kelime kelime sarar; tek başına sığmayan kelime harf harf bölünür."""
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if draw.textlength(candidate, font=font) <= max_w:
            current = candidate
            continue
        if current:
            lines.append(current)
        while draw.textlength(word, font=font) > max_w:
            cut = len(word) - 1
            while cut > 1 and draw.textlength(word[:cut], font=font) > max_w:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines or [""]


def _line_height(font) -> int:
    ascent, descent = font.getmetrics()
    return ascent + descent + 2


def _strip(height: int):
    image = Image.new("1", (WIDTH, height), 255)
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"  # kenar yumuşatma yok; gri piksel termal kafada gürültü olur
    return image, draw


_measure = ImageDraw.Draw(Image.new("1", (1, 1)))


def _draw_line(line: Line, logo: Image.Image) -> Image.Image:
    inner = WIDTH - 2 * PAD
    if line.kind == "logo":
        image, _ = _strip(logo.height)
        image.paste(logo, ((WIDTH - logo.width) // 2, 0))
        return image
    if line.kind == "gap":
        return _strip(line.space)[0]
    if line.kind == "image":
        picture = line.image.convert("1")
        image, _ = _strip(picture.height)
        image.paste(picture, ((WIDTH - picture.width) // 2, 0))
        return image
    if line.kind == "rule":
        image, draw = _strip(18)
        y = 8
        if line.dashed:
            for x in range(PAD, WIDTH - PAD, 12):
                draw.rectangle((x, y, min(x + 6, WIDTH - PAD - 1), y + 1), fill=0)
        else:
            draw.rectangle((PAD, y, WIDTH - PAD - 1, y + 1), fill=0)
        return image

    font = _font(SIZES[line.size], line.bold)
    step = _line_height(font)

    if line.kind == "row":
        right_w = _measure.textlength(line.right, font=font)
        left = _wrap(_measure, line.text, font, max(inner - right_w - 12, inner / 3))
        image, draw = _strip(step * len(left))
        for i, text in enumerate(left):
            draw.text((PAD, i * step), text, font=font, fill=0)
        # Tutar ilk satırda, sağa yaslı.
        draw.text((WIDTH - PAD, 0), line.right, font=font, fill=0, anchor="ra")
        return image

    texts = _wrap(_measure, line.text, font, inner)
    image, draw = _strip(step * len(texts))
    for i, text in enumerate(texts):
        if line.kind == "center":
            draw.text((WIDTH // 2, i * step), text, font=font, fill=0, anchor="ma")
        else:
            draw.text((PAD, i * step), text, font=font, fill=0)
    return image


def render_receipt(lines: list[Line], logo: Image.Image | None = None) -> Image.Image:
    """384 nokta genişliğinde fiş, mod "1"."""
    if logo is None:
        logo = current_logo()
    strips = [_draw_line(line, logo) for line in lines]
    image = Image.new("1", (WIDTH, sum(s.height for s in strips)), 255)
    y = 0
    for strip in strips:
        image.paste(strip, (0, y))
        y += strip.height
    return image


def receipt_image(sale) -> Image.Image:
    return render_receipt(receipt_lines(sale) + [Line("gap", space=mm_to_px(FEED_MM))])


def height_mm(image: Image.Image) -> float:
    return image.height * 25.4 / DPI

