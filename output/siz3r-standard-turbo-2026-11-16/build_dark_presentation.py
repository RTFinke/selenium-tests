"""Full-page landscape try-ons on a dark background, grouped by garment and mode."""

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
TARGET = OUT / 'Siz3r_Standard_and_Turbo_Dark_Large_Photos.pdf'
WIDTH, HEIGHT = 1920, 1080
TOTAL_PAGES, SECTION_PAGES = 158, 79
FONT_FILES = {'Regular': r'C:\Windows\Fonts\arial.ttf', 'Bold': r'C:\Windows\Fonts\arialbd.ttf'}
FONTS = {name: fitz.Font(fontfile=path) for name, path in FONT_FILES.items()}


def rgb(value):
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


BLACK, WHITE, MUTED, LINE = map(rgb, ('080A0D', 'F2F5F8', 'ADB5BF', '272D35'))
GREEN, RED, ERROR_BG = map(rgb, ('35E9AE', 'FF9C95', '28161B'))
ACCENT = {'standard': rgb('94B9FF'), 'turbo': rgb('F5C16F')}
CATEGORY = {'upper': 'GÓRA', 'lower': 'DÓŁ', 'full': 'CAŁY STRÓJ'}


def text(page, x, y, value, size=16, bold=False, color=WHITE, max_width=None):
    name = 'Bold' if bold else 'Regular'
    if max_width:
        size = min(size, size * max_width / max(FONTS[name].text_length(value, fontsize=size), 1))
    assert size >= 10, (value, size)
    page.insert_text((x, y + size), value, fontsize=size, fontname=name, color=color)


def colorspace_fingerprint(document, xref):
    kind, value = document.xref_get_key(xref, 'ColorSpace')
    if kind != 'xref':
        return kind, value
    definition = document.xref_object(int(value.split()[0]), compressed=True)

    def resolve(match):
        target = int(match.group(1))
        if document.xref_is_stream(target):
            return 'stream-sha256:' + hashlib.sha256(document.xref_stream(target)).hexdigest()
        return document.xref_object(target, compressed=True)

    return kind, re.sub(r'(\d+) 0 R', resolve, definition)


def image_fingerprints(document):
    xrefs = {image[0] for page in document for image in page.get_images()}
    return {(document.xref_get_key(xref, 'Width'), document.xref_get_key(xref, 'Height'),
             colorspace_fingerprint(document, xref), document.xref_get_key(xref, 'BitsPerComponent'),
             document.xref_get_key(xref, 'Filter'),
             hashlib.sha256(document.xref_stream_raw(xref)).hexdigest()) for xref in xrefs}


manifest = json.loads((OUT / 'presentation-manifest.json').read_text(encoding='ascii'))
previous = json.loads((OUT / 'presentation-manifest-triplets.json').read_text(encoding='ascii'))
previous_heights = {(plan['mode'], plan['garment'], row['model']): row['image_height']
                    for plan in previous['page_plan'] if plan['kind'] == 'garment' for row in plan['rows']}
doc = fitz.open(SOURCE)
assert len(doc) == 78 and manifest['test_cases'] == 156
original_images = image_fingerprints(doc)
assert len(original_images) == 194

# Capture original image references before replacing the document's pages.
cases, cover_images = [], {}
for plan in manifest['page_plan']:
    page = doc[plan['page'] - 1]
    images = page.get_image_info(xrefs=True)
    if plan['kind'] == 'section':
        cover_images[plan['mode']] = images
        continue
    offset = 1
    garment_number = (plan['page'] - 2) % 39 + 1
    for row in plan['rows']:
        photos = {'model': images[offset], 'garment': images[0]}
        offset += 1
        if row['status'] == 'success':
            photos['result'] = images[offset]
            offset += 1
        cases.append({key: plan[key] for key in ('mode', 'category', 'gender', 'garment', 'title')} |
                     {key: row[key] for key in ('model', 'model_id', 'status', 'test_number', 'archive', 'metadata_member')} |
                     {'garment_number': garment_number, 'photos': photos})
    assert offset == len(images)
assert len(cases) == 156
assert [case['mode'] for case in cases] == ['standard'] * 78 + ['turbo'] * 78
for first, second in zip(cases[:78], cases[78:]):
    assert (first['garment'], first['model']) == (second['garment'], second['model'])

result_ratios = {}
for case in cases:
    if 'result' in case['photos']:
        image = case['photos']['result']
        result_ratios[(case['mode'], case['model'])] = image['width'] / image['height']

old_page_count = len(doc)
doc.set_toc([])
doc.new_page(width=WIDTH, height=HEIGHT)
doc.delete_pages(0, old_page_count - 1)
assert len(doc) == 1
audit_pages, links, toc = [], [], []


def new_page(index):
    page = doc[0] if index == 0 else doc.new_page(width=WIDTH, height=HEIGHT)
    for name, path in FONT_FILES.items():
        page.insert_font(fontname=name, fontfile=path)
    page.draw_rect(page.rect, color=None, fill=BLACK)
    return page


def cover(mode, index):
    page = new_page(index)
    accent = ACCENT[mode]
    successes = sum(case['status'] == 'success' for case in cases if case['mode'] == mode)
    text(page, 36, 28, 'Siz3r', 30, bold=True, color=GREEN)
    text(page, 36, 138, '01 / STANDARD' if mode == 'standard' else '02 / TURBO', 18, bold=True, color=accent)
    text(page, 31, 180, mode.title(), 82, bold=True)
    text(page, 36, 292, 'Wyniki przymiarek', 33)
    text(page, 36, 400, f'{successes} / 78', 65, bold=True)
    text(page, 39, 485, 'udanych generacji', 23, color=MUTED)
    text(page, 36, 558, '38 ubrań  /  4 modele', 23, bold=True)
    text(page, 36, 615, '1 przymiarka na stronie', 23, color=accent)
    text(page, 36, 677, 'Oryginalne zdjęcie', 24)
    text(page, 36, 715, '→ Ubranie → Wynik', 24)
    text(page, 36, 799, f'Liczba generacji bez wyniku: {78 - successes}',
         18, color=MUTED, max_width=455)
    other, target = ('Turbo', SECTION_PAGES) if mode == 'standard' else ('Standard', 0)
    jump = fitz.Rect(36, 912, 490, 976)
    page.draw_rect(jump, color=LINE, fill=rgb('14181F'), width=1)
    text(page, 55, 928, f'Przejdź do {other}  /  s. {target + 1}', 22, bold=True, color=accent)
    links.append((index, jump, target))
    text(page, 36, 1037, '16 listopada 2026', 14, color=MUTED)
    text(page, 1780, 1037, f'{index + 1} / {TOTAL_PAGES}', 14, color=MUTED)
    toc.append([1, mode.title(), index + 1])
    audit_pages.append({'page': index + 1, 'kind': 'section', 'mode': mode})


def case_page(case, case_index, page_index):
    page = new_page(page_index)
    mode, photos = case['mode'], case['photos']
    accent = ACCENT[mode]
    compare_index = page_index + (SECTION_PAGES if mode == 'standard' else -SECTION_PAGES)
    other_mode = 'Turbo' if mode == 'standard' else 'Standard'
    text(page, 24, 15, 'Siz3r', 21, bold=True, color=GREEN)
    text(page, 112, 17, mode.upper(), 18, bold=True, color=accent)
    title = f"G{case['garment_number']:02d} · {case['title']} · Model {case['model_id']}"
    text(page, 252, 13, title, 25, bold=True, max_width=1228)
    compare_box = fitz.Rect(1534, 9, 1896, 49)
    text(page, 1544, 18, f'Porównaj: {other_mode} → s. {compare_index + 1}', 17,
         color=accent, max_width=340)
    links.append((page_index, compare_box, compare_index))

    kinds = ('model', 'garment', 'result')
    ratios = [(photos[kind]['width'] / photos[kind]['height']) if kind in photos
              else result_ratios[(mode, case['model'])] for kind in kinds]
    image_height = min(962, (WIDTH - 48 - 2 * 18) / sum(ratios))
    content_width = sum(ratios) * image_height + 36
    x = (WIDTH - content_width) / 2
    y = 79 + (962 - image_height) / 2
    boxes, digests = {}, {}
    for kind, ratio, label in zip(kinds, ratios, ('ORYGINALNE ZDJĘCIE', 'UBRANIE', 'WYNIK')):
        box = fitz.Rect(x, y, x + ratio * image_height, y + image_height)
        text(page, x, 53, label, 15, bold=True, color=accent if kind == 'result' else MUTED)
        if kind in photos:
            info = photos[kind]
            page.insert_image(box, xref=info['xref'], keep_proportion=True)
            digests[kind] = info['digest'].hex()
        else:
            page.draw_rect(box, color=rgb('4B252C'), fill=ERROR_BG, width=1)
            text(page, x + 28, box.y0 + box.height / 2 - 55, 'Brak wyniku', 39, bold=True, color=RED,
                 max_width=box.width - 56)
            text(page, x + 28, box.y0 + box.height / 2 + 13, 'Limit czasu generacji: 105 s', 23, color=RED,
                 max_width=box.width - 56)
        boxes[kind] = list(box)
        x = box.x1 + 18
    text(page, 24, 1053, f"{CATEGORY[case['category']]}  /  {'DAMSKIE' if case['gender'] == 'women' else 'MĘSKIE'}",
         12, color=MUTED)
    text(page, 1780, 1053, f'{page_index + 1} / {TOTAL_PAGES}', 12, color=MUTED)
    original_height = previous_heights[(mode, case['garment'], case['model'])]
    scale_gain = (image_height / HEIGHT) / (original_height / 1440)
    assert scale_gain > 2.5
    audit_pages.append({key: case[key] for key in ('mode', 'category', 'gender', 'garment', 'title', 'model',
                                                   'model_id', 'status', 'garment_number', 'test_number', 'archive',
                                                   'metadata_member')} |
                       {'page': page_index + 1, 'kind': 'try_on', 'compare_page': compare_index + 1,
                        'image_boxes': boxes, 'image_digests': digests, 'image_height': image_height,
                        'height_gain_at_equal_page_height': scale_gain})


print('Captured 156 try-ons; building 158 dark landscape pages.', flush=True)
for mode_index, mode in enumerate(('standard', 'turbo')):
    start = mode_index * SECTION_PAGES
    cover(mode, start)
    selected = [case for case in cases if case['mode'] == mode]
    last_category, last_garment = None, None
    for case_index, case in enumerate(selected):
        index = start + case_index + 1
        if case['category'] != last_category:
            toc.append([2, CATEGORY[case['category']], index + 1])
            last_category = case['category']
        if case['garment'] != last_garment:
            toc.append([3, f"G{case['garment_number']:02d} / {case['title']}", index + 1])
            last_garment = case['garment']
        toc.append([4, 'Model ' + case['model_id'], index + 1])
        case_page(case, case_index, index)
    print(f'{mode.title()}: 78 large try-ons ready.', flush=True)
for index, box, target in links:
    doc[index].insert_link({'kind': fitz.LINK_GOTO, 'from': box, 'page': target})
doc.set_toc(toc)
doc.set_metadata({'title': 'Siz3r - Standard / Turbo - Duże zdjęcia, ciemny motyw', 'author': 'Siz3r',
                  'subject': 'Oryginalne zdjęcie, ubranie i wynik. Jedna przymiarka na poziomej stronie.',
                  'creator': 'Siz3r results presentation'})
doc.save(TARGET, garbage=4, deflate=True)
print('Saved PDF; checking image identity, ordering, links and dark backgrounds.', flush=True)

check = fitz.open(TARGET)
assert len(check) == TOTAL_PAGES
assert image_fingerprints(check) == original_images
assert [plan['mode'] for plan in audit_pages] == ['standard'] * SECTION_PAGES + ['turbo'] * SECTION_PAGES
successful = failed = 0
gains = []
for plan in audit_pages:
    page = check[plan['page'] - 1]
    assert page.rect == fitz.Rect(0, 0, WIDTH, HEIGHT)
    assert page.get_links()
    drawings = page.get_drawings()
    assert drawings and tuple(round(c * 255) for c in drawings[0]['fill']) == (8, 10, 13)
    page_text = page.get_text().replace('\u00a0', ' ').replace('\u00ad', '-')
    assert page_text.strip()
    for block in page.get_text('dict', flags=0)['blocks']:
        for line in block.get('lines', []):
            for span in line['spans']:
                assert page.rect.contains(fitz.Rect(span['bbox'])), span['text']
    if plan['kind'] == 'section':
        continue
    for label in ('ORYGINALNE ZDJĘCIE', 'UBRANIE', 'WYNIK'):
        assert page_text.splitlines().count(label) == 1
    assert any(link.get('page') == plan['compare_page'] - 1 for link in page.get_links())
    kinds = ['model', 'garment'] + (['result'] if plan['status'] == 'success' else [])
    actual = page.get_image_info(hashes=True)
    assert len(actual) == len(kinds)
    for kind, image in zip(kinds, actual):
        expected, bounds = fitz.Rect(plan['image_boxes'][kind]), fitz.Rect(image['bbox'])
        assert all(abs(a - b) < 0.02 for a, b in zip(expected, bounds))
        assert page.rect.contains(bounds)
        assert image['digest'].hex() == plan['image_digests'][kind]
        assert abs(bounds.width / bounds.height - image['width'] / image['height']) < 0.002
    successful += plan['status'] == 'success'
    failed += plan['status'] == 'failed'
    assert ('Brak wyniku' in page_text) == (plan['status'] == 'failed')
    gains.append(plan['height_gain_at_equal_page_height'])
assert successful == 152 and failed == 4
standard_cases = [p for p in audit_pages if p['kind'] == 'try_on' and p['mode'] == 'standard']
turbo_cases = [p for p in audit_pages if p['kind'] == 'try_on' and p['mode'] == 'turbo']
assert [(p['garment'], p['model']) for p in standard_cases] == [(p['garment'], p['model']) for p in turbo_cases]
for mode in ('standard', 'turbo'):
    grouped_pages = {}
    for plan in audit_pages:
        if plan['mode'] == mode and plan['kind'] == 'try_on':
            grouped_pages.setdefault(plan['garment'], []).append(plan['page'])
    assert len(grouped_pages) == 38
    for pages in grouped_pages.values():
        assert pages == list(range(min(pages), max(pages) + 1))

indices = [0, 1, 2, 3, 40, 53, 61, 79, 80, 81, 132, 157]
sheet = Image.new('RGB', (4 * 480, 3 * 294), '#111318')
draw = ImageDraw.Draw(sheet)
font = ImageFont.truetype(FONT_FILES['Regular'], 13)
for i, index in enumerate(indices):
    pix = check[index].get_pixmap(matrix=fitz.Matrix(0.25, 0.25), alpha=False)
    image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    x, y = i % 4 * 480, i // 4 * 294
    sheet.paste(image, (x, y))
    draw.text((x + 8, y + 275), f'Strona {index + 1}', font=font, fill='#D6DEE8')
sheet.save(OUT / 'dark-overview.jpg', quality=92)
for index, name in [(1, 'standard'), (53, 'timeout'), (80, 'turbo')]:
    check[index].get_pixmap(matrix=fitz.Matrix(0.65, 0.65), alpha=False).save(OUT / f'dark-{name}.png')
audit = {'pdf': str(TARGET), 'pages': TOTAL_PAGES, 'standard_pages': [1, 79], 'turbo_pages': [80, 158],
         'test_cases': 156, 'successful_results': successful, 'timeout_placeholders': failed,
         'garments_per_mode': 38, 'background': '#080A0D', 'one_try_on_per_page': True,
         'layout': ['Oryginalne zdjęcie', 'Ubranie', 'Wynik'], 'source_image_streams_preserved': True,
         'minimum_photo_height_gain': min(gains), 'maximum_photo_height_gain': max(gains),
         'page_plan': audit_pages}
(OUT / 'presentation-manifest-dark.json').write_text(json.dumps(audit, ensure_ascii=True, indent=2), encoding='ascii')
check.close()
doc.close()
print(json.dumps({key: value for key, value in audit.items() if key != 'page_plan'}, indent=2))
print(f'PDF size: {TARGET.stat().st_size / 1024**2:.1f} MB')
