FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# نسخ وتثبيت المكتبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تثبيت متصفح Chromium
RUN playwright install chromium

# نسخ كافة ملفات التطبيق
COPY . .

# المنفذ
EXPOSE 8080

# تشغيل الخادم مع دعم المنفذ الديناميكي
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}"]

