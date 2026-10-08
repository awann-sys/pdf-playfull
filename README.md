# PDF Toolkit — siap deploy ke Render

Aplikasi ini menggunakan **FastAPI + HTML/JavaScript + PyMuPDF**, bukan Streamlit.
Terdapat menu Pemotong Skripsi, PDF Tools, dan PDF Playfull.
Konversi Word ke PDF memerlukan LibreOffice, sudah dipasang lewat `Dockerfile`.

## Deploy di Render (cara paling mudah)

1. Ekstrak ZIP ini di komputer. Isinya harus berada di **root repository** GitHub, terutama `Dockerfile`, `render.yaml`, `server.py`, `pdf_core.py`, `requirements.txt`, dan folder `static/`. Jangan unggah hanya ZIP-nya.
2. Masuk ke https://github.com/new dan buat repository baru, misalnya `pdf-toolkit`, boleh `Private`.
3. Buka repository baru → **Add file** → **Upload files** → unggah **semua isi folder hasil ekstrak** → **Commit changes**. Pastikan bukan terbungkus lagi dalam folder `pdf-toolkit/`.
4. Masuk ke https://dashboard.render.com/ → **New** → **Blueprint** → hubungkan GitHub → pilih repository tadi.
5. Render membaca `render.yaml`. Periksa service bernama `pdf-toolkit`, runtime Docker, plan Free, region Singapore → klik **Deploy Blueprint**.
6. Buka halaman service Render dan tunggu sampai status **Live**. Proses pertama butuh waktu lebih lama karena instalasi LibreOffice.
7. Buka alamat seperti `https://pdf-toolkit-xxxx.onrender.com/` (gunakan alamat yang benar-benar ditampilkan oleh Render).
8. Untuk mengecek backend, buka `https://<alamat-render-kamu>/healthz`; hasil normal `{"status":"ok"}`.

## Alternatif: New → Web Service

- Hubungkan repository GitHub yang sama.
- Pilih **Language: Docker**, **Branch: main**, **Root Directory: kosong** (karena file ada di root), **Instance Type: Free** untuk mencoba.
- Dockerfile Path: `./Dockerfile`. Tidak perlu menulis Build Command maupun Start Command; keduanya ditangani oleh Dockerfile.
- Jika menggunakan mode Web Service manual, tambahkan env `MAX_UPLOAD_MB=25` jika ingin menentukan batas upload per berkas.
- Klik **Deploy Web Service**.

## Pengaturan penting

- Aplikasi mendengarkan `0.0.0.0:$PORT` (default `10000`) sesuai persyaratan Render.
- `GET /healthz` digunakan untuk health check.
- Tidak memerlukan `packages.txt`: LibreOffice dipasang di dalam Dockerfile.
- Paket Free memiliki RAM 512 MB. PDF panjang, kompresi raster, dan Word → PDF berpotensi membutuhkan lebih banyak RAM; kurangi ukuran berkas atau gunakan instance lebih besar jika gagal karena kehabisan memori.
- Server tidak menyimpan berkas pengguna secara permanen. Ruang kerja PDF di browser juga akan hilang saat halaman ditutup atau dimuat ulang. Sistem berkas lokal Render tidak permanen.
- Jangan memasukkan PDF sensitif ke layanan publik tanpa kontrol akses dan kebijakan privasi.

## Uji lokal

Jika Docker tersedia:

```bash
docker build -t pdf-toolkit .
docker run --rm -p 10000:10000 -e PORT=10000 pdf-toolkit
```

Buka http://localhost:10000 dan http://localhost:10000/healthz.

Jika ingin menjalankan FastAPI tanpa Docker, install `requirements.txt` dan LibreOffice sistem, kemudian:

```bash
python -m uvicorn server:app --reload --host 127.0.0.1 --port 8000
```

Buka http://127.0.0.1:8000.

## Mengatasi masalah

- **ModuleNotFoundError**: pastikan `requirements.txt` berada pada root repository yang sama dengan `Dockerfile`.
- **No open ports detected**: cek bahwa perintah Docker menggunakan `--host 0.0.0.0 --port ${PORT:-10000}`.
- **Word → PDF gagal**: pastikan yang dipilih adalah **Docker** dan log build memasang `libreoffice-writer`.
- **Out of memory**: kurangi jumlah halaman/besar dokumen atau upgrade dari Free untuk pekerjaan berat.
- **Deployment gagal**: buka service → **Logs** pada Render dan salin pesan error paling bawah untuk diagnosis lebih lanjut.
