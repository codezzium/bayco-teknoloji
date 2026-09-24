"""Personel yönetimi, şifre değiştirme ve hareket kayıtları."""

import csv
from datetime import datetime, time

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.stock.permissions import (
    ACCESS,
    PANEL_GROUPS,
    is_patron,
    panel_required,
    patron_required,
)
from apps.stock.views.base import paginate, pick_template, querystring

from .actions import field_label
from .forms import StaffForm, StyledPasswordChangeForm, granted_keys
from .models import ActivityLog

User = get_user_model()


# ---------- Personel ----------

@patron_required
def staff_list(request):
    users = (User.objects
             .filter(Q(is_superuser=True) | Q(is_staff=True)
                     | Q(groups__name__in=PANEL_GROUPS))
             .distinct()
             .prefetch_related("groups")
             .order_by("-is_active", "username"))
    rows = []
    for user in users:
        patron = is_patron(user)
        keys = granted_keys(user)
        rows.append({
            "user": user,
            "patron": patron,
            "labels": [] if patron else [item.label for key, item in ACCESS.items()
                                         if key in keys],
        })
    return render(request, "staff/staff_list.html", {
        "active": "personel", "title": "Personel", "singular": "Personel",
        "rows": rows, "total": len(rows),
        "create_url": reverse("staff:create"),
    })


@patron_required
def staff_form(request, pk=None):
    instance = get_object_or_404(User, pk=pk) if pk else None
    if request.method == "POST":
        form = StaffForm(request.POST, instance=instance, acting_user=request.user)
        if form.is_valid():
            user = form.save()
            request.audit = {"target": user.get_username(), "detail": form.changes}
            messages.success(request, f"{user.get_username()} kaydedildi.")
            return redirect("staff:list")
    else:
        form = StaffForm(instance=instance, acting_user=request.user)
    return render(request, "staff/staff_form.html", {
        "active": "personel", "form": form, "title": "Personel",
        "singular": "Personel", "is_edit": instance is not None,
        "back_url": reverse("staff:list"),
    })


@panel_required
def password_change(request):
    if request.method == "POST":
        form = StyledPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            # Şifre değişince oturum hash'i değişir; bu satır olmadan kullanıcı
            # kendi değişikliğiyle oturumdan atılır.
            update_session_auth_hash(request, user)
            messages.success(request, "Şifreniz değiştirildi.")
            return redirect("dashboard:home")
    else:
        form = StyledPasswordChangeForm(request.user)
    return render(request, "staff/password.html", {"active": "", "form": form})


# ---------- Hareket kayıtları ----------

def _day_bounds(value, end=False):
    day = parse_date(value or "") if value else None
    if day is None:
        return None
    return timezone.make_aware(datetime.combine(day, time.max if end else time.min))


def _filtered_logs(request):
    logs = ActivityLog.objects.select_related("user")
    user_id = request.GET.get("kullanici", "")
    kind = request.GET.get("tur", "")
    query = request.GET.get("q", "").strip()
    start = _day_bounds(request.GET.get("baslangic"))
    end = _day_bounds(request.GET.get("bitis"), end=True)

    if user_id.isdigit():
        logs = logs.filter(user_id=int(user_id))
    if kind in ActivityLog.Kind.values:
        logs = logs.filter(kind=kind)
    if start:
        logs = logs.filter(at__gte=start)
    if end:
        logs = logs.filter(at__lte=end)
    if query:
        logs = logs.filter(Q(action__icontains=query) | Q(target__icontains=query)
                           | Q(username__icontains=query))
    return logs


@patron_required
def log_list(request):
    logs = _filtered_logs(request)
    if request.GET.get("format") == "csv":
        return _csv_response(logs)

    page = paginate(logs, request, per_page=50)
    for log in page:
        log.detail_rows = [(field_label(key), value) for key, value in
                           (log.detail or {}).items()]
    return render(request, pick_template(request, "staff/partials/log_rows.html",
                                         "staff/log_list.html"), {
        "active": "loglar", "title": "Hareket Kayıtları",
        "page": page, "total": page.paginator.count,
        "kullanici": request.GET.get("kullanici", ""),
        "tur": request.GET.get("tur", ""),
        "q": request.GET.get("q", ""),
        "baslangic": request.GET.get("baslangic", ""),
        "bitis": request.GET.get("bitis", ""),
        "qs": querystring(request),
        "csv_qs": querystring(request, drop=("sayfa", "format")),
        "kinds": ActivityLog.Kind.choices,
        "users": User.objects.filter(activity_logs__isnull=False).distinct()
                             .order_by("username"),
    })


class _Echo:
    def write(self, value):
        return value


def _csv_response(logs):
    """Excel (TR) uyumlu CSV: UTF-8 BOM + `;` ayırıcı.

    Türkçe Excel ondalık ayırıcı olarak virgül kullandığı için CSV'de `;`
    bekler; BOM olmadan da "ş, ğ, ı" bozuk görünür.
    """
    writer = csv.writer(_Echo(), delimiter=";")

    def rows():
        yield "﻿"
        yield writer.writerow(["Zaman", "Kullanıcı", "Tür", "İşlem", "Kayıt",
                               "Girilen değerler", "IP", "Cihaz"])
        for log in logs.iterator(chunk_size=500):
            detail = " | ".join(f"{field_label(key)}: {value}"
                                for key, value in (log.detail or {}).items())
            yield writer.writerow([
                timezone.localtime(log.at).strftime("%d.%m.%Y %H:%M:%S"),
                log.username, log.get_kind_display(), log.action, log.target,
                detail, log.ip or "", log.user_agent,
            ])

    filename = f"hareket-kayitlari-{timezone.localdate():%Y-%m-%d}.csv"
    return StreamingHttpResponse(
        rows(), content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})
