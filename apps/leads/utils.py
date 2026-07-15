from urllib.parse import quote


def wa_link(number: str, text: str) -> str:
    """wa.me deep-link üretir (metin URL-encode edilir)."""
    number = "".join(ch for ch in (number or "") if ch.isdigit())
    return f"https://wa.me/{number}?text={quote(text)}"


def normalize_tr(phone: str) -> str:
    """TR telefon numarasını uluslararası biçime çevirir (90...)."""
    d = "".join(ch for ch in (phone or "") if ch.isdigit())
    if d.startswith("90"):
        return d
    if d.startswith("0"):
        return "90" + d[1:]
    if len(d) == 10:  # 5xxxxxxxxx
        return "90" + d
    return d


def customer_wa(phone: str) -> str:
    """Panelden müşteriye WhatsApp yanıtı için deep-link."""
    return f"https://wa.me/{normalize_tr(phone)}"


def quote_message(qr) -> str:
    """QuoteRequest için WhatsApp mesaj metni."""
    if qr.kind == qr.Kind.SAT:
        lines = [
            "Merhaba, telefonumu satmak / takas etmek istiyorum. 📱",
            "",
            f"👤 Ad Soyad: {qr.name}",
            f"📞 Telefon: {qr.phone}",
        ]
        rows = [
            ("Marka", qr.brand),
            ("Model", qr.model),
            ("Yıl", qr.year),
            ("Hafıza", qr.storage),
            ("Durum", qr.condition),
        ]
    else:
        lines = [
            "Merhaba, aşağıdaki ürün için fiyat teklifi almak istiyorum. 🛒",
            "",
            f"👤 Ad Soyad: {qr.name}",
            f"📞 Telefon: {qr.phone}",
        ]
        rows = [
            ("Ürün / Model", qr.model or (qr.product.name if qr.product else "")),
            ("Marka", qr.brand),
            ("Hafıza", qr.storage),
            ("Renk/Tercih", qr.condition),
        ]

    for label, value in rows:
        if value:
            lines.append(f"• {label}: {value}")
    if qr.note:
        lines += ["", f"📝 Not: {qr.note}"]
    return "\n".join(lines)


def service_message(sr) -> str:
    """ServiceRequest için WhatsApp mesaj metni."""
    lines = [
        "Merhaba, teknik servis / tamir talebim var. 🛠️",
        "",
        f"👤 Ad Soyad: {sr.name}",
        f"📞 Telefon: {sr.phone}",
        f"📱 Cihaz: {sr.device}",
        f"⚠️ Arıza: {sr.issue}",
    ]
    if sr.note:
        lines += ["", f"📝 Not: {sr.note}"]
    return "\n".join(lines)


def contact_message(cm) -> str:
    """ContactMessage için WhatsApp mesaj metni."""
    lines = [
        "Merhaba, iletişime geçmek istiyorum. 👋",
        "",
        f"👤 Ad Soyad: {cm.name}",
    ]
    if cm.phone:
        lines.append(f"📞 Telefon: {cm.phone}")
    if cm.email:
        lines.append(f"✉️ E-posta: {cm.email}")
    lines += ["", f"💬 Mesaj: {cm.message}"]
    return "\n".join(lines)
