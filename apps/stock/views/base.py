"""Stok view'ları için ortak yardımcılar."""

from django.core.paginator import Paginator

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
