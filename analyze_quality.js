import "dotenv/config";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  LABEL_KEYS, envNumber, fileToDataUrl, parseRetryAfterMs,
  RATING_RESPONSE_FORMAT, AUDIT_RESPONSE_FORMAT,
  validateAndNormalizeRating as normalizeRating, validateArtifactAudit,
  applyArtifactAuditToRating as applyAudit,
} from "./lib/assessment.js";

const OPENAI_API_KEY = String(process.env.OPENAI_API_KEY || "").trim();
const HAS_OPENAI_API_KEY = OPENAI_API_KEY.length > 0;
const MODEL = String(process.env.OPENAI_MODEL || "gpt-4.1").trim();
const ENDPOINT = "https://api.openai.com/v1/chat/completions";
const TIMEOUT_MS = envNumber(process.env, "OPENAI_TIMEOUT_MS", 180000, { min: 1 });
const DELAY_MS = envNumber(process.env, "OPENAI_DELAY_MS", 750, { min: 0 });
const MAX_RETRIES = envNumber(process.env, "OPENAI_MAX_RETRIES", 3, { min: 1 });
const CONCURRENCY = envNumber(process.env, "OPENAI_CONCURRENCY", 2, { min: 1 });
const MIN_RETRY_DELAY_MS = envNumber(process.env, "OPENAI_MIN_RETRY_DELAY_MS", 1000, { min: 1 });
const RATE_LIMIT_JITTER_MS = envNumber(process.env, "OPENAI_RATE_LIMIT_JITTER_MS", 250, { min: 0 });
const ENABLE_ARTIFACT_AUDIT = /^(1|true|yes)$/i.test(String(process.env.ANALYZE_ENABLE_ARTIFACT_AUDIT || "").trim());
const REPORT_MODE = String(process.env.ANALYSIS_REPORT_MODE || "review").trim().toLowerCase();
const GALLERY_ONLY_MODE = REPORT_MODE === "gallery";
const COMPARISON_ONLY_MODE = REPORT_MODE === "comparison";
const SCORE_POLICY = {
  passScore: envNumber(process.env, "OPENAI_PASS_SCORE_THRESHOLD", 80, { max: 100 }),
  maxMinorLabels: envNumber(process.env, "OPENAI_MAX_MINOR_LABELS_FOR_PASS", 2, { max: 4 }),
};
const OUTPUTS_DIR = path.resolve(process.env.ANALYSIS_OUTPUT_DIR || "outputs");
const IMAGE_EXTENSIONS = new Set([".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"]);

const PROMPT = `You are a common-sense QA evaluator for virtual try-on transfer quality.
Your job is to judge whether the clothing from garment.png was transferred well onto the person from model.png, creating result.png.
You should think like a careful human reviewer, not a rigid rule parser.

The main question is:
Does result.png look like the same person from model.png wearing the same garment from garment.png, without obvious damage or nonsense being introduced?

Image roles are fixed by order:
1) TARGET_GARMENT = garment.png. This is the source garment that should be transferred.
2) PERSON = model.png. This is the original person before try-on.
3) GENERATED_RESULT = result.png. This is the final try-on result and the image you judge.

If only two images are provided, they are:
1) TARGET_GARMENT
2) GENERATED_RESULT

Core judgment principles:
- Focus on the transferred garment first.
- Also check whether the person from PERSON was damaged during generation.
- The result should still look like the same person from PERSON.
- The garment in GENERATED_RESULT should still look like the same garment from TARGET_GARMENT.
- Use common sense. If the result looks good and believable to a normal shopper, that matters.
- Do not fail tiny issues that most people would never notice.
- Do not ignore obvious failures just because the garment is roughly recognizable.

What matters most:

1) Garment transfer fidelity
- Compare TARGET_GARMENT with the clothing worn in GENERATED_RESULT.
- Focus on garment type, neckline, sleeve type, sleeve length, silhouette, length, looseness, and overall structure.
- Focus on visible structural details such as buttons, zippers, plackets, pockets, stripes, seams, panels, trims, cuffs, ribbing, and closures.
- If TARGET_GARMENT itself shows a visible inner collar, mock neck, knit insert, zipper guard, lining, or underlayer at the neck, treat that visible neck element as part of the target appearance.
- A similar neck insert or visible underlayer in GENERATED_RESULT is acceptable when it matches or plausibly corresponds to what is visible in TARGET_GARMENT.
- Placement of details matters.
- Missing visible details that are clearly present in TARGET_GARMENT are errors.
- Added details that are not in TARGET_GARMENT are errors.
- If a visible key element is fully missing, that is usually a MAJOR issue.
- If the garment has a print or stripes, the result should preserve them well enough to still read as the same garment.
- Minor distortion from pose, body shape, or drape is acceptable.
- Normal on-body drape is acceptable. Do not over-penalize small changes caused by pose, gravity, body shape, lighting, or resolution.

2) Person and non-target preservation
- Compare PERSON with GENERATED_RESULT.
- The person should remain intact: no damaged face, hair, neck, hands, skin, legs, or body shape.
- Clothing and items that are not the transferred garment should remain intact unless naturally covered by the transferred garment.
- If other clothing, shoes, or accessories from PERSON are recolored, changed, erased, warped, merged, or replaced without good reason, that is an error.
- If PERSON originally had a turtleneck, high collar, scarf-like neck coverage, or other garment covering the neck, GENERATED_RESULT may legitimately reveal or synthesize neck skin or upper chest that was hidden before.
- A newly visible or newly synthesized neck area is acceptable if it looks anatomically natural, smoothly integrated, and consistent in skin tone, lighting, and shading.
- Do NOT treat a clean, natural-looking exposed neck as leftover turtleneck damage just because that area was hidden in PERSON.
- Only treat the neck area as artifact or damage if there are clear remnants of the old neck covering, or if the generated neck looks malformed, implausible, mismatched, or corrupted.
- If the transferred garment is a top, bottoms from PERSON should usually remain the same unless naturally covered.
- If PERSON originally wears a dress, skirt, tunic, romper, pinafore, or another outfit with a lower portion visible below the transferred upper-body garment, that lower portion may remain visible in GENERATED_RESULT.
- For top or outerwear transfers, it can be correct for GENERATED_RESULT to look like PERSON put a hoodie, jacket, cardigan, sweater, or similar upper-body layer on over the existing outfit.
- Do NOT require the original dress or skirt to be fully replaced or hidden when the transferred garment is only an upper-body item and the result reads as a natural layered outfit.
- Do NOT mistake the preserved lower part of an original dress for an invented skirt or extra lower-body garment if it looks coherent, intentional, and consistent with PERSON.
- Only flag that preserved lower portion as damage if it is clearly recolored, corrupted, detached, implausibly reshaped, or appears to be a truly new invented garment not supported by PERSON.
- Only if TARGET_GARMENT visibly appears tucked into bottoms in garment.png, GENERATED_RESULT may also reveal or synthesize the upper part of the bottoms that was hidden in PERSON.
- A newly visible waistband, top of pants, top of skirt, or top of shorts caused by tucking is acceptable if it looks plausible, consistent with the rest of the bottoms, and visually fitting.
- If garment.png does not visibly show the top tucked into bottoms, do NOT excuse a changed waistband or top-of-bottom area as a tuck effect.
- Because that upper-bottom area may have been hidden in PERSON, do NOT require an exact reconstruction of the original waistband or top edge.
- Elastic waistbands or gathered shorts/pants may sit a bit higher and show stronger bunching or gathers after tucking; that alone is not damage.
- Small differences in the top seam, waistband shape, gathers, folds, or upper-bottom contour are acceptable if the result still looks natural and coherent overall.
- Only treat that newly generated upper-bottom area as damage if it looks malformed, mismatched, corrupted, or like an invented extra layer.
- If the transferred garment is longer and naturally covers some underlying clothing, that is fine.

3) No unreasonable additions
- Do not allow random added layers, extra collars, ghost garments, leftover old clothing fragments, or invented details that are not supported by either TARGET_GARMENT or PERSON.
- Small plausible generation variation is acceptable.
- Clearly invented structure is not acceptable.

4) Artifact check
- Look for neck damage, merged hair, leftover collars or hoods, warped boundaries, ghosting, broken body parts, and damaged non-target clothing.
- Before calling a neck-area leftover, compare the neck region to TARGET_GARMENT and do not mistake a target-supported inner collar, knit insert, or neck underlayer for old clothing.
- Artifacts that clearly damage the person, the garment, or other visible clothing are MAJOR issues.
- Use MINOR only when the artifact is clearly noticeable but still limited in scope.
- Tiny edge noise, slight boundary wobble, mild blur, or very small leftover traces that a normal shopper would likely ignore should be NONE, not MINOR.
- Smaller warping or mild resolution loss can be MINOR if it is noticeable enough to reduce trust.

Category focus:
- The supplied transfer mode defines which clothing is meant to change.
- UPPER: transfer the upper garment; preserve lower clothing unless naturally covered.
- LOWER: transfer pants, shorts, or skirt; preserve the upper clothing unless naturally occluded.
- FULL: transfer the full dress, jumpsuit, suit, or multi-piece outfit shown in TARGET_GARMENT. Replacing both upper and lower clothing is expected; do not call those replacements collateral damage.
- For FULL multi-piece references, compare every intended garment, not just the top. Use garment_category="outfit" for multi-piece outfits.
- If TARGET_GARMENT is a top or outerwear, judge only that transferred top garment for garment fidelity.
- If TARGET_GARMENT is pants, judge only the transferred pants for garment fidelity.
- Ignore other clothing for identity matching unless that other clothing was damaged by the generation.
- Clothing that is hidden by natural overlap or occlusion does not count as missing.

Common-sense pass/fail standard:
- A pass means the try-on looks like a good transfer of TARGET_GARMENT onto PERSON, and GENERATED_RESULT would not make a normal shopper or merchant immediately distrust it.
- A fail means the garment identity is clearly wrong, important details are missing, the person is damaged, other clothing is wrongly changed, or obvious artifacts break trust.

Label assignment, choose ONE per category:
- garment_structure_error: NONE | MINOR | MAJOR
- construction_alignment_error: NONE | MINOR | MAJOR
- fit_error: NONE | MINOR | MAJOR
- artifact_error: NONE | MINOR | MAJOR

Scoring and pass/fail are calculated by the application from your severity labels.
Do not calculate scores or make the final pass/fail decision yourself.

Output requirements:
Return ONLY valid JSON, no markdown and no commentary, exactly in this schema:
{
  "garment_type": string,
  "garment_category": "top" | "pants" | "dress" | "skirt" | "outerwear" | "outfit" | "other",
  "intended_fit": "tight" | "regular" | "loose" | "oversized" | null,
  "silhouette_preserved": "YES" | "PARTIAL" | "NO",
  "critical_issues": [string],
  "minor_issues": [string],
  "positives": [string],
  "notes": string,
  "labels": {
    "garment_structure_error": "NONE" | "MINOR" | "MAJOR",
    "construction_alignment_error": "NONE" | "MINOR" | "MAJOR",
    "fit_error": "NONE" | "MINOR" | "MAJOR",
    "artifact_error": "NONE" | "MINOR" | "MAJOR"
  }
}
Use null for intended_fit if the visible evidence is insufficient.
Every critical issue must correspond to at least one MAJOR label.
Garment structure includes silhouette and length preservation.

Hard limits:
- critical_issues: max 6 items
- minor_issues: max 6 items
- positives: max 6 items
- notes: max 350 characters, no repetition
- If you start repeating, stop and output the JSON immediately.
- Return JSON only.
- Begin with "{" and end with "}".
- No trailing text after the final "}".

Constraints:
- Be strict about visible garment design and detail.
- Be tolerant of small color and texture variation.
- Do not invent details that are not visible.
- Judge only visible evidence.`.trim();

const ARTIFACT_AUDIT_PROMPT = `You are a careful integrity auditor for virtual try-on images.
Your ONLY job is to detect obvious or materially important failures in GENERATED_RESULT that a general garment evaluator might overlook.

You may receive:
1) MODEL_ORIGINAL - the original person before try-on
2) TARGET_GARMENT - the intended garment reference
3) GENERATED_RESULT - the final try-on image to audit

Use the supplied transfer mode. For LOWER transfers, upper clothing is non-target. For FULL transfers, both upper and lower target garments may change; only damage outside the target outfit counts as collateral damage.

Focus especially on:
- neck and shoulder leftovers from the original clothing: old collars, hoods, padded neck shapes, scarf-like wraps, masks, or fragments that clearly do not belong to TARGET_GARMENT
- non-target clothing damage: especially bottoms, skirts, pants, shorts, leggings, shoes, or socks that were recolored, changed, warped, erased, or partially replaced even though the try-on was only supposed to change another garment
- added extra lower-body garments or layers, such as invented shorts, skirts, leggings, or overlays that were not present in MODEL_ORIGINAL and are not part of TARGET_GARMENT
- preserved lower portions of an original dress, skirt, tunic, romper, or similar garment showing below a transferred top or outerwear are acceptable when the result reads as a natural layered outfit; do not treat that as an extra garment by default
- obvious merged boundaries, ghost remnants, or corrupted clothing/body regions
- If TARGET_GARMENT itself shows a visible inner collar, knit neck insert, mock neck, or neck underlayer, a similar visible neck element in GENERATED_RESULT can be correct and should not be treated as leftover clothing
- BUT if MODEL_ORIGINAL had a turtleneck, high collar, or other neck coverage, a newly visible or newly synthesized neck can be acceptable and should be judged for natural appearance rather than treated as automatic leftover clothing
- BUT only if TARGET_GARMENT visibly appears tucked into bottoms in garment.png, a newly visible or newly synthesized waistband or upper-bottom area can be acceptable and should be judged for plausibility rather than treated as automatic damage

Rules:
- Only set artifact_present to "YES" when the artifact is clear enough that a normal reviewer would notice it and care
- Do not flag tiny, ambiguous, or low-impact irregularities such as slight edge roughness, tiny neck shading oddities, mild blur, or small leftover traces that do not materially hurt trust
- Use artifact_severity = "MINOR" only for localized, noticeable issues that do not materially damage the person, the transferred garment, or non-target clothing
- If a large or obvious leftover-clothing artifact is clearly visible without reasonable doubt, artifact_severity must be "MAJOR"
- If visible non-target bottoms are recolored, changed, replaced, or corrupted relative to MODEL_ORIGINAL, artifact_severity should usually be "MAJOR", except for a plausible newly visible upper-bottom area caused by a tucked-in target garment
- If a new lower-body garment or extra layer appears in GENERATED_RESULT that was not present in MODEL_ORIGINAL and is not the target garment, artifact_severity should usually be "MAJOR"
- If the neck or shoulder area clearly contains remnants of the original outfit that are not part of TARGET_GARMENT, artifact_severity should usually be "MAJOR"
- Before flagging a neck remnant, first check whether TARGET_GARMENT already includes a visible inner neck layer or collar detail; if it does, a matching neck element in GENERATED_RESULT is expected, not an artifact
- Do NOT call a visible neck insert, mock neck, knit collar, or inner layer a leftover artifact when that same type of neck detail is present in TARGET_GARMENT
- If MODEL_ORIGINAL hid the neck with a turtleneck, high collar, scarf, or similar coverage, do NOT treat a clean generated neck as a leftover artifact by itself
- In those neck-covered cases, judge the newly visible neck by whether it looks natural in anatomy, skin tone, edge blending, and lighting; flag it only if it looks like actual leftover clothing or clearly unnatural synthetic anatomy
- If something could plausibly be normal shadow, fold, drape, or natural occlusion, do NOT call it MAJOR
- Never return a perfect clean result if a clear artifact or collateral damage exists
- Do NOT treat the original garment disappearing inside the replaced target area as damage; that replacement is expected
- When MODEL_ORIGINAL is available, non-target garments such as bottoms and shoes should remain the same in GENERATED_RESULT unless naturally covered by the target garment
- If MODEL_ORIGINAL wears a dress, skirt, tunic, romper, or similar lower garment and TARGET_GARMENT is a top or outerwear item, do NOT require that original lower garment to disappear; a visible lower portion can be correct
- Do NOT call the visible lower part of an original dress a "new skirt" or "extra lower-body garment" when it simply remains visible beneath a newly added hoodie, jacket, cardigan, sweater, or other upper-body layer and still looks coherent
- Only when TARGET_GARMENT visibly appears tucked into bottoms in garment.png, do NOT treat a newly visible or synthesized waistband, top of pants, top of skirt, or top of shorts as damage by itself
- In tucked-in cases, judge that upper-bottom area by whether it looks plausible and consistent with the visible bottoms; do NOT require an exact reconstruction of the hidden original upper-bottom area
- Elastic waistbands or gathered shorts/pants may appear higher, tighter, or more bunched after tucking; do NOT call that warped or detached unless there is a clear floating gap, broken outline, double layer, or impossible geometry
- Minor differences in waistband curve, top edge shape, folds, gathers, or upper-bottom contour should usually be NONE or at most MINOR if the area still looks natural overall
- Flag the tucked upper-bottom area only if it is clearly malformed, detached, impossible-looking, badly blended, or appears like an extra garment
- If garment.png does not visibly show a tucked-in presentation, do NOT use tucking as a justification for changed upper-bottom structure
- Do NOT compare bottoms or shoes in GENERATED_RESULT to styled non-target items in TARGET_GARMENT
- If the bottom garment in GENERATED_RESULT is changed, replaced, recolored, warped, erased, or partially lost relative to MODEL_ORIGINAL, that counts as damage to non-target clothing, except for a plausible newly visible or synthesized upper-bottom area caused by a tucked-in target garment

Return ONLY valid JSON in this exact schema:
{
  "artifact_present": "YES" | "NO",
  "artifact_severity": "NONE" | "MINOR" | "MAJOR",
  "artifact_reasons": [string],
  "notes": string
}

Hard limits:
- artifact_reasons: max 4 items
- notes: max 240 characters
- If artifact_present is "NO", artifact_severity must be "NONE"
- If artifact_present is "YES", artifact_severity must be "MINOR" or "MAJOR"
Begin with "{" and end with "}".
No trailing text after the final "}".`.trim();


let globalCooldownUntil = 0;
let nextRequestAt = 0;

function normalizeString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function ensureDir(dirPath) {
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true });
  }
  return dirPath;
}

function projectRelative(filePath) {
  return filePath ? path.relative(process.cwd(), filePath) : null;
}

function toWebPath(filePath) {
  return String(filePath || "").replace(/\\/g, "/");
}

function toReviewAssetPath(reviewRoot, sourcePath) {
  if (!sourcePath || !fs.existsSync(sourcePath) || !fs.statSync(sourcePath).isFile()) {
    return null;
  }
  return toWebPath(path.relative(reviewRoot, sourcePath));
}

function parseSourceDirList(value) {
  return [...new Set(String(value || "").split(/[\r\n,;]+/).map(part => part.trim()).filter(Boolean).map(part => path.resolve(part)))];
}

function resolveSourceDirs() {
  const explicit = parseSourceDirList(process.env.ANALYZE_SOURCE_DIR);
  if (explicit.length) return explicit;
  const defaults = ["test_results_upper", "test_results_lower", "test_results_full", "test_results"]
    .map(name => path.resolve(name)).filter(dir => fs.existsSync(dir) && fs.statSync(dir).isDirectory());
  return defaults.length ? defaults : [path.resolve("images")];
}

function isSupportedImage(filename) {
  return IMAGE_EXTENSIONS.has(path.extname(filename).toLowerCase());
}

function findUniqueImageByBase(dirPath, base) {
  if (!fs.existsSync(dirPath) || !fs.statSync(dirPath).isDirectory()) {
    return { filePath: null, error: null };
  }

  const baseLower = base.toLowerCase();
  const matches = fs
    .readdirSync(dirPath, { withFileTypes: true })
    .filter((entry) => entry.isFile() && isSupportedImage(entry.name))
    .map((entry) => entry.name)
    .filter((name) => path.parse(name).name.toLowerCase() === baseLower);

  if (matches.length === 0) return { filePath: null, error: null };
  if (matches.length > 1) {
    return {
      filePath: null,
      error: `Duplicate files for "${base}" in ${projectRelative(dirPath) || dirPath}: ${matches.join(", ")}`,
    };
  }

  return { filePath: path.resolve(dirPath, matches[0]), error: null };
}

function readJsonFileSafe(filePath) {
  if (!filePath || !fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    return { ok: false, value: null, error: null };
  }

  try {
    const raw = fs.readFileSync(filePath, "utf8");
    return { ok: true, value: JSON.parse(raw), error: null };
  } catch (error) {
    return { ok: false, value: null, error: error?.message ?? String(error) };
  }
}

function summarizeMetadata(metadata) {
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return null;
  }

  const picked = {};
  for (const key of [
    "test_number",
    "test_id",
    "gender",
    "model_filename",
    "garment_filename",
    "garment_run_key",
    "garment_mode_requested",
    "garment_mode_selected",
    "quality_mode_selected",
    "premium_requested",
    "turbo_requested",
    "turbo_enabled",
    "flat_requested",
    "flat_enabled",
    "generation_profile_requested",
    "advanced_enabled",
    "segmentation_free_enabled",
    "steps_selected",
    "pairing_mode",
    "pairing_seed",
    "error",
    "status",
    "timestamp",
  ]) {
    if (metadata[key] !== undefined) {
      picked[key] = metadata[key];
    }
  }

  return Object.keys(picked).length > 0 ? picked : null;
}

function collectFolderAssets(folderName, folderPath, sourceLayout) {
  const nested = (subdir, base) => findUniqueImageByBase(path.join(folderPath, subdir), base);
  const flat = (base) => findUniqueImageByBase(folderPath, base);

  const garment = sourceLayout === "test_results" ? nested("garment", "garment") : flat("garment");
  const model = sourceLayout === "test_results" ? nested("model", "model") : flat("model");
  const result = sourceLayout === "test_results" ? nested("result", "result") : flat("result");
  const metadataPath = path.join(folderPath, "metadata.json");
  const metadata = readJsonFileSafe(metadataPath);
  const errors = [garment.error, model.error, result.error, metadata.error].filter(Boolean);

  return {
    folder: folderName,
    folderPath,
    sourceLayout,
    ok: errors.length === 0,
    error: errors.join(" | ") || null,
    garmentPath: garment.filePath,
    modelPath: model.filePath,
    resultPath: result.filePath,
    metadataPath:
      metadataPath && fs.existsSync(metadataPath) && fs.statSync(metadataPath).isFile() ? metadataPath : null,
    metadata: metadata.ok ? metadata.value : null,
    metadataError: metadata.error,
  };
}

function safeJsonParse(text) {
  try {
    return { ok: true, json: JSON.parse(text) };
  } catch (e) {
    return { ok: false, error: e?.message ?? String(e) };
  }
}

function validateAndNormalizeRating(raw) {
  return normalizeRating(raw, SCORE_POLICY);
}

function applyArtifactAuditToRating(rating, audit) {
  return applyAudit(rating, audit, SCORE_POLICY);
}

function shouldRunArtifactAudit(rating) {
  return ENABLE_ARTIFACT_AUDIT || rating.successful === "YES";
}

function requestContext(context) {
  const metadata = summarizeMetadata(context.metadata) || {};
  const mode = inferGarmentRunType({ ...metadata, folder: context.folder, source_folder: context.folderPath });
  return "Transfer mode: " + mode.toUpperCase() + ". Generation settings (context only, apply the same quality standard to every setting): " + JSON.stringify({
    quality: metadata.quality_mode_selected ?? null,
    flat: metadata.flat_enabled ?? metadata.flat_requested ?? null,
    profile: metadata.generation_profile_requested ?? null,
    steps: metadata.steps_selected ?? null,
  });
}

function setGlobalCooldown(ms) {
  globalCooldownUntil = Math.max(globalCooldownUntil, Date.now() + ms + Math.floor(Math.random() * (RATE_LIMIT_JITTER_MS + 1)));
}

async function waitForGlobalCooldown() {
  const reserved = Math.max(Date.now(), nextRequestAt, globalCooldownUntil);
  nextRequestAt = reserved + DELAY_MS;
  if (reserved > Date.now()) await sleep(reserved - Date.now());
  // A concurrent request may have received a 429 while this one was waiting.
  while (globalCooldownUntil > Date.now()) await sleep(globalCooldownUntil - Date.now());
}

function extractAssistantText(resp) {
  const msg = resp?.choices?.[0]?.message;
  if (!msg) return "";
  if (typeof msg.content === "string") return msg.content;

  if (Array.isArray(msg.content)) {
    const texts = msg.content
      .map((p) => (p && typeof p.text === "string" ? p.text : ""))
      .filter(Boolean);
    return texts.join("\n");
  }

  return "";
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function postChatCompletionsOnce(payload) {
  await waitForGlobalCooldown();
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const res = await fetch(ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${OPENAI_API_KEY}`,
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    const text = await res.text();
    if (!res.ok) {
      const safeText = OPENAI_API_KEY ? text.replaceAll(OPENAI_API_KEY, "[redacted]") : text;
      const err = new Error(`HTTP ${res.status}: ${safeText}`);
      err.status = res.status;
      err.body = safeText;
      err.headers = Object.fromEntries(res.headers.entries());
      throw err;
    }

    return JSON.parse(text);
  } finally {
    clearTimeout(t);
  }
}

async function postChatCompletions(payload) {
  let lastErr;
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      return await postChatCompletionsOnce(payload);
    } catch (err) {
      lastErr = err;
      const isRetryable =
        !err.status ||
        err.status >= 500 ||
        err.status === 429 ||
        err.name === "AbortError" ||
        err.message === "fetch failed";

      if (!isRetryable || attempt === MAX_RETRIES) throw err;

      const retryAfterMs = parseRetryAfterMs(err);
      const backoff = Math.max(
        MIN_RETRY_DELAY_MS * attempt,
        DELAY_MS * attempt,
        retryAfterMs ?? 0,
      );

      if (err.status === 429 && backoff > 0) {
        setGlobalCooldown(backoff);
      }

      console.warn(`  Attempt ${attempt}/${MAX_RETRIES} failed (${err.message}). Retrying in ${backoff}ms...`);
      await sleep(backoff);
    }
  }
  throw lastErr;
}

async function runArtifactAudit(garmentUrl, modelUrl, resultUrl, garmentCategory, contextText) {
  const content = [{ type: "text", text: ARTIFACT_AUDIT_PROMPT }, { type: "text", text: contextText }];

  if (garmentCategory) {
    content.push({ type: "text", text: `Predicted target garment category: ${garmentCategory}` });
  }

  if (modelUrl) {
    content.push({ type: "text", text: "IMAGE 1: MODEL_ORIGINAL" });
    content.push({ type: "image_url", image_url: { url: modelUrl } });
    content.push({ type: "text", text: "IMAGE 2: TARGET_GARMENT" });
    content.push({ type: "image_url", image_url: { url: garmentUrl } });
    content.push({ type: "text", text: "IMAGE 3: GENERATED_RESULT" });
    content.push({ type: "image_url", image_url: { url: resultUrl } });
  } else {
    content.push({ type: "text", text: "IMAGE 1: TARGET_GARMENT" });
    content.push({ type: "image_url", image_url: { url: garmentUrl } });
    content.push({ type: "text", text: "IMAGE 2: GENERATED_RESULT" });
    content.push({ type: "image_url", image_url: { url: resultUrl } });
  }

  const payload = {
    model: MODEL,
    temperature: 0,
    max_completion_tokens: 800,
    top_p: 1,
    presence_penalty: 0,
    n: 1,
    response_format: AUDIT_RESPONSE_FORMAT,
    messages: [
      {
        role: "user",
        content,
      },
    ],
  };

  const resp = await postChatCompletions(payload);
  const raw = extractAssistantText(resp);
  const parsed = safeJsonParse(raw);
  const stopped = resp?.choices?.[0]?.finish_reason === "stop";
  const validated = parsed.ok && stopped ? validateArtifactAudit(parsed.json) : null;

  return {
    ok: Boolean(parsed.ok && validated?.ok),
    audit: validated?.ok ? validated.audit : null,
    raw_output_text: parsed.ok && validated?.ok ? null : raw,
    parse_error: !stopped ? `Artifact audit did not finish: ${resp?.choices?.[0]?.finish_reason ?? "missing response"}` : parsed.ok ? validated?.error ?? null : parsed.error,
    finish_reason: resp?.choices?.[0]?.finish_reason ?? null,
  };
}

async function evaluateFolder(folderName, folderContext) {
  if (!folderContext.ok) return { folder: folderName, ok: false, error: folderContext.error };
  const { garmentPath, modelPath, resultPath } = folderContext;
  if (!garmentPath || !modelPath || !resultPath) {
    return { folder: folderName, ok: false, error: "Missing required images: garment.*, model.*, and result.* are all needed for a complete assessment." };
  }
  const [garmentUrl, modelUrl, resultUrl] = await Promise.all([garmentPath, modelPath, resultPath].map(fileToDataUrl));
  const contextText = requestContext(folderContext);
  const payload = {
    model: MODEL, temperature: 0, max_completion_tokens: 2000,
    response_format: RATING_RESPONSE_FORMAT,
    messages: [{ role: "user", content: [
      { type: "text", text: PROMPT }, { type: "text", text: contextText },
      { type: "text", text: "IMAGE 1: TARGET_GARMENT" }, { type: "image_url", image_url: { url: garmentUrl } },
      { type: "text", text: "IMAGE 2: PERSON" }, { type: "image_url", image_url: { url: modelUrl } },
      { type: "text", text: "IMAGE 3: GENERATED_RESULT" }, { type: "image_url", image_url: { url: resultUrl } },
    ] }],
  };
  const response = await postChatCompletions(payload);
  const finishReason = response?.choices?.[0]?.finish_reason;
  const raw = extractAssistantText(response);
  const parsed = safeJsonParse(raw);
  const validated = parsed.ok && finishReason === "stop" ? validateAndNormalizeRating(parsed.json) : null;
  if (!validated?.ok) {
    return { folder: folderName, ok: false, error: finishReason !== "stop" ? "Assessment did not finish: " + (finishReason || "missing response") : validated?.error || parsed.error, raw_output_text: raw, finish_reason: finishReason };
  }
  let rating = validated.rating;
  let auditResult = null;
  if (shouldRunArtifactAudit(rating)) {
    try {
      auditResult = await runArtifactAudit(garmentUrl, modelUrl, resultUrl, rating.garment_category, contextText);
    } catch (error) {
      auditResult = { ok: false, parse_error: error.message };
    }
    if (!auditResult.ok) return {
      folder: folderName, ok: false, rating: null, preliminary_rating: rating,
      error: "Assessment incomplete: artifact audit failed. " + (auditResult.parse_error || "Invalid response"),
      artifact_audit_error: auditResult.parse_error,
      artifact_audit_raw_output: auditResult.raw_output_text ?? null,
      artifact_audit_finish_reason: auditResult.finish_reason ?? null,
    };
    rating = applyArtifactAuditToRating(rating, auditResult.audit);
  }
  return { folder: folderName, ok: true, rating, finish_reason: finishReason,
    artifact_audit: auditResult?.audit ?? null, artifact_audit_status: auditResult ? "completed" : "not_required" };
}

async function mapWithConcurrency(items, limit, worker) {
  const results = new Array(items.length);
  let nextIndex = 0;

  async function runWorker() {
    while (true) {
      const currentIndex = nextIndex;
      nextIndex++;

      if (currentIndex >= items.length) {
        return;
      }

      results[currentIndex] = await worker(items[currentIndex], currentIndex);
    }
  }

  const workers = Array.from({ length: Math.min(limit, items.length) }, () => runWorker());
  await Promise.all(workers);
  return results;
}

function describeFile(filePath) {
  if (!filePath) return null;
  return {
    name: path.basename(filePath),
    relative_path: projectRelative(filePath),
  };
}

function createPerFolderPayload(folderName, folderContext, record) {
  return {
    folder: folderName,
    timestamp: new Date().toISOString(),
    evaluation_mode: record.evaluation_mode ?? "llm",
    source_layout: folderContext.sourceLayout,
    source_folder: projectRelative(folderContext.folderPath),
    metadata: summarizeMetadata(folderContext.metadata),
    source_run: folderContext.sourceRun ?? null,
    preliminary_rating: record.preliminary_rating ?? null,
    metadata_error: folderContext.metadataError ?? null,
    files: {
      model: describeFile(folderContext.modelPath),
      garment: describeFile(folderContext.garmentPath),
      result: describeFile(folderContext.resultPath),
      metadata: folderContext.metadataPath ? projectRelative(folderContext.metadataPath) : null,
    },
    ok: record.ok,
    rating: record.rating ?? null,
    error: record.error ?? null,
    found: record.found ?? null,
    status: record.status ?? null,
    message: record.message ?? null,
    parse_error: record.parse_error ?? null,
    raw_output_text: record.raw_output_text ?? null,
    finish_reason: record.finish_reason ?? null,
    artifact_audit: record.artifact_audit ?? null,
    artifact_audit_status: record.artifact_audit_status ?? (record.artifact_audit_error ? "failed" : null),
    artifact_audit_error: record.artifact_audit_error ?? null,
    artifact_audit_raw_output: record.artifact_audit_raw_output ?? null,
    artifact_audit_finish_reason: record.artifact_audit_finish_reason ?? null,
    body: record.body ?? null,
  };
}

function describeSourceLayouts(layouts) {
  const uniqueLayouts = [...new Set(layouts.filter(Boolean))];
  if (uniqueLayouts.length === 0) return "unknown";
  if (uniqueLayouts.length === 1) return uniqueLayouts[0];
  return `mixed (${uniqueLayouts.join(", ")})`;
}

function collectSourceEntries(sourceDirs) {
  const entries = [];
  const visited = new Set();
  const sources = [];
  const expectations = [];
  const excluded = new Set([".git", "node_modules", "outputs", "garment", "model", "result"]);
  function visit(dir, sourceDir, sourceRun = null) {
    if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) return;
    const real = fs.realpathSync(dir);
    if (visited.has(real)) return;
    visited.add(real);
    const descriptor = readJsonFileSafe(path.join(dir, "source-run.json"));
    if (descriptor.ok) {
      sourceRun = descriptor.value;
      expectations.push(sourceRun);
    }
    const children = fs.readdirSync(dir, { withFileTypes: true });
    const nested = children.some(child => child.isDirectory() && ["garment", "model", "result"].includes(child.name));
    const flat = children.some(child => child.isFile() && /^(garment|model|result)\.(jpg|jpeg|png|webp|avif|gif)$/i.test(child.name));
    if (nested || flat || children.some(child => child.isFile() && child.name === "metadata.json")) {
      const metadata = readJsonFileSafe(path.join(dir, "metadata.json")).value;
      const runType = inferGarmentRunType({ ...metadata, folder: path.basename(dir), source_folder: dir });
      if (!sourceRun?.selected_categories?.length || sourceRun.selected_categories.includes(runType)) {
        entries.push({ folderName: path.basename(dir), folderPath: dir, sourceDir, sourceLayout: nested ? "test_results" : "flat", sourceRun });
      }
      return;
    }
    for (const child of children) if (child.isDirectory() && !excluded.has(child.name)) visit(path.join(dir, child.name), sourceDir, sourceRun);
  }
  for (const sourceDir of sourceDirs) {
    const start = entries.length;
    visit(sourceDir, sourceDir);
    if (entries.length > start) sources.push({ sourceDir, sourceLayout: describeSourceLayouts(entries.slice(start).map(entry => entry.sourceLayout)) });
  }
  entries.sort((a, b) => a.folderPath.localeCompare(b.folderPath, undefined, { numeric: true }));
  return { sources, entries, expectations };
}

function writeReviewBundle(reviewRoot, payload, folderContext) {
  return {
    bundleDir: null,
    files: {
      model: toReviewAssetPath(reviewRoot, folderContext.modelPath),
      garment: toReviewAssetPath(reviewRoot, folderContext.garmentPath),
      result: toReviewAssetPath(reviewRoot, folderContext.resultPath),
      metadata: toReviewAssetPath(reviewRoot, folderContext.metadataPath),
    },
  };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderHtmlList(items, emptyText) {
  if (!items || items.length === 0) {
    return `<p class="muted">${escapeHtml(emptyText)}</p>`;
  }
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function renderImageCard(label, relativePath, options = {}) {
  const variant = normalizeString(options.variant) || "standard";
  const description = normalizeString(options.description);
  if (!relativePath) {
    return `
      <div class="image-card image-card-${escapeHtml(variant)} missing">
        <div class="image-label">${escapeHtml(label)}</div>
        ${description ? `<div class="image-subtitle">${escapeHtml(description)}</div>` : ""}
        <div class="missing-text">Missing</div>
      </div>
    `;
  }

  const safeSrc = relativePath.split("/").map(encodeURIComponent).join("/");
  const safeLabel = escapeHtml(label);
  return `
    <div class="image-card image-card-${escapeHtml(variant)}">
      <div class="image-card-header">
        <div>
          <div class="image-label">${safeLabel}</div>
          ${description ? `<div class="image-subtitle">${escapeHtml(description)}</div>` : ""}
        </div>
      </div>
      <div class="image-frame">
        <img src="${escapeHtml(safeSrc)}" alt="${safeLabel}" decoding="async">
      </div>
    </div>
  `;
}

function renderMetaChips(entry) {
  const chips = [];
  if (entry.test_number !== null && entry.test_number !== undefined) {
    chips.push(`Test #${entry.test_number}`);
  }
  if (entry.gender) {
    chips.push(entry.gender);
  }
  if (entry.folder) {
    chips.push(`Folder: ${entry.folder}`);
  }

  if (entry.metadata?.quality_mode_selected) chips.push("Quality: " + entry.metadata.quality_mode_selected);
  if (entry.metadata?.flat_enabled !== undefined && entry.metadata.flat_enabled !== null) chips.push("Flat: " + entry.metadata.flat_enabled);
  if (entry.metadata?.generation_profile_requested) chips.push("Profile: " + entry.metadata.generation_profile_requested);
  if (entry.metadata?.steps_selected != null) chips.push("Steps: " + entry.metadata.steps_selected);
  if (entry.source_run?.run_id) chips.push("Run: " + entry.source_run.run_id);
  if (entry.source_run?.branch) chips.push("Branch: " + entry.source_run.branch);
  if (chips.length === 0) return "";
  return `<div class="meta-chips">${chips.map((item) => `<span class="meta-chip">${escapeHtml(item)}</span>`).join("")}</div>`;
}

function inferGarmentRunType(entry) {
  for (const value of [entry.garment_run_key, entry.garment_mode_requested]) {
    const normalized = normalizeString(value)?.toLowerCase();
    if (["lower", "upper", "full"].includes(normalized)) {
      return normalized;
    }
  }

  const fallbackText = [entry.test_id, entry.folder, entry.source_folder]
    .map((value) => normalizeString(value))
    .filter(Boolean)
    .join("/");
  const fallbackMatch = fallbackText.match(/(?:^|[_/\\-])(lower|upper|full)(?=$|[_/\\-])/i);
  return fallbackMatch ? fallbackMatch[1].toLowerCase() : "unknown";
}

function renderGenerationTitle(entry) {
  const garmentFilename = normalizeString(entry.garment_filename);
  const garmentName = garmentFilename
    ? path.parse(garmentFilename).name
    : normalizeString(entry.test_id) || normalizeString(entry.folder) || "Unknown garment";
  return `${garmentName} || Garment type: ${inferGarmentRunType(entry)}`;
}

function renderGalleryBoard(entry) {
  return `
    <div class="images images-gallery">
      ${renderImageCard("Person", entry.files.model, {
        variant: "gallery",
      })}
      ${renderImageCard("Garment", entry.files.garment, {
        variant: "gallery",
      })}
      ${renderImageCard("Output", entry.files.result, {
        variant: "gallery",
      })}
    </div>
  `;
}

function createReviewEntry(payload, bundle) {
  const rating = payload.rating;
  return {
    folder: payload.folder,
    metadata: payload.metadata,
    source_run: payload.source_run,
    test_number: payload.metadata?.test_number ?? null,
    test_id: payload.metadata?.test_id ?? payload.folder,
    gender: payload.metadata?.gender ?? null,
    garment_filename: payload.metadata?.garment_filename ?? null,
    garment_run_key: payload.metadata?.garment_run_key ?? null,
    garment_mode_requested: payload.metadata?.garment_mode_requested ?? null,
    selenium_status: payload.metadata?.status ?? null,
    evaluation_ok: payload.ok,
    evaluation_mode: payload.evaluation_mode ?? "llm",
    ai_successful: rating?.successful ?? null,
    quality_percent: rating?.quality_percent ?? null,
    garment_category: rating?.garment_category ?? null,
    garment_type: rating?.garment_type ?? null,
    intended_fit: rating?.intended_fit ?? null,
    silhouette_preserved: rating?.silhouette_preserved ?? null,
    labels: rating?.labels ?? null,
    notes: rating?.notes ?? ([payload.error, payload.message, payload.parse_error, payload.artifact_audit_error].filter(Boolean).join(" ") || null),
    critical_issues: rating?.critical_issues ?? [],
    minor_issues: rating?.minor_issues ?? [],
    positives: rating?.positives ?? [],
    source_folder: payload.source_folder,
    files: bundle.files,
  };
}

function buildReviewHtml(reviewEntries, summary, meta) {
  const isGalleryOnly = meta.reportMode === "gallery";
  const reportTitle = isGalleryOnly ? "Try-On Gallery Report" : "Try-On Review Report";
  const cards = reviewEntries
    .map((entry) => {
      const score = entry.quality_percent ?? (entry.evaluation_mode === "generation_failed" || entry.evaluation_mode === "comparison_only" ? "—" : "ERR");
      const aiStatus = ["generation_failed", "comparison_only"].includes(entry.evaluation_mode) ? "SKIPPED" : entry.ai_successful || "ERROR";
      const scoreClass =
        entry.quality_percent === null || entry.quality_percent === undefined
          ? "score-error"
          : aiStatus === "YES"
            ? "score-pass"
            : "score-fail";
      const seleniumStatus = normalizeString(entry.selenium_status)?.toUpperCase() || null;
      const galleryBadgeClass =
        seleniumStatus === "SUCCESS" ? "score-pass" : seleniumStatus === "FAILED" ? "score-fail" : "badge-neutral";
      const galleryBadges = seleniumStatus
        ? `<div class="badges"><span class="badge ${galleryBadgeClass}">Generation: ${escapeHtml(seleniumStatus)}</span></div>`
        : "";
      const reviewBadges = `
            <div class="badges">
              <span class="badge ${scoreClass}">Score: ${escapeHtml(score)}</span>
              <span class="badge ${aiStatus === "YES" ? "score-pass" : aiStatus === "NO" ? "score-fail" : "score-error"}">AI: ${escapeHtml(aiStatus)}</span>
            </div>`;
      const detailSections = isGalleryOnly
        ? ""
        : `
          <div class="details">
            <p><strong>Type:</strong> ${escapeHtml(entry.garment_type || "n/a")}</p>
            <p><strong>Category:</strong> ${escapeHtml(entry.garment_category || "n/a")}</p>
            <p><strong>Fit:</strong> ${escapeHtml(entry.intended_fit || "n/a")}</p>
            <p><strong>Silhouette:</strong> ${escapeHtml(entry.silhouette_preserved || "n/a")}</p>
            <p><strong>Labels:</strong> ${escapeHtml(
              entry.labels
                ? `structure ${entry.labels.garment_structure_error}, alignment ${entry.labels.construction_alignment_error}, fit ${entry.labels.fit_error}, artifact ${entry.labels.artifact_error}`
                : "n/a",
            )}</p>
            <p><strong>Notes:</strong> ${escapeHtml(entry.notes || "n/a")}</p>
          </div>

          <div class="lists">
            <section>
              <h3>Critical Issues</h3>
              ${renderHtmlList(entry.critical_issues, "None")}
            </section>
            <section>
              <h3>Minor Issues</h3>
              ${renderHtmlList(entry.minor_issues, "None")}
            </section>
            <section>
              <h3>Positives</h3>
              ${renderHtmlList(entry.positives, "None")}
            </section>
          </div>`;

      return `
        <article class="card ${isGalleryOnly ? "card-gallery" : "card-review"}">
          <div class="card-top">
            <div class="card-heading">
              <div class="card-kicker">${isGalleryOnly ? "Result Sheet" : "Review Entry"}</div>
              <h2>${escapeHtml(renderGenerationTitle(entry))}</h2>
              ${renderMetaChips(entry)}
            </div>
            ${isGalleryOnly ? galleryBadges : galleryBadges + reviewBadges}
          </div>

          ${isGalleryOnly
            ? renderGalleryBoard(entry)
            : `<div class="images">
            ${renderImageCard("Model", entry.files.model)}
            ${renderImageCard("Garment", entry.files.garment)}
            ${renderImageCard("Result", entry.files.result)}
          </div>`}
          ${isGalleryOnly && seleniumStatus === "FAILED" ? `<p class="muted">${escapeHtml(entry.notes || "Generation failed.")}</p>` : ""}
          ${detailSections}
        </article>
      `;
    })
    .join("\n");

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(reportTitle)}</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #070a0f;
      --panel: #0e141c;
      --card: #141b24;
      --ink: #edf3f8;
      --muted: #9aa8b7;
      --line: #2b3745;
      --pass: #198754;
      --fail: #c43d4b;
      --error: #7656a8;
      --accent: #55d6be;
      --accent-soft: #173833;
      --shadow: 0 20px 48px rgba(0, 0, 0, 0.38);
    }
    * { box-sizing: border-box; }
    html {
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }
    body {
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(85, 214, 190, 0.14), transparent 28%),
        linear-gradient(180deg, #0c1219 0%, var(--bg) 100%);
    }
    main {
      max-width: 1680px;
      margin: 0 auto;
      padding: 28px 18px 40px;
    }
    h1, h2, h3 { margin: 0; }
    .summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }
    .summary-card {
      background: rgba(20, 27, 36, 0.92);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 18px 18px 16px;
      box-shadow: 0 10px 24px rgba(0, 0, 0, 0.24);
    }
    .summary-card strong {
      display: block;
      font-size: 2rem;
      line-height: 1;
      margin-bottom: 6px;
    }
    .summary-card span {
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.4;
    }
    .cards {
      display: grid;
      gap: 20px;
    }
    .card {
      background: rgba(20, 27, 36, 0.97);
      border: 1px solid var(--line);
      border-radius: 28px;
      padding: 24px;
      box-shadow: var(--shadow);
      break-inside: avoid;
      page-break-inside: avoid;
    }
    .card-top {
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: start;
      margin-bottom: 18px;
    }
    .card-heading {
      max-width: 820px;
    }
    .card-kicker {
      margin-bottom: 8px;
      font-family: "Aptos", "Segoe UI", sans-serif;
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--accent);
    }
    .card h2 {
      font-size: clamp(1.5rem, 3vw, 2.15rem);
      line-height: 1.08;
      word-break: break-word;
    }
    .meta {
      margin-top: 6px;
      color: var(--muted);
      font-size: 0.95rem;
    }
    .meta-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }
    .meta-chip {
      display: inline-flex;
      align-items: center;
      min-height: 30px;
      padding: 5px 12px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: var(--accent-soft);
      font-family: "Aptos", "Segoe UI", sans-serif;
      font-size: 0.84rem;
      color: var(--ink);
    }
    .badges {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: end;
    }
    .badge {
      border-radius: 999px;
      padding: 8px 13px;
      font-family: "Aptos", "Segoe UI", sans-serif;
      font-size: 0.88rem;
      color: white;
      font-weight: 600;
      white-space: nowrap;
    }
    .badge-neutral { background: #4b5968; }
    .score-pass { background: var(--pass); }
    .score-fail { background: var(--fail); }
    .score-error { background: var(--error); }
    .images {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
      margin-bottom: 18px;
      align-items: start;
    }
    .images-gallery {
      margin-bottom: 0;
      align-items: stretch;
    }
    .image-card {
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 14px;
      background: var(--panel);
      min-height: 100%;
      display: flex;
      flex-direction: column;
    }
    .image-card-header {
      display: flex;
      gap: 12px;
      align-items: start;
      margin-bottom: 12px;
    }
    .image-frame {
      display: block;
      width: 100%;
      flex: 1;
    }
    .image-card img {
      width: 100%;
      height: 480px;
      object-fit: contain;
      border-radius: 14px;
      background:
        radial-gradient(circle at top, rgba(85, 214, 190, 0.08), transparent 28%),
        linear-gradient(180deg, #101823, #090d13);
    }
    .card-gallery .image-card img {
      height: min(70vh, 900px);
    }
    .image-card.missing {
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      min-height: 220px;
    }
    .image-label {
      font-family: "Aptos", "Segoe UI", sans-serif;
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
    }
    .image-subtitle {
      margin-top: 6px;
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.35;
    }
    .missing-text, .muted {
      color: var(--muted);
    }
    .details {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 8px 14px;
      margin-bottom: 18px;
    }
    .details p {
      margin: 0;
      line-height: 1.45;
    }
    .lists {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin-bottom: 12px;
    }
    .lists section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
    }
    .lists h3 {
      font-size: 1rem;
      margin-bottom: 8px;
    }
    .lists ul {
      margin: 0;
      padding-left: 18px;
      line-height: 1.45;
    }
    a {
      color: var(--accent);
      text-decoration-thickness: 1px;
      text-underline-offset: 3px;
    }
    @page {
      size: A4 portrait;
      margin: 8mm;
    }
    @media print {
      body {
        background: white;
        color: #1d1a16;
      }
      main {
        max-width: none;
        padding: 0;
      }
      .summary-card,
      .card {
        box-shadow: none;
      }
      .summary {
        display: none;
      }
      .cards {
        gap: 0;
      }
      .card {
        padding: 4mm 0 0;
        border-radius: 0;
        border: 0;
        background: white;
        color: #1d1a16;
      }
      .card-gallery {
        min-height: 272mm;
        page-break-after: always;
        break-after: page;
        break-inside: avoid;
        display: grid;
        grid-template-rows: auto 1fr;
      }
      .card-gallery:last-child { page-break-after: auto; break-after: auto; }
      .card-top {
        margin-bottom: 4mm;
      }
      .badges {
        justify-content: start;
      }
      .images-gallery {
        gap: 4mm;
        min-height: 0;
      }
      .image-card {
        padding: 2mm;
        border-radius: 8px;
        border: 1px solid #d9d0c3;
        background: white;
        color: #1d1a16;
      }
      .image-card-header {
        margin-bottom: 2mm;
      }
      .image-card img {
        border-radius: 4px;
        background: white;
      }
      .meta-chip {
        border-color: #d8cbba;
        background: #f3eadf;
        color: #44382b;
      }
      .image-label,
      .image-subtitle,
      .missing-text,
      .muted {
        color: #6a6257;
      }
      .lists section {
        border-color: #d8cbba;
        background: white;
      }
      a { color: #7a3e07; }
      .card-gallery .image-card img {
        height: 234mm;
      }
    }
    @media (max-width: 720px) {
      main { padding: 16px 12px 26px; }
      .card { padding: 16px; }
      .card-top { flex-direction: column; }
      .badges { justify-content: start; }
      .images { grid-template-columns: 1fr; }
      .image-card img { height: 320px; }
      .card-gallery .image-card img { height: 360px; }
    }
  </style>
</head>
<body>
  <main>
    <section class="summary">
      ${isGalleryOnly
        ? `
      <div class="summary-card"><strong>${escapeHtml(summary.total)}</strong><span>Total results</span></div>
      <div class="summary-card"><strong>${escapeHtml(summary.generation_successful || 0)}</strong><span>Successful generations</span></div>
      <div class="summary-card"><strong>${escapeHtml(summary.generation_failed || 0)}</strong><span>Failed generations</span></div>
      <div class="summary-card"><strong>${escapeHtml(summary.generation_unknown || 0)}</strong><span>Unknown status</span></div>`
        : `
      <div class="summary-card"><strong>${escapeHtml(summary.total)}</strong><span>Total cases</span></div>
      <div class="summary-card"><strong>${escapeHtml(summary.successful)}</strong><span>AI pass</span></div>
      <div class="summary-card"><strong>${escapeHtml(summary.failed)}</strong><span>AI fail</span></div>
      <div class="summary-card"><strong>${escapeHtml(summary.comparison_only || 0)}</strong><span>Comparison only</span></div>
      <div class="summary-card"><strong>${escapeHtml(summary.errors)}</strong><span>Assessment errors</span></div>
      <div class="summary-card"><strong>${escapeHtml(summary.generation_failed)}</strong><span>Generation failures (skipped)</span></div>`}
    </section>

    <p class="muted">${escapeHtml(meta.generatedAt)}${isGalleryOnly ? " · Generation gallery" : COMPARISON_ONLY_MODE ? " · Comparison only: AI not run" : ` · Evaluator: ${escapeHtml(MODEL)} · Pass: ${escapeHtml(SCORE_POLICY.passScore)}% · Maximum minor labels: ${escapeHtml(SCORE_POLICY.maxMinorLabels)}`}</p>
    ${summary.source_errors?.length ? `<section><h2>Source errors</h2>${renderHtmlList(summary.source_errors, "")}</section>` : ""}
    <section class="cards">
      ${cards}
    </section>
  </main>
</body>
</html>`;
}

function writeReviewIndex(reviewRoot, reviewEntries, summary, sourceDirs, sourceLayout) {
  const generatedAt = new Date().toISOString();
  const sourceDirLabel = sourceDirs
    .map((dir) => projectRelative(dir) || dir)
    .join(", ");

  const html = buildReviewHtml(reviewEntries, summary, {
    generatedAt,
    sourceDir: sourceDirLabel,
    sourceLayout,
    reportMode: REPORT_MODE,
  });
  fs.writeFileSync(path.join(reviewRoot, "index.html"), html, "utf8");
}

async function main() {
  if (!["gallery", "review", "comparison"].includes(REPORT_MODE)) throw new Error("ANALYSIS_REPORT_MODE must be gallery, review, or comparison.");
  const sourceDirs = resolveSourceDirs();
  const { entries, expectations } = collectSourceEntries(sourceDirs);
  if (!entries.length) {
    console.error("No test cases found. Searched: " + sourceDirs.join(", "));
    return { exitCode: 1, summary: null };
  }
  const reviewRoot = ensureDir(OUTPUTS_DIR);
  const sourceLayout = describeSourceLayouts(entries.map(entry => entry.sourceLayout));
  console.log("Report mode: " + REPORT_MODE.toUpperCase() + "; model: " + MODEL + "; cases: " + entries.length);
  const sourceErrors = [];
  for (const expected of expectations) {
    for (const category of expected.selected_categories || []) {
      if (!entries.some(entry => entry.sourceRun === expected && inferGarmentRunType({ ...readJsonFileSafe(path.join(entry.folderPath, "metadata.json")).value, folder: entry.folderName, source_folder: entry.folderPath }) === category)) {
        sourceErrors.push(`Artifact ${expected.artifact_name || expected.artifact_id} from run ${expected.run_id} contains no ${category} test cases.`);
      }
    }
  }
  for (const error of sourceErrors) console.error(error);
  const summary = {
    total: 0, successful: 0, failed: 0, comparison_only: 0, errors: sourceErrors.length,
    generation_successful: 0, generation_failed: 0, generation_unknown: 0,
    by_category: {}, silhouette_stats: { YES: 0, PARTIAL: 0, NO: 0 },
    by_fit: Object.fromEntries(["tight", "regular", "loose", "oversized"].map(key => [key, { total: 0, pass: 0 }])),
    source_dirs: sourceDirs.map(projectRelative), source_layout: sourceLayout, source_errors: sourceErrors,
  };
  const evaluations = await mapWithConcurrency(entries, CONCURRENCY, async entry => {
    const context = collectFolderAssets(entry.folderName, entry.folderPath, entry.sourceLayout);
    context.sourceRun = entry.sourceRun;
    let record;
    if (context.metadata?.status === "failed") {
      record = { ok: true, rating: null, evaluation_mode: "generation_failed", message: context.metadata.error || "Generation failed before a result was saved." };
    } else if (GALLERY_ONLY_MODE || COMPARISON_ONLY_MODE) {
      record = { ok: context.ok, rating: null, evaluation_mode: GALLERY_ONLY_MODE ? "gallery_only" : "comparison_only", error: context.error, message: "AI evaluation intentionally skipped." };
    } else if (!HAS_OPENAI_API_KEY) {
      record = { ok: false, error: "OPENAI_API_KEY is missing. Set it in .env locally or in GitHub Actions repository secrets." };
    } else {
      try { record = await evaluateFolder(entry.folderName, context); }
      catch (error) { record = { ok: false, error: error.message, status: error.status ?? null }; }
    }
    record.folder = entry.folderName;
    console.log(entry.folderName + ": " + (record.evaluation_mode === "generation_failed" ? "GENERATION FAILED (skipped)" : record.ok ? record.rating?.successful || "SKIPPED" : "ASSESSMENT ERROR: " + record.error));
    const payload = createPerFolderPayload(entry.folderName, context, record);
    return { record, payload, bundle: writeReviewBundle(reviewRoot, payload, context) };
  });
  const reviewEntries = [];
  for (const { record, payload, bundle } of evaluations) {
    summary.total++;
    if (payload.metadata?.status === "success") summary.generation_successful++;
    else if (payload.metadata?.status === "failed") summary.generation_failed++;
    else summary.generation_unknown++;
    if (!record.ok) summary.errors++;
    else if (record.evaluation_mode === "comparison_only") summary.comparison_only++;
    else if (record.rating) {
      const rating = record.rating;
      const passed = rating.successful === "YES";
      if (passed) summary.successful++; else summary.failed++;
      const category = summary.by_category[rating.garment_category] ||= { total: 0, pass: 0, fail: 0 };
      category.total++; if (passed) category.pass++; else category.fail++;
      summary.silhouette_stats[rating.silhouette_preserved]++;
      if (rating.intended_fit) { summary.by_fit[rating.intended_fit].total++; if (passed) summary.by_fit[rating.intended_fit].pass++; }
    }
    reviewEntries.push(createReviewEntry(payload, bundle));
  }
  writeReviewIndex(reviewRoot, reviewEntries, summary, sourceDirs, sourceLayout);
  const report = {
    schema_version: 2, generated_at: new Date().toISOString(), report_mode: REPORT_MODE,
    evaluator_model: MODEL, scoring_policy: SCORE_POLICY, summary,
    results: evaluations.map(item => item.payload),
  };
  fs.writeFileSync(path.join(reviewRoot, "analysis.json"), JSON.stringify(report, null, 2));
  console.log("AI pass: " + summary.successful + "; AI fail: " + summary.failed + "; generation failures: " + summary.generation_failed + "; assessment errors: " + summary.errors);
  console.log("Review report: " + path.join(reviewRoot, "index.html"));
  const noJudgments = !GALLERY_ONLY_MODE && !COMPARISON_ONLY_MODE && summary.successful + summary.failed === 0;
  if (noJudgments && !summary.errors) console.error("No generated results were available for AI assessment.");
  return { exitCode: summary.errors || noJudgments ? 1 : 0, summary, report };
}

export { main, collectSourceEntries, collectFolderAssets, resolveSourceDirs, renderImageCard, evaluateFolder, buildReviewHtml };

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().then(result => { process.exitCode = result.exitCode; }).catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
