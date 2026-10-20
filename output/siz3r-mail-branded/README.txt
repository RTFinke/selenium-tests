SIZ3R — SZABLON MAILOWY

Układ na podstawie Interview Invitation Email.html: zwarty nagłówek,
duża ilustracja, sześć punktów z zielonymi ikonami i mała stopka.
Polska treść przedstawia osobistą propozycję współpracy z siz3r.
Przed wysyłką dopasuj powitanie i akapity do konkretnego odbiorcy.

PLIKI
Siz3r_Email_podglad.html — podgląd w przeglądarce; korzysta z lokalnych
obrazów w assets. Otwieraj po rozpakowaniu całego pakietu ZIP.
Siz3r_Email_szablon.html — pełny HTML do wysyłki. Zastąp placeholdery
publicznymi adresami HTTPS odpowiednich grafik albo użyj mechanizmu
osadzania obrazów programu wysyłającego:
  {{logo_url}} — assets/siz3r-logo.png
  {{hero_url}} — assets/siz3r-illustration.png
  {{check_icon_url}} — assets/siz3r-check.png
  {{round_logo_url}} — assets/siz3r-round.jpg
  {{linkedin_icon_url}} — assets/icon-linkedin.png
  {{instagram_icon_url}} — assets/icon-instagram.png
  {{tiktok_icon_url}} — assets/icon-tiktok.png
  {{youtube_icon_url}} — assets/icon-youtube.png
Adres ikony zastąp we wszystkich sześciu miejscach.
Siz3r_Email_Roundcube.txt — kod treści do edytora HTML w Roundcube.
Siz3r_Email_podglad.eml — plik wersji roboczej z wersją tekstową i HTML
oraz ośmioma obrazami osadzonymi przez CID; bez adresu odbiorcy.
Plik nie został wysłany. Jego otwarcie i edycja zależą od programu
pocztowego; w Roundcube korzystaj z instrukcji poniżej.
Siz3r_Email_tekst.txt — treść wiadomości bez formatowania.
Zrzuty PNG — podglądy wyglądu na komputerze i telefonie.
Weryfikacja.txt — zakres sprawdzeń i ich ograniczenia.
Grafiki_prompty.txt — opis poleceń użytych przy przygotowaniu ilustracji
i zielonej ikony w generatorze obrazów.
Pakiet ZIP — szablon, podglądy, instrukcje i wszystkie osiem grafik.

OBRAZY
Szablon zawiera trzynaście elementów obrazu, ale tylko osiem plików:
logo w nagłówku, duża ilustracja, jedna ikona użyta sześć razy
oraz okrągły znak i cztery ikony społecznościowe w stopce.
Nie trzeba tworzyć sześciu kopii zielonej ikony.
Logo i okrągły znak pochodzą z przekazanych plików siz3r. Ilustracja
i ikona nawiązują do oryginalnego szablonu i mają zieloną kolorystykę.
Ikony LinkedIn, Instagram, TikTok i YouTube pochodzą bez zmian
z wcześniejszej wiadomości siz3r w pliku EML. Odnośniki do profili
przeniesiono z jej podpisu; nie weryfikowano ich ponownie.

WYSYŁKA W EHOST / ROUNDCUBE
1. Otwórz Siz3r_Email_Roundcube.txt w Notatniku i skopiuj cały kod.
2. Włącz HTML w oknie nowej wiadomości. Na pasku formatowania otwórz
   Kod źródłowy (<>), zastąp całą zawartość kodem i zatwierdź.
3. Przez Załącz / Dołącz plik dodaj osiem plików z katalogu assets:
   siz3r-logo.png, siz3r-illustration.png, siz3r-check.png,
   siz3r-round.jpg, icon-linkedin.png, icon-instagram.png,
   icon-tiktok.png, icon-youtube.png. Każdy plik dołącz tylko raz.
4. Wybierz miejsce logo w nagłówku i kliknij Wstaw/edytuj obraz.
   Użyj selektora pliku przy polu Źródło / Adres i wybierz dołączony
   siz3r-logo.png. Zachowaj rozmiary określone w szablonie.
5. Tak samo zastąp miejsce ilustracji plikiem siz3r-illustration.png
   oraz miejsce znaku w stopce plikiem siz3r-round.jpg.
6. W każdym z sześciu punktów wybierz miejsce ikony i ustaw ten sam
   dołączony plik siz3r-check.png. Ikonę dołączasz raz, używasz sześć
   razy. Zachowaj rozmiary elementów określone w szablonie.
7. W ostatnim rzędzie stopki zastąp cztery miejsca ikon plikami
   odpowiednich serwisów. Zachowaj rozmiar 24 × 24 px i istniejące
   odnośniki. W tym samym rzędzie po lewej zostaje Terms of Service.
8. Jeśli nie da się zaznaczyć niedziałającego obrazu, usuń tylko ten
   element i wstaw odpowiedni plik w tym samym miejscu.
9. Pozostaw obrazy dołączone. Wstawiaj je przez selektor Roundcube,
   który obsługuje osadzenie w wiadomości. Nie wklejaj lokalnych
   ścieżek ani danych base64 do pola Źródło. Same placeholdery
   nie wyświetlą obrazów.
10. Dopasuj treść, uzupełnij Do i Temat. Nie dodawaj drugi raz starej
   stopki. Wyślij próbę do siebie i sprawdź wszystkie grafiki, linki
   oraz wygląd wiadomości na telefonie i komputerze.

STOPKA
Zawiera kontakt, krótkie dane firmy i link Terms of Service:
https://siz3r.com/terms. W ostatnim, zwartym rzędzie link jest
po lewej, a cztery małe ikony społecznościowe po prawej.
Zgodnie z ustaleniami szablon nie zawiera linku rezygnacji z ofert.

SPRAWDZENIE PRZED WYSYŁKĄ
Podglądy i kontrole w przeglądarce nie zastępują testu w Gmail, Onet,
WP i Outlook. Zakres walidacji opisuje Weryfikacja.txt. Wiadomości
nie wysłano z konta ehost; przed użyciem sprawdź próbę na własnych
skrzynkach. Odbiorca może mieć wyłączone wyświetlanie obrazów,
dlatego treść oferty i kontakt pozostają zapisane jako tekst.

PRZYCISK
Oba warianty mają przycisk 224 × 52 px w zieleni siz3r #00D278,
z białym tekstem Arial 16 px bez pogrubienia i rogami o promieniu
8 px. Treść przycisku i adres docelowy pozostają bez zmian.
Kod zawiera wersję HTML oraz warunkową wersję VML dla klasycznego
Outlooka. Zmieniając tekst lub adres w źródle, popraw obie wersje.
Edytor wizualny Roundcube może usunąć komentarze warunkowe VML;
wygląd rogów w starszym Outlooku sprawdź w rzeczywiście wysłanej
próbie. Nie wykonano testu wysyłki z ehost ani w samym Outlooku.
