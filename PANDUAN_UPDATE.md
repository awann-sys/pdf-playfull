# PDF Playfull — Universal PDF Workspace (revisi non-AI)

## Revisi yang sudah tersedia

- Preview PDF, daftar file, keranjang halaman, dan penamaan hasil **tetap terlihat** saat berpindah alat.
- Pilihan target tindakan: **halaman aktif (default)**, **halaman dalam keranjang**, **rentang per dokumen**, atau **seluruh halaman dokumen pilihan**.
- Tindakan yang diterapkan ke draft tanpa unduhan: **watermark, crop, putar halaman, nomor halaman, tanda tangan gambar, redaksi berdasarkan frasa, formulir isian**.
- Watermark, nomor halaman, redaksi, form, dan tanda tangan tampak dalam preview melalui render server. **Crop** diberi panduan area dan **rotasi** dicatat dalam draft; tampilan canvas editor tidak diputar supaya koordinat objek asli tidak salah. Keduanya diterapkan saat ekspor.
- Tindakan otomatis tersimpan sementara selama tab masih terbuka, dipisahkan per dokumen, dan bisa dibatalkan lewat **Batalkan terakhir** atau dikembalikan dengan **Ulangi tindakan**. Undo/Redo untuk objek visual masih berada di editor objek.
- **Keranjang ekspor terpisah dari target tindakan.** Halaman di luar keranjang tidak dimasukkan unduhan meskipun memiliki perubahan draft.
- Ekspor tetap mendukung satu PDF, per dokumen, per rentang, per halaman, nama tiap PDF dan ZIP.
- Alat tingkat dokumen seperti OCR, PDF/A, perbaikan PDF, dan konversi memproses draft aktif lebih dahulu, kemudian mengolahnya. Jika hasilnya PDF, **Simpan hasil sebagai dokumen baru di workspace** sudah aktif secara default, tanpa perlu download.
- Quality Match untuk teks tambahan pada scan tetap tersedia dan **tidak memburamkan watermark**.
- Fitur AI tidak ditambahkan.

## Keterbatasan yang harus diketahui

- Proses berat seperti OCR/PDF-A/konversi Office dijalankan oleh server ketika tombol proses ditekan. Hasilnya dapat ditambahkan sebagai dokumen kerja baru, tetapi bukan manipulasi langsung pada canvas.
- Crop dan rotasi belum memperlihatkan hasil final bersudut penuh di canvas objek. Crop menggunakan panduan area; ekspor final sudah menerapkan operasi sebenarnya.
- Draft saat ini belum bertahan setelah refresh/menutup tab. Simpanlah hasil penting dengan mengekspor.
- Redaksi permanen menghapus isi dari PDF hasil. Pratinjau bisa berbeda jika jenis font atau PDF scan kompleks.
- Batas 12 dokumen, 400 tindakan halaman per dokumen, 800 halaman dalam satu kali ekspor dan 55 MB total unggahan batch. Render Free bisa kehabisan RAM pada PDF besar.
- Sertifikat digital P12 ditandatangani melalui alat dokumen terpisah; menandatangani secara digital bukan sekadar menambahkan gambar tanda tangan.

## Cara memasang PATCH (Windows CMD)

1. Ekstrak isi ZIP Patch **ke** `C:\pdf pecah` dengan **Replace/Timpa**, bukan memasukkan seluruh ZIP ke folder `static`.
2. Empat file yang perlu ada:
   - `C:\pdf pecah\advanced_pdf.py`
   - `C:\pdf pecah\server.py`
   - `C:\pdf pecah\workspace_ops.py` (**file baru**)
   - `C:\pdf pecah\static\advanced.html`
3. Jalankan:

```cmd
cd /d "C:\pdf pecah"
git status
git add advanced_pdf.py server.py workspace_ops.py static/advanced.html
git commit -m "Integrasi workspace PDF dan tindakan multi-halaman"
git push origin main
```

4. Render → Events → tunggu status Live. Buka situs kemudian `Ctrl + Shift + R`.
5. Jika Git menampilkan `nothing to commit`, jalankan `git status` dan pastikan file `static\advanced.html` memang ditimpa, bukan ditaruh di root proyek.

## Tes penggunaan

1. Upload dua PDF berukuran kecil.
2. Klik Watermark; pilih **Rentang per dokumen**. Centang file A lalu isi `2-4,8`, centang file B lalu isi `3`.
3. Pilih **Terapkan ke Draft**. Periksa halaman yang diberi watermark dan riwayat tindakan.
4. Klik Batalkan terakhir lalu Ulangi tindakan; lihat perubahan kembali.
5. Centang beberapa halaman masuk keranjang **dengan urutan bebas lintas file**.
6. Klik Buat & Unduh Hasil Pilihan, pilih format hasil dan nama yang diinginkan.
7. Gunakan Perbaiki PDF untuk memeriksa opsi hasil otomatis masuk workspace (tanpa unduh ulang).
