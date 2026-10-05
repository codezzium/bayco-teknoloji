"""Teknik servis: iş kuralları, kâr hesabı, belgeler ve ekran yetkileri."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Brand
from apps.sitecore.models import SiteSettings
from apps.staff.models import ActivityLog
from apps.staff.testing import grant
from apps.stock import reports as stock_reports
from apps.stock.models import Contact, DeviceModel
from apps.stock.permissions import GROUP_PERSONEL

from . import pdf, reports, services, slip
from .forms import TicketForm
from .models import (
    RepairShop,
    RepairShopPayment,
    ServiceCost,
    ServiceOutsource,
    ServiceTicket,
    validate_pattern,
)

TL = Decimal
Status = ServiceTicket.Status


class ServiceBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_roles", verbosity=0)
        cls.patron = User.objects.create_user("patron", password="pw", is_staff=True,
                                              is_superuser=True)
        cls.personel = User.objects.create_user("personel", password="pw")
        cls.personel.groups.add(Group.objects.get(name=GROUP_PERSONEL))
        brand = Brand.objects.create(name="Samsung")
        cls.model = DeviceModel.objects.create(brand=brand, name="Galaxy S21")
        cls.customer = Contact.objects.create(full_name="Ayşe Kaya", phone="0532 111 22 33")
        cls.shop = RepairShop.objects.create(name="Usta Elektronik", phone="0222 000 00 00")

    def make_ticket(self, **extra):
        values = {"customer": self.customer, "device_model": self.model,
                  "complaint": "Ekran kırık, dokunmatik çalışmıyor",
                  "lock_pin": "4821", "lock_pattern": "1-5-9-6",
                  "estimated_price": TL("1500")}
        values.update(extra)
        deposit = values.pop("deposit", None)
        return services.create_ticket(ServiceTicket(**values), user=self.patron,
                                      deposit=deposit)

    def send(self, ticket, cost=None):
        job = ServiceOutsource(shop=self.shop, work="Ekran değişimi", cost=cost)
        return services.send_to_shop(ticket, job, user=self.patron)


# ===========================================================================
# İş kuralları
# ===========================================================================

class TicketRulesTests(ServiceBase):
    def test_ticket_number_status_log_and_deposit(self):
        ticket = self.make_ticket(deposit=TL("500"))
        self.assertTrue(ticket.ticket_no.startswith("SRV-"))
        self.assertEqual(ticket.status, Status.KABUL)
        self.assertEqual(ticket.paid_total, TL("500.00"))
        self.assertEqual(ticket.status_logs.count(), 1)
        self.assertNotEqual(self.make_ticket().ticket_no, ticket.ticket_no)

    def test_manual_status_cannot_jump_to_shop_or_close(self):
        ticket = self.make_ticket()
        for target in (Status.DIS_SERVISTE, Status.TESLIM, Status.IADE):
            with self.assertRaises(services.ServiceError):
                services.set_status(ticket, target, user=self.patron)
        services.set_status(ticket, Status.INCELEME, user=self.patron)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.INCELEME)

    def test_device_at_shop_is_locked_until_return(self):
        ticket = self.make_ticket()
        self.send(ticket, cost=TL("400"))
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.DIS_SERVISTE)
        with self.assertRaises(services.ServiceError):
            self.send(ticket)
        with self.assertRaises(services.ServiceError):
            services.set_status(ticket, Status.HAZIR, user=self.patron)
        with self.assertRaises(services.ServiceError):
            services.close_ticket(ticket, outcome=Status.TESLIM, final_price=TL("1"))

    def test_return_writes_debt_and_payments_reduce_it(self):
        ticket = self.make_ticket()
        job = self.send(ticket, cost=TL("400"))
        # Gönderimde borç yok: cihaz dönmeden borç yazılmaz.
        self.assertEqual(reports.shop_balances([self.shop])[0]["balance"], TL("0.00"))

        services.return_from_shop(job, next_status=Status.HAZIR, cost=TL("350"),
                                  user=self.patron)
        ticket.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(ticket.status, Status.HAZIR)
        self.assertEqual(job.status, ServiceOutsource.Status.DONDU)
        self.assertEqual(job.cost, TL("350.00"))

        services.pay_shop(RepairShopPayment(shop=self.shop, amount=TL("200")),
                          user=self.patron)
        row = reports.shop_balances([self.shop])[0]
        self.assertEqual((row["debt"], row["paid"], row["balance"]),
                         (TL("350.00"), TL("200.00"), TL("150.00")))
        statement = reports.shop_statement(self.shop)
        self.assertEqual([r["balance"] for r in statement], [TL("350.00"), TL("150.00")])
        self.assertEqual(reports.shop_debt_total(), TL("150.00"))

    def test_return_without_money_access_keeps_agreed_cost(self):
        ticket = self.make_ticket()
        job = self.send(ticket, cost=TL("400"))
        services.return_from_shop(job, cost=None, update_cost=False)
        job.refresh_from_db()
        self.assertEqual(job.cost, TL("400.00"))

    def test_cancelled_job_writes_no_debt(self):
        ticket = self.make_ticket()
        job = self.send(ticket, cost=TL("400"))
        services.cancel_outsource(job, user=self.patron)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.TAMIRDE)
        self.assertEqual(reports.shop_debt_total(), TL("0.00"))

    def test_close_requires_price_and_wipes_lock(self):
        ticket = self.make_ticket(deposit=TL("500"))
        with self.assertRaises(services.ServiceError):
            services.close_ticket(ticket, outcome=Status.TESLIM, final_price=None)
        services.close_ticket(ticket, outcome=Status.TESLIM, final_price=TL("1500"),
                              payment=TL("1000"), user=self.patron)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.TESLIM)
        self.assertIsNotNone(ticket.closed_at)
        self.assertEqual((ticket.lock_pin, ticket.lock_pattern), ("", ""))
        self.assertEqual(ticket.paid_total, TL("1500.00"))
        self.assertEqual(ticket.balance, TL("0.00"))

        services.reopen_ticket(ticket, user=self.patron)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.HAZIR)
        self.assertIsNone(ticket.closed_at)

    def test_refund_payment_is_subtracted(self):
        ticket = self.make_ticket(deposit=TL("500"))
        services.record_payment(ticket, TL("200"), kind="iade", user=self.patron)
        ticket.refresh_from_db()
        self.assertEqual(ticket.paid_total, TL("300.00"))

    def test_ticket_with_payment_or_job_cannot_be_deleted(self):
        paid = self.make_ticket(deposit=TL("100"))
        with self.assertRaises(services.ServiceError):
            services.delete_ticket(paid)
        sent = self.make_ticket()
        self.send(sent)
        with self.assertRaises(services.ServiceError):
            services.delete_ticket(sent)
        empty = self.make_ticket()
        services.delete_ticket(empty)
        self.assertFalse(ServiceTicket.objects.filter(pk=empty.pk).exists())

    def test_pattern_validation_and_normalisation(self):
        validate_pattern("1-5-9-6")
        validate_pattern("")
        for bad in ("1-2", "1-1-2-3"):
            with self.assertRaises(ValidationError):
                validate_pattern(bad)
        form = TicketForm(data={
            "customer": self.customer.pk, "device_model": self.model.pk,
            "complaint": "Şarj olmuyor", "lock_pattern": "1596",
            "deposit_method": "nakit",
        }, user=self.patron)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["lock_pattern"], "1-5-9-6")


# ===========================================================================
# Kâr raporu
# ===========================================================================

class ProfitReportTests(ServiceBase):
    def test_profit_matches_costs_to_closing_period(self):
        today = timezone.localdate()
        ticket = self.make_ticket()
        ServiceCost.objects.create(ticket=ticket, title="Ekran", amount=TL("200"),
                                   spent_on=today - timedelta(days=40))
        job = self.send(ticket, cost=TL("300"))
        services.return_from_shop(job, next_status=Status.HAZIR, cost=TL("300"))
        # İptal edilen teknik servis işi maliyet sayılmaz.
        cancelled = self.send(ticket, cost=TL("999"))
        services.cancel_outsource(cancelled)
        services.close_ticket(ticket, outcome=Status.TESLIM, final_price=TL("1000"))

        # Açık kayıt ve dönem dışında kapanan kayıt sayılmaz.
        self.make_ticket(final_price=TL("5000"))
        old = self.make_ticket()
        services.close_ticket(old, outcome=Status.TESLIM, final_price=TL("700"))
        ServiceTicket.objects.filter(pk=old.pk).update(
            closed_at=timezone.now() - timedelta(days=90))

        result = reports.service_profit(today - timedelta(days=29), today)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["revenue"], TL("1000.00"))
        self.assertEqual(result["internal"], TL("200.00"))
        self.assertEqual(result["external"], TL("300.00"))
        self.assertEqual(result["net"], TL("500.00"))
        self.assertEqual(result["margin"], TL("50"))

    def test_service_money_stays_out_of_store_profit(self):
        today = timezone.localdate()
        ticket = self.make_ticket()
        services.close_ticket(ticket, outcome=Status.TESLIM, final_price=TL("1000"),
                              payment=TL("1000"))
        store = stock_reports.net_profit(today, today)
        self.assertEqual(store["revenue"], TL("0.00"))
        self.assertEqual(store["net"], TL("0.00"))
        self.assertEqual(reports.service_cash(today, today), TL("1000.00"))

    def test_unrepaired_return_counts_its_costs(self):
        today = timezone.localdate()
        ticket = self.make_ticket()
        ServiceCost.objects.create(ticket=ticket, title="Test parçası", amount=TL("80"))
        services.close_ticket(ticket, outcome=Status.IADE)
        result = reports.service_profit(today, today)
        self.assertEqual((result["revenue"], result["net"]), (TL("0.00"), TL("-80.00")))


# ===========================================================================
# Belgeler
# ===========================================================================

def _texts(flowables) -> str:
    """Flowable ağacındaki tüm Paragraph metinleri (tablolar dahil)."""
    out = []

    def walk(item):
        if isinstance(item, (list, tuple)):
            for child in item:
                walk(child)
        elif hasattr(item, "_cellvalues"):
            walk(item._cellvalues)
        elif hasattr(item, "_content"):  # KeepInFrame
            walk(item._content)
        elif hasattr(item, "text"):
            out.append(item.text)

    walk(flowables)
    return " ".join(out)


class DocumentTests(ServiceBase):
    def test_pdf_has_two_copies_and_pin_only_on_service_copy(self):
        ticket = self.make_ticket(deposit=TL("500"))
        data = pdf.intake_pdf(ticket)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertIn(b"/Count 2", data)

        pdf._register_fonts()
        site, st = SiteSettings.load(), pdf._styles()
        customer = _texts(pdf._copy(ticket, site, st, service_copy=False))
        service = _texts(pdf._copy(ticket, site, st, service_copy=True))
        self.assertIn("MÜŞTERİ NÜSHASI", customer)
        self.assertNotIn("4821", customer)
        self.assertIn("SERVİS NÜSHASI", service)
        self.assertIn("4821", service)
        self.assertIn("1 → 5 → 9 → 6", service)

    def test_each_copy_stays_on_one_page_even_with_long_text(self):
        ticket = self.make_ticket(complaint="Ekran titriyor ve kararıyor. " * 60,
                                  condition_note="Çizik " * 80)
        self.assertIn(b"/Count 2", pdf.intake_pdf(ticket))

    def test_pdf_after_delivery_says_lock_was_wiped(self):
        ticket = self.make_ticket()
        services.close_ticket(ticket, outcome=Status.TESLIM, final_price=TL("900"))
        ticket.refresh_from_db()
        pdf._register_fonts()
        service = _texts(pdf._copy(ticket, SiteSettings.load(), pdf._styles(),
                                   service_copy=True))
        self.assertIn("silindi", service)
        self.assertNotIn("4821", service)

    def test_slip_never_prints_lock_and_switches_title_on_delivery(self):
        ticket = self.make_ticket(deposit=TL("500"))
        texts = " ".join(line.text for line in slip.slip_lines(ticket))
        self.assertIn("SERVİS FİŞİ", texts)
        self.assertIn(ticket.ticket_no, texts)
        self.assertNotIn("4821", texts)
        self.assertEqual(slip.slip_image(ticket).width, 384)

        services.close_ticket(ticket, outcome=Status.TESLIM, final_price=TL("1500"))
        ticket.refresh_from_db()
        texts = " ".join(line.text for line in slip.slip_lines(ticket))
        self.assertIn("SERVİS TESLİM FİŞİ", texts)
        self.assertIn("KALAN", texts)


# ===========================================================================
# Ekranlar ve yetkiler
# ===========================================================================

class ScreenTests(ServiceBase):
    def setUp(self):
        self.ticket = self.make_ticket(deposit=TL("500"))
        self.job_ticket = self.make_ticket()
        self.job = self.send(self.job_ticket, cost=TL("300"))
        services.return_from_shop(self.job, next_status=Status.HAZIR, cost=TL("300"))
        self.shop_payment = services.pay_shop(
            RepairShopPayment(shop=self.shop, amount=TL("100")))

    def test_patron_sees_every_screen(self):
        self.client.force_login(self.patron)
        pk, shop = self.ticket.pk, self.shop.pk
        for url in [
            reverse("service:ticket_list"),
            reverse("service:ticket_list") + "?durum=tumu&q=ayse",
            reverse("service:ticket_create"),
            reverse("service:ticket_detail", kwargs={"pk": pk}),
            reverse("service:ticket_detail", kwargs={"pk": self.job_ticket.pk}),
            reverse("service:ticket_edit", kwargs={"pk": pk}),
            reverse("service:ticket_slip", kwargs={"pk": pk}),
            reverse("service:shop_list"),
            reverse("service:shop_create"),
            reverse("service:shop_detail", kwargs={"pk": shop}),
            reverse("service:shop_edit", kwargs={"pk": shop}),
            reverse("stock:contact_detail", kwargs={"pk": self.customer.pk}),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

        response = self.client.get(reverse("service:ticket_pdf", kwargs={"pk": pk}))
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["Cache-Control"], "no-store")
        response = self.client.get(reverse("service:ticket_slip_png", kwargs={"pk": pk}))
        self.assertEqual(response["Content-Type"], "image/png")

    def test_widget_is_on_reports_page_only(self):
        self.client.force_login(self.patron)
        self.assertContains(self.client.get(reverse("stock:reports")), "Net Servis Kârı")
        self.assertNotContains(self.client.get(reverse("dashboard:home")), "Net Servis Kârı")

    def test_create_through_form_logs_without_lock_values(self):
        self.client.force_login(self.patron)
        response = self.client.post(reverse("service:ticket_create"), {
            "customer": self.customer.pk, "device_model": self.model.pk,
            "imei": "351234567890123", "complaint": "Hoparlör cızırtılı",
            "received_items": ["sarj", "kutu"], "lock_pin": "987654",
            "lock_pattern": "3-5-7-8", "estimated_price": "1.250",
            "deposit": "250", "deposit_method": "kart",
        })
        ticket = ServiceTicket.objects.get(imei="351234567890123")
        self.assertRedirects(response, reverse("service:ticket_detail",
                                               kwargs={"pk": ticket.pk}) + "?yeni=1")
        self.assertEqual(ticket.received_items, ["sarj", "kutu"])
        self.assertEqual(ticket.estimated_price, TL("1250.00"))
        self.assertEqual(ticket.paid_total, TL("250.00"))
        log = ActivityLog.objects.filter(view_name="service:ticket_create").latest("at")
        self.assertNotIn("lock_pin", log.detail)
        self.assertNotIn("lock_pattern", log.detail)
        self.assertNotIn("987654", str(log.detail))

    def test_personel_without_tick_is_denied(self):
        self.client.force_login(self.personel)
        for url in [reverse("service:ticket_list"),
                    reverse("service:ticket_detail", kwargs={"pk": self.ticket.pk}),
                    reverse("service:ticket_pdf", kwargs={"pk": self.ticket.pk})]:
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), reverse("dashboard:home"),
                                     fetch_redirect_response=False)

    def test_service_tick_without_money_hides_costs_and_ledger(self):
        grant(self.personel, "service")
        self.client.force_login(self.personel)
        detail = self.client.get(reverse("service:ticket_detail",
                                         kwargs={"pk": self.job_ticket.pk}))
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, "Maliyet ve Kâr")
        self.assertNotContains(detail, "300,00")
        self.assertNotIn("cost", detail.context["send_form"].fields)
        self.assertNotIn("cost", detail.context["return_form"].fields)
        self.assertRedirects(self.client.get(reverse("service:shop_list")),
                             reverse("dashboard:home"), fetch_redirect_response=False)
        self.client.post(reverse("service:cost_add", kwargs={"pk": self.ticket.pk}),
                         {"kind": "parca", "title": "x", "amount": "10",
                          "spent_on": timezone.localdate().isoformat()})
        self.assertFalse(self.ticket.costs.exists())

    def test_status_close_and_shop_payment_views(self):
        self.client.force_login(self.patron)
        pk = self.ticket.pk
        self.client.post(reverse("service:ticket_status", kwargs={"pk": pk}),
                         {"status": "tamirde"})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.TAMIRDE)

        self.client.post(reverse("service:ticket_close", kwargs={"pk": pk}), {
            "outcome": "teslim", "final_price": "1.500", "payment": "1.000",
            "method": "nakit"})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.TESLIM)
        self.assertEqual(self.ticket.balance, TL("0.00"))
        self.assertEqual(self.ticket.lock_pin, "")

        self.client.post(reverse("service:shop_payment", kwargs={"pk": self.shop.pk}),
                         {"amount": "200", "method": "havale",
                          "paid_at": timezone.localdate().isoformat()})
        self.assertEqual(reports.shop_balances([self.shop])[0]["balance"], TL("0.00"))

    def test_scan_opens_service_ticket(self):
        self.client.force_login(self.patron)
        response = self.client.post(reverse("stock:scan_resolve"),
                                    {"mode": "lookup", "code": self.ticket.ticket_no.lower()},
                                    HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"],
                         reverse("service:ticket_detail", kwargs={"pk": self.ticket.pk}))

    def test_quick_customer_from_service_form_is_not_supplier(self):
        self.client.force_login(self.patron)
        response = self.client.get(reverse("stock:contact_quick") + "?alan=id_customer&rol=musteri")
        self.assertFalse(response.context["form"]["is_supplier"].value())
