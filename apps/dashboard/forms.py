from django import forms

from apps.catalog.models import Brand, Product
from apps.sitecore.models import FAQ, SiteSettings, Slider, Testimonial


def _style(fields):
    """Form alanlarına tasarım sistemi sınıflarını uygular."""
    for name, field in fields.items():
        w = field.widget
        cls = "input"
        if isinstance(w, forms.Textarea):
            cls = "textarea"
        elif isinstance(w, (forms.Select, forms.SelectMultiple)):
            cls = "select"
        elif isinstance(w, forms.CheckboxInput):
            cls = "toggle-check"
        existing = w.attrs.get("class", "")
        w.attrs["class"] = f"{existing} {cls}".strip()


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields)


class SliderForm(StyledModelForm):
    class Meta:
        model = Slider
        fields = ["title", "subtitle", "badge", "image", "link_url", "order", "is_active"]


class ProductForm(StyledModelForm):
    class Meta:
        model = Product
        fields = [
            "name", "brand", "condition", "price", "old_price", "storage", "color",
            "year", "condition_grade", "warranty", "short_desc", "description",
            "cover", "is_featured", "is_active", "order",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class TestimonialForm(StyledModelForm):
    class Meta:
        model = Testimonial
        fields = ["name", "role", "rating", "comment", "avatar", "order", "is_active"]
        widgets = {"comment": forms.Textarea(attrs={"rows": 3})}


class FAQForm(StyledModelForm):
    class Meta:
        model = FAQ
        fields = ["question", "answer", "order", "is_active"]
        widgets = {"answer": forms.Textarea(attrs={"rows": 3})}


class BrandForm(StyledModelForm):
    class Meta:
        model = Brand
        fields = ["name", "logo", "order"]


class SiteSettingsForm(StyledModelForm):
    class Meta:
        model = SiteSettings
        exclude = []
        widgets = {
            "hero_subtitle": forms.Textarea(attrs={"rows": 2}),
            "footer_about": forms.Textarea(attrs={"rows": 3}),
            "maps_embed": forms.Textarea(attrs={"rows": 2}),
        }
