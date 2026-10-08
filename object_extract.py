"""Read-only PDF object/region extraction; no changes to the source PDF or draft."""
from __future__ import annotations
import io
import math
import re
import zipfile
from pathlib import Path

import fitz
from PIL import Image

MAX_OBJECTS = 30
MAX_RENDER_PIXELS = 18_000_000  # Protect small Render machines from huge raster allocations
ALLOWED_FORMATS = {'original', 'png', 'jpg', 'webp'}


def safe_stem(s: str, fallback: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(s or '')).strip().strip('.')
    return s[:95] or fallback


def normalize_rect(page, coords):
    if not isinstance(coords, dict):
        raise ValueError('Pilih kotak objek atau seleksi area terlebih dahulu.')
    values = [float(coords.get(k, float('nan'))) for k in ('x','y','w','h')]
    x,y,w,h = values
    if not all(math.isfinite(v) for v in values) or w<=0 or h<=0:
        raise ValueError('Area ekstraksi tidak valid.')
    if min(x, y) < -0.0005 or x+w > 1.0005 or y+h > 1.0005:
        raise ValueError('Area ekstraksi di luar halaman.')
    box=fitz.Rect(x*page.rect.width,y*page.rect.height,(x+w)*page.rect.width,(y+h)*page.rect.height)
    box &= page.rect
    if box.is_empty or box.width < 1 or box.height < 1:
        raise ValueError('Area terlalu kecil atau berada di luar halaman.')
    return box


def render_clip(page, clip, fmt, dpi, transparent=False):
    scale = dpi/72
    width=math.ceil(clip.width*scale);height=math.ceil(clip.height*scale)
    if width*height>MAX_RENDER_PIXELS:
        raise ValueError('Area terlalu besar untuk DPI ini. Perkecil kotak atau gunakan 150/300 DPI.')
    pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),clip=clip,colorspace=fitz.csRGB,
                        alpha=transparent and fmt in {'png','webp'})
    raw=pix.tobytes('png')
    return convert_image(raw,fmt,transparent),fmt


def convert_image(raw,fmt,transparent=False):
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        if fmt == 'png':
            image=image.convert('RGBA' if (transparent and 'A' in image.getbands()) else 'RGB')
            ext='PNG'; kw={}
        elif fmt=='jpg':
            image=image.convert('RGB');ext='JPEG';kw={'quality':94,'subsampling':0}
        elif fmt=='webp':
            image=image.convert('RGBA' if transparent and 'A' in image.getbands() else 'RGB')
            ext='WEBP';kw={'lossless': True,'method':4}
        else: raise ValueError('Format tidak didukung.')
        out=io.BytesIO();image.save(out,format=ext,**kw);return out.getvalue()


def native_image(doc,page,box,fmt,transparent):
    """Locate displayed raster occurrence by bbox and return its original image xref.

    If a logo is vector content or baked into a scan, the UI should use area mode.
    """
    candidates=[]
    for img in page.get_image_info(xrefs=True):
        xref=int(img.get('xref') or 0)
        if xref<=0:continue
        r=fitz.Rect(img['bbox']); intersection=(box&r).get_area()
        if intersection<=0:continue
        overlap=intersection/max(1,box.get_area())
        cover=intersection/max(1,r.get_area())
        if overlap>=.55 and cover>=.45:
            candidates.append((overlap+cover,xref))
    if not candidates:
        raise ValueError('Tidak ada gambar bitmap asli pada kotak itu. Gunakan Mode B untuk scan, teks atau logo vektor.')
    _,xref=max(candidates)
    info=doc.extract_image(xref)
    if not info or not info.get('image'):
        raise ValueError('Gambar asli tidak dapat diekstrak. Coba Mode B.')
    raw=info['image']; ext=str(info.get('ext') or 'png').lower()
    smask=int(info.get('smask') or 0)
    if smask:
        base=fitz.Pixmap(doc,xref);mask=fitz.Pixmap(doc,smask)
        try:
            merged=fitz.Pixmap(base,mask)
            raw=merged.tobytes('png')
        finally:
            base=None;mask=None
        ext='png'
    if fmt=='original':
        if ext=='jpeg':ext='jpg'
        return raw,ext
    return convert_image(raw,fmt,transparent),fmt


def extract_many(files, options):
    items=options.get('items',[])
    if not isinstance(items,list) or not 1 <= len(items) <= MAX_OBJECTS:
        raise ValueError(f'Pilih 1–{MAX_OBJECTS} objek/area untuk diekstrak.')
    if len(files)>12:raise ValueError('Maksimal 12 dokumen sekaligus.')
    fmt=options.get('format','png')
    if fmt not in ALLOWED_FORMATS:raise ValueError('Format gambar tidak didukung.')
    dpi=int(options.get('dpi',300))
    if dpi not in (150,300,600):raise ValueError('Resolusi hanya 150, 300 atau 600 DPI.')
    transparent=bool(options.get('transparent',False))
    passwords=options.get('passwords',[])
    docs=[]
    try:
        for i,f in enumerate(files):
            if not f.name.lower().endswith('.pdf'):raise ValueError('Hanya file PDF yang dapat diekstrak.')
            doc=fitz.open(stream=f.data,filetype='pdf')
            pw=passwords[i] if isinstance(passwords,list) and i<len(passwords) else ''
            if doc.needs_pass and not doc.authenticate(str(pw or '')):
                doc.close();raise ValueError(f'Password PDF {f.name} tidak sesuai.')
            docs.append(doc)
        outs=[];used=set()
        for index,item in enumerate(items):
            fidx=int(item.get('fileIndex',-1));pnum=int(item.get('page',0))
            if not 0 <= fidx < len(docs):raise ValueError('Asal file tidak valid.')
            doc=docs[fidx]
            if not 1<=pnum<=len(doc):raise ValueError('Halaman di luar rentang PDF.')
            page=doc[pnum-1]
            mode=item.get('mode')
            if mode not in ('object','area'):raise ValueError('Mode ekstraksi tidak valid.')
            clip=normalize_rect(page,item.get('rect'))
            use_native=(mode=='object' and options.get('quality','native')=='native')
            if use_native:
                out,ext=native_image(doc,page,clip,fmt,transparent)
            else:
                f = 'png' if fmt=='original' else fmt
                out,ext=render_clip(page,clip,f,dpi,transparent)
            stem=safe_stem(item.get('name'),f'{Path(files[fidx].name).stem}_h{pnum:03d}_{index+1:02d}')
            # User can type the extension, but the output extension must match the actual bytes.
            stem=re.sub(r'\.(png|jpe?g|webp|jpx|tiff?|bmp)$','',stem,flags=re.IGNORECASE)
            name=f'{stem}.{ext}'
            base=name
            j=2
            while name.casefold() in used:
                name=f'{stem}_{j}.{ext}'; j+=1
            used.add(name.casefold())
            outs.append((name,out))
        if len(outs)==1:
            n,b=outs[0]
            return b,n,{'png':'image/png','jpg':'image/jpeg','webp':'image/webp',
                        'jpx':'image/jp2','tif':'image/tiff','tiff':'image/tiff'}.get(Path(n).suffix.lstrip('.'),'application/octet-stream')
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
            for name,data in outs:z.writestr(name,data)
        name=safe_stem(options.get('zipName'),'Hasil_Ekstrak_Objek')
        if not name.lower().endswith('.zip'):name+='.zip'
        return buf.getvalue(),name,'application/zip'
    finally:
        for doc in docs:doc.close()
