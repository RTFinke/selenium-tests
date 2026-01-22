from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time, random, string, os, sys, shutil, base64

GRID_URL = os.getenv('SELENIUM_GRID_URL', 'http://localhost:4444')
PREFIX = "biztest_"
NUM_TESTS = int(os.getenv('NUM_TESTS', '3'))
HEADLESS = os.getenv('HEADLESS', 'false').lower() == 'true'

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
    if not os.path.exists(folder):
        raise Exception(f"Folder nie istnieje: {folder}")
    images = [f for f in os.listdir(folder) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not f.startswith('.')]
    if not images:
        raise Exception(f"Brak zdjęć w: {folder}")
    return os.path.join(folder, random.choice(images))

def get_test_images():
    gender = random.choice(['women', 'men'])
    return {
        "gender": gender,
        "person": get_random_image(FOLDERS[f"{gender}_people"]),
        "clothes": get_random_image(FOLDERS[f"{gender}_clothes"])
    }

def download_image_from_element(driver, img_element, filepath):
    """Pobierz obrazek używając Selenium (screenshot elementu)"""
    try:
        # Metoda 1: Screenshot elementu
        img_element.screenshot(filepath)
        return True
    except Exception as e:
        print(f"  ⚠️  Screenshot nie zadziałał, próbuję canvas: {e}")
        try:
            # Metoda 2: Przez canvas (dla blob URLs)
            script = """
            var img = arguments[0];
            var canvas = document.createElement('canvas');
            canvas.width = img.naturalWidth;
            canvas.height = img.naturalHeight;
            var ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0);
            return canvas.toDataURL('image/png');
            """
            base64_data = driver.execute_script(script, img_element)
            
            # Usuń prefix "data:image/png;base64,"
            if ',' in base64_data:
                base64_data = base64_data.split(',')[1]
            
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(base64_data))
            return True
        except Exception as e2:
            print(f"  ❌ Canvas też nie zadziałał: {e2}")
            return False

def test_business_flow(test_num):
    driver = None
    user = generate_user()
    try:
        images = get_test_images()
        print(f"\n[{test_num}] {user['email']} | {images['gender']}")
        
        test_folder = os.path.join(RESULTS_FOLDER, f"test_{test_num}")
        garment_folder = os.path.join(test_folder, "garment")
        model_folder = os.path.join(test_folder, "model")
        result_folder = os.path.join(test_folder, "result")
        
        os.makedirs(garment_folder, exist_ok=True)
        os.makedirs(model_folder, exist_ok=True)
        os.makedirs(result_folder, exist_ok=True)
        
        garment_ext = os.path.splitext(images['clothes'])[1]
        model_ext = os.path.splitext(images['person'])[1]
        
        shutil.copy2(images['clothes'], os.path.join(garment_folder, f"garment{garment_ext}"))
        shutil.copy2(images['person'], os.path.join(model_folder, f"model{model_ext}"))
        
        opts = webdriver.ChromeOptions()
        if HEADLESS:
            opts.add_argument('--headless')
        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage')
        
        driver = webdriver.Remote(GRID_URL, options=opts)
        driver.set_page_load_timeout(40)
        wait = WebDriverWait(driver, 30)
        
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
        
        if not register_btn:
            raise Exception("Brak przycisku rejestracji")
        
        driver.execute_script("arguments[0].click();", register_btn)
        time.sleep(5)
        
        no_thanks = find_button_safe(driver, ['nie, dziękuję', 'no, thanks', 'no thanks'])
        if no_thanks:
            driver.execute_script("arguments[0].click();", no_thanks)
            time.sleep(2)
        
        driver.get("https://siz3r.com/business/playground")
        time.sleep(5)
        
        print(f"  ⏳ Czekam na file inputs...")
        wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "input[type='file']")))
        
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        if len(file_inputs) < 2:
            raise Exception(f"Za mało file inputs: {len(file_inputs)}")
        
        file_inputs[0].send_keys(images['person'])
        time.sleep(3)
        
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        file_inputs[1].send_keys(images['clothes'])
        time.sleep(3)
        
        generate_btn = find_button_safe(driver, ['generuj', 'generate'])
        if not generate_btn:
            raise Exception("Brak przycisku Generuj/Generate")
        
        driver.execute_script("arguments[0].click();", generate_btn)
        print(f"  ⏳ Czekam na generację (max 20s)...")
        
        def result_image_present(driver):
            try:
                imgs = driver.find_elements(By.TAG_NAME, "img")
                for img in imgs:
                    src = img.get_attribute('src') or ''
                    if ('gradio_api' in src or 'demo.siz3r.com' in src):
                        rect = img.rect
                        width = rect['width']
                        height = rect['height']
                        if width > 300 and height > 400:
                            return img
            except:
                pass
            return False
        
        result_img = WebDriverWait(driver, 20).until(result_image_present)
        print(f"  ✅ Znaleziono wynik!")
        
        time.sleep(2)
        
        print(f"  📥 Pobieram wynik (screenshot)...")
        result_path = os.path.join(result_folder, "result.png")
        
        if download_image_from_element(driver, result_img, result_path):
            print(f"✅ OK [{test_num}] - zapisano w {test_folder}")
            driver.quit()
            return True
        else:
            raise Exception("Nie udało się pobrać zdjęcia wyniku")
        
    except Exception as e:
        print(f"❌ FAIL [{test_num}] {str(e)}")
        if driver:
            try:
                driver.quit()
            except:
                pass
        return False

if __name__ == "__main__":
    print("🧪 SIZ3R BUSINESS TESTS")
    print(f"Headless mode: {HEADLESS}")
    
    missing = [k for k, v in FOLDERS.items() if not os.path.exists(v)]
    if missing:
        print(f"❌ Brakuje: {', '.join(missing)}")
        sys.exit(1)
    
    for key, path in FOLDERS.items():
        count = len([f for f in os.listdir(path) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not f.startswith('.')])
        print(f"  {key}: {count} zdjęć")
    
    os.makedirs(RESULTS_FOLDER, exist_ok=True)
    
    success = 0
    for i in range(1, NUM_TESTS + 1):
        if test_business_flow(i):
            success += 1
        time.sleep(2)
    
    print(f"\n📊 Wynik: {success}/{NUM_TESTS}")
    sys.exit(0 if success > 0 else 1)
