FROM python:3.12-slim

# LibreOffice diperlukan oleh fitur Word -> PDF.
# Font dasar ditambahkan agar hasil DOCX -> PDF lebih konsisten.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    fonts-liberation \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY . .

# Hindari menjalankan PDF parser sebagai root.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-10000}"]
