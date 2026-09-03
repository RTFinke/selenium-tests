from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time, random, string, os

GRID_URL = 'http://localhost:4444'
PREFIX = "biztest_"

def generate_user():
    uid = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return {"email": f"{PREFIX}{uid}@test.com", "password": "TestPass123!"}

def find_button_safe(driver, texts):
    buttons = driver.find_elements(By.TAG_NAME, "button")
    for btn in buttons:
        try:
            btn_text = btn.text.strip().lower()
            for text in texts:
                if text.lower() in btn_text:
                    return btn
        except:
            continue
    return None

def get_random_image(folder):
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_images')
    full_path = os.path.join(base, folder)
    images = [f for f in os.listdir(full_path) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.avif')) and not f.startswith('.')]
    return os.path.join(full_path, images[0])

user = generate_user()
print(f"🧪 Test: {user['email']}")

opts = webdriver.ChromeOptions()
opts.add_argument('--no-sandbox')
opts.add_argument('--disable-dev-shm-usage')

driver = webdriver.Remote(GRID_URL, options=opts)
driver.set_page_load_timeout(60)
wait = WebDriverWait(driver, 30)

try:
    print("📝 Rejestracja...")
    driver.get("https://siz3r.com/business/register")
    time.sleep(3)
    
    email_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email']")))
    email_input.send_keys(user['email'])
    
    password_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
    password_inputs[0].send_keys(user['password'])
    password_inputs[1].send_keys(user['password'])
    time.sleep(1)
    
    buttons = driver.find_elements(By.TAG_NAME, "button")
    register_btn = None
    for btn in buttons:
        try:
            btn_text = btn.text.strip().lower()
            btn_class = (btn.get_attribute('class') or '').lower()
            if 'tab' in btn_class:
                continue
            if any(t in btn_text for t in ['zarejestruj', 'register', 'sign up']):
                register_btn = btn
                break
        except:
            continue
    
    if register_btn:
        driver.execute_script("arguments[0].click();", register_btn)
        time.sleep(5)
    
    no_thanks = find_button_safe(driver, ['nie, dziękuję', 'no, thanks', 'no thanks'])
    if no_thanks:
        driver.execute_script("arguments[0].click();", no_thanks)
        time.sleep(2)
    
    print("🎮 Playground...")
    driver.get("https://siz3r.com/business/playground")
    time.sleep(5)
    
    wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "input[type='file']")))
    file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    
    person_img = get_random_image('women_people')
    clothes_img = get_random_image('women_clothes')
    
    print(f"📤 Upload osoby: {os.path.basename(person_img)}")
    file_inputs[0].send_keys(person_img)
    time.sleep(3)
    
    file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    print(f"📤 Upload ubrania: {os.path.basename(clothes_img)}")
    file_inputs[1].send_keys(clothes_img)
    time.sleep(3)
    
    generate_btn = find_button_safe(driver, ['generuj', 'generate'])
    if generate_btn:
        print("🚀 Klikam Generuj...")
        driver.execute_script("arguments[0].click();", generate_btn)
    
    # CZEKAJ 15 SEKUND I SPRAWDŹ CO JEST NA STRONIE
    print("⏳ Czekam 15 sekund na generację...")
    time.sleep(15)
    
    print("\n🔍 WSZYSTKIE OBRAZKI NA STRONIE:")
    imgs = driver.find_elements(By.TAG_NAME, "img")
    print(f"Znaleziono {len(imgs)} obrazków")
    
    for i, img in enumerate(imgs):
        src = img.get_attribute('src') or ''
        width = img.size.get('width', 0)
        height = img.size.get('height', 0)
        print(f"\n  [{i}] {width}x{height}px")
        print(f"      src: {src[:100]}...")
        
        if 'gradio_api' in src or 'demo.siz3r.com' in src:
            print(f"      ⭐ TO MOŻE BYĆ WYNIK!")
    
    print("\n✅ Debug zakończony - sprawdź output powyżej")
    input("Naciśnij Enter żeby zamknąć przeglądarkę...")
    
except Exception as e:
    print(f"❌ Błąd: {e}")
    import traceback
    traceback.print_exc()
finally:
    driver.quit()
