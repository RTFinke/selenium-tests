from collections import Counter
import base64
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import hashlib
import json
import re
from urllib.parse import quote


SOURCE = Path(r"C:\Users\suici\Downloads\Siz3r_mail_ofertowy(4).original-2026-11-13.html")
OUTPUT = Path(__file__).parent
TARGET = OUTPUT / "Siz3r_mail_ofertowy_szablon.html"
MEASUREMENTS_IMAGE = Path(r"C:\Users\suici\Downloads\Polish fitting room measurement overlay.png")
original = SOURCE.read_text(encoding="utf-8")
updated = original


def replace_once(before, after):
    global updated
    assert updated.count(before) == 1, (before[:100], updated.count(before))
    updated = updated.replace(before, after, 1)


subject = "Jak ułatwić klientom wybór ubrania i rozmiaru?"
replace_once(
    "<title>Przymierzanie online dla sklepów odzieżowych</title>",
    f"<title>{subject}</title>",
)
replace_once(
    '<html lang="pl">',
    '<html lang="pl">\n'
    '<!-- '
    f'Temat wiadomości (ustaw osobno w programie pocztowym): {subject}\n'
    'Tytuł HTML nie ustawia automatycznie tematu wysyłanej wiadomości. -->',
)
replace_once(
    '    <h1 class="headline theme-ink" style="margin:27px 0 16px;color:#17181B;font-size:43px;line-height:45px;font-weight:900;letter-spacing:-.045em;text-transform:uppercase;">Przymierzanie online<br> <span style="color:#00633D;" class="theme-accent">w Twoim sklepie.</span></h1>',
    '    <h1 class="headline theme-ink" style="margin:27px 0 16px;color:#17181B;font-size:43px;line-height:45px;font-weight:900;letter-spacing:-.045em;text-transform:uppercase;">'
    'Pomóż klientom<br> <span style="color:#00633D;" class="theme-accent">wybrać pewniej.</span></h1>',
)
replace_once(
    'Pokaż klientom, jak wyglądają w\u00a0ubraniach z\u00a0Twojego sklepu. Wystarczy ich zdjęcie.',
    'Dzień dobry! Przy zakupach odzieży online trudno ocenić wygląd i rozmiar. '
    'Pomagamy sklepom takim jak Twój ułatwić klientom wybór dzięki Siz3r.',
)

cta_url = 'mailto:office@siz3r.com?subject=' + quote('5 minut rozmowy o przymierzaniu online', safe='')
updated, cta_count = re.subn(
    r'href="(?:https://siz3r\.com/pl/for-business|mailto:office@siz3r\.com\?subject=[^"]+)"',
    f'href="{escape(cta_url, quote=True)}"', updated,
)
assert cta_count == 4  # Both placements, including the Outlook VML buttons.
for label in ('Poznaj rozwiązanie', 'Umów prezentację'):
    assert updated.count(label) == 2
    updated = updated.replace(label, 'Porozmawiajmy')

updated, removed_buttons = re.subn(
    r'    <table role="presentation" cellspacing="0" cellpadding="0" width="206" align="left".*?</table>',
    '', updated, count=1, flags=re.DOTALL,
)
assert removed_buttons == 1
replace_once('max-width:435px;margin:0 0 21px;', 'max-width:435px;margin:0;')

for before, after in (
    ('>Efekt przymierzenia</td>', '>Przykład efektu Siz3r</td>'),
    ('>Jak to działa?</h2>', '>Trzy proste kroki</h2>'),
    ('Wybiera zdjęcie z galerii.', 'Z własnej galerii.'),
    ('Na karcie produktu wybiera opcję przymierzania.', 'Na karcie produktu.'),
    ('Ogląda ubranie na własnym zdjęciu.', 'Na swoim zdjęciu.'),
    ('>Prosto z karty produktu</h2>', '>Wymiary i rozmiar<br>z jednego zdjęcia</h2>'),
    ('Klient uruchamia narzędzie przy ubraniu, które ogląda. Może użyć tego samego zdjęcia, by przymierzyć kolejne produkty.',
     'Z jednego zdjęcia Siz3r odczytuje wymiary klienta i od razu poleca rozmiar każdego '
     'ubrania w Twoim sklepie. Zdjęcie pokazuje przykładowy pomiar.'),
    ('>Zobacz demo na ubraniach z\u00a0Twojego sklepu</h2>', '>Porozmawiajmy krótko</h2>'),
    ('Podczas krótkiej prezentacji pokażemy, jak działa przymierzanie online, i omówimy wdrożenie w\u00a0Twoim sklepie.',
     'Czy masz 5 minut w przyszłym tygodniu na telefon, żeby sprawdzić, czy Siz3r pasuje do Twojego sklepu?'),
):
    replace_once(before, after)

replace_once(
    '    <p style="margin:0;padding-top:15px;border-top:1px solid #DDDDE2;color:#50505A;font-size:12px;line-height:18px;" class="theme-rule theme-muted">',
    '    <p style="margin:0 0 16px;color:#50505A;font-size:14px;line-height:21px;" class="theme-muted">'
    'Pozdrawiamy,<br><strong style="color:#17181B;" class="theme-ink">Zespół Siz3r</strong></p>\n'
    '    <p style="margin:0;padding-top:15px;border-top:1px solid #DDDDE2;color:#50505A;font-size:12px;line-height:18px;" class="theme-rule theme-muted">',
)
replace_once(
    '<a href="mailto:office@siz3r.com" style="color:#00633D;" class="theme-accent">office@siz3r.com</a>',
    '<a href="mailto:office@siz3r.com" style="color:#00633D;" class="theme-accent">office@siz3r.com</a>'
    ' · <a href="https://siz3r.com/pl/for-business" style="color:#00633D;" class="theme-accent">siz3r.com</a>',
)

measurements_bytes = MEASUREMENTS_IMAGE.read_bytes()
assert measurements_bytes.startswith(b'\x89PNG\r\n\x1a\n')
measurements_data_url = 'data:image/png;base64,' + base64.b64encode(measurements_bytes).decode('ascii')
updated, replaced_images = re.subn(
    r'(<img src=")[^"]+(" width="222" alt=")Modelka w jasnoróżowej koszuli i jasnych spodniach po przymierzeniu online(")',
    lambda match: match.group(1) + measurements_data_url + match.group(2)
    + 'Przykład odczytu wymiarów sylwetki z jednego zdjęcia' + match.group(3),
    updated, count=1,
)
assert replaced_images == 1


# Typography and color values read from https://siz3r.com/pl/ on 2026-11-13.
for old_color, new_color in {
    '#F0F0F2': '#000000',
    '#09090B': '#000000',
    '#141416': '#0D0D0D',
    '#F5F5F6': '#0D0D0D',
    '#EFEFEF': '#0D0D0D',
    '#17181B': '#FFFFFF',
    '#50505A': '#CCCCCC',
    '#A7A7B0': '#CCCCCC',
    '#00E676': '#00D278',
    '#00633D': '#00D278',
    '#DDDDE2': '#222222',
    '#26262B': '#222222',
}.items():
    updated = updated.replace(old_color, new_color)
updated = updated.replace('bgcolor="#FFFFFF"', 'bgcolor="#000000"')
updated = updated.replace('background-color:#FFFFFF', 'background-color:#000000')
updated = updated.replace('color-scheme:light dark', 'color-scheme:dark')
updated = updated.replace('content="light dark"', 'content="dark"')
updated = updated.replace("'Marketing Inter',Inter,Arial,Helvetica,sans-serif", "'Figtree',Arial,Helvetica,sans-serif")
updated = updated.replace('font-weight:400;', 'font-weight:500;')
updated = updated.replace('font-weight:700;', 'font-weight:500;')
updated = updated.replace('letter-spacing:normal;', 'letter-spacing:-.02em;')
updated = updated.replace('font-size:29px !important; line-height:31px', 'font-size:29px !important; line-height:32px')
updated = updated.replace('font-size:25px !important; line-height:27px', 'font-size:25px !important; line-height:28px')


def heading_style(match):
    level = int(match.group(1))
    tag = match.group(0)
    weight = {1: 600, 2: 400, 3: 500}[level]
    spacing = '-.0314em' if level == 1 else '-.04em'
    tag = re.sub(r'font-weight:\d+;', f'font-weight:{weight};', tag)
    tag = re.sub(r'letter-spacing:[^;]+;', f'letter-spacing:{spacing};', tag)
    tag = tag.replace('text-transform:uppercase;', 'text-transform:none;')
    tag = tag.replace('line-height:45px;', 'line-height:47px;')
    tag = tag.replace('line-height:32px;', 'line-height:33px;')
    return tag


updated = re.sub(r'<h([123])\b[^>]*>', heading_style, updated)
updated = re.sub(
    r'(<table role="presentation" class="mail [^"]+"[^>]*style=")[^"]+("\s*>)',
    lambda match: match.group(0).replace("font-family:'Figtree',Arial,Helvetica,sans-serif;", "font-family:'Figtree',Arial,Helvetica,sans-serif;font-weight:500;"),
    updated, count=1,
)
replace_once(
    '<table role="presentation" width="100%" bgcolor="#00D278" style="width:100%;background-color:#00D278;">',
    '<table role="presentation" width="100%" bgcolor="#0D0D0D" class="theme-panel theme-rule" '
    'style="width:100%;background-color:#0D0D0D;border:1px solid #222222;">',
)
replace_once(
    'style="padding:30px 25px 29px;color:#000000;"',
    'style="padding:30px 25px 29px;color:#FFFFFF;"',
)
replace_once(
    '<h2 style="margin:0;color:#000000;',
    '<h2 style="margin:0;color:#FFFFFF;',
)
replace_once(
    '<p style="max-width:425px;margin:12px 0 18px;color:#000000;',
    '<p style="max-width:425px;margin:12px 0 18px;color:#CCCCCC;',
)
updated = re.sub(
    r'<a\b[^>]*class="mail-button"[^>]*>',
    lambda match: re.sub(
        r'background-color:#[0-9A-Fa-f]{6};color:#[0-9A-Fa-f]{6};',
        'background-color:#704B9B;color:#FFFFFF;', match.group(0),
    ), updated,
)
updated = re.sub(r'(<v:rect\b[^>]*fillcolor=")#[0-9A-Fa-f]{6}("[^>]*>)', r'\g<1>#704B9B\2', updated)
updated = updated.replace('<center style="color:#000000;', '<center style="color:#FFFFFF;')

font_folder = OUTPUT / 'brand-fonts'
font_faces = []
font_ranges = {
    'Figtree-latin-ext.woff2': 'U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C4,U+2113,U+2C60-2C7F,U+A720-A7FF',
    'Figtree-latin.woff2': 'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD',
}
for filename, unicode_range in font_ranges.items():
    font_data = (font_folder / filename).read_bytes()
    assert font_data[:4] == b'wOF2'
    encoded = base64.b64encode(font_data).decode('ascii')
    font_faces.append(
        "@font-face {font-family:'Figtree';font-style:normal;font-weight:300 900;font-display:swap;"
        f"src:url('data:font/woff2;base64,{encoded}') format('woff2');unicode-range:{unicode_range};}}"
    )
font_license = (font_folder / 'OFL.txt').read_text(encoding='utf-8').strip()
font_license = re.sub(r'-{2,}', lambda match: ' '.join(match.group()), font_license)
assert '--' not in font_license
updated, font_replacements = re.subn(
    r'<style>@font-face\s*\{.*?</style><!--Inter Variable,.*?-->',
    lambda _: '<style>' + '\n'.join(font_faces) + '</style>\n<!--\n' + font_license + '\n-->',
    updated, count=1, flags=re.DOTALL,
)
assert font_replacements == 1


# Use one fixed type scale across desktop and mobile: headings, body, and captions.
# Responsive rules change spacing and layout, without introducing more type sizes.
updated = re.sub(r'\s*\.headline\s*\{[^}]*\}', '', updated)
updated = re.sub(r'\s*\.section-title\s*\{[^}]*\}', '', updated)
updated = re.sub(r'\s*\.photo-label\s*\{[^}]*\}', '', updated)
updated = updated.replace(
    'body { margin:0; padding:0; -webkit-text-size-adjust:100%; }',
    "body { margin:0; padding:0; -webkit-text-size-adjust:100%; font-family:'Figtree',Arial,Helvetica,sans-serif; font-size:16px; line-height:24px; }",
)


def set_style_property(style, property_name, value):
    pattern = rf'(?<![-\w]){re.escape(property_name)}:[^;]+;?'
    if re.search(pattern, style):
        return re.sub(pattern, f'{property_name}:{value};', style)
    return style.rstrip(';') + f';{property_name}:{value};'


def simplify_typography(match):
    tag = match.group(1)
    element = match.group(0)
    style_match = re.search(r'\bstyle="([^"]*)"', element)
    if not style_match:
        return element
    style = style_match.group(1)
    classes_match = re.search(r'\bclass="([^"]*)"', element)
    classes = classes_match.group(1).split() if classes_match else []
    # Normalize incidental sizes such as image alternative text and arrow glyphs.
    style = re.sub(r'font-size:\d+px;', 'font-size:16px;', style)
    style = style.replace("font:900 22px/34px", "font:600 16px/34px")
    style = style.replace("font:700 16px/28px", "font:600 16px/24px")
    if tag in ('h1', 'h2'):
        for name, value in {'font-size': '32px', 'line-height': '38px', 'font-weight': '600', 'letter-spacing': '-.03em'}.items():
            style = set_style_property(style, name, value)
    elif tag == 'h3':
        for name, value in {'font-size': '16px', 'line-height': '24px', 'font-weight': '600'}.items():
            style = set_style_property(style, name, value)
    elif tag == 'p':
        is_company_footer = 'border-top:' in style
        style = set_style_property(style, 'font-size', '12px' if is_company_footer else '16px')
        style = set_style_property(style, 'line-height', '18px' if is_company_footer else '24px')
    elif tag == 'td' and 'photo-label' in classes:
        style = set_style_property(style, 'font-size', '12px')
        style = set_style_property(style, 'line-height', '18px')
    elif tag == 'td' and 'feature-gap' in classes:
        style = set_style_property(style, 'font-size', '12px')
    elif (tag == 'a' and 'mail-button' in classes) or tag == 'center':
        style = set_style_property(style, 'font-size', '16px')
        style = set_style_property(style, 'font-weight', '600')
    elif tag == 'table' and 'mail' in classes:
        style = set_style_property(style, 'font-size', '16px')
        style = set_style_property(style, 'line-height', '24px')
    return element[:style_match.start(1)] + style + element[style_match.end(1):]


updated = re.sub(r'<(h[123]|p|a|td|img|center|table|span)\b[^>]*>', simplify_typography, updated)
assert set(re.findall(r'font-size:\s*(\d+)px', updated)) == {'12', '16', '32'}


class InspectHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.counts = Counter()
        self.assets = []
        self.ctas = []
        self.words = []
        self.stack = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.counts[tag] += 1
        if tag == 'img':
            self.assets.append(attrs['src'])
        if tag == 'a' and 'mail-button' in attrs.get('class', '').split():
            self.ctas.append(attrs['href'])
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(tag)
        if tag in {'head', 'style', 'title'}:
            self.skip += 1

    def handle_endtag(self, tag):
        assert self.stack and self.stack[-1] == tag, (tag, self.stack[-3:])
        self.stack.pop()
        if tag in {'head', 'style', 'title'}:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.words.append(data)


before = InspectHTML()
before.feed(original)
after = InspectHTML()
after.feed(updated)
assert not before.stack and not after.stack
for tag in ('table', 'tr', 'td', 'img', 'h1', 'h2', 'h3'):
    removed_count = 1 if tag in ('table', 'tr', 'td') else 0
    assert before.counts[tag] - removed_count == after.counts[tag], tag
assert before.assets[:-1] == after.assets[:-1]
assert after.assets[-1] == measurements_data_url
asset_pattern = r'data:[^;"\s]+;base64,[A-Za-z0-9+/=]+'
assert len(re.findall(r'data:font/woff2;base64,', updated)) == 2
assert len(after.ctas) == 1 and len(set(after.ctas)) == 1
assert updated.count(cta_url) == 2  # One visible placement and its Outlook VML equivalent.
assert '\ufffd' not in updated
assert 'https://siz3r.com/pl/for-business' in updated
main_copy = ' '.join(after.words).split('Siz3r Sp. z o.o.')[0]
assert not re.search(r'\[[^\]]+\]', main_copy)
assert main_copy.count('Dzień dobry') == 1
intro_markup = re.search(r'<td class="intro[^\"]*"[^>]*>(.*?)</td>', updated, re.DOTALL).group(1)
assert intro_markup.index('<h1') < intro_markup.index('<p')
assert 'Marketing Inter' not in updated
assert 'Inter Variable' not in updated
word_count = len(re.findall(r'[^\W_]+(?:[-’][^\W_]+)*', main_copy, flags=re.UNICODE))
assert 80 <= word_count <= 100, word_count

OUTPUT.mkdir(parents=True, exist_ok=True)
TARGET.write_text(updated, encoding='utf-8', newline='\n')
report = {
    'output': str(TARGET),
    'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    'output_sha256': hashlib.sha256(TARGET.read_bytes()).hexdigest(),
    'subject': subject,
    'body_word_count_excluding_company_footer': word_count,
    'preserved_structural_elements': {tag: after.counts[tag] for tag in ('table', 'tr', 'td', 'img', 'h1', 'h2', 'h3')},
    'preserved_embedded_images': len(after.assets) - 1,
    'measurements_image': str(MEASUREMENTS_IMAGE),
    'measurements_image_sha256': hashlib.sha256(measurements_bytes).hexdigest(),
    'embedded_font_family': 'Figtree',
    'font_weights': {'h1': 600, 'h2': 600, 'h3': 600, 'body': 500},
    'font_sizes_px': {'headings': 32, 'body_and_button': 16, 'captions_and_company_footer': 12},
    'brand_reference': 'https://siz3r.com/pl/',
    'brand_palette': {'background': '#000000', 'panel': '#0D0D0D', 'headings': '#FFFFFF', 'body': '#CCCCCC', 'green': '#00D278', 'button': '#704B9B', 'border': '#222222'},
    'cta_placements': len(after.ctas),
    'distinct_cta_destinations': len(set(after.ctas)),
    'outlook_cta_destinations_checked': True,
    'placeholders': sorted(set(re.findall(r'\[(?!if|endif)[^\]\n]+\]', main_copy))),
}
(OUTPUT / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
