"""Stok view'ları için ortak yardımcılar."""

import json
import re

from django.core.paginator import Paginator
from django.http import HttpResponse

from apps.dashboard.utils import (  # noqa: F401  (view modülleri buradan alır)
    preselected,
    safe_next,
    with_param,
)
from apps.stock.permissions import (  # noqa: F401  (view modülleri buradan alır)
    access_required,
    can_manage_stock,
    can_see_money,
    deny,
    has_access,
    is_patron,
    money_required,
    panel_required,
    patron_required,
)

PAGE_SIZE = 25


def is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def paginate(queryset, request, per_page=PAGE_SIZE):
    return Paginator(queryset, per_page).get_page(request.GET.get("sayfa") or 1)


def querystring(request, drop=("sayfa",)):
    """Mevcut GET parametrelerini sayfa numarası olmadan yeniden kodlar.

    Filtre bağlantılarını elle `?durum={{ durum }}&marka={{ marka }}` diye
    kurmak, bir parametre eklendiğinde altı ayrı yerde unutulmasına yol açar.
    """
    params = request.GET.copy()
    for key in drop:
        params.pop(key, None)
    return params.urlencode()


def pick_template(request, partial: str, full: str) -> str:
    """htmx isteğinde parçayı, normal gezinmede tam sayfayı render eder."""
    return partial if is_htmx(request) else full


def quick_target(request, default: str) -> str:
    """Pop-up'ın kaydı ekleyeceği <select>'in id'si (`?alan=id_supplier`).

    Değer JS'te `getElementById`'ye gider ve şablona yazılır; yalnızca
    Django'nun ürettiği biçimdeki id'ler kabul edilir.
    """
    field_id = request.GET.get("alan", "")
    return field_id if re.fullmatch(r"id_\w{1,60}", field_id, re.ASCII) else default


def created_response(field_id: str, obj, *, search: str = "", hint: str = "") -> HttpResponse:
    """Pop-up'ta kaydedilen kaydı çağıran formun seçim kutusuna gönderir.

    Gövde boştur (pop-up içeriği temizlenir); static/js/combobox.js
    `bayco:created` olayında seçeneği <select>'e ekleyip seçer. Etiket
    str(obj)'dir, ModelChoiceField'ın seçenek etiketiyle aynı. json.dumps
    varsayılanı (ensure_ascii) ş/ğ/ı'yı \\u kaçışına çevirir: latin-1 dışı
    karakter HTTP başlığında MIME kodlanır ve htmx JSON'u okuyamazdı.
    """
    response = HttpResponse("")
    response["HX-Trigger"] = json.dumps({"bayco:created": {
        "field": field_id, "value": str(obj.pk), "label": str(obj),
        "search": search, "hint": hint,
    }})
    return response
