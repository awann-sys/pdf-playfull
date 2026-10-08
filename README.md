# PDF Playfull — Editor dan PDF Tools (Tahap 1–3; tanpa AI)

Versi ini mempertahankan aplikasi FastAPI sebelumnya: **Pemotong Skripsi**, **PDF Tools**, dan **PDF Playfull**, plus halaman **Edit PDF Bebas + Tools Lanjutan** (`/advanced.html`). Backend PDF lama tetap berada di `pdf_core.py`; fungsi baru disimpan terpisah di `advanced_pdf.py`. Semua hasil dikirim sebagai unduhan; tidak di-commit atau disimpan ke GitHub otomatis.

## Fitur baru

### Tahap 1 — Editor visual
- PDF.js menampilkan halaman PDF di browser (halaman yang aktif saja).
- Konva.js menyediakan pemilihan, pemindahan, pengubahan ukuran, Undo/Redo, penambahan teks, gambar, kotak dan sorotan.
- Klik dua kali pada bingkai teks asli untuk mengubah teks. Backend menggunakan **redaksi teks lama** lalu menggambar teks baru. Font/layout rumit **tidak sama dengan Microsoft Word**, dan harus diperiksa kembali.
- Memindahkan gambar asli akan mengubah objek menjadi potongan gambar raster, sehingga editability dan sifat vektornya dapat hilang.
- Watermark teks transparan dan crop margin (crop *tampilan*, konten di luar crop masih berada di file).

### Tahap 2 — Konversi
- DOC/DOCX, PPT/PPTX, XLS/XLSX, ODT/ODS/ODP → PDF via LibreOffice.
- HTML lokal (.html/.htm) → PDF via LibreOffice. **URL web langsung belum didukung** untuk menghindari risiko SSRF.
- PDF → DOCX dengan `pdf2docx` (layout tidak selalu sempurna).
- PDF → PPTX dengan *slide berupa gambar halaman* (teks/bentuk tidak langsung editable).
- PDF → XLSX dengan mengekstrak **tabel yang terdeteksi**; bukan konversi tata letak keseluruhan.
- PDF → Markdown dengan deteksi ukuran judul sederhana.
- Ekstraksi gambar bitmap dari PDF.
- PDF → PDF/A-2 melalui LibreOffice; perlu **validasi veraPDF** untuk memastikan kepatuhan standar pengarsipan.

### Tahap 3 — Keamanan dan dokumen
- Redaksi permanen teks sensitif yang dicari, dengan menghapus konten dari PDF.
- OCR scan memakai Tesseract (English dan Bahasa Indonesia), dibatasi 40 halaman per permintaan untuk hosting ringan.
- Gambar tanda tangan visual (bukan tanda tangan digital tersertifikasi).
- Tanda tangan **kriptografis** menggunakan sertifikat milik pengguna dalam format `.p12`/`.pfx`, memakai `pyHanko`.
- Tambah field formulir secara manual, deteksi terbatas label berakhiran `:`, dan isi form memakai JSON berdasarkan nama field.
- Upaya perbaikan PDF (optimasi/rekonstruksi struktur yang masih dapat dibaca; file yang rusak parah bisa gagal).
- Perbandingan **visual dua PDF berdampingan**; belum ada markup otomatis untuk tiap perbedaan.
- Scan kamera di browser melalui HTTPS, lalu hasilnya menjadi PDF.

**Tidak ada fitur AI**: tidak ada ringkasan AI, terjemahan AI atau generator workflow.

## Jalankan lokal

```bash
python -m pip install -r requirements.txt
# instal LibreOffice Writer + Draw + Impress + Calc serta Tesseract eng/ind via package manager sistem
python -m uvicorn server:app --reload
```

Buka `http://localhost:8000/` untuk PDF Toolkit dan `http://localhost:8000/advanced.html` untuk menu baru. Kode editor bergantung pada **PDF.js 3.11.174** dan **Konva.js 9.3.20** melalui CDN, jadi browser harus dapat memuat dependensi dari internet. Tidak ada PDF pengguna yang dikirim oleh server ke layanan AI.

Untuk Render, gunakan `Dockerfile` dan `render.yaml` dari paket ini. Dependencies mencakup LibreOffice Impress/Calc, Tesseract dan modul Python baru. Karena Render Free memiliki memori kecil, **konversi Office, OCR dan dokumen sangat besar mungkin melampaui batas RAM/CPU**.

## Tes yang dilakukan

```bash
PYTHONPATH=. python -m pytest -q tests/test_preview.py tests/test_advanced.py
python -m py_compile server.py pdf_core.py advanced_pdf.py
```

Sebelum deploy publik, uji visual editor secara manual di browser karena lingkungan pembuatan tidak mengizinkan Playwright membuka localhost. Fitur `pyHanko` dan `pdf2docx` juga perlu uji integrasi di lingkungan yang berhasil menginstal kedua paket tersebut. Periksa output digital signature dengan validator sertifikat (dan time-stamp jika diperlukan); penandatanganan tidak otomatis menyatakan legalitas sertifikat.

## Update repository GitHub yang sudah ada

Ekstrak isi paket **pada folder root** proyek `C:\\pdf pecah` (bukan ke dalam subfolder). Lalu di CMD:

```cmd
cd /d "C:\pdf pecah"
git status
git add server.py advanced_pdf.py static/index.html static/advanced.html requirements.txt Dockerfile README.md
git commit -m "Tambah PDF Playfull tahap 1 sampai 3 tanpa AI"
git push origin main
```

Jika Render terhubung dengan GitHub dan Auto Deploy aktif, layanan dapat membangun ulang Docker image. **Jangan upload PDF pribadi atau file sertifikat `.p12` ke repository GitHub.**

## Catatan lisensi

PyMuPDF memiliki ketentuan AGPL/komersial; pastikan penggunaan/distribusi aplikasi mematuhi lisensi yang berlaku. PDF.js dan Konva.js mempunyai lisensi open-source masing-masing. Untuk kebutuhan pengguna publik yang memproses data sensitif, audit keamanan dan privasi harus dilakukan sebelum produksi.
