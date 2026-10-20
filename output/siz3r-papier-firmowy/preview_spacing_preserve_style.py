"""Preview spacing-only edits using original run styles and intact sections."""

from pathlib import Path
from xml.sax.saxutils import escape
import re
import zipfile
import xml.etree.ElementTree as ET

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph

import fix_spacing_preserve_style as source
import preview_filled_aio as renderer

W=source.W
pdfmetrics.registerFont(TTFont("Arial-Italic",r"C:\Windows\Fonts\ariali.ttf"))
pdfmetrics.registerFont(TTFont("Arial-BoldItalic",r"C:\Windows\Fonts\arialbi.ttf"))
pdfmetrics.registerFontFamily("Arial",normal="Arial",bold="Arial-Bold",italic="Arial-Italic",boldItalic="Arial-BoldItalic")


def val(parent,tag,default):
    node=parent.find(W+tag) if parent is not None else None
    return node.get(W+"val",default) if node is not None else default


def para(p,line_scale=1):
    pr=p.find(W+"pPr")
    mark=pr.find(W+"rPr")
    default_size=float(val(mark,"sz","22"))/2
    base_bold=val(mark,"b","0")=="1"
    base_italic=val(mark,"i","0")=="1"
    base_color=val(mark,"color","35413B")
    visible=[r for r in p.findall(".//"+W+"r") if source.norm(source.text(r))]
    max_size=max([float(val(r.find(W+"rPr"),"sz",str(round(default_size*2))))/2 for r in visible] or [default_size])
    family={ (False,False):"Arial",(True,False):"Arial-Bold",(False,True):"Arial-Italic",(True,True):"Arial-BoldItalic"}
    spacing=pr.find(W+"spacing")
    indent=pr.find(W+"ind")
    left=int(indent.get(W+"left","0"))/20 if indent is not None else 0
    hanging=int(indent.get(W+"hanging","0"))/20 if indent is not None else 0
    first=int(indent.get(W+"firstLine","0"))/20 if indent is not None else 0
    style=ParagraphStyle("Original",fontName=family[base_bold,base_italic],fontSize=max_size,
                         leading=max_size*1.15*int(spacing.get(W+"line","240"))/240*line_scale,
                         textColor=colors.HexColor("#"+base_color),leftIndent=left,
                         firstLineIndent=-hanging if hanging else first,
                         spaceBefore=int(spacing.get(W+"before","0"))/20,
                         spaceAfter=int(spacing.get(W+"after","0"))/20,
                         keepWithNext=val(pr,"keepNext","0")=="1",allowOrphans=0,allowWidows=0,splitLongWords=False,
                         alignment={"left":0,"right":2,"center":1}.get(val(pr,"jc","left"),0))
    numbered=pr.find(W+"numPr") is not None
    if numbered:
        style.firstLineIndent=0
        style.bulletIndent=left-hanging
        style.bulletFontName="Arial"
        style.bulletFontSize=max_size
    html=""
    for r in p.findall(".//"+W+"r"):
        rp=r.find(W+"rPr")
        fragment=""
        for node in r:
            if node.tag==W+"t":fragment+=escape(node.text or "")
            elif node.tag==W+"br":fragment+="<br/>"
            elif node.tag==W+"tab":fragment+="&#160;"*4
        fragment=re.sub(r" {2,}",lambda m:"&#160;"*len(m.group()),fragment)
        size=float(val(rp,"sz",str(round(default_size*2))))/2
        fragment='<font size="'+str(size)+'" color="#'+val(rp,"color",base_color)+'">'+fragment+'</font>'
        if val(rp,"b",str(int(base_bold)))=="1":fragment="<b>"+fragment+"</b>"
        if val(rp,"i",str(int(base_italic)))=="1":fragment="<i>"+fragment+"</i>"
        if val(rp,"u","none") not in ["none","0"]:fragment="<u>"+fragment+"</u>"
        html+=fragment
    if not source.norm(source.text(p)):
        html="&#160;"+"<br/>&#160;"*len(p.findall(".//"+W+"br"))
    result=Paragraph(html,style,bulletText="●" if numbered else None)
    if val(pr,"pageBreakBefore","0")=="1":result.style.pageBreakBefore=True
    return result


def verify(path,images=False):
    with zipfile.ZipFile(source.TARGET) as archive:
        body=ET.fromstring(archive.read("word/document.xml")).find(W+"body")
    expected=[source.norm(source.text(p)) for p in body.findall(".//"+W+"p") if source.norm(source.text(p))]
    sections=[]
    for p in body.findall(W+"p"):
        if source.heading(p):sections.append([])
        if sections:sections[-1].append(source.norm(source.text(p)))
    with renderer.fitz.open(path) as pdf:
        page_texts=[source.norm(p.get_text()) for p in pdf]
        all_text=" ".join(page_texts)
        for value in expected:
            if re.match(r"^0[1-7]",value):value=value[2:]
            assert value in all_text,value
        for i,section in enumerate(sections):
            values=[v[2:] if re.match(r"^0[1-7]",v) else v for v in section]
            matches=[n for n,text in enumerate(page_texts) if all(value in text for value in values)]
            assert len(matches)==1,("Section split",i+1,matches)
            print("SECTION",i+1,"fully on page",matches[0]+1)
        for page in pdf:
            assert source.norm(page.get_textbox(renderer.fitz.Rect(renderer.LEFT,125,renderer.RIGHT,752)))
            if images:page.get_pixmap(matrix=renderer.fitz.Matrix(1.3,1.3)).save(path.with_name(path.stem+f"_strona_{page.number+1}.png"))
        print(f"OK: {path.name}; {len(pdf)} pages; all seven sections intact; original bold and italic rendered. Local preview, not a Google export.")


if __name__=="__main__":
    renderer.fix=source
    renderer.para=para
    # The two downloads are the same original export; reuse its vector furniture.
    assert (source.OUT/"AIO_oryginal_Google.pdf").read_bytes()==(renderer.OUT/"AIO_zrodlo_Google.pdf").read_bytes()
    target=source.OUT/"Siz3r_AIO_odstepy_oryginalny_styl_podglad.pdf"
    verify(renderer.render(target),images=True)
    verify(renderer.render(source.OUT/"_kontrola_interlinia_110.pdf",line_scale=1.1))
