"""Cihaz formunda aranabilir seçim ve pop-up'la cari/model ekleme.

Pop-up sayfadan çıkmaz: kayıt sonrası yönlendirme yerine HX-Trigger ile
`bayco:created` döner ve static/js/combobox.js yeni kaydı seçim kutusuna
ekler. Bu yüzden arkadaki cihaz formuna girilmiş değerler kaybolmaz.
"""

import json
import re

from django.urls import reverse

from apps.dashboard.forms import SearchableSelect
from apps.staff.models import ActivityLog
from apps.stock.forms import DeviceForm
from apps.stock.models import Contact, Device, DeviceModel

from .test_views import ScreenTestCase


def created(response) -> dict:
    return json.loads(response["HX-Trigger"])["bayco:created"]


class DeviceFormQuickAddTests(ScreenTestCase):
    def setUp(self):
        self.client.force_login(self.patron)

    def device_payload(self, **overrides):
        data = {
            "device_model": self.model.pk, "condition": "ikinci_el",
            "imei1": "356938035643809", "imei2": "", "serial_no": "",
            "storage": "128GB", "color": "Mavi", "battery_health": "88",
            "shelf": "B1", "defect_note": "", "supplier": "",
            "purchase_date": "2026-09-01", "purchase_price": "12000",
            "list_price": "14500", "warranty_months": "0", "warranty_start": "",
        }
        data.update(overrides)
        return data

    def test_selects_are_searchable_and_open_popups_in_place(self):
        response = self.client.get(reverse("stock:device_create"))
        self.assertContains(response, 'name="supplier"')
        self.assertContains(response, 'data-combobox="1"', count=2)
        self.assertContains(response, "?alan=id_supplier")
        self.assertContains(response, "?alan=id_device_model")
        self.assertContains(response, 'id="quick-body"')
        self.assertContains(response, "data-guard")
        # Eski "Yeni model ekleyin" bağlantısı sayfadan çıkıp girilenleri siliyordu.
        self.assertNotContains(response, "?next=")
        # Pop-up düğmeleri arkadaki formu göndermemeli (type="button").
        buttons = re.findall(r'<button([^>]*)hx-target="#quick-body"', response.content.decode())
        self.assertEqual(len(buttons), 2)
        for attrs in buttons:
            self.assertIn('type="button"', attrs)

    def test_popup_shell_only_on_forms_with_quick_add(self):
        response = self.client.get(reverse("stock:contact_create"))
        self.assertNotContains(response, 'id="quick-body"')
        self.assertNotContains(response, "data-guard")

    def test_customer_only_contact_is_listed_and_becomes_supplier(self):
        customer = Contact.objects.create(full_name="Zeynep Kara", phone="0544 000 11 22")
        self.assertFalse(customer.is_supplier)
        form = DeviceForm(user=self.patron)
        self.assertIn(customer, form.fields["supplier"].queryset)

        response = self.client.post(reverse("stock:device_create"),
                                    self.device_payload(supplier=customer.pk))
        device = Device.objects.get(imei1="356938035643809")
        self.assertRedirects(response, reverse("stock:device_detail", kwargs={"pk": device.pk}))
        self.assertEqual(device.supplier, customer)
        customer.refresh_from_db()
        self.assertTrue(customer.is_supplier)
        self.assertTrue(customer.is_customer)

    def test_bound_form_keeps_guard_dirty_after_error(self):
        response = self.client.post(reverse("stock:device_create"),
                                    self.device_payload(device_model=""))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-guard="dirty"')
        self.assertContains(response, 'value="356938035643809"')

    def test_dates_render_in_the_format_date_inputs_accept(self):
        # type="date" yerel biçimi ("30/09/2026") reddeder: alan boş görünürdü.
        response = self.client.get(reverse("stock:device_edit", kwargs={"pk": self.device.pk}))
        self.assertContains(
            response, f'name="purchase_date" value="{self.device.purchase_date.isoformat()}"')

    def test_options_carry_search_text_and_phone_hint(self):
        html = str(DeviceForm(user=self.patron)["supplier"])
        self.assertIn(f'data-search="{self.contact.search_blob}"', html)
        self.assertIn('data-hint="0532 111 22 33"', html)
        self.assertIsInstance(DeviceForm.base_fields["device_model"].widget, SearchableSelect)


class ContactQuickTests(ScreenTestCase):
    def setUp(self):
        self.client.force_login(self.personel)
        self.url = reverse("stock:contact_quick") + "?alan=id_supplier"

    def payload(self, **overrides):
        data = {"full_name": "Şükrü Işık", "phone": "0555 987 65 43", "company": "",
                "email": "", "tax_no": "", "address": "", "is_customer": "on",
                "is_supplier": "on", "note": ""}
        data.update(overrides)
        return data

    def test_get_renders_the_same_fields_as_the_contact_form(self):
        response = self.client.get(self.url)
        for name in ("full_name", "phone", "company", "email", "tax_no", "address",
                     "is_customer", "is_supplier", "note"):
            self.assertContains(response, f'name="{name}"')
        # Pop-up'ın id'leri cihaz formununkilerle çakışmaz.
        self.assertContains(response, 'id="quick_full_name"')
        self.assertContains(response, "autofocus")
        # Cihaz formundan eklenen kişi tedarikçi olarak işaretli gelir.
        self.assertContains(response, 'name="is_supplier" class="toggle-check" id="quick_is_supplier" checked')
        self.assertNotContains(response, "<aside")

    def test_valid_post_returns_the_new_contact_to_the_select(self):
        response = self.client.post(self.url, self.payload())
        self.assertEqual(response.status_code, 200)
        contact = Contact.objects.get(full_name="Şükrü Işık")
        self.assertTrue(contact.is_supplier)
        # Başlık ASCII kalmalı: latin-1 dışı ş/ı MIME kodlanırsa htmx JSON'u okuyamaz.
        response["HX-Trigger"].encode("ascii")
        self.assertEqual(created(response), {
            "field": "id_supplier", "value": str(contact.pk), "label": "Şükrü Işık",
            "search": contact.search_blob, "hint": "0555 987 65 43",
        })
        self.assertEqual(response.content, b"")
        log = ActivityLog.objects.get(view_name="stock:contact_quick")
        self.assertEqual(log.action, "Cari ekledi")
        self.assertEqual(log.target, "Şükrü Işık")

    def test_invalid_post_redraws_the_popup_and_is_logged_as_unsaved(self):
        response = self.client.post(self.url, self.payload(is_customer="", is_supplier=""))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("HX-Trigger", response)
        self.assertContains(response, "en az bir role")
        self.assertContains(response, 'value="Şükrü Işık"')
        self.assertFalse(Contact.objects.filter(full_name="Şükrü Işık").exists())
        log = ActivityLog.objects.get(view_name="stock:contact_quick")
        self.assertEqual(log.action, "Cari ekledi (form hatalı, kaydedilmedi)")

    def test_same_phone_asks_first_then_saves_on_confirm(self):
        response = self.client.post(self.url, self.payload(phone="0532 111 22 33"))
        self.assertNotIn("HX-Trigger", response)
        self.assertContains(response, "zaten kayıtlı")
        self.assertContains(response, f'data-created-value="{self.contact.pk}"')
        self.assertContains(response, 'data-created-field="id_supplier"')
        self.assertContains(response, 'name="confirm_phone" value="0532 111 22 33"')
        self.assertFalse(Contact.objects.filter(full_name="Şükrü Işık").exists())

        response = self.client.post(self.url, self.payload(phone="0532 111 22 33",
                                                           confirm_phone="0532 111 22 33"))
        self.assertIn("HX-Trigger", response)
        self.assertEqual(Contact.objects.filter(phone_norm=self.contact.phone_norm).count(), 2)

    def test_confirmation_does_not_cover_a_different_number(self):
        other = Contact.objects.create(full_name="Ali Veli", phone="0533 444 55 66")
        response = self.client.post(self.url, self.payload(phone=other.phone,
                                                           confirm_phone="0532 111 22 33"))
        self.assertNotIn("HX-Trigger", response)
        self.assertContains(response, "Ali Veli")

    def test_target_field_is_sanitised(self):
        for alan in ('"><script>', "supplier", "id_ş"):
            with self.subTest(alan=alan):
                response = self.client.post(
                    reverse("stock:contact_quick") + "?" + f"alan={alan}",
                    self.payload(full_name=f"Kişi {len(alan)}", phone=""))
                self.assertEqual(created(response)["field"], "id_supplier")

    def test_pos_cart_is_untouched(self):
        self.client.post(self.url, self.payload())
        self.assertNotIn("customer_id", self.client.session.get("stock_cart", {}) or {})


class ModelQuickTests(ScreenTestCase):
    def setUp(self):
        self.client.force_login(self.personel)
        self.url = reverse("stock:simple_quick", kwargs={"key": "modeller"}) + "?alan=id_device_model"

    def test_get_keeps_the_brand_link_in_a_new_tab(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'target="_blank"')
        self.assertNotContains(response, "?next=")
        self.assertNotContains(response, 'name="is_active"')
        self.assertContains(response, 'data-combobox="1"')

    def test_valid_post_returns_the_new_model(self):
        response = self.client.post(self.url, {"brand": self.brand.pk, "name": "iPhone 15",
                                               "kind": "telefon"})
        model = DeviceModel.objects.get(name="iPhone 15")
        self.assertTrue(model.is_active)
        self.assertEqual(created(response)["label"], "Apple iPhone 15")
        self.assertEqual(created(response)["field"], "id_device_model")
        log = ActivityLog.objects.get(view_name="stock:simple_quick")
        self.assertEqual(log.action, "Model ekledi")

    def test_duplicate_model_is_a_popup_error(self):
        response = self.client.post(self.url, {"brand": self.brand.pk, "name": self.model.name,
                                               "kind": "telefon"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("HX-Trigger", response)
        self.assertEqual(DeviceModel.objects.filter(name=self.model.name).count(), 1)

    def test_default_target_follows_the_registry(self):
        response = self.client.post(reverse("stock:simple_quick", kwargs={"key": "modeller"}),
                                    {"brand": self.brand.pk, "name": "iPhone 16", "kind": "telefon"})
        self.assertEqual(created(response)["field"], "id_device_model")
