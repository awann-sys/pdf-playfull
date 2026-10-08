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
import streamlit as st

# =========================================================
# PENGATURAN
# =========================================================
BATAS_CARI_COVER = 8
AMBANG_WARNA = 0.002
BATAS_HEADER = 0.12
BATAS_FOOTER = 0.88
JUMLAH_HALAMAN_PERIKSA = 30


# =========================================================
# FUNGSI PEMBANTU
# =========================================================
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


# =========================================================
# INTISARI, NAMA, KATA KUNCI
# =========================================================
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


# =========================================================
# COVER BERWARNA
# =========================================================
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


# =========================================================
# JUMLAH HALAMAN
# =========================================================
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


# =========================================================
# PROSES SATU PDF  ->  (hasil, pesan_error)
# =========================================================
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



# =========================================================
# PDF TOOLKIT - FUNGSI UMUM
# =========================================================
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
            "LibreOffice belum terpasang di server. Pada Streamlit Community Cloud, "
            "tambahkan 'libreoffice-writer' ke packages.txt lalu redeploy."
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


def panel_word_ke_pdf(prefix, heading=True):
    if heading:
        st.subheader("📄 Word → PDF")
    st.caption("Unggah Word .docx; format halaman, tabel, gambar, dan margin dipertahankan sejauh didukung LibreOffice.")
    file = st.file_uploader("Pilih dokumen Word (.docx)", type=["docx"], key=prefix+"_upload")
    if file is None:
        return
    nama_default = Path(file.name).stem + ".pdf"
    nama = nama_output(nama_default, prefix+"_filename")
    nama = Path(nama).stem + ".pdf"
    if st.button("📄 Konversi Word ke PDF", type="primary", key=prefix+"_run"):
        try:
            hasil = word_ke_pdf(file.getvalue(), file.name)
            st.session_state[prefix+"_result"] = (hasil, nama, hashlib.sha256(file.getvalue()).hexdigest())
            st.success("Word berhasil dikonversi ke PDF.")
        except Exception as exc:
            st.error(str(exc))
    data = st.session_state.get(prefix+"_result")
    if data and data[2] == hashlib.sha256(file.getvalue()).hexdigest():
        hasil, filename, _ = data
        download_hasil(hasil, filename, "application/pdf")
        if st.button("📁 Tambahkan hasil ke ruang kerja PDF", key=prefix+"_workspace"):
            st.session_state.setdefault("pdf_workspace", {})[filename] = hasil
            st.success("PDF tersedia di ruang kerja dan dapat dibuka dari menu lain.")


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


@st.cache_data(show_spinner=False, max_entries=8)
def preview_halaman(data_bytes, maksimum=24, dpi=55, password=""):
    pdf = buka_pdf(data_bytes, password)
    try:
        gambar = []
        for i in range(min(len(pdf), maksimum)):
            pix = pdf[i].get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
            gambar.append((i + 1, pix.tobytes("jpeg", jpg_quality=70)))
        return gambar, len(pdf)
    finally:
        pdf.close()


# =========================================================
# PDF TOOLKIT - TAMPILAN
# =========================================================
def download_hasil(data, nama_file, mime, label="⬇️ Unduh hasil"):
    st.download_button(
        label,
        data=data,
        file_name=nama_file,
        mime=mime,
        use_container_width=True,
    )


def tampilkan_pemotong_skripsi():
    st.title("📄 Pemotong Skripsi")
    st.write(
        "Upload PDF skripsi. Aplikasi akan mengambil cover berwarna, "
        "halaman INTISARI (sebagai abstrak), jumlah halaman, dan kata kunci."
    )

    tahun = st.text_input("Tahun", value="2026", key="skripsi_tahun")
    berkas = st.file_uploader(
        "Pilih file PDF", type="pdf", accept_multiple_files=True, key="skripsi_pdf"
    )

    if st.button("Proses", type="primary", disabled=not berkas, key="skripsi_proses"):
        buffer = io.BytesIO()
        ok, periksa = 0, 0
        bar = st.progress(0.0)

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, f in enumerate(berkas):
                try:
                    hasil, pesan = proses_pdf(f.getvalue(), tahun)
                except Exception as e:
                    hasil, pesan = None, f"{type(e).__name__}: {e}"

                if hasil is None:
                    st.warning(f"PERIKSA {f.name}: {pesan}")
                    periksa += 1
                else:
                    for path, isi in hasil["files"].items():
                        zf.writestr(path, isi)
                    with st.expander(f"✅ {f.name} → {hasil['nama']}"):
                        st.write(
                            f"Cover: halaman {hasil['halaman_cover']} "
                            f"(skor warna {hasil['skor']:.4%})  \n"
                            f"INTISARI: halaman {hasil['halaman_intisari']}  \n"
                            f"Jumlah halaman: {hasil['jumlah']}  \n"
                            f"Kata kunci: {hasil['keyword']}"
                        )
                    ok += 1
                bar.progress((i + 1) / len(berkas))

        st.success(f"Selesai. Berhasil: {ok} | Perlu periksa: {periksa}")
        if ok:
            download_hasil(
                buffer.getvalue(),
                "Hasil_Potongan.zip",
                "application/zip",
                "⬇️ Unduh hasil (ZIP)",
            )


# Ruang kerja bersama untuk seluruh submenu PDF Tools.
def file_ruang_kerja(nama):
    isi = st.session_state.get("pdf_workspace", {})
    if nama not in isi:
        return None
    file = io.BytesIO(isi[nama])
    file.name = nama
    return file


def pilih_pdf_bersama(label="Pilih PDF", *, key="pdf_source"):
    simpanan = st.session_state.get("pdf_workspace", {})
    pilihan = st.selectbox(label + " dari ruang kerja", list(simpanan) if simpanan else ["— Pilih file —"], key=key)
    return file_ruang_kerja(pilihan) if pilihan in simpanan else None


def pilih_banyak_pdf_bersama(label="Pilih beberapa PDF", *, key="pdf_multi"):
    simpanan = st.session_state.get("pdf_workspace", {})
    dipilih = st.multiselect(label + " dari ruang kerja", list(simpanan), default=list(simpanan), key=key)
    return [file_ruang_kerja(n) for n in dipilih]


def panel_ruang_kerja():
    st.markdown("#### 📁 Ruang kerja PDF bersama")
    st.caption("Unggah satu kali; file bisa digunakan di Arrange, Compress, Convert, atau submenu lainnya tanpa unggah ulang. Hasil Playfull juga dapat dikirim ke sini.")
    unggahan = st.file_uploader("Tambahkan PDF ke ruang kerja", type="pdf", accept_multiple_files=True, key="workspace_upload")
    store = st.session_state.setdefault("pdf_workspace", {})
    if unggahan:
        for f in unggahan:
            if f.name not in store or store[f.name] != f.getvalue():
                store[f.name] = f.getvalue()
    if store:
        st.caption("Tersedia: " + " · ".join(f"{nama} ({format_ukuran(len(data))})" for nama, data in store.items()))
        if st.button("Kosongkan ruang kerja", key="workspace_clear"):
            st.session_state["pdf_workspace"] = {}
            st.rerun()


def nama_output(default, key):
    value = st.text_input("Nama file hasil (boleh diubah)", value=default, key=key)
    value = Path(value.strip()).name
    if not value or value in {".", ".."}:
        return default
    return value

def tampilkan_tool_merge():
    st.subheader("🔗 Merge PDF")
    st.caption("Gabungkan beberapa PDF menjadi satu file. Urutan file bisa diubah sebelum digabung.")
    files = pilih_banyak_pdf_bersama("Pilih PDF untuk digabung", key="merge_shared")
    if files:
        for i, f in enumerate(files, start=1):
            st.write(f"**{i}.** {f.name}")
        default = ",".join(str(i) for i in range(1, len(files) + 1))
        urutan = st.text_input("Urutan file", value=default, key="merge_order")
        if st.button("Gabungkan PDF", type="primary", key="merge_run"):
            try:
                indeks = parse_halaman(urutan, len(files))
                hasil, total_halaman = gabung_pdf(files, indeks)
                st.success(f"Berhasil digabung menjadi {total_halaman} halaman ({format_ukuran(len(hasil))}).")
                download_hasil(hasil, "merged.pdf", "application/pdf")
            except Exception as e:
                st.error(str(e))


# Komponen native Streamlit v2: thumbnail dapat dipindahkan dengan drag-and-drop.
# Data gambar tetap dipasok sebagai data, bukan HTML/JavaScript tidak tepercaya.
ARRANGE_GRID = st.components.v2.component(
    "pdf_thumbnail_arranger",
    html='<div id="pdf-sort-grid" aria-label="Susun halaman PDF"></div>',
    css="""
    #pdf-sort-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(120px,1fr)); gap:12px; padding:12px 1px; }
    .pdf-sort-card { cursor:grab; user-select:none; touch-action:pan-y; border:2px solid var(--st-secondary-background-color,#555); border-radius:12px; padding:8px; background:var(--st-secondary-background-color,#25252c); text-align:center; color:var(--st-text-color,#fafafa); }
    .pdf-sort-card:active { cursor:grabbing; }
    .pdf-sort-card.dragging { opacity:.35; }
    .pdf-sort-card.over { border-color:#fb4545; box-shadow:0 0 0 2px #fb454555; }
    .pdf-sort-card img { display:block; width:100%; height:160px; object-fit:contain; border-radius:5px; pointer-events:none; background:#fff; }
    .pdf-sort-card span { display:block; padding-top:7px; font-weight:650; font-size:12px; }
    .pdf-sort-hint { grid-column:1/-1; font-size:12px; opacity:.8; margin:0; }
    """,
    js="""
    export default function({ parentElement, data, setStateValue }) {
      const host = parentElement.querySelector('#pdf-sort-grid');
      const pages = data.pages || [];
      const valid = pages.map(p => p.number);
      let order = Array.isArray(data.order) && data.order.length === valid.length &&
        new Set(data.order).size === valid.length && data.order.every(n => valid.includes(n))
        ? [...data.order] : [...valid];
      const byId = new Map(pages.map(p => [p.number, p]));
      let dragged = null;
      const render = () => {
        host.replaceChildren();
        for (const n of order) {
          const page = byId.get(n);
          const tile = document.createElement('div');
          tile.className = 'pdf-sort-card';
          tile.draggable = true;
          tile.dataset.page = String(n);
          tile.setAttribute('aria-label', 'Halaman ' + n + ', geser untuk memindah');
          const img = document.createElement('img');
          img.src = 'data:image/jpeg;base64,' + page.image;
          img.alt = 'Pratinjau halaman ' + n;
          img.draggable = false;
          const title = document.createElement('span');
          title.textContent = 'Hal. ' + n;
          tile.append(img,title);
          tile.addEventListener('dragstart', e => {
            dragged=n;
            e.dataTransfer.effectAllowed='move';
            e.dataTransfer.setData('text/plain',String(n));
            tile.classList.add('dragging');
          });
          tile.addEventListener('dragover', e => {e.preventDefault(); e.dataTransfer.dropEffect='move'; tile.classList.add('over');});
          tile.addEventListener('dragleave', () => tile.classList.remove('over'));
          tile.addEventListener('drop', e => {
            e.preventDefault();
            const from = dragged ?? Number(e.dataTransfer.getData('text/plain'));
            if (!order.includes(from) || from===n) return;
            order = order.filter(x=>x!==from);
            order.splice(order.indexOf(n),0,from);
            dragged=null;
            setStateValue('order', [...order]);
            render();
          });
          tile.addEventListener('dragend', () => {dragged=null; host.querySelectorAll('.pdf-sort-card').forEach(x=>x.classList.remove('over','dragging'));});
          host.appendChild(tile);
        }
      };
      render();
    }
    """,
)


def tampilkan_tool_arrange():
    st.subheader("🧩 Arrange / Reorder PDF")
    st.caption("Klik-tahan gambar halaman, geser ke posisi yang kamu mau, lalu lepaskan. Urutan gambar adalah urutan PDF hasilnya.")
    f = pilih_pdf_bersama(key="shared_arrange_file")
    password = st.text_input("Password PDF (jika ada)", type="password", key="arrange_pw")
    if not f:
        return
    try:
        data_pdf = f.getvalue()
        fingerprint = hashlib.sha256(data_pdf + password.encode()).hexdigest()[:16]
        # Semua halaman ditampilkan; gambar mini beresolusi rendah agar tetap ringan.
        thumbs, total = preview_halaman(data_pdf, maksimum=10000, dpi=38, password=password)
        st.write(f"Total halaman: **{total}** · Geser langsung gambar di bawah ini untuk mengurutkan.")
        item_data = [{"number": number, "image": base64.b64encode(img).decode('ascii')}
                     for number,img in thumbs]
        state_key = f"pdf_arrange_{fingerprint}"
        state = st.session_state.get(state_key, {})
        current_order = state.get('order', list(range(1,total+1))) if isinstance(state,dict) else list(range(1,total+1))
        if len(current_order)!=total or set(current_order)!=set(range(1,total+1)):
            current_order=list(range(1,total+1))
        sorted_ui = ARRANGE_GRID(
            data={"pages":item_data, "order":current_order},
            default={"order":current_order}, key=state_key,
            on_order_change=lambda: None,
        )
        urutan = sorted_ui.order if sorted_ui.order is not None else current_order
        if len(urutan)!=total or set(urutan)!=set(range(1,total+1)):
            st.error("Urutan tidak valid. Muat ulang file dan coba kembali.")
            return
        st.caption("Urutan saat ini: " + ", ".join(map(str,urutan[:35])) + (" …" if total>35 else ""))
        if st.button("Buat PDF tersusun", type="primary", key="arrange_run"):
            pdf = buka_pdf(data_pdf,password)
            try:
                hasil = buat_pdf_halaman(pdf,[n-1 for n in urutan])
            finally:
                pdf.close()
            st.success(f"PDF baru berisi {len(urutan)} halaman sesuai posisi gambar.")
            download_hasil(hasil,f"{nama_file_aman(f.name)}_arranged.pdf","application/pdf")
    except Exception as e:
        st.error(str(e))


def tampilkan_tool_split():
    st.subheader("✂️ Split / Extract PDF")
    f = pilih_pdf_bersama(key="shared_split_file")
    password = st.text_input("Password PDF (jika ada)", type="password", key="split_pw")
    if not f:
        return
    try:
        pdf = buka_pdf(f.getvalue(), password)
        total = len(pdf)
        pdf.close()
        st.write(f"Total halaman: **{total}**")
    except Exception as e:
        st.error(str(e))
        return

    mode = st.selectbox(
        "Mode",
        ["Extract halaman tertentu", "Satu file per halaman", "Bagi setiap N halaman", "Grup halaman custom"],
        key="split_mode",
    )

    if mode == "Extract halaman tertentu":
        pilihan = st.text_input("Halaman", value=f"1-{total}", key="extract_pages")
        if st.button("Extract", type="primary", key="extract_run"):
            try:
                pdf = buka_pdf(f.getvalue(), password)
                try:
                    indeks = parse_halaman(pilihan, len(pdf))
                    hasil = buat_pdf_halaman(pdf, indeks)
                finally:
                    pdf.close()
                download_hasil(hasil, f"{nama_file_aman(f.name)}_extract.pdf", "application/pdf")
            except Exception as e:
                st.error(str(e))
    elif mode == "Satu file per halaman":
        if st.button("Split semua halaman", type="primary", key="split_each_run"):
            try:
                hasil, jumlah = split_pdf_zip(f.getvalue(), "per_halaman", password=password)
                st.success(f"Dibuat {jumlah} file PDF.")
                download_hasil(hasil, f"{nama_file_aman(f.name)}_split.zip", "application/zip")
            except Exception as e:
                st.error(str(e))
    elif mode == "Bagi setiap N halaman":
        n = st.number_input("Halaman per file", min_value=1, value=5, step=1, key="split_n")
        if st.button("Bagi PDF", type="primary", key="split_n_run"):
            try:
                hasil, jumlah = split_pdf_zip(f.getvalue(), "setiap_n", int(n), password=password)
                st.success(f"Dibuat {jumlah} file PDF.")
                download_hasil(hasil, f"{nama_file_aman(f.name)}_split.zip", "application/zip")
            except Exception as e:
                st.error(str(e))
    else:
        grup = st.text_input("Grup", value="1-3;4-6;7-10", key="split_groups")
        st.caption("Pisahkan grup dengan titik koma. Contoh: 1-3;4,6,8;9-12")
        if st.button("Buat grup PDF", type="primary", key="split_group_run"):
            try:
                hasil, jumlah = split_pdf_zip(f.getvalue(), "grup_custom", grup, password=password)
                st.success(f"Dibuat {jumlah} file PDF.")
                download_hasil(hasil, f"{nama_file_aman(f.name)}_split.zip", "application/zip")
            except Exception as e:
                st.error(str(e))


def tampilkan_tool_delete():
    st.subheader("🗑️ Delete Pages")
    f = pilih_pdf_bersama(key="shared_delete_file")
    password = st.text_input("Password PDF (jika ada)", type="password", key="delete_pw")
    if f:
        try:
            pdf = buka_pdf(f.getvalue(), password)
            total = len(pdf)
            pdf.close()
            hapus = st.text_input("Halaman yang dihapus", value="1", key="delete_pages")
            if st.button("Hapus halaman", type="primary", key="delete_run"):
                pdf = buka_pdf(f.getvalue(), password)
                try:
                    indeks_hapus = set(parse_halaman(hapus, len(pdf)))
                    simpan = [i for i in range(len(pdf)) if i not in indeks_hapus]
                    if not simpan:
                        raise ValueError("Semua halaman tidak boleh dihapus.")
                    hasil = buat_pdf_halaman(pdf, simpan)
                finally:
                    pdf.close()
                st.success(f"{len(indeks_hapus)} halaman dihapus. Sisa {len(simpan)} halaman.")
                download_hasil(hasil, f"{nama_file_aman(f.name)}_deleted.pdf", "application/pdf")
        except Exception as e:
            st.error(str(e))


def tampilkan_tool_rotate():
    st.subheader("🔄 Rotate PDF")
    f = pilih_pdf_bersama(key="shared_rotate_file")
    password = st.text_input("Password PDF (jika ada)", type="password", key="rotate_pw")
    if f:
        try:
            pdf = buka_pdf(f.getvalue(), password)
            total = len(pdf)
            pdf.close()
            halaman = st.text_input("Halaman", value="semua", key="rotate_pages")
            sudut = st.selectbox("Putar", [90, 180, 270], key="rotate_angle")
            if st.button("Putar PDF", type="primary", key="rotate_run"):
                pdf = buka_pdf(f.getvalue(), password)
                try:
                    indeks = parse_halaman(halaman, len(pdf), default_semua=True)
                    for i in indeks:
                        pdf[i].set_rotation((pdf[i].rotation + int(sudut)) % 360)
                    hasil = pdf_ke_bytes(pdf, encryption=fitz.PDF_ENCRYPT_NONE)
                finally:
                    pdf.close()
                st.success(f"{len(indeks)} halaman diputar {sudut}°.")
                download_hasil(hasil, f"{nama_file_aman(f.name)}_rotated.pdf", "application/pdf")
        except Exception as e:
            st.error(str(e))


def tampilkan_tool_compress():
    st.subheader("🗜️ Compress / Optimize PDF")
    f = pilih_pdf_bersama(key="shared_compress_file")
    password = st.text_input("Password PDF (jika ada)", type="password", key="compress_pw")
    mode = st.radio(
        "Metode",
        ["Lossless / aman", "Kompresi kuat (raster)"],
        horizontal=True,
        key="compress_mode",
    )
    dpi, kualitas = 120, 70
    if mode == "Kompresi kuat (raster)":
        st.warning("Mode kuat mengubah tiap halaman menjadi gambar, jadi teks tidak lagi selectable/searchable.")
        dpi = st.slider("Resolusi (DPI)", 72, 180, 120, 12, key="compress_dpi")
        kualitas = st.slider("Kualitas JPG", 35, 95, 70, 5, key="compress_quality")
    if f and st.button("Kompres PDF", type="primary", key="compress_run"):
        try:
            asli = len(f.getvalue())
            if mode == "Lossless / aman":
                pdf = buka_pdf(f.getvalue(), password)
                try:
                    hasil = pdf_ke_bytes(pdf, encryption=fitz.PDF_ENCRYPT_NONE)
                finally:
                    pdf.close()
            else:
                hasil = kompres_pdf_raster(f.getvalue(), dpi=dpi, kualitas=kualitas, password=password)
            if asli and len(hasil) <= asli:
                persen = (1 - len(hasil) / asli) * 100
                keterangan = f"berkurang {persen:.1f}%"
            elif asli:
                persen = (len(hasil) / asli - 1) * 100
                keterangan = f"bertambah {persen:.1f}%"
            else:
                keterangan = "selesai"
            st.success(
                f"Ukuran: {format_ukuran(asli)} → {format_ukuran(len(hasil))} "
                f"({keterangan})."
            )
            download_hasil(hasil, f"{nama_file_aman(f.name)}_compressed.pdf", "application/pdf")
        except Exception as e:
            st.error(str(e))


def tampilkan_tool_pdf_image():
    st.subheader("🖼️ PDF → JPG / PNG")
    f = pilih_pdf_bersama(key="shared_pdfimg_file")
    password = st.text_input("Password PDF (jika ada)", type="password", key="pdfimg_pw")
    fmt = st.selectbox("Format", ["JPG", "PNG"], key="pdfimg_fmt")
    dpi = st.slider("Resolusi (DPI)", 72, 300, 150, 6, key="pdfimg_dpi")
    kualitas = 90
    if fmt == "JPG":
        kualitas = st.slider("Kualitas JPG", 40, 100, 90, 5, key="pdfimg_quality")
    if f and st.button("Convert ke gambar", type="primary", key="pdfimg_run"):
        try:
            hasil, jumlah = pdf_ke_gambar_zip(
                f.getvalue(), fmt.lower(), dpi, kualitas, password=password
            )
            st.success(f"{jumlah} halaman berhasil dikonversi.")
            download_hasil(hasil, f"{nama_file_aman(f.name)}_{fmt.lower()}.zip", "application/zip")
        except Exception as e:
            st.error(str(e))


def tampilkan_tool_image_pdf():
    st.subheader("🌄 JPG / PNG / WEBP → PDF")
    files = st.file_uploader(
        "Pilih gambar", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key="imgpdf_files"
    )
    if files:
        for i, f in enumerate(files, start=1):
            st.write(f"**{i}.** {f.name}")
        default = ",".join(str(i) for i in range(1, len(files) + 1))
        urutan = st.text_input("Urutan gambar", value=default, key="imgpdf_order")
        if st.button("Buat PDF", type="primary", key="imgpdf_run"):
            try:
                indeks = parse_halaman(urutan, len(files))
                hasil, jumlah = gambar_ke_pdf(files, indeks)
                st.success(f"PDF berhasil dibuat dengan {jumlah} halaman.")
                download_hasil(hasil, "images_to_pdf.pdf", "application/pdf")
            except Exception as e:
                st.error(str(e))


def tampilkan_tool_pdf_text():
    st.subheader("📝 PDF → TXT")
    st.caption("Cocok untuk PDF yang memang memiliki text layer. PDF hasil scan tanpa OCR bisa menghasilkan teks kosong.")
    f = pilih_pdf_bersama(key="shared_pdftxt_file")
    password = st.text_input("Password PDF (jika ada)", type="password", key="pdftxt_pw")
    if f and st.button("Extract teks", type="primary", key="pdftxt_run"):
        try:
            hasil = pdf_ke_teks(f.getvalue(), password)
            download_hasil(hasil, f"{nama_file_aman(f.name)}.txt", "text/plain")
        except Exception as e:
            st.error(str(e))


def tampilkan_tool_pdf_docx():
    st.subheader("📘 PDF → DOCX (teks)")
    st.caption("Konversi ini memprioritaskan isi teks dan page break; layout tabel/kolom/gambar kompleks tidak dijamin identik.")
    f = pilih_pdf_bersama(key="shared_pdfdocx_file")
    password = st.text_input("Password PDF (jika ada)", type="password", key="pdfdocx_pw")
    if f and st.button("Convert ke DOCX", type="primary", key="pdfdocx_run"):
        try:
            hasil = pdf_ke_docx_teks(f.getvalue(), password)
            download_hasil(
                hasil,
                f"{nama_file_aman(f.name)}.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        except Exception as e:
            st.error(str(e))


def tampilkan_tool_number():
    st.subheader("🔢 Add Page Numbers")
    f = pilih_pdf_bersama(key="shared_number_file")
    password = st.text_input("Password PDF (jika ada)", type="password", key="number_pw")
    posisi = st.selectbox(
        "Posisi",
        ["Bawah tengah", "Bawah kanan", "Bawah kiri", "Atas tengah", "Atas kanan", "Atas kiri"],
        key="number_pos",
    )
    mulai = st.number_input("Nomor awal", value=1, step=1, key="number_start")
    ukuran = st.slider("Ukuran font", 7, 18, 10, key="number_size")
    if f and st.button("Tambahkan nomor", type="primary", key="number_run"):
        try:
            hasil = tambah_nomor_halaman(f.getvalue(), posisi, mulai, ukuran, password)
            download_hasil(hasil, f"{nama_file_aman(f.name)}_numbered.pdf", "application/pdf")
        except Exception as e:
            st.error(str(e))


def tampilkan_tool_security():
    st.subheader("🔐 Protect / Unlock PDF")
    mode = st.radio("Mode", ["Protect PDF", "Unlock PDF"], horizontal=True, key="security_mode")
    f = pilih_pdf_bersama(key="shared_security_file")
    if mode == "Protect PDF":
        user_pw = st.text_input("Password untuk membuka PDF", type="password", key="protect_user_pw")
        owner_pw = st.text_input(
            "Owner password (opsional; jika kosong akan sama dengan password buka)",
            type="password",
            key="protect_owner_pw",
        )
        allow_print = st.checkbox("Izinkan print", value=True, key="protect_print")
        allow_copy = st.checkbox("Izinkan copy text", value=False, key="protect_copy")
        if f and st.button("Kunci PDF", type="primary", key="protect_run"):
            try:
                if not user_pw:
                    raise ValueError("Password tidak boleh kosong.")
                pdf = buka_pdf(f.getvalue())
                try:
                    permissions = fitz.PDF_PERM_ACCESSIBILITY
                    if allow_print:
                        permissions |= fitz.PDF_PERM_PRINT | fitz.PDF_PERM_PRINT_HQ
                    if allow_copy:
                        permissions |= fitz.PDF_PERM_COPY
                    hasil = pdf_ke_bytes(
                        pdf,
                        encryption=fitz.PDF_ENCRYPT_AES_256,
                        user_pw=user_pw,
                        owner_pw=owner_pw or user_pw,
                        permissions=permissions,
                    )
                finally:
                    pdf.close()
                download_hasil(hasil, f"{nama_file_aman(f.name)}_protected.pdf", "application/pdf")
            except Exception as e:
                st.error(str(e))
    else:
        password = st.text_input("Password PDF", type="password", key="unlock_pw")
        if f and st.button("Unlock PDF", type="primary", key="unlock_run"):
            try:
                pdf = buka_pdf(f.getvalue(), password)
                try:
                    hasil = pdf_ke_bytes(pdf, encryption=fitz.PDF_ENCRYPT_NONE)
                finally:
                    pdf.close()
                download_hasil(hasil, f"{nama_file_aman(f.name)}_unlocked.pdf", "application/pdf")
            except Exception as e:
                st.error(str(e))


def tampilkan_pdf_tools():
    st.title("🧰 PDF Tools")
    st.write(
        "Toolkit PDF serbaguna bergaya iLovePDF: gabung, atur halaman, split, kompres, "
        "convert, beri nomor halaman, dan proteksi PDF langsung dari aplikasi ini."
    )

    panel_ruang_kerja()

    daftar_tool = [
        ("merge", "🔗 Merge PDF"),
        ("arrange", "🧩 Arrange PDF"),
        ("split", "✂️ Split / Extract"),
        ("delete", "🗑️ Delete Pages"),
        ("rotate", "🔄 Rotate PDF"),
        ("compress", "🗜️ Compress PDF"),
        ("pdf_image", "🖼️ PDF → Image"),
        ("image_pdf", "🌄 Image → PDF"),
        ("pdf_text", "📝 PDF → TXT"),
        ("pdf_docx", "📘 PDF → DOCX"),
        ("word_pdf", "📄 Word → PDF"),
        ("number", "🔢 Page Numbers"),
        ("security", "🔐 Protect / Unlock"),
    ]

    if "pdf_tool" not in st.session_state:
        st.session_state.pdf_tool = "merge"

    for awal in range(0, len(daftar_tool), 4):
        cols = st.columns(4)
        for col, (kode, label) in zip(cols, daftar_tool[awal:awal + 4]):
            with col:
                aktif = st.session_state.pdf_tool == kode
                if st.button(
                    ("✓ " if aktif else "") + label,
                    key=f"pilih_tool_{kode}",
                    use_container_width=True,
                    type="primary" if aktif else "secondary",
                ):
                    st.session_state.pdf_tool = kode

    st.divider()
    tool = st.session_state.pdf_tool
    pemetaan = {
        "merge": tampilkan_tool_merge,
        "arrange": tampilkan_tool_arrange,
        "split": tampilkan_tool_split,
        "delete": tampilkan_tool_delete,
        "rotate": tampilkan_tool_rotate,
        "compress": tampilkan_tool_compress,
        "pdf_image": tampilkan_tool_pdf_image,
        "image_pdf": tampilkan_tool_image_pdf,
        "pdf_text": tampilkan_tool_pdf_text,
        "pdf_docx": tampilkan_tool_pdf_docx,
        "word_pdf": lambda: panel_word_ke_pdf("tool_word_pdf"),
        "number": tampilkan_tool_number,
        "security": tampilkan_tool_security,
    }
    pemetaan[tool]()


# =========================================================
# PDF PLAYFULL: preview, pemilihan & manipulasi visual halaman
# =========================================================
PLAYFULL_GRID = st.components.v2.component(
    "pdf_playfull_grid",
    html='<div id="playfull-root"></div>',
    css="""
    #playfull-root {font-family:inherit; color:var(--st-text-color,#fafafa)}
    .pf-bar {display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin:6px 0 14px}
    .pf-btn {border:1px solid #7777; background:transparent; color:inherit; border-radius:9px; padding:9px 14px; cursor:pointer}
    .pf-btn:hover {border-color:#ff5555}
    .pf-stats {opacity:.85; font-size:13px}
    .pf-grid {display:grid; grid-template-columns:repeat(auto-fill,minmax(138px,1fr)); grid-auto-rows: min-content; gap:13px; padding:4px; max-height:690px; overflow-y:auto; overscroll-behavior:contain; scrollbar-gutter:stable; border:1px solid #7774; border-radius:12px}
    .pf-card {border:2px solid #7776; border-radius:12px; padding:9px; background:var(--st-secondary-background-color,#25252c); cursor:grab; user-select:none; position:relative; text-align:center}
    .pf-card.selected {border-color:#ff5757; box-shadow:0 0 0 2px #ff575744}
    .pf-card.over {border-color:#e83c3c; background:#ff555522}
    .pf-card.dragging {opacity:.3}
    .pf-card img {display:block; width:100%; height:175px; object-fit:contain; background:white; border-radius:5px; pointer-events:none}
    .pf-card .pf-bottom {display:flex; align-items:center; justify-content:space-between; font-size:12px; padding-top:8px; gap:4px}
    .pf-select {cursor:pointer; width:19px; height:19px; accent-color:#ff4848}
    .pf-zoom {border:none; cursor:pointer; background:transparent; font-size:18px; color:inherit; padding:3px}
    .pf-overlay {position:fixed; z-index:999999; inset:0; background:#000e; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:15px; padding:15px}
    .pf-overlay img {max-width:92vw; max-height:80vh; object-fit:contain; background:white}
    .pf-close {padding:10px 18px; cursor:pointer; border:1px solid #aaa; border-radius:8px; background:#292929; color:white}
    """,
    js="""
    export default function({parentElement, data, setStateValue}) {
      const host=parentElement.querySelector('#playfull-root');
      const pages=data.pages || [];
      const valid=pages.map(p=>p.number);
      const goodOrder=x=>Array.isArray(x)&&x.length===valid.length&&new Set(x).size===valid.length&&x.every(n=>valid.includes(n));
      let order=goodOrder(data.order)?[...data.order]:[...valid];
      let selected=new Set(Array.isArray(data.selected)?data.selected.filter(n=>valid.includes(n)):[]);
      const pageMap=new Map(pages.map(p=>[p.number,p]));
      let dragged=null;
      // Kirim urutan dan pilihan sekaligus pada setiap interaksi (tanpa Save).
      function syncChanges(){
        setStateValue('snapshot',{order:[...order],selected:order.filter(n=>selected.has(n))});
      }
      function updateSelectedUI(n, tile){
        tile.classList.toggle('selected',selected.has(n));
        const cb=tile.querySelector('.pf-select');if(cb)cb.checked=selected.has(n);
        const info=host.querySelector('.pf-count');if(info)info.textContent=selected.size+' dari '+order.length+' halaman dipilih';
        syncChanges();
      }
      function button(title,fn){const b=document.createElement('button');b.className='pf-btn';b.textContent=title;b.type='button';b.addEventListener('click',fn);return b;}
      function zoom(n){
        const overlay=document.createElement('div');overlay.className='pf-overlay';
        const img=document.createElement('img');img.src='data:image/jpeg;base64,'+pageMap.get(n).image;img.alt='Halaman '+n;
        const close=button('Tutup pratinjau ✕',()=>overlay.remove());close.className='pf-close';
        overlay.append(img,close);overlay.addEventListener('click',e=>{if(e.target===overlay)overlay.remove();});
        host.appendChild(overlay);
      }
      function render(){
        const previousGrid=host.querySelector('.pf-grid');
        const scroll=previousGrid ? previousGrid.scrollTop : 0;
        host.replaceChildren();
        const bar=document.createElement('div');bar.className='pf-bar';
        bar.append(button('☑ Pilih semua',()=>{selected=new Set(order);render();syncChanges();}));
        bar.append(button('☐ Hapus pilihan',()=>{selected.clear();render();syncChanges();}));
        bar.append(button('↩ Reset urutan',()=>{order=[...valid];render();syncChanges();}));
        const info=document.createElement('span');info.className='pf-stats pf-count';info.textContent=selected.size+' dari '+order.length+' halaman dipilih';bar.appendChild(info);
        host.appendChild(bar);
        const grid=document.createElement('div');grid.className='pf-grid';
        for (const n of order){
          const tile=document.createElement('div');tile.className='pf-card'+(selected.has(n)?' selected':'');tile.draggable=true;
          const img=document.createElement('img');img.draggable=false;img.src='data:image/jpeg;base64,'+pageMap.get(n).image;img.alt='Preview halaman '+n;
          const bottom=document.createElement('div');bottom.className='pf-bottom';
          const check=document.createElement('input');check.type='checkbox';check.className='pf-select';check.checked=selected.has(n);
          check.setAttribute('aria-label','Pilih halaman '+n);
          check.addEventListener('click',e=>e.stopPropagation());
          check.addEventListener('change',()=>{if(check.checked)selected.add(n);else selected.delete(n);updateSelectedUI(n,tile);});
          const label=document.createElement('span');label.textContent='Hal. '+(pageMap.get(n).page||n);label.title=pageMap.get(n).file||'';
          const preview=document.createElement('button');preview.type='button';preview.className='pf-zoom';preview.textContent='🔍';preview.title='Lihat halaman lebih besar';preview.addEventListener('click',e=>{e.stopPropagation();zoom(n);});
          bottom.append(check,label,preview);tile.append(img,bottom); if(pageMap.get(n).file){const origin=document.createElement('small');origin.textContent=pageMap.get(n).file;origin.title=pageMap.get(n).file;origin.style.cssText='display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;opacity:.7;';tile.append(origin);}
          tile.addEventListener('click',e=>{if(e.target===check||e.target===preview)return;if(selected.has(n))selected.delete(n);else selected.add(n);updateSelectedUI(n,tile);});
          tile.addEventListener('dragstart',e=>{dragged=n;e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',String(n));tile.classList.add('dragging');});
          tile.addEventListener('dragover',e=>{e.preventDefault();tile.classList.add('over');});
          tile.addEventListener('dragleave',()=>tile.classList.remove('over'));
          tile.addEventListener('drop',e=>{e.preventDefault();const from=dragged??Number(e.dataTransfer.getData('text/plain'));if(!order.includes(from)||from===n)return;order=order.filter(x=>x!==from);order.splice(order.indexOf(n),0,from);dragged=null;render();syncChanges();});
          tile.addEventListener('dragend',()=>{dragged=null;host.querySelectorAll('.pf-card').forEach(x=>x.classList.remove('over','dragging'));});
          grid.append(tile);
        }
        host.append(grid);
        grid.scrollTop=scroll;
      }
      render();
    }
    """,
)


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


@st.cache_data(show_spinner=False, max_entries=4)
def pdf_dari_banyak(daftar, passwords=None):
    """Gabung beberapa PDF secara berurutan; kembalikan data dan asal halaman."""
    keluar = fitz.open()
    origins = []
    try:
        for nama, blob in daftar:
            with buka_pdf(blob, (passwords or {}).get(nama, "")) as doc:
                for i in range(len(doc)):
                    keluar.insert_pdf(doc, from_page=i, to_page=i)
                    origins.append((nama, i + 1))
        if not len(keluar):
            raise ValueError("Tidak ada halaman PDF.")
        return pdf_ke_bytes(keluar, encryption=fitz.PDF_ENCRYPT_NONE), origins
    finally:
        keluar.close()


def tampilkan_pdf_playfull():
    st.title("😊 PDF Playfull")
    st.write("Edit halaman secara visual dari satu atau beberapa PDF. Drag-and-drop, centang halaman, lalu pilih tindakan.")
    with st.expander("📄 Word → PDF (tanpa perlu upload PDF terlebih dahulu)"):
        panel_word_ke_pdf("playfull_word_pdf", heading=False)
    panel_ruang_kerja()
    daftar = st.session_state.get("pdf_workspace", {})
    if not daftar:
        st.info("Tambahkan PDF di ruang kerja untuk mulai mengedit.")
        return
    nama_files = st.multiselect("Pilih PDF yang akan diedit (urutan file sesuai daftar)",
        options=list(daftar), default=list(daftar), key="playfull_input_files")
    if not nama_files:
        return
    st.caption("Untuk menggabungkan atau memindahkan halaman antarfile, geser thumbnail langsung di panel di bawah.")
    passwords = {}
    with st.expander("🔐 Password PDF (bila ada)"):
        for nama in nama_files:
            passwords[nama] = st.text_input("Password: " + nama, type="password", key="pf_pw_"+hashlib.md5(nama.encode()).hexdigest())
    try:
        combined, origins = pdf_dari_banyak([(n, daftar[n]) for n in nama_files], passwords)
        total = len(origins)
        fingerprint = hashlib.sha256(combined).hexdigest()[:16]
        thumbs, _ = preview_halaman(combined, maksimum=10000, dpi=34)
        pages = [{"number": n, "page": origins[n-1][1], "file": origins[n-1][0],
                  "image": base64.b64encode(img).decode("ascii")} for n, img in thumbs]
        st.write(f"**{len(nama_files)} file · {total} halaman**")
        st.caption("Centang atau geser halaman sesuai kebutuhan. Pilihan dan urutan otomatis tersimpan secara real-time; tombol Reset urutan tetap tersedia. Panel thumbnail dapat digulir.")
        state_key = "playfull_grid_" + fingerprint
        # Simpan snapshot valid secara permanen untuk rerun Streamlit berikutnya.
        # Jangan menganggap data kosong sebagai instruksi memakai semua halaman.
        state = st.session_state.get("pf_saved_" + fingerprint, {})
        initial_order = state.get("order", list(range(1, total+1))) if isinstance(state, dict) else list(range(1,total+1))
        initial_selected = state.get("selected", []) if isinstance(state, dict) else []
        if len(initial_order) != total or set(initial_order) != set(range(1,total+1)):
            initial_order = list(range(1,total+1))
        # Pilihan dan urutan dikirim sebagai satu state atomik agar salah satu
        # update tidak menimpa yang lain saat Streamlit me-render ulang.
        ui = PLAYFULL_GRID(data={"pages":pages,"order":initial_order,"selected":initial_selected},
            default={"snapshot":{"order":initial_order,"selected":initial_selected}},
            key=state_key, on_snapshot_change=lambda:None)
        snapshot = ui.snapshot if isinstance(ui.snapshot, dict) else {}
        if "order" in snapshot and "selected" in snapshot:
            candidate_order = snapshot["order"]
            candidate_selected = snapshot["selected"]
            if (isinstance(candidate_order, list) and isinstance(candidate_selected, list)
                    and len(candidate_order) == total
                    and set(candidate_order) == set(range(1, total + 1))
                    and all(isinstance(n, int) and not isinstance(n, bool) for n in candidate_selected)
                    and set(candidate_selected).issubset(set(candidate_order))):
                st.session_state["pf_saved_" + fingerprint] = {
                    "order": list(candidate_order), "selected": list(candidate_selected)
                }
                state = st.session_state["pf_saved_" + fingerprint]
        urutan = list(state.get("order", initial_order))
        terpilih = [n for n in urutan if n in set(state.get("selected", initial_selected))]
        if len(urutan) != total or set(urutan) != set(range(1,total+1)):
            st.error("Urutan tidak valid; coba muat ulang.")
            return
        st.caption(f"**{len(terpilih)} dari {total} halaman dipilih.** Pilihan tersimpan otomatis. Jika tidak mencentang apa pun, tindakan umum tanpa opsi 'Gunakan halaman yang dicentang saja' berlaku untuk semua halaman.")
        daftar_aksi = [
            "Susun ulang semua halaman", "Merge PDF", "Split / Extract", "Split PDF (per halaman)", "Delete Pages",
            "Rotate PDF", "Compress PDF", "PDF → Image", "Image → PDF", "PDF → TXT", "PDF → DOCX",
            "Page Numbers", "Protect PDF", "Unlock PDF", "Duplikat halaman terpilih",
        ]
        aksi = st.selectbox("Tindakan untuk halaman/dokumen", daftar_aksi, key="playfull_action_v2")
        only_selected = st.checkbox("Gunakan halaman yang dicentang saja", value=aksi in ("Split / Extract",),
                                   key="pf_only_selected", disabled=aksi in ("Delete Pages", "Duplikat halaman terpilih"))
        degree = st.selectbox("Sudut rotasi", [90,180,270], key="pf_rotation") if aksi == "Rotate PDF" else 90
        compression = st.selectbox("Tingkat kompresi", ["Lossless", "Kuat (raster)"], key="pf_compression") if aksi == "Compress PDF" else None
        dpi = st.slider("Resolusi DPI", 72, 200, 120, key="pf_dpi") if aksi in ("Compress PDF", "PDF → Image") else 120
        fmt = st.selectbox("Format gambar", ["jpg", "png"], key="pf_image_fmt") if aksi == "PDF → Image" else "jpg"
        pos = st.selectbox("Posisi nomor", ["Bawah tengah", "Bawah kiri", "Bawah kanan", "Atas tengah"], key="pf_n_position") if aksi == "Page Numbers" else "Bawah tengah"
        startnum = st.number_input("Mulai nomor dari", 1, 999999, 1, key="pf_n_start") if aksi == "Page Numbers" else 1
        new_password = st.text_input("Password baru", type="password", key="pf_new_pw") if aksi == "Protect PDF" else ""
        uploads_images = st.file_uploader("Upload gambar untuk Image → PDF", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key="pf_images") if aksi == "Image → PDF" else []
        ext = ("." + fmt) if aksi == "PDF → Image" else ".pdf" if aksi == "Split PDF (per halaman)" else ".txt" if aksi == "PDF → TXT" else ".docx" if aksi == "PDF → DOCX" else ".pdf"
        suffix = {"Susun ulang semua halaman":"arranged", "Merge PDF":"merged", "Split / Extract":"extract",
                  "Split PDF (per halaman)":"split", "Delete Pages":"deleted", "Rotate PDF":"rotated", "Compress PDF":"compressed",
                  "PDF → Image":"images", "Image → PDF":"from_images", "PDF → TXT":"text", "PDF → DOCX":"docx",
                  "Page Numbers":"numbered", "Protect PDF":"protected", "Unlock PDF":"unlocked",
                  "Duplikat halaman terpilih":"duplicated"}[aksi]
        default_name = f"{nama_file_aman(nama_files[0])}_{suffix}{ext}"
        out_name = nama_output(default_name, "pf_filename_" + suffix + "_" + fingerprint)
        st.caption("Nama default di atas diambil dari nama file dan jenis tindakan; boleh diganti sebelum diproses.")
        if st.button("✨ Proses PDF Playfull", type="primary", key="playfull_run_v2"):
            if aksi == "Image → PDF":
                if not uploads_images: raise ValueError("Unggah gambar terlebih dahulu.")
                out, _ = gambar_ke_pdf(uploads_images)
                mime = "application/pdf"
                selected_order = []
            elif aksi == "Delete Pages":
                if not terpilih: raise ValueError("Pilih halaman yang ingin dihapus.")
                selected_order = [n for n in urutan if n not in terpilih]
            elif aksi == "Duplikat halaman terpilih":
                if not terpilih: raise ValueError("Pilih halaman yang ingin diduplikat.")
                selected_order = [n for n in urutan for _ in range(2 if n in terpilih else 1)]
            elif only_selected or aksi == "Split / Extract":
                # Mode halaman terpilih tidak boleh diam-diam kembali ke SEMUA.
                if not terpilih:
                    raise ValueError("Belum ada halaman yang dicentang. Centang halaman pada preview terlebih dahulu.")
                selected_order = [n for n in urutan if n in terpilih]
            else:
                selected_order = list(urutan)
            if aksi != "Image → PDF":
                if not selected_order: raise ValueError("Hasil PDF tidak boleh kosong.")
                with buka_pdf(combined) as src:
                    intermediate = buat_pdf_halaman(src, [n-1 for n in selected_order])
                out = intermediate
                mime = "application/pdf"
            if aksi == "Rotate PDF":
                with buka_pdf(intermediate) as doc:
                    for j, n in enumerate(selected_order):
                        if (not terpilih or n in terpilih) and (not only_selected or n in terpilih):
                            doc[j].set_rotation((doc[j].rotation + degree)%360)
                    out = pdf_ke_bytes(doc, encryption=fitz.PDF_ENCRYPT_NONE)
            elif aksi == "Split PDF (per halaman)":
                with buka_pdf(intermediate) as src:
                    if len(src) == 1:
                        out = buat_pdf_halaman(src, [0])
                        mime = "application/pdf"
                    else:
                        base = Path(out_name).stem
                        bio = io.BytesIO()
                        with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
                            for ix in range(len(src)):
                                one = buat_pdf_halaman(src, [ix])
                                zf.writestr(f"{base}_{ix+1:03d}.pdf", one)
                        out = bio.getvalue()
                        mime = "application/zip"
            elif aksi == "Compress PDF":
                if compression == "Kuat (raster)": out = kompres_pdf_raster(intermediate, dpi=dpi)
                else:
                    with buka_pdf(intermediate) as doc: out = pdf_ke_bytes(doc, encryption=fitz.PDF_ENCRYPT_NONE)
            elif aksi == "PDF → Image":
                with buka_pdf(intermediate) as src:
                    if len(src) == 1:
                        pix = src[0].get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
                        out = pix.tobytes("jpeg", jpg_quality=90) if fmt == "jpg" else pix.tobytes("png")
                        mime = "image/jpeg" if fmt == "jpg" else "image/png"
                    else:
                        base = Path(out_name).stem
                        bio = io.BytesIO()
                        with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
                            for ix, page in enumerate(src, 1):
                                pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
                                img = pix.tobytes("jpeg", jpg_quality=90) if fmt == "jpg" else pix.tobytes("png")
                                zf.writestr(f"{base}_{ix:03d}.{fmt}", img)
                        out = bio.getvalue()
                        mime = "application/zip"
            elif aksi == "PDF → TXT":
                out = pdf_ke_teks(intermediate); mime="text/plain"
            elif aksi == "PDF → DOCX":
                out = pdf_ke_docx_teks(intermediate); mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            elif aksi == "Page Numbers":
                out = tambah_nomor_halaman(intermediate, posisi=pos, mulai=int(startnum))
            elif aksi == "Protect PDF":
                if not new_password: raise ValueError("Isi password baru terlebih dahulu.")
                with buka_pdf(intermediate) as doc:
                    out = pdf_ke_bytes(doc, encryption=fitz.PDF_ENCRYPT_AES_256,
                        owner_pw=new_password, user_pw=new_password, permissions=0)
            elif aksi == "Unlock PDF":
                with buka_pdf(intermediate) as doc: out = pdf_ke_bytes(doc, encryption=fitz.PDF_ENCRYPT_NONE)
            # Ekstensi mengikuti hasil sebenarnya: file tunggal = PDF/JPG/PNG,
            # beberapa file = ZIP. Nama kustom diterapkan pada isi ZIP juga.
            real_ext = ".zip" if mime == "application/zip" else ext
            out_name = str(Path(out_name).with_suffix(real_ext))
            st.session_state["pf_latest_result"] = (out, out_name, mime)
            st.success("Berhasil memproses " + str(len(selected_order)) + " halaman" + (" terpilih." if only_selected or aksi == "Split / Extract" else "."))
        result = st.session_state.get("pf_latest_result")
        if result:
            blob, filename, mime = result
            download_hasil(blob, filename, mime)
            if mime == "application/pdf":
                if st.button("📁 Simpan hasil ke ruang kerja bersama", key="pf_add_workspace"):
                    st.session_state.setdefault("pdf_workspace", {})[filename] = blob
                    st.success("Hasil sudah tersimpan; tersedia di semua submenu PDF Tools.")
    except Exception as exc:
        st.error(f"PDF Playfull: {exc}")


# =========================================================
# TAMPILAN WEB UTAMA
# =========================================================
st.set_page_config(
    page_title="PDF Toolkit, Playfull & Pemotong Skripsi",
    page_icon="📄",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1200px;}
    div[data-testid="stButton"] > button {min-height: 3.2rem; border-radius: 12px; font-weight: 650;}
    div[data-testid="stDownloadButton"] > button {border-radius: 10px; font-weight: 650;}
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("📚 Menu")
    menu = st.radio(
        "Pilih fitur",
        ["✂️ Pemotong Skripsi", "🧰 PDF Tools", "😊 PDF Playfull"],
        label_visibility="collapsed",
    )
    st.divider()
    st.caption("Semua proses dilakukan saat tombol proses ditekan dan hasil dapat langsung diunduh.")

if menu == "✂️ Pemotong Skripsi":
    tampilkan_pemotong_skripsi()
elif menu == "🧰 PDF Tools":
    tampilkan_pdf_tools()
else:
    tampilkan_pdf_playfull()
