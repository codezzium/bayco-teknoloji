"""Eski hareket kayıtlarını siler.

Normalde gerekmez: her girişte 365 günden eskiler zaten silinir
(apps/staff/signals.py). Elle ya da farklı bir süreyle temizlemek için:
    python manage.py prune_activity_log --days 180
"""

from django.core.management.base import BaseCommand

from apps.staff.audit import RETENTION_DAYS, prune


class Command(BaseCommand):
    help = "Belirtilen günden eski hareket kayıtlarını siler."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=RETENTION_DAYS)

    def handle(self, *args, days, **options):
        deleted = prune(days)
        self.stdout.write(self.style.SUCCESS(f"{deleted} kayıt silindi ({days} günden eski)."))
