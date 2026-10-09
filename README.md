# PDF Playfull V9 — Paket Fresh Start

Versi lengkap untuk mengisi ulang repository GitHub `awann-sys/pdf-playfull` dengan file aplikasi yang bersih, membuat ulang Render, dan mengakses aplikasi melalui `https://awanhujan.web.id/pdf/` memakai Cloudflare Worker.

**Arsitektur:** GitHub (source) → Render (FastAPI/Python + pemrosesan PDF) ← Cloudflare Worker (reverse proxy `awanhujan.web.id/pdf/*`). Cloudflare DNS atau Worker biasa **tidak** menggantikan server Python.

## Isi paket

- `server.py`, `pdf_core.py`, `advanced_pdf.py`, `workspace_ops.py`, `object_extract.py`: backend PDF Playfull V9 lengkap
- `static/index.html`, `static/advanced.html`: frontend V9 dengan URL subpath `/pdf` **dan** akses Render langsung
- `requirements.txt`, `Dockerfile`, `render.yaml`: deployment Render
- `.gitignore`, `.dockerignore`: mencegah file sementara, arsip, video, cache, PDF pengguna ikut terkirim
- `cloudflare-worker.mjs`: Worker reverse proxy, jangan dimasukkan sebagai aplikasi terpisah di Render
- `PANDUAN_DARI_NOL.md`: langkah GitHub, Render, Cloudflare, pengujian

Fitur: editor PDF, keranjang halaman multi-dokumen, draft, watermark, crop, rotasi, nomor halaman, tanda tangan mouse/touchpad, Reset/Undo/Redo, OCR, konversi, dan ekstraksi objek Mode A/B.

**Penting:** Paket baru tidak otomatis memperbaiki DNS yang sedang gagal. Pastikan zona Cloudflare Active dan record A publik berfungsi sebelum menguji `/pdf`.

Baca `PANDUAN_DARI_NOL.md` dan ikuti secara berurutan. Jangan menghapus domain Cloudflare atau nameserver hanya untuk reset Worker Routes.
