from django.urls import path

from . import views

app_name = "website"

urlpatterns = [
    path("", views.home, name="home"),
    path("urunler/", views.products, name="products"),
    path("urun/<slug:slug>/", views.product_detail, name="product_detail"),
    path("teklif/", views.quote, name="quote"),
    path("teklif/gonder/", views.quote_submit, name="quote_submit"),
    path("servis/", views.service, name="service"),
    path("servis/gonder/", views.service_submit, name="service_submit"),
    path("iletisim/", views.contact, name="contact"),
    path("iletisim/gonder/", views.contact_submit, name="contact_submit"),
]
