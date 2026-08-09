FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /app

# Pillow wheel'leri cp312/aarch64 için hazır — sistem build bağımlılığı gerekmiyor.
# gunicorn requirements.txt'te yok, ayrıca kuruluyor.
COPY requirements.txt /app/
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn==23.0.0

COPY . /app

EXPOSE 8090

# Sync WSGI site — gunicorn, 2 worker, reload yok (prod).
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8090", "--workers", "2", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-"]
