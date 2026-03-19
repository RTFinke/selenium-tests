import "dotenv/config";
import fs from "node:fs";
import path from "node:path";

function normalizeBaseUrlToV1(baseUrl) {
  if (!baseUrl) return null;
  const trimmed = String(baseUrl).trim().replace(/\/+$/, "");
  if (trimmed.endsWith("/v1")) return trimmed;
  return `${trimmed}/v1`;
}

const BASE_URL = normalizeBaseUrlToV1(process.env.LOCAL_LLM_BASE_URL);
const MODEL = String(process.env.LOCAL_LLM_MODEL || "").trim();
const API_KEY = String(process.env.LOCAL_LLM_API_KEY || "").trim();
const TIMEOUT_MS = Number(process.env.LOCAL_LLM_TIMEOUT_MS || 180000);

if (!BASE_URL) {
  throw new Error("Missing LOCAL_LLM_BASE_URL (e.g. http://127.0.0.1:8001).");
}
if (!MODEL) {
  throw new Error("Missing LOCAL_LLM_MODEL.");
}

const ENDPOINT = `${BASE_URL}/chat/completions`;

const PROMPT = `You are a practical QA evaluator for virtual try-on quality.
You evaluate ALL garment types: tops, pants, jackets, dresses, skirts, etc.
You are a FAIR and REALISTIC judge. You understand how clothing works on real bodies.

You will receive EXACTLY TWO images:
1) TARGET_GARMENT — the product/garment reference image (often a FLATLAY or product photo on white background)
2) GENERATED_RESULT — the try-on result (person wearing the target garment — THIS IS WHAT YOU JUDGE)

CRITICAL UNDERSTANDING — FLATLAY vs ON-BODY:
The TARGET_GARMENT is usually a FLATLAY photo (garment laid flat or on mannequin). When any garment is put on a real person:
- It NATURALLY becomes narrower/more fitted because a body has shape and gravity pulls fabric down
- Sleeves drape differently on arms than when laid flat
- The overall width ALWAYS decreases compared to flatlay — this is PHYSICS, not an error
- An oversized garment on a person will still look more fitted than on a flatlay — THIS IS NORMAL AND EXPECTED
- ONLY flag silhouette issues if the garment becomes CLEARLY SKIN-TIGHT when it should be loose/oversized
- A garment looking "slightly narrower on body than flatlay" is NEVER an error

STEP 1 — AUTO-DETECT GARMENT TYPE:
Look at TARGET_GARMENT and determine:
- garment_category: "top" | "pants" | "dress" | "skirt" | "outerwear" | "other"
- intended_fit: "tight" | "regular" | "loose" | "oversized"

STEP 2 — SILHOUETTE & FIT PRESERVATION:
Compare TARGET_GARMENT vs GENERATED_RESULT, keeping flatlay-vs-body difference in mind:
- silhouette_preserved: "YES" | "PARTIAL" | "NO"
  - YES = garment looks like the same garment on the person (even if slightly narrower than flatlay)
  - PARTIAL = garment shape is recognizable but noticeably different (e.g. loose became regular)
  - NO = garment is COMPLETELY different silhouette (e.g. oversized hoodie became skin-tight bodysuit)
- Default to YES if the garment is recognizably the same item on the person

STEP 3 — EVALUATE:

Check in order of priority:

1) Garment structure & shape fidelity (HIGHEST PRIORITY)
- Is it the SAME TYPE of garment? (jacket stays jacket, not sweater)
- Sleeve type and length roughly correct?
- Collar/neckline type roughly correct?
- Key structural elements present: zippers, buttons, pockets, seams, panels, stripes, pleats
- ADDED elements that don't exist on TARGET_GARMENT = MAJOR issue
- FULLY MISSING key visible elements (not obstructed) = MAJOR issue
- Shape changes due to body type, pose, gravity, lighting = NOT an error
- Rolled up sleeves = NOT an issue
- Slight hood/collar differences = NOT an issue
- Collar tags missing = NOT an issue
- Prints slightly distorted = MINOR (only MAJOR if completely unrecognizable)

2) Construction details & alignment
- Zippers/buttons exist where expected (if visible)
- Seams, stripes, panels roughly follow correct direction
- No duplicated or floating garment parts

3) Fit & placement on the body
- Garment is on the correct body part
- Reasonable scaling
- Plausible drape and folds

4) Occlusion & layering realism
- Garment layers correctly over body/hair
- No unnatural merging with arms, hair, background
- Other clothing obstructing parts of TARGET garment = NOT a failure

5) Color & texture (LOW PRIORITY)
- Only penalize if color clearly indicates a DIFFERENT garment
- Resolution differences, slight color shifts = NOT an error

6) Artifacts
- Warping, melting, ghosting, broken boundaries
- Artifacts that break garment shape = MAJOR
- Minor warping or resolution loss = MINOR
- Small artifacts at edges = MINOR

CATEGORY-SPECIFIC RULES:

IF garment_category is "pants":
- Judge ONLY pants, ignore tops/shoes
- Elements obstructed by other clothing = NOT missing, count as correct
- Pants partially visible due to crop/pose = judge only visible parts

IF garment_category is "top" or "outerwear":
- Judge ONLY the top/outerwear, ignore pants/shoes

IF garment_category is "dress":
- Judge full garment from neckline to hem

TOLERANCE GUIDELINES — BE FAIR:
- This is virtual try-on, NOT photo editing. Some imperfection is expected.
- If you can look at the result and say "yes, that person is wearing that garment" = it's a pass
- Focus on: is the garment RECOGNIZABLE as the same item?
- Don't nitpick minor differences that any reasonable person would accept

Label assignment (choose ONE per category):
- garment_structure_error: NONE | MINOR | MAJOR
- construction_alignment_error: NONE | MINOR | MAJOR
- fit_error: NONE | MINOR | MAJOR
- artifact_error: NONE | MINOR | MAJOR
- silhouette_error: NONE | MINOR | MAJOR

Scoring (mechanical, fixed penalties):
Start score = 100
Subtract:
- garment_structure_error: MINOR -10, MAJOR -35
- construction_alignment_error: MINOR -5, MAJOR -20
- fit_error: MINOR -5, MAJOR -20
- artifact_error: MINOR -10, MAJOR -30
- silhouette_error: MINOR -10, MAJOR -35
Clamp score to 0..100.

Decision rule:
- YES if score >= 65 AND garment_structure_error != MAJOR AND silhouette_error != MAJOR
- Otherwise NO

Output requirements:
Return ONLY valid JSON (no markdown, no commentary) exactly in this schema:
{
  "successful": "YES" | "NO",
  "quality_percent": number,
  "garment_category": "top" | "pants" | "dress" | "skirt" | "outerwear" | "other",
  "garment_type": string (e.g. "black oversized longsleeve", "blue slim jeans"),
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
- notes: max 350 characters, no repetition
Begin with "{" and end with "}".
No trailing text after the final "}".`.trim();

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

async function postChatCompletions(payload) {
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const headers = {
      "Content-Type": "application/json",
    };
    if (API_KEY) headers["Authorization"] = `Bearer ${API_KEY}`;

    const res = await fetch(ENDPOINT, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    const text = await res.text();
    if (!res.ok) {
      const err = new Error(`HTTP ${res.status}: ${text}`);
      err.status = res.status;
      err.body = text;
      throw err;
    }

    return JSON.parse(text);
  } finally {
    clearTimeout(t);
  }
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
    response_format: { "type": "json_object" },
    messages: [
      {
        role: "user",
        content: [
          { type: "text", text: PROMPT },
          { type: "image_url", image_url: { url: garmentUrl } },
          { type: "image_url", image_url: { url: resultUrl } },
        ],
      },
    ],
  };

  const resp = await postChatCompletions(payload);
  const raw = extractAssistantText(resp);
  const parsed = safeJsonParse(raw);

  return {
    folder: folderName,
    ok: true,
    rating: parsed.ok ? parsed.json : null,
    raw_output_text: parsed.ok ? null : raw,
    parse_error: parsed.ok ? null : parsed.error,
  };
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

  console.log(`Local endpoint: ${ENDPOINT}`);
  console.log(`Model: ${MODEL}`);
  console.log(`Folders: ${folders.length}`);

  const summary = {
    total: 0,
    successful: 0,
    failed: 0,
    errors: 0,
    by_category: {},
    silhouette_stats: { YES: 0, PARTIAL: 0, NO: 0 },
    by_fit: { tight: { total: 0, pass: 0 }, regular: { total: 0, pass: 0 }, loose: { total: 0, pass: 0 }, oversized: { total: 0, pass: 0 } },
  };

  for (const folderName of folders) {
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
      body: record.body ?? null,
    };
    fs.writeFileSync(perFolderPath, JSON.stringify(perFolderPayload, null, 2), "utf8");
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
