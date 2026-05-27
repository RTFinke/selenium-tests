from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time, random, string, os, sys, shutil, base64, json, traceback, hashlib
from html import escape as html_escape
from pathlib import Path

GRID_URL = os.getenv('SELENIUM_GRID_URL', 'http://localhost:4444')
PREFIX = "biztest_"
HEADLESS = os.getenv('HEADLESS', 'false').lower() == 'true'
PAIRING_MODE = os.getenv('TEST_PAIRING_MODE', 'deterministic').strip().lower()
PAIRING_SEED = os.getenv('TEST_PAIRING_SEED', 'stable-v1').strip() or 'stable-v1'

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_PATH = os.path.join(SCRIPT_DIR, 'test_images')

def first_existing_directory(*candidates):
    for candidate in candidates:
        if not candidate:
            continue
        if os.path.isdir(candidate):
            return os.path.abspath(candidate)
    return None

def resolve_existing_folder(*relative_paths):
    candidates = [os.path.join(BASE_PATH, relative_path) for relative_path in relative_paths]
    for candidate in candidates:
        if not os.path.isdir(candidate):
            continue
        try:
            if any(
                entry.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
                for entry in os.listdir(candidate)
            ):
                return candidate
        except OSError:
            continue
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    return candidates[-1]

PEOPLE_FOLDERS = {
    "women": resolve_existing_folder("woman_photo", "women_people"),
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
DEFAULT_FLAT_MODEL_ROOT = first_existing_directory(
    os.getenv('FLAT_MODEL_SOURCE_ROOT'),
    os.path.join(SCRIPT_DIR, 'FlatAndModel'),
    os.path.join(BASE_PATH, 'FlatAndModel'),
    r'C:\Users\suici\OneDrive\Documents\FlatAndModel',
)
FLAT_GARMENTS_FOLDER = first_existing_directory(
    os.getenv('FLAT_GARMENTS_FOLDER'),
    os.path.join(DEFAULT_FLAT_MODEL_ROOT, 'flat') if DEFAULT_FLAT_MODEL_ROOT else None,
) or os.path.abspath(os.path.join(SCRIPT_DIR, 'FlatAndModel', 'flat'))
MODEL_GARMENTS_FOLDER = first_existing_directory(
    os.getenv('MODEL_GARMENTS_FOLDER'),
    os.path.join(DEFAULT_FLAT_MODEL_ROOT, 'model') if DEFAULT_FLAT_MODEL_ROOT else None,
) or os.path.abspath(os.path.join(SCRIPT_DIR, 'FlatAndModel', 'model'))
FLAT_MODEL_SITE_MODE = os.getenv('FLAT_MODEL_SITE_MODE', 'upper').strip().lower() or 'upper'
PAIRED_RESULTS_FOLDER = os.path.join(SCRIPT_DIR, "test_results_flat_vs_model")
PAIRED_REPORT_PATH = os.path.join(PAIRED_RESULTS_FOLDER, "index.html")
PAIRED_RUN_CONFIG = {
    "key": "paired",
    "label": "Flat vs Model",
    "site_mode": FLAT_MODEL_SITE_MODE,
    "results_folder": PAIRED_RESULTS_FOLDER,
}

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

def find_tryon_button(driver):
    buttons = driver.find_elements(By.TAG_NAME, "button")
    preferred_tokens = ['tryon', 'try on', 'generuj', 'generate']

    for btn in buttons:
        try:
            btn_text = ' '.join((btn.text or '').strip().lower().split())
            if not btn_text:
                continue

            if any(token in btn_text for token in preferred_tokens):
                return btn
        except Exception:
            continue

    for btn in buttons:
        try:
            btn_text = ' '.join((btn.text or '').strip().lower().split())
            if not btn_text:
                continue

            if '$' in btn_text or 'credit' in btn_text or 'token' in btn_text:
                return btn
        except Exception:
            continue

    return None

def pair_sort_key(value):
    text = str(value or "").strip()
    return (0, int(text)) if text.isdigit() else (1, text.lower())

def get_primary_woman_model():
    people_folder = PEOPLE_FOLDERS["women"]
    people_images = list_supported_images(people_folder, sort_files=True)
    if not people_images:
        raise Exception(f"Brak zdjec modelki w: {people_folder}")

    selected_person = people_images[0]
    return {
        "person_folder": people_folder,
        "person_name": selected_person,
        "person_path": os.path.join(people_folder, selected_person),
        "person_image_count": len(people_images),
    }

def collect_flat_model_pairs():
    flat_images = {
        Path(filename).stem: filename
        for filename in list_supported_images(FLAT_GARMENTS_FOLDER, sort_files=True)
    }
    model_images = {
        Path(filename).stem: filename
        for filename in list_supported_images(MODEL_GARMENTS_FOLDER, sort_files=True)
    }

    paired_keys = sorted(set(flat_images) & set(model_images), key=pair_sort_key)
    flat_only = sorted(set(flat_images) - set(model_images), key=pair_sort_key)
    model_only = sorted(set(model_images) - set(flat_images), key=pair_sort_key)

    pairs = []
    for pair_index, pair_key in enumerate(paired_keys, 1):
        pairs.append({
            "pair_key": pair_key,
            "pair_index": pair_index,
            "flat_name": flat_images[pair_key],
            "flat_path": os.path.join(FLAT_GARMENTS_FOLDER, flat_images[pair_key]),
            "model_name": model_images[pair_key],
            "model_path": os.path.join(MODEL_GARMENTS_FOLDER, model_images[pair_key]),
        })

    return pairs, flat_only, model_only

def build_paired_tryon_job(person_info, pair_info, source_variant, total_pairs):
    if source_variant not in {"flat", "model"}:
        raise ValueError(f"Unsupported source variant: {source_variant}")

    garment_name = pair_info[f"{source_variant}_name"]
    garment_path = pair_info[f"{source_variant}_path"]
    return {
        "gender": "women",
        "person_path": person_info["person_path"],
        "person_name": person_info["person_name"],
        "person_image_count": person_info["person_image_count"],
        "clothes_folder": os.path.dirname(garment_path),
        "garment_run_key": PAIRED_RUN_CONFIG["key"],
        "garment_site_mode": PAIRED_RUN_CONFIG["site_mode"],
        "garment_path": garment_path,
        "garment_name": garment_name,
        "garment_selection_mode": "paired-sequence",
        "garment_selection_seed": None,
        "garment_selection_index": pair_info["pair_index"] - 1,
        "garment_pool_size": total_pairs,
        "pair_key": pair_info["pair_key"],
        "pair_index": pair_info["pair_index"],
        "source_variant": source_variant,
        "flat_requested": source_variant == "flat",
        "comparison_model_garment_name": pair_info["model_name"],
    }

def get_all_models(run_config):
    models = []
    skipped_genders = []

    for gender in ["women"]:
        people_folder = PEOPLE_FOLDERS[gender]
        clothes_folder = run_config["clothes_folders"][gender]
        garment_images = list_supported_images(clothes_folder, sort_files=True)

        if not garment_images:
            skipped_genders.append(gender)
            continue

        people_images = list_supported_images(people_folder, sort_files=True)
        if not people_images:
            continue

        selected_person = people_images[0]
        person_path = os.path.join(people_folder, selected_person)
        for garment_index, garment_name in enumerate(garment_images):
            models.append({
                "gender": gender,
                "person_path": person_path,
                "person_name": selected_person,
                "person_image_count": len(people_images),
                "clothes_folder": clothes_folder,
                "garment_run_key": run_config["key"],
                "garment_site_mode": run_config["site_mode"],
                "garment_path": os.path.join(clothes_folder, garment_name),
                "garment_name": garment_name,
                "garment_selection_mode": "sequential",
                "garment_selection_seed": None,
                "garment_selection_index": garment_index,
                "garment_pool_size": len(garment_images),
            })
    
    return models, skipped_genders

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
    const upper = scan('upper');
    const lower = scan('lower');
    const full = scan('full');
    const flat = scan('flat');

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
        flat_enabled: flat.selected,
        flat_state_source: flat.source,
        standard_found: standard.found,
        premium_found: premium.found,
        turbo_found: turbo.found,
        upper_found: upper.found,
        lower_found: lower.found,
        full_found: full.found,
        flat_found: flat.found,
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

def ensure_labeled_toggle_state(driver, desired_label, should_enable):
    toggle_state = driver.execute_script("""
    const desiredLabel = String(arguments[0] || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    const clickIfNeeded = arguments[1];
    const desiredSelected = Boolean(arguments[2]);

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
            "button, label, [role='button'], [role='checkbox'], [role='switch'], div, span"
        ));
        return candidates.filter((el) => isVisible(el) && labelMatches(el, label));
    };

    const getControlsForAnchor = (anchor) => unique([
        anchor.closest && anchor.closest('button'),
        anchor.closest && anchor.closest('label'),
        anchor.closest && anchor.closest("[role='button']"),
        anchor.closest && anchor.closest("[role='checkbox']"),
        anchor.closest && anchor.closest("[role='switch']"),
        anchor,
        anchor.previousElementSibling,
        anchor.nextElementSibling,
        anchor.parentElement,
        anchor.parentElement && anchor.parentElement.parentElement,
    ].filter(Boolean)).filter(isVisible);

    const readState = (root) => {
        if (!root) return null;

        const nodes = unique([
            root,
            ...root.querySelectorAll(
                "input[type='checkbox'], [role='checkbox'], [role='switch'], [aria-checked], [aria-pressed], [data-state]"
            ),
        ]);

        for (const node of nodes) {
            if (!node) continue;

            if (node.matches && node.matches("input[type='checkbox']")) {
                return { selected: Boolean(node.checked), source: 'input.checked' };
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
            if (['mui-checked', 'selected', 'active', 'checked', 'current'].some((token) => className.includes(token))) {
                return { selected: true, source: 'class' };
            }
        }

        return null;
    };

    const scan = () => {
        const anchors = getAnchors(desiredLabel);
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

    let state = scan();
    if (!state.found) {
        return {
            found: false,
            selected: false,
            clicked: false,
            state_source: null,
        };
    }

    if (state.selected === desiredSelected) {
        return {
            found: true,
            selected: state.selected === true,
            clicked: false,
            state_source: state.source,
        };
    }

    if (!clickIfNeeded) {
        return {
            found: true,
            selected: state.selected,
            clicked: false,
            state_source: state.source,
        };
    }

    let clickedAny = false;
    for (const anchor of getAnchors(desiredLabel)) {
        for (const control of getControlsForAnchor(anchor)) {
            try {
                control.scrollIntoView({ block: 'center', inline: 'center' });
                control.click();
                clickedAny = true;
                state = scan();
                if (state.selected === desiredSelected) {
                    return {
                        found: true,
                        selected: state.selected === true,
                        clicked: true,
                        state_source: state.source,
                    };
                }
            } catch (error) {
                // Try the next candidate.
            }
        }
    }

    state = scan();
    return {
        found: true,
        selected: state.selected === true,
        clicked: clickedAny,
        state_source: state.source,
    };
    """, desired_label, True, should_enable)

    if not toggle_state or not toggle_state.get("found"):
        raise Exception(f"Nie znaleziono przelacznika opcji: {desired_label}")

    if toggle_state.get("selected") is should_enable:
        return toggle_state

    if toggle_state.get("clicked"):
        time.sleep(1)
        toggle_state = driver.execute_script("""
        const desiredLabel = String(arguments[0] || '').replace(/\\s+/g, ' ').trim().toLowerCase();
        const desiredSelected = Boolean(arguments[1]);
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
                "button, label, [role='button'], [role='checkbox'], [role='switch'], div, span"
            ));
            return candidates.filter((el) => isVisible(el) && labelMatches(el, label));
        };

        const getControlsForAnchor = (anchor) => unique([
            anchor.closest && anchor.closest('button'),
            anchor.closest && anchor.closest('label'),
            anchor.closest && anchor.closest("[role='button']"),
            anchor.closest && anchor.closest("[role='checkbox']"),
            anchor.closest && anchor.closest("[role='switch']"),
            anchor,
            anchor.previousElementSibling,
            anchor.nextElementSibling,
            anchor.parentElement,
            anchor.parentElement && anchor.parentElement.parentElement,
        ].filter(Boolean)).filter(isVisible);

        const readState = (root) => {
            if (!root) return null;

            const nodes = unique([
                root,
                ...root.querySelectorAll(
                    "input[type='checkbox'], [role='checkbox'], [role='switch'], [aria-checked], [aria-pressed], [data-state]"
                ),
            ]);

            for (const node of nodes) {
                if (!node) continue;

                if (node.matches && node.matches("input[type='checkbox']")) {
                    return { selected: Boolean(node.checked), source: 'input.checked' };
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
                if (['mui-checked', 'selected', 'active', 'checked', 'current'].some((token) => className.includes(token))) {
                    return { selected: true, source: 'class' };
                }
            }

            return null;
        };

        const anchors = getAnchors(desiredLabel);
        for (const anchor of anchors) {
            for (const control of getControlsForAnchor(anchor)) {
                const state = readState(control);
                if (state) {
                    return {
                        found: true,
                        selected: state.selected === true,
                        clicked: false,
                        state_source: state.source,
                    };
                }
            }
        }

        return {
            found: anchors.length > 0,
            selected: false,
            clicked: false,
            state_source: null,
        };
        """, desired_label, should_enable)
        if toggle_state and toggle_state.get("selected") is should_enable:
            return toggle_state

    expected_state = 'wlaczona' if should_enable else 'wylaczona'
    raise Exception(f"Nie udalo sie ustawic opcji {desired_label} na stan: {expected_state}")

def ensure_labeled_toggle_enabled(driver, desired_label):
    return ensure_labeled_toggle_state(driver, desired_label, True)

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
    const flatControl = getControl(getAnchor('flat'));
    const captureElement = findCaptureElement([
        standardControl,
        premiumControl,
        turboControl,
        upperControl,
        lowerControl,
        fullControl,
        flatControl,
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
        flatControl,
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
    garment_name_clean = Path(model_info.get('garment_name', '')).stem
    pair_key = str(model_info.get("pair_key") or "").strip()
    source_variant = str(model_info.get("source_variant") or "").strip().lower()
    if pair_key and source_variant:
        test_id = f"pair_{pair_key}_{source_variant}"
    else:
        test_id = f"test_{test_num}_{model_info['gender']}_{model_name_clean}"
        if garment_name_clean:
            test_id = f"{test_id}_{garment_name_clean}"
    
    metadata = {
        "test_number": test_num,
        "test_id": test_id,
        "gender": model_info['gender'],
        "pair_key": pair_key or None,
        "pair_index": model_info.get("pair_index"),
        "source_variant": source_variant or None,
        "model_filename": model_info['person_name'],
        "user_email": user['email'],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "headless": HEADLESS,
        "pairing_mode": PAIRING_MODE,
        "pairing_seed": PAIRING_SEED if PAIRING_MODE != 'random' else None,
        "person_image_count": model_info.get("person_image_count"),
        "garment_run_key": run_config["key"],
        "garment_run_label": run_config["label"],
        "garment_mode_requested": run_config["site_mode"],
        "garment_mode_selected": None,
        "garment_mode_state_source": None,
        "flat_requested": bool(model_info.get("flat_requested", False)),
        "quality_mode_selected": None,
        "quality_mode_state_source": None,
        "turbo_enabled": None,
        "turbo_state_source": None,
        "flat_enabled": None,
        "flat_state_source": None,
        "option_confirmation_screenshot": None,
    }
    
    try:
        if model_info.get("garment_path"):
            garment_path = model_info["garment_path"]
            garment_name = model_info.get("garment_name") or os.path.basename(garment_path)
            garment_selection = {
                "path": garment_path,
                "mode": model_info.get("garment_selection_mode", "preselected"),
                "seed": model_info.get("garment_selection_seed"),
                "index": model_info.get("garment_selection_index"),
                "pool_size": model_info.get("garment_pool_size"),
            }
        else:
            garment_selection = get_garment_for_model(model_info['clothes_folder'], model_info)
            garment_path = garment_selection["path"]
            garment_name = os.path.basename(garment_path)

        metadata["garment_filename"] = garment_name
        metadata["garment_selection_mode"] = garment_selection["mode"]
        metadata["garment_selection_seed"] = garment_selection["seed"]
        metadata["garment_selection_index"] = garment_selection["index"]
        metadata["garment_pool_size"] = garment_selection["pool_size"]
        
        print(f"\n[{test_num}] {user['email']} | {model_info['gender']}")
        if pair_key and source_variant:
            print(f"  Pair: {pair_key} | Variant: {source_variant}")
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

        garment_mode_state = ensure_garment_site_mode(driver, run_config["site_mode"])
        if garment_mode_state:
            metadata["garment_mode_selected"] = garment_mode_state.get("selected_label")
            metadata["garment_mode_state_source"] = garment_mode_state.get("state_source")
            print(f"  OK Tryb odziezy: {metadata['garment_mode_selected']}")

        desired_flat_state = bool(model_info.get("flat_requested", False))
        flat_option_state = ensure_labeled_toggle_state(driver, "flat", desired_flat_state)
        if flat_option_state:
            metadata["flat_enabled"] = flat_option_state.get("selected")
            metadata["flat_state_source"] = flat_option_state.get("state_source")
            print(f"  OK Flat: {metadata['flat_enabled']} (wanted {desired_flat_state})")

        option_state = read_generation_option_state(driver)
        if option_state:
            metadata["garment_mode_selected"] = option_state.get("garment_mode_selected") or metadata["garment_mode_selected"]
            metadata["garment_mode_state_source"] = option_state.get("garment_mode_state_source") or metadata["garment_mode_state_source"]
            metadata["quality_mode_selected"] = option_state.get("quality_mode_selected")
            metadata["quality_mode_state_source"] = option_state.get("quality_mode_state_source")
            metadata["turbo_enabled"] = option_state.get("turbo_enabled")
            metadata["turbo_state_source"] = option_state.get("turbo_state_source")
            metadata["flat_enabled"] = option_state.get("flat_enabled")
            metadata["flat_state_source"] = option_state.get("flat_state_source")
            print(
                f"  Opcje: garment={metadata['garment_mode_selected'] or 'unknown'} | "
                f"quality={metadata['quality_mode_selected'] or 'unknown'} | "
                f"turbo={metadata['turbo_enabled'] if metadata['turbo_enabled'] is not None else 'unknown'} | "
                f"flat={metadata['flat_enabled'] if metadata['flat_enabled'] is not None else 'unknown'}"
            )

        option_confirmation_path = os.path.join(test_folder, "option_confirmation.png")
        if capture_option_confirmation(driver, option_confirmation_path):
            metadata["option_confirmation_screenshot"] = option_confirmation_path
            print(f"  OK Screenshot opcji zapisany: option_confirmation.png")
        else:
            print(f"  WARN Nie udalo sie zapisac screenshotu opcji")
        
        generate_btn = find_tryon_button(driver)
        if not generate_btn:
            raise Exception("Brak przycisku Tryon/Generate")
        
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
    selected_model_name = all_models[0]["person_name"] if all_models else None

    if skipped_genders:
        print(f"  Pomijam bez ubrań: {', '.join(skipped_genders)}")

    print(f"  Wyniki: {results_folder}")
    print(f"  Testowanie {total_tests} try-onow")
    if selected_model_name:
        print(f"  Woman photo: {selected_model_name}")
    if all_models and (all_models[0].get("person_image_count") or 0) > 1:
        ignored_count = all_models[0]["person_image_count"] - 1
        print(f"  Ignoruje dodatkowe zdjecia kobiet: {ignored_count}")

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

def find_first_supported_image_path(folder_path):
    if not os.path.isdir(folder_path):
        return None

    images = list_supported_images(folder_path, sort_files=True)
    if not images:
        return None

    return os.path.join(folder_path, images[0])

def to_report_web_path(base_folder, target_path):
    if not target_path:
        return None
    return os.path.relpath(target_path, base_folder).replace(os.sep, '/')

def load_paired_result_records(results_folder):
    records = {}
    if not os.path.isdir(results_folder):
        return records

    for folder_name in sorted(os.listdir(results_folder)):
        folder_path = os.path.join(results_folder, folder_name)
        if not os.path.isdir(folder_path):
            continue

        metadata_path = os.path.join(folder_path, "metadata.json")
        if not os.path.isfile(metadata_path):
            continue

        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
        except Exception:
            continue

        pair_key = str(metadata.get("pair_key") or "").strip()
        source_variant = str(metadata.get("source_variant") or "").strip().lower()
        if not pair_key or source_variant not in {"flat", "model"}:
            continue

        records.setdefault(pair_key, {})[source_variant] = {
            "folder_name": folder_name,
            "folder_path": folder_path,
            "metadata_path": metadata_path,
            "metadata": metadata,
            "garment_image": find_first_supported_image_path(os.path.join(folder_path, "garment")),
            "result_image": find_first_supported_image_path(os.path.join(folder_path, "result")),
            "error_screenshot": find_first_supported_image_path(folder_path) if metadata.get("status") == "failed" else None,
        }

    return records

def render_comparison_image_card(title, image_path, web_path, status_label, fallback_text):
    safe_title = html_escape(title)
    safe_status = html_escape(status_label or "")
    if web_path:
        safe_href = html_escape(web_path, quote=True)
        return f"""
        <section class="image-card">
          <div class="image-card-header">
            <div>
              <span class="image-label">{safe_title}</span>
              <span class="status-pill">{safe_status}</span>
            </div>
            <a class="open-link" href="{safe_href}" target="_blank" rel="noreferrer">Open</a>
          </div>
          <a class="image-frame" href="{safe_href}" target="_blank" rel="noreferrer">
            <img src="{safe_href}" alt="{safe_title}" loading="lazy" decoding="async">
          </a>
        </section>
        """

    return f"""
    <section class="image-card missing">
      <div class="image-card-header">
        <div>
          <span class="image-label">{safe_title}</span>
          <span class="status-pill muted-pill">{safe_status}</span>
        </div>
      </div>
      <p class="missing-copy">{html_escape(fallback_text)}</p>
    </section>
    """

def build_flat_model_comparison_html(results_folder, summary, pair_rows):
    row_markup = []
    for row in pair_rows:
        model_variant = row["model_variant"]
        flat_variant = row["flat_variant"]
        garment_status = "Ready" if row["model_garment_web"] else "Missing"
        model_status = model_variant.get("status") or "missing"
        flat_status = flat_variant.get("status") or "missing"
        row_markup.append(f"""
        <article class="pair-row">
          <div class="pair-header">
            <div>
              <p class="pair-eyebrow">Pair {html_escape(row['pair_key'])}</p>
              <h2>Garment {html_escape(row['pair_key'])}</h2>
              <p class="pair-meta">
                Model garment: {html_escape(row.get('model_garment_name') or 'n/a')}
                | Model output: {html_escape(model_status)}
                | Flat output: {html_escape(flat_status)}
              </p>
            </div>
          </div>
          <div class="comparison-grid">
            {render_comparison_image_card("Clothes from model folder", row["model_garment_path"], row["model_garment_web"], garment_status, "Model garment image not found.")}
            {render_comparison_image_card("Output of the model photo", model_variant.get("result_image"), model_variant.get("result_web"), model_status, model_variant.get("fallback_text") or "Model generation not available.")}
            {render_comparison_image_card("Output of the flat photo", flat_variant.get("result_image"), flat_variant.get("result_web"), flat_status, flat_variant.get("fallback_text") or "Flat generation not available.")}
          </div>
        </article>
        """)

    unmatched_markup = ""
    if summary["flat_only_inputs"] or summary["model_only_inputs"]:
        flat_only_markup = ", ".join(html_escape(item) for item in summary["flat_only_inputs"]) or "None"
        model_only_markup = ", ".join(html_escape(item) for item in summary["model_only_inputs"]) or "None"
        unmatched_markup = f"""
        <section class="unmatched">
          <h2>Unmatched Inputs</h2>
          <p><strong>Flat only:</strong> {flat_only_markup}</p>
          <p><strong>Model only:</strong> {model_only_markup}</p>
        </section>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Flat vs Model Try-On Comparison</title>
  <style>
    :root {{
      --page: #f6f1e8;
      --panel: rgba(255, 251, 244, 0.96);
      --line: #d9c9b2;
      --ink: #221b14;
      --muted: #6f6456;
      --accent: #9c5a1a;
      --accent-soft: rgba(156, 90, 26, 0.10);
      --success: #245f45;
      --missing: #8f8475;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: "Georgia", "Times New Roman", serif;
      background:
        radial-gradient(circle at top left, rgba(156, 90, 26, 0.18), transparent 26%),
        linear-gradient(180deg, #fbf7f0 0%, var(--page) 100%);
    }}
    main {{
      max-width: 1600px;
      margin: 0 auto;
      padding: 32px 20px 44px;
    }}
    h1, h2, p {{ margin: 0; }}
    .hero {{
      display: grid;
      gap: 16px;
      margin-bottom: 24px;
    }}
    .hero h1 {{
      font-size: clamp(2.2rem, 4vw, 3.8rem);
      letter-spacing: 0.02em;
    }}
    .hero p {{
      max-width: 920px;
      color: var(--muted);
      line-height: 1.6;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .summary-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 16px 18px;
      box-shadow: 0 14px 28px rgba(48, 33, 15, 0.06);
    }}
    .summary-card strong {{
      display: block;
      font-size: 1.8rem;
      margin-bottom: 4px;
    }}
    .summary-card span {{
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .rows {{
      display: grid;
      gap: 18px;
    }}
    .pair-row {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 28px;
      padding: 22px;
      box-shadow: 0 18px 36px rgba(48, 33, 15, 0.08);
    }}
    .pair-header {{
      margin-bottom: 16px;
    }}
    .pair-eyebrow {{
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.8rem;
      margin-bottom: 6px;
    }}
    .pair-header h2 {{
      font-size: 1.55rem;
      margin-bottom: 6px;
    }}
    .pair-meta {{
      color: var(--muted);
      line-height: 1.5;
    }}
    .comparison-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }}
    .image-card {{
      border: 1px solid var(--line);
      border-radius: 20px;
      background: white;
      padding: 12px;
      min-height: 100%;
    }}
    .image-card.missing {{
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: start;
      background: linear-gradient(180deg, #fffdf9 0%, #f6efe5 100%);
    }}
    .image-card-header {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
      margin-bottom: 10px;
    }}
    .image-label {{
      display: block;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.78rem;
      margin-bottom: 6px;
    }}
    .status-pill {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      padding: 6px 10px;
      font-size: 0.85rem;
      line-height: 1;
    }}
    .muted-pill {{
      background: rgba(111, 100, 86, 0.14);
      color: var(--missing);
    }}
    .open-link {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 6px 10px;
      color: var(--accent);
      text-decoration: none;
      font-size: 0.85rem;
      line-height: 1;
    }}
    .image-frame {{
      display: block;
      text-decoration: none;
    }}
    .image-frame img {{
      width: 100%;
      height: 420px;
      object-fit: contain;
      border-radius: 14px;
      background: linear-gradient(180deg, #fffaf3 0%, #f1e7d9 100%);
    }}
    .missing-copy {{
      color: var(--muted);
      line-height: 1.5;
    }}
    .unmatched {{
      margin-top: 20px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 18px 20px;
    }}
    .unmatched h2 {{
      font-size: 1.2rem;
      margin-bottom: 10px;
    }}
    .unmatched p {{
      color: var(--muted);
      line-height: 1.5;
    }}
    .footer {{
      margin-top: 22px;
      color: var(--muted);
      line-height: 1.5;
    }}
    @media (max-width: 960px) {{
      .comparison-grid {{
        grid-template-columns: 1fr;
      }}
      .image-frame img {{
        height: 340px;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div>
        <h1>Flat vs Model Try-On Comparison</h1>
        <p>
          Each row matches the same numbered garment across both source folders.
          The first pass used the flat garment image with the Flat toggle enabled.
          The second pass used the model garment image with the Flat toggle disabled.
        </p>
      </div>
    </section>

    <section class="summary-grid">
      <div class="summary-card"><strong>{summary['total_pairs']}</strong><span>Matched garment pairs</span></div>
      <div class="summary-card"><strong>{summary['flat_successful']}</strong><span>Flat generations saved</span></div>
      <div class="summary-card"><strong>{summary['model_successful']}</strong><span>Model generations saved</span></div>
      <div class="summary-card"><strong>{summary['pairs_with_both_results']}</strong><span>Pairs with both outputs</span></div>
      <div class="summary-card"><strong>{summary['failed_jobs']}</strong><span>Failed jobs</span></div>
      <div class="summary-card"><strong>{html_escape(summary['woman_photo'])}</strong><span>Woman photo used</span></div>
    </section>

    <section class="rows">
      {''.join(row_markup)}
    </section>

    {unmatched_markup}

    <p class="footer">
      Report folder: <code>{html_escape(results_folder)}</code><br>
      Site mode: <code>{html_escape(summary['site_mode'])}</code> | Generated: <code>{html_escape(summary['generated_at'])}</code>
    </p>
  </main>
</body>
</html>"""

def write_flat_model_report(results_folder, person_info, pairs, flat_only, model_only, success, failed, elapsed_total):
    records = load_paired_result_records(results_folder)
    pair_rows = []
    flat_successful = 0
    model_successful = 0
    pairs_with_both_results = 0

    for pair_info in pairs:
        pair_key = pair_info["pair_key"]
        pair_record = records.get(pair_key, {})
        flat_variant = pair_record.get("flat")
        model_variant = pair_record.get("model")

        flat_status = flat_variant["metadata"].get("status") if flat_variant else "missing"
        model_status = model_variant["metadata"].get("status") if model_variant else "missing"
        if flat_status == "success":
            flat_successful += 1
        if model_status == "success":
            model_successful += 1
        if flat_status == "success" and model_status == "success":
            pairs_with_both_results += 1

        pair_rows.append({
            "pair_key": pair_key,
            "model_garment_name": pair_info["model_name"],
            "model_garment_path": model_variant.get("garment_image") if model_variant else None,
            "model_garment_web": to_report_web_path(results_folder, model_variant.get("garment_image")) if model_variant and model_variant.get("garment_image") else None,
            "model_variant": {
                "status": model_status,
                "result_image": model_variant.get("result_image") if model_variant else None,
                "result_web": to_report_web_path(results_folder, model_variant.get("result_image")) if model_variant and model_variant.get("result_image") else None,
                "fallback_text": model_variant["metadata"].get("error") if model_variant else "Model variant metadata not found.",
            },
            "flat_variant": {
                "status": flat_status,
                "result_image": flat_variant.get("result_image") if flat_variant else None,
                "result_web": to_report_web_path(results_folder, flat_variant.get("result_image")) if flat_variant and flat_variant.get("result_image") else None,
                "fallback_text": flat_variant["metadata"].get("error") if flat_variant else "Flat variant metadata not found.",
            },
        })

    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "woman_photo": person_info["person_name"],
        "woman_photo_count": person_info["person_image_count"],
        "site_mode": PAIRED_RUN_CONFIG["site_mode"],
        "flat_source_folder": FLAT_GARMENTS_FOLDER,
        "model_source_folder": MODEL_GARMENTS_FOLDER,
        "results_folder": results_folder,
        "report_path": PAIRED_REPORT_PATH,
        "total_pairs": len(pairs),
        "total_jobs": len(pairs) * 2,
        "successful_jobs": success,
        "failed_jobs": failed,
        "duration_seconds": int(elapsed_total),
        "flat_successful": flat_successful,
        "model_successful": model_successful,
        "pairs_with_both_results": pairs_with_both_results,
        "flat_only_inputs": list(flat_only),
        "model_only_inputs": list(model_only),
    }

    with open(os.path.join(results_folder, "summary.json"), 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)

    html = build_flat_model_comparison_html(results_folder, summary, pair_rows)
    with open(PAIRED_REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)

    return summary

def run_flat_model_suite():
    print(f"\n{'='*60}")
    print("RUN: FLAT THEN MODEL")
    print(f"{'='*60}")

    results_folder = PAIRED_RUN_CONFIG["results_folder"]
    os.makedirs(results_folder, exist_ok=True)

    person_info = get_primary_woman_model()
    pairs, flat_only, model_only = collect_flat_model_pairs()

    print(f"  Wyniki: {results_folder}")
    print(f"  Woman photo: {person_info['person_name']}")
    if person_info["person_image_count"] > 1:
        print(f"  Ignoruje dodatkowe zdjecia kobiet: {person_info['person_image_count'] - 1}")
    print(f"  Matched pairs: {len(pairs)}")
    if flat_only:
        print(f"  WARN Bez pary w model/: {', '.join(flat_only)}")
    if model_only:
        print(f"  WARN Bez pary w flat/: {', '.join(model_only)}")

    if not pairs:
        summary = write_flat_model_report(results_folder, person_info, [], flat_only, model_only, 0, 0, 0)
        print(f"  Brak sparowanych obrazow do uruchomienia")
        print(f"  HTML zapisany w: {PAIRED_REPORT_PATH}")
        return summary

    flat_jobs = [build_paired_tryon_job(person_info, pair_info, "flat", len(pairs)) for pair_info in pairs]
    model_jobs = [build_paired_tryon_job(person_info, pair_info, "model", len(pairs)) for pair_info in pairs]
    all_jobs = flat_jobs + model_jobs

    print(f"  Flat jobs first: {len(flat_jobs)}")
    print(f"  Model jobs second: {len(model_jobs)}")

    success = 0
    failed = 0
    start_time = time.time()

    for i, model in enumerate(all_jobs, 1):
        if test_single_model(i, model, PAIRED_RUN_CONFIG):
            success += 1
        else:
            failed += 1

        if i < len(all_jobs):
            time.sleep(2)

        elapsed = time.time() - start_time
        avg_per_test = elapsed / i
        remaining = (len(all_jobs) - i) * avg_per_test
        print(f"  Progress: {i}/{len(all_jobs)} | ETA: {int(remaining/60)}min")

    elapsed_total = time.time() - start_time
    summary = write_flat_model_report(results_folder, person_info, pairs, flat_only, model_only, success, failed, elapsed_total)

    print(f"\n{'='*60}")
    print("PODSUMOWANIE FLAT VS MODEL")
    print(f"{'='*60}")
    print(f"Sukces: {success}/{len(all_jobs)}")
    print(f"Bledy: {failed}/{len(all_jobs)}")
    print(f"Pary z dwoma wynikami: {summary['pairs_with_both_results']}/{summary['total_pairs']}")
    print(f"HTML zapisany w: {PAIRED_REPORT_PATH}")

    return summary

if __name__ == "__main__":
    print("SIZ3R BUSINESS TESTS - FLAT VS MODEL")
    print(f"Headless mode: {HEADLESS}")
    print(f"Pairing mode: {PAIRING_MODE}")
    if PAIRING_MODE != 'random':
        print(f"Pairing seed: {PAIRING_SEED}")

    required_paths = {
        "women_people": PEOPLE_FOLDERS["women"],
        "flat_garments": FLAT_GARMENTS_FOLDER,
        "model_garments": MODEL_GARMENTS_FOLDER,
    }

    missing = [(key, value) for key, value in required_paths.items() if not os.path.exists(value)]
    if missing:
        print("Brakuje wymaganych folderow:")
        for key, value in missing:
            print(f"  {key}: {value}")
        sys.exit(1)

    print("Folder counts:")
    for label, path in required_paths.items():
        count = len(list_supported_images(path))
        print(f"  {label}: {count} zdjec")

    with open(RUN_SUMMARY_PATH, 'w') as f:
        json.dump(run_flat_model_suite(), f, indent=2)

    print(f"\nCombined summary zapisane w: {RUN_SUMMARY_PATH}")
    with open(RUN_SUMMARY_PATH, 'r', encoding='utf-8') as f:
        run_summary = json.load(f)

    all_completed_runs_clean = (
        run_summary.get("total_jobs", 0) > 0 and
        run_summary.get("failed_jobs", 0) == 0
    )
    sys.exit(0 if all_completed_runs_clean else 1)
