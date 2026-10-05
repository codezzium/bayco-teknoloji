"""Teknik servis şablon yardımcıları."""

from django import template

register = template.Library()

_TONES = {
    "kabul": ("rgba(60,150,245,.15)", "#9cccff", "rgba(60,150,245,.3)"),
    "inceleme": ("rgba(245,180,60,.15)", "#ffd48a", "rgba(245,180,60,.3)"),
    "onay": ("rgba(245,180,60,.15)", "#ffd48a", "rgba(245,180,60,.3)"),
    "tamirde": ("rgba(122,62,166,.2)", "#d2b3ec", "rgba(122,62,166,.35)"),
    "dis_servis": ("rgba(180,53,127,.18)", "#f3a6d2", "rgba(180,53,127,.35)"),
    "hazir": ("rgba(37,211,102,.15)", "#7ff0ab", "rgba(37,211,102,.3)"),
    "teslim": ("rgba(255,255,255,.08)", "#cfc4dd", "rgba(255,255,255,.15)"),
    "iade": ("rgba(226,58,72,.15)", "#ff8b95", "rgba(226,58,72,.3)"),
    # Teknik servis işi durumları
    "gonderildi": ("rgba(180,53,127,.18)", "#f3a6d2", "rgba(180,53,127,.35)"),
    "dondu": ("rgba(37,211,102,.15)", "#7ff0ab", "rgba(37,211,102,.3)"),
    "iptal": ("rgba(255,255,255,.08)", "#cfc4dd", "rgba(255,255,255,.15)"),
}


@register.simple_tag
def service_tone(status):
    """Servis/teknik servis durum rozetinin (zemin, yazı, kenar) renkleri."""
    return _TONES.get(status, _TONES["teslim"])
