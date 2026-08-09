"""Servis katmanının para aritmetiğini ve iş kurallarını doğrular.

Buradaki senaryolar plandaki uçtan uca doğrulama listesinin otomatikleştirilmiş
hâlidir; özellikle takas üçlüsü ve iade/bakiye hesabı elle test edilmesi kolay
unutulan yerlerdir.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Brand
from apps.stock import services
from apps.stock.models import (
    Accessory,
    Device,
    DeviceModel,
    Expense,
    Payment,
    Sale,
    SaleItem,
    StockMovement,
)
from apps.stock.utils import add_months, normalize_scan, trfold

TL = Decimal


class UtilsTests(TestCase):
    def test_add_months_clamps_month_end(self):
        # 31 Ocak + 1 ay = 28/29 Şubat; timedelta(days=30) yanlış sonuç verirdi
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(add_months(date(2024, 1, 31), 1), date(2024, 2, 29))
        self.assertEqual(add_months(date(2026, 3, 31), 1), date(2026, 4, 30))
        self.assertEqual(add_months(date(2026, 1, 15), 12), date(2027, 1, 15))
        self.assertEqual(add_months(date(2026, 12, 31), 2), date(2027, 2, 28))

    def test_add_months_returns_none_without_input(self):
        self.assertIsNone(add_months(None, 12))
        self.assertIsNone(add_months(date(2026, 1, 1), 0))

    def test_turkish_search_folding(self):
        # SQLite'ın upper()'ı ASCII-only olduğu için arama bu katlamaya bağlı
        self.assertEqual(trfold("Şarj Kablosu"), "sarj kablosu")
        self.assertEqual(trfold("İPHONE 13"), trfold("iphone 13"))
        self.assertEqual(trfold("Iphone"), trfold("ıphone"))
        self.assertEqual(trfold("Güç Bankası"), "guc bankasi")

    def test_normalize_scan_strips_aim_prefix_and_url(self):
        self.assertEqual(normalize_scan("]C1BYC-000123"), "BYC-000123")
        self.assertEqual(normalize_scan("https://x.tr/cihaz/BYC-000123/"), "BYC-000123")
        self.assertEqual(normalize_scan("  byc-000123\r\n"), "BYC-000123")


class StockTestCase(TestCase):
    """Ortak fikstür."""

    def setUp(self):
        self.user = User.objects.create_user("patron", password="x")
        self.brand = Brand.objects.create(name="Apple")
        self.model = DeviceModel.objects.create(brand=self.brand, name="iPhone 13")
        self.customer = services.Device  # placeholder, aşağıda gerçek cari
        from apps.stock.models import Contact
        self.customer = Contact.objects.create(full_name="Ahmet Yılmaz",
                                               phone="0532 111 22 33")

    def make_device(self, price="16000", **kw):
        kw.setdefault("device_model", self.model)
        kw.setdefault("purchase_price", TL(price))
        kw.setdefault("purchase_date", timezone.localdate() - timedelta(days=10))
        return services.create_device(user=self.user, **kw)

    def make_accessory(self, qty=10, cost="80", price="150.90", **kw):
        kw.setdefault("name", "Şarj Kablosu USB-C")
        accessory = Accessory.objects.create(cost=TL(cost), price=TL(price), **kw)
        if qty:
            services.receive_accessory_stock(accessory, qty, user=self.user,
                                             opening=True)
        accessory.refresh_from_db()
        return accessory


class DeviceSaleTests(StockTestCase):
    def test_device_sale_updates_status_stock_and_totals(self):
        device = self.make_device()
        device.list_price = TL("18500")
        device.save()
        accessory = self.make_accessory(qty=10)

        cart = {
            "customer_id": self.customer.pk,
            "lines": [
                {"lid": f"d-{device.pk}", "kind": "cihaz", "id": device.pk,
                 "name": device.label, "qty": 1, "unit": "18500.00"},
                {"lid": f"a-{accessory.pk}", "kind": "aksesuar", "id": accessory.pk,
                 "name": accessory.name, "qty": 2, "unit": "150.90"},
            ],
        }
        sale = services.create_sale_from_cart(cart, user=self.user)

        device.refresh_from_db()
        accessory.refresh_from_db()
        self.assertEqual(device.status, Device.Status.SATILDI)
        self.assertEqual(device.sold_to, self.customer)
        self.assertEqual(device.days_in_stock, 10)
        self.assertEqual(accessory.stock_qty, 8)
        # 18500 + 2×150.90 = 18801.80  — SQLite aggregate'i yuvarlanmış olmalı
        self.assertEqual(sale.grand_total, TL("18801.80"))
        self.assertEqual(str(sale.grand_total), "18801.80")
        self.assertEqual(sale.payable_total, TL("18801.80"))
        self.assertTrue(sale.receipt_no.startswith("BYC-S-"))

    def test_accessory_only_sale_needs_no_customer(self):
        accessory = self.make_accessory(qty=5)
        cart = {"lines": [{"lid": "a", "kind": "aksesuar", "id": accessory.pk,
                           "name": accessory.name, "qty": 1, "unit": "150.90"}]}
        sale = services.create_sale_from_cart(cart, user=self.user)
        self.assertIsNone(sale.customer)
        self.assertEqual(sale.grand_total, TL("150.90"))

    def test_device_sale_requires_customer(self):
        device = self.make_device()
        cart = {"lines": [{"lid": "d", "kind": "cihaz", "id": device.pk,
                           "name": device.label, "qty": 1, "unit": "18500"}]}
        with self.assertRaises(services.CustomerRequired):
            services.create_sale_from_cart(cart, user=self.user)
        device.refresh_from_db()
        # Doğrulama başarısız olunca HİÇBİR ŞEY değişmemeli
        self.assertEqual(device.status, Device.Status.STOKTA)

    def test_cannot_sell_same_device_twice(self):
        device = self.make_device()
        cart = {"customer_id": self.customer.pk,
                "lines": [{"lid": "d", "kind": "cihaz", "id": device.pk,
                           "name": device.label, "qty": 1, "unit": "18500"}]}
        services.create_sale_from_cart(cart, user=self.user)
        with self.assertRaises(services.DeviceNotAvailable):
            services.create_sale_from_cart(cart, user=self.user)

    def test_db_itself_blocks_a_second_active_line_for_one_device(self):
        """Servis atlansa bile veritabanı bir telefonun iki kez satılmasını reddeder."""
        device = self.make_device()
        sale_a = Sale.objects.create(sold_at=timezone.now())
        sale_b = Sale.objects.create(sold_at=timezone.now())
        SaleItem.objects.create(sale=sale_a, kind="cihaz", device=device,
                                item_name="x", unit_price=TL("1"))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SaleItem.objects.create(sale=sale_b, kind="cihaz", device=device,
                                        item_name="x", unit_price=TL("1"))

    def test_insufficient_accessory_stock_is_blocked_but_overridable(self):
        accessory = self.make_accessory(qty=1)
        line = {"lid": "a", "kind": "aksesuar", "id": accessory.pk,
                "name": accessory.name, "qty": 3, "unit": "150.90"}
        with self.assertRaises(services.InsufficientStock):
            services.create_sale_from_cart({"lines": [line]}, user=self.user)

        # Müşterinin elindeki ama sisteme girilmemiş ürün: satış reddedilemez
        line["allow_negative"] = True
        services.create_sale_from_cart({"lines": [line]}, user=self.user)
        accessory.refresh_from_db()
        self.assertEqual(accessory.stock_qty, -2)

    def test_price_drift_requires_confirmation(self):
        accessory = self.make_accessory(qty=5, price="150.90")
        cart = {"lines": [{"lid": "a", "kind": "aksesuar", "id": accessory.pk,
                           "name": accessory.name, "qty": 1, "unit": "150.90"}]}
        accessory.price = TL("199.00")
        accessory.save()

        with self.assertRaises(services.PriceChanged) as ctx:
            services.create_sale_from_cart(cart, user=self.user)
        self.assertEqual(ctx.exception.changes[0]["new"], TL("199.00"))

        sale = services.create_sale_from_cart(cart, user=self.user,
                                              confirm_prices=True)
        self.assertEqual(sale.grand_total, TL("150.90"))


class TradeInTests(StockTestCase):
    def test_trade_in_keeps_revenue_cash_and_inventory_consistent(self):
        """40.000 telefon + 15.000 takas + 25.000 nakit.

        Ciro 40.000 olmalıdır — takas bir indirim değil, ayni ödemeyle
        kapatılmış bir alımdır. Negatif satır kalemi kullanılsaydı ciro 25.000
        görünür ve marj yapay olarak şişerdi.
        """
        device = self.make_device(price="30000")
        cart = {
            "customer_id": self.customer.pk,
            "lines": [{"lid": "d", "kind": "cihaz", "id": device.pk,
                       "name": device.label, "qty": 1, "unit": "40000"}],
            "trade_ins": [{"device_model_id": self.model.pk, "amount": "15000",
                           "imei1": "351111111111111"}],
        }
        sale = services.create_sale_from_cart(
            cart, user=self.user,
            payments=[{"amount": TL("25000"), "method": "nakit"}],
        )

        self.assertEqual(sale.grand_total, TL("40000.00"))      # CİRO
        self.assertEqual(sale.trade_in_total, TL("15000.00"))
        self.assertEqual(sale.payable_total, TL("25000.00"))    # tahsil edilecek
        self.assertEqual(sale.paid_total, TL("25000.00"))
        self.assertEqual(sale.balance, TL("0.00"))

        incoming = Device.objects.get(acquisition=Device.Acquisition.TAKAS)
        self.assertEqual(incoming.status, Device.Status.STOKTA)
        self.assertEqual(incoming.purchase_price, TL("15000.00"))
        self.assertEqual(incoming.supplier, self.customer)

        # Ciro KPI'ı satır kalemlerinden gelir; takas onu bozmamalı
        revenue = SaleItem.objects.filter(
            sale__status=Sale.Status.TAMAMLANDI, returned_at__isnull=True
        ).aggregate(t=__import__("django.db.models", fromlist=["Sum"]).Sum("line_total"))["t"]
        self.assertEqual(Decimal(revenue).quantize(TL("0.01")), TL("40000.00"))


class CreditAndReturnTests(StockTestCase):
    def test_partial_payment_leaves_balance(self):
        accessory = self.make_accessory(qty=10, price="1000")
        cart = {"lines": [{"lid": "a", "kind": "aksesuar", "id": accessory.pk,
                           "name": accessory.name, "qty": 1, "unit": "1000"}]}
        sale = services.create_sale_from_cart(
            cart, user=self.user, payments=[{"amount": TL("400")}],
            due_date=timezone.localdate() + timedelta(days=30),
        )
        self.assertEqual(sale.balance, TL("600.00"))
        self.assertTrue(sale.is_credit)
        self.assertFalse(sale.is_overdue)

    def test_return_with_refund_zeroes_the_balance(self):
        """1.000 ₺ veresiye, 400 ₺ tahsilat, sonra iade + 400 ₺ geri ödeme."""
        accessory = self.make_accessory(qty=10, price="1000")
        cart = {"lines": [{"lid": "a", "kind": "aksesuar", "id": accessory.pk,
                           "name": accessory.name, "qty": 1, "unit": "1000"}]}
        sale = services.create_sale_from_cart(cart, user=self.user,
                                              payments=[{"amount": TL("400")}])
        accessory.refresh_from_db()
        self.assertEqual(accessory.stock_qty, 9)

        item = sale.items.get()
        services.return_sale_item(item, user=self.user, reason="Beğenmedi",
                                  refund=False)
        sale.refresh_from_db()
        # İade sonrası tahsil edilecek 0, ödenen 400 -> mağaza 400 borçlu
        self.assertEqual(sale.payable_total, TL("0.00"))
        self.assertEqual(sale.balance, TL("-400.00"))

        services.record_payment(sale, TL("400"), kind=Payment.Kind.IADE,
                                user=self.user)
        sale.refresh_from_db()
        self.assertEqual(sale.balance, TL("0.00"))

        accessory.refresh_from_db()
        self.assertEqual(accessory.stock_qty, 10)   # stok geri geldi

    def test_returned_device_becomes_sellable_again(self):
        device = self.make_device()
        cart = {"customer_id": self.customer.pk,
                "lines": [{"lid": "d", "kind": "cihaz", "id": device.pk,
                           "name": device.label, "qty": 1, "unit": "18500"}]}
        sale = services.create_sale_from_cart(cart, user=self.user)
        services.return_sale_item(sale.items.get(), user=self.user)

        device.refresh_from_db()
        self.assertEqual(device.status, Device.Status.STOKTA)
        self.assertIsNone(device.sold_at)
        self.assertIsNone(device.sold_price)
        # Kısmi tekil indeks iade edilen satırı saymaz -> yeniden satılabilir
        sale2 = services.create_sale_from_cart(cart, user=self.user)
        self.assertEqual(sale2.items.count(), 1)

    def test_void_sale_reverses_everything(self):
        device = self.make_device()
        accessory = self.make_accessory(qty=10)
        cart = {
            "customer_id": self.customer.pk,
            "lines": [
                {"lid": "d", "kind": "cihaz", "id": device.pk,
                 "name": device.label, "qty": 1, "unit": "18500"},
                {"lid": "a", "kind": "aksesuar", "id": accessory.pk,
                 "name": accessory.name, "qty": 2, "unit": "150.90"},
            ],
        }
        sale = services.create_sale_from_cart(
            cart, user=self.user, payments=[{"amount": TL("18801.80")}])
        services.void_sale(sale, user=self.user, reason="Yanlış giriş")

        sale.refresh_from_db()
        device.refresh_from_db()
        accessory.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.IPTAL)
        self.assertEqual(sale.balance, TL("0.00"))
        self.assertEqual(device.status, Device.Status.STOKTA)
        self.assertEqual(accessory.stock_qty, 10)


class LedgerTests(StockTestCase):
    def test_stock_qty_is_always_the_ledger_sum(self):
        accessory = self.make_accessory(qty=10)
        services.receive_accessory_stock(accessory, 5, user=self.user,
                                         unit_cost=TL("85"))
        services.write_off_accessory(accessory, 2, user=self.user, note="Kırıldı")
        accessory.refresh_from_db()
        self.assertEqual(accessory.stock_qty, 13)
        self.assertEqual(accessory.cost, TL("85.00"))   # yeni parti maliyeti

        ledger = accessory.movements.aggregate(
            t=__import__("django.db.models", fromlist=["Sum"]).Sum("quantity"))["t"]
        self.assertEqual(ledger, accessory.stock_qty)
        self.assertEqual(accessory.movements.order_by("-id").first().balance_after, 13)

    def test_stocktake_writes_a_difference_movement_not_a_direct_set(self):
        accessory = self.make_accessory(qty=10)
        movement = services.adjust_accessory_stock(accessory, 7, user=self.user)
        accessory.refresh_from_db()
        self.assertEqual(movement.quantity, -3)
        self.assertEqual(movement.reason, StockMovement.Reason.SAYIM)
        self.assertEqual(accessory.stock_qty, 7)
        self.assertIsNone(services.adjust_accessory_stock(accessory, 7, user=self.user))

    def test_recalculate_is_idempotent(self):
        device = self.make_device()
        cart = {"customer_id": self.customer.pk,
                "lines": [{"lid": "d", "kind": "cihaz", "id": device.pk,
                           "name": device.label, "qty": 1, "unit": "18500"}]}
        sale = services.create_sale_from_cart(cart, user=self.user,
                                              payments=[{"amount": TL("5000")}])
        before = (sale.grand_total, sale.payable_total, sale.paid_total)
        for _ in range(3):
            sale.recalculate()
        sale.refresh_from_db()
        self.assertEqual((sale.grand_total, sale.payable_total, sale.paid_total),
                         before)


class DeviceRuleTests(StockTestCase):
    def test_warranty_end_is_computed_and_clamped(self):
        device = self.make_device(warranty_months=1,
                                  warranty_start=date(2026, 1, 31))
        self.assertEqual(device.warranty_end, date(2026, 2, 28))

    def test_warranty_starts_at_sale_when_left_blank(self):
        device = self.make_device(warranty_months=12)
        self.assertIsNone(device.warranty_end)
        cart = {"customer_id": self.customer.pk,
                "lines": [{"lid": "d", "kind": "cihaz", "id": device.pk,
                           "name": device.label, "qty": 1, "unit": "18500"}]}
        services.create_sale_from_cart(cart, user=self.user)
        device.refresh_from_db()
        self.assertEqual(device.warranty_start, timezone.localdate())
        self.assertEqual(device.warranty_end,
                         add_months(timezone.localdate(), 12))

    def test_imei_cannot_be_reused_across_devices(self):
        self.make_device(imei1="351234567890123")
        with self.assertRaises(Exception):
            self.make_device(imei1="351234567890123")
        # imei2 de imei1 ile çakışamaz (çapraz sütun kontrolü)
        with self.assertRaises(Exception):
            self.make_device(imei2="351234567890123")

    def test_blank_imei_does_not_collide(self):
        self.make_device()
        self.make_device()
        self.assertEqual(Device.objects.count(), 2)

    def test_manual_sold_status_is_refused(self):
        device = self.make_device()
        with self.assertRaises(services.InvalidStatusTransition):
            services.set_device_status(device, Device.Status.SATILDI, user=self.user)

    def test_illegal_transition_is_refused(self):
        device = self.make_device()
        services.set_device_status(device, Device.Status.KAYIP, user=self.user)
        with self.assertRaises(services.InvalidStatusTransition):
            services.set_device_status(device, Device.Status.STOKTA, user=self.user)

    def test_net_profit_accounts_for_repairs(self):
        device = self.make_device(price="16000")
        services.add_device_expense(device, TL("1200"), kind=Expense.Kind.PARCA,
                                    title="Ekran değişimi", user=self.user)
        cart = {"customer_id": self.customer.pk,
                "lines": [{"lid": "d", "kind": "cihaz", "id": device.pk,
                           "name": device.label, "qty": 1, "unit": "20000"}]}
        services.create_sale_from_cart(cart, user=self.user)
        device.refresh_from_db()
        self.assertEqual(device.gross_profit, TL("4000.00"))
        self.assertEqual(device.net_profit, TL("2800.00"))   # tamir düşülmüş
        self.assertEqual(device.cost_basis, TL("17200.00"))

    def test_overhead_cannot_be_attached_to_a_device(self):
        device = self.make_device()
        with self.assertRaises(services.StockError):
            services.add_device_expense(device, TL("5000"), kind=Expense.Kind.KIRA,
                                        title="Dükkân kirası", user=self.user)


class ScanResolveTests(StockTestCase):
    def test_resolves_stock_code_imei_and_barcode(self):
        device = self.make_device(imei1="351234567890123")
        accessory = self.make_accessory(qty=1, barcode="8690000000017")

        self.assertEqual(services.resolve_scan(device.stock_code), device)
        self.assertEqual(services.resolve_scan(device.stock_code.lower()), device)
        self.assertEqual(services.resolve_scan("351234567890123"), device)
        self.assertEqual(services.resolve_scan("8690000000017"), accessory)
        self.assertEqual(services.resolve_scan(accessory.sku), accessory)
        self.assertIsNone(services.resolve_scan("YOKBOYLEBIRSEY"))
        self.assertIsNone(services.resolve_scan(""))


class PublishTests(StockTestCase):
    def test_publish_and_auto_unpublish_on_sale(self):
        device = self.make_device()
        device.list_price = TL("24999.90")
        device.storage = "256GB"
        device.save()

        product = services.publish_device_to_site(device, user=self.user)
        self.assertTrue(product.is_active)
        # catalog.Product decimal_places=0 -> yuvarlama sınırı
        self.assertEqual(product.price, TL("25000"))
        self.assertEqual(product.brand, self.brand)

        cart = {"customer_id": self.customer.pk,
                "lines": [{"lid": "d", "kind": "cihaz", "id": device.pk,
                           "name": device.label, "qty": 1, "unit": "24999.90"}]}
        services.create_sale_from_cart(cart, user=self.user, confirm_prices=True)
        product.refresh_from_db()
        self.assertFalse(product.is_active)   # satılan cihaz vitrinde kalmaz

    def test_only_in_stock_devices_can_be_published(self):
        device = self.make_device()
        services.set_device_status(device, Device.Status.SERVISTE, user=self.user)
        with self.assertRaises(services.StockError):
            services.publish_device_to_site(device, user=self.user)
