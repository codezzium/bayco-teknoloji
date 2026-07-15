# Bayço Teknoloji — Web Sitesi

Telefon & teknoloji ürünleri satan işletme için **Django + htmx** ile geliştirilmiş,
tam responsive, animasyon ağırlıklı tanıtım + lead (WhatsApp) sitesi ve firma yönetim paneli.

- **Satış WhatsApp üzerinden** yürür: üye girişi / sepet / ödeme yoktur.
- Ürünler vitrinlenir, müşteri **Teklif Al / WhatsApp** ile firmaya yönlendirilir.
- Firma için özel, markalı bir **yönetim paneli** (`/panel/`) vardır.

## Teknolojiler

Django 5.1 · htmx · Alpine.js · Tailwind CSS (Play CDN) · Swiper.js · Pillow · SQLite · WhiteNoise

## Kurulum

```bash
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo          # demo veriler (marka, ürün, slider, yorum, SSS, ayarlar)
python manage.py createsuperuser    # panel + admin kullanıcısı (yoksa)
python manage.py runserver
```

Demo kullanıcı (kurulumda oluşturulduysa): `admin` / `bayco2026`

## Sayfalar

| Alan | URL |
|---|---|
| Ana sayfa (hero + cube swiper) | `/` |
| Ürünler (htmx filtre) | `/urunler/` |
| Ürün detay | `/urun/<slug>/` |
| Teklif Al (2 mod, canlı WhatsApp önizleme) | `/teklif/` |
| Servis / Tamir talebi | `/servis/` |
| İletişim | `/iletisim/` |
| **Firma Paneli** | `/panel/` |
| Django Admin (yedek) | `/yonetim/` |

## Firma Paneli (`/panel/`)

Genel Bakış · Talepler (Teklif/Servis/İletişim gelen kutusu) · Duyurular/Slider ·
Ürünler · Yorumlar · S.S.S. · Markalar · **Site Ayarları** (telefon, WhatsApp no,
hero görseli, kampanya şeridi, sosyal medya…). Değişiklikler siteye anında yansır.

### Hero arka planı & görseller
- **Hero mağaza fotoğrafı:** Panel → Site Ayarları → *Hero Arka Plan*'dan yükleyin.
- **Ürün / slider görselleri:** İlgili panelden yüklenir. Görsel yoksa markalı gradient
  placeholder gösterilir (site boş görünmez).

## Uygulama yapısı

```
config/            # ayarlar, url, wsgi
apps/
  sitecore/        # SiteSettings (singleton), Slider, Testimonial, FAQ + context_processor
  catalog/         # Brand, Product, ProductImage
  leads/           # QuoteRequest, ServiceRequest, ContactMessage + wa.me yardımcıları
  website/         # public görünümler
  dashboard/       # firma paneli (auth + generic htmx CRUD)
templates/  static/  media/
```

## WhatsApp akışı
Formlar gönderildiğinde talep **veritabanına kaydedilir** (panel gelen kutusu) *ve* bir
`wa.me/<numara>?text=...` bağlantısı üretilir; kullanıcı mesajı WhatsApp'tan firmaya iletir.

## Üretime alırken
Ortam değişkenleriyle yapılandırın:
```bash
export DJANGO_SECRET_KEY="uzun-rastgele-anahtar"
export DJANGO_DEBUG=0
export DJANGO_ALLOWED_HOSTS="alanadiniz.com,www.alanadiniz.com"
export DJANGO_CSRF_TRUSTED_ORIGINS="https://alanadiniz.com"
python manage.py collectstatic
```
Not: Tailwind şu an Play CDN ile yüklenir (hızlı geliştirme). Üretim için Tailwind CLI ile
`static/css` derlemesi önerilir; `base.html` içindeki CDN satırı bununla değiştirilebilir.
