import csv
import re
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_date

from apps.catalog.models import Brand
from apps.stock import services
from apps.stock.models import Accessory, AccessoryCategory, Contact, Device, DeviceModel
from apps.stock.utils import trfold

MODEL_CASING = {
    "Iphone": "iPhone", "Ipad": "iPad", "Ipod": "iPod", "Imac": "iMac",
    "Gb": "GB", "Tb": "TB", "Se": "SE", "Fe": "FE", "5G": "5G",
    "Xr": "XR", "Xs": "XS", "S25": "S25", "S26": "S26",
}

DEVICE_HEADERS = ("cihaz adi, hafiza, garanti, k/f, imei, kimden alindi, "
                  "alis tarihi, satis tarihi, kime satildi, maliyet, satis fiyati")
ACCESSORY_HEADERS = "marka, ad, varyant, barkod, kategori, maliyet, fiyat, adet, kritik, not"

ALIASES = {
    "cihaz adi": "cihaz_adi", "urun": "cihaz_adi", "urun adi": "cihaz_adi",
    "ad": "ad", "marka": "marka", "varyant": "varyant",
    "hafiza": "hafiza",
    "garanti": "garanti", "garanti ay": "garanti", "garanti suresi": "garanti",
    "k/f": "kf", "kutu/fatura": "kf", "kutu fatura": "kf",
    "imei": "imei", "imei 1": "imei",
    "kimden alindi": "kimden_alindi", "tedarikci": "kimden_alindi",
    "alis tarihi": "alis_tarihi",
    "satis tarihi": "satis_tarihi",
    "kime satildi": "kime_satildi", "musteri": "kime_satildi",
    "maliyet": "maliyet", "alis fiyati": "maliyet",
    "satis fiyati": "satis_fiyati", "fiyat": "fiyat",
    "renk": "renk", "raf": "raf", "pil": "pil", "not": "not", "kar": "kar",
    "barkod": "barkod", "kategori": "kategori", "adet": "adet", "kritik": "kritik",
}


def _key(value):
    folded = trfold(value).strip()
    return ALIASES.get(folded, folded.replace(" ", "_").replace("/", "_"))


def _decimal(value, default="0"):
    text = str(value or "").replace(".", "").replace(",", ".").strip()
    if not text:
        text = default
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal(default)


def _months(value):
    digits = re.findall(r"\d+", str(value or ""))
    return min(int(digits[0]), 120) if digits else 0


def _date(value):
    text = str(value or "").strip()
    if not text:
        return None
    parsed = parse_date(text)
    if parsed:
        return parsed
    match = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if match:
        day, month, year = (int(g) for g in match.groups())
        from datetime import date
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _bool(value):
    return trfold(value).strip() in {"1", "evet", "var", "true", "x", "e"}


def _imei(value):
    text = str(value or "").strip()
    if not text:
        return "", None
    if "e+" in text.lower() or "E+" in text:
        return "", (f"IMEI Excel'de bilimsel gösterime dönüşmüş ({text}); "
                    f"boş bırakıldı")
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return "", None
    if not 14 <= len(digits) <= 17:
        return "", f"IMEI {len(digits)} haneli ({text}); boş bırakıldı"
    return digits, None


class Command(BaseCommand):
    help = (f"Excel sayfasını CSV olarak içe aktarır.\n"
            f"Cihaz sütunları: {DEVICE_HEADERS}\n"
            f"Aksesuar sütunları: {ACCESSORY_HEADERS}")

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--tip", choices=["cihaz", "aksesuar"], required=True)
        parser.add_argument("--marka", default="",
                            help="Sayfa adı marka ise (APPLE, SAMSUNG…) buradan verin.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            handle = open(options["path"], newline="", encoding="utf-8-sig")
        except OSError as exc:
            raise CommandError(f"Dosya açılamadı: {exc}")

        created = sold = skipped = 0
        notes = []
        with handle, transaction.atomic():
            for line_no, raw in enumerate(csv.DictReader(handle), start=2):
                row = {_key(k): (v or "").strip() for k, v in raw.items() if k}
                if not any(row.values()):
                    continue
                try:
                    with transaction.atomic():
                        if options["tip"] == "cihaz":
                            made_sale, note = self._device(row, options["marka"])
                            sold += 1 if made_sale else 0
                        else:
                            note = self._accessory(row, options["marka"])
                    created += 1
                    if note:
                        notes.append(f"satır {line_no}: {note}")
                except Exception as exc:
                    skipped += 1
                    self.stderr.write(self.style.WARNING(
                        f"satır {line_no}: atlandı — {exc}"))
            if options["dry_run"]:
                transaction.set_rollback(True)

        for note in notes:
            self.stdout.write(self.style.WARNING("  " + note))
        prefix = "[deneme] " if options["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}{created} kayıt eklendi ({sold} tanesi satılmış), "
            f"{skipped} atlandı."))

    def _device(self, row, brand_hint):
        name = row.get("cihaz_adi", "").strip()
        storage = row.get("hafiza", "").strip()
        if not name and not brand_hint:
            raise ValueError("cihaz adı boş")

        brand_name = row.get("marka") or brand_hint or name.split()[0]
        brand, _ = Brand.objects.get_or_create(name=brand_name.title())

        model_name = self._model_name(name, storage, brand.name)
        model, _ = DeviceModel.objects.get_or_create(brand=brand, name=model_name)

        imei, imei_note = _imei(row.get("imei"))
        months = _months(row.get("garanti"))
        cost = _decimal(row.get("maliyet"))
        purchase_date = _date(row.get("alis_tarihi"))
        supplier = self._contact(row.get("kimden_alindi"), supplier=True)

        condition = (Device.Condition.SIFIR if months >= 24
                     else Device.Condition.IKINCI_EL)
        has_kf = _bool(row.get("kf"))

        device = services.create_device(
            device_model=model,
            condition=condition,
            imei1=imei,
            storage=f"{storage}GB" if storage.isdigit() else storage,
            color=row.get("renk", ""),
            has_box=has_kf,
            has_invoice=has_kf,
            shelf=row.get("raf", ""),
            defect_note=row.get("not", ""),
            battery_health=int(row["pil"]) if row.get("pil", "").isdigit() else None,
            supplier=supplier,
            purchase_date=purchase_date,
            purchase_price=cost,
            warranty_months=months,
        )

        sold_on = _date(row.get("satis_tarihi"))
        price = _decimal(row.get("satis_fiyati"))
        note = imei_note
        if sold_on and price > 0:
            if sold_on < device.purchase_date:
                note = ((note + " · ") if note else "") + (
                    f"satış tarihi ({sold_on}) alış tarihinden önce; "
                    f"alış tarihine çekildi")
                sold_on = device.purchase_date
            customer = self._contact(row.get("kime_satildi"), customer=True)
            services.record_historical_sale(device, customer=customer,
                                            sold_on=sold_on, price=price)
            return True, note
        return False, note

    def _model_name(self, name, storage, brand_name):
        cleaned = re.sub(r"\s+", " ", name).strip()
        for prefix in (brand_name.upper(), brand_name):
            if cleaned.upper().startswith(prefix.upper()):
                cleaned = cleaned[len(prefix):].strip()
                break
        if storage:
            cleaned = re.sub(rf"\b{re.escape(storage)}\s*(GB)?\b\s*$", "",
                             cleaned, flags=re.I).strip()
        cleaned = re.sub(r"\b\d{2,4}\s*GB\b\s*$", "", cleaned, flags=re.I).strip()
        if not cleaned:
            return "Model"
        words = [MODEL_CASING.get(w.title(), w.title()) for w in cleaned.split()]
        return " ".join(words)

    def _contact(self, name, *, supplier=False, customer=False):
        name = (name or "").strip()
        if not name:
            return None
        contact, created = Contact.objects.get_or_create(
            full_name=name,
            defaults={"is_supplier": supplier, "is_customer": customer,
                      "company": name if name.isupper() else ""},
        )
        changed = []
        if supplier and not contact.is_supplier:
            contact.is_supplier = True
            changed.append("is_supplier")
        if customer and not contact.is_customer:
            contact.is_customer = True
            changed.append("is_customer")
        if changed:
            contact.save(update_fields=changed)
        return contact

    def _accessory(self, row, brand_hint):
        brand = None
        brand_name = row.get("marka") or brand_hint
        if brand_name:
            brand, _ = Brand.objects.get_or_create(
                name=brand_name.title(), defaults={"is_public": False})
        category = None
        if row.get("kategori"):
            category, _ = AccessoryCategory.objects.get_or_create(name=row["kategori"])

        accessory = Accessory.objects.create(
            name=row.get("ad") or row.get("cihaz_adi", ""),
            variant=row.get("varyant", ""),
            barcode="".join(ch for ch in row.get("barkod", "") if ch.isdigit()),
            brand=brand,
            category=category,
            cost=_decimal(row.get("maliyet")),
            price=_decimal(row.get("fiyat") or row.get("satis_fiyati")),
            min_stock_level=int(row["kritik"]) if row.get("kritik", "").isdigit() else 2,
            note=row.get("not", ""),
        )
        quantity = int(row["adet"]) if row.get("adet", "").lstrip("-").isdigit() else 0
        if quantity > 0:
            services.receive_accessory_stock(
                accessory, quantity, unit_cost=accessory.cost or None,
                opening=True, note="Açılış içe aktarma")
        return None
