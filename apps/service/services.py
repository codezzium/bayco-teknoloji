"""Teknik servis iş kuralları — durum, ödeme ve teknik servis yazımlarının TEK yeri.

View'lar modele doğrudan status/paid_total yazmaz; buradaki fonksiyonları
çağırır. Böylece her durum değişikliği zaman çizelgesine (ServiceStatusLog)
düşer ve ödeme önbelleği kendini kaynak satırlardan yeniden toplar.
"""

from django.db import transaction
from django.utils import timezone

from apps.stock.models import Payment
from apps.stock.utils import money

from .models import (
    RepairShopPayment,
    ServiceCost,
    ServiceOutsource,
    ServicePayment,
    ServiceStatusLog,
    ServiceTicket,
)

Status = ServiceTicket.Status


class ServiceError(Exception):
    """Kullanıcıya gösterilebilir iş kuralı hatası."""


def _log(ticket, from_status, to_status, user=None, note=""):
    ServiceStatusLog.objects.create(ticket=ticket, from_status=from_status,
                                    to_status=to_status, note=note[:200],
                                    created_by=user)


def _locked(ticket) -> ServiceTicket:
    return ServiceTicket.objects.select_for_update().get(pk=ticket.pk)


# ---------------------------------------------------------------------------
# Kabul
# ---------------------------------------------------------------------------

@transaction.atomic
def create_ticket(ticket: ServiceTicket, *, user=None, deposit=None,
                  deposit_method=Payment.Method.NAKIT) -> ServiceTicket:
    """Formdan gelen (kaydedilmemiş) kaydı açar; kapora varsa tahsil eder."""
    ticket.status = Status.KABUL
    ticket.created_by = user
    ticket.save()
    _log(ticket, "", Status.KABUL, user, "Cihaz teslim alındı")
    if deposit:
        record_payment(ticket, deposit, method=deposit_method, user=user,
                       note="Kapora")
    return ticket


# ---------------------------------------------------------------------------
# Durum
# ---------------------------------------------------------------------------

@transaction.atomic
def set_status(ticket: ServiceTicket, to_status, *, user=None, note="") -> ServiceTicket:
    ticket = _locked(ticket)
    if to_status not in ServiceTicket.MANUAL_STATUSES:
        raise ServiceError("Bu durum buradan seçilemez.")
    if ticket.is_closed:
        raise ServiceError("Kapanmış kayıt. Önce yeniden açın.")
    if ticket.at_shop:
        raise ServiceError("Cihaz teknik serviste. Önce teknik servisten dönüşünü kaydedin.")
    if ticket.status == to_status:
        return ticket
    old = ticket.status
    ticket.status = to_status
    ticket.save(update_fields=["status", "updated_at"])
    _log(ticket, old, to_status, user, note)
    return ticket


@transaction.atomic
def close_ticket(ticket: ServiceTicket, *, outcome, final_price=None, payment=None,
                 method=Payment.Method.NAKIT, user=None, note="") -> ServiceTicket:
    """Cihazı müşteriye geri verir: tamir edilmiş (teslim) ya da tamirsiz (iade).

    Ekran kilidi bilgisi burada SİLİNİR: cihaz artık bizde değil, parolasını
    saklamanın hiçbir gerekçesi kalmaz (KVKK).
    """
    ticket = _locked(ticket)
    if outcome not in ServiceTicket.CLOSED_STATUSES:
        raise ServiceError("Geçersiz kapanış türü.")
    if ticket.is_closed:
        raise ServiceError("Bu kayıt zaten kapanmış.")
    if ticket.at_shop:
        raise ServiceError("Cihaz teknik serviste. Önce teknik servisten dönüşünü kaydedin.")
    if final_price is None:
        if outcome == Status.TESLIM:
            raise ServiceError("Teslim için servis ücretini girin (ücretsizse 0).")
        final_price = money(0)

    old = ticket.status
    ticket.final_price = money(final_price)
    ticket.status = outcome
    ticket.closed_at = timezone.now()
    ticket.lock_pin = ""
    ticket.lock_pattern = ""
    ticket.save(update_fields=["final_price", "status", "closed_at", "lock_pin",
                               "lock_pattern", "updated_at"])
    _log(ticket, old, outcome, user, note)
    if payment:
        record_payment(ticket, payment, method=method, user=user,
                       note="Teslimde tahsilat")
    return ticket


@transaction.atomic
def reopen_ticket(ticket: ServiceTicket, *, user=None, note="") -> ServiceTicket:
    """Yanlışlıkla kapatılan kaydı "Teslime Hazır"a geri alır."""
    ticket = _locked(ticket)
    if not ticket.is_closed:
        raise ServiceError("Kayıt zaten açık.")
    old = ticket.status
    ticket.status = Status.HAZIR
    ticket.closed_at = None
    ticket.save(update_fields=["status", "closed_at", "updated_at"])
    _log(ticket, old, Status.HAZIR, user, note or "Kayıt yeniden açıldı")
    return ticket


@transaction.atomic
def delete_ticket(ticket: ServiceTicket):
    if ticket.payments.exists():
        raise ServiceError("Bu kayda ödeme girilmiş; silinemez. Tamirsiz iade ile kapatın.")
    if ticket.outsources.exists():
        raise ServiceError("Bu kayıt teknik servis hesabında geçiyor; silinemez.")
    ticket.delete()


# ---------------------------------------------------------------------------
# Müşteri ödemeleri ve iç maliyet
# ---------------------------------------------------------------------------

@transaction.atomic
def record_payment(ticket: ServiceTicket, amount, *, method=Payment.Method.NAKIT,
                   kind=Payment.Kind.TAHSILAT, user=None, paid_at=None,
                   note="") -> ServicePayment:
    amount = money(amount)
    if amount <= 0:
        raise ServiceError("Ödeme tutarı pozitif olmalıdır.")
    payment = ServicePayment.objects.create(
        ticket=ticket, kind=kind, method=method, amount=amount,
        paid_at=paid_at or timezone.now(), note=note[:200], created_by=user,
    )
    ticket.recalculate()
    return payment


def add_cost(ticket: ServiceTicket, cost: ServiceCost, *, user=None) -> ServiceCost:
    cost.ticket = ticket
    cost.created_by = user
    cost.save()
    return cost


# ---------------------------------------------------------------------------
# Teknik servis
# ---------------------------------------------------------------------------

@transaction.atomic
def send_to_shop(ticket: ServiceTicket, job: ServiceOutsource, *,
                 user=None) -> ServiceOutsource:
    ticket = _locked(ticket)
    if ticket.is_closed:
        raise ServiceError("Kapanmış kayıt teknik servise gönderilemez.")
    if ticket.at_shop:
        raise ServiceError("Cihaz zaten teknik serviste.")
    job.ticket = ticket
    job.status = ServiceOutsource.Status.GONDERILDI
    job.created_by = user
    job.save()
    old = ticket.status
    ticket.status = Status.DIS_SERVISTE
    ticket.save(update_fields=["status", "updated_at"])
    _log(ticket, old, Status.DIS_SERVISTE, user, f"{job.shop} — {job.work}")
    return job


@transaction.atomic
def return_from_shop(job: ServiceOutsource, *, next_status=Status.TAMIRDE, cost=None,
                     update_cost=True, returned_at=None, user=None,
                     note="") -> ServiceOutsource:
    """Teknik servisten dönüş. Borç bu anda yazılır (job.status=dondu).

    `update_cost=False`: bedeli göremeyen (Maliyet tiki olmayan) kullanıcı
    dönüşü kaydeder; gönderirken girilmiş bedel olduğu gibi kalır.
    """
    job = ServiceOutsource.objects.select_for_update().get(pk=job.pk)
    if job.status != ServiceOutsource.Status.GONDERILDI:
        raise ServiceError("Bu teknik servis işi zaten kapanmış.")
    if next_status not in (Status.TAMIRDE, Status.HAZIR, Status.INCELEME):
        raise ServiceError("Geçersiz sonraki durum.")
    job.status = ServiceOutsource.Status.DONDU
    job.returned_at = returned_at or timezone.localdate()
    if update_cost:
        job.cost = money(cost) if cost is not None else None
    if note:
        job.note = note[:200]
    job.save()

    ticket = _locked(job.ticket)
    ticket.status = next_status
    ticket.save(update_fields=["status", "updated_at"])
    _log(ticket, Status.DIS_SERVISTE, next_status, user, f"{job.shop} teknik servisinden döndü")
    return job


def set_job_cost(job: ServiceOutsource, cost) -> ServiceOutsource:
    if job.status == ServiceOutsource.Status.IPTAL:
        raise ServiceError("İptal edilmiş işin bedeli değiştirilemez.")
    job.cost = money(cost) if cost is not None else None
    job.save(update_fields=["cost"])
    return job


@transaction.atomic
def cancel_outsource(job: ServiceOutsource, *, user=None) -> ServiceOutsource:
    """Gönderimden vazgeçildi (cihaz işlem görmeden geri alındı): borç yazılmaz."""
    job = ServiceOutsource.objects.select_for_update().get(pk=job.pk)
    if job.status != ServiceOutsource.Status.GONDERILDI:
        raise ServiceError("Yalnızca teknik servisteki iş iptal edilebilir.")
    if job.payments.exists():
        raise ServiceError("Bu işe ödeme yapılmış; iptal yerine dönüş kaydedin.")
    job.status = ServiceOutsource.Status.IPTAL
    job.save(update_fields=["status"])
    ticket = _locked(job.ticket)
    ticket.status = Status.TAMIRDE
    ticket.save(update_fields=["status", "updated_at"])
    _log(ticket, Status.DIS_SERVISTE, Status.TAMIRDE, user,
         f"{job.shop} gönderimi iptal edildi")
    return job


def pay_shop(payment: RepairShopPayment, *, user=None) -> RepairShopPayment:
    if payment.outsource_id and payment.outsource.shop_id != payment.shop_id:
        raise ServiceError("Seçilen iş bu teknik servise ait değil.")
    payment.created_by = user
    payment.save()
    return payment
