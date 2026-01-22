from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time, random, string, os

GRID_URL = 'http://localhost:4444'
PREFIX = "biztest_"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_PATH = os.path.join(SCRIPT_DIR, 'test_images')

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
    images = [f for f in os.listdir(folder) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not f.startswith('.')]
    return os.path.join(folder, random.choice(images))

# Quick test
user = generate_user()
person_img = get_random_image(os.path.join(BASE_PATH, 'women_people'))
clothes_img = get_random_image(os.path.join(BASE_PATH, 'women_clothes'))

opts = webdriver.ChromeOptions()
opts.add_argument('--headless')
opts.add_argument('--no-sandbox')
opts.add_argument('--disable-dev-shm-usage')

driver = webdriver.Remote(GRID_URL, options=opts)
driver.set_page_load_timeout(40)
wait = WebDriverWait(driver, 30)

print(f"User: {user['email']}")

driver.get("https://siz3r.com/business/register")
time.sleep(3)

email_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email']")))
email_input.send_keys(user['email'])

password_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
password_inputs[0].send_keys(user['password'])
password_inputs[1].send_keys(user['password'])
time.sleep(1)

buttons = driver.find_elements(By.TAG_NAME, "button")
for btn in buttons:
    try:
        btn_text = btn.text.strip().lower()
        if 'register' in btn_text or 'zarejestruj' in btn_text:
            driver.execute_script("arguments[0].click();", btn)
            break
    except:
        continue

time.sleep(5)

no_thanks = find_button_safe(driver, ['nie, dziękuję', 'no, thanks'])
if no_thanks:
    driver.execute_script("arguments[0].click();", no_thanks)
    time.sleep(2)

driver.get("https://siz3r.com/business/playground")
time.sleep(5)

file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
file_inputs[0].send_keys(person_img)
time.sleep(3)

file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
file_inputs[1].send_keys(clothes_img)
time.sleep(3)

generate_btn = find_button_safe(driver, ['generuj', 'generate'])
driver.execute_script("arguments[0].click();", generate_btn)

print("Czekam 20s...")
time.sleep(20)
driver.save_screenshot("debug_20s.png")
print("Screenshot po 20s: debug_20s.png")

print("Czekam kolejne 20s...")
time.sleep(20)
driver.save_screenshot("debug_40s.png")
print("Screenshot po 40s: debug_40s.png")

# Pokaż ile jest obrazków
all_imgs = driver.find_elements(By.TAG_NAME, "img")
print(f"\nZnaleziono {len(all_imgs)} obrazków po 40s:")
for i, img in enumerate(all_imgs):
    try:
        src = img.get_attribute('src')
        width = img.size.get('width', 0)
        height = img.size.get('height', 0)
        if width > 200 and height > 200:
            has_gradio = 'gradio' in src or 'demo.siz3r' in src
            src_short = src[:60] if src else 'BRAK'
            print(f"  [{i}] {width}x{height} gradio={has_gradio} src={src_short}...")
    except:
        pass

driver.quit()
print("\nSprawdź screenshoty: debug_20s.png i debug_40s.png")
