"""Render a local PDF preview and inspect the revised DOCX layout.

Arial's observed natural line height in the previous Google export is about
1.15 times font size. This is a local model, not a live Google conversion.
"""

from pathlib import Path
from xml.sax.saxutils import escape
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Table, TableStyle
from reportlab.lib.utils import ImageReader

import build_google_docs_v3 as source

ROOT, OUT, W = source.ROOT, source.OUT, source.W
sys.path.insert(0,str(ROOT.parents[1]/".tmp-pdf-tools"))
import pymupdf as fitz

pdfmetrics.registerFont(TTFont("Arial",r"C:\Windows\Fonts\arial.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Bold",r"C:\Windows\Fonts\arialbd.ttf"))
pdfmetrics.registerFontFamily("Arial",normal="Arial",bold="Arial-Bold",italic="Arial",boldItalic="Arial-Bold")

PAGE_W, PAGE_H = 11906/20, 16838/20
LEFT, RIGHT = 1304/20, (11906-1304)/20
NATURAL_LINE = 1.15


def para(node, *, line_scale=1):
    ppr = node.find(W+"pPr")
    sid = ppr.find(W+"pStyle").get(W+"val")
    spec = source.SPECS[sid]
    spacing = ppr.find(W+"spacing")
    settings = dict(fontName="Arial-Bold" if spec.get("bold") else "Arial",
                    fontSize=spec["size"], leading=spec["size"] * spec["line"] / 240 * NATURAL_LINE * line_scale,
                    textColor=colors.HexColor("#"+spec["color"]),
                    spaceBefore=int(spacing.get(W+"before","0"))/20,
                    spaceAfter=int(spacing.get(W+"after","0"))/20,
                    keepWithNext=ppr.find(W+"keepNext").get(W+"val","1")=="1",splitLongWords=False)
    indent = ppr.find(W+"ind")
    if indent is not None:
        settings["leftIndent"] = int(indent.get(W+"left","0"))/20
        settings["firstLineIndent"] = -int(indent.get(W+"hanging","0"))/20
    align = ppr.find(W+"jc")
    if align is not None:
        settings["alignment"] = {"left":0,"right":2,"center":1}[align.get(W+"val")]
    text = ""
    for run in node.findall(W+"r"):
        if run.find(W+"tab") is not None:
            text += "&#160;"*4
            continue
        chunk = "".join(escape(t.text or "") for t in run.findall(W+"t"))
        chunk += "<br/>"*len(run.findall(W+"br"))
        chunk = re.sub(r" {2,}",lambda m:"&#160;"*len(m.group()),chunk)
        props = run.find(W+"rPr")
        if props is not None:
            color = props.find(W+"color")
            if color is not None:
                chunk = '<font color="#'+color.get(W+"val")+'">'+chunk+'</font>'
            bold = props.find(W+"b")
            if bold is not None and bold.get(W+"val","1")=="1":
                chunk = "<b>"+chunk+"</b>"
        text += chunk
    if not any((t.text or "").strip() for t in node.findall(".//"+W+"t")):
        # Empty formatted spans otherwise have zero height in ReportLab.
        text = "&#160;" + "<br/>&#160;"*len(node.findall(".//"+W+"br"))
    return Paragraph(text or "&#160;",ParagraphStyle(sid,**settings))


def furniture(canvas,doc,numbered):
    canvas.saveState()
    canvas.setTitle("Siz3r — odpowiedź AIO, podgląd wersji 3" if numbered else "Siz3r — papier firmowy, wersja 3")
    canvas.setAuthor("Siz3r")
    canvas.setSubject("Lokalny podgląd szablonu DOCX do edycji w Google Docs")
    top = 1134/20
    logo_w,logo_h = 1512000/12700,354375/12700
    canvas.drawImage(ImageReader(str(Path(r"C:\Users\suici\Downloads\logoSiz3r.png"))),LEFT,PAGE_H-top-logo_h,
                     width=logo_w,height=logo_h,mask="auto")
    canvas.setFillColor(colors.HexColor("#"+source.INK))
    canvas.setFont("Arial-Bold",9)
    canvas.drawRightString(RIGHT,PAGE_H-top-9,"siz3r.com")
    canvas.setFillColor(colors.HexColor("#"+source.MUTED))
    canvas.setFont("Arial",9)
    canvas.drawRightString(RIGHT,PAGE_H-top-9-12.35,"office@siz3r.com")
    canvas.setStrokeColor(colors.HexColor("#"+source.RULE))
    canvas.setLineWidth(.5)
    canvas.line(LEFT,PAGE_H-top-logo_h-15,RIGHT,PAGE_H-top-logo_h-15)

    footer_top = PAGE_H-40-35.85
    canvas.line(LEFT,PAGE_H-footer_top,RIGHT,PAGE_H-footer_top)
    y = PAGE_H-footer_top-10-9
    canvas.setFillColor(colors.HexColor("#"+source.BODY))
    name = "Siz3r Sp. z o.o."
    canvas.setFont("Arial-Bold",9)
    canvas.drawString(LEFT,y,name)
    canvas.setFont("Arial",9)
    canvas.drawString(LEFT+pdfmetrics.stringWidth(name,"Arial-Bold",9)+pdfmetrics.stringWidth("    ","Arial",9),y,
                      "ul. Stanisławowska 47, 54-611 Wrocław")
    canvas.drawString(LEFT,y-14.35,"NIP: 894-313-42-44    KRS: 0000754380    REGON: 381639043")
    if numbered:
        canvas.drawRightString(RIGHT,y,f"{doc.page} / 3")
    canvas.restoreState()


def render(docx,target,*,numbered=False,line_scale=1,height=PAGE_H):
    with zipfile.ZipFile(docx) as archive:
        body = ET.fromstring(archive.read("word/document.xml")).find(W+"body")
    flows = []
    for node in body:
        if node.tag == W+"p":
            flows.append(para(node,line_scale=line_scale))
        elif node.tag == W+"tbl":
            row = node.find(W+"tr")
            cells = row.findall(W+"tc")
            widths = [int(cell.find(W+"tcPr/"+W+"tcW").get(W+"w"))/20 for cell in cells]
            contents = [[para(p,line_scale=line_scale) for p in cell.findall(W+"p")] for cell in cells]
            table = Table([contents],colWidths=widths,hAlign="LEFT")
            table.setStyle(TableStyle([("LEFTPADDING",(0,0),(-1,-1),0),
                                       ("RIGHTPADDING",(0,0),(-1,-1),0),
                                       ("TOPPADDING",(0,0),(-1,-1),0),
                                       ("BOTTOMPADDING",(0,0),(-1,-1),0),
                                       ("VALIGN",(0,0),(-1,-1),"TOP")]))
            flows.append(table)
    doc = BaseDocTemplate(str(target),pagesize=(PAGE_W,height),leftMargin=LEFT,rightMargin=LEFT,
                          topMargin=2660/20,bottomMargin=1860/20)
    frame = Frame(doc.leftMargin,doc.bottomMargin,doc.width,doc.height,
                  leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
    doc.addPageTemplates(PageTemplate(id="Body",frames=[frame],onPage=lambda c,d:furniture(c,d,numbered)))
    doc.build(flows)
    return target


def verify(path,*,aio=False,images=False):
    with fitz.open(path) as pdf:
        assert len(pdf)==(3 if aio else 1),(path,len(pdf))
        texts = [p.get_text() for p in pdf]
        assert all("Siz3r Sp. z o.o." in t for t in texts)
        combined = " ".join(" ".join(texts).split())
        assert "Kapitał" not in combined and "Wpisz" not in combined and "[" not in combined
        if aio:
            for _,questions in source.QUESTIONS:
                for question in questions:
                    assert " ".join(question.split()) in combined,question
            for page,expected in zip(pdf,[(1,2),(3,4),(5,6,7)]):
                text = " ".join(page.get_text().split())
                for number in expected:
                    assert source.QUESTIONS[number-1][0] in text,(page.number,number)
            # The footer alone must never count as a populated content page.
            assert all(p.get_textbox(fitz.Rect(LEFT,133,RIGHT,748)).strip() for p in pdf)
            assert "Z poważaniem," in texts[-1]
            question_lines = [l for b in pdf[0].get_text("dict")["blocks"] if b["type"]==0 for l in b["lines"]]
            assert not any("".join(s["text"] for s in l["spans"]).strip()=="3D?" for l in question_lines)
            title = next(l for l in question_lines if "Wirtualna przymierzalnia" in "".join(s["text"] for s in l["spans"]))
            subtitle = next(l for l in question_lines if "Odpowiedź na zapytanie" in "".join(s["text"] for s in l["spans"]))
            gap = subtitle["bbox"][1]-title["bbox"][3]
            assert 0 < gap < 16,("Title gap",gap)
        for page in pdf:
            spans = [s for b in page.get_text("dict")["blocks"] if b["type"]==0 for l in b["lines"] for s in l["spans"] if s["text"].strip()]
            assert all(s["bbox"][0]>=LEFT-.5 and s["bbox"][2]<=RIGHT+.5 for s in spans)
            assert all(s["bbox"][3]<page.rect.height-25 for s in spans)
            assert len(page.get_images())>=1
            if images:
                page.get_pixmap(matrix=fitz.Matrix(1.4,1.4)).save(path.with_name(path.stem+f"_strona_{page.number+1}.png"))
        print(f"OK: {path.name}; {len(pdf)} pages, complete content, no blank content pages. Local layout model.")


if __name__=="__main__":
    aio_docx = OUT/"Siz3r_AIO_Google_Docs_v3.docx"
    blank_docx = OUT/"Siz3r_Papier_firmowy_Google_Docs_v3.docx"
    verify(render(aio_docx,OUT/"Siz3r_AIO_v3_podglad.pdf",numbered=True),aio=True,images=True)
    verify(render(blank_docx,OUT/"Siz3r_Papier_firmowy_v3_podglad.pdf"),images=True)
    for name,height,scale in [("A4_interlinia_110",PAGE_H,1.1),("nizsza_strona",792,1)]:
        verify(render(aio_docx,OUT/("_kontrola_"+name+".pdf"),numbered=True,line_scale=scale,height=height),aio=True)
