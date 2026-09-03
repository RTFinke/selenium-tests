from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time, random, string, os, sys, shutil, requests
from datetime import datetime

GRID_URL = os.getenv('SELENIUM_GRID_URL', 'http://localhost:4444')
PREFIX = "biztest_"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_PATH = os.path.join(SCRIPT_DIR, 'test_images')

FOLDERS = {
    "women_people": os.path.join(BASE_PATH, "women_people"),
    "women_clothes": os.path.join(BASE_PATH, "women_clothes"),
    "men_people": os.path.join(BASE_PATH, "men_people"),
    "men_clothes": os.path.join(BASE_PATH, "men_clothes")
}

RESULTS_FOLDER = os.path.join(SCRIPT_DIR, "test_results")

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
    images = [f for f in os.listdir(folder) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.avif')) and not f.startswith('.')]
    return os.path.join(folder, random.choice(images))

def get_test_images():
    gender = random.choice(['women', 'men'])
    return {
        "gender": gender,
        "person": get_random_image(FOLDERS[f"{gender}_people"]),
        "clothes": get_random_image(FOLDERS[f"{gender}_clothes"])
    }

images = get_test_images()
user = generate_user()

print(f"User: {user['email']}")
print(f"Gender: {images['gender']}")

opts = webdriver.ChromeOptions()
# WYŁĄCZ headless na chwilę
# opts.add_argument('--headless')
opts.add_argument('--no-sandbox')
opts.add_argument('--disable-dev-shm-usage')

driver = webdriver.Remote(GRID_URL, options=opts)
driver.set_page_load_timeout(40)
wait = WebDriverWait(driver, 30)

# Rejestracja
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

driver.execute_script("arguments[0].click();", register_btn)
time.sleep(5)

no_thanks = find_button_safe(driver, ['nie, dziękuję', 'no, thanks', 'no thanks'])
if no_thanks:
    driver.execute_script("arguments[0].click();", no_thanks)
    time.sleep(2)

if 'business' not in driver.current_url:
    driver.get("https://siz3r.com/business")
    time.sleep(3)

playground_btn = find_button_safe(driver, ['playground', 'przetestuj'])
if not playground_btn:
    links = driver.find_elements(By.TAG_NAME, "a")
    for link in links:
        try:
            if 'playground' in (link.get_attribute('href') or '').lower():
                driver.execute_script("arguments[0].click();", link)
                break
        except:
            continue
else:
    driver.execute_script("arguments[0].click();", playground_btn)

time.sleep(3)

# Upload
file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
file_inputs[0].send_keys(images['person'])
time.sleep(3)

file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
if len(file_inputs) >= 2:
    file_inputs[1].send_keys(images['clothes'])
else:
    file_inputs[0].send_keys(images['clothes'])
time.sleep(3)

generate_btn = find_button_safe(driver, ['generuj', 'generate'])
driver.execute_script("arguments[0].click();", generate_btn)

print("Czekam 30s na generację...")
time.sleep(30)

# DEBUG - zobacz co jest
all_imgs = driver.find_elements(By.TAG_NAME, "img")
print(f"\nZnaleziono {len(all_imgs)} obrazków:")
for i, img in enumerate(all_imgs):
    try:
        src = img.get_attribute('src')[:80] if img.get_attribute('src') else 'BRAK'
        width = img.size.get('width', 0)
        height = img.size.get('height', 0)
        role = img.get_attribute('role') or 'brak'
        print(f"  [{i}] {width}x{height} role={role} src={src}")
    except:
        print(f"  [{i}] ERROR")

print("\nZostaw okno otwarte, sprawdź co jest na stronie")
print("Możesz otworzyć VNC: http://localhost:7900 (hasło: secret)")
input("Naciśnij ENTER żeby zamknąć...")
driver.quit()
