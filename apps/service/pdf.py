"""Teknik servis cihaz kabul formu — A4 PDF (ReportLab).

İki sayfa: 1) MÜŞTERİ NÜSHASI, 2) SERVİS NÜSHASI. Servis nüshasında ayrıca
ekran kilidi kutusu (parola + 3×3 desen çizimi) vardır; müşteriye verilen
kâğıtta parola yazmaz. Desen girilmemişse elle çizmek için boş ızgara basılır.

Yazı tipi stok etiketlerinin kullandığı DejaVu Sans Condensed'dir: ReportLab'ın
yerleşik Helvetica'sında ğ/ş/ı ve ₺ yoktur.
"""

from functools import cache
from io import BytesIO

import segno
from django.contrib.staticfiles import finders
from django.utils import dateformat, timezone
from django.utils.html import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    Image,
    KeepInFrame,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from apps.sitecore.models import SiteSettings
from apps.stock.niimbot import FONT_DIR
from apps.stock.templatetags.stock_extras import tl

FONT, FONT_BOLD = "DejaVu", "DejaVu-Bold"
INK = colors.HexColor("#1e1330")
MUTED = colors.HexColor("#6b6177")
LINE = colors.HexColor("#c9c2d3")
SHADE = colors.HexColor("#f1edf5")
#: Desen çizgisi. Ekrandakiyle aynı renk ailesi; siyah-beyaz yazıcıda da
#: seçilsin diye koyu yeşil.
PATTERN = colors.HexColor("#1e9e50")

PAGE_W, PAGE_H = A4
MARGIN = 13 * mm
TOP, BOTTOM = 11 * mm, 13 * mm
CONTENT_W = PAGE_W - 2 * MARGIN
#: Bir nüshanın sığması gereken yükseklik (SimpleDocTemplate çerçevesinin
#: 6 pt iç boşluğu düşülür).
CONTENT_H = PAGE_H - TOP - BOTTOM - 12


@cache
def _register_fonts():
    pdfmetrics.registerFont(TTFont(FONT, str(FONT_DIR / "DejaVuSansCondensed.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONT_DIR / "DejaVuSansCondensed-Bold.ttf")))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD,
                                  italic=FONT, boldItalic=FONT_BOLD)
    return True


def _styles():
    base = ParagraphStyle("base", fontName=FONT, fontSize=8.8, leading=11.5,
                          textColor=INK)
    return {
        "base": base,
        "small": ParagraphStyle("small", parent=base, fontSize=7.4, leading=9.4,
                                textColor=MUTED),
        "brand": ParagraphStyle("brand", parent=base, fontName=FONT_BOLD, fontSize=14,
                                leading=17),
        "label": ParagraphStyle("label", parent=base, fontSize=7.4, leading=9,
                                textColor=MUTED),
        "value": ParagraphStyle("value", parent=base, fontName=FONT_BOLD),
        "section": ParagraphStyle("section", parent=base, fontName=FONT_BOLD,
                                  fontSize=8.2, leading=10, textColor=INK),
        "title": ParagraphStyle("title", parent=base, fontName=FONT_BOLD, fontSize=11.5,
                                leading=14),
        "copy": ParagraphStyle("copy", parent=base, fontName=FONT_BOLD, fontSize=9.5,
                               leading=14, alignment=TA_RIGHT),
        "right": ParagraphStyle("right", parent=base, alignment=TA_RIGHT),
        "pin": ParagraphStyle("pin", parent=base, fontName=FONT_BOLD, fontSize=16,
                              leading=20),
        "terms": ParagraphStyle("terms", parent=base, fontSize=7.2, leading=9.1,
                                textColor=MUTED, leftIndent=9, firstLineIndent=-9),
    }


def _tr_upper(value: str) -> str:
    """Türkçe büyük harf: str.upper() "i"yi noktasız "I" yapardı."""
    return value.replace("i", "İ").replace("ı", "I").upper()


def _text(value) -> str:
    """Paragraph işaretlemesine güvenli metin; satır sonları korunur."""
    return escape(str(value or "")).replace("\n", "<br/>")


# ---------------------------------------------------------------------------
# Desen çizimi
# ---------------------------------------------------------------------------

class PatternDrawing(Flowable):
    """3×3 kilit deseni: noktalar, çizgiler, başlangıç halkası ve sıra numaraları."""

    def __init__(self, points, size=29 * mm):
        super().__init__()
        self.points = list(points or [])
        self.size = size

    def wrap(self, avail_w, avail_h):
        return self.size, self.size

    def _pos(self, n):
        step = self.size / 3
        col, row = (n - 1) % 3, (n - 1) // 3
        return col * step + step / 2, self.size - (row * step + step / 2)

    def draw(self):
        c = self.canv
        c.setStrokeColor(LINE)
        c.setLineWidth(0.6)
        c.roundRect(0, 0, self.size, self.size, 4, stroke=1, fill=0)

        if len(self.points) > 1:
            c.setStrokeColor(PATTERN)
            c.setLineWidth(2.4)
            c.setLineCap(1)
            c.setLineJoin(1)
            path = c.beginPath()
            path.moveTo(*self._pos(self.points[0]))
            for n in self.points[1:]:
                path.lineTo(*self._pos(n))
            c.drawPath(path, stroke=1, fill=0)

        for n in range(1, 10):
            x, y = self._pos(n)
            visited = n in self.points
            c.setFillColor(INK if visited else colors.white)
            c.setStrokeColor(INK if visited else MUTED)
            c.setLineWidth(1)
            c.circle(x, y, 2.6 * mm if visited else 1.6 * mm, stroke=1, fill=1)
            if visited:
                c.setFillColor(colors.white)
                c.setFont(FONT_BOLD, 7.5)
                c.drawCentredString(x, y - 2.6, str(self.points.index(n) + 1))

        if self.points:
            # Başlangıç noktası: dış halka.
            x, y = self._pos(self.points[0])
            c.setStrokeColor(PATTERN)
            c.setLineWidth(1)
            c.circle(x, y, 3.8 * mm, stroke=1, fill=0)


# ---------------------------------------------------------------------------
# Bloklar
# ---------------------------------------------------------------------------

def _qr_image(value, size):
    buffer = BytesIO()
    segno.make(str(value), error="m").save(buffer, kind="png", scale=8, border=1)
    buffer.seek(0)
    return Image(buffer, width=size, height=size)


def _logo(size):
    path = finders.find("img/logo.png")
    if not path:
        return ""
    image = Image(path)
    ratio = image.imageHeight / image.imageWidth
    return Image(path, width=size, height=size * ratio)


def _header(ticket, site, st):
    contact = [site.address, " · ".join(filter(None, [site.phone, site.email]))]
    brand = [Paragraph(_text(site.brand_name), st["brand"])]
    brand += [Paragraph(_text(line), st["small"]) for line in contact if line]
    number = [
        _qr_image(ticket.ticket_no, 19 * mm),
        Paragraph("SERVİS NO", ParagraphStyle("n", parent=st["label"], alignment=TA_RIGHT)),
        Paragraph(_text(ticket.ticket_no), ParagraphStyle(
            "no", parent=st["value"], fontSize=12, leading=14, alignment=TA_RIGHT)),
    ]
    table = Table([[_logo(18 * mm), brand, number]],
                  colWidths=[22 * mm, CONTENT_W - 22 * mm - 36 * mm, 36 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _title_bar(copy_label, st):
    table = Table([[Paragraph("TEKNİK SERVİS CİHAZ KABUL FORMU", st["title"]),
                    Paragraph(copy_label, st["copy"])]],
                  colWidths=[CONTENT_W * 0.65, CONTENT_W * 0.35])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SHADE),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _cell(label, value, st):
    return [Paragraph(_text(label), st["label"]), Paragraph(_text(value) or "—", st["value"])]


def _grid(cells, columns, st, widths=None):
    """Etiket/değer hücrelerinden kutulu ızgara."""
    rows = [cells[i:i + columns] for i in range(0, len(cells), columns)]
    if rows and len(rows[-1]) < columns:
        rows[-1] += [""] * (columns - len(rows[-1]))
    table = Table(rows, colWidths=widths or [CONTENT_W / columns] * columns)
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _section(title, body, st):
    """Başlıklı tek sütun kutu."""
    table = Table([[Paragraph(title, st["section"])], [body]], colWidths=[CONTENT_W])
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("BACKGROUND", (0, 0), (-1, 0), SHADE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _people_and_device(ticket, st):
    customer = ticket.customer
    half = CONTENT_W / 2
    left = [
        _cell("Ad Soyad / Ünvan", customer.full_name, st),
        _cell("Telefon", customer.phone, st),
        _cell("TCKN / VKN", customer.tax_no, st),
        _cell("Adres", customer.address, st),
    ]
    right = [
        _cell("Marka / Model", str(ticket.device_model), st),
        _cell("IMEI", ticket.imei, st),
        _cell("Seri No", ticket.serial_no, st),
        _cell("Renk", ticket.color, st),
    ]
    rows = [[Paragraph("MÜŞTERİ BİLGİLERİ", st["section"]),
             Paragraph("CİHAZ BİLGİLERİ", st["section"])]]
    rows += [[left[i], right[i]] for i in range(4)]
    table = Table(rows, colWidths=[half, half])
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
        ("BACKGROUND", (0, 0), (-1, 0), SHADE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _money_row(ticket, st):
    cells = [
        _cell("Tahmini Ücret", tl(ticket.estimated_price), st),
        _cell("Alınan Ödeme / Kapora", tl(ticket.paid_total), st),
    ]
    if ticket.final_price is not None:
        cells += [_cell("Servis Ücreti", tl(ticket.final_price), st),
                  _cell("Kalan", tl(ticket.balance), st)]
    else:
        due = (ticket.estimated_price - ticket.paid_total
               if ticket.estimated_price is not None else None)
        cells += [_cell("Kalan (tahmini)", tl(due), st),
                  _cell("Tahmini Teslim",
                        dateformat.format(ticket.estimated_ready, "d.m.Y")
                        if ticket.estimated_ready else "", st)]
    return _grid(cells, 4, st)


def _lock_box(ticket, st):
    """Yalnızca servis nüshası: parola ve desen."""
    if ticket.is_closed:
        body = Paragraph("Cihaz teslim edildiği için ekran kilidi bilgisi silindi.",
                         st["small"])
        return _section("EKRAN KİLİDİ (SERVİS NÜSHASI)", body, st)

    pin = ticket.lock_pin or "—"
    left = [
        Paragraph("Parola / PIN", st["label"]),
        Paragraph(_text(pin), st["pin"]),
        Spacer(1, 4),
        Paragraph("Desen", st["label"]),
        Paragraph(_text(ticket.lock_pattern.replace("-", " → ")) if ticket.lock_pattern
                  else "Girilmedi — gerekirse yandaki ızgaraya elle çizin.", st["base"]),
        Spacer(1, 4),
        Paragraph("Halkalı nokta desenin başlangıcıdır; numaralar çizim sırasını "
                  "gösterir. Bu bilgi müşteri nüshasında yer almaz ve cihaz teslim "
                  "edilince sistemden silinir.", st["small"]),
    ]
    drawing = PatternDrawing(ticket.pattern_points)
    inner = Table([[left, drawing]], colWidths=[CONTENT_W - 12 - 34 * mm, 34 * mm])
    inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return _section("EKRAN KİLİDİ (SERVİS NÜSHASI)", inner, st)


def _terms(site, st):
    lines = [line.strip() for line in (site.service_terms or "").splitlines() if line.strip()]
    if not lines:
        return None
    body = [Paragraph(f"{i}. {_text(line)}", st["terms"]) for i, line in enumerate(lines, 1)]
    return _section("SERVİS ŞARTLARI", body, st)


def _signatures(site, st):
    def box(title, sub):
        return [Paragraph(title, st["section"]), Paragraph(sub, st["small"]),
                Spacer(1, 13 * mm)]

    table = Table([[box("TESLİM EDEN (MÜŞTERİ)",
                        "Yukarıdaki bilgileri ve servis şartlarını okudum, kabul ediyorum. "
                        "Ad Soyad / İmza"),
                    box(f"TESLİM ALAN ({_text(_tr_upper(site.brand_name))})",
                        "Yetkili Ad Soyad / İmza / Kaşe")]],
                  colWidths=[CONTENT_W / 2, CONTENT_W / 2])
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _copy(ticket, site, st, *, service_copy):
    received = timezone.localtime(ticket.received_at)
    person = ticket.created_by
    meta = [
        _cell("Kabul Tarihi", dateformat.format(received, "d.m.Y H:i"), st),
        _cell("Teslim Alan",
              (person.get_full_name() or person.get_username()) if person else "", st),
        _cell("Tahmini Teslim",
              dateformat.format(ticket.estimated_ready, "d.m.Y")
              if ticket.estimated_ready else "", st),
        _cell("Durum", ticket.get_status_display(), st),
    ]
    items = ", ".join(ticket.received_labels) or "Yok (yalnızca cihaz)"
    gap = Spacer(1, 2.6 * mm)

    flow = [
        _header(ticket, site, st), Spacer(1, 3 * mm),
        _title_bar("SERVİS NÜSHASI" if service_copy else "MÜŞTERİ NÜSHASI", st), gap,
        _grid(meta, 4, st), gap,
        _people_and_device(ticket, st), gap,
        _grid([_cell("Teslim Alınan Aksesuarlar", items, st),
               _cell("Fiziksel Durum", ticket.condition_note, st)], 2, st), gap,
        _section("MÜŞTERİ ŞİKÂYETİ / ARIZA",
                 Paragraph(_text(ticket.complaint), st["base"]), st), gap,
    ]
    if ticket.diagnosis:
        flow += [_section("TESPİT / YAPILAN İŞLEM",
                          Paragraph(_text(ticket.diagnosis), st["base"]), st), gap]
    flow += [_money_row(ticket, st), gap]
    if service_copy:
        flow += [_lock_box(ticket, st), gap]
    terms = _terms(site, st)
    if terms is not None:
        flow += [terms, gap]
    flow.append(_signatures(site, st))
    # Her nüsha TEK sayfa: uzun bir arıza metni nüshayı ikinci sayfaya taşırsa
    # müşteri/servis sayfaları birbirine karışırdı. Sığmayan içerik küçültülür.
    return [KeepInFrame(CONTENT_W, CONTENT_H, flow, mode="shrink")]


def _footer(ticket, site):
    stamp = dateformat.format(timezone.localtime(), "d.m.Y H:i")

    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 8 * mm,
                          f"{site.brand_name} · {ticket.ticket_no} · oluşturuldu {stamp}")
        canvas.drawRightString(PAGE_W - MARGIN, 8 * mm, f"Sayfa {doc.page}")
        canvas.restoreState()
    return draw


def intake_pdf(ticket, site=None) -> bytes:
    """İki nüshalı kabul formu (bytes)."""
    _register_fonts()
    site = site or SiteSettings.load()
    st = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=TOP, bottomMargin=BOTTOM,
        title=f"Servis Kabul Formu {ticket.ticket_no}", author=site.brand_name,
        subject=str(ticket.device_model),
    )
    story = _copy(ticket, site, st, service_copy=False)
    story += [PageBreak()] + _copy(ticket, site, st, service_copy=True)
    footer = _footer(ticket, site)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
