"""Non-AI PDF Playfull draft actions applied by page before basket export.

The input PDFs are immutable. Actions are submitted with export and only
selected output pages are copied into final results. Coordinates are PDF points.
"""
from __future__ import annotations

import base64
from collections import defaultdict
import fitz

SUPPORTED = {'watermark', 'crop', 'rotate_page', 'page_number', 'sign_visual', 'redact', 'form'}
MAX_ACTIONS = 400


def _rgb(value, fallback='#777777'):
    value = str(value or fallback).lstrip('#')
    if len(value) != 6 or any(ch not in '0123456789abcdefABCDEF' for ch in value):
        raise ValueError('Warna harus dalam format #RRGGBB.')
    return tuple(int(value[i:i+2], 16) / 255 for i in (0, 2, 4))


def _bounded(value, low, high, name):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} harus berupa angka.') from None
    if not (low <= number <= high):
        raise ValueError(f'{name} harus antara {low} dan {high}.')
    return number


def _signature(page, opts):
    data = str(opts.get('image', ''))
    if not data.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/jpg;base64,')):
        raise ValueError('Tanda tangan harus gambar PNG/JPG.')
    raw = base64.b64decode(data.partition(',')[2], validate=True)
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError('Ukuran tanda tangan maksimal 5 MB.')
    x = _bounded(opts.get('x', 50), 0, page.rect.width, 'X')
    y = _bounded(opts.get('y', 50), 0, page.rect.height, 'Y')
    w = _bounded(opts.get('w', 170), 5, page.rect.width, 'Lebar')
    h = _bounded(opts.get('h', 60), 5, page.rect.height, 'Tinggi')
    rect = fitz.Rect(x,y,x+w,y+h) & page.rect
    if rect.is_empty: raise ValueError('Posisi tanda tangan di luar halaman.')
    page.insert_image(rect, stream=raw, keep_proportion=True, overlay=True)


def apply_action(page, action, *, preview=False):
    """Apply exactly one page-specific action.

    Preview deliberately leaves crop and rotation unapplied because the editor's
    draggable original-object coordinates remain tied to the unrotated page.
    The UI shows the crop guide / rotation status and the exported PDF is exact.
    """
    tool = action.get('tool')
    options = action.get('options') or {}
    if tool not in SUPPORTED or not isinstance(options, dict):
        raise ValueError('Tindakan halaman tidak dikenal.')
    if tool == 'watermark':
        text = str(options.get('text', 'DRAFT'))[:200]
        if not text.strip(): raise ValueError('Teks watermark kosong.')
        fs = _bounded(options.get('fontSize', 35), 6, 120, 'Ukuran font')
        angle = int(_bounded(options.get('angle', 0), 0, 270, 'Rotasi watermark'))
        if angle not in (0, 90, 180, 270): raise ValueError('Rotasi watermark: 0/90/180/270.')
        opacity = _bounded(options.get('opacity', 0.32), 0.05, 1, 'Opacity')
        x = _bounded(options.get('x', 15), 0, 95, 'Posisi X (%)') / 100 * page.rect.width
        y = _bounded(options.get('y', 52), 0, 100, 'Posisi Y (%)') / 100 * page.rect.height
        shape = page.new_shape()
        shape.insert_text((x,y), text, fontname='helv', fontsize=fs, rotate=angle, color=_rgb(options.get('color')), fill_opacity=opacity)
        shape.commit(overlay=True)
    elif tool == 'crop':
        l,t,r,b = [_bounded(options.get(k,0),0,300,k) for k in ('left','top','right','bottom')]
        base = page.cropbox
        rect = fitz.Rect(base.x0+l,base.y0+t,base.x1-r,base.y1-b)
        if rect.width < 30 or rect.height < 30: raise ValueError('Crop terlalu besar.')
        if not preview: page.set_cropbox(rect)
    elif tool == 'rotate_page':
        angle = int(options.get('angle', 90))
        if angle not in (90,180,270): raise ValueError('Putar halaman: 90, 180, atau 270.')
        if not preview: page.set_rotation((page.rotation+angle)%360)
    elif tool == 'page_number':
        value = str(options.get('text') or options.get('number') or '1')[:40]
        fs = _bounded(options.get('fontSize', 11), 6, 36, 'Ukuran nomor halaman')
        position = options.get('position','bottom_center')
        if position not in ('bottom_left','bottom_center','bottom_right','top_left','top_center','top_right'):
            raise ValueError('Posisi nomor halaman tidak valid.')
        width = max(40, page.rect.width / 3)
        left = {'left':20,'center':(page.rect.width-width)/2,'right':page.rect.width-width-20}[position.split('_')[1]]
        y = 18 if position.startswith('top') else page.rect.height-24
        alignment = {'left':0,'center':1,'right':2}[position.split('_')[1]]
        page.insert_textbox(fitz.Rect(left,y,left+width,y+fs*2),value,fontname='helv',fontsize=fs,align=alignment,color=_rgb(options.get('color','#222222')),overlay=True)
    elif tool == 'sign_visual':
        _signature(page,options)
    elif tool == 'redact':
        phrase = str(options.get('phrase','')).strip()
        if not phrase: raise ValueError('Isi teks yang akan disamarkan.')
        boxes = page.search_for(phrase)
        for rect in boxes: page.add_redact_annot(rect,fill=_rgb(options.get('color','#000000')),cross_out=False)
        if boxes: page.apply_redactions(images=0,graphics=0,text=0)
    elif tool == 'form':
        x = _bounded(options.get('x',60),0,page.rect.width,'X')
        y = _bounded(options.get('y',80),0,page.rect.height,'Y')
        w = _bounded(options.get('w',210),15,page.rect.width,'Lebar')
        h = _bounded(options.get('h',26),12,page.rect.height,'Tinggi')
        rect = fitz.Rect(x,y,x+w,y+h) & page.rect
        if rect.is_empty: raise ValueError('Field berada di luar halaman.')
        field=fitz.Widget()
        field.field_name=str(options.get('field_name','kolom'))[:70]
        if not field.field_name: raise ValueError('Nama field kosong.')
        field.field_label=field.field_name
        field.field_type=fitz.PDF_WIDGET_TYPE_TEXT
        field.rect=rect
        field.text_font='Helv'
        field.text_fontsize=11
        field.field_value=str(options.get('default',''))[:200]
        page.add_widget(field)


def validate_actions(doc, actions):
    if not isinstance(actions,list) or len(actions)>MAX_ACTIONS:
        raise ValueError(f'Maksimum {MAX_ACTIONS} tindakan per dokumen.')
    result=defaultdict(list)
    for item in actions:
        if not isinstance(item,dict) or type(item.get('page')) is not int:
            raise ValueError('Halaman tindakan harus berupa bilangan bulat.')
        n=item['page']
        if n<1 or n>len(doc):raise ValueError('Halaman tindakan di luar dokumen.')
        if item.get('tool') not in SUPPORTED:raise ValueError('Jenis tindakan tidak dikenal.')
        result[n].append(item)
    return result


def apply_document_actions(doc, actions):
    for page_no, operations in validate_actions(doc, actions).items():
        for op in operations: apply_action(doc[page_no-1],op)
    return doc


def preview_page(source, page, actions, password=''):
    """Render lightweight PNG of staged visible edits on one page only."""
    from advanced_pdf import open_pdf
    with open_pdf(source,password) as original:
        if not 1 <= page <= len(original): raise ValueError('Nomor halaman tidak valid.')
        with fitz.open() as preview:
            preview.insert_pdf(original,from_page=page-1,to_page=page-1)
            for entry in actions:
                if int(entry.get('page',-1))==page:
                    apply_action(preview[0],entry,preview=True)
            pix=preview[0].get_pixmap(matrix=fitz.Matrix(1.1,1.1),alpha=False)
            return pix.tobytes('png')
