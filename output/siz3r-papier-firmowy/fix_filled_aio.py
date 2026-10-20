"""Reflow the user's filled AIO reply, preserving every word and native lists.

Remove blank template lines and long keep-with-next chains. Leave the branded
header, footer, source document and remote Google file untouched.
"""

from copy import deepcopy
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "google-docs" / "filled"
SOURCE = OUT / "AIO_zrodlo_Google.docx"
TARGET = OUT / "Siz3r_AIO_wypelniony_poprawiony.docx"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
for prefix,uri in {
    "w": W[1:-1],
    "r":"http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "w14":"http://schemas.microsoft.com/office/word/2010/wordml",
    "wp":"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a":"http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic":"http://schemas.openxmlformats.org/drawingml/2006/picture",
}.items():
    ET.register_namespace(prefix,uri)

INK, BODY, MUTED, GREEN = "17211D","35413B","69766F","00D278"


def text(p):
    return "".join(n.text or "" for n in p.findall(".//"+W+"t"))


def normalized(value):
    return " ".join(value.replace("\u200b","").split())


SPECS = {
    "Title": dict(size=20.5,line=264,color=INK,bold=True,before=18,after=3,keep=True,lines=True,indent=0),
    "Subtitle": dict(size=9.5,line=240,color=MUTED,bold=False,before=0,after=18,keep=True,lines=True,indent=0),
    "Intro": dict(size=10.5,line=276,color=BODY,bold=False,before=0,after=8,keep=False,lines=False,indent=0),
    "Heading": dict(size=12,line=264,color=INK,bold=True,before=16,after=8,keep=True,lines=True,indent=540,hanging=540),
    "Question": dict(size=10.5,line=264,color=MUTED,bold=False,before=0,after=5,keep=True,lines=True,indent=540),
    "Answer": dict(size=10.5,line=264,color=BODY,bold=False,before=0,after=8,keep=False,lines=False,indent=540),
    "Bullet": dict(size=10.5,line=264,color=BODY,bold=False,before=0,after=1.5,keep=False,lines=True,indent=810,hanging=270),
    "Numbered": dict(size=10.5,line=264,color=BODY,bold=False,before=0,after=5,keep=False,lines=False,indent=810,hanging=270),
    "ListLabel": dict(size=10.5,line=264,color=BODY,bold=True,before=8,after=3,keep=True,lines=True,indent=540),
    "Contact": dict(size=10.5,line=264,color=BODY,bold=False,before=12,after=0,keep=True,lines=True,indent=540),
    "Signature": dict(size=10.5,line=264,color=BODY,bold=False,before=8,after=4,keep=True,lines=True,indent=540),
    "Signer": dict(size=11,line=240,color=INK,bold=True,before=0,after=1,keep=True,lines=True,indent=540),
    "Phone": dict(size=10.5,line=240,color=BODY,bold=False,before=0,after=0,keep=False,lines=True,indent=540),
}


def rpr(spec, *, color=None):
    result=ET.Element(W+"rPr")
    ET.SubElement(result,W+"rFonts",{W+"ascii":"Arial",W+"hAnsi":"Arial",W+"cs":"Arial",W+"eastAsia":"Arial"})
    for tag in ["b","bCs"]:
        ET.SubElement(result,W+tag,{W+"val":str(int(spec["bold"]))})
    for tag in ["i","iCs"]:
        ET.SubElement(result,W+tag,{W+"val":"0"})
    ET.SubElement(result,W+"color",{W+"val":color or spec["color"]})
    for tag in ["sz","szCs"]:
        ET.SubElement(result,W+tag,{W+"val":str(round(spec["size"]*2))})
    ET.SubElement(result,W+"lang",{W+"val":"pl-PL"})
    return result


def ppr(kind, spec, num=None):
    result=ET.Element(W+"pPr")
    ET.SubElement(result,W+"pStyle",{W+"val":"Siz3r"+kind})
    ET.SubElement(result,W+"keepNext",{W+"val":str(int(spec["keep"]))})
    ET.SubElement(result,W+"keepLines",{W+"val":str(int(spec["lines"]))})
    ET.SubElement(result,W+"pageBreakBefore",{W+"val":"0"})
    ET.SubElement(result,W+"widowControl",{W+"val":"1"})
    if num is not None:
        result.append(deepcopy(num))
    if kind=="Heading":
        tabs=ET.SubElement(result,W+"tabs")
        ET.SubElement(tabs,W+"tab",{W+"val":"left",W+"pos":"540"})
    ET.SubElement(result,W+"spacing",{W+"before":str(round(spec["before"]*20)),W+"after":str(round(spec["after"]*20)),
                                       W+"line":str(spec["line"]),W+"lineRule":"auto"})
    attrs={W+"left":str(spec["indent"]),W+"right":"0"}
    attrs[W+"hanging" if "hanging" in spec else W+"firstLine"]=str(spec.get("hanging",0))
    ET.SubElement(result,W+"ind",attrs)
    ET.SubElement(result,W+"jc",{W+"val":"left"})
    if kind=="Heading":
        ET.SubElement(result,W+"outlineLvl",{W+"val":"1"})
    result.append(rpr(spec))
    return result


def trim_blank_breaks(p):
    # Preserve intentional breaks inside real text, remove empty lines at edges.
    leaves = [(parent,node) for parent in p.iter() for node in list(parent) if node.tag in [W+"t",W+"br"]]
    filled = [i for i,(_,n) in enumerate(leaves) if n.tag==W+"t" and normalized(n.text or "")]
    if not filled:
        return
    first,last = min(filled),max(filled)
    for i,(parent,node) in enumerate(leaves):
        if node.tag==W+"br" and (i<first or i>last):
            parent.remove(node)


def classify(p):
    value=normalized(text(p))
    old=p.find(W+"pPr")
    num=old.find(W+"numPr") if old is not None else None
    if value=="Wirtualna przymierzalnia": return "Title"
    if value.startswith("Odpowiedź na zapytanie"): return "Subtitle"
    if value.startswith(("Szanowny Panie","dziękujemy za zainteresowanie")): return "Intro"
    if re.match(r"^0[1-7]",value): return "Heading"
    if value.startswith(("Czy ","Jak ","Jakich ")): return "Question"
    if value=="Z poważaniem,": return "Signature"
    if value=="Bogumił Butryn": return "Signer"
    if value.startswith("tel."): return "Phone"
    if value.startswith("W przypadku wątpliwości"): return "Contact"
    if value in ["Zużycie kredytów:","Cennik pakietów:"]: return "ListLabel"
    if num is not None: return "Bullet"
    if re.match(r"^[12]\. moduł",value): return "Numbered"
    return "Answer"


def build():
    with zipfile.ZipFile(SOURCE) as archive:
        parts={k:archive.read(k) for k in archive.namelist()}
    document=ET.fromstring(parts["word/document.xml"])
    body=document.find(W+"body")
    before=[normalized(text(p)) for p in body.findall(".//"+W+"p") if normalized(text(p))]
    removed=0
    kinds=[]
    for p in list(body):
        if p.tag!=W+"p": continue
        if not normalized(text(p)):
            body.remove(p)
            removed+=1
            continue
        kind=classify(p)
        spec=dict(SPECS[kind])
        if kind=="Heading" and normalized(text(p)).startswith("01"):
            spec["before"]=8
        if kind=="Intro" and normalized(text(p)).startswith("dziękujemy"):
            spec["after"]=16
        old=p.find(W+"pPr")
        num=old.find(W+"numPr") if old is not None else None
        new=ppr(kind,spec,num)
        if old is not None: p.remove(old)
        p.insert(0,new)
        trim_blank_breaks(p)
        for run in p.findall(".//"+W+"r"):
            props=run.find(W+"rPr")
            color=GREEN if kind=="Heading" and re.match(r"^0[1-7]$",normalized(text(run))) else None
            if props is not None:run.remove(props)
            run.insert(0,rpr(spec,color=color))
        kinds.append(kind)
    after=[normalized(text(p)) for p in body.findall(".//"+W+"p") if normalized(text(p))]
    assert before==after,"Text changed"
    assert kinds.count("Heading")==7 and kinds.count("Question")==10
    assert kinds.count("Bullet")==10
    assert not any(not normalized(text(p)) for p in body.findall(W+"p"))
    for p in body.findall(W+"p"):
        if classify(p) in ["Answer","Bullet","Numbered"]:
            assert p.find(W+"pPr/"+W+"keepNext").get(W+"val")=="0"
    styles=ET.fromstring(parts["word/styles.xml"])
    for kind,spec in SPECS.items():
        s=ET.SubElement(styles,W+"style",{W+"type":"paragraph",W+"styleId":"Siz3r"+kind})
        ET.SubElement(s,W+"name",{W+"val":"Siz3r "+kind})
        ET.SubElement(s,W+"basedOn",{W+"val":"Normal"})
        s.append(ppr(kind,spec))
        s.find(W+"pPr").remove(s.find(W+"pPr/"+W+"pStyle"))
        s.find(W+"pPr").remove(s.find(W+"pPr/"+W+"rPr"))
        s.append(rpr(spec))
    # Match bullet marker and text indents in the native numbering definitions.
    numbering=ET.fromstring(parts["word/numbering.xml"])
    for level in numbering.findall(".//"+W+"lvl"):
        if level.get(W+"ilvl")=="0":
            indent=level.find(W+"pPr/"+W+"ind")
            if indent is not None:indent.attrib={W+"left":"810",W+"hanging":"270"}
    settings=ET.fromstring(parts["word/settings.xml"])
    update=settings.find(W+"updateFields")
    if update is None:update=ET.SubElement(settings,W+"updateFields")
    update.set(W+"val","true")
    for key,tree in {"word/document.xml":document,"word/styles.xml":styles,"word/numbering.xml":numbering,"word/settings.xml":settings}.items():
        parts[key]=ET.tostring(tree,encoding="utf-8",xml_declaration=True)
    core=ET.fromstring(parts["docProps/core.xml"])
    dc="{http://purl.org/dc/elements/1.1/}"
    for key,value in {"title":"Siz3r — wypełniona odpowiedź AIO, poprawiony układ",
                      "description":"Wypełniony dokument z poprawionymi odstępami, wcięciami i przepływem tekstu."}.items():
        node=core.find(dc+key)
        if node is None:node=ET.SubElement(core,dc+key)
        node.text=value
    parts["docProps/core.xml"]=ET.tostring(core,encoding="utf-8",xml_declaration=True)
    with zipfile.ZipFile(TARGET,"w",zipfile.ZIP_DEFLATED) as archive:
        for key,value in parts.items():archive.writestr(key,value)
    with zipfile.ZipFile(TARGET) as archive:
        assert archive.testzip() is None
        for key in archive.namelist():
            if key.endswith((".xml",".rels")):ET.fromstring(archive.read(key))
        with zipfile.ZipFile(SOURCE) as original:
            for key in ["word/header1.xml","word/footer1.xml","word/_rels/header1.xml.rels","word/media/image1.png"]:
                assert archive.read(key)==original.read(key)
        rebuilt=ET.fromstring(archive.read("word/document.xml"))
        assert [normalized(text(p)) for p in rebuilt.find(W+"body").findall(".//"+W+"p") if normalized(text(p))]==before
    print(f"OK: {TARGET.name}; preserved all {len(before)} nonempty paragraphs, 7 sections, 10 questions, 10 bullets; removed {removed} empty body paragraphs.")
    (OUT/"Jak_korzystac_z_poprawionej_wersji.txt").write_text(
        "SIZ3R — WYPEŁNIONA ODPOWIEDŹ AIO, POPRAWIONY UKŁAD\n\n"
        "Prześlij Siz3r_AIO_wypelniony_poprawiony.docx na Dysk Google, otwórz w Dokumentach Google i zapisz jako Dokumenty Google. "
        "Zachowaj format A4 z podziałem na strony. Plik zawiera już wszystkie wpisane odpowiedzi oraz podpis.\n\n"
        "Odstępy ustawia się w formatowaniu akapitów. Unikaj dodawania serii pustych wierszy do przesuwania tekstu. "
        "Długie odpowiedzi mogą przechodzić między stronami; nagłówki i pytania są powiązane z następującym po nich tekstem.\n\n"
        "PDF jest lokalnym podglądem poprawionej kopii. Przed wysłaniem sprawdź końcowy układ w Google Docs i stamtąd pobierz PDF. "
        "Dokument pod dotychczasowym linkiem pozostaje bez zmian.\n",encoding="utf-8-sig")
    return TARGET


if __name__=="__main__":
    build()
