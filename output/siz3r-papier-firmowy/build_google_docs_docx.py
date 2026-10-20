"""Create current SIZ3R templates as simple, editable DOCX files.

Uses standard paragraphs, automatic pagination, inline PNG and native header /
footer tables. It deliberately uses Arial rather than a local-only font.
Google Docs conversion still needs to be checked in the user's account.
"""

from pathlib import Path
from datetime import datetime, timezone
import ast
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "google-docs"
OUT.mkdir(exist_ok=True)
BASE = ROOT / "Siz3r_Papier_firmowy.docx"
LOGO = Path(r"C:\Users\suici\Downloads\logoSiz3r.png").read_bytes()

source = ast.parse((ROOT / "build_refined_pdf.py").read_text(encoding="utf-8"))
QUESTIONS = next(ast.literal_eval(item.value) for item in source.body
                 if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "QUESTIONS" for t in item.targets))

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WIDTH = 9298
GREEN, INK, BODY, MUTED, RULE = "00D278", "17211D", "35413B", "69766F", "DDE5E0"


def run(text="", bold=False, color=None):
    props = ("<w:b/>" if bold else "") + (f'<w:color w:val="{color}"/>' if color else "")
    return f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def p(text="", style="Body", *, raw=False, before=0, after=0, page_break=False, align=None):
    props = f'<w:pStyle w:val="{style}"/><w:spacing w:before="{round(before*20)}" w:after="{round(after*20)}"/>'
    if page_break:
        props += "<w:pageBreakBefore/>"
    if align:
        props += f'<w:jc w:val="{align}"/>'
    return f'<w:p><w:pPr>{props}</w:pPr>{text if raw else run(text)}</w:p>'


def blanks(points=55):
    # A single editable paragraph reserves space through paragraph spacing.
    # Repeated empty paragraphs can overflow onto a blank page after import.
    return p(style="Answer", before=8, after=max(0, points-13.5)+8)


def section(number, spaces, before=0):
    title, questions = QUESTIONS[number-1]
    title_runs = run(f"{number:02d}", bold=True, color=GREEN) + '<w:r><w:tab/></w:r>' + run(title, bold=True)
    body = p(title_runs, "Heading2", raw=True, before=before, after=11)
    for question, space in zip(questions, spaces):
        body += p(question, "Question") + blanks(space)
    return body


def cell_table(left, right, widths, *, edge):
    cells = ''.join(
        f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr>{content}</w:tc>'
        for content, width in zip((left, right), widths)
    )
    border = f'<w:tblBorders><w:{edge} w:val="single" w:sz="4" w:color="{RULE}"/></w:tblBorders>'
    top, bottom = (220, 0) if edge == "top" else (0, 220)
    return (
        f'<w:tbl><w:tblPr><w:tblW w:w="{WIDTH}" w:type="dxa"/><w:tblLayout w:type="fixed"/>'
        f'{border}<w:tblCellMar><w:top w:w="{top}" w:type="dxa"/><w:left w:w="0" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tblCellMar></w:tblPr>'
        f'<w:tblGrid>{"".join(f"<w:gridCol w:w=\"{width}\"/>" for width in widths)}</w:tblGrid>'
        f'<w:tr><w:trPr><w:cantSplit/></w:trPr>{cells}</w:tr></w:tbl>'
    )


def style(name, size, line, *, font_bold=False, color=BODY, indent=False, keep=False, heading=False):
    properties = f'<w:spacing w:after="0" w:before="0" w:line="{round(line*20)}" w:lineRule="exact"/>'
    if indent:
        properties += '<w:ind w:left="540"/>'
    if keep:
        properties += "<w:keepNext/>"
    if heading:
        properties += '<w:ind w:left="540" w:hanging="540"/><w:tabs><w:tab w:val="left" w:pos="540"/></w:tabs><w:outlineLvl w:val="1"/>'
    half_points = round(size*2)
    return (
        f'<w:style w:type="paragraph" w:styleId="{name}"><w:name w:val="{name}"/><w:basedOn w:val="Normal"/>'
        f'<w:pPr>{properties}<w:widowControl/></w:pPr><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/>'
        f'<w:color w:val="{color}"/><w:sz w:val="{half_points}"/><w:szCs w:val="{half_points}"/>'
        f'{"<w:b/>" if font_bold else ""}</w:rPr></w:style>'
    )


STYLES = f'''<w:styles {NS}>
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/>
<w:sz w:val="22"/><w:color w:val="{BODY}"/><w:lang w:val="pl-PL"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
{style('Body',10.5,15.3)}
{style('Title',20.5,27,font_bold=True,color=INK,keep=True)}
{style('Heading2',12,17,font_bold=True,color=INK,keep=True,heading=True)}
{style('Question',11,15.2,indent=True,keep=True)}
{style('Answer',11,13.5,indent=True)}
{style('Signature',10.5,15.3,indent=True)}
{style('Label',8,12,font_bold=True,color=MUTED,keep=True)}
{style('Name',11,16,font_bold=True,color=INK,keep=True)}
{style('Meta',9.5,14,color=MUTED,keep=True)}
{style('Header',9,14,color=MUTED)}
{style('HeaderLogo',9,32,color=MUTED)}
{style('Footer',8.5,14)}
{style('EndTable',1,1)}
</w:styles>'''

LOGO_DRAWING = '''<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">
<wp:extent cx="1512000" cy="354375"/><wp:docPr id="1" name="Logo Siz3r" descr="Logo dostarczone przez użytkownika"/>
<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>
<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>
<pic:nvPicPr><pic:cNvPr id="0" name="logoSiz3r.png"/><pic:cNvPicPr/></pic:nvPicPr>
<pic:blipFill><a:blip r:embed="rIdLogo"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1512000" cy="354375"/></a:xfrm>
<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>
</wp:inline></w:drawing></w:r>'''

HEADER = f'<w:hdr {NS}>' + cell_table(
    p(LOGO_DRAWING, "HeaderLogo", raw=True),
    p(run("siz3r.com", bold=True, color=INK), "Header", raw=True, align="right") + p("office@siz3r.com", "Header", align="right"),
    [5579, 3719], edge="bottom",
) + p(style="EndTable") + '</w:hdr>'


def footer(total, numbered):
    left = p(run("Siz3r Sp. z o.o.", bold=True) + run("    ul. Stanisławowska 47, 54-611 Wrocław"), "Footer", raw=True)
    left += p("NIP: 894-313-42-44    KRS: 0000754380    REGON: 381639043", "Footer")
    right = p(style="Footer", align="right")
    if numbered:
        fields = '<w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple>' + run(" / ") + f'<w:fldSimple w:instr="NUMPAGES"><w:r><w:t>{total}</w:t></w:r></w:fldSimple>'
        right = p(fields, "Footer", raw=True, align="right")
    right += p(style="Footer", align="right")
    return f'<w:ftr {NS}>' + cell_table(left, right, [7903, 1395], edge="top") + p(style="EndTable") + '</w:ftr>'


def aio_body():
    value = p("ADRESAT", "Label", after=5)
    value += p("Bartłomiej Fitas", "Name") + p("Kierownik działu e-commerce", "Meta") + p("sklep.aio.com.pl", "Meta", after=27)
    value += p("Wirtualna przymierzalnia", "Title", after=7)
    value += p("Odpowiedź na zapytanie · sklep.aio.com.pl", "Meta", after=21)
    value += p("Szanowny Panie Bartłomieju,", after=8)
    value += p("dziękujemy za zainteresowanie rozwiązaniem Siz3r. Poniżej przedstawiamy odpowiedzi na pytania dotyczące wdrożenia wirtualnej przymierzalni w Państwa sklepie.", after=25)
    value += section(1, [44,44]) + section(2, [52], before=9)
    value += section(3, [62,62], before=18) + section(4, [62,62], before=18)
    value += section(5, [50], before=18) + section(6, [62], before=13) + section(7, [50], before=13)
    value += p("Z poważaniem,", "Signature", before=13, after=35)
    return value


def build(name, body, title, *, aio=False):
    with zipfile.ZipFile(BASE) as original:
        parts = {key: original.read(key) for key in original.namelist()}
    section_xml = '''<w:sectPr><w:headerReference w:type="default" r:id="rIdHeader"/>
    <w:footerReference w:type="default" r:id="rIdFooter"/><w:pgSz w:w="11906" w:h="16838"/>
    <w:pgMar w:top="2660" w:right="1304" w:bottom="1860" w:left="1304" w:header="1134" w:footer="800"/>
    <w:cols w:space="708"/></w:sectPr>'''
    xml_parts = {
        'word/document.xml': f'<w:document {NS}><w:body>{body}{section_xml}</w:body></w:document>',
        'word/styles.xml': STYLES,
        'word/header1.xml': HEADER,
        'word/footer1.xml': footer(3 if aio else 1,aio),
        'word/settings.xml': f'<w:settings {NS}><w:defaultTabStop w:val="720"/><w:updateFields w:val="true"/><w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>',
    }
    for key, text in xml_parts.items():
        ET.fromstring(text)
        parts[key] = text.encode('utf-8')
    core = ET.fromstring(parts['docProps/core.xml'])
    dc = '{http://purl.org/dc/elements/1.1/}'
    core.find(dc+'title').text = title
    core.find(dc+'description').text = 'Edytowalny szablon DOCX do importu do Dokumentów Google.'
    core.find('{http://purl.org/dc/terms/}created').text = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    parts['docProps/core.xml'] = ET.tostring(core,encoding='utf-8',xml_declaration=True)
    parts['word/media/siz3r-logo.png'] = LOGO
    target = OUT / name
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as result:
        for key, data in parts.items():
            result.writestr(key,data)
    with zipfile.ZipFile(target) as result:
        assert result.testzip() is None
        for key in result.namelist():
            if key.endswith(('.xml','.rels')):
                ET.fromstring(result.read(key))
        document = ET.fromstring(result.read('word/document.xml'))
        all_text = ' '.join(' '.join(ET.fromstring(result.read(key)).itertext()) for key in xml_parts)
        assert 'Kapitał zakładowy' not in all_text and '[' not in all_text and 'Wpisz' not in all_text
        assert result.read('word/media/siz3r-logo.png') == LOGO
        assert b'wp:anchor' not in result.read('word/header1.xml')
        assert b'Segoe' not in result.read('word/styles.xml')
        assert all(b'TargetMode="External"' not in result.read(key) for key in result.namelist() if key.endswith('.rels'))
        if aio:
            paragraph_items = document.findall('.//'+W+'body/'+W+'p')
            question_items = [item for item in paragraph_items if item.find(W+'pPr/'+W+'pStyle').get(W+'val')=='Question']
            assert len(question_items)==10
            assert [''.join(item.itertext()) for item in question_items] == [q for _,values in QUESTIONS for q in values]
            assert not document.findall('.//'+W+'pageBreakBefore')
            assert not document.findall('.//'+W+'br')
            answer_items = [item for item in paragraph_items if item.find(W+'pPr/'+W+'pStyle').get(W+'val')=='Answer']
            assert len(answer_items)==10 and all(not ''.join(item.itertext()) for item in answer_items)
            assert ''.join(paragraph_items[-1].itertext()) == 'Z poważaniem,'
    print(f'OK: {target.name}; embedded original logo, native headers/footers, editable paragraphs, no placeholders or capital amount.')


if __name__ == '__main__':
    build('Siz3r_AIO_Google_Docs.docx',aio_body(),'Siz3r — odpowiedź na zapytanie AIO',aio=True)
    build('Siz3r_Papier_firmowy_Google_Docs.docx',p(),'Siz3r — papier firmowy do Dokumentów Google')
    (OUT/'Jak_otworzyc_w_Google_Docs.txt').write_text('''SIZ3R — EDYTOWALNY SZABLON DO DOKUMENTÓW GOOGLE

1. Prześlij plik DOCX na Dysk Google.
2. Kliknij go prawym przyciskiem: Otwórz w > Dokumenty Google.
3. W menu Plik wybierz Zapisz jako Dokumenty Google, aby utworzyć natywną kopię.
4. W Plik > Ustawienia strony używaj trybu Z podziałem na strony i formatu A4.
5. Wpisuj odpowiedzi w pustym akapicie pod każdym pytaniem. Dokument ma automatyczne podziały stron; nie zawiera ręcznych podziałów ani serii pustych akapitów.
6. Zachowaj plik jako szablon. Każdy nowy dokument twórz przez Plik > Utwórz kopię.
7. Przed wysłaniem sprawdź podziały stron i numerację. Gotowy dokument pobierz jako PDF z Google Docs.

Plik zawiera nowe logo wskazane przez użytkownika, bieżącą stopkę bez kapitału zakładowego, edytowalne pytania i całkowicie puste miejsca na odpowiedzi. Czcionka Arial ogranicza ryzyko podmiany kroju podczas importu. Nagłówek i stopka są natywnymi elementami DOCX.

DOCX został sprawdzony lokalnie. Konwersja i wygląd na koncie Google użytkownika nie zostały jeszcze sprawdzone; bez takiego sprawdzenia nie gwarantujemy identycznego układu w Google Docs.

Pomoc Google:
https://support.google.com/docs/answer/9406611?hl=pl
https://support.google.com/docs/answer/11528737?hl=pl
''',encoding='utf-8-sig')
