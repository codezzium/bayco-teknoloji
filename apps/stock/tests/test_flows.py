from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Brand, Product
from apps.stock import services
from apps.stock.models import (
    Accessory,
    AccessoryCategory,
    Contact,
    Device,
    DeviceModel,
    DeviceStatusLog,
    Payment,
    Sale,
    SaleItem,
    StockMovement,
)

TL = Decimal


class PanelFlowTestCase(TransactionTestCase):
    def setUp(self):
        self.patron = User.objects.create_user("patron", password="pw", is_staff=True,
                                               is_superuser=True)
        self.client.force_login(self.patron)
        self.brand = Brand.objects.create(name="Apple")
        self.model = DeviceModel.objects.create(brand=self.brand, name="iPhone 13")
        self.customer = Contact.objects.create(full_name="Ayşe Kaya",
                                               phone="0532 111 22 33")

    def device_payload(self, **overrides):
        data = {
            "device_model": self.model.pk, "condition": "ikinci_el",
            "imei1": "351234567890123", "imei2": "", "serial_no": "",
            "storage": "256GB", "color": "Grafit", "battery_health": "91",
            "shelf": "A1", "defect_note": "", "supplier": "",
            "purchase_date": timezone.localdate().isoformat(),
            "purchase_price": "16000", "list_price": "18500",
            "warranty_months": "12", "warranty_start": "",
        }
        data.update(overrides)
        return data

    def accessory_payload(self, **overrides):
        data = {
            "name": "Şarj Kablosu", "variant": "USB-C 1m", "brand": self.brand.pk,
            "category": "", "barcode": "8816581028935", "cost": "80",
            "price": "150", "min_stock_level": "2", "note": "", "is_active": "on",
            "opening_qty": "5",
        }
        data.update(overrides)
        return data

    def make_accessory(self, qty=10, **kw):
        kw.setdefault("name", "Kılıf")
        accessory = Accessory.objects.create(cost=TL("50"), price=TL("120"), **kw)
        if qty:
            services.receive_accessory_stock(accessory, qty, user=self.patron,
                                             opening=True)
        accessory.refresh_from_db()
        return accessory

    def make_device(self, **kw):
        kw.setdefault("device_model", self.model)
        kw.setdefault("purchase_price", TL("16000"))
        kw.setdefault("list_price", TL("18500"))
        return services.create_device(user=self.patron, **kw)


class CatalogFlowTests(PanelFlowTestCase):
    def test_accessory_created_from_panel_with_opening_stock(self):
        response = self.client.post(reverse("stock:accessory_create"),
                                    self.accessory_payload())
        accessory = Accessory.objects.get()
        self.assertRedirects(response, reverse("stock:accessory_detail",
                                               kwargs={"pk": accessory.pk}))
        self.assertEqual(accessory.sku, "BYC-A-000001")
        self.assertEqual(accessory.stock_qty, 5)
        self.assertEqual(accessory.movements.get().reason, StockMovement.Reason.ACILIS)

    def test_second_accessory_gets_the_next_code(self):
        self.client.post(reverse("stock:accessory_create"), self.accessory_payload())
        self.client.post(reverse("stock:accessory_create"),
                         self.accessory_payload(barcode="", opening_qty="0"))
        self.assertEqual(
            list(Accessory.objects.order_by("sku").values_list("sku", flat=True)),
            ["BYC-A-000001", "BYC-A-000002"])

    def test_accessory_edit_from_panel(self):
        accessory = self.make_accessory()
        response = self.client.post(
            reverse("stock:accessory_edit", kwargs={"pk": accessory.pk}),
            self.accessory_payload(name="Kılıf Pro", barcode=""))
        self.assertEqual(response.status_code, 302)
        accessory.refresh_from_db()
        self.assertEqual(accessory.name, "Kılıf Pro")
        self.assertEqual(accessory.stock_qty, 10)

    def test_device_created_from_panel(self):
        response = self.client.post(reverse("stock:device_create"),
                                    self.device_payload())
        device = Device.objects.get()
        self.assertRedirects(response, reverse("stock:device_detail",
                                               kwargs={"pk": device.pk}))
        self.assertEqual(device.stock_code, "BYC-000001")
        self.assertEqual(device.created_by, self.patron)

    def test_device_edit_keeps_the_stock_code(self):
        device = self.make_device()
        response = self.client.post(
            reverse("stock:device_edit", kwargs={"pk": device.pk}),
            self.device_payload(imei1=device.imei1, shelf="B2"))
        self.assertEqual(response.status_code, 302)
        device.refresh_from_db()
        self.assertEqual(device.shelf, "B2")
        self.assertEqual(device.stock_code, "BYC-000001")

    def test_duplicate_imei_is_a_form_error(self):
        self.make_device(imei1="351234567890123")
        response = self.client.post(reverse("stock:device_create"),
                                    self.device_payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Device.objects.count(), 1)

    def test_device_model_and_category_created_from_panel(self):
        response = self.client.post(
            reverse("stock:simple_create", kwargs={"key": "modeller"}),
            {"brand": self.brand.pk, "name": "iPhone 15", "kind": "telefon",
             "is_active": "on"})
        self.assertEqual(response.status_code, 302)
        response = self.client.post(
            reverse("stock:simple_create", kwargs={"key": "kategoriler"}),
            {"name": "Kılıf", "order": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(DeviceModel.objects.filter(name="iPhone 15").exists())
        self.assertTrue(AccessoryCategory.objects.filter(name="Kılıf").exists())

    def test_used_device_model_cannot_be_deleted(self):
        self.make_device()
        response = self.client.post(
            reverse("stock:simple_delete", kwargs={"key": "modeller", "pk": self.model.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(DeviceModel.objects.filter(pk=self.model.pk).exists())

    def test_device_status_change_publish_and_delete(self):
        device = self.make_device()
        response = self.client.post(
            reverse("stock:device_publish", kwargs={"pk": device.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Product.objects.get().is_active)
        self.client.post(reverse("stock:device_status", kwargs={"pk": device.pk}),
                         {"status": "serviste", "note": "Ekran değişimi"})
        device.refresh_from_db()
        self.assertEqual(device.status, Device.Status.SERVISTE)
        response = self.client.post(reverse("stock:device_delete",
                                            kwargs={"pk": device.pk}))
        self.assertRedirects(response, reverse("stock:device_list"))
        self.assertFalse(Device.objects.filter(pk=device.pk).exists())

    def test_contact_and_expense_created_from_panel(self):
        response = self.client.post(reverse("stock:contact_create"), {
            "full_name": "Mehmet Demir", "phone": "0533 222 33 44", "company": "",
            "email": "", "tax_no": "", "address": "", "is_customer": "on",
            "note": "",
        })
        self.assertEqual(response.status_code, 302)
        contact = Contact.objects.get(full_name="Mehmet Demir")
        self.assertEqual(contact.phone_norm, "905332223344")

        device = self.make_device()
        response = self.client.post(reverse("stock:expense_create"), {
            "kind": "parca", "title": "Ekran", "amount": "1500",
            "spent_on": timezone.localdate().isoformat(), "device": device.pk,
            "supplier": "", "note": "",
        })
        self.assertRedirects(response, reverse("stock:device_detail",
                                               kwargs={"pk": device.pk}))
        self.assertEqual(device.cost_basis, TL("17500.00"))

    def test_label_page_renders_for_new_records(self):
        device = self.make_device()
        accessory = self.make_accessory(barcode="8690000000017")
        response = self.client.get(reverse("stock:label_print"),
                                   {"ids": device.pk, "acc": accessory.pk})
        self.assertContains(response, device.stock_code)
        self.assertContains(response, accessory.barcode)


class StockMovementFlowTests(PanelFlowTestCase):
    def setUp(self):
        super().setUp()
        self.accessory = self.make_accessory(barcode="8690000000017")

    def adjust(self, **data):
        return self.client.post(
            reverse("stock:accessory_adjust", kwargs={"pk": self.accessory.pk}), data)

    def test_intake_stocktake_and_write_off_from_panel(self):
        self.adjust(mode="giris", quantity="4", unit_cost="55", note="Tedarikçi A")
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, 14)
        self.assertEqual(self.accessory.cost, TL("55.00"))

        self.adjust(mode="sayim", counted_qty="12", note="")
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, 12)

        self.adjust(mode="fire", quantity="2", note="Kırık")
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, 10)
        self.assertEqual(
            list(self.accessory.movements.order_by("id")
                 .values_list("reason", "quantity", "balance_after")),
            [("acilis", 10, 10), ("giris", 4, 14), ("sayim", -2, 12), ("fire", -2, 10)])

    def test_scan_intake_and_counting_session(self):
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "intake", "code": self.accessory.barcode})
        self.client.post(reverse("stock:intake_add"),
                         {"accessory": self.accessory.pk, "delta": "3"})
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, 14)

        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "count", "code": self.accessory.barcode})
        self.client.post(reverse("stock:stocktake_mark"),
                         {"accessory": self.accessory.pk, "counted": "9"})
        response = self.client.post(reverse("stock:stocktake_finish"))
        self.assertRedirects(response, reverse("stock:stocktake"))
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, 9)

    def test_scan_lookup_finds_new_records(self):
        device = self.make_device(imei1="351234567890123")
        for code, url in ((device.stock_code, "stock:device_detail"),
                          (device.imei1, "stock:device_detail"),
                          (self.accessory.barcode, "stock:accessory_detail"),
                          (self.accessory.sku, "stock:accessory_detail")):
            with self.subTest(code=code):
                pk = device.pk if url == "stock:device_detail" else self.accessory.pk
                response = self.client.post(reverse("stock:scan_resolve"),
                                            {"mode": "lookup", "code": code})
                self.assertEqual(response["HX-Redirect"], reverse(url, kwargs={"pk": pk}))

    @skipUnlessDBFeature("has_select_for_update")
    def test_movements_lock_the_accessory_row(self):
        with CaptureQueriesContext(connection) as queries:
            services.receive_accessory_stock(self.accessory, 1, user=self.patron)
        locked = [q["sql"] for q in queries.captured_queries
                  if "FOR UPDATE" in q["sql"] and "stock_accessory" in q["sql"]]
        self.assertTrue(locked)


class SaleFlowTests(PanelFlowTestCase):
    def setUp(self):
        super().setUp()
        self.device = self.make_device(imei1="351234567890123")
        self.accessory = self.make_accessory(barcode="8690000000017")

    def fill_cart(self):
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "sale", "code": self.device.stock_code})
        self.client.post(reverse("stock:cart_add"),
                         {"kind": "aksesuar", "id": self.accessory.pk, "qty": "2"})
        self.client.post(reverse("stock:cart_customer"),
                         {"customer": self.customer.pk, "note": "Kasa notu"})

    def test_checkout_with_device_accessory_and_trade_in(self):
        self.fill_cart()
        self.client.post(reverse("stock:cart_trade_in"), {
            "device_model": self.model.pk, "amount": "3000",
            "imei1": "359876543210987", "color": "Mavi", "storage": "128GB",
            "note": "Kasa çizik",
        })
        self.client.post(
            reverse("stock:cart_price", kwargs={"lid": f"d-{self.device.pk}"}),
            {"price": "18000", "discount": "500"})
        response = self.client.post(reverse("stock:checkout"), {
            "paid_amount": "", "payment_method": "kart", "due_date": "",
            "confirm_prices": "1",
        })
        self.assertEqual(response.status_code, 200)

        sale = Sale.objects.get()
        self.assertContains(response, sale.receipt_no)
        self.assertEqual(sale.receipt_no, "BYC-S-000001")
        self.assertEqual(sale.grand_total, TL("17740.00"))
        self.assertEqual(sale.trade_in_total, TL("3000.00"))
        self.assertEqual(sale.payable_total, TL("14740.00"))
        self.assertEqual(sale.balance, TL("0.00"))
        self.assertEqual(sale.payments.get().method, Payment.Method.KART)

        self.device.refresh_from_db()
        self.assertEqual(self.device.status, Device.Status.SATILDI)
        self.assertEqual(self.device.sold_to, self.customer)
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, 8)

        trade_in = Device.objects.get(acquisition=Device.Acquisition.TAKAS)
        self.assertEqual(trade_in.stock_code, "BYC-000002")
        self.assertEqual(trade_in.purchase_price, TL("3000.00"))

    def test_credit_sale_then_payment_return_and_void(self):
        self.fill_cart()
        self.client.post(reverse("stock:checkout"),
                         {"paid_amount": "0", "payment_method": "nakit",
                          "due_date": (timezone.localdate() + timedelta(days=30)).isoformat()})
        sale = Sale.objects.get()
        self.assertEqual(sale.paid_total, TL("0.00"))
        self.assertEqual(sale.balance, TL("18740.00"))

        response = self.client.post(
            reverse("stock:sale_payment", kwargs={"pk": sale.pk}),
            {"amount": "740", "method": "nakit", "kind": "tahsilat",
             "paid_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "note": ""})
        self.assertRedirects(response, reverse("stock:sale_detail", kwargs={"pk": sale.pk}))
        sale.refresh_from_db()
        self.assertEqual(sale.balance, TL("18000.00"))

        item = sale.items.get(kind=SaleItem.Kind.AKSESUAR)
        self.client.post(reverse("stock:sale_item_return",
                                 kwargs={"pk": sale.pk, "item_id": item.pk}),
                         {"reason": "Beğenmedi", "refund": ""})
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, 10)

        self.client.post(reverse("stock:sale_void", kwargs={"pk": sale.pk}),
                         {"reason": "Müşteri vazgeçti"})
        sale.refresh_from_db()
        self.device.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.IPTAL)
        self.assertEqual(sale.paid_total, TL("0.00"))
        self.assertEqual(self.device.status, Device.Status.STOKTA)

    def test_sold_device_keeps_history(self):
        self.fill_cart()
        self.client.post(reverse("stock:checkout"),
                         {"paid_amount": "", "payment_method": "nakit"})
        self.assertEqual(
            list(DeviceStatusLog.objects.filter(device=self.device)
                 .order_by("id").values_list("to_status", flat=True)),
            ["stokta", "satildi"])
