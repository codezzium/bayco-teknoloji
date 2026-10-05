"""POS58 servis fişi (58 mm termal).

Çizim satış fişiyle aynı motordan geçer (apps/stock/pos58.py); burada yalnızca
fişte ne yazacağı kurulur. Kayıt açıkken "SERVİS FİŞİ" (müşteri cihazı almaya
gelirken getirir), kapandıktan sonra "SERVİS TESLİM FİŞİ" (ücret ve ödemeler)
basılır. QR, Barkod Tara ekranında okutulunca kaydı açar.

Ekran kilidi bilgisi fişe ASLA basılmaz: fiş müşteride kalır.
"""

from io import BytesIO

import segno
from django.utils import dateformat, timezone
from PIL import Image

from apps.sitecore.models import SiteSettings
from apps.stock.models import Payment
from apps.stock.niimbot import mm_to_px
from apps.stock.pos58 import FEED_MM, Line, render_receipt
from apps.stock.templatetags.stock_extras import tl

COMPLAINT_CHARS = 140


def _row(left, right, size="body", bold=False):
    return Line("row", text=left, right=right, size=size, bold=bold)


def _qr(value) -> Image.Image:
    buffer = BytesIO()
    segno.make(str(value), error="m").save(buffer, kind="png", scale=6, border=1)
    buffer.seek(0)
    return Image.open(buffer).convert("1")


def slip_lines(ticket, site=None) -> list[Line]:
    site = site or SiteSettings.load()
    closed = ticket.is_closed
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
        Line("rule", dashed=False),
        Line("center", "SERVİS TESLİM FİŞİ" if closed else "SERVİS FİŞİ",
             size="info", bold=True),
        Line("rule", dashed=False),
        Line("center", ticket.ticket_no, size="title", bold=True),
        Line("gap", space=4),
        _row("Kabul", dateformat.format(timezone.localtime(ticket.received_at), "d.m.Y H:i")),
    ]
    if closed and ticket.closed_at:
        lines.append(_row("Teslim",
                          dateformat.format(timezone.localtime(ticket.closed_at), "d.m.Y H:i")))
    lines += [
        _row("Müşteri", ticket.customer.full_name),
        Line("rule"),
        Line("text", str(ticket.device_model), bold=True),
    ]
    if ticket.color:
        lines.append(Line("text", ticket.color, size="small"))
    if ticket.imei:
        lines.append(Line("text", f"IMEI: {ticket.imei}", size="small"))
    complaint = " ".join(ticket.complaint.split())
    if len(complaint) > COMPLAINT_CHARS:
        complaint = complaint[:COMPLAINT_CHARS - 1].rstrip() + "…"
    lines.append(Line("text", f"Arıza: {complaint}", size="small"))
    if closed and ticket.diagnosis:
        lines.append(Line("text", f"Yapılan: {' '.join(ticket.diagnosis.split())[:COMPLAINT_CHARS]}",
                          size="small"))
    lines.append(Line("rule"))

    if closed:
        lines.append(_row("Servis Ücreti", tl(ticket.final_price), size="total", bold=True))
        for payment in ticket.payments.order_by("paid_at", "id"):
            refund = payment.kind == Payment.Kind.IADE
            lines.append(_row(payment.get_method_display() + (" (iade)" if refund else ""),
                              ("-" if refund else "") + tl(payment.amount)))
        if ticket.balance:
            lines.append(_row("KALAN", tl(ticket.balance), size="total", bold=True))
    else:
        if ticket.estimated_price is not None:
            lines.append(_row("Tahmini Ücret", tl(ticket.estimated_price)))
        if ticket.final_price is not None:
            lines.append(_row("Servis Ücreti", tl(ticket.final_price), bold=True))
        if ticket.paid_total:
            lines.append(_row("Alınan Kapora", tl(ticket.paid_total)))
        if ticket.estimated_ready:
            lines.append(_row("Tahmini Teslim",
                              dateformat.format(ticket.estimated_ready, "d.m.Y")))

    lines += [
        Line("rule"),
        Line("gap", space=6),
        Line("image", image=_qr(ticket.ticket_no)),
        Line("gap", space=6),
    ]
    if not closed:
        lines.append(Line("center", "Cihazınızı teslim alırken bu fişi getiriniz.",
                          size="foot"))
    lines += [
        Line("center", "Bizi tercih ettiğiniz için teşekkürler.", size="foot"),
        Line("gap", space=8),
        Line("center", "Mali değeri yoktur.", size="small", bold=True),
    ]
    return lines


def slip_image(ticket) -> Image.Image:
    return render_receipt(slip_lines(ticket) + [Line("gap", space=mm_to_px(FEED_MM))])
