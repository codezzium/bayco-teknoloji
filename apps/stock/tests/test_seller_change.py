"""Satıcı değiştirme (patron onaylı), kasada satıcı seçimi, panel bildirimleri
ve personel bazlı satış raporları."""

from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Brand
from apps.staff.models import ActivityLog, Notification
from apps.stock import reports as rpt
from apps.stock import services
from apps.stock.models import (
    Accessory,
    AccessoryCategory,
    Contact,
    DeviceModel,
    Sale,
    SellerChange,
)
from apps.stock.permissions import GROUP_PERSONEL

TL = Decimal
HTMX = {"HTTP_HX_REQUEST": "true"}


class SellerTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_roles", verbosity=0)
        personel = Group.objects.get(name=GROUP_PERSONEL)
        cls.patron = User.objects.create_user("patron", password="pw",
                                              is_staff=True, is_superuser=True)
        cls.ali = User.objects.create_user("ali", password="pw", first_name="Ali")
        cls.ayse = User.objects.create_user("ayse", password="pw", first_name="Ayşe")
        for user in (cls.ali, cls.ayse):
            user.groups.add(personel)
        cls.outsider = User.objects.create_user("disari", password="pw")  # panelde değil

        cls.model = DeviceModel.objects.create(brand=Brand.objects.create(name="Apple"),
                                               name="iPhone 13")
        cls.contact = Contact.objects.create(full_name="Müşteri", phone="0532 000 00 00")
        cls.category = AccessoryCategory.objects.create(name="Kablo")
        cls.accessory = Accessory.objects.create(name="USB-C Kablo", category=cls.category,
                                                 cost=TL("80"), price=TL("150"))
        services.receive_accessory_stock(cls.accessory, 50, user=cls.patron, opening=True)

    def make_device(self, imei="351234567890123"):
        return services.create_device(user=self.patron, device_model=self.model, imei1=imei,
                                      purchase_price=TL("16000"), list_price=TL("18500"))

    def sell(self, user, *, device=None, accessories=0, seller=None):
        lines = []
        if device is not None:
            lines.append({"lid": "d", "kind": "cihaz", "id": device.pk,
                          "name": device.label, "qty": 1, "unit": "18500.00"})
        if accessories:
            lines.append({"lid": "a", "kind": "aksesuar", "id": self.accessory.pk,
                          "name": self.accessory.name, "qty": accessories,
                          "unit": "150.00"})
        return services.create_sale_from_cart(
            {"customer_id": self.contact.pk, "lines": lines}, user=user, seller=seller)

    def request(self, sale, user, to_user, reason="Satışı başkası yaptı"):
        return services.request_seller_change(sale, to_user=to_user, reason=reason, user=user)

    def notes(self, user):
        return list(Notification.objects.filter(user=user).values_list("message", flat=True))


class SellerChangeServiceTests(SellerTestCase):
    def test_personel_request_waits_for_patron(self):
        sale = self.sell(self.ali, accessories=1)
        change = self.request(sale, self.ali, self.ayse)

        self.assertEqual(change.status, SellerChange.Status.BEKLIYOR)
        sale.refresh_from_db()
        self.assertEqual(sale.cashier, self.ali)
        self.assertEqual(len(self.notes(self.patron)), 1)
        self.assertIn("Ali → Ayşe yapmak istiyor", self.notes(self.patron)[0])
        self.assertEqual(self.notes(self.ayse), [])

    def test_personel_may_request_for_any_sale(self):
        """Kullanıcı kararı: personel tüm satışlar için talep açabilir."""
        sale = self.sell(self.patron, accessories=1)
        change = self.request(sale, self.ali, self.ayse)
        self.assertEqual(change.status, SellerChange.Status.BEKLIYOR)

    def test_patron_changes_directly_and_both_sellers_are_told(self):
        sale = self.sell(self.ali, accessories=1)
        change = self.request(sale, self.patron, self.ayse)

        self.assertEqual(change.status, SellerChange.Status.ONAYLANDI)
        self.assertEqual(change.decided_by, self.patron)
        self.assertEqual(change.from_user, self.ali)
        sale.refresh_from_db()
        self.assertEqual(sale.cashier, self.ayse)
        self.assertIn("sizin adınıza", self.notes(self.ayse)[0])
        self.assertIn("Ayşe adına aktarıldı", self.notes(self.ali)[0])
        self.assertEqual(self.notes(self.patron), [])

    def test_approve_moves_the_sale_and_tells_the_requester(self):
        sale = self.sell(self.ali, accessories=1)
        change = self.request(sale, self.ali, self.ayse)
        change = services.decide_seller_change(change, user=self.patron, approve=True)

        self.assertEqual(change.status, SellerChange.Status.ONAYLANDI)
        sale.refresh_from_db()
        self.assertEqual(sale.cashier, self.ayse)
        self.assertEqual(len(self.notes(self.ali)), 1)  # tek bildirim: "onaylandı"
        self.assertIn("onaylandı", self.notes(self.ali)[0])
        self.assertIn("sizin adınıza", self.notes(self.ayse)[0])

    def test_reject_keeps_the_seller(self):
        sale = self.sell(self.ali, accessories=1)
        change = self.request(sale, self.ali, self.ayse)
        change = services.decide_seller_change(change, user=self.patron, approve=False,
                                               note="Satışı Ali yaptı")

        self.assertEqual(change.status, SellerChange.Status.REDDEDILDI)
        sale.refresh_from_db()
        self.assertEqual(sale.cashier, self.ali)
        self.assertIn("reddedildi", self.notes(self.ali)[0])
        self.assertIn("Satışı Ali yaptı", self.notes(self.ali)[0])
        self.assertEqual(self.notes(self.ayse), [])

    def test_invalid_requests_are_refused(self):
        sale = self.sell(self.ali, accessories=1)
        for to_user, reason, message in (
                (self.ali, "x", "zaten"),
                (self.ayse, "   ", "gerekçe"),
                (self.outsider, "x", "ekipte"),
        ):
            with self.subTest(to_user=to_user.username), \
                    self.assertRaisesMessage(services.StockError, message):
                self.request(sale, self.ali, to_user, reason)

        self.request(sale, self.ali, self.ayse)
        with self.assertRaisesMessage(services.StockError, "onay bekleyen"):
            self.request(sale, self.ayse, self.ayse)

        voided = self.sell(self.ali, accessories=1)
        services.void_sale(voided, user=self.patron, reason="Hata")
        with self.assertRaisesMessage(services.StockError, "İptal"):
            self.request(voided, self.patron, self.ayse)

    def test_patron_direct_change_supersedes_pending_request(self):
        sale = self.sell(self.ali, accessories=1)
        pending = self.request(sale, self.ali, self.ayse)
        self.request(sale, self.patron, self.patron, "Satışı ben yaptım")

        pending.refresh_from_db()
        self.assertEqual(pending.status, SellerChange.Status.GECERSIZ)
        sale.refresh_from_db()
        self.assertEqual(sale.cashier, self.patron)

    def test_stale_request_becomes_invalid_instead_of_overwriting(self):
        sale = self.sell(self.ali, accessories=1)
        change = self.request(sale, self.ali, self.ayse)
        Sale.objects.filter(pk=sale.pk).update(cashier=self.patron)

        change = services.decide_seller_change(change, user=self.patron, approve=True)
        self.assertEqual(change.status, SellerChange.Status.GECERSIZ)
        sale.refresh_from_db()
        self.assertEqual(sale.cashier, self.patron)

    def test_voiding_the_sale_closes_the_pending_request(self):
        sale = self.sell(self.ali, accessories=1)
        change = self.request(sale, self.ali, self.ayse)
        services.void_sale(sale, user=self.patron, reason="Hata")
        change.refresh_from_db()
        self.assertEqual(change.status, SellerChange.Status.GECERSIZ)

    def test_only_patron_can_decide(self):
        sale = self.sell(self.ali, accessories=1)
        change = self.request(sale, self.ali, self.ayse)
        with self.assertRaises(services.StockError):
            services.decide_seller_change(change, user=self.ayse, approve=True)


class SellerChangeScreenTests(SellerTestCase):
    def test_popup_sends_personel_request_for_approval(self):
        sale = self.sell(self.ali, accessories=1)
        self.client.force_login(self.ali)
        url = reverse("stock:sale_seller_change", kwargs={"pk": sale.pk})

        response = self.client.get(url, **HTMX)
        self.assertContains(response, "Onaya Gönder")
        self.assertContains(response, "Ayşe")

        response = self.client.post(url, {"to_user": self.ayse.pk,
                                          "reason": "Satışı Ayşe yaptı"}, **HTMX)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Refresh"], "true")
        self.assertTrue(SellerChange.objects.filter(
            sale=sale, status=SellerChange.Status.BEKLIYOR).exists())
        log = ActivityLog.objects.get(view_name="stock:sale_seller_change")
        self.assertEqual(log.action, "Satıcı değişikliği yaptı/istedi")
        self.assertEqual(log.target, sale.receipt_no)
        self.assertEqual(log.detail["Sonuç"], "Onay bekliyor")

        # Bekleyen talep varken pop-up formu değil durumu gösterir.
        response = self.client.get(url, **HTMX)
        self.assertContains(response, "patron onayını bekliyor")
        self.assertNotContains(response, "Onaya Gönder")

    def test_popup_requires_a_reason(self):
        sale = self.sell(self.ali, accessories=1)
        self.client.force_login(self.ali)
        response = self.client.post(
            reverse("stock:sale_seller_change", kwargs={"pk": sale.pk}),
            {"to_user": self.ayse.pk, "reason": ""}, **HTMX)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SellerChange.objects.exists())
        log = ActivityLog.objects.get(view_name="stock:sale_seller_change")
        self.assertIn("form hatalı", log.action)

    def test_patron_popup_changes_immediately(self):
        sale = self.sell(self.ali, accessories=1)
        self.client.force_login(self.patron)
        self.client.post(reverse("stock:sale_seller_change", kwargs={"pk": sale.pk}),
                         {"to_user": self.ayse.pk, "reason": "Düzeltme"}, **HTMX)
        sale.refresh_from_db()
        self.assertEqual(sale.cashier, self.ayse)

    def test_patron_decides_from_notifications_page(self):
        sale = self.sell(self.ali, accessories=1)
        change = self.request(sale, self.ali, self.ayse)
        self.client.force_login(self.patron)

        page = self.client.get(reverse("staff:notifications"))
        self.assertContains(page, "Onay Bekleyen Satıcı Değişiklikleri")
        self.assertContains(page, sale.receipt_no)

        response = self.client.post(
            reverse("stock:seller_change_decide", kwargs={"pk": change.pk}),
            {"decision": "onayla", "next": reverse("staff:notifications")})
        self.assertRedirects(response, reverse("staff:notifications"),
                             fetch_redirect_response=False)
        sale.refresh_from_db()
        self.assertEqual(sale.cashier, self.ayse)
        log = ActivityLog.objects.get(view_name="stock:seller_change_decide")
        self.assertEqual(log.action, "Satıcı değişikliğini onayladı")

    def test_personel_cannot_decide(self):
        sale = self.sell(self.ali, accessories=1)
        change = self.request(sale, self.ali, self.ayse)
        self.client.force_login(self.ayse)
        response = self.client.post(
            reverse("stock:seller_change_decide", kwargs={"pk": change.pk}),
            {"decision": "onayla"})
        self.assertRedirects(response, reverse("dashboard:home"),
                             fetch_redirect_response=False)
        change.refresh_from_db()
        self.assertEqual(change.status, SellerChange.Status.BEKLIYOR)
        self.assertTrue(ActivityLog.objects.filter(kind=ActivityLog.Kind.YETKISIZ).exists())

    def test_bell_counts_unread_and_page_marks_them_read(self):
        sale = self.sell(self.ali, accessories=1)
        self.request(sale, self.patron, self.ayse)
        self.client.force_login(self.ayse)

        home = self.client.get(reverse("stock:sale_list"))
        self.assertContains(home, "Bildirimler (1 yeni)")
        self.client.get(reverse("staff:notifications"))
        self.assertFalse(Notification.objects.filter(user=self.ayse,
                                                     read_at__isnull=True).exists())
        home = self.client.get(reverse("stock:sale_list"))
        self.assertNotContains(home, "1 yeni")

    def test_sale_list_shows_switch_button_pending_chip_and_filters_by_person(self):
        own = self.sell(self.ali, accessories=1)
        other = self.sell(self.ayse, accessories=1)
        self.request(own, self.ali, self.ayse)
        self.client.force_login(self.ali)

        response = self.client.get(reverse("stock:sale_list"))
        self.assertContains(response, reverse("stock:sale_seller_change",
                                              kwargs={"pk": own.pk}))
        self.assertContains(response, "Satıcı onayda", count=1)

        response = self.client.get(reverse("stock:sale_list"),
                                   {"personel": self.ayse.pk}, **HTMX)
        self.assertContains(response, other.receipt_no)
        self.assertNotContains(response, own.receipt_no)

    def test_sale_detail_shows_history(self):
        sale = self.sell(self.ali, accessories=1)
        self.request(sale, self.patron, self.ayse, "Kasada yanlış oturum")
        self.client.force_login(self.ali)
        response = self.client.get(reverse("stock:sale_detail", kwargs={"pk": sale.pk}))
        self.assertContains(response, "Satıcı Geçmişi")
        self.assertContains(response, "Kasada yanlış oturum")

    def test_device_form_does_not_submit_on_enter(self):
        self.client.force_login(self.ali)
        response = self.client.get(reverse("stock:device_create"))
        self.assertContains(response, "data-enter-next")


class CheckoutSellerTests(SellerTestCase):
    def checkout(self, user, seller):
        self.client.force_login(user)
        self.client.post(reverse("stock:cart_add"),
                         {"kind": "aksesuar", "id": self.accessory.pk, "qty": "1"})
        return self.client.post(reverse("stock:checkout"), {
            "paid_amount": "", "payment_method": "nakit", "due_date": "",
            "seller": seller.pk,
        })

    def test_cart_offers_the_team_with_current_user_selected(self):
        self.client.force_login(self.ali)
        self.client.post(reverse("stock:cart_add"),
                         {"kind": "aksesuar", "id": self.accessory.pk, "qty": "1"})
        response = self.client.get(reverse("stock:pos"))
        self.assertContains(response, 'name="seller"')
        self.assertContains(response, f'value="{self.ali.pk}" selected')
        self.assertContains(response, "patron onayına düşer")

    def test_personel_choosing_someone_else_goes_to_approval(self):
        response = self.checkout(self.ali, self.ayse)
        self.assertEqual(response.status_code, 200)
        sale = Sale.objects.get()
        self.assertEqual(sale.cashier, self.ali)
        change = SellerChange.objects.get(sale=sale)
        self.assertEqual(change.status, SellerChange.Status.BEKLIYOR)
        self.assertEqual(change.to_user, self.ayse)
        self.assertEqual(len(self.notes(self.patron)), 1)
        log = ActivityLog.objects.get(view_name="stock:checkout")
        self.assertEqual(log.detail["Satıcı"], "Patron onayına gönderildi")

    def test_personel_selling_as_self_needs_nothing(self):
        self.checkout(self.ali, self.ali)
        self.assertEqual(Sale.objects.get().cashier, self.ali)
        self.assertFalse(SellerChange.objects.exists())

    def test_patron_choice_is_written_directly(self):
        self.checkout(self.patron, self.ayse)
        self.assertEqual(Sale.objects.get().cashier, self.ayse)
        self.assertFalse(SellerChange.objects.exists())

    def test_seller_outside_the_team_falls_back_to_current_user(self):
        self.checkout(self.ali, self.outsider)
        self.assertEqual(Sale.objects.get().cashier, self.ali)
        self.assertFalse(SellerChange.objects.exists())


class StaffReportTests(SellerTestCase):
    def setUp(self):
        self.today = timezone.localdate()
        # Ali: 1 cihaz + 2 aksesuar (tek fiş); Ayşe: 3 aksesuar.
        self.ali_sale = self.sell(self.ali, device=self.make_device(), accessories=2)
        self.ayse_sale = self.sell(self.ayse, accessories=3)

    def rows(self):
        return {row["user"]: row for row in rpt.sales_by_staff(self.today, self.today)}

    def test_sales_are_split_by_person_and_kind(self):
        rows = self.rows()
        ali, ayse = rows[self.ali], rows[self.ayse]
        self.assertEqual((ali["receipts"], ali["device_qty"], ali["accessory_qty"]), (1, 1, 2))
        self.assertEqual(ali["device_revenue"], TL("18500.00"))
        self.assertEqual(ali["accessory_revenue"], TL("300.00"))
        self.assertEqual(ali["revenue"], TL("18800.00"))
        self.assertEqual(ali["profit"], TL("18800.00") - TL("16000") - TL("160"))
        self.assertEqual((ayse["receipts"], ayse["device_qty"], ayse["accessory_qty"]),
                         (1, 0, 3))
        self.assertEqual(ayse["revenue"], TL("450.00"))
        self.assertEqual(rpt.sales_by_staff(self.today, self.today)[0]["user"], self.ali)
        self.assertAlmostEqual(float(ali["share"] + ayse["share"]), 100.0, places=2)

    def test_returns_and_voids_drop_out(self):
        item = self.ali_sale.items.get(kind="cihaz")
        services.return_sale_item(item, user=self.patron, reason="Arızalı")
        services.void_sale(self.ayse_sale, user=self.patron, reason="Hata")

        rows = self.rows()
        self.assertEqual(rows[self.ali]["device_qty"], 0)
        self.assertEqual(rows[self.ali]["revenue"], TL("300.00"))
        self.assertNotIn(self.ayse, rows)

        breakdown = rpt.staff_breakdown(self.today, self.today, self.ali)
        self.assertEqual(breakdown["returns"]["lines"], 1)
        self.assertEqual(breakdown["returns"]["total"], TL("18500.00"))

    def test_approved_seller_change_moves_the_numbers(self):
        self.request(self.ali_sale, self.patron, self.ayse)
        rows = self.rows()
        self.assertNotIn(self.ali, rows)
        self.assertEqual(rows[self.ayse]["receipts"], 2)
        self.assertEqual(rows[self.ayse]["revenue"], TL("19250.00"))

    def test_single_person_summary_shares_against_the_whole_shop(self):
        summary = rpt.staff_sales_summary(self.today, self.today, self.ayse)
        self.assertEqual(summary["revenue"], TL("450.00"))
        self.assertLess(summary["share"], 100)
        empty = rpt.staff_sales_summary(self.today, self.today, self.patron)
        self.assertEqual((empty["receipts"], empty["revenue"]), (0, TL("0.00")))

    def test_breakdown_by_device_kind_and_accessory_category(self):
        breakdown = rpt.staff_breakdown(self.today, self.today, self.ali)
        self.assertEqual(breakdown["devices"][0]["label"], "Cep Telefonu · İkinci El")
        self.assertEqual(breakdown["devices"][0]["qty"], 1)
        self.assertEqual(breakdown["accessories"],
                         [{"label": "Kablo", "qty": 2, "revenue": TL("300.00"),
                           "profit": TL("140.00")}])

    def test_monthly_series_ends_with_this_month(self):
        series = rpt.revenue_series(12, cashier=self.ali)
        self.assertEqual(len(series["labels"]), 12)
        names = ["Oca", "Şub", "Mar", "Nis", "May", "Haz",
                 "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
        self.assertEqual(series["labels"][-1],
                         f"{names[self.today.month - 1]} {str(self.today.year)[2:]}")
        self.assertEqual(series["revenue"][-1], 18800.0)
        self.assertEqual(sum(series["revenue"]), 18800.0)

    def test_report_pages_show_people(self):
        self.client.force_login(self.patron)
        response = self.client.get(reverse("stock:reports"), {"donem": "bugun"})
        self.assertContains(response, "Personel Satışları")
        self.assertContains(response, reverse("stock:staff_report", kwargs={"pk": self.ali.pk}))
        # Personel seçimi: satışı olmayan ekip üyesi de seçilebilir (patron).
        self.assertContains(response, 'aria-label="Personel seç"')
        self.assertContains(response, "Personel seçin…")
        self.assertContains(
            response, reverse("stock:staff_report", kwargs={"pk": self.patron.pk}) + "?donem=bugun")

        response = self.client.get(reverse("stock:staff_report", kwargs={"pk": self.ali.pk}),
                                   {"donem": "bugun"})
        self.assertContains(response, "Ali · Satış Raporu")
        self.assertContains(
            response,
            f'value="{reverse("stock:staff_report", kwargs={"pk": self.ali.pk})}?donem=bugun" selected')
        self.assertContains(response, "Cep Telefonu · İkinci El")
        self.assertContains(response, "iPhone 13")

        response = self.client.get(reverse("staff:list"))
        self.assertContains(response, "1 fiş · 1 cihaz · 2 aksesuar")

    def test_activity_log_shows_only_sales_summary_for_selected_person(self):
        self.client.force_login(self.patron)
        response = self.client.get(reverse("staff:logs"), {"kullanici": self.ayse.pk},
                                   **HTMX)
        self.assertContains(response, "Ayşe · Satışlar")
        self.assertContains(response, "son 30 gün")
        self.assertContains(response, "450 ₺")

        response = self.client.get(reverse("staff:logs"))
        self.assertNotContains(response, "· Satışlar")
