"""Paneldeki her POST'u hareket kaydına yazar.

Neden middleware: her view'a elle log satırı eklemek, eklenmesi unutulan her
yeni view'ı sessizce kayıt dışı bırakırdı. Burada kapsam "/panel/ altındaki
her POST"tur; etiketler apps/staff/actions.py'den gelir.

View'lar kayda bilgi ekleyebilir:
    request.audit = {"target": obj_or_text, "target_url": url, "detail": {...}}
"""

from django.urls import reverse

from apps.stock.permissions import in_panel

from . import audit
from .actions import FORM_PAGES, describe
from .models import ActivityLog

SKIP_VIEWS = {"dashboard:login", "dashboard:logout"}


class ActivityLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.prefix = reverse("dashboard:home")  # "/panel/"

    def __call__(self, request):
        response = self.get_response(request)
        info = getattr(request, "_activity_info", None)
        if info is not None and not getattr(request, "_activity_logged", False):
            self._write(request, response, info)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method != "POST" or not request.path.startswith(self.prefix):
            return
        match = request.resolver_match
        if match is None or match.view_name in SKIP_VIEWS:
            return
        if not in_panel(request.user):
            return
        # Hedefin adı view'dan ÖNCE okunur: silme sonrası kayıt artık yoktur.
        request._activity_info = describe(request)

    def _write(self, request, response, info):
        extra = getattr(request, "audit", None) or {}
        detail = audit.sanitize_post(request)
        detail.update(extra.get("detail") or {})
        target_url = (extra.get("target_url")
                      or response.headers.get("HX-Redirect")
                      or (response.headers.get("Location")
                          if 300 <= response.status_code < 400 else "")
                      or "")
        if not target_url.startswith(self.prefix):
            target_url = ""
        action = info.label
        # Tam sayfa form POST'u 200 dönüyorsa form hatayla yeniden çizilmiştir
        # (başarılı kayıt yönlendirir). htmx parçaları ise başarıda da 200 döner.
        if (response.status_code == 200 and info.view_name in FORM_PAGES
                and request.headers.get("HX-Request") != "true"):
            action += " (form hatalı, kaydedilmedi)"
        audit.record(
            kind=ActivityLog.Kind.ISLEM,
            action=action,
            request=request,
            target=extra.get("target") or info.target,
            target_url=target_url,
            view_name=info.view_name,
            detail=detail,
            status_code=response.status_code,
        )
