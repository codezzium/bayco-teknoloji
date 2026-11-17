from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from apps.staff.models import ActivityLog
from apps.stock import services
from apps.stock.models import Accessory
from apps.stock.permissions import GROUP_PERSONEL
from apps.stock.reports import negative_stock, recent_products, stock_capital

TL = Decimal


class AccessoryDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("seed_roles", verbosity=0)
        cls.patron = User.objects.create_user("patron", password="pw",
                                              is_staff=True, is_superuser=True)
        cls.personel = User.objects.create_user("personel", password="pw")
        cls.personel.groups.add(Group.objects.get(name=GROUP_PERSONEL))

    def setUp(self):
        self.accessory = Accessory.objects.create(
            name="Yanlış Kılıf", barcode="8690000000024", cost=TL("40"), price=TL("90"))
        services.receive_accessory_stock(self.accessory, 5, user=self.patron, opening=True)

    def delete(self, user=None, reason="Yanlış girildi"):
        self.client.force_login(user or self.patron)
        return self.client.post(
            reverse("stock:accessory_delete", kwargs={"pk": self.accessory.pk}),
            {"reason": reason})

    def restore(self, user=None):
        self.client.force_login(user or self.patron)
        return self.client.post(
            reverse("stock:accessory_restore", kwargs={"pk": self.accessory.pk}))

    def list_ids(self, filtre=""):
        url = reverse("stock:accessory_list") + (f"?filtre={filtre}" if filtre else "")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return [a.pk for a in response.context["page"]]

    def test_delete_with_reason_moves_card_to_deleted_and_logs_reason(self):
        response = self.delete()
        self.assertRedirects(response, reverse("stock:accessory_list") + "?filtre=silinen",
                             fetch_redirect_response=False)
        self.accessory.refresh_from_db()
        self.assertTrue(self.accessory.is_deleted)
        self.assertFalse(self.accessory.is_active)
        self.assertEqual(self.accessory.deleted_by, self.patron)
        self.assertEqual(self.accessory.delete_reason, "Yanlış girildi")
        self.assertEqual(self.accessory.stock_qty, 5)
        log = ActivityLog.objects.get(view_name="stock:accessory_delete")
        self.assertEqual(log.action, "Aksesuarı sildi")
        self.assertEqual(log.detail["reason"], "Yanlış girildi")
        self.assertIn("Yanlış Kılıf", log.target)

    def test_blank_reason_does_not_delete(self):
        self.delete(reason="   ")
        self.accessory.refresh_from_db()
        self.assertFalse(self.accessory.is_deleted)
        self.assertTrue(self.accessory.is_active)
        log = ActivityLog.objects.get(view_name="stock:accessory_delete")
        self.assertIn("kaydedilmedi", log.action)

    def test_too_long_reason_does_not_delete(self):
        self.delete(reason="x" * 201)
        self.accessory.refresh_from_db()
        self.assertFalse(self.accessory.is_deleted)

    def test_personel_cannot_delete_or_restore(self):
        self.delete(user=self.personel)
        self.accessory.refresh_from_db()
        self.assertFalse(self.accessory.is_deleted)
        services.delete_accessory(self.accessory, user=self.patron, reason="Test")
        self.restore(user=self.personel)
        self.accessory.refresh_from_db()
        self.assertTrue(self.accessory.is_deleted)
        self.assertTrue(ActivityLog.objects.filter(kind=ActivityLog.Kind.YETKISIZ).exists())

    def test_get_is_not_allowed(self):
        self.client.force_login(self.patron)
        response = self.client.get(
            reverse("stock:accessory_delete", kwargs={"pk": self.accessory.pk}))
        self.assertEqual(response.status_code, 405)

    def test_lists_separate_deleted_from_active_and_passive(self):
        passive = Accessory.objects.create(name="Pasif Kart", is_active=False)
        self.delete()
        self.assertNotIn(self.accessory.pk, self.list_ids())
        self.assertNotIn(self.accessory.pk, self.list_ids("pasif"))
        self.assertIn(passive.pk, self.list_ids("pasif"))
        self.assertEqual(self.list_ids("silinen"), [self.accessory.pk])
        response = self.client.get(reverse("stock:accessory_list") + "?filtre=silinen")
        self.assertContains(response, "Yanlış girildi")
        self.assertContains(response, "Tekrar Aktif Et")

    def test_detail_of_deleted_card_shows_banner_and_hides_stock_forms(self):
        self.delete()
        response = self.client.get(
            reverse("stock:accessory_detail", kwargs={"pk": self.accessory.pk}))
        self.assertContains(response, "Bu aksesuar silindi")
        self.assertContains(response, "Yanlış girildi")
        self.assertContains(response, reverse("stock:accessory_restore",
                                              kwargs={"pk": self.accessory.pk}))
        self.assertNotContains(response, "Girişi Kaydet")
        self.assertNotContains(response, reverse("stock:accessory_delete",
                                                 kwargs={"pk": self.accessory.pk}))

    def test_detail_shows_delete_form_only_with_delete_access(self):
        url = reverse("stock:accessory_detail", kwargs={"pk": self.accessory.pk})
        delete_url = reverse("stock:accessory_delete", kwargs={"pk": self.accessory.pk})
        self.client.force_login(self.patron)
        self.assertContains(self.client.get(url), delete_url)
        self.client.force_login(self.personel)
        self.assertNotContains(self.client.get(url), delete_url)

    def test_restore_reactivates_card_and_logs(self):
        self.delete()
        response = self.restore()
        self.assertRedirects(response, reverse("stock:accessory_detail",
                                               kwargs={"pk": self.accessory.pk}),
                             fetch_redirect_response=False)
        self.accessory.refresh_from_db()
        self.assertFalse(self.accessory.is_deleted)
        self.assertTrue(self.accessory.is_active)
        self.assertIsNone(self.accessory.deleted_by)
        self.assertEqual(self.accessory.delete_reason, "")
        self.assertEqual(self.accessory.stock_qty, 5)
        log = ActivityLog.objects.get(view_name="stock:accessory_restore")
        self.assertEqual(log.action, "Aksesuarı tekrar aktif etti")
        self.assertIn(self.accessory.pk, self.list_ids())

    def test_deleted_barcode_is_free_and_blocks_restore_when_taken(self):
        self.delete()
        replacement = Accessory.objects.create(name="Doğru Kılıf", barcode="8690000000024")
        self.assertEqual(services.resolve_scan("8690000000024"), replacement)
        self.restore()
        self.accessory.refresh_from_db()
        self.assertTrue(self.accessory.is_deleted)
        log = ActivityLog.objects.get(view_name="stock:accessory_restore")
        self.assertIn("kaydedilmedi", log.action)
        with self.assertRaises(services.StockError):
            services.restore_accessory(self.accessory, user=self.patron)

    def test_new_card_form_accepts_barcode_of_deleted_card(self):
        self.delete()
        self.client.post(reverse("stock:accessory_create"), {
            "name": "Doğru Kılıf", "barcode": "8690000000024", "cost": "40",
            "price": "90", "min_stock_level": "2", "is_active": "on", "opening_qty": "0",
        })
        self.assertTrue(Accessory.objects.filter(name="Doğru Kılıf",
                                                 barcode="8690000000024").exists())

    def test_live_duplicate_barcode_is_still_a_form_error(self):
        self.client.force_login(self.patron)
        data = {"name": "Kopya Kılıf", "barcode": "8690000000024", "cost": "40",
                "price": "90", "min_stock_level": "2", "is_active": "on", "opening_qty": "0"}
        response = self.client.post(reverse("stock:accessory_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "zaten")
        self.assertFalse(Accessory.objects.filter(name="Kopya Kılıf").exists())
        other = Accessory.objects.create(name="Diğer Kılıf", barcode="8690000000031")
        data.pop("opening_qty")
        response = self.client.post(
            reverse("stock:accessory_edit", kwargs={"pk": other.pk}), data)
        self.assertEqual(response.status_code, 200)
        other.refresh_from_db()
        self.assertEqual(other.barcode, "8690000000031")

    def test_editing_card_keeps_its_own_barcode(self):
        self.client.force_login(self.patron)
        response = self.client.post(
            reverse("stock:accessory_edit", kwargs={"pk": self.accessory.pk}),
            {"name": "Doğru Ad", "barcode": "8690000000024", "cost": "40", "price": "90",
             "min_stock_level": "2", "is_active": "on"})
        self.assertEqual(response.status_code, 302)
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.name, "Doğru Ad")

    def test_deleted_card_cannot_be_scanned_sold_or_stocked(self):
        self.delete()
        self.assertIsNone(services.resolve_scan("8690000000024"))
        self.assertIsNone(services.resolve_scan(self.accessory.sku))
        self.client.post(reverse("stock:cart_add"),
                         {"kind": "aksesuar", "id": self.accessory.pk, "qty": "1"},
                         HTTP_HX_REQUEST="true")
        self.assertFalse(self.client.session.get("stock_cart", {}).get("lines"))
        for call in (
            lambda: services.receive_accessory_stock(self.accessory, 1, user=self.patron),
            lambda: services.adjust_accessory_stock(self.accessory, 0, user=self.patron),
            lambda: services.write_off_accessory(self.accessory, 1, user=self.patron),
        ):
            with self.assertRaises(services.StockError):
                call()
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, 5)

    def test_adjust_and_edit_views_refuse_deleted_card(self):
        self.delete()
        self.client.post(reverse("stock:accessory_adjust", kwargs={"pk": self.accessory.pk}),
                         {"mode": "giris", "quantity": "3"})
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, 5)
        response = self.client.get(
            reverse("stock:accessory_edit", kwargs={"pk": self.accessory.pk}))
        self.assertRedirects(response, reverse("stock:accessory_detail",
                                               kwargs={"pk": self.accessory.pk}),
                             fetch_redirect_response=False)

    def test_checkout_refuses_card_deleted_after_it_was_added_to_cart(self):
        cart = {"lines": [{"lid": f"a-{self.accessory.pk}", "kind": "aksesuar",
                           "id": self.accessory.pk, "name": "Yanlış Kılıf",
                           "qty": 1, "unit": "90.00"}]}
        services.delete_accessory(self.accessory, user=self.patron, reason="Test")
        with self.assertRaisesRegex(services.StockError, "silinmiş"):
            services.create_sale_from_cart(cart, user=self.patron,
                                           payments=[{"amount": TL("90")}])
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, 5)

    def test_sold_card_can_be_deleted_and_old_sale_still_returns(self):
        cart = {"lines": [{"lid": "a", "kind": "aksesuar", "id": self.accessory.pk,
                           "name": "Yanlış Kılıf", "qty": 1, "unit": "90.00"}]}
        sale = services.create_sale_from_cart(cart, user=self.patron,
                                              payments=[{"amount": TL("90")}])
        self.delete()
        self.accessory.refresh_from_db()
        self.assertTrue(self.accessory.is_deleted)
        services.return_sale_item(sale.items.get(), user=self.patron, reason="İade")
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, 5)

    def test_reports_ignore_deleted_cards(self):
        broken = Accessory.objects.create(name="Eksi Kart", cost=TL("10"))
        services.write_off_accessory(broken, 2, user=self.patron)
        before = stock_capital()["accessories"]
        services.delete_accessory(self.accessory, user=self.patron, reason="Test")
        services.delete_accessory(broken, user=self.patron, reason="Test")
        self.assertEqual(stock_capital()["accessories"], before - TL("200"))
        self.assertNotIn(broken, list(negative_stock()))
        recent = [row.get("accessory") for row in recent_products()]
        self.assertNotIn(self.accessory, recent)

    def test_delete_twice_is_refused(self):
        services.delete_accessory(self.accessory, user=self.patron, reason="Test")
        with self.assertRaises(services.StockError):
            services.delete_accessory(self.accessory, user=self.patron, reason="Tekrar")
