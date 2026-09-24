"""Stok modülü yardımcıları — saf fonksiyonlar, Django modeli import etmez."""

import calendar
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from apps.dashboard.numbers import normalize_decimal_input

# ---------------------------------------------------------------------------
# Para yuvarlama
# ---------------------------------------------------------------------------
# Django'nun SQLite backend'i DecimalField sonucunu YALNIZCA doğrudan sütun
# okumasında (Col) kuruşa yuvarlar; Sum/Coalesce gibi her ifade
# create_decimal_from_float'tan yuvarlanmadan geçer
# (django/db/backends/sqlite3/operations.py:340-344). Sonuç: bir toplam
# 18902.7000000000 olarak döner ve şablonda öyle görünür.
#
# Bu yüzden bir aggregate sonucu modele yazılıyorsa veya ekrana basılıyorsa
# MUTLAKA money() içinden geçirilir.
CENT = Decimal("0.01")
ZERO_TL = Decimal("0.00")
MONEY_MAX = Decimal("9999999999.99")
MAX_QTY = 99_999


def money(value) -> Decimal:
    """Aggregate sonucunu kuruşa yuvarlar; None'ı 0.00 yapar."""
    if value is None:
        return ZERO_TL
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_money(raw) -> Decimal | None:
    """Türkçe yazılmış tutar: "18.500" → 18500, "18.500,90" → 18500.90, "150,90" → 150.90.

    Eskiden virgül noktaya çevriliyordu; "18.500" 18,5 okunurdu. Biçim kuralları
    apps.dashboard.numbers'ta, panel formlarıyla ortak.
    """
    try:
        value = Decimal(normalize_decimal_input(raw or "0"))
    except InvalidOperation:
        return None
    if not value.is_finite() or abs(value) > MONEY_MAX:
        return None
    return value

# ---------------------------------------------------------------------------
# Türkçe arama katlaması
# ---------------------------------------------------------------------------
# SQLite'ın yerleşik upper()/lower() fonksiyonları YALNIZCA ASCII üzerinde
# çalışır. Django'nun __icontains'i SQLite'ta "LIKE UPPER(...)" ürettiği için
# "sarj" araması "Şarj" kaydını bulamaz ve arama bozuk sanılır.
#
# Çözüm: aranabilir metni ASCII'ye katlayıp Device.search_blob alanında
# saklamak, sorguyu da aynı tablodan geçirip __contains kullanmak.
# Böylece iki taraf da küçük harf ASCII olur ve veritabanının harf
# büyüklüğü davranışına hiç bağımlı kalmayız.
_FOLD = str.maketrans({
    "İ": "i", "I": "i", "ı": "i",
    "Ş": "s", "ş": "s",
    "Ğ": "g", "ğ": "g",
    "Ü": "u", "ü": "u",
    "Ö": "o", "ö": "o",
    "Ç": "c", "ç": "c",
    "Â": "a", "â": "a",
    "Î": "i", "î": "i",
    "Û": "u", "û": "u",
})


def trfold(value: str) -> str:
    """Türkçe metni aranabilir ASCII biçimine indirger: 'Şarj Kablosu' -> 'sarj kablosu'.

    Katlama .lower()'dan ÖNCE yapılır; Python'un .lower()'ı noktasız I'yı ters
    yönde yanlış çevirir ("I".lower() == "i", oysa Türkçede "ı" olmalıdır).
    Burada zaten her iki I varyantını da "i"ye indirdiğimiz için sorun kalmaz.
    """
    return (value or "").translate(_FOLD).lower()


def digits_only(value: str) -> str:
    """Yalnızca rakamları bırakır (IMEI/barkod temizliği)."""
    return "".join(ch for ch in (value or "") if ch.isdigit())


# ---------------------------------------------------------------------------
# Okutulan kodun temizlenmesi
# ---------------------------------------------------------------------------
# Bazı el terminalleri barkodun önüne AIM tanımlayıcısı ekler (]C1, ]E0, ]Q1…).
_AIM = re.compile(r"^\](?:C1|E0|d1|Q1|A0|X0)")


def normalize_scan(raw: str) -> str:
    """Okuyucudan/kameradan gelen ham değeri arama anahtarına indirger."""
    code = (raw or "").strip().strip("\x00\r\n\t")
    code = _AIM.sub("", code)
    # QR bir URL taşıyorsa (başka bir sistemin etiketi olabilir) son segmenti al
    if "://" in code:
        code = code.rstrip("/").rsplit("/", 1)[-1]
    return code.strip().upper()


# ---------------------------------------------------------------------------
# Tarih aritmetiği
# ---------------------------------------------------------------------------

def add_months(start: date | None, months: int | None) -> date | None:
    """Tarihe ay ekler, ay sonunu kırparak.

    31 Ocak + 1 ay -> 28/29 Şubat. timedelta(days=30*n) kullanmak YANLIŞTIR ve
    doğrudan garanti tartışması üretir (12 ay = 360 gün olurdu).
    """
    if not start or not months:
        return None
    year, month = divmod(start.month - 1 + int(months), 12)
    year += start.year
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last_day))


# ---------------------------------------------------------------------------
# Kod üreteci
# ---------------------------------------------------------------------------

def next_code(key: str, prefix: str, width: int = 6) -> str:
    """Sıradaki stok/fiş kodunu üretir: next_code("device", "BYC") -> "BYC-000123".

    MUTLAKA bir transaction içinde çağrılmalıdır (servis fonksiyonları zaten
    @transaction.atomic). Counter satırı select_for_update ile kilitlenir;
    SQLite'ta bu no-op olsa da DATABASES OPTIONS'taki transaction_mode
    "IMMEDIATE" yazma kilidini BEGIN anında aldığı için sıra numarası
    yarış koşulundan etkilenmez.

    max(pk)+1 kullanılmaz: kayıt silindiğinde numara geri döner ve daha önce
    basılmış bir etiketle çakışır.
    """
    from .models import Counter  # döngüsel import'u önlemek için gecikmeli

    counter = Counter.objects.select_for_update().filter(pk=key).first()
    if counter is None:
        counter = Counter.objects.create(key=key, value=0)
    counter.value += 1
    counter.save(update_fields=["value"])
    return f"{prefix}-{counter.value:0{width}d}"
