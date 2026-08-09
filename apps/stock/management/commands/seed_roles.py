"""Patron / Personel gruplarını kurar.

Neden data migration DEĞİL: Meta.permissions satırlarını (stock.view_money,
stock.manage_stock) django.contrib.auth'un post_migrate handler'ı yaratır ve o
handler aynı `migrate` koşusundaki TÜM migration'lardan sonra çalışır. Bir
RunPython içinde bu izinler henüz mevcut olmadığı için sessizce atlanırdı.

Idempotent — her deploy sonrası çalıştırılabilir:
    python manage.py migrate && python manage.py seed_roles
"""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.stock.permissions import GROUP_PATRON, GROUP_PERSONEL

# Personel: stoğu görür, satış yapar, tahsilat girer, cari ekler.
# GÖREMEZ: maliyet, kâr, ciro (view_money yok), giderler, silme yetkisi.
PERSONEL_PERMS = [
    "stock.view_device",
    "stock.change_device",
    "stock.add_device",
    "stock.view_devicemodel",
    "stock.add_devicemodel",
    "stock.view_accessory",
    "stock.change_accessory",
    "stock.add_accessory",
    "stock.view_accessorycategory",
    "stock.view_contact",
    "stock.add_contact",
    "stock.change_contact",
    "stock.view_sale",
    "stock.add_sale",
    "stock.change_sale",
    "stock.view_saleitem",
    "stock.add_saleitem",
    "stock.view_payment",
    "stock.add_payment",
    "stock.view_stockmovement",
    "stock.add_stockmovement",
    "stock.view_tradein",
    "stock.add_tradein",
    "stock.view_devicestatuslog",
    "stock.manage_stock",
]


class Command(BaseCommand):
    help = "Patron ve Personel gruplarını oluşturur / izinlerini günceller."

    @transaction.atomic
    def handle(self, *args, **options):
        stock_perms = Permission.objects.filter(
            content_type__app_label="stock"
        ).select_related("content_type")
        catalog_perms = Permission.objects.filter(content_type__app_label="catalog")

        if not stock_perms.exists():
            self.stderr.write(self.style.ERROR(
                "stock izinleri bulunamadı. Önce `manage.py migrate` çalıştırın."
            ))
            return

        # --- Patron: her şey ---
        patron, _ = Group.objects.get_or_create(name=GROUP_PATRON)
        patron.permissions.set(list(stock_perms) + list(catalog_perms))

        # --- Personel: sınırlı liste ---
        wanted = set(PERSONEL_PERMS)
        found, by_label = [], {}
        for perm in stock_perms:
            by_label[f"stock.{perm.codename}"] = perm
        missing = []
        for label in sorted(wanted):
            perm = by_label.get(label)
            if perm is None:
                missing.append(label)
            else:
                found.append(perm)

        personel, _ = Group.objects.get_or_create(name=GROUP_PERSONEL)
        personel.permissions.set(found)

        self.stdout.write(self.style.SUCCESS(
            f"{GROUP_PATRON}: {patron.permissions.count()} izin · "
            f"{GROUP_PERSONEL}: {personel.permissions.count()} izin"
        ))
        if missing:
            self.stderr.write(self.style.WARNING(
                "Bulunamayan izinler (model adı değişmiş olabilir): "
                + ", ".join(missing)
            ))
        self.stdout.write(
            "Hatırlatma: Personel hesapları is_staff=False olmalıdır, aksi halde "
            "/yonetim/ üzerinden maliyet bilgisine erişirler."
        )
