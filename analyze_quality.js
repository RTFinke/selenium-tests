import "dotenv/config";
import fs from "node:fs";
import path from "node:path";

const OPENAI_API_KEY = String(process.env.OPENAI_API_KEY || "").trim();
const MODEL = String(process.env.OPENAI_MODEL || "gpt-4o-mini").trim();
const ENDPOINT = "https://api.openai.com/v1/chat/completions";
const TIMEOUT_MS = Number(process.env.OPENAI_TIMEOUT_MS || 180000);
const DELAY_MS = Number(process.env.OPENAI_DELAY_MS || 2000);
const MAX_RETRIES = Number(process.env.OPENAI_MAX_RETRIES || 3);
const CONCURRENCY = Math.max(1, Number(process.env.OPENAI_CONCURRENCY || 4));
const MIN_RETRY_DELAY_MS = Math.max(250, Number(process.env.OPENAI_MIN_RETRY_DELAY_MS || 1000));
const RATE_LIMIT_JITTER_MS = Math.max(0, Number(process.env.OPENAI_RATE_LIMIT_JITTER_MS || 250));
const OUTPUTS_DIR = path.resolve(process.env.ANALYSIS_OUTPUT_DIR || "outputs");
const REVIEW_DIR_NAME = String(process.env.ANALYSIS_REVIEW_DIR || "review").trim() || "review";
const IMAGE_EXTENSIONS = new Set([".jpg", ".jpeg", ".png", ".webp", ".avif"]);

if (!OPENAI_API_KEY) {
  throw new Error("Missing OPENAI_API_KEY.");
}

const PROMPT = `You are a strict commercial QA evaluator for virtual try-on quality.
You evaluate all garment types: tops, pants, jackets, dresses, skirts, outerwear, and others.
Your job is not to decide whether the result is "pretty good for AI".
Your job is to decide whether a paying fashion retailer would be satisfied using GENERATED_RESULT as a standard customer-facing virtual try-on result.

You will receive exactly two labeled images:
1) TARGET_GARMENT: the product or garment reference image, often a flatlay or product photo
2) GENERATED_RESULT: the try-on result showing a person wearing the garment

Commercial standard:
- A pass means the result is accurate enough for a normal online shopper to trust it as a representation of that product.
- "Recognizable as roughly the same item" is NOT enough for a pass.
- If visible differences would make a merchant hesitate to show this on a product page, mark it down.
- If a shopper could reasonably think they are seeing a meaningfully different garment, the result should fail.
- Be objective, skeptical, and commercially minded.

Critical understanding: flatlay vs on-body
- A garment on a body naturally looks narrower or more fitted than when laid flat.
- Sleeves and hems drape differently on a person because of pose, gravity, and body shape.
- Slight narrowing from flatlay to on-body is expected and is not a silhouette failure.
- However, visible retail-relevant differences in length, volume, neckline, sleeve shape, or overall proportion still matter.

General evaluation rules:
- Judge only visible evidence.
- Do not infer missing details from hidden, cropped, or obstructed areas.
- Do not penalize differences caused only by pose, lighting, gravity, body shape, or normal fabric drape.
- Do not let "overall resemblance" cancel out visible structural errors.
- If a visible feature is important for product identity, treat mistakes seriously.
- If you are unsure whether a visible mismatch matters to a merchant, assume it probably does.

Step 1: detect the garment
Determine:
- garment_category: "top" | "pants" | "dress" | "skirt" | "outerwear" | "other"
- garment_type: short plain description of the item
- intended_fit: "tight" | "regular" | "loose" | "oversized"

Step 2: judge silhouette preservation
Compare TARGET_GARMENT vs GENERATED_RESULT:
- silhouette_preserved: "YES" | "PARTIAL" | "NO"
- YES = commercially faithful silhouette and proportion
- PARTIAL = recognizable but merchant-visible silhouette differences
- NO = clearly wrong silhouette, length, volume, or overall garment behavior
- Do NOT default to YES just because the item is recognizable

Step 3: assign severity labels
Choose one value for each:
- garment_structure_error: "NONE" | "MINOR" | "MAJOR"
- construction_alignment_error: "NONE" | "MINOR" | "MAJOR"
- fit_error: "NONE" | "MINOR" | "MAJOR"
- artifact_error: "NONE" | "MINOR" | "MAJOR"
- silhouette_error: "NONE" | "MINOR" | "MAJOR"

How to assign labels:
1) Garment structure and identity
- Check whether it is the same garment type.
- Sleeve type, sleeve length, collar, neckline, closure type, hem shape, major panels, pockets, and major structural features should match when visible.
- Visible text, logo, print motif, stripe layout, or graphic placement differences matter.
- Added or missing visible features that change customer perception are major.
- If a visible structural detail is clearly wrong but the garment is still mostly the same item, mark at least minor.

2) Construction and alignment
- Seams, stripes, panels, pleats, buttons, zippers, quilting lines, and pocket placement should be consistent when visible.
- Misaligned or distorted pattern/layout that a shopper would notice is an error, not a harmless variation.
- Duplicated, floating, or broken garment parts are errors.

3) Fit and drape
- The garment should sit on the correct body area with commercially believable scale and drape.
- Wrong length, wrong tightness, wrong sleeve volume, or wrong crop level are merchant-relevant.
- Do not penalize missing cuffs, waistband, hem, or similar parts when they are cropped out or occluded.

4) Artifacts and layering realism
- Check for warping, melting, ghosting, broken boundaries, or bad merging with skin, hair, or background.
- If artifacts would reduce shopper trust or make the image look low-quality, penalize them.

5) Color and texture
- Penalize visible color, texture, pattern scale, or material changes when they alter the product impression.
- Slight lighting-driven color shift alone is not enough, but merchant-visible changes are important.

Scoring mindset:
- Reserve perfect or near-perfect judgment only for outputs that look commercially reliable.
- Multiple minor issues should usually mean the result is not merchant-satisfactory.
- Do not inflate scores because the result looks plausible overall.

Category-specific rules:
- If garment_category is "pants", judge only the pants and ignore tops and shoes.
- If garment_category is "top" or "outerwear", judge only that garment and ignore pants and shoes.
- If garment_category is "dress", judge the full dress from neckline to hem, but do not penalize areas that are not visible.

Output requirements:
Return only valid JSON with no markdown and no extra text.
Use exactly this schema:
{
  "garment_category": "top" | "pants" | "dress" | "skirt" | "outerwear" | "other",
  "garment_type": string,
  "intended_fit": "tight" | "regular" | "loose" | "oversized",
  "silhouette_preserved": "YES" | "PARTIAL" | "NO",
  "critical_issues": [string],
  "minor_issues": [string],
  "positives": [string],
  "notes": string,
  "labels": {
    "garment_structure_error": "NONE" | "MINOR" | "MAJOR",
    "construction_alignment_error": "NONE" | "MINOR" | "MAJOR",
    "fit_error": "NONE" | "MINOR" | "MAJOR",
    "artifact_error": "NONE" | "MINOR" | "MAJOR",
    "silhouette_error": "NONE" | "MINOR" | "MAJOR"
  }
}

Hard limits:
- critical_issues: max 6 items
- minor_issues: max 6 items
- positives: max 6 items
- notes: max 350 characters, avoid repetition
Begin with "{" and end with "}".
No trailing text after the final "}".`.trim();

const ALLOWED_CATEGORIES = new Set(["top", "pants", "dress", "skirt", "outerwear", "other"]);
const ALLOWED_FITS = new Set(["tight", "regular", "loose", "oversized"]);
const ALLOWED_SILHOUETTES = new Set(["YES", "PARTIAL", "NO"]);
const ALLOWED_SEVERITIES = new Set(["NONE", "MINOR", "MAJOR"]);
const LABEL_KEYS = [
  "garment_structure_error",
  "construction_alignment_error",
  "fit_error",
  "artifact_error",
  "silhouette_error",
];
const SCORE_PENALTIES = {
  garment_structure_error: { NONE: 0, MINOR: 15, MAJOR: 45 },
  construction_alignment_error: { NONE: 0, MINOR: 10, MAJOR: 25 },
  fit_error: { NONE: 0, MINOR: 10, MAJOR: 25 },
  artifact_error: { NONE: 0, MINOR: 15, MAJOR: 35 },
  silhouette_error: { NONE: 0, MINOR: 15, MAJOR: 40 },
};
const PASS_SCORE_THRESHOLD = Math.max(0, Math.min(100, Number(process.env.OPENAI_PASS_SCORE_THRESHOLD || 85)));
const MAX_MINOR_LABELS_FOR_PASS = Math.max(0, Number(process.env.OPENAI_MAX_MINOR_LABELS_FOR_PASS || 1));
let globalCooldownUntil = 0;

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

function validateAndNormalizeRating(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { ok: false, error: "Response JSON is not an object." };
  }

  const garmentCategory = normalizeString(raw.garment_category);
  if (!ALLOWED_CATEGORIES.has(garmentCategory)) {
    return { ok: false, error: `Invalid garment_category: ${JSON.stringify(raw.garment_category)}` };
  }

  const intendedFit = normalizeString(raw.intended_fit);
  if (!ALLOWED_FITS.has(intendedFit)) {
    return { ok: false, error: `Invalid intended_fit: ${JSON.stringify(raw.intended_fit)}` };
  }

  const silhouettePreserved = normalizeString(raw.silhouette_preserved);
  if (!ALLOWED_SILHOUETTES.has(silhouettePreserved)) {
    return { ok: false, error: `Invalid silhouette_preserved: ${JSON.stringify(raw.silhouette_preserved)}` };
  }

  const labels = raw.labels;
  if (!labels || typeof labels !== "object" || Array.isArray(labels)) {
    return { ok: false, error: "Missing or invalid labels object." };
  }

  const normalizedLabels = {};
  for (const key of LABEL_KEYS) {
    let value = normalizeString(labels[key]);
    if (key === "silhouette_error" && value === "PARTIAL") {
      value = "MINOR";
    }
    if (!ALLOWED_SEVERITIES.has(value)) {
      return { ok: false, error: `Invalid label for ${key}: ${JSON.stringify(labels[key])}` };
    }
    normalizedLabels[key] = value;
  }

  let score = 100;
  for (const key of LABEL_KEYS) {
    score -= SCORE_PENALTIES[key][normalizedLabels[key]];
  }
  score = clamp(score, 0, 100);

  const minorCount = LABEL_KEYS.filter((key) => normalizedLabels[key] === "MINOR").length;
  const majorCount = LABEL_KEYS.filter((key) => normalizedLabels[key] === "MAJOR").length;

  const successful =
    score >= PASS_SCORE_THRESHOLD &&
    majorCount === 0 &&
    minorCount <= MAX_MINOR_LABELS_FOR_PASS &&
    normalizedLabels.garment_structure_error === "NONE" &&
    normalizedLabels.silhouette_error === "NONE"
      ? "YES"
      : "NO";

  return {
    ok: true,
    rating: {
      successful,
      quality_percent: score,
      garment_category: garmentCategory,
      garment_type: normalizeString(raw.garment_type),
      intended_fit: intendedFit,
      silhouette_preserved: silhouettePreserved,
      critical_issues: normalizeStringList(raw.critical_issues, 6),
      minor_issues: normalizeStringList(raw.minor_issues, 6),
      positives: normalizeStringList(raw.positives, 6),
      notes: normalizeString(raw.notes).slice(0, 350),
      labels: normalizedLabels,
    },
  };
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

async function evaluateFolder(folderName, folderContext) {
  if (!folderContext.ok) {
    return { folder: folderName, ok: false, error: folderContext.error };
  }

  const { garmentPath, resultPath } = folderContext;

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
  const resultUrl = fileToDataUrl(resultPath);

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
          { type: "text", text: "IMAGE 1: TARGET_GARMENT" },
          { type: "image_url", image_url: { url: garmentUrl } },
          { type: "text", text: "IMAGE 2: GENERATED_RESULT" },
          { type: "image_url", image_url: { url: resultUrl } },
        ],
      },
    ],
  };

  const resp = await postChatCompletions(payload);
  const raw = extractAssistantText(resp);
  const parsed = safeJsonParse(raw);
  const validated = parsed.ok ? validateAndNormalizeRating(parsed.json) : null;

  return {
    folder: folderName,
    ok: Boolean(parsed.ok && validated?.ok),
    rating: validated?.ok ? validated.rating : null,
    raw_output_text: parsed.ok && validated?.ok ? null : raw,
    parse_error: parsed.ok ? validated?.error ?? null : parsed.error,
    finish_reason: resp?.choices?.[0]?.finish_reason ?? null,
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
    lines.push(`Garment category: ${rating.garment_category}`);
    lines.push(`Garment type: ${rating.garment_type || "(blank)"}`);
    lines.push(`Intended fit: ${rating.intended_fit}`);
    lines.push(`Silhouette preserved: ${rating.silhouette_preserved}`);
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
  return `
    <div class="image-card">
      <div class="image-label">${escapeHtml(label)}</div>
      <a href="${safeSrc}" target="_blank" rel="noreferrer">
        <img src="${safeSrc}" alt="${escapeHtml(label)}" loading="lazy">
      </a>
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
          : entry.quality_percent >= PASS_SCORE_THRESHOLD
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
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }
    .image-card {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 12px;
      background: #fff;
      min-height: 100%;
    }
    .image-card img {
      width: 100%;
      height: 320px;
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
    @media (max-width: 720px) {
      main { padding: 20px 14px 32px; }
      .card { padding: 16px; }
      .card-top { flex-direction: column; }
      .badges { justify-content: start; }
      .image-card img { height: 240px; }
    }
  </style>
</head>
<body>
  <main>
    <h1>Try-On Review</h1>
    <p class="intro">
      Source: <strong>${escapeHtml(meta.sourceDir)}</strong> (${escapeHtml(meta.sourceLayout)} layout).
      Generated ${escapeHtml(meta.generatedAt)}.
      Open any image or JSON file directly from this folder if you want the raw files.
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

      const category = rating.garment_category || "unknown";
      if (!summary.by_category[category]) summary.by_category[category] = { total: 0, pass: 0, fail: 0 };
      summary.by_category[category].total++;
      if (rating.successful === "YES") summary.by_category[category].pass++;
      else summary.by_category[category].fail++;

      const silhouette = rating.silhouette_preserved || "unknown";
      if (summary.silhouette_stats[silhouette] !== undefined) summary.silhouette_stats[silhouette]++;

      const fit = rating.intended_fit || "regular";
      if (summary.by_fit[fit]) {
        summary.by_fit[fit].total++;
        if (rating.successful === "YES") summary.by_fit[fit].pass++;
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
