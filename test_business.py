from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
import time, random, string, os, sys, shutil, base64, json, traceback, hashlib, re, unicodedata
from pathlib import Path

GRID_URL = os.getenv('SELENIUM_GRID_URL', 'http://localhost:4444')
PREFIX = "biztest_"
HEADLESS = os.getenv('HEADLESS', 'false').lower() == 'true'
PAIRING_MODE = os.getenv('TEST_PAIRING_MODE', 'all').strip().lower()
PAIRING_SEED = os.getenv('TEST_PAIRING_SEED', 'stable-v1').strip() or 'stable-v1'
FAIL_ON_TEST_FAILURES = os.getenv('FAIL_ON_TEST_FAILURES', 'true').lower() == 'true'
GARMENTS_PER_PERSON_RAW = os.getenv('TEST_GARMENTS_PER_PERSON', '').strip()
TEST_RUN_KEYS_RAW = os.getenv('TEST_RUN_KEYS', '').strip()
GENERATION_PROFILE = os.getenv('TEST_GENERATION_PROFILE', 'default').strip().lower() or 'default'
REUSE_BROWSER_SESSION = os.getenv('TEST_REUSE_BROWSER_SESSION', 'true').strip().lower() in ('1', 'true', 'yes', 'on')
GENERATION_RESULT_TIMEOUT = int(os.getenv('TEST_GENERATION_RESULT_TIMEOUT', '60').strip() or '60')
GENERATION_ACTIVE_GRACE_TIMEOUT = int(os.getenv('TEST_GENERATION_ACTIVE_GRACE_TIMEOUT', '45').strip() or '45')
GENERATION_RETRY_COUNT = max(0, int(os.getenv('TEST_GENERATION_RETRY_COUNT', '1').strip() or '1'))
SHARED_TEST_ACCOUNT_EMAIL = "massTest@gmail.com"
SHARED_TEST_ACCOUNT_PASSWORD = "massTest@gmail.com"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_PATH = os.path.join(SCRIPT_DIR, 'test_images')
BUTTON_CANDIDATE_SELECTOR = "button, [role='button'], input[type='button'], input[type='submit'], [class*='button'], [class*='Button']"
GENERATE_BUTTON_TEXTS = ['generuj', 'generate', 'try on', 'try-on', 'tryon']
REGISTER_BUTTON_TEXTS = ['zarejestruj', 'register', 'sign up']
LOGIN_BUTTON_TEXTS = ['zaloguj', 'login', 'log in', 'sign in']
CREDIT_MODAL_SKIP_TEXTS = ['nie dziękuję', 'nie dziekuje', 'no thank', 'no thanks']

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
ADVANCED_GENERATION_PROFILE = 'advanced_segmentation_free_30'
ALLOWED_GENERATION_PROFILES = {'default', ADVANCED_GENERATION_PROFILE}
ONE_MODEL_PER_GARMENT_MODE = 'one_model_per_garment'
ALLOWED_PAIRING_MODES = {'all', 'deterministic', 'random', ONE_MODEL_PER_GARMENT_MODE}

if PAIRING_MODE not in ALLOWED_PAIRING_MODES:
    allowed_modes = ', '.join(sorted(ALLOWED_PAIRING_MODES))
    raise ValueError(
        f"TEST_PAIRING_MODE must be one of: {allowed_modes}. Got: {PAIRING_MODE}"
    )

if GENERATION_PROFILE not in ALLOWED_GENERATION_PROFILES:
    allowed_profiles = ', '.join(sorted(ALLOWED_GENERATION_PROFILES))
    raise ValueError(
        f"TEST_GENERATION_PROFILE must be one of: {allowed_profiles}. Got: {GENERATION_PROFILE}"
    )

def parse_optional_positive_int(value, variable_name):
    if not value:
        return None

    try:
        parsed_value = int(value)
    except ValueError as exc:
        raise ValueError(f"{variable_name} must be a positive integer, got: {value}") from exc

    if parsed_value <= 0:
        raise ValueError(f"{variable_name} must be a positive integer, got: {value}")

    return parsed_value

def parse_optional_choice_list(value, variable_name, allowed_values):
    if not value:
        return None

    allowed_lookup = {item.lower(): item.lower() for item in allowed_values}
    selected_values = []
    seen = set()

    for raw_value in value.split(','):
        normalized_value = raw_value.strip().lower()
        if not normalized_value:
            continue

        if normalized_value not in allowed_lookup:
            allowed_text = ', '.join(sorted(allowed_lookup))
            raise ValueError(f"{variable_name} must contain only: {allowed_text}. Got: {value}")

        if normalized_value not in seen:
            selected_values.append(normalized_value)
            seen.add(normalized_value)

    return selected_values or None

GARMENTS_PER_PERSON = parse_optional_positive_int(GARMENTS_PER_PERSON_RAW, 'TEST_GARMENTS_PER_PERSON')
SELECTED_RUN_KEYS = parse_optional_choice_list(
    TEST_RUN_KEYS_RAW,
    'TEST_RUN_KEYS',
    [run_config["key"] for run_config in GARMENT_RUNS],
)
PAIRING_SEED_ACTIVE = PAIRING_MODE in ('deterministic', ONE_MODEL_PER_GARMENT_MODE) or (
    GARMENTS_PER_PERSON is not None and PAIRING_MODE != 'random'
)

# Account creation is intentionally disabled for large shared test runs.
# def generate_user():
#     uid = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
#     return {"email": f"{PREFIX}{uid}@test.com", "password": "TestPass123!"}

def get_test_account():
    return {
        "email": SHARED_TEST_ACCOUNT_EMAIL,
        "password": SHARED_TEST_ACCOUNT_PASSWORD,
    }

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

def wait_for_registration_form(driver, timeout=20):
    def registration_form_ready(current):
        email_inputs = current.find_elements(By.CSS_SELECTOR, "input[type='email']")
        password_inputs = current.find_elements(By.CSS_SELECTOR, "input[type='password']")
        if not email_inputs or len(password_inputs) < 2:
            return False
        return {
            "email_input": email_inputs[0],
            "password_inputs": password_inputs,
        }

    return WebDriverWait(driver, timeout, poll_frequency=0.25).until(registration_form_ready)

def wait_for_post_registration_state(driver, timeout=7):
    def registration_progressed(current):
        current_url = ''
        try:
            current_url = current.current_url or ''
        except Exception:
            current_url = ''

        if '/business/register' not in current_url:
            return True

        skip_button = find_button_safe(current, CREDIT_MODAL_SKIP_TEXTS)
        if skip_button and is_button_interactable(skip_button):
            return True

        email_inputs = current.find_elements(By.CSS_SELECTOR, "input[type='email']")
        password_inputs = current.find_elements(By.CSS_SELECTOR, "input[type='password']")
        if not email_inputs and len(password_inputs) < 2:
            return True

        return False

    return WebDriverWait(driver, timeout, poll_frequency=0.25).until(registration_progressed)

def wait_for_auth_form(driver, minimum_password_inputs=1, timeout=20):
    def auth_form_ready(current):
        email_inputs = current.find_elements(By.CSS_SELECTOR, "input[type='email']")
        password_inputs = current.find_elements(By.CSS_SELECTOR, "input[type='password']")
        if not email_inputs or len(password_inputs) < minimum_password_inputs:
            return False
        return {
            "email_input": email_inputs[0],
            "password_inputs": password_inputs,
        }

    return WebDriverWait(driver, timeout, poll_frequency=0.25).until(auth_form_ready)

def wait_for_post_auth_state(driver, auth_path, minimum_password_inputs=1, timeout=7):
    def auth_progressed(current):
        current_url = ''
        try:
            current_url = current.current_url or ''
        except Exception:
            current_url = ''

        if auth_path not in current_url:
            return True

        skip_button = find_button_safe(current, CREDIT_MODAL_SKIP_TEXTS)
        if skip_button and is_button_interactable(skip_button):
            return True

        email_inputs = current.find_elements(By.CSS_SELECTOR, "input[type='email']")
        password_inputs = current.find_elements(By.CSS_SELECTOR, "input[type='password']")
        if not email_inputs and len(password_inputs) < minimum_password_inputs:
            return True

        return False

    return WebDriverWait(driver, timeout, poll_frequency=0.25).until(auth_progressed)

def wait_for_file_inputs(driver, minimum_count=2, timeout=20):
    def file_inputs_ready(current):
        inputs = current.find_elements(By.CSS_SELECTOR, "input[type='file']")
        return inputs if len(inputs) >= minimum_count else False

    return WebDriverWait(driver, timeout, poll_frequency=0.25).until(file_inputs_ready)

def wait_for_generation_surface(driver, timeout=4):
    def generation_surface_ready(current):
        option_state = read_generation_option_state(current)
        if option_state and any(
            option_state.get(key) for key in [
                "standard_found",
                "premium_found",
                "turbo_found",
                "upper_found",
                "lower_found",
                "full_found",
            ]
        ):
            return option_state

        button = find_button_safe(current, GENERATE_BUTTON_TEXTS)
        return button or False

    return WebDriverWait(driver, timeout, poll_frequency=0.25).until(generation_surface_ready)

def wait_for_image_render_complete(driver, image_element, timeout=2):
    def image_ready(current):
        try:
            return current.execute_script("""
            const img = arguments[0];
            if (!img) return false;
            return Boolean(img.complete && img.naturalWidth > 0 && img.naturalHeight > 0);
            """, image_element)
        except (StaleElementReferenceException, NoSuchElementException):
            return False

    return WebDriverWait(driver, timeout, poll_frequency=0.2).until(image_ready)

def wait_for_element_to_disappear(driver, element, timeout=3):
    def element_gone(_):
        try:
            return not element.is_displayed()
        except (StaleElementReferenceException, NoSuchElementException):
            return True

    return WebDriverWait(driver, timeout, poll_frequency=0.2).until(element_gone)

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

def get_preselected_garments_for_person(garment_images, gender, person_name):
    if not garment_images:
        return []

    if GARMENTS_PER_PERSON is None:
        if PAIRING_MODE == 'all':
            return {
                "mode": "all",
                "seed": None,
                "garments": list(enumerate(garment_images)),
            }
        return None

    garment_count = min(GARMENTS_PER_PERSON, len(garment_images))
    if garment_count == len(garment_images):
        return {
            "mode": "all",
            "seed": None,
            "garments": list(enumerate(garment_images)),
        }

    if PAIRING_MODE == 'random':
        selected_indexes = sorted(random.sample(range(len(garment_images)), garment_count))
        selection_mode = "sample-random"
        selection_seed = None
    else:
        selection_seed = f"{PAIRING_SEED}|{gender}|{person_name}|sample"
        rng = random.Random(selection_seed)
        selected_indexes = sorted(rng.sample(range(len(garment_images)), garment_count))
        selection_mode = "sample-deterministic"

    return {
        "mode": selection_mode,
        "seed": selection_seed,
        "garments": [
            (index, garment_images[index])
            for index in selected_indexes
        ],
    }

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

def clear_file_input(driver, input_element):
    driver.execute_script("""
    const input = arguments[0];
    try {
        input.value = '';
    } catch (error) {
        // Ignore direct assignment failures and still emit change notifications.
    }
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    """, input_element)

def is_generation_still_running(driver):
    try:
        generation_state = driver.execute_script("""
        const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' &&
                style.visibility !== 'hidden' &&
                parseFloat(style.opacity || '1') > 0 &&
                rect.width > 0 &&
                rect.height > 0;
        };

        const buttonCandidates = Array.from(document.querySelectorAll(
            "button, [role='button'], input[type='button'], input[type='submit']"
        ));
        const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
        const generateTexts = ['generuj', 'generate', 'try on', 'try-on', 'tryon'];
        const generateButton = buttonCandidates.find((el) => {
            const text = normalize(el.innerText || el.textContent || el.value);
            if (!isVisible(el)) return false;
            return generateTexts.some((candidate) => text.includes(candidate));
        });

        const generateDisabled = Boolean(generateButton) && (
            generateButton.disabled ||
            generateButton.getAttribute('aria-disabled') === 'true'
        );

        const spinnerSelectors = [
            "[role='progressbar']",
            ".spinner",
            ".loading",
            ".loader",
            "[class*='spinner']",
            "[class*='loading']",
            "[class*='loader']",
            "svg.animate-spin",
        ];
        const spinnerVisible = spinnerSelectors.some((selector) =>
            Array.from(document.querySelectorAll(selector)).some(isVisible)
        );

        return {
            generateDisabled,
            spinnerVisible,
        };
        """)
    except Exception:
        return False

    if not isinstance(generation_state, dict):
        return False

    return bool(generation_state.get("generateDisabled") or generation_state.get("spinnerVisible"))

def wait_for_generated_result(driver, result_image_present):
    try:
        return WebDriverWait(driver, GENERATION_RESULT_TIMEOUT).until(result_image_present)
    except TimeoutException:
        if not is_generation_still_running(driver):
            raise

        print(f"  WARN Generacja trwa dluzej niz {GENERATION_RESULT_TIMEOUT}s, czekam dodatkowe {GENERATION_ACTIVE_GRACE_TIMEOUT}s...")
        return WebDriverWait(driver, GENERATION_ACTIVE_GRACE_TIMEOUT).until(result_image_present)

def get_result_column_images(driver):
    generate_btn = find_button_safe(driver, GENERATE_BUTTON_TEXTS)
    if not generate_btn:
        return []

    try:
        return driver.execute_script("""
        const button = arguments[0];
        const canonical = (value) => String(value || '')
            .replace(/[_-]+/g, ' ')
            .replace(/\\s+/g, ' ')
            .trim()
            .toLowerCase();
        const isVisible = (element) => {
            if (!element) return false;
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' &&
                rect.width > 0 && rect.height > 0;
        };
        const visibleImages = (root) => Array.from(root.querySelectorAll('img'))
            .filter(isVisible);
        const buttonRect = button.getBoundingClientRect();
        const imagesInButtonColumn = (root) => visibleImages(root).filter((image) => {
            const rect = image.getBoundingClientRect();
            const overlap = Math.max(0, Math.min(rect.right, buttonRect.right) -
                Math.max(rect.left, buttonRect.left));
            const verticalGap = buttonRect.top - rect.bottom;
            return overlap >= Math.min(rect.width, buttonRect.width) * 0.5 &&
                verticalGap >= -20 && verticalGap <= 120;
        });

        const resultLabels = Array.from(document.querySelectorAll(
            "h1, h2, h3, h4, h5, h6, [role='heading'], div, span, p"
        )).filter((element) =>
            isVisible(element) && ['result', 'wynik'].includes(
                canonical(element.innerText || element.textContent)
            )
        );

        let container = button.parentElement;
        while (container && container !== document.body) {
            if (resultLabels.some((label) => container.contains(label))) {
                return imagesInButtonColumn(container);
            }
            container = container.parentElement;
        }

        // Fallback for markup without a Result heading: the output is directly
        // above the Tryon button and horizontally overlaps its column.
        return imagesInButtonColumn(document);
        """, generate_btn) or []
    except Exception:
        return []

def get_result_image_sources(driver):
    sources = set()
    for img in get_result_column_images(driver):
        try:
            if not img.is_displayed():
                continue

            src = img.get_attribute('currentSrc') or img.get_attribute('src') or ''
            if src:
                sources.add(src)
        except (StaleElementReferenceException, NoSuchElementException):
            continue
    return sources

def find_new_generated_image(driver, baseline_sources):
    for img in get_result_column_images(driver):
        try:
            if not img.is_displayed():
                continue

            src = img.get_attribute('currentSrc') or img.get_attribute('src') or ''
            if not src or src in baseline_sources:
                continue

            rect = img.rect
            width = rect.get('width', 0)
            height = rect.get('height', 0)
            if width >= 150 and height >= 150:
                return img
        except (StaleElementReferenceException, NoSuchElementException):
            continue
    return False

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

        if PAIRING_MODE == ONE_MODEL_PER_GARMENT_MODE:
            assignment_basis = f"{PAIRING_SEED}|{gender}|one-model-per-garment"
            assignment_digest = hashlib.sha256(assignment_basis.encode('utf-8')).hexdigest()
            person_offset = int(assignment_digest[:8], 16) % len(people_images)

            for garment_index, garment_name in enumerate(garment_images):
                person_name = people_images[(garment_index + person_offset) % len(people_images)]
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
                    "preselected_garment_mode": ONE_MODEL_PER_GARMENT_MODE,
                    "preselected_garment_seed": PAIRING_SEED,
                })
            continue

        for person_name in people_images:
            preselected_garments = get_preselected_garments_for_person(garment_images, gender, person_name)
            if preselected_garments:
                for garment_index, garment_name in preselected_garments["garments"]:
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
                        "preselected_garment_mode": preselected_garments["mode"],
                        "preselected_garment_seed": preselected_garments["seed"],
                    })
                continue

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
            "mode": model_info.get("preselected_garment_mode", "all"),
            "seed": model_info.get("preselected_garment_seed"),
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
    # An element screenshot is limited to the image's rendered CSS size. The
    # Advanced panel uses a small preview, so saving that screenshot turns a
    # full-resolution result into a low-resolution PNG. Draw the decoded image
    # at its intrinsic dimensions first and keep the screenshot only as a
    # fallback for sources that cannot be read through a canvas (for example,
    # a cross-origin image without CORS headers).
    try:
        image_data = driver.execute_script("""
        const img = arguments[0];
        if (!img.complete || img.naturalWidth <= 0 || img.naturalHeight <= 0) {
            throw new Error('Result image has not finished loading');
        }

        const canvas = document.createElement('canvas');
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        const context = canvas.getContext('2d');
        if (!context) {
            throw new Error('Could not create a canvas context');
        }

        context.drawImage(img, 0, 0, img.naturalWidth, img.naturalHeight);
        return {
            data_url: canvas.toDataURL('image/png'),
            width: img.naturalWidth,
            height: img.naturalHeight,
        };
        """, img_element)

        data_url = image_data.get('data_url', '') if isinstance(image_data, dict) else ''
        if not data_url.startswith('data:image/png;base64,'):
            raise ValueError("Browser did not return a PNG data URL")

        encoded_data = data_url.split(',', 1)[1]
        decoded_data = base64.b64decode(encoded_data, validate=True)
        if not decoded_data:
            raise ValueError("Browser returned an empty result image")

        with open(filepath, 'wb') as f:
            f.write(decoded_data)

        print(
            f"  Rozdzielczosc wyniku: "
            f"{image_data.get('width')}x{image_data.get('height')}"
        )
        return True
    except Exception:
        try:
            img_element.screenshot(filepath)
            print("  WARN Zapisano zrzut podgladu zamiast obrazu w pelnej rozdzielczosci")
            return True
        except Exception:
            return False

def ensure_advanced_generation_settings(driver, target_steps=30):
    """Enable Advanced, segmentation_free, and the requested steps value."""
    last_state = None

    # React replaces the Joy Slider input after each value change, so every
    # iteration must reacquire the live element before sending another key.
    for _ in range(60):
        state = driver.execute_script("""
        const targetSteps = Number(arguments[0]);
        const canonical = (value) => String(value || '')
            .replace(/[_-]+/g, ' ')
            .replace(/\\s+/g, ' ')
            .trim()
            .toLowerCase();

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

        const findAnchors = (label) => Array.from(document.querySelectorAll(
            "button, label, input, [role='button'], [role='tab'], [role='radio'], " +
            "[role='checkbox'], [role='switch'], div, span, p"
        )).filter((el) => {
            if (!isVisible(el)) return false;
            return canonical(el.innerText || el.textContent) === label ||
                canonical(el.getAttribute && el.getAttribute('aria-label')) === label ||
                canonical(el.getAttribute && el.getAttribute('title')) === label ||
                canonical(el.getAttribute && el.getAttribute('name')) === label;
        });

        const readState = (root) => {
            if (!root) return null;
            const nodes = unique([
                root,
                ...(root.querySelectorAll ? root.querySelectorAll(
                    "input[type='radio'], input[type='checkbox'], [role='tab'], [role='radio'], " +
                    "[role='checkbox'], [role='switch'], [aria-selected], [aria-checked], " +
                    "[aria-pressed], [data-state]"
                ) : []),
            ]);

            for (const node of nodes) {
                if (node.matches && node.matches("input[type='radio'], input[type='checkbox']")) {
                    return { selected: Boolean(node.checked), source: 'input.checked' };
                }

                for (const attribute of ['aria-selected', 'aria-checked', 'aria-pressed']) {
                    const value = canonical(node.getAttribute && node.getAttribute(attribute));
                    if (value === 'true' || value === 'false') {
                        return { selected: value === 'true', source: attribute };
                    }
                }

                const dataState = canonical(node.getAttribute && node.getAttribute('data-state'));
                if (['checked', 'on', 'active', 'selected'].includes(dataState)) {
                    return { selected: true, source: 'data-state' };
                }
                if (['unchecked', 'off', 'inactive'].includes(dataState)) {
                    return { selected: false, source: 'data-state' };
                }

                const rawClassName = typeof node.className === 'string' ? node.className : '';
                const classTokens = rawClassName.toLowerCase().split(/\\s+/).filter(Boolean);
                if (classTokens.some((token) =>
                    ['selected', 'active', 'checked', 'current'].includes(token) ||
                    token.endsWith('-selected') || token.endsWith('-checked')
                )) {
                    return { selected: true, source: 'class' };
                }
            }
            return null;
        };

        const controlsForAnchor = (anchor, label) => {
            const closestLabel = anchor.closest && anchor.closest('label');
            const labelledByFor = anchor.matches && anchor.matches('label') && anchor.htmlFor
                ? document.getElementById(anchor.htmlFor)
                : null;
            const labelledById = anchor.id
                ? document.querySelector(`[aria-labelledby~="${CSS.escape(anchor.id)}"]`)
                : null;
            const exactContainers = [];
            let container = anchor.parentElement;
            for (let depth = 0; container && depth < 4; depth += 1) {
                if (canonical(container.innerText || container.textContent) === label) {
                    exactContainers.push(container);
                    container = container.parentElement;
                    continue;
                }
                break;
            }
            const exactContainerControls = exactContainers.flatMap((item) => Array.from(
                item.querySelectorAll(
                    "input[type='radio'], input[type='checkbox'], [role='tab'], [role='radio'], " +
                    "[role='checkbox'], [role='switch'], button"
                )
            ));
            return unique([
                anchor.control,
                closestLabel && closestLabel.control,
                labelledByFor,
                labelledById,
                anchor.matches && anchor.matches("input[type='radio'], input[type='checkbox']") ? anchor : null,
                anchor.querySelector && anchor.querySelector("input[type='radio'], input[type='checkbox']"),
                closestLabel && closestLabel.querySelector("input[type='radio'], input[type='checkbox']"),
                anchor.closest && anchor.closest("[role='tab'], [role='radio'], [role='checkbox'], [role='switch']"),
                anchor.closest && anchor.closest('button'),
                closestLabel,
                ...exactContainerControls,
                anchor,
            ]);
        };

        const scanToggle = (label) => {
            const anchors = findAnchors(label);
            let fallbackControl = null;
            for (const anchor of anchors) {
                for (const control of controlsForAnchor(anchor, label)) {
                    fallbackControl = fallbackControl || control;
                    const current = readState(control);
                    if (current) {
                        return {
                            found: true,
                            selected: current.selected,
                            source: current.source,
                            control,
                        };
                    }
                }
            }
            return {
                found: anchors.length > 0,
                selected: null,
                source: null,
                control: fallbackControl,
            };
        };

        const clickControl = (entry) => {
            if (!entry || !entry.control) return false;
            try {
                entry.control.scrollIntoView({ block: 'center', inline: 'center' });
                entry.control.click();
                return true;
            } catch (error) {
                return false;
            }
        };

        const advancedPanelVisible = Array.from(document.querySelectorAll('h1, h2, h3, h4, div, span, p'))
            .some((el) => isVisible(el) && canonical(el.innerText || el.textContent) === 'advanced mode');
        const advanced = scanToggle('advanced');

        if (!advanced.found || !advanced.control) {
            return { ready: false, error: 'Advanced control was not found' };
        }
        if (advanced.selected === null) {
            return { ready: false, error: 'Advanced checkbox state could not be read' };
        }
        if (advanced.selected === false) {
            if (!clickControl(advanced)) {
                return { ready: false, error: 'Advanced control could not be clicked' };
            }
            return { ready: false, changed: 'advanced' };
        }
        if (!advancedPanelVisible) {
            return { ready: false, changed: 'waiting-for-advanced-panel' };
        }

        const segmentation = scanToggle('segmentation free');
        if (!segmentation.found || !segmentation.control) {
            return { ready: false, error: 'segmentation_free control was not found' };
        }
        if (segmentation.selected !== true) {
            if (!clickControl(segmentation)) {
                return { ready: false, error: 'segmentation_free control could not be clicked' };
            }
            return { ready: false, changed: 'segmentation_free' };
        }

        const stepAnchors = findAnchors('steps');
        const sliders = unique(Array.from(document.querySelectorAll("input[type='range'], [role='slider']")));
        let bestSlider = null;
        let bestScore = Number.POSITIVE_INFINITY;

        for (const anchor of stepAnchors) {
            for (const slider of sliders) {
                let container = anchor;
                let depth = 0;
                let sharedDepth = null;
                while (container && depth <= 8) {
                    if (container.contains(slider)) {
                        sharedDepth = depth;
                        break;
                    }
                    container = container.parentElement;
                    depth += 1;
                }

                const anchorRect = anchor.getBoundingClientRect();
                const sliderRect = slider.getBoundingClientRect();
                const verticalDistance = Math.abs(
                    (anchorRect.top + anchorRect.height / 2) - (sliderRect.top + sliderRect.height / 2)
                );
                const score = (sharedDepth === null ? 10000 : sharedDepth * 100) + verticalDistance;
                if (score < bestScore) {
                    bestScore = score;
                    bestSlider = slider;
                }
            }
        }

        if (!bestSlider) {
            return { ready: false, error: 'steps slider was not found' };
        }

        const valueAttribute = bestSlider.matches("input[type='range']") ? 'value' : 'aria-valuenow';
        const currentSteps = Number(
            bestSlider.matches("input[type='range']")
                ? bestSlider.value
                : bestSlider.getAttribute(valueAttribute)
        );

        if (currentSteps !== targetSteps) {
            const minimum = Number(
                bestSlider.matches("input[type='range']")
                    ? (bestSlider.min || 0)
                    : (bestSlider.getAttribute('aria-valuemin') || 0)
            );
            const maximum = Number(
                bestSlider.matches("input[type='range']")
                    ? (bestSlider.max || 100)
                    : (bestSlider.getAttribute('aria-valuemax') || 100)
            );
            if (targetSteps < minimum || targetSteps > maximum) {
                return {
                    ready: false,
                    error: `steps value ${targetSteps} is outside slider range ${minimum}-${maximum}`,
                };
            }

            return {
                ready: false,
                changed: 'steps-keyboard',
                steps_element: bestSlider,
                steps_current: currentSteps,
                steps_direction: currentSteps < targetSteps ? 'right' : 'left',
            };
        }

        return {
            ready: true,
            advanced_enabled: true,
            advanced_state_source: advanced.source,
            segmentation_free_enabled: true,
            segmentation_free_state_source: segmentation.source,
            steps_selected: currentSteps,
        };
        """, target_steps)

        last_state = state
        if not isinstance(state, dict):
            raise Exception("Nie udalo sie odczytac ustawien Advanced")
        if state.get("error"):
            raise Exception(state["error"])
        if state.get("ready"):
            return state

        if state.get("changed") == "steps-keyboard":
            slider = state.get("steps_element")
            if slider is None:
                raise Exception("Nie udalo sie ustawic suwaka steps")
            direction = state.get("steps_direction")
            slider_key = Keys.ARROW_RIGHT if direction == "right" else Keys.ARROW_LEFT
            try:
                # Send exactly one key. The resulting React render can safely
                # invalidate this element because the next loop reacquires it.
                slider.send_keys(slider_key)
            except StaleElementReferenceException:
                # A concurrent render won the race; reacquire without counting
                # this as a configuration failure.
                continue
            time.sleep(0.1)
            continue

        time.sleep(0.5)

    raise Exception(f"Nie udalo sie potwierdzic ustawien Advanced: {last_state}")

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

def configure_generation_options(driver, metadata):
    advanced_state = None
    if GENERATION_PROFILE == ADVANCED_GENERATION_PROFILE:
        print("  Ustawiam Advanced: segmentation_free=true, steps=30...")
        advanced_state = ensure_advanced_generation_settings(driver, target_steps=30)

    option_state = read_generation_option_state(driver)
    if option_state:
        metadata["garment_mode_selected"] = (
            option_state.get("garment_mode_selected") or metadata["garment_mode_selected"]
        )
        metadata["garment_mode_state_source"] = (
            option_state.get("garment_mode_state_source") or metadata["garment_mode_state_source"]
        )
        metadata["quality_mode_selected"] = option_state.get("quality_mode_selected")
        metadata["quality_mode_state_source"] = option_state.get("quality_mode_state_source")
        metadata["turbo_enabled"] = option_state.get("turbo_enabled")
        metadata["turbo_state_source"] = option_state.get("turbo_state_source")

    if advanced_state:
        metadata["advanced_enabled"] = advanced_state.get("advanced_enabled")
        metadata["advanced_state_source"] = advanced_state.get("advanced_state_source")
        metadata["segmentation_free_enabled"] = advanced_state.get("segmentation_free_enabled")
        metadata["segmentation_free_state_source"] = advanced_state.get("segmentation_free_state_source")
        metadata["steps_selected"] = advanced_state.get("steps_selected")

    print(
        f"  Opcje: garment={metadata['garment_mode_selected'] or 'unknown'} | "
        f"quality={metadata['quality_mode_selected'] or 'unknown'} | "
        f"turbo={metadata['turbo_enabled'] if metadata['turbo_enabled'] is not None else 'unknown'} | "
        f"profile={metadata['generation_profile_requested']}"
    )
    if advanced_state:
        print(
            f"  OK Advanced={metadata['advanced_enabled']} | "
            f"segmentation_free={metadata['segmentation_free_enabled']} | "
            f"steps={metadata['steps_selected']}"
        )

    return option_state

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

def get_selected_run_configs():
    if not SELECTED_RUN_KEYS:
        return GARMENT_RUNS

    selected_run_lookup = set(SELECTED_RUN_KEYS)
    return [
        run_config for run_config in GARMENT_RUNS
        if run_config["key"] in selected_run_lookup
    ]

def create_remote_driver():
    opts = webdriver.ChromeOptions()
    if HEADLESS:
        opts.add_argument('--headless=new')
        opts.add_argument('--disable-gpu')
        opts.add_argument('--window-size=1920,1080')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')

    driver = webdriver.Remote(GRID_URL, options=opts)
    driver.set_page_load_timeout(60)
    return driver

def login_to_business_account(driver, user, relogin=False):
    login_label = "Ponowne logowanie..." if relogin else "Logowanie..."
    print(f"  {login_label}")
    driver.get("https://siz3r-dev.vercel.app/business/login")
    wait_for_document_ready(driver, 30)

    try:
        auth_form = wait_for_auth_form(driver, minimum_password_inputs=1, timeout=40)
        email_input = auth_form["email_input"]
        password_inputs = auth_form["password_inputs"]
        email_input.send_keys(user['email'])
    except TimeoutException:
        raise Exception("Timeout: nie znaleziono pola email logowania")

    if len(password_inputs) < 1:
        raise Exception(f"Za malo pol hasla logowania: {len(password_inputs)}")

    password_inputs[0].send_keys(user['password'])

    login_btn = wait_for_button_safe(driver, LOGIN_BUTTON_TEXTS, timeout=10, require_enabled=True)
    if not login_btn:
        raise Exception("Brak przycisku logowania")

    driver.execute_script("arguments[0].click();", login_btn)
    try:
        wait_for_post_auth_state(driver, '/business/login', minimum_password_inputs=1, timeout=7)
    except TimeoutException:
        print(f"  WARN Nie wykryto od razu potwierdzenia logowania, sprawdzam dalej...")

def dismiss_credit_modal_if_present(driver):
    print(f"  Sprawdzam modal kredytow...")
    try:
        skip_button = wait_for_button_safe(driver, CREDIT_MODAL_SKIP_TEXTS, timeout=5, require_enabled=True)
        if skip_button:
            button_label = ' / '.join(get_button_text_variants(skip_button)[:2]) or 'skip'
            print(f"  OK Znalazlem przycisk pomijania ({button_label}), klikam...")
            driver.execute_script("arguments[0].click();", skip_button)
            try:
                wait_for_element_to_disappear(driver, skip_button, timeout=3)
            except TimeoutException:
                pass
            print(f"  OK Modal pominiety")
        else:
            print(f"  WARN Modal nie pojawil sie (lub juz zamkniety)")
    except Exception as exc:
        print(f"  WARN Blad przy modal: {exc}")

def create_authenticated_driver(user):
    driver = create_remote_driver()
    login_to_business_account(driver, user)
    dismiss_credit_modal_if_present(driver)
    return driver

def open_authenticated_playground(driver, user):
    print(f"  Playground...")
    driver.get("https://siz3r-dev.vercel.app/business/playground")
    wait_for_document_ready(driver, 30)

    if '/business/login' in (driver.current_url or ''):
        print(f"  WARN Sesja wygasla podczas wejscia do playground, loguje ponownie...")
        login_to_business_account(driver, user, relogin=True)
        dismiss_credit_modal_if_present(driver)
        print(f"  Playground...")
        driver.get("https://siz3r-dev.vercel.app/business/playground")
        wait_for_document_ready(driver, 30)

def is_driver_alive(driver):
    if not driver:
        return False

    try:
        driver.current_url
        return True
    except Exception:
        return False

def close_driver_safely(driver):
    if not driver:
        return

    try:
        driver.quit()
    except Exception:
        pass

def get_generation_file_inputs(driver):
    file_inputs = None
    for attempt in range(3):
        try:
            file_inputs = wait_for_file_inputs(driver, minimum_count=2, timeout=12)
            break
        except TimeoutException:
            if attempt < 2:
                print(f"  Retry {attempt+1} - odswiezam strone...")
                driver.refresh()
                wait_for_document_ready(driver, 20)
            else:
                raise Exception("Timeout: nie znaleziono file inputs po 3 probach")

    if not file_inputs or len(file_inputs) < 2:
        raise Exception(f"Za malo file inputs: {len(file_inputs) if file_inputs else 0}")

    return file_inputs

def ensure_person_uploaded(driver, model_info, session_state=None):
    active_person_path = session_state.get("active_person_path") if session_state else None
    if active_person_path == model_info['person_path']:
        return

    print(f"  Wgrywam model osoby...")
    last_error = None

    for attempt in range(3):
        try:
            file_inputs = get_generation_file_inputs(driver)
            person_input = file_inputs[0]
            person_input.send_keys(model_info['person_path'])
        except StaleElementReferenceException as exc:
            last_error = exc
            print(f"  WARN Input modelu odswiezyl sie przed wyslaniem pliku, ponawiam ({attempt+1}/3)...")
            wait_for_document_ready(driver, 10)
            continue

        try:
            dispatch_file_input_events(driver, person_input)
        except StaleElementReferenceException:
            # Uploading the file can make React replace the input immediately.
            # send_keys() has already submitted the file, so reacquire the live inputs
            # instead of failing the whole first try-on for the new person.
            print("  WARN Input modelu odswiezyl sie po wyslaniu pliku, kontynuuje...")

        try:
            wait_for_file_inputs(driver, minimum_count=2, timeout=4)
        except TimeoutException:
            pass

        if session_state is not None:
            session_state["active_person_path"] = model_info['person_path']
            session_state["active_person_name"] = model_info['person_name']
        return

    if last_error:
        raise last_error

def upload_garment_file(driver, garment_path):
    last_error = None

    for attempt in range(3):
        try:
            file_inputs = wait_for_file_inputs(driver, minimum_count=2, timeout=12)
            if len(file_inputs) < 2:
                raise Exception(f"Za malo file inputs po modelu: {len(file_inputs)}")

            garment_input = file_inputs[1]
            clear_file_input(driver, garment_input)

            file_inputs = wait_for_file_inputs(driver, minimum_count=2, timeout=12)
            if len(file_inputs) < 2:
                raise Exception(f"Za malo file inputs po czyszczeniu ubrania: {len(file_inputs)}")

            garment_input = file_inputs[1]
            garment_input.send_keys(garment_path)
            dispatch_file_input_events(driver, garment_input)

            try:
                wait_for_generation_surface(driver, timeout=4)
            except TimeoutException:
                pass

            return
        except StaleElementReferenceException as exc:
            last_error = exc
            print(f"  WARN Input ubrania odswiezyl sie podczas podmiany, ponawiam ({attempt+1}/3)...")
            wait_for_document_ready(driver, 10)

    if last_error:
        raise last_error

def test_single_model(test_num, model_info, run_config):
    driver = None
    # user = generate_user()
    user = get_test_account()
    
    model_name_clean = Path(model_info['person_name']).stem
    garment_name_clean = None
    preselected_garment_name = model_info.get("preselected_garment_name")
    if preselected_garment_name:
        garment_name_clean = Path(preselected_garment_name).stem

    test_id_parts = [f"test_{test_num}", run_config["key"], model_info['gender'], model_name_clean]
    if garment_name_clean:
        test_id_parts.append(garment_name_clean)
    test_id = "_".join(test_id_parts)
    
    metadata = {
        "test_number": test_num,
        "test_id": test_id,
        "gender": model_info['gender'],
        "model_filename": model_info['person_name'],
        "user_email": user['email'],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "headless": HEADLESS,
        "pairing_mode": PAIRING_MODE,
        "pairing_seed": PAIRING_SEED if PAIRING_SEED_ACTIVE else None,
        "generation_profile_requested": GENERATION_PROFILE,
        "garment_run_key": run_config["key"],
        "garment_run_label": run_config["label"],
        "garment_mode_requested": run_config["site_mode"],
        "garment_mode_selected": None,
        "garment_mode_state_source": None,
        "quality_mode_selected": None,
        "quality_mode_state_source": None,
        "turbo_enabled": None,
        "turbo_state_source": None,
        "advanced_enabled": None,
        "advanced_state_source": None,
        "segmentation_free_enabled": None,
        "segmentation_free_state_source": None,
        "steps_selected": None,
        # "option_confirmation_screenshot": None,
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
        
        print(f"  Logowanie...")
        driver.get("https://siz3r-dev.vercel.app/business/login")
        wait_for_document_ready(driver, 30)

        try:
            auth_form = wait_for_auth_form(driver, minimum_password_inputs=1, timeout=40)
            email_input = auth_form["email_input"]
            password_inputs = auth_form["password_inputs"]
            email_input.send_keys(user['email'])
        except TimeoutException:
            raise Exception("Timeout: nie znaleziono pola email logowania")

        password_inputs[0].send_keys(user['password'])
        login_btn = wait_for_button_safe(driver, LOGIN_BUTTON_TEXTS, timeout=10, require_enabled=True)

        if not login_btn:
            raise Exception("Brak przycisku logowania")

        driver.execute_script("arguments[0].click();", login_btn)
        try:
            wait_for_post_auth_state(driver, '/business/login', minimum_password_inputs=1, timeout=7)
        except TimeoutException:
            print(f"  WARN Nie wykryto od razu potwierdzenia logowania, sprawdzam dalej...")

        # Registration flow kept for quick rollback if shared-account login is no longer desired.
        # print(f"  Rejestracja...")
        # driver.get("https://siz3r-dev.vercel.app/business/register")
        # wait_for_document_ready(driver, 30)
        #
        # try:
        #     registration_form = wait_for_registration_form(driver, 40)
        #     email_input = registration_form["email_input"]
        #     password_inputs = registration_form["password_inputs"]
        #     email_input.send_keys(user['email'])
        # except TimeoutException:
        #     raise Exception("Timeout: nie znaleziono pola email")
        #
        # password_inputs[0].send_keys(user['password'])
        # password_inputs[1].send_keys(user['password'])
        # register_btn = wait_for_button_safe(driver, REGISTER_BUTTON_TEXTS, timeout=10, require_enabled=True)
        #
        # if not register_btn:
        #     raise Exception("Brak przycisku rejestracji")
        #
        # driver.execute_script("arguments[0].click();", register_btn)
        # try:
        #     wait_for_post_registration_state(driver, timeout=7)
        # except TimeoutException:
        #     print(f"  WARN Nie wykryto od razu potwierdzenia rejestracji, sprawdzam dalej...")
        
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

        configure_generation_options(driver, metadata)

        # Option confirmation screenshots are disabled to keep runs lighter and faster.
        # option_confirmation_path = os.path.join(test_folder, "option_confirmation.png")
        # if capture_option_confirmation(driver, option_confirmation_path):
        #     metadata["option_confirmation_screenshot"] = option_confirmation_path
        #     print(f"  OK Screenshot opcji zapisany: option_confirmation.png")
        # else:
        #     print(f"  WARN Nie udalo sie zapisac screenshotu opcji")
        
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
        result_image_baseline = get_result_image_sources(driver)
        driver.execute_script("arguments[0].click();", generate_btn)
        print(f"  Generacja...")
        
        def result_image_present(driver):
            return find_new_generated_image(driver, result_image_baseline)
        
        try:
            result_img = wait_for_generated_result(driver, result_image_present)
        except TimeoutException:
            raise Exception(f"Timeout: nie znaleziono wyniku generacji po {GENERATION_RESULT_TIMEOUT + GENERATION_ACTIVE_GRACE_TIMEOUT}s")
        
        # The result image is already gated by explicit waits above, so this extra
        # pause is disabled to keep serial runs moving faster.
        # time.sleep(2)
        
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

def test_single_model_wait_optimized(test_num, model_info, run_config, driver=None, user=None, session_state=None):
    owns_driver = driver is None
    # user = generate_user()
    user = user or get_test_account()

    model_name_clean = Path(model_info['person_name']).stem
    garment_name_clean = None
    preselected_garment_name = model_info.get("preselected_garment_name")
    if preselected_garment_name:
        garment_name_clean = Path(preselected_garment_name).stem

    test_id_parts = [f"test_{test_num}", run_config["key"], model_info['gender'], model_name_clean]
    if garment_name_clean:
        test_id_parts.append(garment_name_clean)
    test_id = "_".join(test_id_parts)

    metadata = {
        "test_number": test_num,
        "test_id": test_id,
        "gender": model_info['gender'],
        "model_filename": model_info['person_name'],
        "user_email": user['email'],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "headless": HEADLESS,
        "pairing_mode": PAIRING_MODE,
        "pairing_seed": PAIRING_SEED if PAIRING_SEED_ACTIVE else None,
        "generation_profile_requested": GENERATION_PROFILE,
        "garment_run_key": run_config["key"],
        "garment_run_label": run_config["label"],
        "garment_mode_requested": run_config["site_mode"],
        "garment_mode_selected": None,
        "garment_mode_state_source": None,
        "quality_mode_selected": None,
        "quality_mode_state_source": None,
        "turbo_enabled": None,
        "turbo_state_source": None,
        "advanced_enabled": None,
        "advanced_state_source": None,
        "segmentation_free_enabled": None,
        "segmentation_free_state_source": None,
        "steps_selected": None,
        # "option_confirmation_screenshot": None,
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

        if owns_driver:
            driver = create_authenticated_driver(user)
        elif not is_driver_alive(driver):
            raise Exception("Sesja przegladarki jest niedostepna")

        total_generation_attempts = GENERATION_RETRY_COUNT + 1
        result_img = None

        for generation_attempt in range(1, total_generation_attempts + 1):
            should_open_playground = True
            if session_state is not None:
                should_open_playground = not session_state.get("playground_ready", False)

            if should_open_playground:
                open_authenticated_playground(driver, user)
                if session_state is not None:
                    session_state["playground_ready"] = True
                    session_state["active_person_path"] = None
                    session_state["active_person_name"] = None

            ensure_person_uploaded(driver, model_info, session_state=session_state)
            upload_garment_file(driver, garment_path)

            garment_mode_state = ensure_garment_site_mode(driver, run_config["site_mode"])
            if garment_mode_state:
                metadata["garment_mode_selected"] = garment_mode_state.get("selected_label")
                metadata["garment_mode_state_source"] = garment_mode_state.get("state_source")
                print(f"  OK Tryb odziezy: {metadata['garment_mode_selected']}")

            configure_generation_options(driver, metadata)

            # Option confirmation screenshots are disabled to keep runs lighter and faster.
            # option_confirmation_path = os.path.join(test_folder, "option_confirmation.png")
            # if capture_option_confirmation(driver, option_confirmation_path):
            #     metadata["option_confirmation_screenshot"] = option_confirmation_path
            #     print(f"  OK Screenshot opcji zapisany: option_confirmation.png")
            # else:
            #     print(f"  WARN Nie udalo sie zapisac screenshotu opcji")

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
            result_image_baseline = get_result_image_sources(driver)
            driver.execute_script("arguments[0].click();", generate_btn)
            print(f"  Generacja...")

            def result_image_present(current):
                return find_new_generated_image(current, result_image_baseline)

            try:
                result_img = wait_for_generated_result(driver, result_image_present)
                break
            except TimeoutException:
                if generation_attempt >= total_generation_attempts:
                    raise Exception(f"Timeout: nie znaleziono wyniku generacji po {GENERATION_RESULT_TIMEOUT + GENERATION_ACTIVE_GRACE_TIMEOUT}s")

                print(f"  WARN Generacja utkwiła, odswiezam playground i ponawiam ({generation_attempt}/{total_generation_attempts - 1})...")
                if session_state is not None:
                    session_state["playground_ready"] = False
                    session_state["active_person_path"] = None
                    session_state["active_person_name"] = None

        try:
            wait_for_image_render_complete(driver, result_img, timeout=2)
        except TimeoutException:
            pass

        print(f"  Zapisuje wynik...")
        result_path = os.path.join(result_folder, "result.png")
        if download_image_from_element(driver, result_img, result_path):
            metadata["status"] = "success"
            metadata["result_path"] = result_path

            with open(os.path.join(test_folder, "metadata.json"), 'w') as f:
                json.dump(metadata, f, indent=2)

            print(f"  OK - {test_id}")
            if owns_driver:
                close_driver_safely(driver)
            return True

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
            except Exception:
                pass

            if session_state is not None:
                session_state["playground_ready"] = False
                session_state["active_person_path"] = None
                session_state["active_person_name"] = None

            if owns_driver:
                close_driver_safely(driver)

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
        "pairing_seed": PAIRING_SEED if PAIRING_SEED_ACTIVE else None,
        "generation_profile": GENERATION_PROFILE,
        "garments_per_person": GARMENTS_PER_PERSON,
        "reuse_browser_session": REUSE_BROWSER_SESSION,
        "selected_run_keys": SELECTED_RUN_KEYS or [config["key"] for config in GARMENT_RUNS],
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
    shared_user = get_test_account() if REUSE_BROWSER_SESSION else None
    shared_driver = None
    shared_session_state = {
        "playground_ready": False,
        "active_person_path": None,
        "active_person_name": None,
    } if REUSE_BROWSER_SESSION else None

    print(f"  Browser session reuse: {'enabled' if REUSE_BROWSER_SESSION else 'disabled'}")

    for i, model in enumerate(all_models, 1):
        test_passed = False

        if REUSE_BROWSER_SESSION:
            if not is_driver_alive(shared_driver):
                close_driver_safely(shared_driver)
                shared_driver = None
                try:
                    shared_driver = create_authenticated_driver(shared_user)
                except Exception as exc:
                    print(f"  WARN Nie udalo sie przygotowac wspolnej sesji, uruchamiam osobna przegladarke: {exc}")

            if shared_driver:
                test_passed = test_single_model_wait_optimized(
                    i,
                    model,
                    run_config,
                    driver=shared_driver,
                    user=shared_user,
                    session_state=shared_session_state,
                )
                if not is_driver_alive(shared_driver):
                    close_driver_safely(shared_driver)
                    shared_driver = None
                    shared_session_state["playground_ready"] = False
                    shared_session_state["active_person_path"] = None
                    shared_session_state["active_person_name"] = None
            else:
                test_passed = test_single_model_wait_optimized(i, model, run_config)
        else:
            test_passed = test_single_model_wait_optimized(i, model, run_config)

        if test_passed:
            success += 1
        else:
            failed += 1

        # Extra pacing between serial tests is disabled to reduce total runtime.
        # if i < total_tests:
        #     time.sleep(2)

        elapsed = time.time() - start_time
        avg_per_test = elapsed / i
        remaining = (total_tests - i) * avg_per_test
        print(f"  Progress: {i}/{total_tests} | ETA: {int(remaining/60)}min")

    close_driver_safely(shared_driver)

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
    selected_run_configs = get_selected_run_configs()

    print("SIZ3R BUSINESS TESTS - ALL MODELS")
    print(f"Headless mode: {HEADLESS}")
    print(f"Pairing mode: {PAIRING_MODE}")
    print(f"Generation profile: {GENERATION_PROFILE}")
    if PAIRING_SEED_ACTIVE:
        print(f"Pairing seed: {PAIRING_SEED}")
    if GARMENTS_PER_PERSON is not None:
        if PAIRING_MODE == ONE_MODEL_PER_GARMENT_MODE:
            print(
                f"Garments per person: {GARMENTS_PER_PERSON} "
                "(ignored by one_model_per_garment)"
            )
        else:
            print(f"Garments per person: {GARMENTS_PER_PERSON}")
    print(f"Selected runs: {', '.join(run_config['key'] for run_config in selected_run_configs)}")
    print(f"Reuse browser session: {REUSE_BROWSER_SESSION}")
    print(f"Fail on test failures: {FAIL_ON_TEST_FAILURES}")

    required_paths = {
        "women_people": PEOPLE_FOLDERS["women"],
        "men_people": PEOPLE_FOLDERS["men"],
    }
    for run_config in selected_run_configs:
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
    for run_config in selected_run_configs:
        run_summaries[run_config["key"]] = run_test_suite(run_config)

    with open(RUN_SUMMARY_PATH, 'w') as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "headless_mode": HEADLESS,
            "pairing_mode": PAIRING_MODE,
            "pairing_seed": PAIRING_SEED if PAIRING_SEED_ACTIVE else None,
            "generation_profile": GENERATION_PROFILE,
            "selected_run_keys": [run_config["key"] for run_config in selected_run_configs],
            "reuse_browser_session": REUSE_BROWSER_SESSION,
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
    if all_completed_runs_clean:
        sys.exit(0)

    if FAIL_ON_TEST_FAILURES:
        sys.exit(1)

    any_successful_tests = any(
        summary.get("successful", 0) > 0
        for summary in completed_run_summaries
    )
    if any_successful_tests:
        print("\nPartial failures detected, but returning success because FAIL_ON_TEST_FAILURES=false")
        sys.exit(0)

    sys.exit(1)
