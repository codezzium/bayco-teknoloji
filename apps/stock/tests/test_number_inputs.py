"""Tutar alanlarında Türkçe biçim ("18.500,90") ve adet sayacı işaretleri.

Panel tutarları yazarken binlik noktası koyar (static/js/fields.js). En tehlikeli
hata "18.500"ün 18,5 okunmasıdır; buradaki testler sunucunun bu biçimi her giriş
yolunda (ModelForm, düz form, kasa view'ları) 18500 okuduğunu doğrular.
"""

from decimal import Decimal

from django.test import SimpleTestCase
from django.urls import reverse

from apps.dashboard.forms import ProductForm
from apps.dashboard.numbers import format_decimal_input, normalize_decimal_input
from apps.stock import cart as cart_utils
from apps.stock.forms import AccessoryForm, StockIntakeForm, StocktakeForm
from apps.stock.models import Accessory
from apps.stock.tests.test_edge_cases import EdgeCaseTestCase
from apps.stock.utils import parse_money

TL = Decimal


class NumberFormatTests(SimpleTestCase):
    def test_normalize(self):
        cases = {
            "18.500": "18500", "18.500,90": "18500.90", "150,90": "150.90",
            "150.90": "150.90", "1.234.567": "1234567", "₺ 18.500": "18500",
            "18.500,": "18500.", "12.5": "12.5", "0": "0",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_decimal_input(raw), expected)

    def test_parse_money_reads_thousands_dot(self):
        # Eskiden virgül noktaya çevriliyordu ve "18.500" 18,5 okunuyordu.
        self.assertEqual(parse_money("18.500"), TL("18500"))
        self.assertEqual(parse_money("18.500,90"), TL("18500.90"))
        self.assertEqual(parse_money("150,90"), TL("150.90"))
        self.assertEqual(parse_money("150.90"), TL("150.90"))
        self.assertIsNone(parse_money("abc"))

    def test_format(self):
        self.assertEqual(format_decimal_input(TL("18500.00")), "18.500")
        self.assertEqual(format_decimal_input(TL("150.9")), "150,90")
        self.assertEqual(format_decimal_input(TL("1234567.5")), "1.234.567,50")
        self.assertEqual(format_decimal_input(TL("18500"), 0), "18.500")
        self.assertEqual(format_decimal_input(None), "")
        # Hatalı form yeniden gösterilirken kullanıcının yazdığı korunur.
        self.assertEqual(format_decimal_input("18.500,9"), "18.500,9")


class MoneyFormTests(EdgeCaseTestCase):
    def accessory_data(self, **overrides):
        data = {"name": "Ekran Koruyucu", "variant": "", "brand": "", "category": "",
                "barcode": "", "cost": "1.250", "price": "2.499,90",
                "min_stock_level": "2", "note": "", "is_active": "on", "opening_qty": "3"}
        data.update(overrides)
        return data

    def test_accessory_form_reads_turkish_amounts(self):
        form = AccessoryForm(data=self.accessory_data(), user=self.patron)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["cost"], TL("1250"))
        self.assertEqual(form.cleaned_data["price"], TL("2499.90"))

    def test_accessory_create_view_saves_turkish_amounts(self):
        response = self.client.post(reverse("stock:accessory_create"), self.accessory_data())
        self.assertEqual(response.status_code, 302)
        accessory = Accessory.objects.get(name="Ekran Koruyucu")
        self.assertEqual((accessory.cost, accessory.price), (TL("1250"), TL("2499.90")))
        self.assertEqual(accessory.stock_qty, 3)

    def test_widgets_render_formatted_text_inputs(self):
        form = AccessoryForm(instance=Accessory(name="x", cost=TL("18500"), price=TL("150.90")),
                             user=self.patron)
        cost, price = str(form["cost"]), str(form["price"])
        self.assertIn('type="text"', price)
        self.assertIn('data-money="2"', price)
        self.assertIn('value="150,90"', price)
        self.assertIn('value="18.500"', cost)
        # Adet alanları sayaç olur; sınırlar alanın min/max'ından gelir.
        for name in ("opening_qty", "min_stock_level"):
            html = str(form[name])
            self.assertIn("data-qty", html)
            self.assertIn('type="text"', html)
            self.assertIn('data-min="0"', html)
        self.assertIn('data-max="99999"', str(form["opening_qty"]))

    def test_intake_and_stocktake_forms(self):
        form = StockIntakeForm(data={"quantity": "3", "unit_cost": "1.250,50", "note": ""},
                               user=self.patron)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["unit_cost"], TL("1250.50"))
        self.assertIn('data-min="1"', str(form["quantity"]))
        self.assertIn("data-qty", str(StocktakeForm()["counted_qty"]))

    def test_intake_view_saves_turkish_unit_cost(self):
        self.client.post(reverse("stock:accessory_adjust", kwargs={"pk": self.accessory.pk}),
                         {"mode": "giris", "quantity": "2", "unit_cost": "1.250,50", "note": ""})
        movement = self.accessory.movements.order_by("-pk").first()
        self.assertEqual((movement.quantity, movement.unit_cost), (2, TL("1250.50")))

    def test_product_price_has_no_decimals(self):
        field = ProductForm().fields["price"]
        self.assertEqual(field.clean("18.500"), TL("18500"))
        self.assertIn('data-money="0"', str(ProductForm()["price"]))


class PosTurkishAmountTests(EdgeCaseTestCase):
    def setUp(self):
        super().setUp()
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "sale", "code": self.accessory.barcode})
        self.lid = f"a-{self.accessory.pk}"

    def line(self):
        return cart_utils.get_cart(self.client)["lines"][0]

    def test_cart_price_and_discount(self):
        url = reverse("stock:cart_price", kwargs={"lid": self.lid})
        self.client.post(url, {"price": "18.500"})
        self.assertEqual(self.line()["unit"], "18500.00")
        self.client.post(url, {"price": "1.250,50", "discount": "1.000"})
        self.assertEqual((self.line()["unit"], self.line()["discount"]), ("1250.50", "1000.00"))

    def test_trade_in_amount(self):
        self.client.post(reverse("stock:cart_trade_in"), {
            "device_model": self.model.pk, "amount": "3.000", "imei1": "",
            "color": "", "storage": "", "note": ""})
        self.assertEqual(cart_utils.get_cart(self.client)["trade_ins"][0]["amount"], "3000.00")

    def test_cart_renders_text_inputs_for_money_and_quantity(self):
        response = self.client.get(reverse("stock:pos"))
        self.assertContains(response, 'name="price" data-money="2"')
        self.assertContains(response, 'value="120"')
        self.assertContains(response, 'name="qty" data-qty data-min="1"')
        self.assertContains(response, 'x-model="paidText"')
        self.assertNotContains(response, 'type="number"')
        # fields.js her panel sayfasında; çok satırlı {# #} yorumu sayfaya metin olarak sızmasın.
        self.assertContains(response, "js/fields.js")
        self.assertNotContains(response, "{#")
