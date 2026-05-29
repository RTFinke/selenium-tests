from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
import time, random, string, os, sys, shutil, base64, json, traceback, hashlib, re, unicodedata
from pathlib import Path

GRID_URL = os.getenv('SELENIUM_GRID_URL', 'http://localhost:4444')
PREFIX = "biztest_"
HEADLESS = os.getenv('HEADLESS', 'false').lower() == 'true'
PAIRING_MODE = os.getenv('TEST_PAIRING_MODE', 'deterministic').strip().lower()
PAIRING_SEED = os.getenv('TEST_PAIRING_SEED', 'stable-v1').strip() or 'stable-v1'

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_PATH = os.path.join(SCRIPT_DIR, 'test_images')
BUTTON_CANDIDATE_SELECTOR = "button, [role='button'], input[type='button'], input[type='submit'], [class*='button'], [class*='Button']"
GENERATE_BUTTON_TEXTS = ['generuj', 'generate', 'try on', 'try-on', 'tryon']

PEOPLE_FOLDERS = {
    "women": os.path.join(BASE_PATH, "women_people"),
    "men": os.path.join(BASE_PATH, "men_people"),
}

GARMENT_RUNS = [
    {
        "key": "upper",
        "label": "Upper",
        "site_mode": "upper",
        "results_folder": os.path.join(SCRIPT_DIR, "test_results_upper"),
        "clothes_folders": {
            "women": os.path.join(BASE_PATH, "women_clothes"),
            "men": os.path.join(BASE_PATH, "men_clothes"),
        },
    },
    {
        "key": "lower",
        "label": "Lower",
        "site_mode": "lower",
        "results_folder": os.path.join(SCRIPT_DIR, "test_results_lower"),
        "clothes_folders": {
            "women": os.path.join(BASE_PATH, "women_lower_clothes"),
            "men": os.path.join(BASE_PATH, "men_lower_clothes"),
        },
    },
    {
        "key": "full",
        "label": "Full",
        "site_mode": "full",
        "results_folder": os.path.join(SCRIPT_DIR, "test_results_full"),
        "clothes_folders": {
            "women": os.path.join(BASE_PATH, "women_full_clothes"),
            "men": os.path.join(BASE_PATH, "men_full_clothes"),
        },
    },
]

RUN_SUMMARY_PATH = os.path.join(SCRIPT_DIR, "test_results_summary.json")

def generate_user():
    uid = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return {"email": f"{PREFIX}{uid}@test.com", "password": "TestPass123!"}

def list_supported_images(folder, sort_files=False):
    images = [
        f for f in os.listdir(folder)
        if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not f.startswith('.')
    ]
    return sorted(images) if sort_files else images

def canonicalize_ui_text(value):
    normalized = unicodedata.normalize('NFKC', str(value or ''))
    normalized = normalized.replace('\xa0', ' ')
    normalized = ' '.join(normalized.split()).lower()
    normalized = ''.join(
        char for char in unicodedata.normalize('NFKD', normalized)
        if not unicodedata.combining(char)
    )
    normalized = re.sub(r'[^a-z0-9]+', ' ', normalized)
    return normalized.strip()

def wait_for_document_ready(driver, timeout=30):
    WebDriverWait(driver, timeout).until(
        lambda current: current.execute_script("return document.readyState") == "complete"
    )

def get_button_text_variants(element):
    values = []
    for raw_value in [
        element.text,
        element.get_attribute('innerText'),
        element.get_attribute('textContent'),
        element.get_attribute('aria-label'),
        element.get_attribute('title'),
        element.get_attribute('value'),
        element.get_attribute('name'),
    ]:
        normalized = canonicalize_ui_text(raw_value)
        if normalized and normalized not in values:
            values.append(normalized)
    return values

def is_button_interactable(element):
    try:
        if not element.is_displayed() or not element.is_enabled():
            return False

        disabled = canonicalize_ui_text(element.get_attribute('disabled'))
        aria_disabled = canonicalize_ui_text(element.get_attribute('aria-disabled'))
        return disabled not in ('true', 'disabled') and aria_disabled != 'true'
    except (StaleElementReferenceException, NoSuchElementException):
        return False

def get_button_match_score(element, target_texts):
    text_variants = get_button_text_variants(element)
    if not text_variants:
        return None

    target_variants = []
    for target_text in target_texts:
        normalized = canonicalize_ui_text(target_text)
        if normalized and normalized not in target_variants:
            target_variants.append(normalized)

    if not target_variants:
        return None

    tag_name = canonicalize_ui_text(getattr(element, 'tag_name', ''))
    button_type = canonicalize_ui_text(element.get_attribute('type'))
    role = canonicalize_ui_text(element.get_attribute('role'))
    class_name = canonicalize_ui_text(element.get_attribute('class'))

    best_score = None
    for target in target_variants:
        for text_value in text_variants:
            if target not in text_value:
                continue

            score = 1
            if text_value == target:
                score += 4
            elif text_value.startswith(target):
                score += 2

            if tag_name == 'button':
                score += 2
            if button_type == 'submit':
                score += 3
            if role == 'button':
                score += 1
            if 'tab' in class_name.split():
                score -= 3

            if best_score is None or score > best_score:
                best_score = score

    return best_score

def find_button_safe(driver, texts):
    best_match = None
    best_score = None
    for btn in driver.find_elements(By.CSS_SELECTOR, BUTTON_CANDIDATE_SELECTOR):
        try:
            if not btn.is_displayed():
                continue

            score = get_button_match_score(btn, texts)
            if score is None:
                continue

            if best_score is None or score > best_score or (score == best_score and is_button_interactable(btn)):
                best_match = btn
                best_score = score
        except (StaleElementReferenceException, NoSuchElementException):
            continue
    return best_match

def wait_for_button_safe(driver, texts, timeout=20, require_enabled=True):
    try:
        return WebDriverWait(driver, timeout).until(
            lambda current: (
                (button := find_button_safe(current, texts)) and
                (not require_enabled or is_button_interactable(button)) and
                button
            ) or False
        )
    except TimeoutException:
        return None

def dispatch_file_input_events(driver, input_element):
    driver.execute_script("""
    const input = arguments[0];
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    """, input_element)

def describe_button_candidates(driver, limit=12):
    descriptions = []
    for btn in driver.find_elements(By.CSS_SELECTOR, BUTTON_CANDIDATE_SELECTOR):
        if len(descriptions) >= limit:
            break

        try:
            text_variants = get_button_text_variants(btn)
            descriptions.append(
                "tag={tag} role={role} enabled={enabled} text={text}".format(
                    tag=canonicalize_ui_text(getattr(btn, 'tag_name', '')) or '-',
                    role=canonicalize_ui_text(btn.get_attribute('role')) or '-',
                    enabled=is_button_interactable(btn),
                    text=' | '.join(text_variants[:2]) or '<empty>',
                )
            )
        except (StaleElementReferenceException, NoSuchElementException):
            continue

    return descriptions

def get_all_models(run_config):
    models = []
    skipped_genders = []

    for gender in ["women", "men"]:
        people_folder = PEOPLE_FOLDERS[gender]
        clothes_folder = run_config["clothes_folders"][gender]
        people_images = list_supported_images(people_folder, sort_files=True)
        garment_images = list_supported_images(clothes_folder, sort_files=True)

        if not people_images or not garment_images:
            skipped_genders.append(gender)
            continue

        if PAIRING_MODE == 'all':
            for person_name in people_images:
                for garment_index, garment_name in enumerate(garment_images):
                    models.append({
                        "gender": gender,
                        "person_path": os.path.join(people_folder, person_name),
                        "person_name": person_name,
                        "clothes_folder": clothes_folder,
                        "garment_run_key": run_config["key"],
                        "garment_site_mode": run_config["site_mode"],
                        "preselected_garment_path": os.path.join(clothes_folder, garment_name),
                        "preselected_garment_name": garment_name,
                        "preselected_garment_index": garment_index,
                        "preselected_garment_pool_size": len(garment_images),
                    })
            continue

        for person_name in people_images:
            models.append({
                "gender": gender,
                "person_path": os.path.join(people_folder, person_name),
                "person_name": person_name,
                "clothes_folder": clothes_folder,
                "garment_run_key": run_config["key"],
                "garment_site_mode": run_config["site_mode"],
            })
    
    return models, skipped_genders

def get_garment_for_model(clothes_folder, model_info):
    preselected_garment_path = model_info.get("preselected_garment_path")
    if preselected_garment_path:
        return {
            "path": preselected_garment_path,
            "mode": "all",
            "seed": None,
            "index": model_info.get("preselected_garment_index"),
            "pool_size": model_info.get("preselected_garment_pool_size"),
        }

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
    const upper = scan('upper');
    const lower = scan('lower');
    const full = scan('full');

    let qualityMode = null;
    let qualitySource = null;
    if (standard.selected === true || premium.selected === false) {
        qualityMode = 'standard';
        qualitySource = standard.selected === true ? standard.source : premium.source;
    } else if (premium.selected === true || standard.selected === false) {
        qualityMode = 'premium';
        qualitySource = premium.selected === true ? premium.source : standard.source;
    }

    let garmentMode = null;
    let garmentModeSource = null;
    if (upper.selected === true) {
        garmentMode = 'upper';
        garmentModeSource = upper.source;
    } else if (lower.selected === true) {
        garmentMode = 'lower';
        garmentModeSource = lower.source;
    } else if (full.selected === true) {
        garmentMode = 'full';
        garmentModeSource = full.source;
    }

    return {
        quality_mode_selected: qualityMode,
        quality_mode_state_source: qualitySource,
        garment_mode_selected: garmentMode,
        garment_mode_state_source: garmentModeSource,
        turbo_enabled: turbo.selected,
        turbo_state_source: turbo.source,
        standard_found: standard.found,
        premium_found: premium.found,
        turbo_found: turbo.found,
        upper_found: upper.found,
        lower_found: lower.found,
        full_found: full.found,
    };
    """)

    return option_state if isinstance(option_state, dict) else None

def ensure_garment_site_mode(driver, desired_mode):
    mode_state = driver.execute_script("""
    const desiredLabel = String(arguments[0] || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    const clickIfNeeded = arguments[1];

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
            "button, label, [role='button'], [role='tab'], [role='radio'], div, span"
        ));
        return candidates.filter((el) => isVisible(el) && labelMatches(el, label));
    };

    const getControlsForAnchor = (anchor) => unique([
        anchor.closest && anchor.closest('button'),
        anchor.closest && anchor.closest('label'),
        anchor.closest && anchor.closest("[role='button']"),
        anchor.closest && anchor.closest("[role='tab']"),
        anchor.closest && anchor.closest("[role='radio']"),
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
                "input[type='radio'], [role='tab'], [role='radio'], [aria-selected], [aria-checked], [aria-pressed], [data-state]"
            ),
        ]);

        for (const node of nodes) {
            if (!node) continue;

            if (node.matches && node.matches("input[type='radio']")) {
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
            if (['mui-selected', 'selected', 'active', 'checked', 'current'].some((token) => className.includes(token))) {
                return { selected: true, source: 'class' };
            }
        }

        return null;
    };

    const labels = ['upper', 'lower', 'full'];

    const scanLabel = (label) => {
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

    const scanAll = () => {
        const states = {};
        for (const label of labels) {
            states[label] = scanLabel(label);
        }
        return states;
    };

    let states = scanAll();
    if (!states[desiredLabel] || !states[desiredLabel].found) {
        return {
            found: false,
            selected: false,
            clicked: false,
            state_source: null,
            selected_label: null,
        };
    }

    const getSelectedLabel = () => labels.find((label) => states[label] && states[label].selected === true) || null;
    let selectedLabel = getSelectedLabel();

    if (selectedLabel === desiredLabel) {
        return {
            found: true,
            selected: true,
            clicked: false,
            state_source: states[desiredLabel].source,
            selected_label: selectedLabel,
        };
    }

    if (!clickIfNeeded) {
        return {
            found: true,
            selected: states[desiredLabel].selected,
            clicked: false,
            state_source: states[desiredLabel].source,
            selected_label: selectedLabel,
        };
    }

    let clickedAny = false;
    for (const anchor of getAnchors(desiredLabel)) {
        for (const control of getControlsForAnchor(anchor)) {
            try {
                control.scrollIntoView({ block: 'center', inline: 'center' });
                control.click();
                clickedAny = true;
                states = scanAll();
                selectedLabel = getSelectedLabel();
                if (selectedLabel === desiredLabel) {
                    return {
                        found: true,
                        selected: true,
                        clicked: true,
                        state_source: states[desiredLabel].source,
                        selected_label: selectedLabel,
                    };
                }
            } catch (error) {
                // Try the next candidate.
            }
        }
    }

    states = scanAll();
    selectedLabel = getSelectedLabel();
    return {
        found: true,
        selected: selectedLabel === desiredLabel,
        clicked: clickedAny,
        state_source: states[desiredLabel].source,
        selected_label: selectedLabel,
    };
    """, desired_mode, True)

    if not mode_state or not mode_state.get("found"):
        raise Exception(f"Nie znaleziono przycisku trybu odziezy: {desired_mode}")

    if mode_state.get("selected") is True:
        return mode_state

    if mode_state.get("clicked"):
        time.sleep(1)
        mode_state = driver.execute_script("""
        const desiredLabel = String(arguments[0] || '').replace(/\\s+/g, ' ').trim().toLowerCase();
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
                "button, label, [role='button'], [role='tab'], [role='radio'], div, span"
            ));
            return candidates.filter((el) => isVisible(el) && labelMatches(el, label));
        };
        const getControlsForAnchor = (anchor) => unique([
            anchor.closest && anchor.closest('button'),
            anchor.closest && anchor.closest('label'),
            anchor.closest && anchor.closest("[role='button']"),
            anchor.closest && anchor.closest("[role='tab']"),
            anchor.closest && anchor.closest("[role='radio']"),
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
                    "input[type='radio'], [role='tab'], [role='radio'], [aria-selected], [aria-checked], [aria-pressed], [data-state]"
                ),
            ]);
            for (const node of nodes) {
                if (!node) continue;
                if (node.matches && node.matches("input[type='radio']")) {
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
                if (['mui-selected', 'selected', 'active', 'checked', 'current'].some((token) => className.includes(token))) {
                    return { selected: true, source: 'class' };
                }
            }
            return null;
        };
        const labels = ['upper', 'lower', 'full'];
        const states = {};
        for (const label of labels) {
            states[label] = { found: false, selected: null, source: null };
            const anchors = getAnchors(label);
            for (const anchor of anchors) {
                for (const control of getControlsForAnchor(anchor)) {
                    const state = readState(control);
                    if (state) {
                        states[label] = { found: true, selected: state.selected, source: state.source };
                        break;
                    }
                }
                if (states[label].found && states[label].selected !== null) {
                    break;
                }
            }
            if (!states[label].found) {
                states[label].found = anchors.length > 0;
            }
        }
        const selectedLabel = labels.find((label) => states[label] && states[label].selected === true) || null;
        return {
            found: states[desiredLabel] ? states[desiredLabel].found : false,
            selected: selectedLabel === desiredLabel,
            clicked: false,
            state_source: states[desiredLabel] ? states[desiredLabel].source : null,
            selected_label: selectedLabel,
        };
        """, desired_mode)
        if mode_state and mode_state.get("selected") is True:
            return mode_state

    raise Exception(f"Nie udalo sie potwierdzic wyboru trybu odziezy: {desired_mode}")

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
    const upperControl = getControl(getAnchor('upper'));
    const lowerControl = getControl(getAnchor('lower'));
    const fullControl = getControl(getAnchor('full'));
    const captureElement = findCaptureElement([
        standardControl,
        premiumControl,
        turboControl,
        upperControl,
        lowerControl,
        fullControl,
    ]);

    if (!captureElement) {
        return null;
    }

    captureElement.scrollIntoView({ block: 'center', inline: 'center' });
    return [
        captureElement,
        standardControl,
        premiumControl,
        turboControl,
        upperControl,
        lowerControl,
        fullControl,
    ];
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

def test_single_model(test_num, model_info, run_config):
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
        "garment_run_key": run_config["key"],
        "garment_run_label": run_config["label"],
        "garment_mode_requested": run_config["site_mode"],
        "garment_mode_selected": None,
        "garment_mode_state_source": None,
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
        
        test_folder = os.path.join(run_config["results_folder"], test_id)
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
        wait_for_document_ready(driver, 30)
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
        wait_for_document_ready(driver, 30)
        time.sleep(10)
        
        for attempt in range(3):
            try:
                wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "input[type='file']")))
                break
            except TimeoutException:
                if attempt < 2:
                    print(f"  Retry {attempt+1} - odswiezam strone...")
                    driver.refresh()
                    wait_for_document_ready(driver, 20)
                    time.sleep(7)
                else:
                    raise Exception("Timeout: nie znaleziono file inputs po 3 probach")
        
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        
        if len(file_inputs) < 2:
            raise Exception(f"Za malo file inputs: {len(file_inputs)}")
        
        file_inputs[0].send_keys(model_info['person_path'])
        dispatch_file_input_events(driver, file_inputs[0])
        time.sleep(4)
        
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        file_inputs[1].send_keys(garment_path)
        dispatch_file_input_events(driver, file_inputs[1])
        time.sleep(4)

        garment_mode_state = ensure_garment_site_mode(driver, run_config["site_mode"])
        if garment_mode_state:
            metadata["garment_mode_selected"] = garment_mode_state.get("selected_label")
            metadata["garment_mode_state_source"] = garment_mode_state.get("state_source")
            print(f"  OK Tryb odziezy: {metadata['garment_mode_selected']}")

        option_state = read_generation_option_state(driver)
        if option_state:
            metadata["garment_mode_selected"] = option_state.get("garment_mode_selected") or metadata["garment_mode_selected"]
            metadata["garment_mode_state_source"] = option_state.get("garment_mode_state_source") or metadata["garment_mode_state_source"]
            metadata["quality_mode_selected"] = option_state.get("quality_mode_selected")
            metadata["quality_mode_state_source"] = option_state.get("quality_mode_state_source")
            metadata["turbo_enabled"] = option_state.get("turbo_enabled")
            metadata["turbo_state_source"] = option_state.get("turbo_state_source")
            print(
                f"  Opcje: garment={metadata['garment_mode_selected'] or 'unknown'} | "
                f"quality={metadata['quality_mode_selected'] or 'unknown'} | "
                f"turbo={metadata['turbo_enabled'] if metadata['turbo_enabled'] is not None else 'unknown'}"
            )

        option_confirmation_path = os.path.join(test_folder, "option_confirmation.png")
        if capture_option_confirmation(driver, option_confirmation_path):
            metadata["option_confirmation_screenshot"] = option_confirmation_path
            print(f"  OK Screenshot opcji zapisany: option_confirmation.png")
        else:
            print(f"  WARN Nie udalo sie zapisac screenshotu opcji")
        
        generate_btn = wait_for_button_safe(driver, GENERATE_BUTTON_TEXTS, timeout=25, require_enabled=True)
        if not generate_btn:
            disabled_generate_btn = wait_for_button_safe(driver, GENERATE_BUTTON_TEXTS, timeout=1, require_enabled=False)
            button_candidates = describe_button_candidates(driver)
            metadata["visible_button_candidates"] = button_candidates
            if disabled_generate_btn:
                metadata["generate_button_detected_but_disabled"] = get_button_text_variants(disabled_generate_btn)
            details = " | ".join(button_candidates[:6]) if button_candidates else "brak widocznych kandydatow"
            if disabled_generate_btn:
                disabled_label = ' / '.join(get_button_text_variants(disabled_generate_btn)) or 'unknown'
                raise Exception(f"Przycisk generacji istnieje, ale pozostal wylaczony: {disabled_label}. Kandydaci: {details}")
            raise Exception(f"Brak przycisku Generuj/Tryon. Kandydaci: {details}")
        
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", generate_btn)
        time.sleep(1)
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
            result_img = WebDriverWait(driver, 60).until(result_image_present)
        except TimeoutException:
            raise Exception("Timeout: nie znaleziono wyniku generacji po 60s")
        
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
        
        test_folder = os.path.join(run_config["results_folder"], test_id)
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

def write_run_summary(run_config, total_tests, success, failed, elapsed_total, skipped_genders):
    results_folder = run_config["results_folder"]
    summary = {
        "run_key": run_config["key"],
        "run_label": run_config["label"],
        "garment_mode": run_config["site_mode"],
        "total_tests": total_tests,
        "successful": success,
        "failed": failed,
        "success_rate": f"{(success / total_tests * 100):.1f}%" if total_tests > 0 else "0.0%",
        "duration_seconds": int(elapsed_total),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "test_results_folder": results_folder,
        "headless_mode": HEADLESS,
        "pairing_mode": PAIRING_MODE,
        "pairing_seed": PAIRING_SEED if PAIRING_MODE != 'random' else None,
        "skipped_genders_without_garments": skipped_genders,
    }

    with open(os.path.join(results_folder, "summary.json"), 'w') as f:
        json.dump(summary, f, indent=2)

    return summary

def run_test_suite(run_config):
    print(f"\n{'='*60}")
    print(f"RUN: {run_config['label'].upper()}")
    print(f"{'='*60}")

    results_folder = run_config["results_folder"]
    os.makedirs(results_folder, exist_ok=True)

    all_models, skipped_genders = get_all_models(run_config)
    total_tests = len(all_models)

    if skipped_genders:
        print(f"  Pomijam bez ubrań: {', '.join(skipped_genders)}")

    print(f"  Wyniki: {results_folder}")
    print(f"  Testowanie {total_tests} modeli")
    print(f"  Women: {len([m for m in all_models if m['gender'] == 'women'])}")
    print(f"  Men: {len([m for m in all_models if m['gender'] == 'men'])}")

    if total_tests == 0:
        summary = write_run_summary(run_config, 0, 0, 0, 0, skipped_genders)
        print(f"  Brak testów do uruchomienia dla {run_config['label']}")
        print(f"  Summary zapisane w: {results_folder}/summary.json")
        return summary

    success = 0
    failed = 0
    start_time = time.time()

    for i, model in enumerate(all_models, 1):
        if test_single_model(i, model, run_config):
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
    print(f"PODSUMOWANIE {run_config['label'].upper()}")
    print(f"{'='*60}")
    print(f"Sukces: {success}/{total_tests} ({success/total_tests*100:.1f}%)")
    print(f"Bledy: {failed}/{total_tests}")
    print(f"Czas: {int(elapsed_total/60)}min {int(elapsed_total%60)}s")
    print(f"Wyniki: {results_folder}")

    summary = write_run_summary(run_config, total_tests, success, failed, elapsed_total, skipped_genders)
    print(f"\nSummary zapisane w: {results_folder}/summary.json")
    return summary

if __name__ == "__main__":
    print("SIZ3R BUSINESS TESTS - ALL MODELS")
    print(f"Headless mode: {HEADLESS}")
    print(f"Pairing mode: {PAIRING_MODE}")
    if PAIRING_MODE != 'random':
        print(f"Pairing seed: {PAIRING_SEED}")

    required_paths = {
        "women_people": PEOPLE_FOLDERS["women"],
        "men_people": PEOPLE_FOLDERS["men"],
    }
    for run_config in GARMENT_RUNS:
        required_paths[f"{run_config['key']}_women_clothes"] = run_config["clothes_folders"]["women"]
        required_paths[f"{run_config['key']}_men_clothes"] = run_config["clothes_folders"]["men"]

    missing = [key for key, value in required_paths.items() if not os.path.exists(value)]
    if missing:
        print(f"Brakuje: {', '.join(missing)}")
        sys.exit(1)

    print("Folder counts:")
    for label, path in required_paths.items():
        count = len(list_supported_images(path))
        print(f"  {label}: {count} zdjec")

    run_summaries = {}
    for run_config in GARMENT_RUNS:
        run_summaries[run_config["key"]] = run_test_suite(run_config)

    with open(RUN_SUMMARY_PATH, 'w') as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "headless_mode": HEADLESS,
            "pairing_mode": PAIRING_MODE,
            "pairing_seed": PAIRING_SEED if PAIRING_MODE != 'random' else None,
            "runs": run_summaries,
        }, f, indent=2)

    print(f"\nCombined summary zapisane w: {RUN_SUMMARY_PATH}")

    completed_run_summaries = [
        summary for summary in run_summaries.values()
        if summary.get("total_tests", 0) > 0
    ]
    all_completed_runs_clean = completed_run_summaries and all(
        summary.get("failed", 0) == 0 and
        summary.get("successful", 0) == summary.get("total_tests", 0)
        for summary in completed_run_summaries
    )
    sys.exit(0 if all_completed_runs_clean else 1)
