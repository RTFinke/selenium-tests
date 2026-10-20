from pathlib import Path
from email import policy
from email.parser import BytesParser
import re

dest=Path(__file__).resolve().parent.parent/'siz3r-mail-z-naglowkiem'
html=(dest/'Siz3r_Oferta_szablon.html').read_text(encoding='utf-8')
(dest/'Siz3r_Oferta_podglad.html').write_text(html,encoding='utf-8')
css=re.search(r'<style type="text/css">.*?</style>',html,re.S)[0]
body=re.search(r'<body[^>]*>(.*?)</body>',html,re.S)[1]
(dest/'Siz3r_Roundcube_do_wklejenia.txt').write_text(css+'\n'+body,encoding='utf-8')
message=BytesParser(policy=policy.SMTP).parsebytes((dest/'Siz3r_Oferta_podglad.eml').read_bytes())
message.get_body(preferencelist=('html',)).set_content(html,subtype='html',charset='utf-8',cte='quoted-printable')
(dest/'Siz3r_Oferta_podglad.eml').write_bytes(message.as_bytes(policy=policy.SMTP))

p=dest/'README.txt'
text=p.read_text(encoding='utf-8').replace('przed podpisem, przed linią stopki, linia→tekst stopki oraz\ntekst stopki→dół karty. 24 px: tytuł→podtytuł oraz między akapitami.', 'przed podpisem, przed linią stopki i tekst stopki→dół karty.\n24 px: tytuł→podtytuł, między akapitami oraz linia→tekst stopki.')
p.write_text(text,encoding='utf-8')
p=dest/'Lista_poprawek.txt'
text=p.read_text(encoding='utf-8').replace('wewnętrzne paddingi stopki. 24 px między akapitami.', 'boki i dolny padding stopki. 24 px między akapitami oraz od linii\ndo tekstu stopki, zgodnie z ostatnią zaakceptowaną korektą.')
p.write_text(text,encoding='utf-8')
print('Updated HTML, preview, Roundcube, EML and spacing documentation.')
