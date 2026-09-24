"""Türkçe yazılan sayılar: binlik nokta, ondalık virgül.

Panelde tutar alanları yazılırken biçimlenir (static/js/fields.js):
18500 → "18.500", 18500,9 → "18.500,90". Sunucu bu biçimi ve eski/ham biçimi
("18500.90") aynı sonuca çevirmeli; en kritik durum "18.500"ün 18,5 değil
18500 okunmasıdır. Ayrıştırma ve biçimlendirmenin TEK kaynağı burası.
"""

import re
from decimal import Decimal, InvalidOperation

# Nokta yalnızca binlik ayırıcı düzenindeyse atılır: 1–3 hane, ardından üçlü gruplar.
_THOUSANDS = re.compile(r"-?\d{1,3}(\.\d{3})+")


def normalize_decimal_input(raw) -> str:
    """Kullanıcının yazdığı sayıyı Decimal'in anladığı biçime çevirir.

    "18.500" → "18500", "18.500,90" → "18500.90", "150,90" → "150.90",
    "150.90" → "150.90" (virgülsüz ve binlik düzeninde olmayan nokta ondalıktır).
    """
    text = str(raw).strip().replace(" ", "").replace(" ", "").replace("₺", "")
    if "," in text:
        return text.replace(".", "").replace(",", ".")
    if _THOUSANDS.fullmatch(text):
        return text.replace(".", "")
    return text


def format_decimal_input(value, decimals: int = 2) -> str:
    """Input'a konacak değer: 18500 → "18.500", 150.9 → "150,90".

    Kuruş sıfırsa yazılmaz. Metin olduğu gibi döner: hatalı form yeniden
    gösterilirken kullanıcının yazdığı kaybolmasın.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return str(value)
    number = number.quantize(Decimal(1).scaleb(-decimals)) if decimals else number.quantize(Decimal(1))
    sign = "-" if number < 0 else ""
    integer, _, fraction = f"{abs(number):f}".partition(".")
    grouped = f"{int(integer):,}".replace(",", ".")
    if fraction and fraction.strip("0"):
        return f"{sign}{grouped},{fraction}"
    return f"{sign}{grouped}"
