import "dotenv/config";
import fs from "node:fs";
import path from "node:path";

const OPENAI_API_KEY = String(process.env.OPENAI_API_KEY || "").trim();
const MODEL = String(process.env.OPENAI_MODEL || "gpt-4.1").trim();
const ENDPOINT = "https://api.openai.com/v1/chat/completions";
const TIMEOUT_MS = Number(process.env.OPENAI_TIMEOUT_MS || 180000);
const DELAY_MS = Number(process.env.OPENAI_DELAY_MS || 2000);
const MAX_RETRIES = Number(process.env.OPENAI_MAX_RETRIES || 3);
const CONCURRENCY = Math.max(1, Number(process.env.OPENAI_CONCURRENCY || 4));
const MIN_RETRY_DELAY_MS = Math.max(250, Number(process.env.OPENAI_MIN_RETRY_DELAY_MS || 1000));
const RATE_LIMIT_JITTER_MS = Math.max(0, Number(process.env.OPENAI_RATE_LIMIT_JITTER_MS || 250));
const INCLUDE_MODEL_IN_MAIN = /^(1|true|yes)$/i.test(String(process.env.ANALYZE_INCLUDE_MODEL_IN_MAIN || "1").trim());
const ENABLE_ARTIFACT_AUDIT = /^(1|true|yes)$/i.test(String(process.env.ANALYZE_ENABLE_ARTIFACT_AUDIT || "").trim());
const OUTPUTS_DIR = path.resolve(process.env.ANALYSIS_OUTPUT_DIR || "outputs");
const REVIEW_DIR_NAME = String(process.env.ANALYSIS_REVIEW_DIR || "review").trim() || "review";
const IMAGE_EXTENSIONS = new Set([".jpg", ".jpeg", ".png", ".webp", ".avif"]);

if (!OPENAI_API_KEY) {
  throw new Error("Missing OPENAI_API_KEY.");
}

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
- If TARGET_GARMENT is tucked in, or clearly meant to be tucked in, GENERATED_RESULT may also reveal or synthesize the upper part of the bottoms that was hidden in PERSON.
- A newly visible waistband, top of pants, top of skirt, or top of shorts caused by tucking is acceptable if it looks plausible, consistent with the rest of the bottoms, and visually fitting.
- Because that upper-bottom area may have been hidden in PERSON, do NOT require an exact reconstruction of the original waistband or top edge.
- Small differences in the top seam, waistband shape, gathers, folds, or upper-bottom contour are acceptable if the result still looks natural and coherent overall.
- Only treat that newly generated upper-bottom area as damage if it looks malformed, mismatched, corrupted, or like an invented extra layer.
- If the transferred garment is longer and naturally covers some underlying clothing, that is fine.

3) No unreasonable additions
- Do not allow random added layers, extra collars, ghost garments, leftover old clothing fragments, or invented details that are not supported by either TARGET_GARMENT or PERSON.
- Small plausible generation variation is acceptable.
- Clearly invented structure is not acceptable.

4) Artifact check
- Look for neck damage, merged hair, leftover collars or hoods, warped boundaries, ghosting, broken body parts, and damaged non-target clothing.
- Artifacts that clearly damage the person, the garment, or other visible clothing are MAJOR issues.
- Use MINOR only when the artifact is clearly noticeable but still limited in scope.
- Tiny edge noise, slight boundary wobble, mild blur, or very small leftover traces that a normal shopper would likely ignore should be NONE, not MINOR.
- Smaller warping or mild resolution loss can be MINOR if it is noticeable enough to reduce trust.

Category focus:
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

Scoring, mechanical fixed penalties:
Start score = 100
Subtract:
- garment_structure_error: MINOR -20, MAJOR -60
- construction_alignment_error: MINOR -15, MAJOR -40
- fit_error: MINOR -10, MAJOR -30
- artifact_error: MINOR -5, MAJOR -40
Clamp score to 0..100.

Decision rule:
- YES if score >= 75 AND garment_structure_error != MAJOR AND artifact_error != MAJOR
- Otherwise NO

Output requirements:
Return ONLY valid JSON, no markdown and no commentary, exactly in this schema:
{
  "successful": "YES" | "NO",
  "quality_percent": number,
  "garment_type": string,
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

Focus especially on:
- neck and shoulder leftovers from the original clothing: old collars, hoods, padded neck shapes, scarf-like wraps, masks, or fragments that clearly do not belong to TARGET_GARMENT
- non-target clothing damage: especially bottoms, skirts, pants, shorts, leggings, shoes, or socks that were recolored, changed, warped, erased, or partially replaced even though the try-on was only supposed to change another garment
- added extra lower-body garments or layers, such as invented shorts, skirts, leggings, or overlays that were not present in MODEL_ORIGINAL and are not part of TARGET_GARMENT
- obvious merged boundaries, ghost remnants, or corrupted clothing/body regions
- BUT if MODEL_ORIGINAL had a turtleneck, high collar, or other neck coverage, a newly visible or newly synthesized neck can be acceptable and should be judged for natural appearance rather than treated as automatic leftover clothing
- BUT if TARGET_GARMENT is tucked in, a newly visible or newly synthesized waistband or upper-bottom area can be acceptable and should be judged for plausibility rather than treated as automatic damage

Rules:
- Only set artifact_present to "YES" when the artifact is clear enough that a normal reviewer would notice it and care
- Do not flag tiny, ambiguous, or low-impact irregularities such as slight edge roughness, tiny neck shading oddities, mild blur, or small leftover traces that do not materially hurt trust
- Use artifact_severity = "MINOR" only for localized, noticeable issues that do not materially damage the person, the transferred garment, or non-target clothing
- If a large or obvious leftover-clothing artifact is clearly visible without reasonable doubt, artifact_severity must be "MAJOR"
- If visible non-target bottoms are recolored, changed, replaced, or corrupted relative to MODEL_ORIGINAL, artifact_severity should usually be "MAJOR", except for a plausible newly visible upper-bottom area caused by a tucked-in target garment
- If a new lower-body garment or extra layer appears in GENERATED_RESULT that was not present in MODEL_ORIGINAL and is not the target garment, artifact_severity should usually be "MAJOR"
- If the neck or shoulder area clearly contains remnants of the original outfit that are not part of TARGET_GARMENT, artifact_severity should usually be "MAJOR"
- If MODEL_ORIGINAL hid the neck with a turtleneck, high collar, scarf, or similar coverage, do NOT treat a clean generated neck as a leftover artifact by itself
- In those neck-covered cases, judge the newly visible neck by whether it looks natural in anatomy, skin tone, edge blending, and lighting; flag it only if it looks like actual leftover clothing or clearly unnatural synthetic anatomy
- If something could plausibly be normal shadow, fold, drape, or natural occlusion, do NOT call it MAJOR
- Never return a perfect clean result if a clear artifact or collateral damage exists
- Do NOT treat the original garment disappearing inside the replaced target area as damage; that replacement is expected
- When MODEL_ORIGINAL is available, non-target garments such as bottoms and shoes should remain the same in GENERATED_RESULT unless naturally covered by the target garment
- If TARGET_GARMENT is tucked in, do NOT treat a newly visible or synthesized waistband, top of pants, top of skirt, or top of shorts as damage by itself
- In tucked-in cases, judge that upper-bottom area by whether it looks plausible and consistent with the visible bottoms; do NOT require an exact reconstruction of the hidden original upper-bottom area
- Minor differences in waistband curve, top edge shape, folds, gathers, or upper-bottom contour should usually be NONE or at most MINOR if the area still looks natural overall
- Flag the tucked upper-bottom area only if it is clearly malformed, detached, impossible-looking, badly blended, or appears like an extra garment
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


const ALLOWED_CATEGORIES = new Set(["top", "pants", "dress", "skirt", "outerwear", "other"]);
const ALLOWED_FITS = new Set(["tight", "regular", "loose", "oversized"]);
const ALLOWED_SILHOUETTES = new Set(["YES", "PARTIAL", "NO"]);
const ALLOWED_SEVERITIES = new Set(["NONE", "MINOR", "MAJOR"]);
const ALLOWED_YES_NO = new Set(["YES", "NO"]);
const LABEL_KEYS = [
  "garment_structure_error",
  "construction_alignment_error",
  "fit_error",
  "artifact_error",
  "silhouette_error",
];
const SCORE_PENALTIES = {
  garment_structure_error: { NONE: 0, MINOR: 20, MAJOR: 60 },
  construction_alignment_error: { NONE: 0, MINOR: 15, MAJOR: 40 },
  fit_error: { NONE: 0, MINOR: 10, MAJOR: 30 },
  artifact_error: { NONE: 0, MINOR: 5, MAJOR: 40 },
  silhouette_error: { NONE: 0, MINOR: 0, MAJOR: 0 },
};
const PASS_SCORE_THRESHOLD = 75;
const ARTIFACT_PATTERNS = [
  /artifact/i,
  /leftover/i,
  /remnant/i,
  /residual/i,
  /mask/i,
  /ghost/i,
  /merged hair/i,
  /broken boundar/i,
  /old clothing/i,
  /damaged neck/i,
  /neck.*(artifact|leftover|remnant|residual|hood|old)/i,
  /(hood|collar).*(artifact|leftover|remnant|residual|old)/i,
  /(damaged|warped|melted|broken|merged).*(hair|skin|hand|face|arm|body|neck)/i,
  /(bottom|pants|skirt|shorts|shoes).*(damaged|recolored|warped|erased|changed|replaced)/i,
  /(shorts|skirt|leggings|pants).*(added|invented|new|extra)/i,
  /added.*(shorts|skirt|leggings|pants)/i,
  /extra.*(shorts|skirt|leggings|pants)/i,
];
const MAJOR_ARTIFACT_PATTERNS = [
  /large.*artifact/i,
  /obvious.*artifact/i,
  /major.*artifact/i,
  /obvious.*damage/i,
  /clearly damaged/i,
  /damaged neck/i,
  /neck.*(leftover|remnant|residual|hood|old)/i,
  /(hood|collar).*(leftover|remnant|residual|old)/i,
  /(damaged|warped|melted|broken|merged).*(hair|skin|hand|face|arm|body|neck)/i,
  /(bottom|pants|skirt|shorts|shoes).*(damaged|recolored|warped|erased|changed|replaced)/i,
  /(shorts|skirt|leggings|pants).*(added|invented|new|extra)/i,
  /added.*(shorts|skirt|leggings|pants)/i,
  /extra.*(shorts|skirt|leggings|pants)/i,
  /ghost garment/i,
  /broken boundar/i,
];
const COVERED_NECK_SYNTHESIS_PATTERNS = [
  /(neck|upper chest).*(newly visible|revealed|shown|synthesized|generated).*(turtleneck|high neck|high collar|covered|obscured|hidden)/i,
  /(turtleneck|high neck|high collar|covered neck|hidden neck).*(neck|upper chest).*(newly visible|revealed|shown|synthesized|generated)/i,
  /(natural|plausible|clean|smooth).*(generated|synthesized).*(neck|upper chest)/i,
];
const TUCKED_UPPER_BOTTOM_PATTERNS = [
  /(waistband|top of pants|top of skirt|top of shorts|upper bottoms?|upper (pants|shorts|skirt) area).*(newly visible|revealed|shown|synthesized|generated|tuck|tucked)/i,
  /(tuck|tucked|tucked-in).*(waistband|top of pants|top of skirt|top of shorts|upper bottoms?|upper (pants|shorts|skirt) area)/i,
  /(pants|shorts|skirt).*(partially replaced at the top|replaced at the top|distorted at the top|warped at the top)/i,
  /upper (pants|shorts|skirt) area inconsistent/i,
  /tucked-in effect.*(implausible|inconsistent|corrupted)/i,
  /(waistband|top of pants|top of shorts|top of skirt).*(warped|distorted|inconsistent|corrupted|implausible)/i,
];
const LOW_IMPACT_ARTIFACT_PATTERNS = [
  /(tiny|small|slight|subtle|faint|minor|localized|barely noticeable).*(artifact|leftover|remnant|trace|blur|boundary|warp|roughness)/i,
  /(artifact|leftover|remnant|trace|blur|boundary|warp|roughness).*(tiny|small|slight|subtle|faint|minor|localized|barely noticeable)/i,
  /mild blur/i,
  /slight edge roughness/i,
  /slight boundary wobble/i,
  /tiny neck shading oddit/i,
  ...COVERED_NECK_SYNTHESIS_PATTERNS,
  ...TUCKED_UPPER_BOTTOM_PATTERNS,
  /(pants|skirt|shorts|bottoms).*(newly visible|revealed|shown).*(because|due to).*(tuck|tucked)/i,
];
const STRUCTURE_MAJOR_PATTERNS = [
  /shorts?\s+are\s+visible\s+instead\s+of\s+expected\s+pants/i,
  /shorts?\s+instead\s+of\s+pants/i,
  /pants\s+instead\s+of\s+shorts/i,
  /added.*shorts/i,
  /invented.*shorts/i,
  /extra.*lower-body garment/i,
  /wrong garment type/i,
  /different garment type/i,
  /missing visible buttons?/i,
  /buttons?\s+are\s+missing/i,
  /closure.*missing/i,
  /zipper.*missing/i,
];
const SILHOUETTE_MAJOR_PATTERNS = [
  /garment appears shorter/i,
  /garment is shorter/i,
  /too short/i,
  /wrong length/i,
  /length.*altered/i,
  /crop level/i,
];
const FIT_MAJOR_PATTERNS = [/too tight/i, /too loose/i, /wrong tightness/i];
const TOLERABLE_ISSUE_PATTERNS = [
  /pose may affect/i,
  /lighting may affect/i,
  /body shape may affect/i,
  /gravity may affect/i,
  /normal fabric drape/i,
  /slightly narrower on body than flatlay/i,
  ...COVERED_NECK_SYNTHESIS_PATTERNS,
  ...TUCKED_UPPER_BOTTOM_PATTERNS,
  /(pants|skirt|shorts|bottoms).*(newly visible|revealed|shown).*(because|due to).*(tuck|tucked)/i,
];
const CLEAN_ARTIFACT_PATTERNS = [
  /no artifacts?/i,
  /no visible artifacts?/i,
  /no person damage/i,
  /no damage to the person/i,
  /person remains intact/i,
  /(shorts|pants|skirt|bottoms|accessories|shoes).*(remain|remains) unchanged/i,
  /realistic and trustworthy/i,
  /result is realistic/i,
  /looks realistic/i,
  /trustworthy/i,
  /no artifacts or person damage/i,
];
let globalCooldownUntil = 0;

function normalizeString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function normalizeOptionalEnum(value, allowedSet) {
  const normalized = normalizeString(value);
  if (!normalized) return null;
  return allowedSet.has(normalized) ? normalized : null;
}

function normalizeGarmentType(value) {
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) {
    return value
      .map((item) => normalizeString(item))
      .filter(Boolean)
      .join("; ")
      .slice(0, 160);
  }
  return "";
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

function listSubfoldersSorted(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }));
}

function resolveSourceDir() {
  const envPath = normalizeString(process.env.ANALYZE_SOURCE_DIR);
  if (envPath) return path.resolve(envPath);

  const candidates = [path.resolve("test_results"), path.resolve("images")];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isDirectory()) {
      return candidate;
    }
  }

  return candidates[0];
}

function detectSourceLayout(sourceDir, folders) {
  for (const folderName of folders) {
    const folderPath = path.join(sourceDir, folderName);
    if (!fs.existsSync(folderPath) || !fs.statSync(folderPath).isDirectory()) {
      continue;
    }

    const hasNestedAssets =
      fs.existsSync(path.join(folderPath, "garment")) ||
      fs.existsSync(path.join(folderPath, "model")) ||
      fs.existsSync(path.join(folderPath, "result"));

    return hasNestedAssets ? "test_results" : "flat";
  }

  return "flat";
}

function isSupportedImage(filename) {
  return IMAGE_EXTENSIONS.has(path.extname(filename).toLowerCase());
}

function guessMimeType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".png") return "image/png";
  if (ext === ".webp") return "image/webp";
  if (ext === ".avif") return "image/avif";
  return "application/octet-stream";
}

function fileToDataUrl(filePath) {
  const mimeType = guessMimeType(filePath);
  const b64 = fs.readFileSync(filePath, { encoding: "base64" });
  return `data:${mimeType};base64,${b64}`;
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
  const metadataPath = sourceLayout === "test_results" ? path.join(folderPath, "metadata.json") : null;
  const metadata = readJsonFileSafe(metadataPath);
  const errors = [garment.error, model.error, result.error].filter(Boolean);

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

function normalizeStringList(value, maxItems) {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => normalizeString(item))
    .filter(Boolean)
    .slice(0, maxItems);
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function severityRank(value) {
  if (value === "MAJOR") return 2;
  if (value === "MINOR") return 1;
  return 0;
}

function maxSeverity(a, b) {
  return severityRank(b) > severityRank(a) ? b : a;
}

function matchesAnyPattern(text, patterns) {
  return patterns.some((pattern) => pattern.test(text));
}

function sanitizeIssueLists(rating) {
  if (!rating) return rating;

  const shouldKeep = (issue) => {
    const text = normalizeString(issue);
    if (!text) return false;
    return !matchesAnyPattern(text, TOLERABLE_ISSUE_PATTERNS);
  };

  return {
    ...rating,
    critical_issues: rating.critical_issues.filter(shouldKeep),
    minor_issues: rating.minor_issues.filter(shouldKeep),
  };
}

function applyIssueConsistencyGuards(rating) {
  if (!rating) return rating;

  const criticalText = rating.critical_issues.join(" ");
  const minorText = rating.minor_issues.join(" ");
  const notesText = normalizeString(rating.notes);
  const allText = `${criticalText}\n${minorText}\n${notesText}`;
  const nextLabels = { ...rating.labels };
  const artifactTexts = [...rating.critical_issues, ...rating.minor_issues, notesText]
    .map(normalizeString)
    .filter(Boolean);
  const hasIndependentMajorArtifactSignal = artifactTexts.some((text) =>
    matchesAnyPattern(text, MAJOR_ARTIFACT_PATTERNS) &&
    !matchesAnyPattern(text, COVERED_NECK_SYNTHESIS_PATTERNS) &&
    !matchesAnyPattern(text, TUCKED_UPPER_BOTTOM_PATTERNS),
  );
  const hasActionableArtifactSignal = artifactTexts.some((text) =>
    matchesAnyPattern(text, ARTIFACT_PATTERNS) &&
    !matchesAnyPattern(text, LOW_IMPACT_ARTIFACT_PATTERNS),
  );

  if (hasIndependentMajorArtifactSignal) {
    nextLabels.artifact_error = maxSeverity(nextLabels.artifact_error, "MAJOR");
  } else if (
    hasActionableArtifactSignal ||
    (matchesAnyPattern(allText, ARTIFACT_PATTERNS) && nextLabels.artifact_error !== "NONE")
  ) {
    nextLabels.artifact_error = maxSeverity(nextLabels.artifact_error, "MINOR");
  }

  if (matchesAnyPattern(criticalText, STRUCTURE_MAJOR_PATTERNS)) {
    nextLabels.garment_structure_error = maxSeverity(nextLabels.garment_structure_error, "MAJOR");
  }

  if (matchesAnyPattern(criticalText, SILHOUETTE_MAJOR_PATTERNS)) {
    nextLabels.silhouette_error = maxSeverity(nextLabels.silhouette_error, "MAJOR");
  }

  if (matchesAnyPattern(criticalText, FIT_MAJOR_PATTERNS)) {
    nextLabels.fit_error = maxSeverity(nextLabels.fit_error, "MAJOR");
  }

  return {
    ...rating,
    labels: nextLabels,
  };
}

function relaxContextualArtifactOvercalls(rating) {
  if (!rating || rating.labels?.artifact_error !== "MAJOR") return rating;

  const artifactTexts = [...rating.critical_issues, ...rating.minor_issues, rating.notes]
    .map(normalizeString)
    .filter(Boolean);
  const hasContextualSynthesisSignal = artifactTexts.some((text) =>
    matchesAnyPattern(text, COVERED_NECK_SYNTHESIS_PATTERNS) ||
    matchesAnyPattern(text, TUCKED_UPPER_BOTTOM_PATTERNS),
  );
  const hasIndependentMajorArtifactSignal = artifactTexts.some((text) =>
    matchesAnyPattern(text, MAJOR_ARTIFACT_PATTERNS) &&
    !matchesAnyPattern(text, COVERED_NECK_SYNTHESIS_PATTERNS) &&
    !matchesAnyPattern(text, TUCKED_UPPER_BOTTOM_PATTERNS),
  );

  if (!hasContextualSynthesisSignal || hasIndependentMajorArtifactSignal) {
    return rating;
  }

  return {
    ...rating,
    labels: {
      ...rating.labels,
      artifact_error: "MINOR",
    },
  };
}

function resolveArtifactLabelContradictions(rating) {
  if (!rating || rating.labels?.artifact_error === "NONE") return rating;

  const notesText = normalizeString(rating.notes);
  const positivesText = rating.positives.map(normalizeString).filter(Boolean).join(" ");
  const evidenceTexts = [...rating.critical_issues, ...rating.minor_issues]
    .map(normalizeString)
    .filter(Boolean);

  const hasConcreteArtifactEvidence = evidenceTexts.some((text) =>
    matchesAnyPattern(text, ARTIFACT_PATTERNS) &&
    !matchesAnyPattern(text, CLEAN_ARTIFACT_PATTERNS) &&
    !matchesAnyPattern(text, LOW_IMPACT_ARTIFACT_PATTERNS),
  );
  const hasCleanArtifactSignal = matchesAnyPattern(`${notesText}\n${positivesText}`, CLEAN_ARTIFACT_PATTERNS);

  if (!hasCleanArtifactSignal || hasConcreteArtifactEvidence) {
    return rating;
  }

  return {
    ...rating,
    labels: {
      ...rating.labels,
      artifact_error: "NONE",
    },
  };
}

function demoteLowImpactArtifactCriticalIssues(rating) {
  if (!rating || rating.labels?.artifact_error === "MAJOR") return rating;

  const retainedCritical = [];
  let nextMinor = [...rating.minor_issues];

  for (const issue of rating.critical_issues) {
    const text = normalizeString(issue);
    if (!text) continue;

    const isArtifactIssue = matchesAnyPattern(text, ARTIFACT_PATTERNS);
    const isClearlyMajorArtifact = matchesAnyPattern(text, MAJOR_ARTIFACT_PATTERNS);
    const isContextualSynthesisIssue =
      matchesAnyPattern(text, COVERED_NECK_SYNTHESIS_PATTERNS) ||
      matchesAnyPattern(text, TUCKED_UPPER_BOTTOM_PATTERNS);
    const overlapsAnotherMajorCategory =
      matchesAnyPattern(text, STRUCTURE_MAJOR_PATTERNS) ||
      matchesAnyPattern(text, SILHOUETTE_MAJOR_PATTERNS) ||
      matchesAnyPattern(text, FIT_MAJOR_PATTERNS);

    if (isArtifactIssue && (!isClearlyMajorArtifact || isContextualSynthesisIssue) && !overlapsAnotherMajorCategory) {
      nextMinor = appendUniqueStrings(nextMinor, [text], 6);
      continue;
    }

    retainedCritical.push(text);
  }

  return {
    ...rating,
    critical_issues: retainedCritical,
    minor_issues: nextMinor,
  };
}

function ensureCriticalIssuesHaveMajorLabel(rating) {
  if (!rating) return rating;
  if (rating.critical_issues.length === 0) return rating;
  if (Object.values(rating.labels).some((value) => value === "MAJOR")) return rating;

  return {
    ...rating,
    labels: {
      ...rating.labels,
      garment_structure_error: maxSeverity(rating.labels.garment_structure_error, "MAJOR"),
    },
  };
}

function ensureIssuesMatchLabels(rating) {
  if (!rating) return rating;

  let criticalIssues = [...rating.critical_issues];
  let minorIssues = [...rating.minor_issues];

  const issueTextByLabel = {
    garment_structure_error: {
      MINOR: "Some visible garment structure or detail differs from the source garment.",
      MAJOR: "Important visible garment structure or detail is missing, wrong, or invented.",
    },
    construction_alignment_error: {
      MINOR: "Some visible garment details are slightly misaligned or placed incorrectly.",
      MAJOR: "Visible garment details are clearly misaligned, broken, or placed incorrectly.",
    },
    fit_error: {
      MINOR: "The garment fit or placement looks somewhat off on the person.",
      MAJOR: "The garment fit or placement is clearly wrong on the person.",
    },
    artifact_error: {
      MINOR: "There are noticeable but limited generation artifacts or minor damage in the result.",
      MAJOR: "There are obvious generation artifacts or damage to the person or other clothing.",
    },
    silhouette_error: {
      MINOR: "The garment silhouette differs somewhat from the source garment.",
      MAJOR: "The garment silhouette is clearly wrong compared with the source garment.",
    },
  };

  for (const key of LABEL_KEYS) {
    const severity = rating.labels?.[key] || "NONE";
    if (severity === "NONE") continue;

    const text = issueTextByLabel[key]?.[severity];
    if (!text) continue;

    if (severity === "MAJOR") {
      criticalIssues = appendUniqueStrings(criticalIssues, [text], 6);
    } else {
      minorIssues = appendUniqueStrings(minorIssues, [text], 6);
    }
  }

  return {
    ...rating,
    critical_issues: criticalIssues,
    minor_issues: minorIssues,
  };
}

function calculateQualityScore(labels) {
  let score = 100;
  for (const key of LABEL_KEYS) {
    score -= SCORE_PENALTIES[key][labels[key]];
  }
  return clamp(score, 0, 100);
}

function determineSuccessful(score, labels, criticalIssues) {
  return score >= PASS_SCORE_THRESHOLD &&
    criticalIssues.length === 0 &&
    labels.garment_structure_error !== "MAJOR" &&
    labels.artifact_error !== "MAJOR"
      ? "YES"
      : "NO";
}

function finalizeRating(rating) {
  const sanitizedRating = sanitizeIssueLists(rating);
  const consistentRating = applyIssueConsistencyGuards(sanitizedRating);
  const relaxedRating = relaxContextualArtifactOvercalls(consistentRating);
  const contradictionResolvedRating = resolveArtifactLabelContradictions(relaxedRating);
  const rebalancedRating = demoteLowImpactArtifactCriticalIssues(contradictionResolvedRating);
  const guardedRating = ensureCriticalIssuesHaveMajorLabel(rebalancedRating);
  const completedRating = ensureIssuesMatchLabels(guardedRating);
  let qualityPercent = calculateQualityScore(completedRating.labels);
  if (completedRating.critical_issues.length > 0 && qualityPercent >= PASS_SCORE_THRESHOLD) {
    qualityPercent = PASS_SCORE_THRESHOLD - 1;
  }
  return {
    ...completedRating,
    quality_percent: qualityPercent,
    successful: determineSuccessful(qualityPercent, completedRating.labels, completedRating.critical_issues),
  };
}

function appendUniqueStrings(existing, incoming, maxItems) {
  const result = [];
  const seen = new Set();

  for (const item of [...existing, ...incoming]) {
    const normalized = normalizeString(item);
    if (!normalized) continue;
    const key = normalized.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(normalized);
    if (result.length >= maxItems) break;
  }

  return result;
}

function mergeNotes(baseNotes, extraNotes) {
  const base = normalizeString(baseNotes);
  const extra = normalizeString(extraNotes);
  if (!extra) return base.slice(0, 350);
  if (!base) return extra.slice(0, 350);
  if (base.toLowerCase().includes(extra.toLowerCase())) return base.slice(0, 350);
  return `${base} ${extra}`.slice(0, 350);
}

function parseDurationMs(text) {
  if (!text) return null;

  const trimmed = String(text).trim();
  if (/^\d+ms$/i.test(trimmed)) return Number.parseInt(trimmed, 10);
  if (/^\d+(\.\d+)?s$/i.test(trimmed)) return Math.ceil(Number.parseFloat(trimmed) * 1000);
  if (/^\d+(\.\d+)?m$/i.test(trimmed)) return Math.ceil(Number.parseFloat(trimmed) * 60_000);

  const composite = trimmed.match(/(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?/i);
  if (composite && (composite[1] || composite[2])) {
    const minutes = composite[1] ? Number.parseInt(composite[1], 10) : 0;
    const seconds = composite[2] ? Number.parseFloat(composite[2]) : 0;
    return Math.ceil(minutes * 60_000 + seconds * 1000);
  }

  return null;
}

function parseRetryAfterMs(err) {
  const headerValue = err?.headers?.["retry-after-ms"] || err?.headers?.["retry-after"];
  const headerMs = parseDurationMs(headerValue);
  if (headerMs !== null) return headerMs;

  const resetTokenMs = parseDurationMs(err?.headers?.["x-ratelimit-reset-tokens"]);
  const resetRequestMs = parseDurationMs(err?.headers?.["x-ratelimit-reset-requests"]);
  const resetMs = Math.max(resetTokenMs ?? 0, resetRequestMs ?? 0);
  if (resetMs > 0) return resetMs;

  const message = `${err?.message ?? ""}\n${err?.body ?? ""}`;
  const match = message.match(/try again in\s+(\d+)\s*ms/i);
  if (match) return Number.parseInt(match[1], 10);

  const secondsMatch = message.match(/try again in\s+(\d+(?:\.\d+)?)\s*s/i);
  if (secondsMatch) return Math.ceil(Number.parseFloat(secondsMatch[1]) * 1000);

  return null;
}

function setGlobalCooldown(ms) {
  const jitter = Math.floor(Math.random() * (RATE_LIMIT_JITTER_MS + 1));
  globalCooldownUntil = Math.max(globalCooldownUntil, Date.now() + ms + jitter);
}

async function waitForGlobalCooldown() {
  const remaining = globalCooldownUntil - Date.now();
  if (remaining > 0) {
    await sleep(remaining);
  }
}

function validateArtifactAudit(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { ok: false, error: "Artifact audit JSON is not an object." };
  }

  const artifactPresent = normalizeString(raw.artifact_present);
  if (!ALLOWED_YES_NO.has(artifactPresent)) {
    return { ok: false, error: `Invalid artifact_present: ${JSON.stringify(raw.artifact_present)}` };
  }

  const artifactSeverity = normalizeString(raw.artifact_severity);
  if (!ALLOWED_SEVERITIES.has(artifactSeverity)) {
    return { ok: false, error: `Invalid artifact_severity: ${JSON.stringify(raw.artifact_severity)}` };
  }

  if (artifactPresent === "NO" && artifactSeverity !== "NONE") {
    return { ok: false, error: "artifact_present=NO requires artifact_severity=NONE." };
  }

  if (artifactPresent === "YES" && artifactSeverity === "NONE") {
    return { ok: false, error: "artifact_present=YES requires artifact_severity=MINOR or MAJOR." };
  }

  return {
    ok: true,
    audit: {
      artifact_present: artifactPresent,
      artifact_severity: artifactSeverity,
      artifact_reasons: normalizeStringList(raw.artifact_reasons, 4),
      notes: normalizeString(raw.notes).slice(0, 240),
    },
  };
}

function validateAndNormalizeRating(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { ok: false, error: "Response JSON is not an object." };
  }

  const garmentCategory = normalizeOptionalEnum(raw.garment_category, ALLOWED_CATEGORIES);
  const intendedFit = normalizeOptionalEnum(raw.intended_fit, ALLOWED_FITS);
  const silhouettePreserved = normalizeOptionalEnum(raw.silhouette_preserved, ALLOWED_SILHOUETTES);

  const labels = raw.labels;
  if (!labels || typeof labels !== "object" || Array.isArray(labels)) {
    return { ok: false, error: "Missing or invalid labels object." };
  }

  const normalizedLabels = {};
  for (const key of LABEL_KEYS) {
    let value = normalizeString(labels[key]);
    if (!value && key === "silhouette_error") {
      value = "NONE";
    }
    if (key === "silhouette_error" && value === "PARTIAL") {
      value = "MINOR";
    }
    if (!ALLOWED_SEVERITIES.has(value)) {
      return { ok: false, error: `Invalid label for ${key}: ${JSON.stringify(labels[key])}` };
    }
    normalizedLabels[key] = value;
  }

  return {
    ok: true,
    rating: finalizeRating({
      garment_category: garmentCategory,
      garment_type: normalizeGarmentType(raw.garment_type),
      intended_fit: intendedFit,
      silhouette_preserved: silhouettePreserved,
      critical_issues: normalizeStringList(raw.critical_issues, 6),
      minor_issues: normalizeStringList(raw.minor_issues, 6),
      positives: normalizeStringList(raw.positives, 6),
      notes: normalizeString(raw.notes).slice(0, 350),
      labels: normalizedLabels,
    }),
  };
}

function applyArtifactAuditToRating(rating, artifactAudit) {
  if (!rating || !artifactAudit) return rating;
  if (artifactAudit.artifact_present !== "YES") return rating;

  const nextLabels = { ...rating.labels };
  if (severityRank(artifactAudit.artifact_severity) > severityRank(nextLabels.artifact_error)) {
    nextLabels.artifact_error = artifactAudit.artifact_severity;
  }

  const reasons =
    artifactAudit.artifact_reasons.length > 0
      ? artifactAudit.artifact_reasons
      : [artifactAudit.notes || "Artifact audit detected visible residual or damaged clothing elements."];

  const nextRating = {
    ...rating,
    labels: nextLabels,
    critical_issues:
      artifactAudit.artifact_severity === "MAJOR"
        ? appendUniqueStrings(rating.critical_issues, reasons, 6)
        : rating.critical_issues,
    minor_issues:
      artifactAudit.artifact_severity === "MINOR"
        ? appendUniqueStrings(rating.minor_issues, reasons, 6)
        : rating.minor_issues,
    notes: mergeNotes(rating.notes, artifactAudit.notes),
  };

  return finalizeRating(nextRating);
}

function shouldRunArtifactAudit(rating, hasModelImage) {
  if (ENABLE_ARTIFACT_AUDIT) return true;
  if (!hasModelImage || !rating) return false;
  return rating.successful === "YES";
}

function enforcePerfectScoreGuard(rating, artifactAuditResult) {
  if (!rating || rating.quality_percent < 100) return rating;

  if (artifactAuditResult?.ok && artifactAuditResult.audit?.artifact_present === "NO") {
    return rating;
  }

  const nextLabels = { ...rating.labels };
  if (nextLabels.artifact_error === "NONE") {
    nextLabels.artifact_error = "MINOR";
  }

  return finalizeRating({
    ...rating,
    labels: nextLabels,
    minor_issues: appendUniqueStrings(
      rating.minor_issues,
      ["Perfect score withheld because artifact audit did not confirm a fully clean image."],
      6,
    ),
    notes: mergeNotes(rating.notes, "Perfect score withheld because artifact audit did not confirm a fully clean image."),
  });
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
      const err = new Error(`HTTP ${res.status}: ${text}`);
      err.status = res.status;
      err.body = text;
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

async function runArtifactAudit(garmentUrl, modelUrl, resultUrl, garmentCategory) {
  const content = [{ type: "text", text: ARTIFACT_AUDIT_PROMPT }];

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
    max_tokens: 220,
    top_p: 1,
    presence_penalty: 0,
    n: 1,
    response_format: { type: "json_object" },
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
  const validated = parsed.ok ? validateArtifactAudit(parsed.json) : null;

  return {
    ok: Boolean(parsed.ok && validated?.ok),
    audit: validated?.ok ? validated.audit : null,
    raw_output_text: parsed.ok && validated?.ok ? null : raw,
    parse_error: parsed.ok ? validated?.error ?? null : parsed.error,
    finish_reason: resp?.choices?.[0]?.finish_reason ?? null,
  };
}

async function evaluateFolder(folderName, folderContext) {
  if (!folderContext.ok) {
    return { folder: folderName, ok: false, error: folderContext.error };
  }

  const { garmentPath, modelPath, resultPath } = folderContext;

  if (!garmentPath || !resultPath) {
    return {
      folder: folderName,
      ok: false,
      error: "Missing required files. Expected garment.* and result.*",
      found: {
        garment: garmentPath ? path.basename(garmentPath) : null,
        result: resultPath ? path.basename(resultPath) : null,
      },
    };
  }

  for (const p of [garmentPath, resultPath]) {
    const st = fs.statSync(p);
    if (!st.isFile() || st.size < 1024) {
      return {
        folder: folderName,
        ok: false,
        error: `File too small or invalid: ${path.basename(p)} (size=${st.size})`,
        found: {
          garment: path.basename(garmentPath),
          result: path.basename(resultPath),
        },
      };
    }
  }

  const garmentUrl = fileToDataUrl(garmentPath);
  const modelUrl = modelPath && INCLUDE_MODEL_IN_MAIN ? fileToDataUrl(modelPath) : null;
  const resultUrl = fileToDataUrl(resultPath);
  const useModelInMain = Boolean(modelUrl && INCLUDE_MODEL_IN_MAIN);

  const payload = {
    model: MODEL,
    temperature: 0,
    max_tokens: 1000,
    top_p: 1,
    presence_penalty: 0,
    n: 1,
    response_format: { type: "json_object" },
    messages: [
      {
        role: "user",
        content: [
          { type: "text", text: PROMPT },
          ...(useModelInMain
            ? [
                { type: "text", text: "IMAGE 1: TARGET_GARMENT" },
                { type: "image_url", image_url: { url: garmentUrl } },
                { type: "text", text: "IMAGE 2: PERSON" },
                { type: "image_url", image_url: { url: modelUrl } },
                { type: "text", text: "IMAGE 3: GENERATED_RESULT" },
                { type: "image_url", image_url: { url: resultUrl } },
              ]
            : [
                { type: "text", text: "IMAGE 1: TARGET_GARMENT" },
                { type: "image_url", image_url: { url: garmentUrl } },
                { type: "text", text: "IMAGE 2: GENERATED_RESULT" },
                { type: "image_url", image_url: { url: resultUrl } },
              ]),
        ],
      },
    ],
  };

  const resp = await postChatCompletions(payload);
  const raw = extractAssistantText(resp);
  const parsed = safeJsonParse(raw);
  const validated = parsed.ok ? validateAndNormalizeRating(parsed.json) : null;
  let finalRating = validated?.rating ?? null;
  let artifactAuditResult = null;

  if (validated?.ok && shouldRunArtifactAudit(finalRating, Boolean(modelPath))) {
    try {
      const auditModelUrl = modelUrl ?? (modelPath ? fileToDataUrl(modelPath) : null);
      artifactAuditResult = await runArtifactAudit(
        garmentUrl,
        auditModelUrl,
        resultUrl,
        finalRating?.garment_category ?? null,
      );
    } catch (error) {
      artifactAuditResult = {
        ok: false,
        audit: null,
        raw_output_text: null,
        parse_error: error?.message ?? String(error),
        finish_reason: null,
      };
    }
  }

  if (validated?.ok && artifactAuditResult?.ok && artifactAuditResult.audit) {
    finalRating = applyArtifactAuditToRating(finalRating, artifactAuditResult.audit);
    finalRating = enforcePerfectScoreGuard(finalRating, artifactAuditResult);
  }

  return {
    folder: folderName,
    ok: Boolean(parsed.ok && validated?.ok),
    rating: validated?.ok ? finalRating : null,
    raw_output_text: parsed.ok && validated?.ok ? null : raw,
    parse_error: parsed.ok ? validated?.error ?? null : parsed.error,
    finish_reason: resp?.choices?.[0]?.finish_reason ?? null,
    artifact_audit: artifactAuditResult?.audit ?? null,
    artifact_audit_raw_output: artifactAuditResult?.raw_output_text ?? null,
    artifact_audit_error: artifactAuditResult?.ok ? null : artifactAuditResult?.parse_error ?? null,
    artifact_audit_finish_reason: artifactAuditResult?.finish_reason ?? null,
  };
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
    source_layout: folderContext.sourceLayout,
    source_folder: projectRelative(folderContext.folderPath),
    metadata: summarizeMetadata(folderContext.metadata),
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
    artifact_audit_error: record.artifact_audit_error ?? null,
    artifact_audit_raw_output: record.artifact_audit_raw_output ?? null,
    artifact_audit_finish_reason: record.artifact_audit_finish_reason ?? null,
    body: record.body ?? null,
  };
}

function copyAsset(sourcePath, targetDir, targetBaseName) {
  if (!sourcePath || !fs.existsSync(sourcePath) || !fs.statSync(sourcePath).isFile()) {
    return null;
  }

  const ext = path.extname(sourcePath);
  const targetPath = path.join(targetDir, `${targetBaseName}${ext}`);
  fs.copyFileSync(sourcePath, targetPath);
  return targetPath;
}

function formatBulletSection(title, items) {
  if (!items || items.length === 0) {
    return `${title}: none`;
  }
  return `${title}:\n${items.map((item) => `- ${item}`).join("\n")}`;
}

function buildTextSummary(payload) {
  const lines = [];
  const rating = payload.rating;

  lines.push(`Folder: ${payload.folder}`);
  lines.push(`Source folder: ${payload.source_folder || "(unknown)"}`);

  if (payload.metadata?.test_id) lines.push(`Test ID: ${payload.metadata.test_id}`);
  if (payload.metadata?.test_number !== undefined) lines.push(`Test number: ${payload.metadata.test_number}`);
  if (payload.metadata?.gender) lines.push(`Gender: ${payload.metadata.gender}`);
  if (payload.metadata?.status) lines.push(`Selenium status: ${payload.metadata.status}`);

  if (rating) {
    lines.push(`AI pass: ${rating.successful}`);
    lines.push(`Quality score: ${rating.quality_percent}%`);
    lines.push(`Garment category: ${rating.garment_category || "n/a"}`);
    lines.push(`Garment type: ${rating.garment_type || "(blank)"}`);
    lines.push(`Intended fit: ${rating.intended_fit || "n/a"}`);
    lines.push(`Silhouette preserved: ${rating.silhouette_preserved || "n/a"}`);
    lines.push(`Notes: ${rating.notes || "none"}`);
    lines.push("");
    lines.push(formatBulletSection("Critical issues", rating.critical_issues));
    lines.push("");
    lines.push(formatBulletSection("Minor issues", rating.minor_issues));
    lines.push("");
    lines.push(formatBulletSection("Positives", rating.positives));
    lines.push("");
    lines.push("Severity labels:");
    for (const key of LABEL_KEYS) {
      lines.push(`- ${key}: ${rating.labels?.[key] || "NONE"}`);
    }
  } else {
    lines.push(`AI pass: not available`);
    lines.push(`Error: ${payload.error || payload.message || payload.parse_error || "Unknown error"}`);
  }

  return `${lines.join("\n").trim()}\n`;
}

function writeReviewBundle(reviewRoot, payload, folderContext) {
  const bundleDir = ensureDir(path.join(reviewRoot, payload.folder));
  const copied = {
    model: copyAsset(folderContext.modelPath, bundleDir, "model"),
    garment: copyAsset(folderContext.garmentPath, bundleDir, "garment"),
    result: copyAsset(folderContext.resultPath, bundleDir, "result"),
    metadata: null,
    quality: null,
    summary: null,
  };

  if (folderContext.metadataPath && fs.existsSync(folderContext.metadataPath)) {
    const metadataTarget = path.join(bundleDir, "metadata.json");
    fs.copyFileSync(folderContext.metadataPath, metadataTarget);
    copied.metadata = metadataTarget;
  }

  const qualityPath = path.join(bundleDir, "quality.json");
  fs.writeFileSync(qualityPath, JSON.stringify(payload, null, 2), "utf8");
  copied.quality = qualityPath;

  const summaryPath = path.join(bundleDir, "summary.txt");
  fs.writeFileSync(summaryPath, buildTextSummary(payload), "utf8");
  copied.summary = summaryPath;

  return {
    bundleDir,
    files: {
      model: copied.model ? toWebPath(path.relative(reviewRoot, copied.model)) : null,
      garment: copied.garment ? toWebPath(path.relative(reviewRoot, copied.garment)) : null,
      result: copied.result ? toWebPath(path.relative(reviewRoot, copied.result)) : null,
      metadata: copied.metadata ? toWebPath(path.relative(reviewRoot, copied.metadata)) : null,
      quality: toWebPath(path.relative(reviewRoot, copied.quality)),
      summary: toWebPath(path.relative(reviewRoot, copied.summary)),
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

function renderImageCard(label, relativePath) {
  if (!relativePath) {
    return `<div class="image-card missing"><div class="image-label">${escapeHtml(label)}</div><div class="missing-text">Missing</div></div>`;
  }

  const safeSrc = encodeURI(relativePath);
  const safeLabel = escapeHtml(label);
  const safeSrcAttr = escapeHtml(safeSrc);
  return `
    <div class="image-card">
      <div class="image-card-header">
        <div class="image-label">${safeLabel}</div>
        <div class="image-actions">
          <button type="button" class="image-action zoom-button" data-full-src="${safeSrcAttr}" data-full-label="${safeLabel}">Zoom</button>
          <a class="image-action" href="${safeSrcAttr}" target="_blank" rel="noreferrer">Open</a>
        </div>
      </div>
      <button type="button" class="image-frame zoom-button" data-full-src="${safeSrcAttr}" data-full-label="${safeLabel}">
        <img src="${safeSrcAttr}" alt="${safeLabel}" loading="lazy" decoding="async">
      </button>
    </div>
  `;
}

function createReviewEntry(payload, bundle) {
  const rating = payload.rating;
  return {
    folder: payload.folder,
    test_number: payload.metadata?.test_number ?? null,
    test_id: payload.metadata?.test_id ?? payload.folder,
    gender: payload.metadata?.gender ?? null,
    selenium_status: payload.metadata?.status ?? null,
    evaluation_ok: payload.ok,
    ai_successful: rating?.successful ?? null,
    quality_percent: rating?.quality_percent ?? null,
    garment_category: rating?.garment_category ?? null,
    garment_type: rating?.garment_type ?? null,
    intended_fit: rating?.intended_fit ?? null,
    silhouette_preserved: rating?.silhouette_preserved ?? null,
    labels: rating?.labels ?? null,
    notes: rating?.notes ?? payload.error ?? payload.message ?? payload.parse_error ?? null,
    critical_issues: rating?.critical_issues ?? [],
    minor_issues: rating?.minor_issues ?? [],
    positives: rating?.positives ?? [],
    source_folder: payload.source_folder,
    bundle_folder: toWebPath(payload.folder),
    files: bundle.files,
  };
}

function csvEscape(value) {
  const text = String(value ?? "");
  if (/[",\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function buildReviewHtml(reviewEntries, summary, meta) {
  const cards = reviewEntries
    .map((entry) => {
      const score = entry.quality_percent ?? "ERR";
      const aiStatus = entry.ai_successful || "ERROR";
      const scoreClass =
        entry.quality_percent === null || entry.quality_percent === undefined
          ? "score-error"
          : aiStatus === "YES"
            ? "score-pass"
            : "score-fail";

      return `
        <article class="card">
          <div class="card-top">
            <div>
              <h2>${escapeHtml(entry.test_id)}</h2>
              <p class="meta">
                Folder: ${escapeHtml(entry.folder)}
                ${entry.test_number !== null ? ` | Test #${escapeHtml(entry.test_number)}` : ""}
                ${entry.gender ? ` | ${escapeHtml(entry.gender)}` : ""}
              </p>
            </div>
            <div class="badges">
              <span class="badge ${scoreClass}">Score: ${escapeHtml(score)}</span>
              <span class="badge ${aiStatus === "YES" ? "score-pass" : aiStatus === "NO" ? "score-fail" : "score-error"}">AI: ${escapeHtml(aiStatus)}</span>
            </div>
          </div>

          <div class="images">
            ${renderImageCard("Model", entry.files.model)}
            ${renderImageCard("Garment", entry.files.garment)}
            ${renderImageCard("Result", entry.files.result)}
          </div>

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
          </div>

          <p class="links">
            <a href="${encodeURI(entry.files.summary)}">summary.txt</a>
            <a href="${encodeURI(entry.files.quality)}">quality.json</a>
            ${entry.files.metadata ? `<a href="${encodeURI(entry.files.metadata)}">metadata.json</a>` : ""}
          </p>
        </article>
      `;
    })
    .join("\n");

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Try-On Review</title>
  <style>
    :root {
      --bg: #f4f0e8;
      --card: #fffdf8;
      --ink: #1f1b16;
      --muted: #6b6257;
      --line: #ded3c2;
      --pass: #2d6a4f;
      --fail: #9d0208;
      --error: #6a4c93;
      --accent: #c97b31;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(201, 123, 49, 0.18), transparent 28%),
        linear-gradient(180deg, #f9f4eb 0%, var(--bg) 100%);
    }
    main {
      max-width: 1440px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }
    h1, h2, h3 { margin: 0; }
    h1 {
      font-size: clamp(2rem, 4vw, 3.5rem);
      letter-spacing: 0.02em;
      margin-bottom: 8px;
    }
    .intro {
      color: var(--muted);
      max-width: 960px;
      margin-bottom: 24px;
      line-height: 1.5;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 28px;
    }
    .summary-card {
      background: rgba(255, 253, 248, 0.9);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
    }
    .summary-card strong {
      display: block;
      font-size: 1.7rem;
      margin-bottom: 4px;
    }
    .summary-card span {
      color: var(--muted);
      font-size: 0.95rem;
    }
    .cards {
      display: grid;
      gap: 18px;
    }
    .card {
      background: rgba(255, 253, 248, 0.97);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 20px;
      box-shadow: 0 12px 30px rgba(56, 39, 19, 0.08);
    }
    .card-top {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: start;
      margin-bottom: 18px;
    }
    .meta {
      margin-top: 6px;
      color: var(--muted);
      font-size: 0.95rem;
    }
    .badges {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: end;
    }
    .badge {
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 0.9rem;
      color: white;
      font-weight: 600;
      white-space: nowrap;
    }
    .score-pass { background: var(--pass); }
    .score-fail { background: var(--fail); }
    .score-error { background: var(--error); }
    .images {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 18px;
      align-items: start;
    }
    .image-card {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 12px;
      background: #fff;
      min-height: 100%;
    }
    .image-card-header {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 10px;
    }
    .image-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .image-action {
      appearance: none;
      border: 1px solid var(--line);
      background: #fffaf2;
      color: #7a3e07;
      border-radius: 999px;
      padding: 6px 10px;
      font: inherit;
      font-size: 0.85rem;
      cursor: pointer;
      text-decoration: none;
      line-height: 1;
    }
    .image-frame {
      display: block;
      width: 100%;
      padding: 0;
      border: 0;
      background: transparent;
      cursor: zoom-in;
      text-align: inherit;
    }
    .image-card img {
      width: 100%;
      height: 400px;
      object-fit: contain;
      border-radius: 12px;
      background: linear-gradient(180deg, #fffaf2, #f3eadf);
    }
    .image-card.missing {
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      min-height: 160px;
    }
    .image-label {
      font-size: 0.85rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 10px;
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
      background: #fff;
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
    .links {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin: 0;
    }
    a {
      color: #7a3e07;
      text-decoration-thickness: 1px;
      text-underline-offset: 3px;
    }
    .footer {
      margin-top: 28px;
      color: var(--muted);
      font-size: 0.95rem;
    }
    .lightbox[hidden] {
      display: none;
    }
    .lightbox {
      position: fixed;
      inset: 0;
      z-index: 999;
      display: grid;
      place-items: center;
      padding: 24px;
      background: rgba(24, 18, 12, 0.82);
      backdrop-filter: blur(8px);
    }
    .lightbox-inner {
      position: relative;
      width: min(96vw, 1800px);
      height: min(94vh, 1200px);
      border-radius: 24px;
      background: rgba(31, 27, 22, 0.94);
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
      padding: 58px 20px 20px;
    }
    .lightbox-caption {
      position: absolute;
      top: 18px;
      left: 20px;
      color: #fffaf2;
      font-size: 0.95rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .lightbox-close {
      position: absolute;
      top: 14px;
      right: 14px;
      border: 1px solid rgba(255, 250, 242, 0.24);
      background: rgba(255, 250, 242, 0.08);
      color: #fffaf2;
      border-radius: 999px;
      padding: 8px 12px;
      font: inherit;
      cursor: pointer;
    }
    .lightbox img {
      width: 100%;
      height: 100%;
      object-fit: contain;
      border-radius: 18px;
      background: radial-gradient(circle at top, rgba(201, 123, 49, 0.12), transparent 30%);
    }
    body.lightbox-open {
      overflow: hidden;
    }
    @media (max-width: 720px) {
      main { padding: 20px 14px 32px; }
      .card { padding: 16px; }
      .card-top { flex-direction: column; }
      .badges { justify-content: start; }
      .images { grid-template-columns: 1fr; }
      .image-card img { height: 320px; }
      .image-card-header { align-items: start; flex-direction: column; }
      .lightbox { padding: 10px; }
      .lightbox-inner { width: 100%; height: min(92vh, 960px); padding: 52px 12px 12px; }
    }
  </style>
</head>
<body>
  <main>
    <h1>Try-On Review</h1>
    <p class="intro">
      Source: <strong>${escapeHtml(meta.sourceDir)}</strong> (${escapeHtml(meta.sourceLayout)} layout).
      Generated ${escapeHtml(meta.generatedAt)}.
      Click any preview to open a full-resolution zoom view, or use the Open button for the raw file.
    </p>

    <section class="summary">
      <div class="summary-card"><strong>${escapeHtml(summary.total)}</strong><span>Total evaluated</span></div>
      <div class="summary-card"><strong>${escapeHtml(summary.successful)}</strong><span>AI pass</span></div>
      <div class="summary-card"><strong>${escapeHtml(summary.failed)}</strong><span>AI fail</span></div>
      <div class="summary-card"><strong>${escapeHtml(summary.errors)}</strong><span>Errors</span></div>
    </section>

    <section class="cards">
      ${cards}
    </section>

    <p class="footer">
      Files in this folder: <code>index.html</code>, <code>index.csv</code>, <code>index.json</code>, plus one subfolder per try-on result.
    </p>
  </main>
  <div class="lightbox" id="lightbox" hidden>
    <div class="lightbox-inner">
      <div class="lightbox-caption" id="lightboxCaption">Image</div>
      <button type="button" class="lightbox-close" id="lightboxClose">Close</button>
      <img id="lightboxImage" alt="">
    </div>
  </div>
  <script>
    (() => {
      const lightbox = document.getElementById("lightbox");
      const lightboxImage = document.getElementById("lightboxImage");
      const lightboxCaption = document.getElementById("lightboxCaption");
      const lightboxClose = document.getElementById("lightboxClose");

      const openLightbox = (src, label) => {
        if (!src) return;
        lightboxImage.src = src;
        lightboxImage.alt = label || "Image";
        lightboxCaption.textContent = label || "Image";
        lightbox.hidden = false;
        document.body.classList.add("lightbox-open");
      };

      const closeLightbox = () => {
        lightbox.hidden = true;
        lightboxImage.removeAttribute("src");
        document.body.classList.remove("lightbox-open");
      };

      for (const trigger of document.querySelectorAll(".zoom-button")) {
        trigger.addEventListener("click", (event) => {
          event.preventDefault();
          openLightbox(trigger.dataset.fullSrc, trigger.dataset.fullLabel);
        });
      }

      lightboxClose.addEventListener("click", closeLightbox);
      lightbox.addEventListener("click", (event) => {
        if (event.target === lightbox) {
          closeLightbox();
        }
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !lightbox.hidden) {
          closeLightbox();
        }
      });
    })();
  </script>
</body>
</html>`;
}

function writeReviewIndex(reviewRoot, reviewEntries, summary, sourceDir, sourceLayout) {
  const generatedAt = new Date().toISOString();

  const indexJsonPath = path.join(reviewRoot, "index.json");
  fs.writeFileSync(
    indexJsonPath,
    JSON.stringify(
      {
        generated_at: generatedAt,
        source_dir: projectRelative(sourceDir),
        source_layout: sourceLayout,
        review_dir: projectRelative(reviewRoot),
        summary,
        entries: reviewEntries,
      },
      null,
      2,
    ),
    "utf8",
  );

  const csvColumns = [
    "folder",
    "test_number",
    "test_id",
    "gender",
    "selenium_status",
    "evaluation_ok",
    "ai_successful",
    "quality_percent",
    "garment_category",
    "garment_type",
    "intended_fit",
    "silhouette_preserved",
    "notes",
    "model_file",
    "garment_file",
    "result_file",
    "summary_file",
    "quality_file",
  ];
  const csvRows = [
    csvColumns.join(","),
    ...reviewEntries.map((entry) =>
      [
        entry.folder,
        entry.test_number,
        entry.test_id,
        entry.gender,
        entry.selenium_status,
        entry.evaluation_ok,
        entry.ai_successful,
        entry.quality_percent,
        entry.garment_category,
        entry.garment_type,
        entry.intended_fit,
        entry.silhouette_preserved,
        entry.notes,
        entry.files.model,
        entry.files.garment,
        entry.files.result,
        entry.files.summary,
        entry.files.quality,
      ]
        .map(csvEscape)
        .join(","),
    ),
  ];
  fs.writeFileSync(path.join(reviewRoot, "index.csv"), `${csvRows.join("\n")}\n`, "utf8");

  const html = buildReviewHtml(reviewEntries, summary, {
    generatedAt,
    sourceDir: projectRelative(sourceDir) || sourceDir,
    sourceLayout,
  });
  fs.writeFileSync(path.join(reviewRoot, "index.html"), html, "utf8");
}

async function main() {
  const sourceDir = resolveSourceDir();
  const folders = listSubfoldersSorted(sourceDir);

  if (folders.length === 0) {
    console.error(`No subfolders found in ${projectRelative(sourceDir) || sourceDir}.`);
    console.error(`Expected either test_results/<test_id>/... or images/<folder>/...`);
    process.exit(1);
  }

  const sourceLayout = detectSourceLayout(sourceDir, folders);
  const outDir = ensureDir(OUTPUTS_DIR);
  const reviewRoot = ensureDir(path.join(outDir, REVIEW_DIR_NAME));
  const outPath = path.join(outDir, "evals.jsonl");
  fs.writeFileSync(outPath, "", "utf8");

  console.log(`OpenAI endpoint: ${ENDPOINT}`);
  console.log(`Model: ${MODEL}`);
  console.log(`Source dir: ${projectRelative(sourceDir) || sourceDir}`);
  console.log(`Source layout: ${sourceLayout}`);
  console.log(`Folders: ${folders.length}`);
  console.log(`Concurrency: ${CONCURRENCY}`);
  console.log(`Main evaluation uses model image: ${INCLUDE_MODEL_IN_MAIN ? "YES" : "NO"}`);
  console.log(`Artifact audit mode: ${ENABLE_ARTIFACT_AUDIT ? "ALWAYS" : "AUTO ON CLEAN PASS CANDIDATES"}`);
  console.log(`Review bundle dir: ${projectRelative(reviewRoot) || reviewRoot}`);

  const summary = {
    total: 0,
    successful: 0,
    failed: 0,
    errors: 0,
    by_category: {},
    silhouette_stats: { YES: 0, PARTIAL: 0, NO: 0 },
    by_fit: {
      tight: { total: 0, pass: 0 },
      regular: { total: 0, pass: 0 },
      loose: { total: 0, pass: 0 },
      oversized: { total: 0, pass: 0 },
    },
    source_dir: projectRelative(sourceDir),
    source_layout: sourceLayout,
    review_dir: projectRelative(reviewRoot),
  };

  const evaluations = await mapWithConcurrency(folders, CONCURRENCY, async (folderName) => {
    const folderPath = path.join(sourceDir, folderName);
    const folderContext = collectFolderAssets(folderName, folderPath, sourceLayout);
    console.log(`\n=== Evaluating: ${folderName} ===`);

    let record;
    try {
      record = await evaluateFolder(folderName, folderContext);
    } catch (err) {
      record = {
        folder: folderName,
        ok: false,
        error: "LLM request failed",
        status: err?.status ?? null,
        message: err?.message ?? String(err),
        body: err?.body ?? null,
      };
    }

    const perFolderPayload = createPerFolderPayload(folderName, folderContext, record);
    const sourceQualityPath = path.join(folderPath, "quality.json");
    fs.writeFileSync(sourceQualityPath, JSON.stringify(perFolderPayload, null, 2), "utf8");

    const bundle = writeReviewBundle(reviewRoot, perFolderPayload, folderContext);

    return { folderContext, record, perFolderPayload, bundle };
  });

  const reviewEntries = [];

  for (const evaluation of evaluations) {
    const { record, perFolderPayload, bundle } = evaluation;

    summary.total++;

    if (record.ok && record.rating) {
      console.log(JSON.stringify(record.rating, null, 2));

      const rating = record.rating;
      if (rating.successful === "YES") summary.successful++;
      else summary.failed++;

      if (rating.garment_category) {
        const category = rating.garment_category;
        if (!summary.by_category[category]) summary.by_category[category] = { total: 0, pass: 0, fail: 0 };
        summary.by_category[category].total++;
        if (rating.successful === "YES") summary.by_category[category].pass++;
        else summary.by_category[category].fail++;
      }

      if (rating.silhouette_preserved && summary.silhouette_stats[rating.silhouette_preserved] !== undefined) {
        summary.silhouette_stats[rating.silhouette_preserved]++;
      }

      if (rating.intended_fit && summary.by_fit[rating.intended_fit]) {
        summary.by_fit[rating.intended_fit].total++;
        if (rating.successful === "YES") summary.by_fit[rating.intended_fit].pass++;
      }
    } else {
      console.log(JSON.stringify(record, null, 2));
      summary.errors++;
    }

    fs.appendFileSync(outPath, JSON.stringify(perFolderPayload) + "\n", "utf8");
    reviewEntries.push(createReviewEntry(perFolderPayload, bundle));
  }

  const summaryPath = path.join(outDir, "analysis_summary.json");
  fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2), "utf8");
  writeReviewIndex(reviewRoot, reviewEntries, summary, sourceDir, sourceLayout);

  console.log(`\n${"=".repeat(60)}`);
  console.log("ANALYSIS SUMMARY");
  console.log(`${"=".repeat(60)}`);
  console.log(`Total evaluated: ${summary.total}`);
  console.log(`Successful (YES): ${summary.successful}`);
  console.log(`Failed (NO): ${summary.failed}`);
  console.log(`Errors: ${summary.errors}`);
  console.log(`\nBy garment category:`);
  for (const [cat, stats] of Object.entries(summary.by_category)) {
    console.log(`  ${cat}: ${stats.pass}/${stats.total} passed (${stats.fail} failed)`);
  }
  console.log(`\nSilhouette preservation:`);
  console.log(`  Preserved (YES): ${summary.silhouette_stats.YES}`);
  console.log(`  Partial: ${summary.silhouette_stats.PARTIAL}`);
  console.log(`  Lost (NO): ${summary.silhouette_stats.NO}`);
  console.log(`\nBy intended fit:`);
  for (const [fit, stats] of Object.entries(summary.by_fit)) {
    if (stats.total > 0) {
      console.log(`  ${fit}: ${stats.pass}/${stats.total} passed`);
    }
  }
  console.log(`\nResults saved to: ${projectRelative(outPath) || outPath}`);
  console.log(`Summary saved to: ${projectRelative(summaryPath) || summaryPath}`);
  console.log(`Review index saved to: ${projectRelative(path.join(reviewRoot, "index.html")) || path.join(reviewRoot, "index.html")}`);
}

main();
