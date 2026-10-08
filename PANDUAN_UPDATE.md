# PDF Playfull — Editor multi-file + ekspor halaman (tanpa AI)

Perubahan ini untuk aplikasi **FastAPI di Render**. Menu lama tetap dipertahankan.

## File yang berubah

- `static/advanced.html`: properti teks/gambar dan workspace multi-file, penamaan per hasil.
- `advanced_pdf.py`: pengaturan font, warna, align, backend edit banyak PDF dan ekspor per kelompok.
- `server.py`: endpoint `POST /advanced/batch-edit` untuk menjalankan pemrosesan yang dipilih.

Tidak ada dependensi Python baru. `requirements.txt`, `Dockerfile`, dan `render.yaml` tetap seperti revisi Tahap 1–3 sebelumnya.

## Cara pakai

1. Buka **Edit PDF Bebas + Tools Lanjutan** di aplikasi. Pilih **Edit Teks & Gambar**.
2. Unggah 1–12 file PDF sekaligus. Pilih file aktif dengan klik namanya. Centang file yang akan dimasukkan ke hasil.
3. Klik blok teks/gambar di preview. Panel **Properti objek** menyediakan teks, font (Helvetica/Times/Courier), ukuran, tebal/miring, warna, rata kiri/tengah/kanan, X/Y, lebar/tinggi. Gunakan drag untuk geser. Tombol Tambah Teks otomatis membuka panel properti, **tanpa dialog browser**.
4. Saat beralih ke PDF lain, riwayat edit dan halaman terakhir untuk setiap file tetap tersimpan **selama tab browser tetap terbuka**. Pilihan file dan rentang disimpan sementara di browser; **tidak tersimpan permanen dan akan hilang saat refresh/menutup tab**.
5. Tentukan cakupan halaman: **halaman ini saja**, **semua**, **halaman saat ini tiap file**, atau **rentang per file** (contoh: `2-4,8,9,10-99`). Angka harus berada dalam jumlah halaman PDF sumber masing-masing.
6. Tentukan keluaran:
   - **Jadikan satu PDF**: semua halaman terpilih dari dokumen tercentang digabung menjadi satu PDF dengan nama dari **Nama file PDF gabungan**.
   - **Setiap rentang**: `2-4,8,9,10-99` membuat empat PDF. Per PDF dapat diberi nama di daftar di bawah pola nama.
   - **Setiap halaman**: setiap halaman dari rentang dibuat PDF sendiri dengan nama individual.
7. Ubah pola nama output dengan `{source}`, `{start}`, `{end}`, `{page}`, `{index}` bila perlu. Tiap keluaran bisa diganti namanya langsung lewat kolom di daftar hasil. Atur nama ZIP dari kolom **Nama ZIP**.
8. Klik **Proses PDF pilihan** atau **Proses hasil edit PDF**, lalu unduh. **Satu keluaran = PDF langsung, dua atau lebih keluaran = ZIP**.

## Contoh

Dua file: `Skripsi_A.pdf` dan `Skripsi_B.pdf`, masing-masing dicentang.
- File A: `2-4,8,9,10-99`; file B: `1,3-5`.
- Mode **per rentang** menghasilkan hingga 6 PDF bernama sesuai isian, dikemas dalam ZIP bernama `PDF_Playfull_Hasil.zip` (bisa diganti).
- Mode **per halaman** mengeluarkan masing-masing halaman sebagai PDF tersendiri.
- Mode **satu PDF** menggabungkan semua halaman terpilih dalam satu PDF menurut urutan file dan rentang.

## Batasan teknis

- Editor teks PDF adalah penggantian blok teks menggunakan redaksi permanen + penulisan ulang; **bukan** mesin layout paragraf Word. Font PDF asli tidak selalu bisa dipertahankan persis. Font yang didukung editor: Helvetica, Times, Courier dan variasi tebal/miring.
- Obyek tertanam yang rumit / teks hasil scan mungkin tidak dapat disunting sebagai teks; OCR disediakan pada menu lain.
- Hasil disimpan lewat unduhan; PDF tidak otomatis diunggah ke GitHub.
- Untuk stabilitas Render Free, batasi dokumen sampai 12 file, ukuran gabungan sekitar 55 MB, 350 kelompok ekspor, dan 800 halaman total yang diekspor per proses.
- Uji fungsi backend dan simulasi browser telah dilakukan, namun jalankan pengujian di browser Render setelah redeploy, terutama dengan PDF besar.

## Update via CMD

Ekstrak isi patch di folder lokal proyek sehingga `server.py`, `advanced_pdf.py`, dan `static/advanced.html` ditimpa, lalu:

```cmd
cd /d "C:\pdf pecah"
git add server.py advanced_pdf.py static/advanced.html PANDUAN_UPDATE.md
git commit -m "Editor PDF teks lengkap, multi-file, dan ekspor halaman fleksibel"
git push origin main
```

Render akan redeploy otomatis jika **Auto Deploy** aktif. Setelah Live, gunakan `Ctrl+F5` untuk refresh browser.
