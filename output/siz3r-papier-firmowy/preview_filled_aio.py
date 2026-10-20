"""Local preview of the repaired filled DOCX, with the actual branded furniture.

Body pagination is a ReportLab model. Header/footer artwork is copied as vector
PDF content from the latest Google export. This is not a new Google export.
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

import fix_filled_aio as fix

ROOT,OUT,W=fix.ROOT,fix.OUT,fix.W
sys.path.insert(0,str(ROOT.parents[1]/".tmp-pdf-tools"))
import pymupdf as fitz

pdfmetrics.registerFont(TTFont("Arial",r"C:\Windows\Fonts\arial.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Bold",r"C:\Windows\Fonts\arialbd.ttf"))
pdfmetrics.registerFontFamily("Arial",normal="Arial",bold="Arial-Bold",italic="Arial",boldItalic="Arial-Bold")

PAGE_W,PAGE_H=11906/20,16838/20
LEFT,RIGHT=1304/20,(11906-1304)/20


def prop(parent,tag,default=None):
    node=parent.find(W+tag) if parent is not None else None
    return node if node is not None else default


def boolean(parent,tag,default=False):
    node=prop(parent,tag)
    return default if node is None else node.get(W+"val","1")=="1"


def para(p,line_scale=1):
    ppr=p.find(W+"pPr")
    rpr=ppr.find(W+"rPr")
    size=float(rpr.find(W+"sz").get(W+"val"))/2
    space=ppr.find(W+"spacing")
    sid=prop(ppr,"pStyle")
    sid=sid.get(W+"val") if sid is not None else "Metadata"
    indent=prop(ppr,"ind")
    left=int(indent.get(W+"left","0"))/20 if indent is not None else 0
    hanging=int(indent.get(W+"hanging","0"))/20 if indent is not None else 0
    cfg=dict(fontName="Arial-Bold" if boolean(rpr,"b") else "Arial",fontSize=size,
             leading=size*1.15*int(space.get(W+"line","240"))/240*line_scale,
             textColor=colors.HexColor("#"+rpr.find(W+"color").get(W+"val")),
             leftIndent=left,firstLineIndent=-hanging,
             spaceBefore=int(space.get(W+"before","0"))/20,
             spaceAfter=int(space.get(W+"after","0"))/20,
             keepWithNext=boolean(ppr,"keepNext"),allowOrphans=0,allowWidows=0,splitLongWords=False)
    jc=prop(ppr,"jc")
    cfg["alignment"]={"left":0,"right":2,"center":1}.get(jc.get(W+"val") if jc is not None else "left",0)
    if prop(ppr,"numPr") is not None:
        cfg["firstLineIndent"]=0
        cfg["bulletIndent"]=left-hanging
        cfg["bulletFontName"]="Arial"
        cfg["bulletFontSize"]=size
    html=""
    for run in p.findall(".//"+W+"r"):
        props=run.find(W+"rPr")
        chunk=""
        for child in run:
            if child.tag==W+"t":chunk+=escape(child.text or "")
            elif child.tag==W+"br":chunk+="<br/>"
            elif child.tag==W+"tab":chunk+="&#160;"*4
        chunk=re.sub(r" {2,}",lambda m:"&#160;"*len(m.group()),chunk)
        if props is not None:
            color=props.find(W+"color")
            if color is not None:chunk='<font color="#'+color.get(W+"val")+'">'+chunk+'</font>'
            if boolean(props,"b"):chunk='<b>'+chunk+'</b>'
        html+=chunk
    if not fix.normalized(fix.text(p)):
        html="&#160;"+"<br/>&#160;"*len(p.findall(".//"+W+"br"))
    return Paragraph(html,ParagraphStyle(sid,**cfg),bulletText="●" if prop(ppr,"numPr") is not None else None)


def render(target,line_scale=1):
    with zipfile.ZipFile(fix.TARGET) as archive:
        body=ET.fromstring(archive.read("word/document.xml")).find(W+"body")
    flows=[]
    for node in body:
        if node.tag==W+"p":flows.append(para(node,line_scale))
        elif node.tag==W+"tbl":
            widths=[int(c.get(W+"w"))/20 for c in node.findall(W+"tblGrid/"+W+"gridCol")]
            rows=[]
            for row in node.findall(W+"tr"):
                rows.append([[para(p,line_scale) for p in c.findall(W+"p")] for c in row.findall(W+"tc")])
            table=Table(rows,colWidths=widths,hAlign="LEFT")
            table.setStyle(TableStyle([("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
                                       ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
                                       ("VALIGN",(0,0),(-1,-1),"TOP")]))
            flows.append(table)
    temp=target.with_name("_body_"+target.name)
    doc=BaseDocTemplate(str(temp),pagesize=(PAGE_W,PAGE_H),leftMargin=LEFT,rightMargin=LEFT,
                         topMargin=2660/20,bottomMargin=1860/20)
    frame=Frame(doc.leftMargin,doc.bottomMargin,doc.width,doc.height,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
    doc.addPageTemplates(PageTemplate(id="Body",frames=[frame]))
    doc.build(flows)
    with fitz.open(temp) as pdf,fitz.open(OUT/"AIO_zrodlo_Google.pdf") as original:
        reference=original[0]
        header=fitz.Rect(0,0,reference.rect.width,125)
        rule=fitz.Rect(0,752,reference.rect.width,773)
        footer=fitz.Rect(0,773,500,reference.rect.height)
        for i,page in enumerate(pdf):
            for clip in [header,rule,footer]:
                page.show_pdf_page(clip,original,0,clip=clip,overlay=True)
            font=fitz.Font(fontfile=r"C:\Windows\Fonts\arial.ttf")
            number=f"{i+1} / {len(pdf)}"
            width=font.text_length(number,fontsize=9)
            page.insert_text((RIGHT-width,782.85),number,fontname="FooterArial",fontfile=r"C:\Windows\Fonts\arial.ttf",fontsize=9,color=(.2078,.2549,.2314))
        pdf.set_metadata({"title":"Siz3r — wypełniona odpowiedź AIO, poprawiony układ","author":"Siz3r","subject":"Lokalny podgląd poprawionego DOCX; nie jest eksportem z Google Docs"})
        pdf.save(target,garbage=4,deflate=True)
    return target


def verify(target,images=False):
    with zipfile.ZipFile(fix.TARGET) as archive:
        body=ET.fromstring(archive.read("word/document.xml")).find(W+"body")
    expected=[fix.normalized(fix.text(p)) for p in body.findall(".//"+W+"p") if fix.normalized(fix.text(p))]
    with fitz.open(target) as pdf:
        text=fix.normalized(" ".join(page.get_text() for page in pdf))
        for value in expected:
            # Heading numbers and labels become separated by a tab/space.
            if re.match(r"^0[1-7]",value):value=value[2:]
            assert value in text,value
        assert "Kapitał" not in text
        assert 3<=len(pdf)<=5,len(pdf)
        for page in pdf:
            content=page.get_textbox(fitz.Rect(LEFT,125,RIGHT,752))
            assert fix.normalized(content),"Page contains only furniture"
            lines=[l for b in page.get_text("dict")["blocks"] if b["type"]==0 for l in b["lines"] if fix.normalized("".join(s["text"] for s in l["spans"]))]
            body_lines=[l for l in lines if l["bbox"][1]>=125 and l["bbox"][3]<=752]
            assert all(l["bbox"][0]>=LEFT-.5 and l["bbox"][2]<=RIGHT+.5 for l in body_lines)
            for earlier,later in zip(body_lines,body_lines[1:]):
                if earlier["bbox"][2]<=later["bbox"][0]+1 or later["bbox"][2]<=earlier["bbox"][0]+1:continue
                assert earlier["bbox"][3]<=later["bbox"][1]+1,(earlier["bbox"],later["bbox"])
            print("PAGE",page.number+1,"body lines",len(body_lines),"last line",round(max(l["bbox"][3] for l in body_lines),1))
            if images:page.get_pixmap(matrix=fitz.Matrix(1.3,1.3)).save(target.with_name(target.stem+f"_strona_{page.number+1}.png"))
        print(f"OK: {target.name}; {len(pdf)} pages; all wording retained, no blank body pages or overlapping text. Local preview.")


if __name__=="__main__":
    verify(render(OUT/"Siz3r_AIO_wypelniony_podglad.pdf"),images=True)
    verify(render(OUT/"_kontrola_interlinia_110.pdf",line_scale=1.1))
