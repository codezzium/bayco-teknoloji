import re
from datetime import date, timedelta
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
    Expense,
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

    def test_warranty_start_without_months_means_manufacturer_warranty(self):
        self.client.post(reverse("stock:device_create"),
                         self.device_payload(warranty_months="0",
                                             warranty_start="2025-06-15"))
        device = Device.objects.get()
        self.assertEqual(device.warranty_months, 24)
        self.assertEqual(device.warranty_end, date(2027, 6, 15))

    def test_warranty_months_typed_with_start_is_kept(self):
        self.client.post(reverse("stock:device_create"),
                         self.device_payload(warranty_months="12",
                                             warranty_start="2026-09-01"))
        self.assertEqual(Device.objects.get().warranty_months, 12)

    def test_editing_old_device_leaves_its_warranty_alone(self):
        device = self.make_device(warranty_months=0, warranty_start=date(2025, 6, 15))
        self.client.post(
            reverse("stock:device_edit", kwargs={"pk": device.pk}),
            self.device_payload(imei1=device.imei1, shelf="B2",
                                warranty_months="0", warranty_start="2025-06-15"))
        device.refresh_from_db()
        self.assertEqual(device.shelf, "B2")
        self.assertEqual(device.warranty_months, 0)

    def test_device_form_fills_24_months_when_start_is_picked(self):
        response = self.client.get(reverse("stock:device_create"))
        self.assertContains(response, 'data-warranty-months="24"')

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
        # Aksesuar etiketi Niimbot görselidir; kod görselin içinde ve alt metninde.
        self.assertContains(response, reverse(
            "stock:niimbot_png", kwargs={"kind": "aksesuar", "pk": accessory.pk}))
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
        self.device = self.make_device(imei1="351234567890123", storage="128GB",
                                       color="Mavi")
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

    def sell_first(self):
        self.fill_cart()
        self.client.post(reverse("stock:checkout"),
                         {"paid_amount": "", "payment_method": "nakit"})
        return Sale.objects.get()

    def trade_back(self, imei, amount="9000"):
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "sale", "code": self.accessory.barcode})
        self.client.post(reverse("stock:cart_customer"), {"customer": self.customer.pk})
        self.client.post(reverse("stock:cart_trade_in"), {
            "device_model": self.model.pk, "amount": amount, "imei1": imei,
            "color": "", "storage": "", "note": "",
        })
        return self.client.post(reverse("stock:checkout"),
                                {"paid_amount": "", "payment_method": "nakit"})

    def sell_to(self, customer, price):
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "sale", "code": self.device.stock_code})
        self.client.post(reverse("stock:cart_customer"), {"customer": customer.pk})
        self.client.post(
            reverse("stock:cart_price", kwargs={"lid": f"d-{self.device.pk}"}),
            {"price": price, "discount": "0"})
        self.client.post(reverse("stock:checkout"), {
            "paid_amount": "", "payment_method": "nakit", "confirm_prices": "1",
        })
        self.device.refresh_from_db()
        return Sale.objects.latest("id")

    def reenter(self, price, supplier, **overrides):
        response = self.client.post(reverse("stock:device_create"), self.device_payload(
            purchase_price=price, supplier=supplier.pk, list_price="", **overrides))
        self.assertRedirects(response, reverse("stock:device_detail",
                                               kwargs={"pk": self.device.pk}))
        self.device.refresh_from_db()

    def test_sold_device_comes_back_on_the_same_record(self):
        first_sale = self.sell_first()
        response = self.trade_back(self.device.imei1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Sale.objects.count(), 2)
        self.assertEqual(Device.objects.count(), 1)

        self.device.refresh_from_db()
        self.assertEqual((self.device.status, self.device.cycle_no,
                          self.device.acquisition, self.device.stock_code),
                         (Device.Status.STOKTA, 2, Device.Acquisition.TAKAS,
                          "BYC-000001"))
        self.assertEqual((self.device.purchase_price, self.device.supplier,
                          self.device.sold_to, self.device.sold_price),
                         (TL("9000.00"), self.customer, None, None))
        self.assertEqual((self.device.storage, self.device.color), ("128GB", "Mavi"))

        cycle = self.device.cycles.get()
        first_item = first_sale.items.get(kind=SaleItem.Kind.CIHAZ)
        self.assertEqual((cycle.cycle_no, cycle.purchase_price, cycle.sold_to,
                          cycle.sold_price, cycle.sale_item),
                         (1, TL("16000.00"), self.customer, TL("18500.00"), first_item))
        self.assertEqual(first_item.line_cost, TL("16000.00"))

        sale = self.sell_to(self.customer, "12000")
        item = sale.items.get()
        self.assertEqual((self.device.status, item.cycle_no, item.line_cost),
                         (Device.Status.SATILDI, 2, TL("9000.00")))

    def test_device_sold_three_times_keeps_every_cycle(self):
        from apps.stock import reports

        second = Contact.objects.create(full_name="Mehmet Demir", phone="0533 222 33 44")
        third = Contact.objects.create(full_name="Zeynep Ak", phone="0534 333 44 55")
        Expense.objects.create(device=self.device, kind="parca", title="Ekran",
                               amount=TL("500"))
        sale_a = self.sell_to(self.customer, "18500")
        self.reenter("9000", self.customer)
        self.assertEqual((self.device.supplier, self.device.acquisition),
                         (self.customer, Device.Acquisition.ALIM))
        Expense.objects.create(device=self.device, kind="iscilik", title="Pil",
                               amount=TL("300"))
        sale_b = self.sell_to(second, "12000")
        self.reenter("7000", second)
        self.assertEqual(self.device.supplier, second)
        self.assertEqual(self.device.total_expense, TL("0.00"))
        capital = reports.stock_capital()
        self.assertEqual((capital["devices"], capital["device_expenses"]),
                         (TL("7000.00"), TL("0.00")))
        sale_c = self.sell_to(third, "10000")

        self.assertEqual(Device.objects.count(), 1)
        self.assertEqual((self.device.stock_code, self.device.imei1, self.device.cycle_no),
                         ("BYC-000001", "351234567890123", 3))
        self.assertEqual(self.device.sold_to, third)
        self.assertEqual(
            list(self.device.cycles.order_by("cycle_no").values_list(
                "cycle_no", "purchase_price", "sold_to", "sold_price")),
            [(1, TL("16000.00"), self.customer.pk, TL("18500.00")),
             (2, TL("9000.00"), second.pk, TL("12000.00"))])
        self.assertEqual(
            [sale.items.get().line_cost for sale in (sale_a, sale_b, sale_c)],
            [TL("16000.00"), TL("9000.00"), TL("7000.00")])
        self.assertEqual(
            sorted(self.device.expenses.values_list("cycle_no", "amount")),
            [(1, TL("500.00")), (2, TL("300.00"))])
        today = timezone.localdate()
        self.assertEqual(reports.revenue_and_profit(today, today)["revenue"],
                         TL("40500.00"))
        self.assertEqual(reports.expenses_for_period(today, today)["device"],
                         TL("800.00"))

        old_item = sale_a.items.get()
        self.client.post(reverse("stock:sale_item_return",
                                 kwargs={"pk": sale_a.pk, "item_id": old_item.pk}),
                         {"reason": "x", "refund": "1"})
        old_item.refresh_from_db()
        self.assertIsNone(old_item.returned_at)
        self.client.post(reverse("stock:sale_void", kwargs={"pk": sale_b.pk}),
                         {"reason": "x"})
        sale_b.refresh_from_db()
        self.assertEqual(sale_b.status, Sale.Status.TAMAMLANDI)
        self.device.refresh_from_db()
        self.assertEqual((self.device.status, self.device.cycle_no),
                         (Device.Status.SATILDI, 3))

        response = self.client.get(reverse("stock:device_detail",
                                           kwargs={"pk": self.device.pk}))
        for text in ("Alış / Satış Dönemleri", "1. dönem", "2. dönem",
                     "3. dönem", "Mehmet Demir", sale_a.receipt_no):
            self.assertContains(response, text)
        response = self.client.get(reverse("stock:contact_detail",
                                           kwargs={"pk": self.customer.pk}))
        self.assertContains(response, "2. dönem")

    def test_voiding_the_buy_back_restores_the_previous_cycle(self):
        first_sale = self.sell_first()
        self.trade_back(self.device.imei1)
        second = Sale.objects.latest("id")
        response = self.client.post(reverse("stock:sale_void", kwargs={"pk": second.pk}),
                                    {"reason": "Yanlış işlem"})
        self.assertEqual(response.status_code, 302)
        second.refresh_from_db()
        self.assertEqual((second.status, second.balance), (Sale.Status.IPTAL, TL("0.00")))
        self.device.refresh_from_db()
        self.assertEqual((self.device.status, self.device.cycle_no, self.device.sold_to,
                          self.device.purchase_price),
                         (Device.Status.SATILDI, 1, self.customer, TL("16000.00")))
        self.assertFalse(self.device.cycles.exists())
        self.assertIsNone(first_sale.items.get(kind=SaleItem.Kind.CIHAZ).returned_at)
        self.assertEqual(Device.objects.count(), 1)

    def test_device_form_offers_the_sold_record(self):
        self.sell_first()
        response = self.client.get(reverse("stock:device_create"),
                                   {"imei": self.device.imei1})
        self.assertContains(response, "daha önce BYC-000001 olarak satıldı")
        self.assertEqual(response.context["form"].initial["supplier"], self.customer.pk)
        self.assertEqual(response.context["form"].initial["storage"], "128GB")

        response = self.client.post(reverse("stock:device_reentry_lookup"),
                                    {"imei1": self.device.imei1})
        data = response.json()
        self.assertTrue(data["found"])
        self.assertEqual(data["values"]["color"], "Mavi")
        self.assertEqual(data["selects"]["device_model"]["value"], self.model.pk)
        self.assertEqual(data["selects"]["supplier"]["value"], self.customer.pk)
        response = self.client.post(reverse("stock:device_reentry_lookup"),
                                    {"imei1": "359999999999999"})
        self.assertFalse(response.json()["found"])

    def test_device_form_puts_the_sold_device_back_in_stock(self):
        first_sale = self.sell_first()
        self.reenter("9000", self.customer, battery_health="85", shelf="B3")
        self.assertEqual(Device.objects.count(), 1)
        self.assertEqual((self.device.status, self.device.cycle_no,
                          self.device.purchase_price, self.device.battery_health,
                          self.device.shelf, self.device.list_price),
                         (Device.Status.STOKTA, 2, TL("9000.00"), 85, "B3", None))
        self.assertEqual(self.device.cycles.get().sale_item,
                         first_sale.items.get(kind=SaleItem.Kind.CIHAZ))
        self.assertFalse(Payment.objects.filter(kind=Payment.Kind.IADE).exists())

        response = self.client.post(reverse("stock:device_create"),
                                    self.device_payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Device.objects.count(), 1)

    def test_customer_return_stays_on_the_same_cycle(self):
        sale = self.sell_first()
        item = sale.items.get(kind=SaleItem.Kind.CIHAZ)
        self.client.post(reverse("stock:sale_item_return",
                                 kwargs={"pk": sale.pk, "item_id": item.pk}),
                         {"reason": "Beğenmedi", "refund": "1"})
        self.device.refresh_from_db()
        self.assertEqual((self.device.status, self.device.cycle_no),
                         (Device.Status.STOKTA, 1))
        self.assertFalse(self.device.cycles.exists())

    def test_stale_checkout_form_is_refused(self):
        self.fill_cart()
        self.client.post(reverse("stock:cart_trade_in"), {
            "device_model": self.model.pk, "amount": "20000", "imei1": "",
            "color": "", "storage": "", "note": "",
        })
        response = self.client.post(reverse("stock:checkout"), {
            "paid_amount": "18.740", "payment_method": "nakit", "payable": "18740.00",
        })
        self.assertContains(response, "Sepet değişti")
        self.assertFalse(Sale.objects.exists())

    def test_sold_device_keeps_history(self):
        self.fill_cart()
        self.client.post(reverse("stock:checkout"),
                         {"paid_amount": "", "payment_method": "nakit"})
        self.assertEqual(
            list(DeviceStatusLog.objects.filter(device=self.device)
                 .order_by("id").values_list("to_status", flat=True)),
            ["stokta", "satildi"])
