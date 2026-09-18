import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.tmp-pdf-tools'))
import pymupdf as fitz
from PIL import Image

SOURCE = Path(r'C:\Users\suici\Downloads\Siz3r_Wyniki_Vistula (2).pdf')
PHOTOS = Path(r'C:\Users\suici\Downloads\bhp1')
FOLDERS = [PHOTOS / ('New folder' if n == 1 else f'New folder ({n})') for n in range(1, 6)]
OUT = Path(__file__).resolve().parent
original = fitz.open(SOURCE)
result = fitz.open()
result.insert_pdf(original, from_page=0, to_page=0)
page = result[0]
subtitle = next(s for b in page.get_text('dict', flags=0)['blocks'] for l in b.get('lines', []) for s in l['spans'] if s['text'].startswith('Produkty Vistula'))
page.add_redact_annot(fitz.Rect(subtitle['bbox']), fill=False)
page.apply_redactions(images=0, graphics=0)
page.insert_text(subtitle['origin'], 'Odzie\u017c BHP na zdj\u0119ciach klient\u00f3w.', fontname='Subtitle', fontfile=r'C:\Windows\Fonts\arialbd.ttf', fontsize=13, color=(0.611765, 0.639216, 0.686275))
for link in page.get_links():
    page.delete_link(link)
for number in range(1, 6):
    slide = fitz.open()
    slide.insert_pdf(original, from_page=1, to_page=1)
    page = slide[0]
    content = page.read_contents().decode('latin1')
    # Remove the category text object, retaining every other original element.
    content, count = re.subn(r'BT[^\n]*\(PE\\001NE\) Tj ET', '', content)
    assert count == 1
    images = sorted(
        [im for im in page.get_image_info(xrefs=True) if im['height'] > 1000],
        key=lambda im: im['bbox'][0],
    )
    assert len(images) == 3
    names = {im[0]: im[7] for im in page.get_images()}
    for column, info in enumerate(images, 1):
        paths = list(FOLDERS[number-1].glob(f'{column}.*'))
        assert len(paths) == 1
        path = paths[0]
        with Image.open(path) as im:
            width, height = im.size
            if path.suffix.lower() == '.webp':
                buffer = io.BytesIO()
                im.save(buffer, format='PNG')
                stream = buffer.getvalue()
            else:
                stream = path.read_bytes()
        page.replace_image(info['xref'], stream=stream)
        # Fill the original rounded frame with proportional scaling and clipping.
        name = names[info['xref']]
        pattern = r'([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm\s+/' + re.escape(name) + r' Do'
        match = re.search(pattern, content)
        assert match
        w, h, x, y = map(float, match.groups())
        contain = column == 2 and number <= 4
        scale = min(w / width, h / height) if contain else max(w / width, h / height)
        nw, nh = width * scale, height * scale
        nx, ny = x + (w - nw) / 2, y + (h - nh) / 2
        replacement = f'{nw:.6f} 0 0 {nh:.6f} {nx:.6f} {ny:.6f} cm\n/{name} Do'
        if contain:
            replacement = f'1 1 1 rg {x} {y} {w} {h} re f\n' + replacement
        content = re.sub(pattern, lambda _: replacement, content, count=1)
    first = page.get_contents()[0]
    page.set_contents(first)
    slide.update_stream(first, content.encode('latin1'))
    result.insert_pdf(slide)
    slide.close()

result.insert_pdf(original, from_page=len(original)-1, to_page=len(original)-1)
result.set_metadata({'title': 'Siz3r - Wyniki e-przymierzalni - BHP'})
target = OUT / 'Siz3r_Wyniki_BHP.pdf'
result.save(target, garbage=4, deflate=True)
result.close()

check = fitz.open(target)
assert len(check) == 7
assert 'Odzie\u017c BHP na zdj\u0119ciach klient\u00f3w.' in check[0].get_text().replace('\u00a0', ' ')
for number in range(1, 6):
    page = check[number]
    assert all(label not in page.get_text() for label in ['PE\u0141NE', 'G\u00d3RA', 'D\u00d3\u0141'])
    actual = sorted([im for im in page.get_image_info(xrefs=True) if im['bbox'][1] > 100], key=lambda im: im['bbox'][0])
    assert len(actual) == 3
    for column, im in enumerate(actual, 1):
        with Image.open(next(FOLDERS[number-1].glob(f'{column}.*'))) as source:
            assert (im['width'], im['height']) == source.size
            embedded = Image.open(io.BytesIO(check.extract_image(im['xref'])['image']))
            assert embedded.convert('RGB').tobytes() == source.convert('RGB').tobytes(), 'Image pixels changed'
        rect = fitz.Rect(im['bbox'])
        assert abs(rect.width / rect.height - im['width'] / im['height']) < 0.001

sheet = Image.new('RGB', (1012, 4 * 370), '#eeeeee')
for i, page in enumerate(check):
    pix = page.get_pixmap(matrix=fitz.Matrix(0.6, 0.6))
    im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    sheet.paste(im, ((i % 2) * 506, (i // 2) * 370))
    if i in [0, 1, 5, 8, 9, 10]:
        page.get_pixmap(matrix=fitz.Matrix(1, 1)).save(OUT / f'aligned-{i+1}.png')
sheet.save(OUT / 'overview-aligned.jpg')
print(f'OK: {len(check)} pages, 15 photographs in order, subtitle and labels verified. {target}')
