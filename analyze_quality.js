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

if (!OPENAI_API_KEY) {
  throw new Error("Missing OPENAI_API_KEY.");
}

const PROMPT = `You are a practical QA evaluator for virtual try-on quality.
You evaluate all garment types: tops, pants, jackets, dresses, skirts, outerwear, and others.
You are fair, realistic, and conservative. You understand how clothing behaves on real bodies.

You will receive exactly two labeled images:
1) TARGET_GARMENT: the product or garment reference image, often a flatlay or product photo
2) GENERATED_RESULT: the try-on result showing a person wearing the garment

Core rule:
Judge whether GENERATED_RESULT still shows the same garment as TARGET_GARMENT on a real person.

Critical understanding: flatlay vs on-body
- A garment on a body naturally looks narrower or more fitted than when laid flat.
- Sleeves and hems drape differently on a person because of pose, gravity, and body shape.
- Slight narrowing from flatlay to on-body is expected and is not a silhouette failure.
- Only flag a major silhouette issue if the garment becomes clearly wrong, such as loose becoming skin-tight.

General evaluation rules:
- Judge only visible evidence.
- Do not infer missing details from hidden, cropped, or obstructed areas.
- Do not penalize differences caused by pose, lighting, gravity, body shape, or normal fabric drape.
- If unsure between two severities, choose the lower severity unless garment identity is clearly broken.
- If the same garment is still clearly recognizable, be tolerant.

Step 1: detect the garment
Determine:
- garment_category: "top" | "pants" | "dress" | "skirt" | "outerwear" | "other"
- garment_type: short plain description of the item
- intended_fit: "tight" | "regular" | "loose" | "oversized"

Step 2: judge silhouette preservation
Compare TARGET_GARMENT vs GENERATED_RESULT:
- silhouette_preserved: "YES" | "PARTIAL" | "NO"
- YES = clearly the same garment silhouette on a person
- PARTIAL = recognizable, but noticeably changed
- NO = clearly a different silhouette or garment behavior
- Default to YES if the item is still recognizably the same garment

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
- Sleeve type, sleeve length, collar, neckline, and major structural features should match when visible.
- Added features that materially change garment identity are major.
- Missing visible key features are major.
- Small print distortion or tiny detail loss is minor.

2) Construction and alignment
- Seams, stripes, panels, zippers, buttons, pleats, and pockets should be roughly correct when visible.
- Duplicated, floating, or badly misaligned garment parts are errors.

3) Fit and drape
- The garment should be on the correct body area with plausible scale and drape.
- Do not penalize normal changes from flatlay to worn appearance.
- Do not penalize missing cuffs, waistband, hem, or similar parts when they are cropped out or occluded.

4) Artifacts and layering realism
- Check for warping, melting, ghosting, broken boundaries, or bad merging with skin, hair, or background.
- Small edge artifacts are minor.
- Artifacts that break garment identity or realism are major.

5) Color and texture
- Penalize only if color or texture changes make it look like a different item.
- Slight color shift or resolution loss is not enough by itself.

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
  garment_structure_error: { NONE: 0, MINOR: 10, MAJOR: 35 },
  construction_alignment_error: { NONE: 0, MINOR: 5, MAJOR: 20 },
  fit_error: { NONE: 0, MINOR: 5, MAJOR: 20 },
  artifact_error: { NONE: 0, MINOR: 10, MAJOR: 30 },
  silhouette_error: { NONE: 0, MINOR: 10, MAJOR: 35 },
};
let globalCooldownUntil = 0;

function guessMimeType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".png") return "image/png";
  if (ext === ".webp") return "image/webp";
  return "application/octet-stream";
}

function fileToDataUrl(filePath) {
  const mimeType = guessMimeType(filePath);
  const b64 = fs.readFileSync(filePath, { encoding: "base64" });
  return `data:${mimeType};base64,${b64}`;
}

function findPair(folderPath) {
  const entries = fs
    .readdirSync(folderPath, { withFileTypes: true })
    .filter((d) => d.isFile())
    .map((d) => d.name);

  const findUniqueByBase = (base) => {
    const baseLower = base.toLowerCase();
    const matches = entries.filter((name) => {
      const parsed = path.parse(name);
      return parsed.name.toLowerCase() === baseLower && parsed.ext.length > 1;
    });

    if (matches.length === 0) return { filePath: null, error: null };
    if (matches.length > 1) {
      return {
        filePath: null,
        error: `Duplicate files for "${base}": ${matches.join(", ")}`,
      };
    }

    return { filePath: path.resolve(folderPath, matches[0]), error: null };
  };

  const garment = findUniqueByBase("garment");
  const result = findUniqueByBase("result");

  const dupErrors = [garment.error, result.error].filter(Boolean);
  if (dupErrors.length > 0) {
    return { ok: false, error: dupErrors.join(" | "), garmentPath: null, resultPath: null };
  }

  return { ok: true, error: null, garmentPath: garment.filePath, resultPath: result.filePath };
}

function ensureOutputsDir() {
  const outDir = path.resolve("outputs");
  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
  return outDir;
}

function listSubfoldersSorted(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }));
}

function safeJsonParse(text) {
  try {
    return { ok: true, json: JSON.parse(text) };
  } catch (e) {
    return { ok: false, error: e?.message ?? String(e) };
  }
}

function normalizeString(value) {
  return typeof value === "string" ? value.trim() : "";
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

  const successful =
    score >= 65 &&
    normalizedLabels.garment_structure_error !== "MAJOR" &&
    normalizedLabels.silhouette_error !== "MAJOR"
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
    const texts = msg
      .content
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

async function evaluateFolder(folderName, folderPath) {
  const pair = findPair(folderPath);

  if (!pair.ok) {
    return { folder: folderName, ok: false, error: pair.error };
  }

  const { garmentPath, resultPath } = pair;

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

async function main() {
  const imagesDir = path.resolve("images");
  const folders = listSubfoldersSorted(imagesDir);

  if (folders.length === 0) {
    console.error("No subfolders found in images/ (e.g. images/Gen0/, images/Gen1/...).");
    process.exit(1);
  }

  const outDir = ensureOutputsDir();
  const outPath = path.join(outDir, "evals.jsonl");
  fs.writeFileSync(outPath, "", "utf8");

  console.log(`OpenAI endpoint: ${ENDPOINT}`);
  console.log(`Model: ${MODEL}`);
  console.log(`Folders: ${folders.length}`);
  console.log(`Concurrency: ${CONCURRENCY}`);

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
  };

  const records = await mapWithConcurrency(folders, CONCURRENCY, async (folderName) => {
    const folderPath = path.join(imagesDir, folderName);
    console.log(`\n=== Evaluating: ${folderName} ===`);

    let record;
    try {
      record = await evaluateFolder(folderName, folderPath);
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

    const perFolderPath = path.join(folderPath, "quality.json");
    const perFolderPayload = {
      folder: folderName,
      timestamp: new Date().toISOString(),
      ok: record.ok,
      rating: record.rating ?? null,
      error: record.error ?? null,
      status: record.status ?? null,
      message: record.message ?? null,
      parse_error: record.parse_error ?? null,
      raw_output_text: record.raw_output_text ?? null,
      finish_reason: record.finish_reason ?? null,
      body: record.body ?? null,
    };
    fs.writeFileSync(perFolderPath, JSON.stringify(perFolderPayload, null, 2), "utf8");

    return record;
  });

  for (const record of records) {
    summary.total++;

    if (record.ok && record.rating) {
      console.log(JSON.stringify(record.rating, null, 2));

      const r = record.rating;
      if (r.successful === "YES") summary.successful++;
      else summary.failed++;

      const cat = r.garment_category || "unknown";
      if (!summary.by_category[cat]) summary.by_category[cat] = { total: 0, pass: 0, fail: 0 };
      summary.by_category[cat].total++;
      if (r.successful === "YES") summary.by_category[cat].pass++;
      else summary.by_category[cat].fail++;

      const sil = r.silhouette_preserved || "unknown";
      if (summary.silhouette_stats[sil] !== undefined) summary.silhouette_stats[sil]++;

      const fit = r.intended_fit || "regular";
      if (summary.by_fit[fit]) {
        summary.by_fit[fit].total++;
        if (r.successful === "YES") summary.by_fit[fit].pass++;
      }
    } else {
      console.log(JSON.stringify(record, null, 2));
      summary.errors++;
    }

    fs.appendFileSync(outPath, JSON.stringify(record) + "\n", "utf8");
  }

  const summaryPath = path.join(outDir, "analysis_summary.json");
  fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2), "utf8");

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
  console.log(`\nResults saved to: ${outPath}`);
  console.log(`Summary saved to: ${summaryPath}`);
}

main();
