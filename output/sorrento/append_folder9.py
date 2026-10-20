import io,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'.tmp-pdf-tools'))
import pymupdf as fitz
from PIL import Image
OUT=Path(__file__).resolve().parent
FOLDERS=[Path(r'C:\Users\suici\Downloads\sorrentocollective.com\New folder (9)')]
def photo_path(folder,column):
    paths=list(folder.glob(f'{column}.*'))
    assert len(paths)==1
    return paths[0]
original=fitz.open(r'C:\Users\suici\Downloads\Siz3r_Wyniki_Vistula (2).pdf')
base=fitz.open(OUT/'Siz3r_Wyniki_SorrentoCollective_reshuffled.pdf')
result=fitz.open()
result.insert_pdf(base,from_page=0,to_page=len(base)-2)
for number in range(1, len(FOLDERS)+1):
    slide = fitz.open()
    slide.insert_pdf(original, from_page=1, to_page=1)
    page = slide[0]
    content = page.read_contents().decode('latin1')
    # Remove the category text object, retaining every other original element.
    content, count = re.subn(r'BT[^\n]*\(PE\\001NE\) Tj ET', '', content)
    assert count == 1
    images = sorted(
        [im for im in page.get_image_info(xrefs=True) if im['height'] > 1000],
        key=lambda im: im['bbox'][0],
    )
    assert len(images) == 3
    names = {im[0]: im[7] for im in page.get_images()}
    for column, info in enumerate(images, 1):
        path = photo_path(FOLDERS[number-1], column)
        with Image.open(path) as im:
            width, height = im.size
            if path.suffix.lower() == '.webp':
                buffer = io.BytesIO()
                im.save(buffer, format='PNG')
                stream = buffer.getvalue()
            else:
                stream = path.read_bytes()
        page.replace_image(info['xref'], stream=stream)
        # Fill the original rounded frame with proportional scaling and clipping.
        name = names[info['xref']]
        pattern = r'([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm\s+/' + re.escape(name) + r' Do'
        match = re.search(pattern, content)
        assert match
        w, h, x, y = map(float, match.groups())
        contain = False
        scale = min(w / width, h / height) if contain else max(w / width, h / height)
        nw, nh = width * scale, height * scale
        nx, ny = x + (w - nw) / 2, y + (h - nh) / 2
        replacement = f'{nw:.6f} 0 0 {nh:.6f} {nx:.6f} {ny:.6f} cm\n/{name} Do'
        if contain:
            replacement = f'1 1 1 rg {x} {y} {w} {h} re f\n' + replacement
        content = re.sub(pattern, lambda _: replacement, content, count=1)
    first = page.get_contents()[0]
    page.set_contents(first)
    slide.update_stream(first, content.encode('latin1'))
    result.insert_pdf(slide)
    slide.close()

result.insert_pdf(base,from_page=len(base)-1,to_page=len(base)-1)
result.set_metadata(base.metadata)
target=OUT/'Siz3r_Wyniki_SorrentoCollective_updated.pdf'
result.save(target,garbage=4,deflate=True)
result.close()
check=fitz.open(target)
assert len(base)==9 and len(check)==10
for i in range(len(base)-1):
    assert check[i].get_pixmap().samples==base[i].get_pixmap().samples
assert check[-1].get_pixmap().samples==base[-1].get_pixmap().samples
photos=sorted([im for im in check[-2].get_image_info(xrefs=True) if im['bbox'][1]>100],key=lambda im:im['bbox'][0])
assert len(photos)==3
for column,im in enumerate(photos,1):
    with Image.open(photo_path(FOLDERS[0],column)) as source:
        embedded=Image.open(io.BytesIO(check.extract_image(im['xref'])['image']))
        assert embedded.convert('RGB').tobytes()==source.convert('RGB').tobytes()
        rect=fitz.Rect(im['bbox'])
        assert abs(rect.width/rect.height-source.width/source.height)<.001
check[-2].get_pixmap().save(OUT/'new-slide-9.png')
print('Verified: new ninth-folder slide appended; image pixels preserved; all other slides unchanged.')
print(target)
