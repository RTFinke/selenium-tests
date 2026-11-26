import "dotenv/config";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { groupByGarment, summarizeProblems, summarizeGarments } from "./lib/review-summary.js";
import { embedReviewImages, IMAGE_PLACEHOLDER, renderEmbeddedImages } from "./lib/review-images.js";
import {
  LABEL_KEYS, envNumber, fileToDataUrl, parseRetryAfterMs,
  RATING_RESPONSE_FORMAT, VERIFICATION_RESPONSE_FORMAT,
  validateAndNormalizeRating as normalizeRating, validateAssessmentVerification,
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
// Retain the existing environment setting while replacing the one-way audit.
const ENABLE_VERIFICATION = /^(1|true|yes)$/i.test(String(process.env.ANALYZE_ENABLE_ARTIFACT_AUDIT || "true").trim());
const REPORT_MODE = String(process.env.ANALYSIS_REPORT_MODE || "review").trim().toLowerCase();
const GALLERY_ONLY_MODE = REPORT_MODE === "gallery";
const COMPARISON_ONLY_MODE = REPORT_MODE === "comparison";
const SCORE_POLICY = {
  passScore: envNumber(process.env, "OPENAI_PASS_SCORE_THRESHOLD", 80, { max: 100 }),
  maxMinorLabels: envNumber(process.env, "OPENAI_MAX_MINOR_LABELS_FOR_PASS", 2, { max: 4 }),
};
const OUTPUTS_DIR = path.resolve(process.env.ANALYSIS_OUTPUT_DIR || "outputs");
const IMAGE_EXTENSIONS = new Set([".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"]);

const PROMPT = fs.readFileSync(new URL("./prompts/tryon-judgment.txt", import.meta.url), "utf8").trim();
const ARTIFACT_AUDIT_PROMPT = fs.readFileSync(new URL("./prompts/tryon-integrity-audit.txt", import.meta.url), "utf8").trim();
const PROMPT_VERSIONS = {
  judgment: { file: "prompts/tryon-judgment.txt", sha256: createHash("sha256").update(PROMPT).digest("hex") },
  integrity_audit: { file: "prompts/tryon-integrity-audit.txt", sha256: createHash("sha256").update(ARTIFACT_AUDIT_PROMPT).digest("hex") },
};

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

function shouldRunAssessmentVerification(rating) {
  return ENABLE_VERIFICATION || rating.successful === "YES";
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

async function runAssessmentVerification(garmentUrl, modelUrl, resultUrl, primaryRating, contextText) {
  const content = [{ type: "text", text: ARTIFACT_AUDIT_PROMPT }, { type: "text", text: contextText }];

  if (modelUrl) {
    content.push({ type: "text", text: "IMAGE 1: MODEL_ORIGINAL" });
    content.push({ type: "image_url", image_url: { url: modelUrl, detail: "high" } });
    content.push({ type: "text", text: "IMAGE 2: TARGET_GARMENT" });
    content.push({ type: "image_url", image_url: { url: garmentUrl, detail: "high" } });
    content.push({ type: "text", text: "IMAGE 3: GENERATED_RESULT" });
    content.push({ type: "image_url", image_url: { url: resultUrl, detail: "high" } });
  } else {
    content.push({ type: "text", text: "IMAGE 1: TARGET_GARMENT" });
    content.push({ type: "image_url", image_url: { url: garmentUrl, detail: "high" } });
    content.push({ type: "text", text: "IMAGE 2: GENERATED_RESULT" });
    content.push({ type: "image_url", image_url: { url: resultUrl, detail: "high" } });
  }

  const proposed = Object.fromEntries(Object.keys(RATING_RESPONSE_FORMAT.json_schema.schema.properties).map(key => [key, primaryRating[key]]));
  content.push({ type: "text", text: "PROPOSED ASSESSMENT (unverified claims; check each against the images and inspect for missed defects):\n" + JSON.stringify(proposed) });

  const payload = {
    model: MODEL,
    temperature: 0,
    max_completion_tokens: 4000,
    top_p: 1,
    presence_penalty: 0,
    n: 1,
    response_format: VERIFICATION_RESPONSE_FORMAT,
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
  const validated = parsed.ok && stopped ? validateAssessmentVerification(parsed.json, SCORE_POLICY) : null;

  return {
    ok: Boolean(parsed.ok && validated?.ok),
    rating: validated?.rating ?? null,
    verification: validated?.verification ?? null,
    accepted_findings: validated?.accepted_findings ?? [],
    excluded_findings: validated?.excluded_findings ?? [],
    raw_output_text: parsed.ok && validated?.ok ? null : raw,
    parse_error: !stopped ? `Assessment verification did not finish: ${resp?.choices?.[0]?.finish_reason ?? "missing response"}` : parsed.ok ? validated?.error ?? null : parsed.error,
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
      { type: "text", text: "IMAGE 1: TARGET_GARMENT" }, { type: "image_url", image_url: { url: garmentUrl, detail: "high" } },
      { type: "text", text: "IMAGE 2: PERSON" }, { type: "image_url", image_url: { url: modelUrl, detail: "high" } },
      { type: "text", text: "IMAGE 3: GENERATED_RESULT" }, { type: "image_url", image_url: { url: resultUrl, detail: "high" } },
    ] }],
  };
  let validated;
  let finishReason;
  const diagnostics = { assessment_attempts: 0, assessment_validation_errors: [] };
  for (let attempt = 1; attempt <= 2; attempt++) {
    diagnostics.assessment_attempts = attempt;
    let response;
    try { response = await postChatCompletions(payload); }
    catch (error) { return { folder: folderName, ok: false, error: error.message, status: error.status ?? null, ...diagnostics }; }
    finishReason = response?.choices?.[0]?.finish_reason;
    const raw = extractAssistantText(response);
    const parsed = safeJsonParse(raw);
    validated = parsed.ok && finishReason === "stop" ? validateAndNormalizeRating(parsed.json) : null;
    if (validated?.ok) break;
    const error = finishReason !== "stop" ? "Assessment did not finish: " + (finishReason || "missing response") : validated?.error || parsed.error;
    diagnostics.assessment_validation_errors.push({ attempt, code: validated?.code ?? null, error, raw_output_text: raw });
    if (validated?.code !== "INCONSISTENT_SEVERITY" || attempt === 2) {
      return { folder: folderName, ok: false, error, raw_output_text: raw, finish_reason: finishReason, ...diagnostics };
    }
    console.warn(folderName + ": AI returned conflicting issue severity; requesting one correction.");
    payload.messages.push(
      { role: "assistant", content: raw },
      { role: "user", content: "Your previous assessment is inconsistent: it lists critical issues but assigns no MAJOR labels. Recheck the same images and return a complete corrected JSON assessment. If an issue is genuinely critical, assign the appropriate MAJOR label. If it is only minor, put it in minor_issues rather than critical_issues. Do not automatically upgrade, downgrade, or delete the defect just to satisfy validation; decide from the visible evidence. Keep the required response schema." },
    );
  }
  let rating = validated.rating;
  const primaryRating = rating;
  let verificationResult = null;
  if (shouldRunAssessmentVerification(rating)) {
    try {
      verificationResult = await runAssessmentVerification(garmentUrl, modelUrl, resultUrl, rating, contextText);
    } catch (error) {
      verificationResult = { ok: false, parse_error: error.message };
    }
    if (!verificationResult.ok) return {
      folder: folderName, ok: false, rating: null, preliminary_rating: rating, primary_rating: primaryRating, ...diagnostics,
      error: "Assessment incomplete: verification failed. " + (verificationResult.parse_error || "Invalid response"),
      verification_status: "failed",
      verification_error: verificationResult.parse_error,
      verification_raw_output: verificationResult.raw_output_text ?? null,
      verification_finish_reason: verificationResult.finish_reason ?? null,
    };
    rating = verificationResult.rating;
  }
  return { folder: folderName, ok: true, rating, primary_rating: primaryRating, finish_reason: finishReason, ...diagnostics,
    verification: verificationResult?.verification ?? null,
    accepted_findings: verificationResult?.accepted_findings ?? [], excluded_findings: verificationResult?.excluded_findings ?? [],
    verification_status: verificationResult ? "completed" : "not_required" };
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
    primary_rating: record.primary_rating ?? null,
    assessment_attempts: record.assessment_attempts ?? 0,
    assessment_validation_errors: record.assessment_validation_errors ?? [],
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
    verification: record.verification ?? null,
    verification_status: record.verification_status ?? null,
    verification_error: record.verification_error ?? null,
    verification_raw_output: record.verification_raw_output ?? null,
    verification_finish_reason: record.verification_finish_reason ?? null,
    accepted_findings: record.accepted_findings ?? [],
    excluded_findings: record.excluded_findings ?? [],
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

function renderVerificationDetails(entry) {
  if (!entry.verification) return "";
  const coverageLabels = { garment_design: "Garment design", fit_and_drape: "Fit and drape", person_integrity: "Person and anatomy", scene_and_other_items: "Scene and other items" };
  const coverage = Object.entries(entry.verification.coverage || {}).map(([key, observation]) =>
    `<p><strong>${escapeHtml(coverageLabels[key] || key)}:</strong> ${escapeHtml(observation)}</p>`).join("");
  const evidence = (entry.accepted_findings || []).map(finding => `<li><strong>${escapeHtml(finding.description)}</strong><br>Reference: ${escapeHtml(finding.original_observation)}<br>Result: ${escapeHtml(finding.result_observation)}${finding.contour_evidence ? `<br>Body region: ${escapeHtml(finding.contour_evidence.region)}<br>Landmarks and scale: ${escapeHtml(finding.contour_evidence.landmark_corroboration)}<br>Clothing explanation checked: ${escapeHtml(finding.contour_evidence.clothing_explanation_exclusion)}` : ""}</li>`).join("");
  const rejected = [...(entry.verification.rejected_claims || []), ...(entry.excluded_findings || []).map(finding => finding.description + " — " + finding.exclusion_reason)];
  return `<details class="review-evidence"><summary>Review evidence and limitations</summary>
    ${coverage}
    ${evidence ? `<h3>Evidence for scored issues</h3><ul>${evidence}</ul>` : ""}
    ${rejected.length ? `<h3>Claims excluded from scoring</h3>${renderHtmlList(rejected, "None")}` : ""}
  </details>`;
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

  const embedded = typeof relativePath === "object";
  const safeSrc = embedded ? IMAGE_PLACEHOLDER : relativePath.split("/").map(encodeURIComponent).join("/");
  const embeddedAttributes = embedded
    ? ` data-review-image="${escapeHtml(relativePath.id)}" width="${relativePath.width}" height="${relativePath.height}"`
    : "";
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
        <img src="${escapeHtml(safeSrc)}"${embeddedAttributes} alt="${safeLabel}" loading="lazy" decoding="async">
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
    model_filename: payload.metadata?.model_filename ?? null,
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
    notes: rating?.notes ?? ([payload.error, payload.message, payload.parse_error, payload.verification_error, payload.artifact_audit_error].filter(Boolean).join(" ") || null),
    critical_issues: rating?.critical_issues ?? [],
    minor_issues: rating?.minor_issues ?? [],
    positives: rating?.positives ?? [],
    major_audit: payload.artifact_audit?.artifact_severity === "MAJOR",
    verification: payload.verification ?? null,
    accepted_findings: payload.accepted_findings ?? [],
    excluded_findings: payload.excluded_findings ?? [],
    source_folder: payload.source_folder,
    files: bundle.files,
  };
}

function renderProblemHighlights({ evaluated_results: total, problems }) {
  const heading = `<div class="section-heading"><h2>Most common reported problems</h2><p>${total} evaluated results. Each result counts once per problem type; one result can have several types. These are grouped AI findings, not new judgments.</p></div>`;
  if (!problems.length) return `<section class="report-section">${heading}<p class="muted">${total ? "No problems reported in the evaluated results." : "No completed AI judgments to summarize."}</p></section>`;
  const highlights = problems.slice(0, 6).map(problem => `
    <article class="problem-card">
      <h3 title="${escapeHtml(problem.label)}">${escapeHtml(problem.label.length > 120 ? problem.label.slice(0, 117) + "…" : problem.label)}</h3>
      <div class="problem-count"><strong>${problem.count}</strong><span>of ${total} results · ${problem.percent}%</span></div>
      <div class="problem-bar" aria-hidden="true"><span style="width:${problem.percent}%"></span></div>
      <p><span class="critical-count">${problem.critical_count} critical</span> · ${problem.minor_count} minor · ${problem.garment_count} garments</p>
      <details><summary>Example findings</summary>${renderHtmlList(problem.examples, "None")}</details>
    </article>
  `).join("\n");
  const remaining = problems.length > 6 ? `<details class="all-problems"><summary>All ${problems.length} reported problem types</summary><ul>${problems.map(problem => `<li><strong>${escapeHtml(problem.label)}</strong>: ${problem.count} results (${problem.critical_count} critical, ${problem.minor_count} minor)</li>`).join("")}</ul></details>` : "";
  return `<section class="report-section">${heading}<div class="problem-grid">${highlights}</div>${remaining}</section>`;
}

function renderGarmentOverview(groups, galleryOnly) {
  const rows = groups.map(group => `
    <tr>
      <td><a href="#${group.id}">${escapeHtml(group.name)}</a><br><span class="muted">${escapeHtml(group.run_mode)}</span></td>
      <td>${group.stats.model_count}</td><td>${group.stats.total}</td>
      ${galleryOnly ? `<td>${group.stats.generation_failed}</td>` : `<td>${group.stats.passed} / ${group.stats.failed}</td><td>${group.stats.average_score === null ? "—" : group.stats.average_score + "%"}</td><td>${group.stats.generation_failed + group.stats.errors}</td>`}
    </tr>
  `).join("\n");
  return `<section class="report-section"><div class="section-heading"><h2>Clothing overview</h2><p>Select a garment to see all of its models together.</p></div>
    <div class="table-scroll"><table class="garment-table"><thead><tr><th>Garment</th><th>Models</th><th>Results</th>${galleryOnly ? "<th>Generation failures</th>" : "<th>AI pass / fail</th><th>Average score</th><th>Generation / assessment errors</th>"}</tr></thead><tbody>${rows}</tbody></table></div>
  </section>`;
}

function buildReviewHtml(reviewEntries, summary, meta) {
  const isGalleryOnly = meta.reportMode === "gallery";
  const evaluatorModel = meta.evaluatorModel ?? MODEL;
  const scoringPolicy = meta.scoringPolicy ?? SCORE_POLICY;
  const reportTitle = isGalleryOnly ? "Try-On Gallery Report" : "Try-On Review Report";
  const garmentGroups = groupByGarment(reviewEntries);
  const problemSummary = summarizeProblems(reviewEntries);
  const renderCard = (entry) => {
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
              ${renderHtmlList(entry.positives, entry.major_audit ? "Earlier positive claims are withheld after a major integrity finding." : "None")}
            </section>
          </div>
          ${renderVerificationDetails(entry)}`;

      return `
        <article class="card ${isGalleryOnly ? "card-gallery" : "card-review"}">
          <div class="card-top">
            <div class="card-heading">
              <div class="card-kicker">${isGalleryOnly ? "Result Sheet" : "Review Entry"}</div>
              <h3>${escapeHtml(entry.model_filename ? path.parse(entry.model_filename).name : entry.test_id || entry.folder || "Unknown model")}</h3>
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
    };
  const cards = garmentGroups.map((group, index) => `
    <section class="garment-group" id="${group.id}">
      <header class="garment-header">
        <p class="card-kicker">Garment ${index + 1} of ${garmentGroups.length} · ${escapeHtml(group.run_mode)}</p>
        <h2>${escapeHtml(group.name)}</h2>
        <p class="muted">${group.stats.model_count} models · ${group.stats.total} results${isGalleryOnly ? "" : ` · ${group.stats.passed} pass · ${group.stats.failed} fail · average ${group.stats.average_score === null ? "—" : group.stats.average_score + "%"}`}${group.stats.generation_failed ? ` · ${group.stats.generation_failed} generation failures` : ""}${group.stats.errors ? ` · ${group.stats.errors} assessment errors` : ""}</p>
      </header>
      <div class="cards">${group.entries.map(renderCard).join("\n")}</div>
    </section>
  `).join("\n");
  const problemHighlights = isGalleryOnly ? "" : renderProblemHighlights(problemSummary);
  const garmentOverview = renderGarmentOverview(garmentGroups, isGalleryOnly);

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
    .report-heading { margin-bottom: 24px; }
    .report-heading h1 { font-size: clamp(1.8rem, 3vw, 2.6rem); }
    .report-heading p { color: var(--muted); margin-bottom: 0; }
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
    .report-section { margin: 28px 0; }
    .section-heading { margin-bottom: 16px; }
    .section-heading h2 { font-size: 1.4rem; }
    .section-heading p { margin-bottom: 0; color: var(--muted); line-height: 1.5; }
    .problem-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
    .problem-card { padding: 18px; background: var(--panel); border: 1px solid var(--line); border-radius: 18px; }
    .problem-card h3 { font-size: 1rem; min-height: 2.5em; line-height: 1.3; }
    .problem-count { display: flex; align-items: baseline; gap: 8px; margin: 12px 0 8px; }
    .problem-count strong { font-size: 2rem; }
    .problem-count span, .problem-card p, .problem-card details { color: var(--muted); font-size: .88rem; line-height: 1.45; }
    .problem-bar { height: 5px; border-radius: 999px; background: var(--line); overflow: hidden; }
    .problem-bar span { display: block; height: 100%; background: var(--accent); }
    .critical-count { color: #ff9b9b; }
    .review-evidence { margin-top: 20px; color: var(--muted); }
    .review-evidence summary { cursor: pointer; color: var(--ink); }
    .review-evidence li { margin-bottom: 12px; }
    .card-review .details > p:last-child { grid-column: 1 / -1; }
    .problem-card details { margin-top: 12px; }
    details summary { cursor: pointer; }
    details ul { padding-left: 20px; line-height: 1.5; }
    .all-problems { margin-top: 16px; color: var(--muted); }
    .table-scroll { overflow-x: auto; border: 1px solid var(--line); border-radius: 16px; }
    .garment-table { border-collapse: collapse; width: 100%; min-width: 620px; background: var(--panel); }
    .garment-table th, .garment-table td { padding: 13px 16px; border-bottom: 1px solid var(--line); text-align: left; }
    .garment-table th { color: var(--muted); font-size: .8rem; }
    .garment-table tbody tr:last-child td { border-bottom: 0; }
    .garment-table td:not(:first-child) { white-space: nowrap; }
    .garment-groups { display: grid; gap: 36px; margin-top: 36px; }
    .garment-group { scroll-margin-top: 20px; }
    .garment-header { padding: 20px 0 16px; border-top: 2px solid var(--accent); }
    .garment-header h2 { font-size: clamp(1.6rem, 3vw, 2.1rem); overflow-wrap: anywhere; }
    .garment-header p { margin: 8px 0; }
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
    .card h3 {
      font-size: clamp(1.2rem, 2.5vw, 1.65rem);
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
      .report-heading, .report-section { break-inside: avoid; }
      .problem-card, .garment-table { background: white; color: #1d1a16; }
      .problem-card h3, .problem-card p, .problem-count span, .garment-table th, .garment-header .muted { color: #44382b; }
      .table-scroll { overflow: visible; }
      .garment-table { min-width: 0; font-size: 9pt; }
      .garment-table th, .garment-table td { padding: 2mm; }
      .garment-header { break-after: avoid; }
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
      .problem-grid { grid-template-columns: 1fr; }
      .image-card img { height: 320px; }
      .card-gallery .image-card img { height: 360px; }
    }
  </style>
</head>
<body>
  <main>
    <header class="report-heading"><h1>${escapeHtml(reportTitle)}</h1><p>Results grouped by clothing, with all models together.</p></header>
    <section class="summary">
      <div class="summary-card"><strong>${garmentGroups.length}</strong><span>Garments</span></div>
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

    ${problemHighlights}
    ${garmentOverview}
    <p class="muted">${escapeHtml(meta.generatedAt)}${isGalleryOnly ? " · Generation gallery" : meta.reportMode === "comparison" ? " · Comparison only: AI not run" : ` · Evaluator: ${escapeHtml(evaluatorModel)} · Pass: ${escapeHtml(scoringPolicy.passScore)}% · Maximum minor labels: ${escapeHtml(scoringPolicy.maxMinorLabels)}`}</p>
    ${summary.source_errors?.length ? `<section><h2>Source errors</h2>${renderHtmlList(summary.source_errors, "")}</section>` : ""}
    <div class="garment-groups">
      ${cards}
    </div>
  </main>
  ${renderEmbeddedImages(meta.images)}
</body>
</html>`;
}

async function writeReviewIndex(reviewRoot, reviewEntries, summary, sourceDirs, sourceLayout) {
  const generatedAt = new Date().toISOString();
  const sourceDirLabel = sourceDirs
    .map((dir) => projectRelative(dir) || dir)
    .join(", ");

  const embedded = GALLERY_ONLY_MODE ? { entries: reviewEntries, warnings: [] } : await embedReviewImages(reviewEntries, reviewRoot);
  for (const warning of embedded.warnings) console.warn(warning);
  const html = buildReviewHtml(embedded.entries, summary, {
    generatedAt,
    sourceDir: sourceDirLabel,
    sourceLayout,
    reportMode: REPORT_MODE,
    images: embedded.images,
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
  const grouped = groupByGarment(reviewEntries);
  const problems = summarizeProblems(reviewEntries);
  summary.by_garment = summarizeGarments(grouped);
  summary.common_problems = problems.problems;
  summary.evaluated_for_problem_summary = problems.evaluated_results;
  const report = {
    schema_version: 3, generated_at: new Date().toISOString(), report_mode: REPORT_MODE,
    evaluator_model: MODEL, prompts: PROMPT_VERSIONS, scoring_policy: SCORE_POLICY, summary,
    results: evaluations.map(item => item.payload),
  };
  fs.writeFileSync(path.join(reviewRoot, "analysis.json"), JSON.stringify(report, null, 2));
  await writeReviewIndex(reviewRoot, reviewEntries, summary, sourceDirs, sourceLayout);
  console.log("AI pass: " + summary.successful + "; AI fail: " + summary.failed + "; generation failures: " + summary.generation_failed + "; assessment errors: " + summary.errors);
  console.log("Review report: " + path.join(reviewRoot, "index.html"));
  const noJudgments = !GALLERY_ONLY_MODE && !COMPARISON_ONLY_MODE && summary.successful + summary.failed === 0;
  if (noJudgments && !summary.errors) console.error("No generated results were available for AI assessment.");
  return { exitCode: summary.errors || noJudgments ? 1 : 0, summary, report };
}

export { main, collectSourceEntries, collectFolderAssets, resolveSourceDirs, renderImageCard, evaluateFolder, createReviewEntry, buildReviewHtml };

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().then(result => { process.exitCode = result.exitCode; }).catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
