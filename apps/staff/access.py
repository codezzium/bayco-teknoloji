"""Personel sayfasındaki yetki tiklerinin kayıt defteri.

Bilinçli olarak HİÇBİR ŞEY import etmez: apps.staff.models Meta.permissions'ı
buradan türetir ve model yüklenirken apps.stock.permissions'ı (o da
apps.dashboard.forms'u, o da katalog modellerini) çekmek import döngüsüne
açık bir zincir kurardı. View'lar ve şablonlar tikleri apps.stock.permissions
üzerinden kullanır; orası bu sözlüğü yeniden dışa verir.

Sıra önemlidir: Personel formundaki tikler bu sırayla ve bölümlere göre
gruplanarak çizilir.

Yeni tik eklemek: buraya bir satır + `makemigrations staff` (Meta.permissions
değiştiği için AlterModelOptions üretir; izin satırını migrate sonrası
Django'nun post_migrate'i yaratır).
"""

from dataclasses import dataclass

SECTION_PAGES = "Sayfalar"
SECTION_HOME = "Genel Bakış"
SECTION_ACTIONS = "İşlemler"
SECTIONS = (SECTION_PAGES, SECTION_HOME, SECTION_ACTIONS)


@dataclass(frozen=True)
class Access:
    perm: str      # "app_label.codename"
    label: str     # formdaki tik ve rozet metni
    section: str
    help: str = ""

    @property
    def codename(self) -> str:
        return self.perm.split(".", 1)[1]


ACCESS = {
    "expenses": Access(
        "staff.access_expenses", "Giderler", SECTION_PAGES,
        "Gider listesi, gider ekleme/düzenleme, cihaza tamir gideri yazma."),
    "reports": Access(
        "staff.access_reports", "Raporlar", SECTION_PAGES,
        "Rapor sayfası ciro, kâr ve sermayeyi de gösterir."),
    "content": Access(
        "staff.manage_content", "İçerik ve Site Ayarları", SECTION_PAGES,
        "Duyurular, site ürünleri, yorumlar, S.S.S., site ayarları ve "
        "cihazı sitede yayınlama."),
    "leads": Access(
        "staff.access_leads", "Talepler", SECTION_PAGES,
        "Teklif, servis ve iletişim talepleri (müşteri adı ve telefonu)."),
    "contacts": Access(
        "staff.access_contacts", "Cariler", SECTION_PAGES,
        "Müşteri/tedarikçi listesi ve bakiyeleri. Kasadan yeni müşteri "
        "eklemek her zaman açıktır."),
    "revenue_today": Access(
        "staff.view_revenue_today", "Bugünkü Ciro", SECTION_HOME),
    "receivables": Access(
        "staff.view_receivables", "Tahsil Edilmemiş", SECTION_HOME,
        "Açık bakiye toplamı ve vadesi geçen fişler."),
    "money": Access(
        "stock.view_money", "Maliyet ve kâr", SECTION_ACTIONS,
        "Alış fiyatı, kâr ve bağlı sermaye."),
    "price": Access(
        "staff.change_prices", "Kasada fiyat, indirim ve takas", SECTION_ACTIONS,
        "Kapalıysa ürün kartındaki satış fiyatını da düzenleyemez "
        "(yeni ürün eklerken fiyat girebilir)."),
    "delete": Access(
        "staff.delete_records", "Silme, iptal, iade ve fire", SECTION_ACTIONS,
        "Kayıt silme, fiş iptali, ürün iadesi, para iadesi, kayıp/fire."),
}


def staff_permissions() -> list[tuple[str, str]]:
    """apps.staff.PanelAccess.Meta.permissions — stock.view_money hariç
    (o izin zaten stock uygulamasında tanımlı)."""
    return [(a.codename, a.label) for a in ACCESS.values()
            if a.perm.startswith("staff.")]
