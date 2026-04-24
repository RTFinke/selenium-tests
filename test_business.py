from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time, random, string, os, sys, shutil, base64, json, traceback, hashlib
from pathlib import Path

GRID_URL = os.getenv('SELENIUM_GRID_URL', 'http://localhost:4444')
PREFIX = "biztest_"
HEADLESS = os.getenv('HEADLESS', 'false').lower() == 'true'
PAIRING_MODE = os.getenv('TEST_PAIRING_MODE', 'deterministic').strip().lower()
PAIRING_SEED = os.getenv('TEST_PAIRING_SEED', 'stable-v1').strip() or 'stable-v1'

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

def list_supported_images(folder, sort_files=False):
    images = [
        f for f in os.listdir(folder)
        if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not f.startswith('.')
    ]
    return sorted(images) if sort_files else images

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
    for img in list_supported_images(women_folder, sort_files=True):
        models.append({
            "gender": "women",
            "person_path": os.path.join(women_folder, img),
            "person_name": img,
            "clothes_folder": FOLDERS["women_clothes"]
        })
    
    men_folder = FOLDERS["men_people"]
    for img in list_supported_images(men_folder, sort_files=True):
        models.append({
            "gender": "men",
            "person_path": os.path.join(men_folder, img),
            "person_name": img,
            "clothes_folder": FOLDERS["men_clothes"]
        })
    
    return models

def get_garment_for_model(clothes_folder, model_info):
    images = list_supported_images(clothes_folder, sort_files=True)
    if not images:
        raise Exception(f"Brak ubran w: {clothes_folder}")

    if PAIRING_MODE == 'random':
        chosen_image = random.choice(images)
        return {
            "path": os.path.join(clothes_folder, chosen_image),
            "mode": "random",
            "seed": None,
            "index": images.index(chosen_image),
            "pool_size": len(images),
        }

    selection_basis = f"{PAIRING_SEED}|{model_info['gender']}|{model_info['person_name']}"
    digest = hashlib.sha256(selection_basis.encode('utf-8')).hexdigest()
    image_index = int(digest[:8], 16) % len(images)
    return {
        "path": os.path.join(clothes_folder, images[image_index]),
        "mode": "deterministic",
        "seed": PAIRING_SEED,
        "index": image_index,
        "pool_size": len(images),
    }

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

def read_generation_option_state(driver):
    option_state = driver.execute_script("""
    const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim().toLowerCase();

    const isVisible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
            rect.width > 0 && rect.height > 0;
    };

    const unique = (elements) => {
        const seen = new Set();
        const result = [];
        for (const el of elements) {
            if (!el || seen.has(el)) continue;
            seen.add(el);
            result.push(el);
        }
        return result;
    };

    const labelMatches = (el, label) => {
        const text = normalize(el.innerText || el.textContent);
        const ariaLabel = normalize(el.getAttribute && el.getAttribute('aria-label'));
        const title = normalize(el.getAttribute && el.getAttribute('title'));
        return text === label || text.startsWith(label + ' ') || ariaLabel === label || title === label;
    };

    const getAnchors = (label) => {
        const candidates = Array.from(document.querySelectorAll(
            "button, label, [role='button'], [role='tab'], [role='radio'], [role='checkbox'], [role='switch'], div, span"
        ));
        return candidates.filter((el) => isVisible(el) && labelMatches(el, label));
    };

    const getControlsForAnchor = (anchor) => unique([
        anchor.closest && anchor.closest('button'),
        anchor.closest && anchor.closest('label'),
        anchor.closest && anchor.closest("[role='button']"),
        anchor.closest && anchor.closest("[role='tab']"),
        anchor.closest && anchor.closest("[role='radio']"),
        anchor.closest && anchor.closest("[role='checkbox']"),
        anchor.closest && anchor.closest("[role='switch']"),
        anchor,
        anchor.parentElement,
        anchor.previousElementSibling,
        anchor.nextElementSibling,
        anchor.parentElement && anchor.parentElement.parentElement,
    ].filter(Boolean)).filter(isVisible);

    const readState = (root) => {
        if (!root) return null;

        const nodes = unique([
            root,
            ...root.querySelectorAll(
                "input[type='radio'], input[type='checkbox'], [role='tab'], [role='radio'], [role='checkbox'], [role='switch'], [aria-selected], [aria-checked], [aria-pressed], [data-state]"
            ),
        ]);

        for (const node of nodes) {
            if (!node) continue;

            if (node.matches && node.matches("input[type='radio'], input[type='checkbox']")) {
                return { selected: Boolean(node.checked), source: 'input.checked' };
            }

            const ariaSelected = normalize(node.getAttribute && node.getAttribute('aria-selected'));
            if (ariaSelected === 'true' || ariaSelected === 'false') {
                return { selected: ariaSelected === 'true', source: 'aria-selected' };
            }

            const ariaChecked = normalize(node.getAttribute && node.getAttribute('aria-checked'));
            if (ariaChecked === 'true' || ariaChecked === 'false') {
                return { selected: ariaChecked === 'true', source: 'aria-checked' };
            }

            const ariaPressed = normalize(node.getAttribute && node.getAttribute('aria-pressed'));
            if (ariaPressed === 'true' || ariaPressed === 'false') {
                return { selected: ariaPressed === 'true', source: 'aria-pressed' };
            }

            const dataState = normalize(node.getAttribute && node.getAttribute('data-state'));
            if (['checked', 'on', 'active', 'selected'].includes(dataState)) {
                return { selected: true, source: 'data-state' };
            }
            if (['unchecked', 'off'].includes(dataState)) {
                return { selected: false, source: 'data-state' };
            }

            const className = normalize(node.className);
            if (['mui-selected', 'mui-checked', 'selected', 'active', 'checked', 'current'].some((token) => className.includes(token))) {
                return { selected: true, source: 'class' };
            }
        }

        return null;
    };

    const scan = (label) => {
        const anchors = getAnchors(label);
        for (const anchor of anchors) {
            for (const control of getControlsForAnchor(anchor)) {
                const state = readState(control);
                if (state) {
                    return { found: true, selected: state.selected, source: state.source };
                }
            }
        }
        return { found: anchors.length > 0, selected: null, source: null };
    };

    const standard = scan('standard');
    const premium = scan('premium');
    const turbo = scan('turbo');

    let qualityMode = null;
    let qualitySource = null;
    if (standard.selected === true || premium.selected === false) {
        qualityMode = 'standard';
        qualitySource = standard.selected === true ? standard.source : premium.source;
    } else if (premium.selected === true || standard.selected === false) {
        qualityMode = 'premium';
        qualitySource = premium.selected === true ? premium.source : standard.source;
    }

    return {
        quality_mode_selected: qualityMode,
        quality_mode_state_source: qualitySource,
        turbo_enabled: turbo.selected,
        turbo_state_source: turbo.source,
        standard_found: standard.found,
        premium_found: premium.found,
        turbo_found: turbo.found,
    };
    """)

    return option_state if isinstance(option_state, dict) else None

def capture_option_confirmation(driver, filepath):
    control_elements = driver.execute_script("""
    const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim().toLowerCase();

    const isVisible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
            rect.width > 0 && rect.height > 0;
    };

    const unique = (elements) => {
        const seen = new Set();
        const result = [];
        for (const el of elements) {
            if (!el || seen.has(el)) continue;
            seen.add(el);
            result.push(el);
        }
        return result;
    };

    const labelMatches = (el, label) => {
        const text = normalize(el.innerText || el.textContent);
        const ariaLabel = normalize(el.getAttribute && el.getAttribute('aria-label'));
        const title = normalize(el.getAttribute && el.getAttribute('title'));
        return text === label || text.startsWith(label + ' ') || ariaLabel === label || title === label;
    };

    const getAnchor = (label) => {
        const candidates = Array.from(document.querySelectorAll(
            "button, label, [role='button'], [role='tab'], [role='radio'], [role='checkbox'], [role='switch'], div, span"
        )).filter(isVisible);
        return candidates.find((el) => labelMatches(el, label)) || null;
    };

    const getControl = (anchor) => {
        if (!anchor) return null;

        const candidates = unique([
            anchor.closest && anchor.closest('button'),
            anchor.closest && anchor.closest('label'),
            anchor.closest && anchor.closest("[role='button']"),
            anchor.closest && anchor.closest("[role='tab']"),
            anchor.closest && anchor.closest("[role='radio']"),
            anchor.closest && anchor.closest("[role='checkbox']"),
            anchor.closest && anchor.closest("[role='switch']"),
            anchor,
            anchor.parentElement,
            anchor.parentElement && anchor.parentElement.parentElement,
        ].filter(Boolean)).filter(isVisible);

        return candidates[0] || anchor;
    };

    const findCaptureElement = (elements) => {
        const filtered = elements.filter(Boolean);
        if (filtered.length === 0) return null;

        let common = filtered[0];
        while (common) {
            if (filtered.every((el) => common.contains(el)) && isVisible(common)) {
                return common;
            }
            common = common.parentElement;
        }

        return filtered[0];
    };

    const standardControl = getControl(getAnchor('standard'));
    const premiumControl = getControl(getAnchor('premium'));
    const turboControl = getControl(getAnchor('turbo'));
    const captureElement = findCaptureElement([standardControl, premiumControl, turboControl]);

    if (!captureElement) {
        return null;
    }

    captureElement.scrollIntoView({ block: 'center', inline: 'center' });
    return [captureElement, standardControl, premiumControl, turboControl];
    """)

    if not control_elements or len(control_elements) < 1:
        return False

    capture_element = control_elements[0]
    option_elements = [element for element in control_elements[1:] if element]

    for element in option_elements:
        driver.execute_script("""
        const el = arguments[0];
        el.dataset.codexConfirmOutline = el.style.outline || '';
        el.dataset.codexConfirmBoxShadow = el.style.boxShadow || '';
        el.dataset.codexConfirmBorderRadius = el.style.borderRadius || '';
        el.style.outline = '3px solid #00ff88';
        el.style.boxShadow = '0 0 0 4px rgba(0, 255, 136, 0.2)';
        el.style.borderRadius = '10px';
        """, element)

    time.sleep(0.5)

    try:
        if capture_element.screenshot(filepath):
            return True
    except Exception:
        pass
    finally:
        for element in option_elements:
            driver.execute_script("""
            const el = arguments[0];
            el.style.outline = el.dataset.codexConfirmOutline || '';
            el.style.boxShadow = el.dataset.codexConfirmBoxShadow || '';
            el.style.borderRadius = el.dataset.codexConfirmBorderRadius || '';
            delete el.dataset.codexConfirmOutline;
            delete el.dataset.codexConfirmBoxShadow;
            delete el.dataset.codexConfirmBorderRadius;
            """, element)

    try:
        return driver.save_screenshot(filepath)
    except Exception:
        return False

def test_single_model(test_num, model_info):
    driver = None
    user = generate_user()
    
    model_name_clean = Path(model_info['person_name']).stem
    test_id = f"test_{test_num}_{model_info['gender']}_{model_name_clean}"
    
    metadata = {
        "test_number": test_num,
        "test_id": test_id,
        "gender": model_info['gender'],
        "model_filename": model_info['person_name'],
        "user_email": user['email'],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "headless": HEADLESS,
        "pairing_mode": PAIRING_MODE,
        "pairing_seed": PAIRING_SEED if PAIRING_MODE != 'random' else None,
        "quality_mode_selected": None,
        "quality_mode_state_source": None,
        "turbo_enabled": None,
        "turbo_state_source": None,
        "option_confirmation_screenshot": None,
    }
    
    try:
        garment_selection = get_garment_for_model(model_info['clothes_folder'], model_info)
        garment_path = garment_selection["path"]
        garment_name = os.path.basename(garment_path)
        metadata["garment_filename"] = garment_name
        metadata["garment_selection_mode"] = garment_selection["mode"]
        metadata["garment_selection_seed"] = garment_selection["seed"]
        metadata["garment_selection_index"] = garment_selection["index"]
        metadata["garment_pool_size"] = garment_selection["pool_size"]
        
        print(f"\n[{test_num}] {user['email']} | {model_info['gender']}")
        print(f"  Model: {model_info['person_name'][:40]}")
        print(f"  Garment: {garment_name[:40]}")
        
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
        
        opts = webdriver.ChromeOptions()
        if HEADLESS:
            opts.add_argument('--headless=new')
            opts.add_argument('--disable-gpu')
            opts.add_argument('--window-size=1920,1080')
        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage')
        
        driver = webdriver.Remote(GRID_URL, options=opts)
        driver.set_page_load_timeout(60)
        wait = WebDriverWait(driver, 40)
        
        # REJESTRACJA
        print(f"  Rejestracja...")
        driver.get("https://siz3r-dev.vercel.app/business/register")
        time.sleep(5)
        
        try:
            email_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email']")))
            email_input.send_keys(user['email'])
        except TimeoutException:
            raise Exception("Timeout: nie znaleziono pola email")
        
        password_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
        if len(password_inputs) < 2:
            raise Exception(f"Za malo pol hasla: {len(password_inputs)}")
        
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
        time.sleep(7)
        
        # ============= HANDLE CREDITS MODAL =============
        print(f"  Sprawdzam modal kredytow...")
        try:
            skip_button = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, 
                    "//button[contains(@class, 'MuiButton') and contains(text(), 'Nie, dziękuję')]"))
            )
            print(f"  OK Znalazlem 'Nie, dziekuje', klikam...")
            driver.execute_script("arguments[0].click();", skip_button)
            time.sleep(3)
            print(f"  OK Modal pominiety")
        except TimeoutException:
            try:
                skip_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, 
                        "//button[contains(text(), 'No, thank')]"))
                )
                print(f"  OK Znalazlem 'No, thanks', klikam...")
                driver.execute_script("arguments[0].click();", skip_button)
                time.sleep(3)
                print(f"  OK Modal pominiety (EN)")
            except TimeoutException:
                print(f"  WARN Modal nie pojawil sie (lub juz zamkniety)")
        except Exception as e:
            print(f"  WARN Blad przy modal: {e}")
        
        # ============= PLAYGROUND =============
        print(f"  Playground...")
        driver.get("https://siz3r-dev.vercel.app/business/playground")
        time.sleep(10)
        
        for attempt in range(3):
            try:
                wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "input[type='file']")))
                break
            except TimeoutException:
                if attempt < 2:
                    print(f"  Retry {attempt+1} - odswiezam strone...")
                    driver.refresh()
                    time.sleep(7)
                else:
                    raise Exception("Timeout: nie znaleziono file inputs po 3 probach")
        
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        
        if len(file_inputs) < 2:
            raise Exception(f"Za malo file inputs: {len(file_inputs)}")
        
        file_inputs[0].send_keys(model_info['person_path'])
        time.sleep(4)
        
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        file_inputs[1].send_keys(garment_path)
        time.sleep(4)

        option_state = read_generation_option_state(driver)
        if option_state:
            metadata["quality_mode_selected"] = option_state.get("quality_mode_selected")
            metadata["quality_mode_state_source"] = option_state.get("quality_mode_state_source")
            metadata["turbo_enabled"] = option_state.get("turbo_enabled")
            metadata["turbo_state_source"] = option_state.get("turbo_state_source")
            print(
                f"  Opcje: quality={metadata['quality_mode_selected'] or 'unknown'} | "
                f"turbo={metadata['turbo_enabled'] if metadata['turbo_enabled'] is not None else 'unknown'}"
            )

        option_confirmation_path = os.path.join(test_folder, "option_confirmation.png")
        if capture_option_confirmation(driver, option_confirmation_path):
            metadata["option_confirmation_screenshot"] = option_confirmation_path
            print(f"  OK Screenshot opcji zapisany: option_confirmation.png")
        else:
            print(f"  WARN Nie udalo sie zapisac screenshotu opcji")
        
        generate_btn = find_button_safe(driver, ['generuj', 'generate'])
        if not generate_btn:
            raise Exception("Brak przycisku Generuj")
        
        driver.execute_script("arguments[0].click();", generate_btn)
        print(f"  Generacja...")
        
        def result_image_present(driver):
            try:
                imgs = driver.find_elements(By.TAG_NAME, "img")
                for img in imgs:
                    src = img.get_attribute('src') or ''
                    if ('gradio_api' in src or 'demo.siz3r.com' in src or 'data:image' in src):
                        rect = img.rect
                        width = rect['width']
                        height = rect['height']
                        if width > 300 and height > 400:
                            return img
            except:
                pass
            return False
        
        try:
            result_img = WebDriverWait(driver, 30).until(result_image_present)
        except TimeoutException:
            raise Exception("Timeout: nie znaleziono wyniku generacji po 30s")
        
        time.sleep(2)
        
        print(f"  Zapisuje wynik...")
        result_path = os.path.join(result_folder, "result.png")
        if download_image_from_element(driver, result_img, result_path):
            metadata["status"] = "success"
            metadata["result_path"] = result_path
            
            with open(os.path.join(test_folder, "metadata.json"), 'w') as f:
                json.dump(metadata, f, indent=2)
            
            print(f"  OK - {test_id}")
            driver.quit()
            return True
        else:
            raise Exception("Nie udalo sie pobrac wyniku")
        
    except Exception as e:
        error_msg = str(e)
        error_trace = traceback.format_exc()
        
        print(f"  FAIL: {error_msg}")
        
        metadata["status"] = "failed"
        metadata["error"] = error_msg
        metadata["error_trace"] = error_trace
        
        test_folder = os.path.join(RESULTS_FOLDER, test_id)
        os.makedirs(test_folder, exist_ok=True)
        with open(os.path.join(test_folder, "metadata.json"), 'w') as f:
            json.dump(metadata, f, indent=2)
        
        if driver:
            try:
                screenshot_path = os.path.join(test_folder, "error_screenshot.png")
                driver.save_screenshot(screenshot_path)
                print(f"  Screenshot zapisany: error_screenshot.png")
            except:
                pass
            
            try:
                driver.quit()
            except:
                pass
        
        return False

if __name__ == "__main__":
    print("SIZ3R BUSINESS TESTS - ALL MODELS")
    print(f"Headless mode: {HEADLESS}")
    print(f"Pairing mode: {PAIRING_MODE}")
    if PAIRING_MODE != 'random':
        print(f"Pairing seed: {PAIRING_SEED}")
    
    missing = [k for k, v in FOLDERS.items() if not os.path.exists(v)]
    if missing:
        print(f"Brakuje: {', '.join(missing)}")
        sys.exit(1)
    
    for key, path in FOLDERS.items():
        count = len(list_supported_images(path))
        print(f"  {key}: {count} zdjec")
    
    all_models = get_all_models()
    
    total_tests = len(all_models)
    
    print(f"\nTestowanie {total_tests} modeli")
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
        print(f"  Progress: {i}/{total_tests} | ETA: {int(remaining/60)}min")
    
    elapsed_total = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"PODSUMOWANIE")
    print(f"{'='*60}")
    print(f"Sukces: {success}/{total_tests} ({success/total_tests*100:.1f}%)")
    print(f"Bledy: {failed}/{total_tests}")
    print(f"Czas: {int(elapsed_total/60)}min {int(elapsed_total%60)}s")
    print(f"Wyniki: {RESULTS_FOLDER}")
    
    summary = {
        "total_tests": total_tests,
        "successful": success,
        "failed": failed,
        "success_rate": f"{(success/total_tests*100):.1f}%",
        "duration_seconds": int(elapsed_total),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "test_results_folder": RESULTS_FOLDER,
        "headless_mode": HEADLESS,
        "pairing_mode": PAIRING_MODE,
        "pairing_seed": PAIRING_SEED if PAIRING_MODE != 'random' else None,
    }
    
    with open(os.path.join(RESULTS_FOLDER, "summary.json"), 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\nSummary zapisane w: {RESULTS_FOLDER}/summary.json")
    
    sys.exit(0 if success > 0 else 1)
