from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time, random, string, os, sys, shutil, base64, json, traceback
from pathlib import Path

GRID_URL = os.getenv('SELENIUM_GRID_URL', 'http://localhost:4444')
PREFIX = "biztest_"
HEADLESS = os.getenv('HEADLESS', 'false').lower() == 'true'
MAX_TESTS = os.getenv('MAX_TESTS', None)

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

def get_all_models():
    models = []
    women_folder = FOLDERS["women_people"]
    for img in sorted(os.listdir(women_folder)):
        if img.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not img.startswith('.'):
            models.append({
                "gender": "women",
                "person_path": os.path.join(women_folder, img),
                "person_name": img,
                "clothes_folder": FOLDERS["women_clothes"]
            })
    
    men_folder = FOLDERS["men_people"]
    for img in sorted(os.listdir(men_folder)):
        if img.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not img.startswith('.'):
            models.append({
                "gender": "men",
                "person_path": os.path.join(men_folder, img),
                "person_name": img,
                "clothes_folder": FOLDERS["men_clothes"]
            })
    
    return models

def get_random_garment(clothes_folder):
    images = [f for f in os.listdir(clothes_folder) 
              if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not f.startswith('.')]
    if not images:
        raise Exception(f"Brak ubrań w: {clothes_folder}")
    return os.path.join(clothes_folder, random.choice(images))

def download_image_from_element(driver, img_element, filepath):
    try:
        img_element.screenshot(filepath)
        return True
    except Exception as e:
        try:
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
            
            if ',' in base64_data:
                base64_data = base64_data.split(',')[1]
            
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(base64_data))
            return True
        except Exception as e2:
            return False

def test_single_model(test_num, model_info):
    driver = None
    user = generate_user()
    
    model_name_clean = Path(model_info['person_name']).stem
    test_id = f"test_{test_num}_{model_info['gender']}_{model_name_clean}"
    
    # Metadata podstawowe
    metadata = {
        "test_number": test_num,
        "test_id": test_id,
        "gender": model_info['gender'],
        "model_filename": model_info['person_name'],
        "user_email": user['email'],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "headless": HEADLESS
    }
    
    try:
        garment_path = get_random_garment(model_info['clothes_folder'])
        garment_name = os.path.basename(garment_path)
        metadata["garment_filename"] = garment_name
        
        print(f"\n[{test_num}] {user['email']} | {model_info['gender']}")
        print(f"  👤 Model: {model_info['person_name'][:40]}")
        print(f"  👔 Garment: {garment_name[:40]}")
        
        test_folder = os.path.join(RESULTS_FOLDER, test_id)
        garment_folder = os.path.join(test_folder, "garment")
        model_folder = os.path.join(test_folder, "model")
        result_folder = os.path.join(test_folder, "result")
        
        os.makedirs(garment_folder, exist_ok=True)
        os.makedirs(model_folder, exist_ok=True)
        os.makedirs(result_folder, exist_ok=True)
        
        garment_ext = os.path.splitext(garment_path)[1]
        model_ext = os.path.splitext(model_info['person_path'])[1]
        
        shutil.copy2(garment_path, os.path.join(garment_folder, f"garment{garment_ext}"))
        shutil.copy2(model_info['person_path'], os.path.join(model_folder, f"model{model_ext}"))
        
        # Setup driver z większymi timeoutami dla headless
        opts = webdriver.ChromeOptions()
        if HEADLESS:
            opts.add_argument('--headless=new')  # Nowy headless mode
            opts.add_argument('--disable-gpu')
            opts.add_argument('--window-size=1920,1080')  # Ważne dla headless!
        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage')
        
        driver = webdriver.Remote(GRID_URL, options=opts)
        driver.set_page_load_timeout(60)  # Zwiększone z 40
        wait = WebDriverWait(driver, 40)  # Zwiększone z 30
        
        # REJESTRACJA
        print(f"  📝 Rejestracja...")
        driver.get("https://siz3r.com/business/register")
        time.sleep(5)  # Zwiększone z 3 dla headless
        
        try:
            email_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email']")))
            email_input.send_keys(user['email'])
        except TimeoutException:
            raise Exception("Timeout: nie znaleziono pola email")
        
        password_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
        if len(password_inputs) < 2:
            raise Exception(f"Za mało pól hasła: {len(password_inputs)}")
        
        password_inputs[0].send_keys(user['password'])
        password_inputs[1].send_keys(user['password'])
        time.sleep(2)
        
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
        time.sleep(7)  # Zwiększone z 5
        
        no_thanks = find_button_safe(driver, ['nie, dziękuję', 'no, thanks', 'no thanks'])
        if no_thanks:
            driver.execute_script("arguments[0].click();", no_thanks)
            time.sleep(3)
        
        # PLAYGROUND
        print(f"  ⏳ Playground...")
        driver.get("https://siz3r.com/business/playground")
        time.sleep(7)  # Zwiększone z 5
        
        try:
            wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "input[type='file']")))
        except TimeoutException:
            raise Exception("Timeout: nie znaleziono file inputs")
        
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        
        if len(file_inputs) < 2:
            raise Exception(f"Za mało file inputs: {len(file_inputs)}")
        
        # Upload person
        file_inputs[0].send_keys(model_info['person_path'])
        time.sleep(4)  # Zwiększone z 3
        
        # Upload garment
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        file_inputs[1].send_keys(garment_path)
        time.sleep(4)
        
        # Generate
        generate_btn = find_button_safe(driver, ['generuj', 'generate'])
        if not generate_btn:
            raise Exception("Brak przycisku Generuj")
        
        driver.execute_script("arguments[0].click();", generate_btn)
        print(f"  ⏳ Generacja...")
        
        # Wait for result z dłuższym timeoutem
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
        
        try:
            result_img = WebDriverWait(driver, 30).until(result_image_present)  # Zwiększone z 20
        except TimeoutException:
            raise Exception("Timeout: nie znaleziono wyniku generacji po 30s")
        
        time.sleep(2)
        
        # Save result
        print(f"  📥 Zapisuję wynik...")
        result_path = os.path.join(result_folder, "result.png")
        if download_image_from_element(driver, result_img, result_path):
            metadata["status"] = "success"
            metadata["result_path"] = result_path
            
            with open(os.path.join(test_folder, "metadata.json"), 'w') as f:
                json.dump(metadata, f, indent=2)
            
            print(f"  ✅ OK - {test_id}")
            driver.quit()
            return True
        else:
            raise Exception("Nie udało się pobrać wyniku")
        
    except Exception as e:
        error_msg = str(e)
        error_trace = traceback.format_exc()
        
        print(f"  ❌ FAIL: {error_msg}")
        
        metadata["status"] = "failed"
        metadata["error"] = error_msg
        metadata["error_trace"] = error_trace
        
        test_folder = os.path.join(RESULTS_FOLDER, test_id)
        os.makedirs(test_folder, exist_ok=True)
        with open(os.path.join(test_folder, "metadata.json"), 'w') as f:
            json.dump(metadata, f, indent=2)
        
        if driver:
            try:
                # Screenshot dla debugowania
                screenshot_path = os.path.join(test_folder, "error_screenshot.png")
                driver.save_screenshot(screenshot_path)
                print(f"  📸 Screenshot zapisany: error_screenshot.png")
            except:
                pass
            
            try:
                driver.quit()
            except:
                pass
        
        return False

if __name__ == "__main__":
    print("🧪 SIZ3R BUSINESS TESTS - ALL MODELS")
    print(f"Headless mode: {HEADLESS}")
    
    missing = [k for k, v in FOLDERS.items() if not os.path.exists(v)]
    if missing:
        print(f"❌ Brakuje: {', '.join(missing)}")
        sys.exit(1)
    
    for key, path in FOLDERS.items():
        count = len([f for f in os.listdir(path) 
                    if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not f.startswith('.')])
        print(f"  {key}: {count} zdjęć")
    
    all_models = get_all_models()
    
    if MAX_TESTS:
        max_tests_int = int(MAX_TESTS)
        print(f"\n⚠️  MAX_TESTS={max_tests_int} - ograniczam do {max_tests_int} pierwszych modeli")
        all_models = all_models[:max_tests_int]
    
    total_tests = len(all_models)
    
    print(f"\n📊 Testowanie {total_tests} modeli")
    print(f"  Women: {len([m for m in all_models if m['gender'] == 'women'])}")
    print(f"  Men: {len([m for m in all_models if m['gender'] == 'men'])}")
    
    os.makedirs(RESULTS_FOLDER, exist_ok=True)
    
    success = 0
    failed = 0
    start_time = time.time()
    
    for i, model in enumerate(all_models, 1):
        if test_single_model(i, model):
            success += 1
        else:
            failed += 1
        
        if i < total_tests:
            time.sleep(2)
        
        elapsed = time.time() - start_time
        avg_per_test = elapsed / i
        remaining = (total_tests - i) * avg_per_test
        print(f"  📊 Progress: {i}/{total_tests} | ETA: {int(remaining/60)}min")
    
    elapsed_total = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"📊 PODSUMOWANIE")
    print(f"{'='*60}")
    print(f"✅ Sukces: {success}/{total_tests} ({success/total_tests*100:.1f}%)")
    print(f"❌ Błędy: {failed}/{total_tests}")
    print(f"⏱️  Czas: {int(elapsed_total/60)}min {int(elapsed_total%60)}s")
    print(f"📁 Wyniki: {RESULTS_FOLDER}")
    
    summary = {
        "total_tests": total_tests,
        "successful": success,
        "failed": failed,
        "success_rate": f"{(success/total_tests*100):.1f}%",
        "duration_seconds": int(elapsed_total),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "test_results_folder": RESULTS_FOLDER,
        "headless_mode": HEADLESS
    }
    
    with open(os.path.join(RESULTS_FOLDER, "summary.json"), 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n💾 Summary zapisane w: {RESULTS_FOLDER}/summary.json")
    
    sys.exit(0 if success > 0 else 1)
