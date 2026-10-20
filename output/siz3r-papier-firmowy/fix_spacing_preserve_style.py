"""Change spacing and pagination only, preserving the original filled styling.

Only document.xml is changed. Run text/properties, paragraph font properties,
styles, numbering, indents, alignment, headers, footer and image remain intact.
"""

from copy import deepcopy
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"google-docs"/"odstepy-bez-zmiany-stylu"
SOURCE=OUT/"AIO_oryginal_Google.docx"
TARGET=OUT/"Siz3r_AIO_poprawione_odstepy_oryginalny_styl.docx"
W="{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
for prefix,uri in {"w":W[1:-1],"w14":"http://schemas.microsoft.com/office/word/2010/wordml",
                   "r":"http://schemas.openxmlformats.org/officeDocument/2006/relationships"}.items():
    ET.register_namespace(prefix,uri)


def text(p):
    return "".join(t.text or "" for t in p.findall(".//"+W+"t"))


def norm(value):
    return " ".join(value.replace("\u200b","").split())


def heading(p):
    return re.match(r"^0[1-7]",norm(text(p))) is not None


def trim_breaks(p):
    items=[(parent,n) for parent in p.iter() for n in parent if n.tag in [W+"t",W+"br"]]
    filled=[i for i,(_,n) in enumerate(items) if n.tag==W+"t" and norm(n.text or "")]
    if not filled:return
    for i,(parent,n) in enumerate(items):
        if n.tag==W+"br" and n.get(W+"type") not in ["page","column"] and (i<min(filled) or i>max(filled)):
            parent.remove(n)


def set_flag(ppr,name,value):
    node=ppr.find(W+name)
    if node is None:
        node=ET.Element(W+name)
        # Pagination controls precede numbering, borders, tabs and spacing.
        index=1 if ppr.find(W+"pStyle") is not None else 0
        ppr.insert(index,node)
    node.set(W+"val",str(int(value)))


def spacing(p,before,after):
    ppr=p.find(W+"pPr")
    node=ppr.find(W+"spacing")
    assert node is not None
    node.set(W+"before",str(round(before*20)))
    node.set(W+"after",str(round(after*20)))


def fingerprint(p):
    ppr=p.find(W+"pPr")
    protected=["pStyle","rPr","numPr","ind","jc","tabs","outlineLvl"]
    return {
        "text":[t.text for t in p.findall(".//"+W+"t")],
        "runs":[ET.tostring(r.find(W+"rPr"),encoding="unicode") if r.find(W+"rPr") is not None else None for r in p.findall(".//"+W+"r")],
        "paragraph":[ET.tostring(ppr.find(W+n),encoding="unicode") if ppr.find(W+n) is not None else None for n in protected],
        "line":{k:v for k,v in ppr.find(W+"spacing").attrib.items() if k not in [W+"before",W+"after"]},
    }


def canonical_without_allowed_changes(tree):
    tree=deepcopy(tree)
    body=tree.find(W+"body")
    for p in list(body):
        if p.tag!=W+"p":continue
        if not norm(text(p)):
            body.remove(p)
            continue
        trim_breaks(p)
        ppr=p.find(W+"pPr")
        for tag in ["keepNext","keepLines","pageBreakBefore"]:
            for n in ppr.findall(W+tag):ppr.remove(n)
        sp=ppr.find(W+"spacing")
        for attr in [W+"before",W+"after"]:sp.attrib.pop(attr,None)
    return ET.tostring(tree,encoding="utf-8")


def build():
    with zipfile.ZipFile(SOURCE) as archive:
        original={k:archive.read(k) for k in archive.namelist()}
    document=ET.fromstring(original["word/document.xml"])
    untouched=deepcopy(document)
    body=document.find(W+"body")
    protected=[fingerprint(p) for p in body.findall(W+"p") if norm(text(p))]
    removed=0
    for p in list(body):
        if p.tag!=W+"p":continue
        if not norm(text(p)):
            body.remove(p)
            removed+=1
            continue
        value=norm(text(p))
        trim_breaks(p)
        if heading(p):spacing(p,0 if value.startswith("01") else 16,8)
        elif value.startswith(("Czy ","Jak ","Jakich ")):spacing(p,0,6)
        elif p.find(W+"pPr/"+W+"numPr") is not None:spacing(p,0,2)
        elif value in ["Zużycie kredytów:","Cennik pakietów:"]:spacing(p,8,4)
        elif value.startswith("W przypadku wątpliwości"):spacing(p,14,4)
        elif value=="Z poważaniem,":spacing(p,8,8)
        elif value=="Bogumił Butryn" or value.startswith("tel."):spacing(p,0,0)
        elif value.startswith(("Wirtualna przymierzalnia","Odpowiedź na zapytanie","Szanowny Panie","dziękujemy za zainteresowanie")):
            pass
        else:spacing(p,0,8)
    sections=[]
    active=None
    for p in body.findall(W+"p"):
        if heading(p):
            active=[]
            sections.append(active)
        if active is not None:active.append(p)
    assert len(sections)==7
    for section in sections:
        for i,p in enumerate(section):
            ppr=p.find(W+"pPr")
            set_flag(ppr,"keepNext",i<len(section)-1)
            set_flag(ppr,"keepLines",True)
    # Balance the middle pages without splitting the client's numbered items.
    set_flag(sections[3][0].find(W+"pPr"),"pageBreakBefore",True)
    assert [fingerprint(p) for p in body.findall(W+"p") if norm(text(p))]==protected,"A word or style was changed"
    assert canonical_without_allowed_changes(untouched)==canonical_without_allowed_changes(document),"Changes outside spacing/pagination"
    parts=dict(original)
    parts["word/document.xml"]=ET.tostring(document,encoding="utf-8",xml_declaration=True)
    with zipfile.ZipFile(TARGET,"w",zipfile.ZIP_DEFLATED) as archive:
        for key,value in parts.items():archive.writestr(key,value)
    with zipfile.ZipFile(TARGET) as archive:
        assert archive.testzip() is None
        for key in archive.namelist():
            if key.endswith((".xml",".rels")):ET.fromstring(archive.read(key))
            if key!="word/document.xml":assert archive.read(key)==original[key],key
        verified=ET.fromstring(archive.read("word/document.xml"))
        assert canonical_without_allowed_changes(untouched)==canonical_without_allowed_changes(verified)
    print(f"OK: {TARGET.name}. All wording, fonts, sizes, bold/italic, colors, indents and original closing preserved. {removed} empty paragraphs removed; 7 sections kept together.")
    return TARGET


if __name__=="__main__":
    build()
