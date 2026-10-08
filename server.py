"""Backend FastAPI. Jalankan: uvicorn server:app --reload"""
import atexit, io, json, os, secrets, shutil, tempfile, threading, time, zipfile
from pathlib import Path
import fitz
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
import pdf_core as c

app = FastAPI(title="PDFKit")


@app.get("/healthz")
def healthz():
    """Render health check: endpoint ringan tanpa memproses PDF."""
    return {"status": "ok"}
MAX_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))   # batas per file (server gratis RAM-nya kecil)
MAX_FILES, MAX_PREVIEW = 20, 300
PREVIEW_TTL_SECONDS = 20 * 60
MAX_PREVIEW_SESSION_MB = 80
MAX_ACTIVE_PREVIEW_MB = 160
MAX_PREVIEW_SESSIONS = 12
_preview_lock = threading.RLock()
_preview_render_slots = threading.BoundedSemaphore(2)
_preview_sessions = {}
_preview_root = Path(tempfile.mkdtemp(prefix="pdf-playfull-preview-"))
atexit.register(lambda: shutil.rmtree(_preview_root, ignore_errors=True))
PDF, ZIP = "application/pdf", "application/zip"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class Berkas:  # pengganti objek upload Streamlit
    def __init__(s, name, data): s.name, s.data = name, data
    def getvalue(s): return s.data


def baca(f):
    d = f.file.read(MAX_MB * 1048576 + 1)
    if len(d) > MAX_MB * 1048576: raise ValueError(f"{f.filename} melebihi batas {MAX_MB} MB.")
    return d


def pw(o): return o.get("password", "")
def stem(f): return c.nama_file_aman(f.name)
def satu(fs):
    if not fs: raise ValueError("Unggah file terlebih dahulu.")
    return fs[0]


def skripsi(fs, o):
    if not fs: raise ValueError("Unggah file terlebih dahulu.")
    buf, ok, gagal = io.BytesIO(), 0, []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in fs:
            try: h, p = c.proses_pdf(f.data, o.get("tahun", "2026"))
            except Exception as e: h, p = None, f"{type(e).__name__}: {e}"
            if h is None: gagal.append(f"{f.name}: {p}"); continue
            ok += 1
            for path, isi in h["files"].items(): z.writestr(path, isi)
        if gagal: z.writestr("PERIKSA.txt", "\n".join(gagal))
    if not ok: raise ValueError("Tidak ada yang berhasil. " + "; ".join(gagal))
    return buf.getvalue(), "Hasil_Potongan.zip", ZIP, f"Berhasil {ok}, perlu periksa {len(gagal)}"


def merge(fs, o):
    d, n = c.gabung_pdf(fs); return d, "merged.pdf", PDF, f"{n} halaman"


def rewrite(b):
    with c.buka_pdf(b) as d: return c.pdf_ke_bytes(d, encryption=fitz.PDF_ENCRYPT_NONE)


def playfull(fs, o):
    if not fs: raise ValueError("Unggah file terlebih dahulu.")
    a, sel, pwd = o.get("aksi", "susun"), set(o.get("selected", [])), pw(o)
    base = fitz.open()
    try:
        for f in fs:
            with c.buka_pdf(f.data, pwd) as d: base.insert_pdf(d)
        total, base_b = len(base), c.pdf_ke_bytes(base, encryption=fitz.PDF_ENCRYPT_NONE)
    finally: base.close()
    order = o.get("order") or list(range(1, total + 1))
    if sorted(order) != list(range(1, total + 1)): raise ValueError("Urutan halaman tidak valid.")
    if (a in ("hapus", "duplikat", "extract") or o.get("only")) and not sel:
        raise ValueError("Centang halaman pada pratinjau terlebih dahulu.")
    if a == "hapus": use = [n for n in order if n not in sel]
    elif a == "duplikat": use = [n for n in order for _ in range(2 if n in sel else 1)]
    elif a == "extract" or o.get("only"): use = [n for n in order if n in sel]
    else: use = list(order)
    if not use: raise ValueError("Hasil PDF tidak boleh kosong.")
    with c.buka_pdf(base_b) as src: mid = c.buat_pdf_halaman(src, [n - 1 for n in use])
    out, ext, mime = mid, ".pdf", PDF
    if a == "putar":
        with c.buka_pdf(mid) as d:
            for j, n in enumerate(use):
                if not sel or n in sel: d[j].set_rotation((d[j].rotation + int(o.get("sudut", 90))) % 360)
            out = c.pdf_ke_bytes(d, encryption=fitz.PDF_ENCRYPT_NONE)
    elif a == "split": out, ext, mime = c.split_pdf_zip(mid, "per_halaman")[0], ".zip", ZIP
    elif a == "compress": out = c.kompres_pdf_raster(mid, int(o.get("dpi", 120))) if o.get("kompresi") == "kuat" else rewrite(mid)
    elif a == "img": out, ext, mime = c.pdf_ke_gambar_zip(mid, o.get("format", "jpg"), int(o.get("dpi", 150)))[0], ".zip", ZIP
    elif a == "txt": out, ext, mime = c.pdf_ke_teks(mid), ".txt", "text/plain"
    elif a == "docx": out, ext, mime = c.pdf_ke_docx_teks(mid), ".docx", DOCX
    elif a == "nomor": out = c.tambah_nomor_halaman(mid, o.get("posisi", "Bawah tengah"), int(o.get("mulai", 1)))
    elif a == "protect":
        if not o.get("baru"): raise ValueError("Isi password baru terlebih dahulu.")
        with c.buka_pdf(mid) as d:
            out = c.pdf_ke_bytes(d, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=o["baru"], owner_pw=o["baru"], permissions=0)
    elif a == "unlock": out = rewrite(mid)
    nama = c.nama_file_aman(o["nama"]) if o.get("nama") else f"{stem(fs[0])}_{a}"
    return out, nama + ext, mime, f"{len(use)} halaman"


def organize(fs, o): return playfull(fs, {**o, "aksi": "susun"})


def split(fs, o):
    f, m = satu(fs), o.get("mode", "extract")
    if m == "extract":
        with c.buka_pdf(f.data, pw(o)) as p:
            d = c.buat_pdf_halaman(p, c.parse_halaman(o.get("halaman", ""), len(p)))
        return d, f"{stem(f)}_extract.pdf", PDF, "Selesai"
    nilai = int(o.get("n", 5)) if m == "setiap_n" else o.get("grup", "")
    d, j = c.split_pdf_zip(f.data, m, nilai, pw(o))
    return d, f"{stem(f)}_split.zip", ZIP, f"{j} file"


def delete(fs, o):
    f = satu(fs)
    with c.buka_pdf(f.data, pw(o)) as p:
        hapus = set(c.parse_halaman(o.get("halaman", ""), len(p)))
        simpan = [i for i in range(len(p)) if i not in hapus]
        if not simpan: raise ValueError("Semua halaman tidak boleh dihapus.")
        d = c.buat_pdf_halaman(p, simpan)
    return d, f"{stem(f)}_deleted.pdf", PDF, f"Sisa {len(simpan)} halaman"


def rotate(fs, o):
    f = satu(fs)
    with c.buka_pdf(f.data, pw(o)) as p:
        for i in c.parse_halaman(o.get("halaman", "semua"), len(p), default_semua=True):
            p[i].set_rotation((p[i].rotation + int(o.get("sudut", 90))) % 360)
        d = c.pdf_ke_bytes(p, encryption=fitz.PDF_ENCRYPT_NONE)
    return d, f"{stem(f)}_rotated.pdf", PDF, "Selesai"


def compress(fs, o):
    f = satu(fs)
    if o.get("mode") == "kuat":
        d = c.kompres_pdf_raster(f.data, int(o.get("dpi", 120)), int(o.get("kualitas", 70)), pw(o))
    else:
        with c.buka_pdf(f.data, pw(o)) as p: d = c.pdf_ke_bytes(p, encryption=fitz.PDF_ENCRYPT_NONE)
    return d, f"{stem(f)}_compressed.pdf", PDF, f"{c.format_ukuran(len(f.data))} -> {c.format_ukuran(len(d))}"


def pdf_image(fs, o):
    f, fmt = satu(fs), o.get("format", "jpg")
    d, j = c.pdf_ke_gambar_zip(f.data, fmt, int(o.get("dpi", 150)), int(o.get("kualitas", 90)), pw(o))
    return d, f"{stem(f)}_{fmt}.zip", ZIP, f"{j} halaman"


def image_pdf(fs, o):
    d, j = c.gambar_ke_pdf(fs); return d, "images_to_pdf.pdf", PDF, f"{j} halaman"


def pdf_text(fs, o):
    f = satu(fs); return c.pdf_ke_teks(f.data, pw(o)), f"{stem(f)}.txt", "text/plain", "Selesai"


def pdf_docx(fs, o):
    f = satu(fs); return c.pdf_ke_docx_teks(f.data, pw(o)), f"{stem(f)}.docx", DOCX, "Selesai"


def word_pdf(fs, o):
    f = satu(fs); return c.word_ke_pdf(f.data, f.name), f"{stem(f)}.pdf", PDF, "Selesai"


def number(fs, o):
    f = satu(fs)
    d = c.tambah_nomor_halaman(f.data, o.get("posisi", "Bawah tengah"), int(o.get("mulai", 1)), int(o.get("ukuran", 10)), pw(o))
    return d, f"{stem(f)}_numbered.pdf", PDF, "Selesai"


def protect(fs, o):
    f, pwd = satu(fs), pw(o)
    if not pwd: raise ValueError("Password tidak boleh kosong.")
    perm = fitz.PDF_PERM_ACCESSIBILITY
    if o.get("print"): perm |= fitz.PDF_PERM_PRINT | fitz.PDF_PERM_PRINT_HQ
    if o.get("copy"): perm |= fitz.PDF_PERM_COPY
    with c.buka_pdf(f.data) as p:
        d = c.pdf_ke_bytes(p, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=pwd, owner_pw=o.get("owner") or pwd, permissions=perm)
    return d, f"{stem(f)}_protected.pdf", PDF, "PDF terkunci"


def unlock(fs, o):
    f = satu(fs)
    with c.buka_pdf(f.data, pw(o)) as p: d = c.pdf_ke_bytes(p, encryption=fitz.PDF_ENCRYPT_NONE)
    return d, f"{stem(f)}_unlocked.pdf", PDF, "Kunci dibuka"


TOOLS = {fn.__name__: fn for fn in (skripsi, merge, organize, playfull, split, delete, rotate, compress, pdf_image,
                                    image_pdf, pdf_text, pdf_docx, word_pdf, number, protect, unlock)}


def _discard_preview(token):
    session = _preview_sessions.pop(token, None)
    if session:
        shutil.rmtree(session["directory"], ignore_errors=True)


def _clean_previews(now):
    """Hapus file sementara setelah 20 menit tidak dipakai."""
    for token, session in list(_preview_sessions.items()):
        if now - session["last_used"] >= PREVIEW_TTL_SECONDS:
            _discard_preview(token)


def _preview_error(message, status=400):
    return JSONResponse({"detail": message}, status_code=status)


@app.post("/preview/init")
def init_preview(files: list[UploadFile] = File(...), password: str = Form("")):
    """Upload sekali saja. Kirim metadata halaman tanpa merender thumbnail."""
    if not files or len(files) > MAX_FILES:
        return _preview_error(f"Unggah 1–{MAX_FILES} PDF.")
    token = secrets.token_urlsafe(32)
    directory = _preview_root / token
    directory.mkdir(mode=0o700)
    metadata, sumber, starts, total_bytes = [], [], [], 0
    try:
        for k, uploaded in enumerate(files):
            name = uploaded.filename or f"Berkas {k + 1}.pdf"
            if not name.lower().endswith(".pdf"):
                raise ValueError(f"{name} bukan file PDF.")
            path = directory / f"{k:03d}.pdf"
            size = 0
            with path.open("wb") as target:
                while data := uploaded.file.read(1024 * 1024):
                    size += len(data)
                    total_bytes += len(data)
                    if size > MAX_MB * 1048576:
                        raise ValueError(f"{name} melebihi batas {MAX_MB} MB.")
                    if total_bytes > MAX_PREVIEW_SESSION_MB * 1048576:
                        raise ValueError(f"Total file preview maksimal {MAX_PREVIEW_SESSION_MB} MB.")
                    target.write(data)
            starts.append(len(metadata))
            with fitz.open(path) as pdf:
                if pdf.needs_pass and (not password or pdf.authenticate(password) <= 0):
                    raise ValueError("PDF terkunci. Masukkan password yang benar.")
                if not pdf.is_pdf:
                    raise ValueError(f"{name} bukan file PDF yang valid.")
                if len(metadata) + len(pdf) > MAX_PREVIEW:
                    raise ValueError(f"Pratinjau dibatasi {MAX_PREVIEW} halaman.")
                for j in range(len(pdf)):
                    metadata.append({"file": name, "page": j + 1})
            sumber.append(str(path))
        with _preview_lock:
            now = time.monotonic()
            _clean_previews(now)
            if len(_preview_sessions) >= MAX_PREVIEW_SESSIONS or (
                sum(s["bytes"] for s in _preview_sessions.values()) + total_bytes
                > MAX_ACTIVE_PREVIEW_MB * 1048576
            ):
                raise ValueError("Server sedang penuh dengan sesi preview. Tunggu sebentar lalu coba lagi.")
            _preview_sessions[token] = {
                "directory": directory, "paths": sumber, "pages": metadata,
                "password": password, "last_used": now, "bytes": total_bytes,
                "starts": starts,
            }
        return {"session": token, "pages": metadata}
    except Exception as exc:
        shutil.rmtree(directory, ignore_errors=True)
        return _preview_error(str(exc))


def _get_preview_page(token, page_index):
    with _preview_lock:
        now = time.monotonic()
        _clean_previews(now)
        session = _preview_sessions.get(token)
        if session is None:
            raise LookupError("Sesi preview berakhir. Klik Muat ulang.")
        if page_index < 0 or page_index >= len(session["pages"]):
            raise IndexError("Nomor halaman tidak valid.")
        # Asal file dicatat menurut nomor halaman pertama, bukan menurut namanya:
        # dua file berbeda boleh mempunyai nama yang sama.
        offsets = session["starts"]
        file_index = max(i for i, start in enumerate(offsets) if start <= page_index)
        session["last_used"] = now
        return session["paths"][file_index], page_index - offsets[file_index], session["password"]


@app.get("/preview/thumb/{token}/{page_index}")
def preview_thumb(token: str, page_index: int):
    try:
        path, number, password = _get_preview_page(token, page_index)
        with _preview_render_slots:
            with fitz.open(path) as pdf:
                if pdf.needs_pass:
                    pdf.authenticate(password)
                picture = pdf[number].get_pixmap(dpi=36, colorspace=fitz.csRGB, alpha=False)
                data = picture.tobytes("jpeg", jpg_quality=60)
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=900"})
    except (LookupError, IndexError) as exc:
        return _preview_error(str(exc), 404 if isinstance(exc, IndexError) else 410)
    except Exception:
        return _preview_error("Gagal membuat thumbnail PDF.")


@app.get("/preview/page/{token}/{page_index}")
def preview_large(token: str, page_index: int):
    try:
        path, number, password = _get_preview_page(token, page_index)
        with _preview_render_slots:
            with fitz.open(path) as pdf:
                if pdf.needs_pass:
                    pdf.authenticate(password)
                picture = pdf[number].get_pixmap(dpi=120, colorspace=fitz.csRGB, alpha=False)
                data = picture.tobytes("jpeg", jpg_quality=80)
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=900"})
    except (LookupError, IndexError) as exc:
        return _preview_error(str(exc), 404 if isinstance(exc, IndexError) else 410)
    except Exception:
        return _preview_error("Gagal membuat pratinjau halaman.")


@app.delete("/preview/session/{token}")
def close_preview(token: str):
    with _preview_lock:
        _discard_preview(token)
    return {"status": "ok"}


@app.post("/api/{tool}")
def jalankan(tool: str, files: list[UploadFile] = File(default=[]), opts: str = Form("{}")):
    if tool not in TOOLS: return JSONResponse({"detail": "Alat tidak ditemukan."}, 404)
    try:
        if len(files) > MAX_FILES: raise ValueError(f"Maksimal {MAX_FILES} file sekaligus.")
        fs = [Berkas(f.filename or "file", baca(f)) for f in files]
        data, nama, mime, info = TOOLS[tool](fs, json.loads(opts))
    except Exception as e:
        return JSONResponse({"detail": str(e)}, 400)
    return Response(data, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="{nama}"',
        "X-Info": info.encode("ascii", "ignore").decode(),
        "Access-Control-Expose-Headers": "X-Info, Content-Disposition"})


# Extra tools: advanced visual editing, conversion, OCR, forms and document security.
import advanced_pdf as adv

@app.post("/advanced/inspect")
def advanced_inspect(file: UploadFile = File(...), page: int = Form(1), password: str = Form("")):
    try:
        if not (file.filename or "").lower().endswith(".pdf"):
            raise ValueError("Pilih file PDF.")
        return adv.inspect_page(baca(file), page, password)
    except Exception as exc:
        return JSONResponse({"detail":str(exc)},status_code=400)

@app.post("/advanced/process/{tool}")
def advanced_process(tool: str, files: list[UploadFile] = File(...), opts: str = Form("{}")):
    try:
        if len(files)>2: raise ValueError("Maksimum dua dokumen untuk fitur ini.")
        if len(opts)>7_000_000: raise ValueError("Terlalu banyak perubahan atau gambar.")
        options=json.loads(opts)
        fs=[Berkas(f.filename or "dokumen.pdf", baca(f)) for f in files]
        # All document-level operations consume the current draft when present.
        # This avoids forcing a manual export/reupload between page editing and OCR, PDF/A, etc.
        if fs and fs[0].name.lower().endswith('.pdf'):
            edit_ops = options.pop('draft_ops', [])
            page_actions = options.pop('draft_page_actions', [])
            if edit_ops or page_actions:
                import workspace_ops as wops
                if edit_ops:
                    changed = adv.apply_edits(fs[0].data, {
                        'password':options.get('password',''), 'operations':edit_ops,
                        'quality_match':bool(options.get('quality_match',False)),
                    })
                else:
                    changed = fs[0].data
                if page_actions:
                    with adv.open_pdf(changed, options.get('password','') if not edit_ops else '') as pdf:
                        wops.apply_document_actions(pdf,page_actions)
                        changed=adv.save_pdf(pdf)
                fs[0]=Berkas(fs[0].name,changed)
                options['password']=''
        body,name,mime,info=adv.dispatch(tool,fs,options)
        return Response(body,media_type=mime,headers={
            "Content-Disposition":f'attachment; filename="{adv.safe_name(name)}"',
            "Access-Control-Expose-Headers":"Content-Disposition"})
    except Exception as exc:
        return JSONResponse({"detail":str(exc)},status_code=400)

def _download_disposition(name):
    from urllib.parse import quote
    safe = adv.safe_name(name)
    ascii_name = ''.join(ch if ch.isascii() and (ch.isalnum() or ch in '._- ()') else '_' for ch in safe)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(safe)}"


@app.post("/advanced/draft-preview")
def advanced_draft_preview(file: UploadFile = File(...), page: int = Form(1), password: str = Form(""), actions: str = Form("[]")):
    try:
        import workspace_ops as wops
        if len(actions) > 100_000: raise ValueError("Terlalu banyak data preview.")
        raw = baca(file)
        if len(raw) > 25 * 1024 * 1024: raise ValueError("PDF preview terlalu besar.")
        operations = json.loads(actions)
        if not isinstance(operations,list) or len(operations)>wops.MAX_ACTIONS:
            raise ValueError("Tindakan preview tidak valid.")
        result = wops.preview_page(raw, page, operations, password)
        return Response(result, media_type="image/png", headers={"Cache-Control":"no-store"})
    except (ValueError, TypeError, RuntimeError) as exc:
        return JSONResponse({"detail":str(exc)},status_code=400)


@app.post("/advanced/batch-edit")
def advanced_batch_edit(files: list[UploadFile] = File(...), opts: str = Form("{}")):
    try:
        if len(opts) > 9_000_000:
            raise ValueError("Data edit terlalu besar.")
        if not (1 <= len(files) <= 12):
            raise ValueError("Maksimum 12 PDF sekaligus.")
        fs = [Berkas(f.filename or "dokumen.pdf", baca(f)) for f in files]
        body, name, mime, count = adv.batch_edit(fs, json.loads(opts))
        return Response(body, media_type=mime, headers={
            "Content-Disposition": _download_disposition(name),
            "Access-Control-Expose-Headers": "Content-Disposition",
            "X-File-Count": str(count),
        })
    except (ValueError, TypeError, KeyError, RuntimeError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


app.mount("/", StaticFiles(directory=str(Path(__file__).parent / "static"), html=True), name="static")
