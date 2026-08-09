from django.core.management.base import BaseCommand
from django.db import transaction

from apps.stock.models import Accessory, Device, Sale
from apps.stock.services import _resync_accessory_qty


class Command(BaseCommand):
    help = ("Önbelleklenmiş toplamları kaynak satırlardan yeniden hesaplar: "
            "aksesuar stok adedi, fiş toplamları ve cihaz satış alanları.")

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Değişiklikleri yazmadan farkları listeler.")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        fixed = {"accessory": 0, "sale": 0, "device": 0}

        with transaction.atomic():
            for accessory in Accessory.objects.all():
                ledger = sum(accessory.movements.values_list("quantity", flat=True))
                if accessory.stock_qty != ledger:
                    self.stdout.write(
                        f"AKSESUAR {accessory.sku}: {accessory.stock_qty} -> {ledger}")
                    fixed["accessory"] += 1
                    if not dry:
                        _resync_accessory_qty(accessory)

            for sale in Sale.objects.prefetch_related("items", "payments", "trade_ins"):
                before = (sale.grand_total, sale.trade_in_total,
                          sale.payable_total, sale.paid_total)
                sale.recalculate(commit=False)
                after = (sale.grand_total, sale.trade_in_total,
                         sale.payable_total, sale.paid_total)
                if before != after:
                    self.stdout.write(f"FİŞ {sale.receipt_no}: {before} -> {after}")
                    fixed["sale"] += 1
                    if not dry:
                        sale.save(update_fields=["grand_total", "trade_in_total",
                                                 "payable_total", "paid_total",
                                                 "updated_at"])

            for device in Device.objects.filter(status=Device.Status.SATILDI):
                item = device.sale_items.filter(returned_at__isnull=True).first()
                if item is None:
                    self.stdout.write(
                        f"CİHAZ {device.stock_code}: satıldı görünüyor ama aktif "
                        f"satış satırı yok")
                    fixed["device"] += 1
                    if not dry:
                        device.status = Device.Status.STOKTA
                        device.sold_to = None
                        device.sold_at = None
                        device.sold_price = None
                        device.days_in_stock = None
                        device.save(update_fields=["status", "sold_to", "sold_at",
                                                   "sold_price", "days_in_stock",
                                                   "updated_at"])

            if dry:
                transaction.set_rollback(True)

        total = sum(fixed.values())
        label = "Bulunan" if dry else "Düzeltilen"
        self.stdout.write(self.style.SUCCESS(
            f"{label}: {fixed['accessory']} aksesuar, {fixed['sale']} fiş, "
            f"{fixed['device']} cihaz (toplam {total})."
        ))
        if total == 0:
            self.stdout.write("Tüm toplamlar tutarlı.")
