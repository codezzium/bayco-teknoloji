"""Etiket baskı sayfası.

Baskı gerçekliği (patrona söylenmeli): termal etiket yazıcısına ancak o
makinede vendor sürücüsü kuruluysa basılabilir; iOS'ta sürücü modeli olmadığı
için termal baskı MÜMKÜN DEĞİLDİR. Etiket baskısı masaüstü/kasa iş akışıdır,
telefon iş akışı taramadır. Ayrıca Safari @page{size} kuralını yok sayar —
Chrome/Edge uyar.
"""

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from ..labels import DEFAULT_FORMAT, LABEL_FORMATS, MAX_COPIES, MAX_LABELS, build_label
from ..labels import paginate_labels
from ..models import Accessory, Device
from ..niimbot import label_image, to_png
from .base import panel_required

NIIMBOT_KINDS = {
    "aksesuar": Accessory.objects.select_related("brand"),
    "cihaz": Device.objects.select_related("device_model__brand"),
}


@panel_required
def label_print(request):
    key = request.GET.get("format", DEFAULT_FORMAT)
    fmt = LABEL_FORMATS.get(key) or LABEL_FORMATS[DEFAULT_FORMAT]

    try:
        copies = min(max(int(request.GET.get("copies") or 1), 1), MAX_COPIES)
    except ValueError:
        copies = 1

    device_ids = [i for i in request.GET.getlist("ids") if i.isdigit()]
    accessory_ids = [i for i in request.GET.getlist("acc") if i.isdigit()]
    show_price = request.GET.get("fiyat", "1") == "1"

    objects = []
    if device_ids:
        found = {d.pk: d for d in Device.objects.select_related(
            "device_model__brand").filter(pk__in=device_ids)}
        objects += [found[int(i)] for i in device_ids if int(i) in found]
    if accessory_ids:
        found = {a.pk: a for a in Accessory.objects.select_related("brand")
                 .filter(pk__in=accessory_ids)}
        objects += [found[int(i)] for i in accessory_ids if int(i) in found]

    truncated = len(objects) > MAX_LABELS
    objects = objects[:MAX_LABELS]

    labels = []
    for obj in objects:
        label = build_label(obj, fmt, show_price=show_price)
        labels.extend([label] * copies)

    return render(request, "stock/labels/print.html", {
        "fmt": fmt, "fmt_key": key, "formats": LABEL_FORMATS,
        "pages": paginate_labels(labels, fmt),
        "count": len(labels),
        "truncated": truncated, "max_labels": MAX_LABELS,
        "auto": request.GET.get("auto") == "1",
        "back_url": request.META.get("HTTP_REFERER") or reverse("stock:device_list"),
    })


@panel_required
def niimbot_png(request, kind, pk):
    """Niimbot termal etiketi (40×12 mm PNG); niim-agent bunu olduğu gibi basar."""
    queryset = NIIMBOT_KINDS.get(kind)
    if queryset is None:
        raise Http404
    obj = get_object_or_404(queryset, pk=pk)
    image = label_image(obj, show_price=request.GET.get("fiyat", "1") == "1")
    return HttpResponse(to_png(image), content_type="image/png")
