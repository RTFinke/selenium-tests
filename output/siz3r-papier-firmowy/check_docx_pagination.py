"""Local layout checks for the revised DOCX, not a Google Docs conversion."""
from pathlib import Path
import sys
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph
from reportlab.lib import colors

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / '.tmp-pdf-tools'))
import pymupdf as fitz

pdfmetrics.registerFont(TTFont('Arial', 'C:/Windows/Fonts/arial.ttf'))
pdfmetrics.registerFont(TTFont('Arial-Bold', 'C:/Windows/Fonts/arialbd.ttf'))
pdfmetrics.registerFontFamily('Arial', normal='Arial', bold='Arial-Bold', italic='Arial', boldItalic='Arial-Bold')
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
OUT = ROOT / 'google-docs'

with zipfile.ZipFile(OUT / 'Siz3r_AIO_Google_Docs_v2.docx') as package:
    document = ET.fromstring(package.read('word/document.xml'))
    styles = ET.fromstring(package.read('word/styles.xml'))
    assert not document.findall('.//' + W + 'pageBreakBefore')
    assert not document.findall('.//' + W + 'br')

configs = {}
for item in styles.findall(W + 'style'):
    name = item.get(W + 'styleId')
    if name == 'Normal':
        continue
    rpr, ppr = item.find(W + 'rPr'), item.find(W + 'pPr')
    spacing = ppr.find(W + 'spacing')
    settings = dict(fontName='Arial-Bold' if rpr.find(W + 'b') is not None else 'Arial',
                    fontSize=int(rpr.find(W + 'sz').get(W + 'val')) / 2,
                    leading=int(spacing.get(W + 'line')) / 20,
                    textColor=colors.HexColor('#' + rpr.find(W + 'color').get(W + 'val')),
                    spaceBefore=0, spaceAfter=0,
                    keepWithNext=ppr.find(W + 'keepNext') is not None)
    indent = ppr.find(W + 'ind')
    if indent is not None:
        settings['leftIndent'] = int(indent.get(W + 'left')) / 20
        settings['firstLineIndent'] = -int(indent.get(W + 'hanging', '0')) / 20
    configs[name] = settings


def check(name, height, line_scale):
    flows = []
    for item in document.findall('.//' + W + 'body/' + W + 'p'):
        ppr = item.find(W + 'pPr')
        sid = ppr.find(W + 'pStyle').get(W + 'val')
        settings = dict(configs[sid])
        spacing = ppr.find(W + 'spacing')
        settings['spaceBefore'] = int(spacing.get(W + 'before', '0')) / 20
        settings['spaceAfter'] = int(spacing.get(W + 'after', '0')) / 20
        settings['leading'] *= line_scale
        text = ''
        for run in item.findall(W + 'r'):
            chunk = ''.join(escape(node.text or '') for node in run.findall(W + 't'))
            if run.find(W + 'tab') is not None:
                chunk += '&#160;&#160;'
            rpr = run.find(W + 'rPr')
            if rpr is not None and rpr.find(W + 'b') is not None:
                chunk = '<b>' + chunk + '</b>'
            text += chunk
        flows.append(Paragraph(text or '&#160;', ParagraphStyle(sid, **settings)))
    target = OUT / ('_kontrola_' + name + '.pdf')
    doc = BaseDocTemplate(str(target), pagesize=(11906/20, height),
                          leftMargin=1304/20, rightMargin=1304/20,
                          topMargin=2660/20, bottomMargin=1860/20)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates(PageTemplate(id='Body', frames=[frame]))
    doc.build(flows)
    with fitz.open(target) as pdf:
        assert all(page.get_text().strip() for page in pdf), 'Blank page in ' + name
        assert len(pdf) == 3, (name, len(pdf))
        text = '\n'.join(page.get_text() for page in pdf)
        assert 'bezrejestracyjnie' in text and 'REGON' not in text
        assert 'Z poważaniem,' in text
        print(f'OK: {name}; {len(pdf)} pages; no blank pages. Local layout model only.')


check('A4_v2', 16838/20, 1.0)
check('A4_interlinia_120_v2', 16838/20, 1.2)
check('nizsza_strona_v2', 792, 1.0)
