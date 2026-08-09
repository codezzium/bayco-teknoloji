"""Şablon yardımcıları: TL biçimlendirme ve widget tipi tespiti."""

from decimal import Decimal, InvalidOperation

from django import forms
from django import template

register = template.Library()


@register.filter
def tl(value, decimals=2):
    """Türkçe para biçimi: 18500.5 -> '18.500,50 ₺'. None -> '—'."""
    if value is None or value == "":
        return "—"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return value
    quantized = f"{amount:,.{int(decimals)}f}"
    # en-US ayırıcılarını TR'ye çevir: 18,500.50 -> 18.500,50
    turkish = quantized.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{turkish} ₺"


@register.filter
def tl0(value):
    """Ondalıksız TL: 18500 -> '18.500 ₺'. Liste ekranlarında daha okunur."""
    return tl(value, 0)


@register.filter
def pct(value, decimals=1):
    if value is None:
        return "—"
    try:
        return f"%{Decimal(str(value)):.{int(decimals)}f}".replace(".", ",")
    except (InvalidOperation, ValueError):
        return "—"


@register.filter
def is_checkbox(field):
    return isinstance(field.field.widget, forms.CheckboxInput)


@register.filter
def is_wide(field):
    """Textarea ve gizli olmayan geniş alanlar formda iki sütun kaplar."""
    return isinstance(field.field.widget, forms.Textarea)


@register.filter
def is_hidden_widget(field):
    return isinstance(field.field.widget, forms.HiddenInput)


@register.simple_tag
def status_tone(status):
    """Cihaz durumuna göre rozet rengi."""
    return {
        "stokta": ("rgba(37,211,102,.15)", "#7ff0ab", "rgba(37,211,102,.3)"),
        "rezerve": ("rgba(245,180,60,.15)", "#ffd48a", "rgba(245,180,60,.3)"),
        "satildi": ("rgba(122,62,166,.2)", "#d2b3ec", "rgba(122,62,166,.35)"),
        "iade": ("rgba(255,255,255,.08)", "#cfc4dd", "rgba(255,255,255,.15)"),
        "serviste": ("rgba(60,150,245,.15)", "#9cccff", "rgba(60,150,245,.3)"),
        "kayip": ("rgba(226,58,72,.15)", "#ff8b95", "rgba(226,58,72,.3)"),
    }.get(status, ("rgba(255,255,255,.08)", "#cfc4dd", "rgba(255,255,255,.15)"))
