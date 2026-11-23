"""Build Original photo | Garment | Result rows from the validated original PDF."""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.tmp-pdf-tools'))
import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
SOURCE = Path(r'C:\Users\suici\Downloads\Siz3r_Standard_and_Turbo_By_Garment.pdf')
TARGET = OUT / 'Siz3r_Standard_and_Turbo_Original_Garment_Result.pdf'
WIDTH, HEIGHT = 1080, 1440
FONT_FILES = {'Regular': r'C:\Windows\Fonts\arial.ttf', 'Bold': r'C:\Windows\Fonts\arialbd.ttf'}
FONTS = {name: fitz.Font(fontfile=path) for name, path in FONT_FILES.items()}


def color(value):
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


INK, MUTED, PAPER, BORDER, WHITE = map(color, ('152638', '667587', 'F5F7FA', 'DEE5ED', 'FFFFFF'))
RED, RED_BG = map(color, ('B54740', 'FFF0EE'))
ACCENT = {'standard': color('2863DB'), 'turbo': color('B76A0C')}
PALE = {'standard': color('E9F0FF'), 'turbo': color('FFF2DC')}
CATEGORY_LABELS = {'upper': 'Tops', 'lower': 'Bottoms', 'full': 'Full outfits'}


def rectangle(page, box, fill, stroke=None):
    page.draw_rect(fitz.Rect(box), color=stroke, fill=fill, width=0.7)


def text(page, x, y, value, size=16, bold=False, fill=INK, max_width=None):
    name = 'Bold' if bold else 'Regular'
    if max_width:
        size = min(size, size * max_width / max(FONTS[name].text_length(value, fontsize=size), 1))
    assert size >= 8, (value, size)
    page.insert_text((x, y + size), value, fontsize=size, fontname=name, color=fill)


def colorspace_fingerprint(document, xref):
    kind, value = document.xref_get_key(xref, 'ColorSpace')
    if kind != 'xref':
        return kind, value
    definition = document.xref_object(int(value.split()[0]), compressed=True)
    def resolved(match):
        target = int(match.group(1))
        if document.xref_is_stream(target):
            return 'stream-sha256:' + hashlib.sha256(document.xref_stream(target)).hexdigest()
        return document.xref_object(target, compressed=True)
    return kind, re.sub(r'(\d+) 0 R', resolved, definition)


def image_fingerprints(document):
    xrefs = {image[0] for page in document for image in page.get_images()}
    return {(document.xref_get_key(xref, 'Width'), document.xref_get_key(xref, 'Height'),
             colorspace_fingerprint(document, xref), document.xref_get_key(xref, 'BitsPerComponent'),
             document.xref_get_key(xref, 'Filter'),
             hashlib.sha256(document.xref_stream_raw(xref)).hexdigest()) for xref in xrefs}


manifest = json.loads((OUT / 'presentation-manifest.json').read_text(encoding='ascii'))
assert manifest['pages'] == 78 and manifest['test_cases'] == 156
plans = manifest['page_plan']
doc = fitz.open(SOURCE)
assert len(doc) == 78
source_fingerprints = image_fingerprints(doc)
print('Loaded the original presentation and all 156 try-ons.', flush=True)
for plan in plans:
    if plan['kind'] != 'garment':
        continue
    page = doc[plan['page'] - 1]
    originals = page.get_image_info(xrefs=True)
    reference = originals[0]
    image_offset = 1
    source_rows = []
    for row in plan['rows']:
        row_images = {'model': originals[image_offset], 'garment': reference}
        image_offset += 1
        if row['status'] == 'success':
            row_images['result'] = originals[image_offset]
            image_offset += 1
        source_rows.append(row_images)
    assert image_offset == len(originals)
    # Replace drawing commands while reusing the exact existing image objects.
    stream = doc.get_new_xref()
    doc.update_object(stream, '<<>>')
    doc.update_stream(stream, b'')
    page.set_contents(stream)
    for name, fontfile in FONT_FILES.items():
        page.insert_font(fontname=name, fontfile=fontfile)
    mode = plan['mode']
    accent = ACCENT[mode]
    group_number = (plan['page'] - 2) % 39 + 1
    other_mode = 'turbo' if mode == 'standard' else 'standard'
    rectangle(page, (0, 0, WIDTH, HEIGHT), PAPER)
    rectangle(page, (0, 0, WIDTH, 7), accent)
    text(page, 40, 30, 'Siz3r', 24, bold=True)
    text(page, 139, 39, 'TRY-ON RESULTS', 11, bold=True, fill=MUTED)
    rectangle(page, (860, 28, 1040, 67), PALE[mode])
    text(page, 881, 37, mode.upper(), 15, bold=True, fill=accent)
    text(page, 40, 87, f"{CATEGORY_LABELS[plan['category']].upper()}  /  {plan['gender'].upper()}  /  G{group_number:02d}",
         12, bold=True, fill=accent)
    text(page, 694, 85, f"Compare with {other_mode.title()}  /  page {plan['compare_page']}",
         12, fill=accent, max_width=336)
    text(page, 40, 116, plan['title'], 31, bold=True, max_width=998)
    successes = sum(row['status'] == 'success' for row in plan['rows'])
    count = len(plan['rows'])
    text(page, 40, 176, f"{count} try-on{'s' if count != 1 else ''}  /  {successes} of {count} results available",
         12, fill=MUTED)
    top, bottom, gap = 206, 1364, 18
    row_height = (bottom - top - gap * (count - 1)) / count
    for i, (row, row_images) in enumerate(zip(plan['rows'], source_rows)):
        y = top + i * (row_height + gap)
        end = y + row_height
        shared_height = min([row_height - 88] + [292 * image['height'] / image['width']
                                                  for image in row_images.values()])
        image_top = y + 44 + (row_height - 88 - shared_height) / 2
        boxes = {}
        for x, kind, label in ((40, 'model', 'ORIGINAL PHOTO'), (380, 'garment', 'GARMENT'),
                                (720, 'result', 'RESULT')):
            fill = RED_BG if kind == 'result' and row['status'] == 'failed' else WHITE
            rectangle(page, (x, y, x + 320, end), fill, BORDER)
            text(page, x + 15, y + 13, label, 12, bold=True, fill=accent if kind == 'result' else MUTED)
            boxes[kind] = (x + 14, image_top, x + 306, image_top + shared_height)
            if kind in row_images:
                page.insert_image(fitz.Rect(boxes[kind]), xref=row_images[kind]['xref'], keep_proportion=True)
        text(page, 55, end - 28, 'Model ' + row['model_id'], 11, bold=True)
        text(page, 395, end - 28, f'Garment G{group_number:02d}', 11, fill=MUTED)
        if row['status'] == 'success':
            text(page, 735, end - 28, mode.title(), 11, bold=True, fill=accent)
        else:
            center = y + row_height / 2
            text(page, 750, center - 43, 'No result', 26, bold=True, fill=RED)
            text(page, 750, center + 3, 'Generation timed out', 16, fill=RED)
            text(page, 750, center + 33, 'after 105 seconds.', 16, fill=RED)
        row.update(row_top=y, image_boxes=boxes, image_height=shared_height,
                   display_order=['model', 'garment', 'result'])
    page.draw_line((40, 1394), (1040, 1394), color=BORDER, width=0.7)
    text(page, 40, 1404, f"{mode.title()}  /  {CATEGORY_LABELS[plan['category']]}  /  Garment {group_number:02d} of 38",
         11, fill=MUTED, max_width=760)
    text(page, 924, 1404, f"{plan['page']:02d} / 78", 12, bold=True, fill=MUTED)
    if plan['page'] in (14, 39, 53, 78):
        print('Rebuilt through page', plan['page'], flush=True)
metadata = doc.metadata
metadata.update(title='Siz3r - Original Photo, Garment, Result - Standard and Turbo',
                subject='Each try-on shows Original photo, Garment and Result. Standard first, Turbo second.')
doc.set_metadata(metadata)
doc.save(TARGET, garbage=4, deflate=True)
print('Saved revised PDF; checking all rows and image data.', flush=True)
check = fitz.open(TARGET)
assert len(check) == 78
assert image_fingerprints(check) == source_fingerprints
successes = failures = 0
for plan in plans:
    page = check[plan['page'] - 1]
    assert page.rect == fitz.Rect(0, 0, WIDTH, HEIGHT)
    if plan['kind'] != 'garment':
        continue
    page_text = page.get_text().replace('\u00a0', ' ').replace('\u00ad', '-')
    assert plan['title'] in page_text
    for label in ('ORIGINAL PHOTO', 'GARMENT', 'RESULT'):
        assert page_text.splitlines().count(label) == len(plan['rows'])
    assert any(link.get('page') == plan['compare_page'] - 1 for link in page.get_links())
    images = page.get_image_info()
    assert len(images) == 3 * len(plan['rows']) - sum(row['status'] == 'failed' for row in plan['rows'])
    image_offset = 0
    for row in plan['rows']:
        kinds = ['model', 'garment'] + (['result'] if row['status'] == 'success' else [])
        row_images = images[image_offset:image_offset + len(kinds)]
        for kind, image in zip(kinds, row_images):
            bounds = fitz.Rect(image['bbox'])
            expected = fitz.Rect(row['image_boxes'][kind])
            assert abs(bounds.y0 - expected.y0) < 0.01
            assert abs(bounds.y1 - expected.y1) < 0.01
            assert abs((bounds.x0 + bounds.x1) / 2 - (expected.x0 + expected.x1) / 2) < 0.01
            assert page.rect.contains(bounds)
            assert abs(bounds.width / bounds.height - image['width'] / image['height']) < 0.002
        assert [image['bbox'][0] for image in row_images] == sorted(image['bbox'][0] for image in row_images)
        image_offset += len(kinds)
        successes += row['status'] == 'success'
        failures += row['status'] == 'failed'
    assert page_text.count('No result') == sum(row['status'] == 'failed' for row in plan['rows'])
    for block in page.get_text('dict', flags=0)['blocks']:
        for line in block.get('lines', []):
            for span in line['spans']:
                assert page.rect.contains(fitz.Rect(span['bbox'])), span['text']
assert successes == 152 and failures == 4
assert [plan['mode'] for plan in plans] == ['standard'] * 39 + ['turbo'] * 39
for index in range(1, 39):
    first, second = plans[index], plans[index + 39]
    assert first['garment'] == second['garment']
    assert [row['model'] for row in first['rows']] == [row['model'] for row in second['rows']]
assert check.get_toc() == doc.get_toc()
indices = [0, 1, 14, 27, 31, 38, 39, 40, 53, 66, 70, 77]
sheet = Image.new('RGB', (1080, 1128), '#E3E8EF')
draw = ImageDraw.Draw(sheet)
font = ImageFont.truetype(FONT_FILES['Regular'], 12)
for i, index in enumerate(indices):
    pix = check[index].get_pixmap(matrix=fitz.Matrix(0.245, 0.245), alpha=False)
    image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    x, y = i % 4 * 270, i // 4 * 376
    sheet.paste(image, (x, y))
    draw.text((x + 5, y + 355), f'Page {index + 1}', font=font, fill='black')
sheet.save(OUT / 'triplets-overview.jpg', quality=92)
for index, name in [(1, 'three-models'), (14, 'one-model'), (27, 'timeout')]:
    check[index].get_pixmap(matrix=fitz.Matrix(0.6, 0.6), alpha=False).save(OUT / f'triplets-{name}.png')
manifest.update(pdf=str(TARGET), source_pdf=str(SOURCE), try_on_layout=['Original photo', 'Garment', 'Result'],
                repeated_garment_in_every_row=True, equal_photo_height_in_each_row=True,
                source_image_streams_preserved=True, successful_results=successes, timeout_placeholders=failures)
(OUT / 'presentation-manifest-triplets.json').write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding='ascii')
check.close()
doc.close()
print(json.dumps({key: value for key, value in manifest.items() if key != 'page_plan'}, indent=2))
print(f'PDF size: {TARGET.stat().st_size / 1024**2:.1f} MB')
