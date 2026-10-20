"""Move the complete UX question/answer onto the BHP page, preserving styles."""

from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
import zipfile
import xml.etree.ElementTree as ET

import fix_spacing_preserve_style as original
import preview_spacing_preserve_style as preview

W = original.W
OUT = original.ROOT / "google-docs" / "punkt-04-podzial"
SOURCE = original.ROOT / "google-docs" / "Siz3r_AIO_ODSTEPY_BEZ_ZMIANY_FORMATOWANIA.docx"
TARGET = OUT / "Siz3r_AIO_punkt_04_podzial_miedzy_pytaniami.docx"


def sections(body):
    result = []
    for paragraph in body.findall(W + "p"):
        if original.heading(paragraph):
            result.append([])
        if result:
            result[-1].append(paragraph)
    assert len(result) == 7
    return result


def build():
    OUT.mkdir(exist_ok=True)
    with zipfile.ZipFile(SOURCE) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    document = ET.fromstring(parts["word/document.xml"])
    untouched = deepcopy(document)
    groups = sections(document.find(W + "body"))
    ux = groups[3]
    assert len(ux) == 5
    assert original.norm(original.text(ux[1])).startswith("Czy klient")
    assert original.norm(original.text(ux[2])).startswith("Obecnie zaimplementowane")
    assert original.norm(original.text(ux[3])).startswith("Jak z formalnego")

    # Keep BHP, the UX heading and its complete first question/answer together.
    original.set_flag(groups[2][-1].find(W + "pPr"), "keepNext", True)
    original.set_flag(ux[0].find(W + "pPr"), "pageBreakBefore", False)
    original.set_flag(ux[2].find(W + "pPr"), "keepNext", False)
    # Start the next page at the independent RODO question.
    original.set_flag(ux[3].find(W + "pPr"), "pageBreakBefore", True)

    assert original.canonical_without_allowed_changes(document) == original.canonical_without_allowed_changes(untouched)
    parts["word/document.xml"] = ET.tostring(document, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(TARGET, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(TARGET) as target:
        assert target.testzip() is None
        for name in source.namelist():
            if name != "word/document.xml":
                assert source.read(name) == target.read(name), name
            if name.endswith((".xml", ".rels")):
                ET.fromstring(target.read(name))
    print("DOCX verified: only four pagination flags changed; all text and style properties preserved.")
    return document


def verify_pdf(path, document, images=False):
    renderer = preview.renderer
    body = document.find(W + "body")
    groups = sections(body)
    with renderer.fitz.open(path) as pdf:
        texts = [original.norm(page.get_text()) for page in pdf]
        combined = " ".join(texts)
        for p in body.findall(".//" + W + "p"):
            value = original.norm(original.text(p))
            if original.heading(p):
                value = value[2:]
            assert not value or value in combined, value

        def page_for(paragraphs):
            values = [original.norm(original.text(p))[2:] if original.heading(p) else original.norm(original.text(p)) for p in paragraphs]
            matches = [i + 1 for i, text in enumerate(texts) if all(value in text for value in values)]
            assert len(matches) == 1, ("Question or answer split", values, matches)
            return matches[0]

        placements = []
        for i, group in enumerate(groups):
            if i == 3:
                placements.extend([("04 UX", page_for(group[:3])), ("04 RODO", page_for(group[3:]))])
            else:
                placements.append((f"{i+1:02}", page_for(group)))
        assert page_for(groups[2]) == page_for(groups[3][:3]) == 2, placements
        assert page_for(groups[3][3:]) == 3, placements
        assert len(pdf) == 4, len(pdf)
        for page in pdf:
            lines = [line for block in page.get_text("dict")["blocks"] if block["type"] == 0 for line in block["lines"] if original.norm("".join(span["text"] for span in line["spans"]))]
            body_lines = [line for line in lines if line["bbox"][1] >= 125 and line["bbox"][3] <= 752]
            assert body_lines, "Empty body page"
            assert max(line["bbox"][3] for line in body_lines) < 749
            assert all(line["bbox"][0] >= renderer.LEFT - .5 and line["bbox"][2] <= renderer.RIGHT + .5 for line in body_lines)
            print(f"Page {page.number+1}: last body line y={max(line['bbox'][3] for line in body_lines):.1f}")
            if images:
                page.get_pixmap(matrix=renderer.fitz.Matrix(1.3, 1.3)).save(path.with_name(path.stem + f"_strona_{page.number+1}.png"))
        print(path.name, placements)


if __name__ == "__main__":
    document = build()
    preview.renderer.fix = SimpleNamespace(TARGET=TARGET)
    preview.renderer.para = preview.para
    pdf = OUT / "Siz3r_AIO_punkt_04_podglad.pdf"
    verify_pdf(preview.renderer.render(pdf), document, images=True)
    stress = OUT / "_kontrola_interlinia_110.pdf"
    verify_pdf(preview.renderer.render(stress, line_scale=1.1), document)
