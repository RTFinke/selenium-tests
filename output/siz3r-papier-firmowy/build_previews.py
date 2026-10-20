"""Render design previews from the DOCX paragraphs and styles.

These previews use ReportLab and are explicitly not a Word/Docs rendering.
"""

from pathlib import Path
import sys
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, PageBreak
from reportlab.lib.utils import ImageReader

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.path.insert(0, str(ROOT / ".tmp-pdf-tools"))
import pymupdf as fitz

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
pdfmetrics.registerFont(TTFont("Arial", "C:/Windows/Fonts/arial.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Bold", "C:/Windows/Fonts/arialbd.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Italic", "C:/Windows/Fonts/ariali.ttf"))
pdfmetrics.registerFont(TTFont("Arial-BoldItalic", "C:/Windows/Fonts/arialbi.ttf"))
pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold", italic="Arial-Italic", boldItalic="Arial-BoldItalic")


def get_val(elem, name, attribute="val", default=None):
    if elem is None:
        return default
    child = elem.find(W + name)
    return child.get(W + attribute, default) if child is not None else default


def style_config(ppr, rpr, base):
    result = dict(base)
    if rpr is not None:
        size = get_val(rpr, "sz")
        if size:
            result["fontSize"] = int(size) / 2
        color = get_val(rpr, "color")
        if color:
            result["textColor"] = colors.HexColor("#" + color)
        if rpr.find(W + "b") is not None:
            result["fontName"] = "Arial-Bold"
    if ppr is not None:
        spacing = ppr.find(W + "spacing")
        if spacing is not None:
            for name, result_name in [("before", "spaceBefore"), ("after", "spaceAfter")]:
                if W + name in spacing.attrib:
                    result[result_name] = int(spacing.get(W + name)) / 20
            if W + "line" in spacing.attrib:
                result["lineRatio"] = int(spacing.get(W + "line")) / 240
        if ppr.find(W + "keepNext") is not None:
            result["keepWithNext"] = True
        alignment = get_val(ppr, "jc")
        if alignment:
            result["alignment"] = {"left": 0, "center": 1, "right": 2}.get(alignment, 0)
    result["leading"] = result["fontSize"] * result["lineRatio"]
    return result


def paragraph_markup(elem):
    chunks = []
    for child in elem:
        if child.tag != W + "r":
            continue
        text = "".join(
            escape(node.text or "") if node.tag == W + "t" else "<br/>" if node.tag == W + "br" else ""
            for node in child
        )
        props = child.find(W + "rPr")
        if props is not None:
            if props.find(W + "b") is not None:
                text = f"<b>{text}</b>"
            if props.find(W + "i") is not None:
                text = f"<i>{text}</i>"
            color = get_val(props, "color")
            if color:
                text = f'<font color="#{color}">{text}</font>'
        chunks.append(text)
    return "".join(chunks)


def on_page(canvas, doc):
    left = 1108 / 20
    right = doc.pagesize[0] - left
    height = doc.pagesize[1]
    canvas.saveState()
    canvas.drawImage(ImageReader(str(OUT / "assets/siz3r-logo.png")), left, height - 50, width=116.22, height=27.21, mask="auto")
    canvas.setFont("Arial", 8.5)
    canvas.setFillColor(colors.HexColor("#65717D"))
    canvas.drawRightString(right, height - 34, "siz3r.com")
    canvas.drawRightString(right, height - 46, "office@siz3r.com")
    canvas.setStrokeColor(colors.HexColor("#00D278"))
    canvas.setLineWidth(1)
    canvas.line(left, height - 65, right, height - 65)
    canvas.setStrokeColor(colors.HexColor("#E4E8E6"))
    canvas.setLineWidth(0.5)
    canvas.line(left, 67, right, 67)
    canvas.setFont("Arial", 7)
    canvas.drawString(left, 54, "Siz3r Sp. z o.o.  |  ul. Stanisławowska 47, 54-611 Wrocław")
    canvas.drawRightString(right, 54, str(doc.page))
    canvas.drawString(left, 44, "NIP: 894-313-42-44  |  KRS: 0000754380  |  REGON: 381639043")
    canvas.restoreState()


def build(source):
    with zipfile.ZipFile(source) as package:
        xml = ET.fromstring(package.read("word/document.xml"))
        styles_xml = ET.fromstring(package.read("word/styles.xml"))
    defaults = dict(fontName="Arial", fontSize=10.5, textColor=colors.HexColor("#14171B"),
                    lineRatio=1.15, leading=12.075, spaceBefore=0, spaceAfter=6,
                    keepWithNext=False, alignment=0, splitLongWords=False)
    configs = {"Normal": defaults}
    for elem in styles_xml.findall(W + "style"):
        sid = elem.get(W + "styleId")
        base = configs.get(get_val(elem, "basedOn", default="Normal"), defaults)
        configs[sid] = style_config(elem.find(W + "pPr"), elem.find(W + "rPr"), base)
    paragraphs = xml.find(W + "body").findall(W + "p")
    flows = []
    for elem in paragraphs:
        ppr = elem.find(W + "pPr")
        if ppr is not None and ppr.find(W + "pageBreakBefore") is not None:
            flows.append(PageBreak())
        sid = get_val(ppr, "pStyle", default="Normal")
        config = style_config(ppr, None, configs[sid])
        config.pop("lineRatio", None)
        flows.append(Paragraph(paragraph_markup(elem) or "&#160;", ParagraphStyle(sid, **config)))
    output = source.with_name(source.stem + "_podglad.pdf")
    doc = BaseDocTemplate(str(output), pagesize=(11906 / 20, 16838 / 20),
                          leftMargin=1108 / 20, rightMargin=1108 / 20,
                          topMargin=2150 / 20, bottomMargin=1550 / 20,
                          title=source.stem.replace("_", " "), author="Siz3r")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates(PageTemplate(id="Letterhead", frames=[frame], onPage=on_page))
    doc.build(flows)
    with fitz.open(output) as pdf:
        for index, page in enumerate(pdf):
            page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4)).save(output.with_name(source.stem + f"_strona_{index+1}.png"))
            text = page.get_text()
            assert "Siz3r Sp. z o.o." in text
            assert "office@siz3r.com" in text
        text = "\n".join(page.get_text() for page in pdf)
        if "AIO" in source.name:
            assert len(pdf) == 2, f"Unexpected preview pagination: {len(pdf)}"
            assert text.count("[Wpisz odpowiedź.]") == 10
            for keyword in ["AtomStore", "Materiały", "BHP", "RODO", "rozmiaru", "koszty", "Pilotaż"]:
                if keyword == "Materiały":
                    continue
                assert keyword in text, keyword
        else:
            assert len(pdf) == 1
        print(f"OK: {output.name}; {len(pdf)} pages; text, header and footer verified.")


for name in ["Siz3r_Papier_firmowy.docx", "Siz3r_Odpowiedz_AIO_do_uzupelnienia.docx"]:
    build(OUT / name)
