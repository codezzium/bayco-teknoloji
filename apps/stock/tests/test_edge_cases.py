import html
import re
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Brand
from apps.stock import cart as cart_utils
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
    TradeIn,
)
from apps.stock.permissions import GROUP_PERSONEL

TL = Decimal
SCANNED = "8816581028935"
LONG = "Ç" * 500
PAYLOAD = "'+alert(1)+'"


class EdgeCaseTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patron = User.objects.create_user("patron", password="pw", is_staff=True,
                                              is_superuser=True)
        cls.brand = Brand.objects.create(name="Apple")
        cls.model = DeviceModel.objects.create(brand=cls.brand, name="iPhone 13")
        cls.customer = Contact.objects.create(full_name="Ayşe Kaya",
                                              phone="0532 111 22 33")
        cls.accessory = Accessory.objects.create(name="Kılıf", barcode="8690000000017",
                                                 cost=TL("50"), price=TL("120"))
        services.receive_accessory_stock(cls.accessory, 10, user=cls.patron,
                                         opening=True)
        cls.device = services.create_device(
            user=cls.patron, device_model=cls.model, imei1="351234567890123",
            purchase_price=TL("16000"), list_price=TL("18500"))

    def setUp(self):
        self.client.force_login(self.patron)
        self.accessory.refresh_from_db()

    def sell_accessory(self, qty=1, paid=True):
        cart = {"lines": [{"lid": "a", "kind": "aksesuar", "id": self.accessory.pk,
                           "name": "Kılıf", "qty": qty, "unit": "120"}]}
        payments = [{"amount": TL("120") * qty}] if paid else []
        return services.create_sale_from_cart(cart, user=self.patron, payments=payments)


class QuantityLimitTests(EdgeCaseTestCase):
    def adjust(self, **data):
        return self.client.post(
            reverse("stock:accessory_adjust", kwargs={"pk": self.accessory.pk}), data)

    def assert_stock_unchanged(self):
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, 10)
        self.assertEqual(self.accessory.movements.count(), 1)

    def test_scanned_barcode_in_opening_stock_is_a_form_error(self):
        response = self.client.post(reverse("stock:accessory_create"), {
            "name": "Ekran Koruyucu", "variant": "", "brand": "", "category": "",
            "barcode": "", "cost": "10", "price": "50", "min_stock_level": "2",
            "note": "", "is_active": "on", "opening_qty": SCANNED,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Accessory.objects.filter(name="Ekran Koruyucu").exists())

    def test_scanned_barcode_in_intake_quantity_is_refused(self):
        response = self.adjust(mode="giris", quantity=SCANNED, unit_cost="", note="")
        self.assertEqual(response.status_code, 302)
        self.assert_stock_unchanged()

    def test_scanned_barcode_in_stocktake_is_refused(self):
        self.adjust(mode="sayim", counted_qty=SCANNED, note="")
        self.assert_stock_unchanged()

    def test_scanned_barcode_in_write_off_is_refused(self):
        self.adjust(mode="fire", quantity=SCANNED, note="")
        self.assert_stock_unchanged()

    def test_scanned_barcode_in_intake_list_is_refused(self):
        self.client.post(reverse("stock:intake_add"),
                         {"accessory": self.accessory.pk, "delta": SCANNED})
        self.assert_stock_unchanged()

    def test_scanned_barcode_in_counting_session_is_ignored(self):
        url = reverse("stock:stocktake_mark")
        self.client.post(url, {"accessory": self.accessory.pk, "counted": "7"})
        self.client.post(url, {"accessory": self.accessory.pk, "counted": SCANNED})
        self.client.post(reverse("stock:stocktake_finish"))
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, 7)

    def test_counting_session_survives_a_missing_accessory(self):
        self.client.post(reverse("stock:stocktake_mark"), {"counted": "3"})
        self.assertEqual(self.client.get(reverse("stock:stocktake")).status_code, 200)

    def test_service_caps_the_quantity_of_a_movement(self):
        with self.assertRaises(services.StockError):
            services.receive_accessory_stock(self.accessory, int(SCANNED),
                                             user=self.patron)
        self.assert_stock_unchanged()

    def test_negative_intake_cost_is_refused(self):
        self.adjust(mode="giris", quantity="1", unit_cost="-5", note="")
        self.assert_stock_unchanged()
        self.assertEqual(self.accessory.cost, TL("50.00"))


class TextLimitTests(EdgeCaseTestCase):
    def test_long_write_off_note_is_trimmed(self):
        self.client.post(
            reverse("stock:accessory_adjust", kwargs={"pk": self.accessory.pk}),
            {"mode": "fire", "quantity": "1", "note": LONG})
        movement = self.accessory.movements.latest("id")
        self.assertEqual(movement.quantity, -1)
        self.assertLessEqual(len(movement.note), 200)

    def test_long_status_note_is_trimmed(self):
        self.client.post(reverse("stock:device_status", kwargs={"pk": self.device.pk}),
                         {"status": "serviste", "note": LONG})
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, Device.Status.SERVISTE)
        self.assertLessEqual(len(self.device.status_logs.latest("id").note), 200)

    def test_long_return_reason_is_trimmed(self):
        sale = self.sell_accessory()
        item = sale.items.get()
        self.client.post(reverse("stock:sale_item_return",
                                 kwargs={"pk": sale.pk, "item_id": item.pk}),
                         {"reason": LONG, "refund": "1"})
        item.refresh_from_db()
        self.assertIsNotNone(item.returned_at)
        self.assertLessEqual(len(item.return_reason), 200)

    def test_long_void_reason_is_trimmed(self):
        sale = self.sell_accessory()
        self.client.post(reverse("stock:sale_void", kwargs={"pk": sale.pk}),
                         {"reason": LONG})
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.IPTAL)
        self.assertLessEqual(len(sale.items.get().return_reason), 200)

    def test_contact_with_two_phone_numbers_is_saved(self):
        response = self.client.post(reverse("stock:contact_create"), {
            "full_name": "Ali Veli", "phone": "0532 123 45 67 / 0212 555 44 33",
            "company": "", "email": "", "tax_no": "", "address": "",
            "is_customer": "on", "note": "",
        })
        self.assertEqual(response.status_code, 302)
        contact = Contact.objects.get(full_name="Ali Veli")
        self.assertTrue(contact.phone_norm.startswith("90532123456"))
        self.assertLessEqual(len(contact.phone_norm), 20)

    def test_long_accessory_name_can_be_sold(self):
        accessory = Accessory.objects.create(name="K" * 160, variant="V" * 120,
                                             cost=TL("1"), price=TL("2"))
        services.receive_accessory_stock(accessory, 1, user=self.patron, opening=True)
        cart = {"lines": [{"lid": "a", "kind": "aksesuar", "id": accessory.pk,
                           "name": "x", "qty": 1, "unit": "2"}]}
        sale = services.create_sale_from_cart(cart, user=self.patron)
        self.assertLessEqual(len(sale.items.get().item_name), 200)


class PosInputTests(EdgeCaseTestCase):
    def setUp(self):
        super().setUp()
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "sale", "code": self.accessory.barcode})
        self.lid = f"a-{self.accessory.pk}"

    def cart(self):
        return cart_utils.get_cart(self.client)

    def add_trade_in(self, **overrides):
        data = {"device_model": self.model.pk, "amount": "3000", "imei1": "",
                "color": "", "storage": "", "note": ""}
        data.update(overrides)
        return self.client.post(reverse("stock:cart_trade_in"), data)

    def checkout(self, **overrides):
        data = {"paid_amount": "", "payment_method": "nakit", "due_date": ""}
        data.update(overrides)
        return self.client.post(reverse("stock:checkout"), data)

    def test_absurd_prices_are_refused(self):
        url = reverse("stock:cart_price", kwargs={"lid": self.lid})
        for raw in (SCANNED, "NaN", "sNaN", "Infinity", "-Infinity", "1e999", "abc"):
            with self.subTest(price=raw):
                response = self.client.post(url, {"price": raw})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.cart()["lines"][0]["unit"], "120.00")

    def test_absurd_discounts_are_ignored(self):
        url = reverse("stock:cart_price", kwargs={"lid": self.lid})
        for raw in (SCANNED, "NaN", "Infinity"):
            with self.subTest(discount=raw):
                self.client.post(url, {"price": "120", "discount": raw})
                self.assertEqual(self.cart()["lines"][0]["discount"], "0.00")

    def test_absurd_paid_amounts_are_refused(self):
        for raw in (SCANNED, "NaN", "Infinity", "1e999"):
            with self.subTest(paid=raw):
                response = self.checkout(paid_amount=raw)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(Sale.objects.exists())

    def test_absurd_trade_in_amounts_are_refused(self):
        for raw in (SCANNED, "NaN", "Infinity"):
            with self.subTest(amount=raw):
                response = self.add_trade_in(amount=raw)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.cart()["trade_ins"], [])

    def test_trade_in_with_a_known_imei_is_explained(self):
        self.client.post(reverse("stock:cart_customer"), {"customer": self.customer.pk})
        self.add_trade_in(imei1=self.device.imei1)
        response = self.checkout()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.device.stock_code)
        self.assertFalse(Sale.objects.exists())
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, 10)

    def test_trade_in_with_invalid_fields_is_explained(self):
        self.client.post(reverse("stock:cart_customer"), {"customer": self.customer.pk})
        self.add_trade_in(imei1="1" * 25, color="M" * 100)
        response = self.checkout()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Sale.objects.exists())
        self.assertEqual(Device.objects.count(), 1)

    def test_trade_in_matching_the_second_imei_moves_both(self):
        device = services.create_device(
            user=self.patron, device_model=self.model, imei1="351111111111111",
            imei2="352222222222222", purchase_price=TL("1000"), list_price=TL("1500"))
        services.create_sale_from_cart(
            {"customer_id": self.customer.pk,
             "lines": [{"lid": "d", "kind": "cihaz", "id": device.pk, "name": "x",
                        "qty": 1, "unit": "1500"}]},
            user=self.patron)
        services.create_sale_from_cart(
            {"customer_id": self.customer.pk, "lines": [],
             "trade_ins": [{"device_model_id": self.model.pk, "amount": "800",
                            "imei1": "352222222222222"}]},
            user=self.patron)
        returned = Device.objects.get(acquisition=Device.Acquisition.TAKAS)
        self.assertEqual((returned.imei1, returned.imei2),
                         ("351111111111111", "352222222222222"))
        device.refresh_from_db()
        self.assertEqual((device.imei1, device.imei2), ("", ""))

    def test_trade_in_long_note_is_trimmed(self):
        self.client.post(reverse("stock:cart_customer"), {"customer": self.customer.pk})
        self.add_trade_in(color="Mavi", storage="128GB", note=LONG)
        self.checkout()
        trade_in = TradeIn.objects.get()
        self.assertLessEqual(len(trade_in.note), 200)
        self.assertEqual(trade_in.device.defect_note, LONG)

    def test_invalid_due_date_is_refused(self):
        response = self.checkout(paid_amount="0", due_date="31.12.2026")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Sale.objects.exists())

    def test_unknown_payment_method_falls_back_to_cash(self):
        self.checkout(payment_method="x" * 50)
        self.assertEqual(Sale.objects.get().payments.get().method, Payment.Method.NAKIT)


class DeleteAndStatusTests(EdgeCaseTestCase):
    def test_device_with_an_expense_is_not_deleted(self):
        Expense.objects.create(device=self.device, kind="parca", title="Ekran",
                               amount=TL("500"))
        response = self.client.post(reverse("stock:device_delete",
                                            kwargs={"pk": self.device.pk}))
        self.assertRedirects(response, reverse("stock:device_detail",
                                               kwargs={"pk": self.device.pk}))
        self.assertTrue(Device.objects.filter(pk=self.device.pk).exists())
        self.assertTrue(DeviceStatusLog.objects.filter(device=self.device).exists())

    def test_trade_in_device_is_not_deleted(self):
        cart = {"customer_id": self.customer.pk, "lines": [],
                "trade_ins": [{"device_model_id": self.model.pk, "amount": "1000"}]}
        sale = services.create_sale_from_cart(cart, user=self.patron)
        device = sale.trade_ins.get().device
        response = self.client.post(reverse("stock:device_delete",
                                            kwargs={"pk": device.pk}))
        self.assertRedirects(response, reverse("stock:device_detail",
                                               kwargs={"pk": device.pk}))
        self.assertTrue(DeviceStatusLog.objects.filter(device=device).exists())

    def test_unknown_status_is_refused(self):
        for status in ("", "xyz"):
            with self.subTest(status=status):
                response = self.client.post(
                    reverse("stock:device_status", kwargs={"pk": self.device.pk}),
                    {"status": status})
                self.assertEqual(response.status_code, 302)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, Device.Status.STOKTA)

    def test_returning_a_stale_item_twice_is_refused(self):
        sale = self.sell_accessory()
        stale = SaleItem.objects.get(sale=sale)
        services.return_sale_item(SaleItem.objects.get(pk=stale.pk), user=self.patron)
        with self.assertRaises(services.StockError):
            services.return_sale_item(stale, user=self.patron)
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, 10)
        self.assertEqual(sale.payments.filter(kind=Payment.Kind.IADE).count(), 1)


class ScriptInjectionTests(EdgeCaseTestCase):
    def script_attributes(self, body):
        values = re.findall(r'(?:x-data|onsubmit|onclick)="([^"]*)"', body)
        return [html.unescape(value) for value in values]

    def assert_not_injected(self, response):
        self.assertEqual(response.status_code, 200)
        for value in self.script_attributes(response.content.decode()):
            self.assertNotIn(PAYLOAD, value)

    def test_list_filters_are_escaped_for_alpine(self):
        for name, param in (("stock:sale_list", "filtre"),
                            ("stock:accessory_list", "filtre"),
                            ("stock:device_list", "durum"),
                            ("stock:contact_list", "rol"),
                            ("stock:expense_list", "kapsam"),
                            ("dashboard:leads", "tab")):
            with self.subTest(view=name):
                self.assert_not_injected(self.client.get(reverse(name), {param: PAYLOAD}))

    def test_names_in_confirm_dialogs_are_escaped(self):
        self.customer.full_name = f"Ali{PAYLOAD}"
        self.customer.save()
        self.assert_not_injected(self.client.get(
            reverse("stock:contact_detail", kwargs={"pk": self.customer.pk})))

        self.accessory.name = f"iPhone 15{PAYLOAD}"
        self.accessory.save()
        sale = self.sell_accessory()
        self.assert_not_injected(self.client.get(
            reverse("stock:sale_detail", kwargs={"pk": sale.pk})))


class PersonelLimitTests(EdgeCaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("seed_roles", stdout=StringIO(), stderr=StringIO())
        cls.personel = User.objects.create_user("personel", password="pw")
        cls.personel.groups.add(Group.objects.get(name=GROUP_PERSONEL))
        cls.category = AccessoryCategory.objects.create(name="Kılıf")

    def setUp(self):
        self.client.force_login(self.personel)

    def test_personel_cannot_delete_or_void(self):
        sale = self.sell_accessory()
        for url in (reverse("stock:device_delete", kwargs={"pk": self.device.pk}),
                    reverse("stock:contact_delete", kwargs={"pk": self.customer.pk}),
                    reverse("stock:simple_delete",
                            kwargs={"key": "kategoriler", "pk": self.category.pk}),
                    reverse("stock:sale_void", kwargs={"pk": sale.pk})):
            with self.subTest(url=url):
                response = self.client.post(url, {"reason": "deneme"})
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith(reverse("dashboard:login")))
        self.assertTrue(Device.objects.filter(pk=self.device.pk).exists())
        self.assertTrue(Contact.objects.filter(pk=self.customer.pk).exists())
        self.assertTrue(AccessoryCategory.objects.filter(pk=self.category.pk).exists())
        sale.refresh_from_db()
        self.assertEqual(sale.status, Sale.Status.TAMAMLANDI)

    def test_personel_does_not_see_delete_or_void_buttons(self):
        sale = self.sell_accessory()
        for page, hidden in (
            (reverse("stock:device_detail", kwargs={"pk": self.device.pk}),
             reverse("stock:device_delete", kwargs={"pk": self.device.pk})),
            (reverse("stock:contact_detail", kwargs={"pk": self.customer.pk}),
             reverse("stock:contact_delete", kwargs={"pk": self.customer.pk})),
            (reverse("stock:simple_list", kwargs={"key": "kategoriler"}),
             reverse("stock:simple_delete",
                     kwargs={"key": "kategoriler", "pk": self.category.pk})),
            (reverse("stock:sale_detail", kwargs={"pk": sale.pk}),
             reverse("stock:sale_void", kwargs={"pk": sale.pk})),
        ):
            with self.subTest(page=page):
                response = self.client.get(page)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, hidden)

    def test_personel_can_still_sell_and_return(self):
        sale = self.sell_accessory()
        item = sale.items.get()
        self.client.post(reverse("stock:sale_item_return",
                                 kwargs={"pk": sale.pk, "item_id": item.pk}),
                         {"reason": "", "refund": "1"})
        item.refresh_from_db()
        self.assertIsNotNone(item.returned_at)
