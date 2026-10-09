"""Logika inti PDF (diekstrak dari app.py lama, tanpa Streamlit)."""
import io
import base64
import hashlib
import re
import zipfile
import subprocess
import tempfile
import shutil
from pathlib import Path
from collections import defaultdict
import fitz  # pymupdf
import numpy as np
BATAS_CARI_COVER = 8
AMBANG_WARNA = 0.002
BATAS_HEADER = 0.12
BATAS_FOOTER = 0.88
JUMLAH_HALAMAN_PERIKSA = 30


def normalisasi(teks):
    return re.sub(r"\s+", " ", teks).strip()


def ambil_baris(halaman):
    return [
        normalisasi(b)
        for b in halaman.get_text("text").splitlines()
        if b.strip()
    ]


def nama_folder_aman(nama):
    nama = normalisasi(nama).title()
    nama = re.sub(r'[<>:"/\\|?*]', "", nama)
    return nama.strip()


def halaman_intisari(pdf):
    kandidat = []
    for nomor, halaman in enumerate(pdf):
        baris = [b.upper() for b in ambil_baris(halaman)]
        if "INTISARI" not in baris[:12]:
            continue
        if "ABSTRACT" in baris[:12]:
            continue
        posisi = baris.index("INTISARI")
        if "OLEH" not in baris[posisi + 1:]:
            continue
        kandidat.append(nomor)
    return kandidat


def cari_nama(pdf, nomor_intisari):
    baris = ambil_baris(pdf[nomor_intisari])
    for i, b in enumerate(baris):
        if b.upper() == "OLEH":
            if i + 1 >= len(baris):
                continue
            nama = baris[i + 1].strip()
            if 2 <= len(nama.split()) <= 8 and not re.search(r"\d", nama):
                return nama_folder_aman(nama)
    return None


def cari_kata_kunci(pdf, nomor_intisari):
    baris = ambil_baris(pdf[nomor_intisari])
    for i, b in enumerate(baris):
        cocok = re.match(
            r"(?i)^(?:kata\s*kunci|keywords?)\s*[:\-]\s*(.*)$", b
        )
        if not cocok:
            continue
        hasil = cocok.group(1).strip()
        for j in range(i + 1, min(i + 5, len(baris))):
            lanjutan = baris[j].strip()
            if re.match(
                r"(?i)^(?:ABSTRAK|ABSTRACT|INTISARI|"
                r"BAB\s+[IVX0-9]+|KATA\s*KUNCI|KEYWORDS?)\b",
                lanjutan,
            ):
                break
            if not hasil:
                hasil = lanjutan
            elif hasil.endswith(","):
                hasil += " " + lanjutan
            elif j == i + 1 and len(lanjutan.split()) <= 8:
                hasil += " " + lanjutan
            else:
                break
        return normalisasi(hasil)
    return "TIDAK TERDETEKSI"


def skor_warna_cover(halaman):
    pix = halaman.get_pixmap(
        matrix=fitz.Matrix(1, 1), colorspace=fitz.csRGB, alpha=False
    )
    gambar = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, 3
    )
    tinggi, lebar, _ = gambar.shape
    area = gambar[
        int(tinggi * 0.10): int(tinggi * 0.75),
        int(lebar * 0.10): int(lebar * 0.90),
    ].astype(np.int16)
    if area.size == 0:
        return 0.0
    r, g, b = area[:, :, 0], area[:, :, 1], area[:, :, 2]
    maksimum = np.maximum.reduce([r, g, b])
    minimum = np.minimum.reduce([r, g, b])
    piksel_warna = ((maksimum - minimum) >= 45) & (maksimum >= 85)
    return float(np.mean(piksel_warna))


def cari_cover_berwarna(pdf, nomor_intisari):
    batas = min(len(pdf), BATAS_CARI_COVER, nomor_intisari)
    kandidat = [(n, skor_warna_cover(pdf[n])) for n in range(batas)]
    if not kandidat:
        return None, 0.0
    nomor, skor = max(kandidat, key=lambda x: x[1])
    if skor < AMBANG_WARNA:
        return None, skor
    return nomor, skor


def kandidat_nomor_halaman(halaman):
    tinggi = halaman.rect.height
    lebar = halaman.rect.width
    daftar = []
    for blok in halaman.get_text("dict")["blocks"]:
        if "lines" not in blok:
            continue
        for line in blok["lines"]:
            x0, y0, x1, y1 = line["bbox"]
            lokasi = None
            if y1 <= tinggi * BATAS_HEADER:
                lokasi = "header"
            elif y0 >= tinggi * BATAS_FOOTER:
                lokasi = "footer"
            if lokasi is None:
                continue
            teks = "".join(s["text"] for s in line["spans"]).strip()
            cocok = re.fullmatch(
                r"[\(\[\-–—]?\s*(\d{1,4})\s*[\)\]\-–—]?", teks
            )
            if not cocok:
                continue
            angka = int(cocok.group(1))
            if not (1 <= angka <= 1899):
                continue
            tengah_x = (x0 + x1) / 2
            if tengah_x < lebar * 0.35:
                sisi = "kiri"
            elif tengah_x > lebar * 0.65:
                sisi = "kanan"
            else:
                sisi = "tengah"
            daftar.append({"nomor": angka, "lokasi": lokasi, "sisi": sisi})
    return daftar


def cari_jumlah_halaman(pdf):
    jumlah_fisik = len(pdf)
    awal = max(0, jumlah_fisik - JUMLAH_HALAMAN_PERIKSA)
    kelompok = defaultdict(list)
    for index in range(awal, jumlah_fisik):
        for item in kandidat_nomor_halaman(pdf[index]):
            kunci = (item["lokasi"], item["sisi"], item["nomor"] - index)
            kelompok[kunci].append({"index": index, "nomor": item["nomor"]})

    pola = sorted(
        kelompok.values(),
        key=lambda g: len(set(x["index"] for x in g)),
        reverse=True,
    )
    for grup in pola:
        unik = {x["index"]: x for x in grup}
        urutan = sorted(unik.values(), key=lambda x: x["index"])
        if len(urutan) < 3:
            continue
        pasangan = sum(
            1
            for a, b in zip(urutan[:-1], urutan[1:])
            if b["index"] == a["index"] + 1 and b["nomor"] == a["nomor"] + 1
        )
        if pasangan < 2:
            continue
        terakhir = urutan[-1]
        if terakhir["index"] == jumlah_fisik - 1:
            status = "Nomor tercetak halaman terakhir"
        else:
            status = (
                "Nomor tercetak terakhir yang ditemukan "
                f"pada halaman fisik {terakhir['index'] + 1}"
            )
        return terakhir["nomor"], status
    return None, "Nomor halaman tidak dapat diverifikasi"


def proses_pdf(data_bytes, tahun):
    with fitz.open(stream=data_bytes, filetype="pdf") as pdf:
        if len(pdf) < 2:
            return None, "kurang dari 2 halaman"

        kandidat = halaman_intisari(pdf)
        if len(kandidat) != 1:
            return None, f"{len(kandidat)} kandidat INTISARI"
        nomor_intisari = kandidat[0]

        nama = cari_nama(pdf, nomor_intisari)
        if not nama:
            return None, "nama mahasiswa tidak ditemukan di bawah OLEH"

        nomor_cover, skor = cari_cover_berwarna(pdf, nomor_intisari)
        if nomor_cover is None:
            return None, "cover berwarna tidak ditemukan"

        jumlah, status = cari_jumlah_halaman(pdf)
        keyword = cari_kata_kunci(pdf, nomor_intisari)

        # Cover JPG
        cover_bytes = pdf[nomor_cover].get_pixmap(
            dpi=200, colorspace=fitz.csRGB, alpha=False
        ).tobytes("jpeg")

        # Abstrak PDF (halaman INTISARI saja)
        hasil = fitz.open()
        try:
            hasil.insert_pdf(
                pdf, from_page=nomor_intisari, to_page=nomor_intisari
            )
            abstrak_bytes = hasil.tobytes(garbage=4, deflate=True)
        finally:
            hasil.close()

        nilai_jumlah = str(jumlah) if jumlah is not None else "TIDAK TERDETEKSI"
        isi_txt = (
            f"Jumlah Halaman : {nilai_jumlah}\n"
            f"Keterangan : {status}\n"
            f"Kata Kunci : {keyword}\n"
        )

        return {
            "nama": nama,
            "halaman_cover": nomor_cover + 1,
            "halaman_intisari": nomor_intisari + 1,
            "skor": skor,
            "jumlah": nilai_jumlah,
            "keyword": keyword,
            "files": {
                f"{nama}/Cover_{nama}_{tahun}.jpg": cover_bytes,
                f"{nama}/Abstrak_{nama}_{tahun}.pdf": abstrak_bytes,
                f"{nama}/jml hal + kata kunci.txt": isi_txt.encode("utf-8"),
            },
        }, None


def nama_file_aman(nama, default="hasil"):
    nama = Path(nama).stem if nama else default
    nama = re.sub(r'[^A-Za-z0-9._ -]+', "", nama).strip(" ._")
    return nama or default


def format_ukuran(jumlah_byte):
    jumlah_byte = float(jumlah_byte)
    for satuan in ("B", "KB", "MB", "GB"):
        if jumlah_byte < 1024 or satuan == "GB":
            return f"{jumlah_byte:.1f} {satuan}"
        jumlah_byte /= 1024


def buka_pdf(data_bytes, password=""):
    pdf = fitz.open(stream=data_bytes, filetype="pdf")
    if pdf.needs_pass:
        if not password or pdf.authenticate(password) <= 0:
            pdf.close()
            raise ValueError("PDF terkunci. Masukkan password yang benar.")
    return pdf


def pdf_ke_bytes(pdf, *, encryption=fitz.PDF_ENCRYPT_KEEP, **kwargs):
    opsi = dict(garbage=4, deflate=True, clean=True, encryption=encryption)
    opsi.update(kwargs)
    return pdf.tobytes(**opsi)


def parse_halaman(teks, total, *, default_semua=False):
    """Ubah '1,3,5-7,10-8' menjadi indeks halaman 0-based dan pertahankan urutan."""
    if total <= 0:
        return []
    teks = (teks or "").strip().lower()
    if not teks:
        if default_semua:
            return list(range(total))
        raise ValueError("Daftar halaman masih kosong.")

    if teks in {"semua", "all", "*"}:
        return list(range(total))
    if teks in {"ganjil", "odd"}:
        return list(range(0, total, 2))
    if teks in {"genap", "even"}:
        return list(range(1, total, 2))

    hasil = []
    for bagian in re.split(r"\s*,\s*", teks):
        bagian = bagian.strip()
        if not bagian:
            continue
        cocok = re.fullmatch(r"(\d+)\s*-\s*(\d+)", bagian)
        if cocok:
            awal, akhir = map(int, cocok.groups())
            langkah = 1 if akhir >= awal else -1
            angka = list(range(awal, akhir + langkah, langkah))
        elif re.fullmatch(r"\d+", bagian):
            angka = [int(bagian)]
        else:
            raise ValueError(
                f"Format '{bagian}' tidak dikenali. Contoh: 1,3,5-8 atau 8-5."
            )

        for nomor in angka:
            if not 1 <= nomor <= total:
                raise ValueError(f"Nomor {nomor} di luar rentang 1-{total}.")
            hasil.append(nomor - 1)

    if not hasil:
        raise ValueError("Tidak ada halaman yang dipilih.")
    return hasil


def buat_pdf_halaman(pdf_sumber, indeks_halaman):
    hasil = fitz.open()
    try:
        for indeks in indeks_halaman:
            hasil.insert_pdf(pdf_sumber, from_page=indeks, to_page=indeks)
        return pdf_ke_bytes(hasil, encryption=fitz.PDF_ENCRYPT_NONE)
    finally:
        hasil.close()


def gabung_pdf(daftar_file, urutan=None):
    if not daftar_file:
        raise ValueError("Belum ada PDF yang dipilih.")
    if urutan is None:
        urutan = list(range(len(daftar_file)))

    hasil = fitz.open()
    try:
        for indeks in urutan:
            f = daftar_file[indeks]
            pdf = buka_pdf(f.getvalue())
            try:
                hasil.insert_pdf(pdf)
            finally:
                pdf.close()
        return pdf_ke_bytes(hasil, encryption=fitz.PDF_ENCRYPT_NONE), len(hasil)
    finally:
        hasil.close()


def split_pdf_zip(data_bytes, mode, nilai=None, password=""):
    pdf = buka_pdf(data_bytes, password)
    try:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            if mode == "per_halaman":
                grup = [[i] for i in range(len(pdf))]
            elif mode == "setiap_n":
                n = int(nilai)
                if n < 1:
                    raise ValueError("Jumlah halaman per file minimal 1.")
                grup = [list(range(i, min(i + n, len(pdf)))) for i in range(0, len(pdf), n)]
            elif mode == "grup_custom":
                grup = []
                for bagian in (nilai or "").split(";"):
                    bagian = bagian.strip()
                    if bagian:
                        grup.append(parse_halaman(bagian, len(pdf)))
                if not grup:
                    raise ValueError("Isi grup halaman, misalnya 1-3;4-7;8,10.")
            else:
                raise ValueError("Mode split tidak dikenal.")

            for nomor, indeks in enumerate(grup, start=1):
                isi = buat_pdf_halaman(pdf, indeks)
                rentang = "-".join(str(x + 1) for x in (indeks[0], indeks[-1]))
                zf.writestr(f"bagian_{nomor:03d}_hal_{rentang}.pdf", isi)
        return buffer.getvalue(), len(grup)
    finally:
        pdf.close()


def kompres_pdf_raster(data_bytes, dpi=120, kualitas=70, password=""):
    sumber = buka_pdf(data_bytes, password)
    hasil = fitz.open()
    try:
        for halaman in sumber:
            pix = halaman.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
            jpg = pix.tobytes("jpeg", jpg_quality=int(kualitas))
            baru = hasil.new_page(width=halaman.rect.width, height=halaman.rect.height)
            baru.insert_image(baru.rect, stream=jpg)
        return pdf_ke_bytes(hasil, encryption=fitz.PDF_ENCRYPT_NONE)
    finally:
        hasil.close()
        sumber.close()


def pdf_ke_gambar_zip(data_bytes, format_gambar="jpg", dpi=150, kualitas=90, password=""):
    pdf = buka_pdf(data_bytes, password)
    try:
        buffer = io.BytesIO()
        ekstensi = "jpg" if format_gambar.lower() in {"jpg", "jpeg"} else "png"
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, halaman in enumerate(pdf, start=1):
                pix = halaman.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
                if ekstensi == "jpg":
                    data = pix.tobytes("jpeg", jpg_quality=int(kualitas))
                else:
                    data = pix.tobytes("png")
                zf.writestr(f"halaman_{i:03d}.{ekstensi}", data)
        return buffer.getvalue(), len(pdf)
    finally:
        pdf.close()


def gambar_ke_pdf(daftar_file, urutan=None):
    if not daftar_file:
        raise ValueError("Belum ada gambar yang dipilih.")
    if urutan is None:
        urutan = list(range(len(daftar_file)))
    hasil = fitz.open()
    try:
        for indeks in urutan:
            f = daftar_file[indeks]
            ekstensi = Path(f.name).suffix.lower().lstrip(".") or "png"
            if ekstensi == "jpg":
                ekstensi = "jpeg"
            gambar = fitz.open(stream=f.getvalue(), filetype=ekstensi)
            try:
                pdf_data = gambar.convert_to_pdf()
                sementara = fitz.open(stream=pdf_data, filetype="pdf")
                try:
                    hasil.insert_pdf(sementara)
                finally:
                    sementara.close()
            finally:
                gambar.close()
        return pdf_ke_bytes(hasil, encryption=fitz.PDF_ENCRYPT_NONE), len(hasil)
    finally:
        hasil.close()


def pdf_ke_teks(data_bytes, password=""):
    pdf = buka_pdf(data_bytes, password)
    try:
        bagian = []
        for i, halaman in enumerate(pdf, start=1):
            bagian.append(f"===== HALAMAN {i} =====\n{halaman.get_text('text').rstrip()}\n")
        return "\n".join(bagian).encode("utf-8")
    finally:
        pdf.close()


def pdf_ke_docx_teks(data_bytes, password=""):
    try:
        from docx import Document
    except ImportError as e:
        raise RuntimeError("Fitur PDF ke DOCX memerlukan package python-docx.") from e

    pdf = buka_pdf(data_bytes, password)
    try:
        dok = Document()
        for i, halaman in enumerate(pdf, start=1):
            teks = halaman.get_text("text")
            for baris in teks.splitlines():
                dok.add_paragraph(baris)
            if i < len(pdf):
                dok.add_page_break()
        buffer = io.BytesIO()
        dok.save(buffer)
        return buffer.getvalue()
    finally:
        pdf.close()


def word_ke_pdf(data_bytes, nama_asli="dokumen.docx"):
    """Konversi DOCX ke PDF via LibreOffice, mempertahankan layout Word."""
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise RuntimeError(
            "LibreOffice belum terpasang di server. Pasang dengan: apt install libreoffice-writer."
        )
    if not data_bytes or not data_bytes[:2] == b"PK":
        raise ValueError("Berkas tidak dikenali sebagai DOCX yang valid.")
    with tempfile.TemporaryDirectory(prefix="word_pdf_") as folder:
        root = Path(folder)
        source = root / "input.docx"
        outdir = root / "hasil"
        outdir.mkdir()
        source.write_bytes(data_bytes)
        profil = (root / "lo_profile").as_uri()
        try:
            process = subprocess.run(
                [executable, f"-env:UserInstallation={profil}", "--headless", "--convert-to",
                 "pdf:writer_pdf_Export", "--outdir", str(outdir), str(source)],
                capture_output=True, text=True, timeout=120, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Konversi Word melebihi batas waktu 120 detik.") from exc
        pdfpath = outdir / "input.pdf"
        if process.returncode != 0 or not pdfpath.exists():
            pesan = (process.stderr or process.stdout or "Kesalahan tidak diketahui").strip()
            raise RuntimeError("Konversi Word ke PDF gagal: " + pesan[:500])
        hasil = pdfpath.read_bytes()
        if not hasil.startswith(b"%PDF"):
            raise RuntimeError("File hasil konversi bukan PDF yang valid.")
        return hasil


def tambah_nomor_halaman(data_bytes, posisi="Bawah tengah", mulai=1, ukuran=10, password=""):
    pdf = buka_pdf(data_bytes, password)
    try:
        for i, halaman in enumerate(pdf):
            teks = str(int(mulai) + i)
            lebar_teks = fitz.get_text_length(teks, fontname="helv", fontsize=ukuran)
            margin = 24
            if "kiri" in posisi.lower():
                x = margin
            elif "kanan" in posisi.lower():
                x = halaman.rect.width - margin - lebar_teks
            else:
                x = (halaman.rect.width - lebar_teks) / 2

            if "atas" in posisi.lower():
                y = margin + ukuran
            else:
                y = halaman.rect.height - margin

            halaman.insert_text(
                fitz.Point(x, y),
                teks,
                fontname="helv",
                fontsize=ukuran,
                color=(0.25, 0.25, 0.25),
                overlay=True,
            )
        return pdf_ke_bytes(pdf, encryption=fitz.PDF_ENCRYPT_NONE)
    finally:
        pdf.close()


def proses_playfull(data_bytes, password, urutan, terpilih, aksi, derajat=90):
    """Hasil PDF dari urutan visual dan pilihan pengguna (nomor 1-based)."""
    sumber = buka_pdf(data_bytes, password)
    try:
        total = len(sumber)
        if len(urutan) != total or set(urutan) != set(range(1, total + 1)):
            raise ValueError("Urutan halaman tidak valid.")
        if not set(terpilih).issubset(set(urutan)):
            raise ValueError("Pilihan halaman tidak valid.")
        pilihan = set(terpilih)
        if aksi in ("Ekstrak halaman terpilih", "Hapus halaman terpilih", "Putar halaman terpilih", "Duplikat halaman terpilih") and not pilihan:
            raise ValueError("Pilih minimal satu halaman terlebih dahulu.")
        if aksi == "Ekstrak halaman terpilih":
            indeks = [n - 1 for n in urutan if n in pilihan]
        elif aksi == "Hapus halaman terpilih":
            indeks = [n - 1 for n in urutan if n not in pilihan]
        elif aksi == "Duplikat halaman terpilih":
            indeks = []
            for n in urutan:
                indeks.append(n - 1)
                if n in pilihan:
                    indeks.append(n - 1)
        else:
            indeks = [n - 1 for n in urutan]
        if not indeks:
            raise ValueError("PDF hasil tidak boleh kosong. Sisakan minimal satu halaman.")
        hasil = fitz.open()
        try:
            for i in indeks:
                hasil.insert_pdf(sumber, from_page=i, to_page=i)
                if aksi == "Putar halaman terpilih" and i + 1 in pilihan:
                    halaman = hasil[-1]
                    halaman.set_rotation((halaman.rotation + int(derajat)) % 360)
            return pdf_ke_bytes(hasil, encryption=fitz.PDF_ENCRYPT_NONE), len(hasil)
        finally:
            hasil.close()
    finally:
        sumber.close()
