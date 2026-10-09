# Panduan mulai dari nol — PDF Playfull V9

Tujuan: **clean source GitHub**, **buat Render baru**, dan **Cloudflare subpath** `https://awanhujan.web.id/pdf/`.

**Jangan langsung hapus zona Cloudflare `awanhujan.web.id`, nameserver, atau record email MX/TXT.** Penghapusan zone bisa memutus domain/email. Yang perlu dibersihkan hanya **Worker Routes yang keliru** dan DNS placeholder `@` jika memang akan diganti. Jika domain utama punya hosting aktif, jangan gunakan placeholder.

## 0. Cadangkan terlebih dahulu

Simpan ZIP ini dan jangan hapus `C:\pdf pecah` untuk sementara. Kalau ingin branch backup di GitHub, dari repo lama yang bersih (tidak ada perubahan belum-commit):

```cmd
cd /d "C:\pdf pecah"
git status
git branch backup-sebelum-reset-v9
git push origin backup-sebelum-reset-v9
```

Jika branch backup sudah ada, gunakan nama berbeda. Ini **tidak** membersihkan riwayat Git lama, tetapi menyimpan keadaan kode sebelumnya.

## 1. Ganti isi repository main TANPA menghapus riwayat Git

Buat folder clone baru agar folder lama tetap aman:

```cmd
cd /d C:\
git clone https://github.com/awann-sys/pdf-playfull.git "C:\pdf-playfull-fresh"
cd /d "C:\pdf-playfull-fresh"
git status
```

Jika folder `C:\pdf-playfull-fresh` sudah ada, pilih nama folder lain yang kosong. **Pastikan `git status` tidak menunjukkan perubahan lokal** sebelum melanjutkan.

Hapus HANYA file **tracked** dari checkout baru, bukan folder `.git`:

```cmd
git rm -r .
```

Jika Git menolak karena perubahan lokal, berhenti dan cek `git status`; jangan pakai opsi `-f` sembarangan.

Ekstrak **semua isi** `PDF-Playfull-V9-START-FRESH.zip` langsung ke `C:\pdf-playfull-fresh`. Pastikan file `server.py` ada langsung di folder itu (bukan di folder dalam ZIP).

Lanjutkan:

```cmd
cd /d "C:\pdf-playfull-fresh"
git add -A
git status
git commit -m "Fresh start PDF Playfull V9 clean deployment"
git push origin main
```

Periksa GitHub: hanya ada backend inti, dua HTML, file deployment, Worker, dan dokumentasi. **GitHub history dan ukuran repository yang berasal dari commit lama tetap tersimpan**; langkah ini membersihkan isi branch terbaru, bukan menghapus sejarah. Jika ingin benar-benar repo baru tanpa history lama, buat repository baru sebagai keputusan terpisah.

## 2. Buat ulang hosting di Render

1. Buka Render dashboard → **New → Web Service** dan hubungkan `awann-sys/pdf-playfull`, branch `main`.
2. Gunakan runtime **Docker**; Dockerfile berada di root repository. Region bebas (mis. Singapore), pilih plan sesuai kebutuhan.
3. Nama contoh `pdf-playfull`, sehingga URL biasanya `https://pdf-playfull.onrender.com` **jika nama tersebut tersedia**.
4. Health-check path `/healthz` (sudah di `render.yaml`). Bila menyiapkan manual, masukkan `/healthz` pada pengaturan.
5. Environment variable `MAX_UPLOAD_MB=25` opsional karena sudah ada default. Jangan gunakan URL domain custom pada Render untuk subpath ini.
6. Tunggu deploy sampai **Live**. Periksa `https://<nama-service>.onrender.com/healthz` dan halaman utamanya.

Jangan menghapus layanan Render lama sebelum layanan pengganti berhasil. URL Render yang berbeda harus diperbarui di kode Worker atau variable `RENDER_ORIGIN` pada Worker Cloudflare.

## 3. Buat/atur ulang Cloudflare Worker

1. Pada Cloudflare account → **Workers & Pages**, buat Worker dari **Start with Hello World** atau gunakan Worker yang sudah ada.
2. Klik **Edit Code**, hapus Hello World dan tempel seluruh isi `cloudflare-worker.mjs` dari paket ini → Deploy.
3. Jika URL Render baru tidak `https://pdf-playfull.onrender.com`, buka Worker **Settings → Variables and Secrets** lalu buat variable text:
   - `RENDER_ORIGIN` = `https://nama-render-baru.onrender.com` (tanpa garis miring di akhir)
   - Deploy perubahan variable sesuai petunjuk Cloudflare.
4. Uji Worker langsung, misalnya `https://nama-worker.akun.workers.dev/pdf/`. Halaman PDF Playfull harus muncul **sebelum** menghubungkan domain.

## 4. Atur DNS domain awanhujan.web.id

**Jangan hapus zona domain atau nameserver.** Pastikan Overview domain status **Active** dan NS publik sesuai dengan yang ditampilkan Cloudflare.

Jika belum ada website utama (apex) dan hanya ingin `/pdf` aktif, Cloudflare Workers Routes dapat menggunakan placeholder:

| Field | Nilai |
|---|---|
| Type | `A` |
| Name | `@` |
| IPv4 | `192.0.2.0` |
| Proxy | **Proxied** (awan oranye) |
| TTL | Auto |

Jika website utama sudah punya hosting, **jangan** gunakan placeholder; gunakan DNS asli website utama dalam mode **Proxied**. Jangan hapus MX/TXT email.

**PENTING berdasarkan masalah sebelumnya:** walaupun record A terlihat di dashboard, `nslookup -type=A awanhujan.web.id 1.1.1.1` sempat tidak memberi IPv4. Pastikan record A **benar-benar dijawab DNS publik** (dan IPv4 browser bekerja), bukan hanya tampil di dashboard. Periksa pengaturan Cloudflare seperti IPv6-only bila perlu, dan hubungi dukungan penyedia domain/Cloudflare jika delegasi atau DNS A tetap tidak terpublikasi. Mengulang instalasi Render atau GitHub **tidak otomatis memperbaiki resolusi DNS**.

## 5. Hubungkan Worker Route ke subpath (bukan Custom Domain)

Di Worker → Settings → Domains & Routes → Add Route, pilih zone `awanhujan.web.id` dan pasang **dua route**:

```text
awanhujan.web.id/pdf
awanhujan.web.id/pdf/*
```

Kedua route menuju Worker yang sama. Route pertama menangani `/pdf` (redirect ke `/pdf/`); kedua menangani `/pdf/`, editor, upload, API, dan ekspor.

`awanhujan.web.id/` tidak otomatis memiliki homepage hanya karena `/pdf/` aktif; homepage membutuhkan hosting/routing terpisah.

## 6. Tes bertahap dari Windows CMD

```cmd
nslookup -type=NS awanhujan.web.id 1.1.1.1
nslookup -type=A awanhujan.web.id 1.1.1.1
curl.exe -I -L --max-time 60 https://awanhujan.web.id/pdf/
```

Urutan memastikan asal masalah:
1. URL Render baru `/healthz` bisa dibuka → backend hidup.
2. URL Worker `.workers.dev/pdf/` bisa dibuka → proxy Worker benar.
3. `https://awanhujan.web.id/pdf/` bisa dibuka → DNS/route domain benar.
4. `https://awanhujan.web.id/pdf/advanced.html` menampilkan editor.
5. Uji upload PDF kecil, tanda tangan → pilih halaman → ekspor; lanjut ekstrak logo Mode A/B.

Jika #1/#2 berhasil tapi #3 gagal, **fokus ke DNS/Routes**, jangan hapus ulang seluruh aplikasi.

## 7. Setelah sistem baru stabil

Baru pertimbangkan hapus Render lama, Worker lama dan route ganda yang tidak dipakai. Jangan hapus GitHub repo kalau memakai repo itu untuk deploy baru. Tidak perlu menambahkan Custom Domain ke Render karena subpath sudah ditangani Cloudflare Worker.

### Batasan operasional

- Render Free bisa tidur saat tidak aktif dan memiliki keterbatasan CPU/RAM.
- Cloudflare proxy Free membatasi ukuran upload per request; pastikan file PDF tidak terlalu besar.
- Paket memakai JavaScript PDF.js/Konva dari CDN, sehingga browser memerlukan koneksi jaringan ke CDN.
- Undo/Redo & draft editor tetap berada dalam sesi browser; bukan penyimpanan cloud permanen.
