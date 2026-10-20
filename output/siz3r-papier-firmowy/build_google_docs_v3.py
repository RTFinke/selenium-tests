"""Revised editable SIZ3R letterhead with import-safe relative line spacing.

The PDF is a local layout preview of the DOCX, not a Google Docs export.
Earlier versions and the user's shared document are left intact.
"""

from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
import ast
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "google-docs" / "v3"
OUT.mkdir(parents=True, exist_ok=True)
LOGO = Path(r"C:\Users\suici\Downloads\logoSiz3r.png").read_bytes()
BASE = ROOT / "Siz3r_Papier_firmowy.docx"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
WIDTH = 9298
GREEN, INK, BODY, MUTED, RULE = "00D278", "17211D", "35413B", "69766F", "DDE5E0"

source = ast.parse((ROOT / "build_refined_pdf.py").read_text(encoding="utf-8"))
QUESTIONS = next(ast.literal_eval(item.value) for item in source.body
                 if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "QUESTIONS" for t in item.targets))

# OOXML auto line spacing uses 240 units per line. Absolute twips converted
# to 'auto' during Google import caused the earlier title to use 2.25 lines.
SPECS = {
    "Body": dict(size=10.5, line=276, color=BODY),
    "Title": dict(size=20.5, line=264, color=INK, bold=True, keep=True),
    "Heading2": dict(size=12, line=276, color=INK, bold=True, keep=True, heading=True),
    "Question": dict(size=11, line=276, color=BODY, indent=True, keep=True),
    "Answer": dict(size=11, line=276, color=BODY, indent=True),
    "Signature": dict(size=10.5, line=276, color=BODY, indent=True, keep=True),
    "Signer": dict(size=11, line=240, color=INK, bold=True, indent=True, keep=True),
    "Role": dict(size=9.5, line=240, color=MUTED, indent=True),
    "Label": dict(size=8, line=240, color=MUTED, bold=True, keep=True),
    "Name": dict(size=11, line=240, color=INK, bold=True, keep=True),
    "Meta": dict(size=9.5, line=240, color=MUTED, keep=True),
    "Header": dict(size=9, line=240, color=MUTED),
    "HeaderLogo": dict(size=9, line=240, color=MUTED),
    "Footer": dict(size=9, line=240, color=BODY),
    "EndTable": dict(size=1, line=240, color=BODY),
}


def rpr(spec, *, bold=None, color=None):
    size = round(spec["size"] * 2)
    is_bold = spec.get("bold", False) if bold is None else bold
    return (f'<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial" w:eastAsia="Arial"/>'
            f'<w:b w:val="{int(is_bold)}"/><w:bCs w:val="{int(is_bold)}"/>'
            f'<w:color w:val="{color or spec["color"]}"/><w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
            '<w:lang w:val="pl-PL"/>')


def run(text="", style="Body", *, bold=None, color=None, tab=False):
    content = "<w:tab/>" if tab else f'<w:t xml:space="preserve">{escape(text)}</w:t>'
    return f'<w:r><w:rPr>{rpr(SPECS[style], bold=bold, color=color)}</w:rPr>{content}</w:r>'


def ppr(spec, before=0, after=0, align=None, keep=None):
    keep = spec.get("keep",False) if keep is None else keep
    props = (f'<w:keepNext w:val="{int(keep)}"/><w:keepLines/>'
             f'<w:widowControl/><w:spacing w:before="{round(before*20)}" w:after="{round(after*20)}" '
             f'w:line="{spec["line"]}" w:lineRule="auto"/>')
    if spec.get("heading"):
        props += '<w:ind w:left="540" w:hanging="540"/><w:tabs><w:tab w:val="left" w:pos="540"/></w:tabs><w:outlineLvl w:val="1"/>'
    elif spec.get("indent"):
        props += '<w:ind w:left="540"/>'
    if align:
        props += f'<w:jc w:val="{align}"/>'
    return props


def p(text="", style="Body", *, raw=False, before=0, after=0, align=None, keep=None):
    spec = SPECS[style]
    # Direct paragraph and run properties also cover empty editable paragraphs.
    props = f'<w:pStyle w:val="{style}"/>' + ppr(spec, before, after, align, keep)
    props += f'<w:rPr>{rpr(spec)}</w:rPr>'
    return f'<w:p><w:pPr>{props}</w:pPr>{text if raw else run(text,style)}</w:p>'


def table(left, right, widths, *, edge=None, padding=0):
    border = f'<w:tblBorders><w:{edge} w:val="single" w:sz="4" w:color="{RULE}"/></w:tblBorders>' if edge else ""
    top = round(padding*20) if edge == "top" else 0
    bottom = round(padding*20) if edge == "bottom" else 0
    cells = ''.join(
        f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/><w:vAlign w:val="top"/></w:tcPr>{text}</w:tc>'
        for text, width in zip((left, right), widths)
    )
    return (
        f'<w:tbl><w:tblPr><w:tblW w:w="{WIDTH}" w:type="dxa"/><w:tblInd w:w="0" w:type="dxa"/>'
        f'<w:tblLayout w:type="fixed"/>{border}<w:tblCellMar>'
        f'<w:top w:w="{top}" w:type="dxa"/><w:left w:w="0" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tblCellMar></w:tblPr>'
        f'<w:tblGrid>{"".join(f"<w:gridCol w:w=\"{width}\"/>" for width in widths)}</w:tblGrid>'
        f'<w:tr><w:trPr><w:cantSplit/></w:trPr>{cells}</w:tr></w:tbl>'
    )


def styles_xml():
    result = f'<w:styles {NS}><w:docDefaults><w:rPrDefault><w:rPr>{rpr(SPECS["Body"])}</w:rPr></w:rPrDefault></w:docDefaults>'
    result += '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
    for name, spec in SPECS.items():
        result += (f'<w:style w:type="paragraph" w:styleId="{name}"><w:name w:val="{name}"/><w:basedOn w:val="Normal"/>'
                   f'<w:pPr>{ppr(spec)}</w:pPr><w:rPr>{rpr(spec)}</w:rPr></w:style>')
    return result + '</w:styles>'


DRAWING = '''<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">
<wp:extent cx="1512000" cy="354375"/><wp:docPr id="1" name="Logo Siz3r" descr="Logo Siz3r"/>
<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>
<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>
<pic:nvPicPr><pic:cNvPr id="0" name="logoSiz3r.png"/><pic:cNvPicPr/></pic:nvPicPr>
<pic:blipFill><a:blip r:embed="rIdLogo"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1512000" cy="354375"/></a:xfrm>
<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>
</wp:inline></w:drawing></w:r>'''


def header():
    contact = p(run("siz3r.com","Header",bold=True,color=INK), "Header", raw=True, align="right", after=2)
    contact += p("office@siz3r.com", "Header", align="right")
    return f'<w:hdr {NS}>' + table(p(DRAWING,"HeaderLogo",raw=True),contact,[5579,3719],edge="bottom",padding=15) + p(style="EndTable") + '</w:hdr>'


def footer(numbered):
    left = p(run("Siz3r Sp. z o.o.","Footer",bold=True) + run("    ul. Stanisławowska 47, 54-611 Wrocław","Footer"), "Footer", raw=True, after=4)
    left += p("NIP: 894-313-42-44    KRS: 0000754380    REGON: 381639043", "Footer")
    fields = ('<w:fldSimple w:instr="PAGE">'+run("1","Footer")+'</w:fldSimple>'+run(" / ","Footer")+
              '<w:fldSimple w:instr="NUMPAGES">'+run("3","Footer")+'</w:fldSimple>') if numbered else run("","Footer")
    right = p(fields, "Footer", raw=True, align="right", after=4) + p(style="Footer",align="right")
    return f'<w:ftr {NS}>' + table(left,right,[7903,1395],edge="top",padding=10) + p(style="EndTable") + '</w:ftr>'


def answer(points, keep=False):
    # A single paragraph of empty text lines has a real, indivisible height.
    # Spacing-after alone is discarded at page edges and can strand headings.
    lines = max(3,round(points/(11*1.15*1.15)))
    blank = run(style="Answer")
    blank += (f'<w:r><w:rPr>{rpr(SPECS["Answer"])}</w:rPr><w:br/></w:r>')*(lines-1)
    return p(blank,"Answer",raw=True,before=8,after=8,keep=keep)


def section(number, spaces, before=0):
    title, questions = QUESTIONS[number-1]
    label = run(f"{number:02d}","Heading2",color=GREEN) + run(style="Heading2",tab=True) + run(title,"Heading2")
    result = p(label,"Heading2",raw=True,before=before,after=10)
    for index,(question, space) in enumerate(zip(questions,spaces)):
        # Preserve the original wording, keeping short phrases together.
        question = question.replace("sesje lub pliki 3D", "sesje\u00a0lub\u00a0pliki\u00a03D").replace("2–3 przesłanych", "2–3\u00a0przesłanych")
        result += p(question,"Question") + answer(space,keep=index<len(questions)-1)
    return result


def aio_body():
    recipient = p("ADRESAT","Label",after=4) + p("Bartłomiej Fitas","Name")
    recipient += p("Kierownik działu e-commerce","Meta") + p("sklep.aio.com.pl","Meta")
    date = p("DATA","Label",align="right",after=4) + p(style="Meta",align="right")
    result = table(recipient,date,[6200,3098])
    result += p("Wirtualna przymierzalnia","Title",before=22,after=3)
    result += p("Odpowiedź na zapytanie · sklep.aio.com.pl","Meta",after=19)
    result += p("Szanowny Panie Bartłomieju,",after=8)
    result += p("dziękujemy za zainteresowanie rozwiązaniem Siz3r. Poniżej przedstawiamy odpowiedzi na pytania dotyczące wdrożenia wirtualnej przymierzalni w Państwa sklepie.",after=24)
    result += section(1,[44,44]) + section(2,[52],before=10)
    result += section(3,[76,76],before=18) + section(4,[76,76],before=18)
    result += section(5,[65],before=18) + section(6,[78],before=13) + section(7,[65],before=13)
    result += p("Z poważaniem,","Signature",before=13,after=8)
    result += p(style="Signer") + p(style="Role")
    return result


def build(name, body, title, *, aio=False):
    with zipfile.ZipFile(BASE) as archive:
        parts = {key: archive.read(key) for key in archive.namelist()}
    sect = '''<w:sectPr><w:headerReference w:type="default" r:id="rIdHeader"/>
    <w:footerReference w:type="default" r:id="rIdFooter"/><w:pgSz w:w="11906" w:h="16838"/>
    <w:pgMar w:top="2660" w:right="1304" w:bottom="1860" w:left="1304" w:header="1134" w:footer="800"/>
    <w:cols w:space="708"/></w:sectPr>'''
    updates = {
        "word/document.xml": f'<w:document {NS}><w:body>{body}{sect}</w:body></w:document>',
        "word/styles.xml": styles_xml(),
        "word/header1.xml": header(),
        "word/footer1.xml": footer(aio),
        "word/settings.xml": f'<w:settings {NS}><w:defaultTabStop w:val="720"/><w:updateFields w:val="true"/><w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>',
    }
    for key, value in updates.items():
        ET.fromstring(value)
        parts[key] = value.encode("utf-8")
    parts["word/media/siz3r-logo.png"] = LOGO
    core = ET.fromstring(parts["docProps/core.xml"])
    dc = "{http://purl.org/dc/elements/1.1/}"
    for key,value in {"title":title,"description":"Edytowalny szablon SIZ3R do Google Docs, wersja 3."}.items():
        node = core.find(dc+key)
        if node is None:
            node = ET.SubElement(core,dc+key)
        node.text = value
    core.find("{http://purl.org/dc/terms/}created").text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts["docProps/core.xml"] = ET.tostring(core,encoding="utf-8",xml_declaration=True)
    target = OUT/name
    with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED) as archive:
        for key,value in parts.items():
            archive.writestr(key,value)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        for key in archive.namelist():
            if key.endswith((".xml",".rels")):
                ET.fromstring(archive.read(key))
        assert archive.read("word/media/siz3r-logo.png") == LOGO
        text = " ".join(" ".join(ET.fromstring(archive.read(k)).itertext()) for k in updates)
        assert "Kapitał" not in text and "Wpisz" not in text and "[" not in text
        assert "wp:anchor" not in archive.read("word/header1.xml").decode()
        for key in ["word/document.xml","word/header1.xml","word/footer1.xml","word/styles.xml"]:
            node = ET.fromstring(archive.read(key))
            assert not node.findall(".//"+W+"pageBreakBefore")
            assert not any(b.get(W+"type") in ("page","column") for b in node.findall(".//"+W+"br"))
            assert all(s.get(W+"lineRule")=="auto" and 240 <= int(s.get(W+"line","240")) <= 276
                       for s in node.findall(".//"+W+"spacing"))
        if aio:
            body_xml = ET.fromstring(archive.read("word/document.xml")).find(W+"body")
            paragraphs = body_xml.findall(W+"p")
            styled = lambda sid: [p for p in paragraphs if p.find(W+"pPr/"+W+"pStyle").get(W+"val")==sid]
            normalize = lambda t: " ".join(t.split())
            assert [normalize("".join(p.itertext())) for p in styled("Question")] == [normalize(q) for _,qs in QUESTIONS for q in qs]
            assert len(styled("Answer")) == 10 and all(not "".join(p.itertext()) for p in styled("Answer"))
            assert len(styled("Heading2")) == 7
            assert all(not "".join(p.itertext()) for sid in ["Signer","Role"] for p in styled(sid))
            assert "DATA" in text
    print(f"OK: {target.name}: original logo, complete questions, empty answers, relative line spacing, no capital amount.")
    return target


if __name__ == "__main__":
    build("Siz3r_AIO_Google_Docs_v3.docx",aio_body(),"Siz3r — odpowiedź na zapytanie AIO, wersja 3",aio=True)
    build("Siz3r_Papier_firmowy_Google_Docs_v3.docx",p(),"Siz3r — papier firmowy, wersja 3")
    (OUT/"Jak_otworzyc.txt").write_text(
        "SIZ3R — WERSJA 3\n\n"
        "Prześlij plik Siz3r_AIO_Google_Docs_v3.docx na Dysk Google i otwórz w Dokumentach Google. "
        "Zapisz jako Dokumenty Google, aby zachować natywną kopię. Używaj formatu A4 z podziałem na strony.\n\n"
        "Wpisz datę w pustym akapicie pod etykietą DATA. Pod każdym pytaniem znajduje się puste, edytowalne miejsce. "
        "Pod zwrotem Z poważaniem znajdują się dwa puste akapity na imię i nazwisko oraz stanowisko.\n\n"
        "Po wpisaniu odpowiedzi możesz usunąć pozostałe puste wiersze, jeśli nie potrzebujesz już zarezerwowanego miejsca. "
        "Przed wysłaniem sprawdź podział stron i pobierz PDF bezpośrednio z Google Docs.\n\n"
        "Załączony PDF jest podglądem układu wygenerowanym lokalnie. Nie jest eksportem nowej wersji z Google Docs. "
        "Poprzedni dokument Google oraz wcześniejsze pliki nie zostały nadpisane.\n",
        encoding="utf-8-sig")
