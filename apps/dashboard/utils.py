"""Panel formları arasında gidiş-dönüş (`?next=`) yardımcıları.

Bir cihaz kaydedilirken modelinin, model kaydedilirken markasının tanımlı
olmadığı sık görülür. Kullanıcıyı "önce şu menüden şunu ekleyin" diye
yollamak yerine, seçim alanının altına bir kısayol konur; ara form
kaydedildiğinde çağıran forma yeni kayıt SEÇİLİ olarak dönülür.

Buradaki üç fonksiyon o zincirin tamamıdır ve hem dashboard hem stock
tarafından kullanılır (stock zaten dashboard.forms'a bağımlıdır, ters yön
döngüsel içe aktarma yaratır).
"""

from urllib.parse import urlencode

from django.utils.html import format_html

#: Dönüş adresleri yalnızca panel içine bakabilir. Bu önek hem dış alan
#: adlarını hem de `//saldirgan.example` biçimindeki protokole göreli
#: adresleri eler, yani açık yönlendirme (open redirect) kapalıdır.
PANEL_PREFIX = "/panel/"


def safe_next(request) -> str:
    """`?next=` / gizli `next` alanını doğrular; geçersizse boş döner."""
    url = request.POST.get("next") or request.GET.get("next", "")
    return url if url.startswith(PANEL_PREFIX) else ""


def with_param(url: str, name: str, value) -> str:
    """Dönüş adresine yeni kaydın kimliğini ekler.

    Aynı ad ikinci kez eklenirse QueryDict.get sonuncuyu verir; tekrarlanan
    ekleme sonrası da en son oluşturulan kayıt seçili gelir.
    """
    return f"{url}{'&' if '?' in url else '?'}{name}={value}"


def preselected(request, *names) -> dict:
    """`?alan=<pk>` biçiminde dönen seçimleri form `initial`'ına çevirir.

    Rakam süzgeci şart: uydurma bir değer initial'a girseydi ModelChoiceField
    onu seçili gösteremez ama form yine de o değerle render edilirdi.
    """
    return {name: request.GET[name] for name in names
            if request.GET.get(name, "").isdigit()}


def define_link(create_url: str, back_url: str, label: str):
    """Seçim alanının altına "listede yoksa ekle" kısayolu üretir.

    Dönen değer form alanının help_text'idir; panel form şablonları help_text'i
    `|safe` ile basar, bu yüzden format_html ile kaçışlanmış olması şarttır.
    """
    target = f"{create_url}?{urlencode({'next': back_url})}"
    return format_html(
        'Listede yok mu? <a href="{}" class="underline" '
        'style="color:var(--ink)">Yeni {} ekleyin</a> — kaydettiğinizde bu '
        'forma seçili olarak dönersiniz.',
        target, label,
    )
