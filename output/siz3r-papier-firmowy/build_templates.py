"""Build editable SIZ3R letterheads using standard WordprocessingML.

The original logo is extracted intact from the existing AIO presentation.
The finished DOCX files contain ordinary text, styles, tables, headers and
footers; they have no macros, external images, floating shapes or text boxes.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
import zipfile
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ASSETS = OUT / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / ".tmp-pdf-tools"))
import pymupdf as fitz

LOGO_SOURCE = ROOT / "output/aio/Siz3r_Wyniki_AIO.pdf"
with fitz.open(LOGO_SOURCE) as pdf:
    item = pdf[0].get_images()[0]
    base = fitz.Pixmap(pdf, item[0])
    logo = fitz.Pixmap(base, fitz.Pixmap(pdf, item[1])) if item[1] else base
    logo.save(ASSETS / "siz3r-logo.png")

GREEN = "00D278"
INK = "14171B"
GRAY = "65717D"
LIGHT = "E4E8E6"
NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
)


def run(text, *, bold=False, color=None, size=None, italic=False):
    props = []
    if bold:
        props.append("<w:b/>")
    if italic:
        props.append("<w:i/>")
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    if size:
        props.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    text_xml = "<w:br/>".join(
        f'<w:t xml:space="preserve">{escape(line)}</w:t>' for line in text.split("\n")
    )
    return f"<w:r>{rpr}{text_xml}</w:r>"


def p(text="", *, style="Normal", align=None, before=None, after=None, keep=False,
      break_before=False, border=None, raw=False):
    props = [f'<w:pStyle w:val="{style}"/>']
    if align:
        props.append(f'<w:jc w:val="{align}"/>')
    if before is not None or after is not None:
        spacing = []
        if before is not None:
            spacing.append(f'w:before="{before}"')
        if after is not None:
            spacing.append(f'w:after="{after}"')
        props.append(f"<w:spacing {' '.join(spacing)}/>")
    if keep:
        props.append("<w:keepNext/>")
    if break_before:
        props.append("<w:pageBreakBefore/>")
    if border:
        props.append(
            f'<w:pBdr><w:bottom w:val="single" w:sz="8" '
            f'w:space="10" w:color="{border}"/></w:pBdr>'
        )
    return f"<w:p><w:pPr>{''.join(props)}</w:pPr>{text if raw else run(text)}</w:p>"


def heading(number, title, *, new_page=False):
    return p(
        run(f"{number:02d}  ", bold=True, color=GREEN) + run(title, bold=True),
        style="Heading2", raw=True, break_before=new_page,
    )


def prompt(text):
    return p(text, style="Prompt")


def placeholder(text):
    return p(f"[{text}]", style="Placeholder")


def table(rows, widths, *, header=False):
    total = sum(widths)
    borders = (
        f'<w:tblBorders><w:top w:val="single" w:sz="4" w:color="{LIGHT}"/>'
        f'<w:left w:val="single" w:sz="4" w:color="{LIGHT}"/>'
        f'<w:bottom w:val="single" w:sz="4" w:color="{LIGHT}"/>'
        f'<w:right w:val="single" w:sz="4" w:color="{LIGHT}"/>'
        f'<w:insideH w:val="single" w:sz="4" w:color="{LIGHT}"/>'
        f'<w:insideV w:val="single" w:sz="4" w:color="{LIGHT}"/></w:tblBorders>'
    ) if not header else ""
    margin = 0 if header else 100
    properties = (
        f'<w:tblW w:w="{total}" w:type="dxa"/>'
        '<w:tblLayout w:type="fixed"/>' + borders +
        f'<w:tblCellMar><w:top w:w="{margin}" w:type="dxa"/>'
        f'<w:left w:w="{margin}" w:type="dxa"/>'
        f'<w:bottom w:w="{margin}" w:type="dxa"/>'
        f'<w:right w:w="{margin}" w:type="dxa"/></w:tblCellMar>'
    )
    body = []
    for row_i, row in enumerate(rows):
        cells = []
        for col_i, text in enumerate(row):
            shade = "" if header or row_i else '<w:shd w:val="clear" w:fill="F0F8F3"/>'
            value = text if header else p(
                run(text, bold=(row_i == 0)), style="TableText", raw=True, after=0,
            )
            cells.append(
                f'<w:tc><w:tcPr><w:tcW w:w="{widths[col_i]}" w:type="dxa"/>'
                f'<w:vAlign w:val="center"/>{shade}</w:tcPr>{value}</w:tc>'
            )
        row_props = '<w:trPr><w:cantSplit/>' + ('<w:tblHeader/>' if not header and row_i == 0 else '') + '</w:trPr>'
        body.append(f"<w:tr>{row_props}{''.join(cells)}</w:tr>")
    return (
        f'<w:tbl><w:tblPr>{properties}</w:tblPr><w:tblGrid>' +
        ''.join(f'<w:gridCol w:w="{width}"/>' for width in widths) +
        f"</w:tblGrid>{''.join(body)}</w:tbl>"
    )


STYLES = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {NS}>
  <w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/>
    <w:color w:val="{INK}"/><w:sz w:val="21"/><w:szCs w:val="21"/><w:lang w:val="pl-PL"/>
  </w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/>
    <w:widowControl/></w:pPr></w:pPrDefault></w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
    <w:pPr><w:keepNext/><w:spacing w:before="100" w:after="180" w:line="264" w:lineRule="auto"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="42"/><w:szCs w:val="42"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
    <w:pPr><w:keepNext/><w:keepLines/><w:outlineLvl w:val="1"/><w:spacing w:before="220" w:after="65"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="23"/><w:szCs w:val="23"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Prompt"><w:name w:val="Siz3r - Pytanie"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:keepNext/><w:spacing w:after="65" w:line="250" w:lineRule="auto"/></w:pPr>
    <w:rPr><w:color w:val="{GRAY}"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Placeholder"><w:name w:val="Siz3r - Do uzupelnienia"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:after="80" w:line="264" w:lineRule="auto"/></w:pPr>
    <w:rPr><w:color w:val="{INK}"/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Meta"><w:name w:val="Siz3r - Metadane"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:after="45" w:line="240" w:lineRule="auto"/></w:pPr>
    <w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Label"><w:name w:val="Siz3r - Etykieta"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:keepNext/><w:spacing w:before="140" w:after="45"/></w:pPr>
    <w:rPr><w:color w:val="{GRAY}"/><w:b/><w:sz w:val="15"/><w:szCs w:val="15"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Header"><w:name w:val="header"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>
    <w:rPr><w:color w:val="{GRAY}"/><w:sz w:val="17"/><w:szCs w:val="17"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:tabs><w:tab w:val="right" w:pos="9690"/></w:tabs><w:spacing w:after="35" w:line="240" w:lineRule="auto"/></w:pPr>
    <w:rPr><w:color w:val="{GRAY}"/><w:sz w:val="14"/><w:szCs w:val="14"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="TableText"><w:name w:val="Siz3r - Tabela"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>
    <w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
</w:styles>'''

LOGO_DRAWING = '''<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">
<wp:extent cx="1476000" cy="345630"/><wp:docPr id="1" name="Logo Siz3r" descr="Oryginalny zielony logotyp Siz3r"/>
<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>
<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
<pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="siz3r-logo.png"/><pic:cNvPicPr/></pic:nvPicPr>
<pic:blipFill><a:blip r:embed="rIdLogo"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1476000" cy="345630"/></a:xfrm>
<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>
</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>'''

HEADER = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr {NS}>{table([(p(LOGO_DRAWING, style="Header", raw=True), p("siz3r.com\noffice@siz3r.com", style="Header", align="right"))], [5250, 4440], header=True)}
{p("", style="Header", before=90, after=0, border=GREEN)}</w:hdr>'''

FOOTER = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr {NS}>
{p(run("Siz3r Sp. z o.o.", bold=True) + run("  |  ul. Stanisławowska 47, 54-611 Wrocław") + '<w:r><w:tab/></w:r>' + '<w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple>', style="Footer", raw=True, border=LIGHT, after=50)}
{p("NIP: 894-313-42-44  |  KRS: 0000754380  |  REGON: 381639043", style="Footer")}
</w:ftr>'''


def recipient(name, role, company):
    return (
        p("[Miejscowość], [data]", style="Meta", align="right", after=180) +
        p("ADRESAT", style="Label", before=0) +
        p(run(name, bold=True) + run(f"\n{role}\n{company}"), style="Meta", raw=True, after=150)
    )


def signature():
    return (
        p("Z poważaniem,", before=200, after=100) +
        p(run("[Imię i nazwisko]", bold=True) + run("\n[Stanowisko]  |  Siz3r\n[E-mail]  |  [Telefon]"), style="Meta", raw=True)
    )


GENERAL = (
    recipient("[Imię i nazwisko adresata]", "[Stanowisko]", "[Firma / adres]") +
    p("KORESPONDENCJA FIRMOWA", style="Label") +
    p("[Temat pisma]", style="Title") +
    p("[Szanowna Pani / Szanowny Panie],", before=140, after=140) +
    placeholder("Wstęp: podziękowanie za kontakt i krótki opis sprawy.") +
    heading(1, "[Nagłówek sekcji — opcjonalnie]") +
    placeholder("Treść pisma. Zastąp ten tekst własną odpowiedzią. Dodawaj kolejne akapity lub sekcje według potrzeb.") +
    placeholder("Zakończenie: proponowany kolejny krok, termin lub informacje kontaktowe.") +
    signature()
)

AIO = (
    recipient("Bartłomiej Fitas", "Kierownik działu e-commerce", "sklep.aio.com.pl") +
    p("ODPOWIEDŹ NA ZAPYTANIE", style="Label") +
    p("Wirtualna przymierzalnia\ndla sklep.aio.com.pl", style="Title") +
    p("Szanowny Panie Bartłomieju,", after=100) +
    p("dziękujemy za zainteresowanie rozwiązaniem Siz3r. Poniżej przedstawiamy odpowiedzi na pytania dotyczące możliwości wdrożenia wirtualnej przymierzalni w Państwa sklepie.", after=100) +
    heading(1, "Integracja z AtomStore i kwestie techniczne") +
    prompt("Czy posiadają Państwo gotowy moduł / integrację z silnikiem AtomStore (np. w oparciu o API / widget JS)?") +
    placeholder("Wpisz odpowiedź.") +
    prompt("Jak wdrożenie Państwa rozwiązania wpływa na wydajność i czas ładowania karty produktu?") +
    placeholder("Wpisz odpowiedź.") +
    heading(2, "Wymagania dotyczące materiałów produktowych") +
    prompt("Jakich materiałów potrzebują Państwo z naszej strony do digitalizacji asortymentu? Czy wystarczą standardowe zdjęcia produktowe, czy wymagane są specjalne sesje lub pliki 3D?") +
    placeholder("Wpisz odpowiedź.") +
    heading(3, "Specyfika asortymentu BHP") +
    prompt("Jak Państwa algorytmy radzą sobie ze specyficznym asortymentem (ciężkie kurtki robocze, obuwie bezpieczne, rękawice, elementy odblaskowe)?") +
    placeholder("Wpisz odpowiedź.") +
    prompt("Czy AI zachowuje wierne odwzorowanie faktury materiału i detali ubrań?") +
    placeholder("Wpisz odpowiedź.") +
    heading(4, "Ścieżka użytkownika (UX) i RODO", new_page=True) +
    prompt("Czy klient końcowy do skorzystania z przymierzalni w naszym sklepie musi zakładać konto w Państwa zewnętrznym serwisie, czy przymiarka może odbywać się bezrejestracyjnie?") +
    placeholder("Wpisz odpowiedź.") +
    prompt("Jak z formalnego punktu widzenia rozwiązana jest kwestia przetwarzania wizerunku użytkownika i zgód RODO (kto jest administratorem danych przesyłanych zdjęć)?") +
    placeholder("Wpisz odpowiedź.") +
    heading(5, "Funkcjonalność (Wizualizacja vs. Dobór rozmiaru)") +
    prompt("Czy narzędzie oferuje jedynie wizualizację wyglądu ubrania na sylwetce, czy sugeruje również konkretny rozmiar (np. M, L, XL) na podstawie wprowadzonych wymiarów klienta?") +
    placeholder("Wpisz odpowiedź.") +
    heading(6, "Model biznesowy i koszty") +
    prompt("Jak wygląda struktura cennika? Interesuje nas koszt przygotowania 1 produktu (digitalizacja), ewentualna opłata za wdrożenie techniczne oraz model bieżących rozliczeń (abonament / opłata za pojedyncze wygenerowane przymierzenie / inne).") +
    placeholder("Wpisz odpowiedź.") +
    heading(7, "Próbka / Pilotaż") +
    prompt("Czy istnieje możliwość bezpłatnego przetestowania narzędzia i przygotowania próbki wizualizacji na podstawie 2–3 przesłanych przez nas produktów?") +
    placeholder("Wpisz odpowiedź.") +
    p("[Opcjonalnie: kolejny krok oraz linki do materiałów informacyjnych lub oferty.]", style="Placeholder", before=100) +
    signature()
)


def make_docx(filename, body, title):
    sect = '''<w:sectPr><w:headerReference w:type="default" r:id="rIdHeader"/>
      <w:footerReference w:type="default" r:id="rIdFooter"/>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="2150" w:right="1108" w:bottom="1550" w:left="1108" w:header="600" w:footer="570"/>
      <w:cols w:space="708"/></w:sectPr>'''
    document = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS}><w:body>{body}{sect}</w:body></w:document>'
    relns = "http://schemas.openxmlformats.org/package/2006/relationships"
    reltype = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
    docrels = (
        f'<Relationships xmlns="{relns}">' +
        ''.join(f'<Relationship Id="{rid}" Type="{reltype}{typ}" Target="{target}"/>' for rid, typ, target in [
            ("rIdStyles", "styles", "styles.xml"),
            ("rIdHeader", "header", "header1.xml"),
            ("rIdFooter", "footer", "footer1.xml"),
            ("rIdSettings", "settings", "settings.xml"),
        ]) + '</Relationships>'
    )
    types = '''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
      <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
      <Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>
      <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
      <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
      <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
      <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
      <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
      <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
      <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
    </Types>'''
    rootrels = f'''<Relationships xmlns="{relns}">
      <Relationship Id="rId1" Type="{reltype}officeDocument" Target="word/document.xml"/>
      <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
      <Relationship Id="rId3" Type="{reltype}extended-properties" Target="docProps/app.xml"/>
    </Relationships>'''
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    core = f'''<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
      xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <dc:title>{escape(title)}</dc:title><dc:creator>Siz3r</dc:creator><dc:language>pl-PL</dc:language>
      <dc:description>Edytowalny papier firmowy do importu do Dokumentów Google.</dc:description>
      <dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>
    </cp:coreProperties>'''
    files = {
        "[Content_Types].xml": types,
        "_rels/.rels": rootrels,
        "docProps/core.xml": core,
        "docProps/app.xml": '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Siz3r template builder</Application></Properties>',
        "word/document.xml": document,
        "word/styles.xml": STYLES,
        "word/header1.xml": HEADER,
        "word/footer1.xml": FOOTER,
        "word/settings.xml": f'<w:settings {NS}><w:defaultTabStop w:val="720"/><w:updateFields w:val="true"/><w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>',
        "word/_rels/document.xml.rels": docrels,
        "word/_rels/header1.xml.rels": f'<Relationships xmlns="{relns}"><Relationship Id="rIdLogo" Type="{reltype}image" Target="media/siz3r-logo.png"/></Relationships>',
    }
    target = OUT / filename
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as package:
        for path, xml in files.items():
            ET.fromstring(xml)
            package.writestr(path, xml.encode("utf-8"))
        package.writestr("word/media/siz3r-logo.png", (ASSETS / "siz3r-logo.png").read_bytes())
    with zipfile.ZipFile(target) as check:
        assert check.testzip() is None
        assert check.read("word/media/siz3r-logo.png") == (ASSETS / "siz3r-logo.png").read_bytes()
        assert b"vbaProject" not in check.read("[Content_Types].xml")
    print(f"OK: {target.name}; {target.stat().st_size:,} bytes")


if __name__ == "__main__":
    make_docx("Siz3r_Papier_firmowy.docx", GENERAL, "Siz3r — papier firmowy")
    make_docx("Siz3r_Odpowiedz_AIO_do_uzupelnienia.docx", AIO, "Siz3r — pytania AIO i miejsca na odpowiedzi")
    instructions = """SIZ3R — PAPIER FIRMOWY I ODPOWIEDŹ DLA AIO

PLIKI
Siz3r_Papier_firmowy.docx — uniwersalny szablon korespondencji.
Siz3r_Odpowiedz_AIO_do_uzupelnienia.docx — szablon pod otrzymany mail, z siedmioma sekcjami, pełnymi pytaniami klienta i miejscem na odpowiedź pod każdym pytaniem.
Pliki PDF — podglądy projektu wygenerowane z treści i stylów DOCX.

IMPORT DO DOKUMENTÓW GOOGLE
1. Prześlij wybrany plik DOCX na Dysk Google (Nowy > Prześlij plik).
2. Otwórz go przez Otwórz w > Dokumenty Google.
3. Wybierz Plik > Zapisz jako Dokumenty Google, aby utworzyć natywną kopię.
4. Zachowaj ją jako SZABLON — SIZ3R — papier firmowy.
5. Przy każdej kolejnej odpowiedzi wybieraj Plik > Utwórz kopię.

EDYCJA
Zastąp pola w nawiasach kwadratowych własnym tekstem.
W dokumencie dla AIO uzupełnij warunki techniczne, prawne i cenowe oraz dane podpisującego.
Szare pytania klienta można zachować albo usunąć po wpisaniu odpowiedzi.
Logo i kontakt są w nagłówku. Dane firmy i numer strony są w stopce.
Aby zmienić te elementy, kliknij dwukrotnie nagłówek lub stopkę.
Układ jest przygotowany na A4, w trybie Strony. W trybie Bez stron nagłówek, stopka i numeracja nie są widoczne.
Sekcja 04 w odpowiedzi dla AIO zaczyna nową stronę. Jeśli zmienisz długość tekstu, możesz dostosować podział przed tą sekcją.
Przed wysłaniem sprawdź układ stron po imporcie, uzupełnienie wszystkich pól i aktualność danych firmy.
Finalną odpowiedź możesz pobrać jako PDF przez Plik > Pobierz > Dokument PDF.

MATERIAŁY I ZAKRES
Logo: oryginalny osadzony plik z istniejącej prezentacji output/aio/Siz3r_Wyniki_AIO.pdf; zachowano proporcje i przezroczystość.
Dane stopki: oficjalna strona https://siz3r.com/pl (sprawdzona 6.10.2026).
Tekst odpowiedzi: szablon do uzupełnienia; nie zawiera potwierdzonych deklaracji o integracji AtomStore, cenach, obsługiwanych kategoriach ani zasadach RODO.
Dokumenty mają edytowalny tekst, style i powtarzany nagłówek oraz stopkę. Logo jest grafiką PNG.
Podglądy PDF pokazują projekt graficzny i treść; zostały wygenerowane lokalnie z treści i stylów DOCX. Nie są eksportem z Google Docs ani Microsoft Word. Renderowanie DOCX i konwersja w Google Docs mogą nieznacznie zmienić odstępy i podziały stron.

POMOC GOOGLE
https://support.google.com/docs/answer/9406611?hl=pl
"""
    (OUT / "Jak_uzywac_szablonu.txt").write_text(instructions, encoding="utf-8-sig")
