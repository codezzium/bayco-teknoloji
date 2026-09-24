"""Mevcut Personel üyelerine, bu sürümden ÖNCE zaten sahip oldukları
erişimlerin tiklerini verir; deploy anında dükkân işleyişi bozulmasın.

Önceden herkese açık olan: Talepler, Cariler, İçerik (Duyurular/Ürünler/
Yorumlar/SSS), kasada fiyat/indirim/takas. "Silme, iptal, iade" VERİLMEZ:
önceden yalnızca iade açıktı, silme ve iptal kapalıydı; güvenlik tiki
bilinçli olarak kapalı başlar ve Patron gerekirse açar.

İzin satırları henüz yoktur (Django onları bu migrate koşusunun SONUNDA,
post_migrate'te yaratır); bu yüzden burada get_or_create edilir. post_migrate
eksikleri (content_type, codename) çiftine göre eklediğinden çakışmaz.
Codename'ler bilinçli olarak sabit yazıldı: migration, access.py'nin
ileride değişecek halini değil, bugünkü durumu yansıtmalı.
"""

from django.conf import settings
from django.db import migrations

PRESERVED = [
    ("access_leads", "Talepler"),
    ("access_contacts", "Cariler"),
    ("manage_content", "İçerik ve Site Ayarları"),
    ("change_prices", "Kasada fiyat, indirim ve takas"),
]


def grant(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")

    group = Group.objects.filter(name="Personel").first()
    if group is None:
        return
    users = list(User.objects.filter(groups=group))
    if not users:
        return
    content_type, _ = ContentType.objects.get_or_create(app_label="staff",
                                                        model="panelaccess")
    perms = [Permission.objects.get_or_create(content_type=content_type,
                                              codename=codename,
                                              defaults={"name": name})[0]
             for codename, name in PRESERVED]
    for user in users:
        user.user_permissions.add(*perms)


class Migration(migrations.Migration):

    dependencies = [
        ("staff", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [migrations.RunPython(grant, migrations.RunPython.noop)]
