import { test, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import sharp from "sharp";
import YAML from "yaml";
import { groupByGarment, summarizeProblems } from "../lib/review-summary.js";
import {
  validateAndNormalizeRating, applyArtifactAuditToRating, parseRetryAfterMs,
  validateArtifactAudit, envNumber, fileToDataUrl,
} from "../lib/assessment.js";

const require = createRequire(import.meta.url);
const { selectArtifacts, parseRunIds, parseRunUrl, artifactDetails, validateArchiveEntries, downloadArtifacts } = require("../.github/scripts/analysis-artifacts.cjs");
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "siz3r-assessment-"));
const png = await sharp({ create: { width: 16, height: 16, channels: 3, background: "#778899" } }).png().toBuffer();
let serial = 0;
const clean = () => ({
  garment_type: "shirt", garment_category: "top", intended_fit: "regular", silhouette_preserved: "YES",
  critical_issues: [], minor_issues: [], positives: ["Garment preserved."], notes: "Looks coherent.",
  labels: { garment_structure_error: "NONE", construction_alignment_error: "NONE", fit_error: "NONE", artifact_error: "NONE" },
});
const cleanAudit = () => ({ artifact_present: "NO", artifact_severity: "NONE", artifact_reasons: [], notes: "Clean." });
const response = (value, finish_reason = "stop") => new Response(JSON.stringify({ choices: [{ message: { content: JSON.stringify(value) }, finish_reason }] }), { status: 200 });

function makeCase(root, { category = "upper", name = `test_${++serial}_${category}`, failed = false, missingModel = false, flat = false } = {}) {
  const directory = path.join(root, `test_results_${category}`, name);
  fs.mkdirSync(directory, { recursive: true });
  const metadata = {
    test_id: name, garment_run_key: category, garment_mode_requested: category, status: failed ? "failed" : "success",
    quality_mode_selected: "turbo", turbo_requested: true, turbo_enabled: true,
    flat_requested: true, flat_enabled: true, generation_profile_requested: "advanced_segmentation_free_30", steps_selected: 30,
    ...(failed ? { error: "Generation timed out before saving the result." } : {}),
  };
  fs.writeFileSync(path.join(directory, "metadata.json"), JSON.stringify(metadata));
  for (const part of failed ? [] : ["garment", "model", "result"]) {
    if (part === "model" && missingModel) continue;
    const destination = flat ? directory : path.join(directory, part);
    fs.mkdirSync(destination, { recursive: true });
    fs.writeFileSync(path.join(destination, `${part}.png`), png);
  }
  return directory;
}

async function withAnalyzer(overrides, callback) {
  const env = {
    DOTENV_CONFIG_PATH: path.join(temporary, "nonexistent.env"), OPENAI_API_KEY: "offline-test-key",
    OPENAI_MODEL: "gpt-4.1", OPENAI_PASS_SCORE_THRESHOLD: "80", OPENAI_MAX_MINOR_LABELS_FOR_PASS: "2",
    OPENAI_DELAY_MS: "0", OPENAI_CONCURRENCY: "1", OPENAI_MAX_RETRIES: "1", OPENAI_TIMEOUT_MS: "1000",
    OPENAI_MIN_RETRY_DELAY_MS: "1", OPENAI_RATE_LIMIT_JITTER_MS: "0", ANALYZE_ENABLE_ARTIFACT_AUDIT: "false",
    ANALYSIS_REPORT_MODE: "review", ANALYZE_SOURCE_DIR: "", ANALYSIS_OUTPUT_DIR: path.join(temporary, `report-${++serial}`),
    ...overrides,
  };
  const before = Object.fromEntries(Object.keys(env).map(key => [key, process.env[key]]));
  const originalFetch = globalThis.fetch;
  Object.assign(process.env, env);
  globalThis.fetch = async () => { throw new Error("Unexpected network request in offline test"); };
  try {
    const module = await import(`../analyze_quality.js?test=${++serial}`);
    return await callback(module, env.ANALYSIS_OUTPUT_DIR);
  } finally {
    globalThis.fetch = originalFetch;
    for (const [key, value] of Object.entries(before)) if (value === undefined) delete process.env[key]; else process.env[key] = value;
  }
}

test("clean negative wording cannot invent a defect", () => {
  const rating = clean(); rating.notes = "No ghost garments or broken boundaries.";
  const result = validateAndNormalizeRating(rating);
  assert.equal(result.rating.quality_percent, 100);
  assert.equal(result.rating.successful, "YES");
});

test("tucking wording cannot erase a major defect", () => {
  const rating = clean();
  rating.labels.artifact_error = "MAJOR";
  rating.critical_issues = ["The generated waistband is detached from the body due to the tucked-in target."];
  rating.notes = rating.critical_issues[0];
  const result = validateAndNormalizeRating(rating);
  assert.equal(result.rating.labels.artifact_error, "MAJOR");
  assert.equal(result.rating.quality_percent, 60);
  assert.equal(result.rating.successful, "NO");
});

test("configured threshold and minor label cap determine the decision", () => {
  const rating = clean(); rating.labels.garment_structure_error = "MINOR"; rating.labels.artifact_error = "MINOR";
  assert.equal(validateAndNormalizeRating(rating, { passScore: 80, maxMinorLabels: 2 }).rating.successful, "NO");
  assert.equal(validateAndNormalizeRating(rating, { passScore: 75, maxMinorLabels: 2 }).rating.successful, "YES");
  assert.equal(validateAndNormalizeRating(rating, { passScore: 75, maxMinorLabels: 1 }).rating.successful, "NO");
});

test("incomplete or contradictory model judgments are rejected", () => {
  const rating = clean(); delete rating.garment_category;
  assert.equal(validateAndNormalizeRating(rating).ok, false);
  const contradictory = clean(); contradictory.critical_issues.push("A serious problem.");
  assert.equal(validateAndNormalizeRating(contradictory).ok, false);
  assert.equal(validateArtifactAudit({ ...cleanAudit(), artifact_severity: "MAJOR" }).ok, false);
});

test("secondary audit preserves major defects regardless of clean notes", () => {
  const rating = validateAndNormalizeRating(clean()).rating;
  const result = applyArtifactAuditToRating(rating, { artifact_present: "YES", artifact_severity: "MAJOR", artifact_reasons: ["Detached waistband with a floating gap."], notes: "The rest looks trustworthy." });
  assert.equal(result.labels.artifact_error, "MAJOR"); assert.equal(result.successful, "NO");
});

test("major integrity findings stay first when earlier issues and notes fill the report limits", () => {
  const original = clean();
  original.labels.garment_structure_error = "MAJOR";
  original.critical_issues = Array.from({ length: 6 }, (_, index) => `Earlier garment issue ${index + 1}.`);
  original.notes = "Earlier garment notes. ".repeat(30);
  const rating = validateAndNormalizeRating(original).rating;
  const bodyFinding = "Both exposed upper arms are visibly narrower than in PERSON.";
  const result = applyArtifactAuditToRating(rating, {
    artifact_present: "YES", artifact_severity: "MAJOR", artifact_reasons: [bodyFinding], notes: bodyFinding,
  });
  assert.equal(result.critical_issues.length, 6);
  assert.equal(result.critical_issues[0], bodyFinding);
  assert(result.notes.startsWith(bodyFinding));
  assert(result.notes.length <= 350);
});

test("Retry-After seconds, dates, milliseconds and compound resets are honored", () => {
  assert.equal(parseRetryAfterMs({ headers: { "retry-after": "30" } }), 30000);
  assert.equal(parseRetryAfterMs({ headers: { "retry-after-ms": "250" } }), 250);
  assert.equal(parseRetryAfterMs({ headers: { "retry-after": "Mon, 23 Nov 2026 12:00:30 GMT" } }, Date.parse("2026-11-23T12:00:00Z")), 30000);
  assert.equal(parseRetryAfterMs({ headers: { "x-ratelimit-reset-tokens": "1m2.5s" } }), 62500);
  assert.throws(() => envNumber({ COUNT: "NaN" }, "COUNT", 1));
});

test("AVIF images are converted to supported PNG inputs", async () => {
  const image = path.join(temporary, "reference.avif");
  await sharp(png).avif().toFile(image);
  assert.match(await fileToDataUrl(image), /^data:image\/png;base64,/);
});

test("discovery reads nested artifacts and detects each test layout separately", async () => {
  const root = path.join(temporary, "discovery");
  makeCase(root); makeCase(root, { category: "lower", flat: true }); makeCase(root, { category: "full", failed: true });
  await withAnalyzer({}, async module => {
    const { entries } = module.collectSourceEntries([root, path.join(root, "test_results_upper")]);
    assert.equal(entries.length, 3); assert.equal(entries.filter(entry => entry.sourceLayout === "flat").length, 2);
  });
});

test("default local discovery includes upper/lower/full folders", async () => {
  const root = path.join(temporary, "local"); makeCase(root); makeCase(root, { category: "full" });
  const previous = process.cwd(); process.chdir(root);
  try {
    await withAnalyzer({}, async module => assert.equal(module.collectSourceEntries(module.resolveSourceDirs()).entries.length, 2));
  } finally { process.chdir(previous); }
});

test("gallery handles real failed generations without needing an API key", async () => {
  const root = path.join(temporary, "gallery"); makeCase(root); makeCase(root, { failed: true });
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root, OPENAI_API_KEY: "", ANALYSIS_REPORT_MODE: "gallery" }, async (module, output) => {
    const result = await module.main();
    assert.equal(result.exitCode, 0); assert.equal(result.summary.generation_failed, 1); assert.equal(result.summary.errors, 0);
    const html = fs.readFileSync(path.join(output, "index.html"), "utf8");
    assert.match(html, /Generation: FAILED/); assert.equal((html.match(/<img src=/g) || []).length, 3);
    assert.match(html, /Generation timed out/);
  });
});

test("review requires an API key; explicit comparison remains available", async () => {
  const root = path.join(temporary, "key"); makeCase(root);
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root, OPENAI_API_KEY: "" }, async module => {
    const result = await module.main(); assert.equal(result.exitCode, 1); assert.equal(result.summary.errors, 1);
  });
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root, OPENAI_API_KEY: "", ANALYSIS_REPORT_MODE: "comparison" }, async module => {
    const result = await module.main(); assert.equal(result.exitCode, 0); assert.equal(result.summary.comparison_only, 1);
  });
});

test("all failed API requests produce a failed process result and redact the key", async () => {
  const root = path.join(temporary, "api-failure"); makeCase(root);
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async (module, output) => {
    globalThis.fetch = async () => new Response('Invalid key offline-test-key', { status: 401 });
    const result = await module.main(); assert.equal(result.exitCode, 1); assert.equal(result.summary.errors, 1);
    assert(!fs.readFileSync(path.join(output, "analysis.json"), "utf8").includes("offline-test-key"));
  });
});

test("passing cases include full context, structured output and a second audit", async () => {
  const root = path.join(temporary, "success"); makeCase(root, { category: "full" }); makeCase(root, { category: "full", failed: true });
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async (module, output) => {
    const requests = [];
    globalThis.fetch = async (_url, options) => {
      const request = JSON.parse(options.body); requests.push(request);
      return response(request.response_format.json_schema.name === "tryon_artifact_audit" ? cleanAudit() : { ...clean(), garment_category: "outfit" });
    };
    const result = await module.main();
    assert.equal(result.exitCode, 0); assert.equal(result.summary.successful, 1); assert.equal(result.summary.generation_failed, 1); assert.equal(requests.length, 2);
    assert(requests.every(request => request.response_format.type === "json_schema" && request.response_format.json_schema.strict));
    assert(requests.every(request => request.messages[0].content.filter(part => part.type === "image_url").length === 3));
    assert(requests.every(request => request.messages[0].content.filter(part => part.type === "image_url").every(part => part.image_url.detail === "high")));
    assert(requests.every(request => request.messages[0].content.some(part => part.type === "text" && part.text.includes("Transfer mode: FULL") && part.text.includes("turbo"))));
    assert.equal(requests[0].messages[0].content[0].text, fs.readFileSync(path.join(repo, "prompts/tryon-judgment.txt"), "utf8").trim());
    assert.equal(requests[1].messages[0].content[0].text, fs.readFileSync(path.join(repo, "prompts/tryon-integrity-audit.txt"), "utf8").trim());
    assert.equal(result.report.prompts.judgment.file, "prompts/tryon-judgment.txt");
    assert.match(result.report.prompts.integrity_audit.sha256, /^[a-f0-9]{64}$/);
    const html = fs.readFileSync(path.join(output, "index.html"), "utf8");
    assert.match(html, /Quality: turbo/); assert.match(html, /Steps: 30/); assert.match(html, /Generation timed out/);
    assert.equal(result.report.results.find(record => record.rating).metadata.flat_enabled, true);
  });
});

test("the default integrity check catches arm damage even when clothing details already failed", async () => {
  const root = path.join(temporary, "body-check-on-failure"); makeCase(root, { category: "full" });
  // Reproduce Test #3's old 55% labels: the primary review missed the arms.
  const previous = clean();
  previous.labels.garment_structure_error = "MINOR";
  previous.labels.construction_alignment_error = "MINOR";
  previous.labels.fit_error = "MINOR";
  previous.minor_issues = ["Dress pockets are missing", "Hemline shape is slightly off"];
  const bodyFinding = "Both exposed upper arms are visibly narrower than in PERSON.";
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root, ANALYZE_ENABLE_ARTIFACT_AUDIT: "" }, async module => {
    let calls = 0;
    globalThis.fetch = async (_url, options) => {
      calls++;
      const request = JSON.parse(options.body);
      return response(request.response_format.json_schema.name === "tryon_artifact_audit"
        ? { artifact_present: "YES", artifact_severity: "MAJOR", artifact_reasons: [bodyFinding], notes: bodyFinding }
        : previous);
    };
    const result = await module.main();
    const record = result.report.results[0];
    assert.equal(calls, 2); assert.equal(result.exitCode, 0);
    assert.equal(record.artifact_audit_status, "completed");
    assert.equal(record.rating.labels.artifact_error, "MAJOR");
    assert.equal(record.rating.critical_issues[0], bodyFinding);
    assert(record.rating.notes.startsWith(bodyFinding));
  });
});

test("failed artifact audit never leaves a successful score", async () => {
  const root = path.join(temporary, "audit-failure"); makeCase(root);
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async (module, output) => {
    let calls = 0;
    globalThis.fetch = async () => ++calls === 1 ? response(clean()) : new Response("Audit unavailable", { status: 401 });
    const result = await module.main();
    assert.equal(result.exitCode, 1); assert.equal(result.summary.successful, 0);
    assert.equal(result.report.results[0].rating, null); assert.match(result.report.results[0].artifact_audit_error, /401/);
    const html = fs.readFileSync(path.join(output, "index.html"), "utf8");
    assert.match(html, /artifact audit failed/); assert(!html.includes("Score: 100"));
  });
});

test("a major integrity finding cannot retain contradictory body-preservation claims", async () => {
  const root = path.join(temporary, "conflicting-body-claims"); makeCase(root);
  const primary = clean();
  primary.positives = ["Person's face and body proportions are well preserved."];
  primary.notes = "Body proportions are well preserved.";
  const bodyFinding = "Both exposed upper arms are visibly narrower than in PERSON.";
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async (module, output) => {
    let calls = 0;
    globalThis.fetch = async () => response(++calls === 1 ? primary : {
      artifact_present: "YES", artifact_severity: "MAJOR", artifact_reasons: [bodyFinding], notes: bodyFinding,
    });
    const result = await module.main();
    const record = result.report.results[0];
    assert.equal(calls, 2); assert.equal(record.rating.successful, "NO");
    assert.equal(record.rating.notes, bodyFinding); assert.deepEqual(record.rating.positives, []);
    assert.deepEqual(record.primary_rating.positives, primary.positives);
    assert.equal(record.primary_rating.notes, primary.notes);
    const html = fs.readFileSync(path.join(output, "index.html"), "utf8");
    assert(!html.includes("Body proportions are well preserved."));
    assert.match(html, /Earlier positive claims are withheld/);
  });
});

const contradictoryGlitter = JSON.parse(fs.readFileSync(path.join(repo, "tests/fixtures/contradictory-glitter-assessment.json"), "utf8"));

test("archived inconsistent glitter judgment is corrected once before audit", async () => {
  const root = path.join(temporary, "corrected-glitter"); makeCase(root, { category: "full" });
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async module => {
    const corrected = structuredClone(contradictoryGlitter);
    corrected.minor_issues.push(...corrected.critical_issues); corrected.critical_issues = [];
    const requests = [];
    globalThis.fetch = async (_url, options) => {
      const request = JSON.parse(options.body); requests.push(request);
      if (requests.length === 1) return response(contradictoryGlitter);
      if (requests.length === 2) {
        assert.equal(request.messages[1].role, "assistant");
        assert.deepEqual(JSON.parse(request.messages[1].content), contradictoryGlitter);
        assert.match(request.messages[2].content, /same images/);
        return response(corrected);
      }
      return response(cleanAudit());
    };
    const result = await module.main();
    assert.equal(result.exitCode, 0); assert.equal(result.summary.errors, 0); assert.equal(requests.length, 3);
    const record = result.report.results[0];
    assert.equal(record.assessment_attempts, 2); assert.equal(record.assessment_validation_errors.length, 1);
    assert.equal(record.assessment_validation_errors[0].code, "INCONSISTENT_SEVERITY");
    assert.equal(record.rating.quality_percent, 80); assert.equal(record.artifact_audit_status, "completed");
    assert(record.rating.minor_issues.includes(contradictoryGlitter.critical_issues[0]));
  });
});

test("a severity correction can confirm a major failure without forcing a pass", async () => {
  const root = path.join(temporary, "confirmed-glitter-failure"); makeCase(root, { category: "full" });
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async module => {
    const corrected = structuredClone(contradictoryGlitter); corrected.labels.garment_structure_error = "MAJOR";
    let calls = 0;
    globalThis.fetch = async () => response(++calls === 1 ? contradictoryGlitter : corrected);
    const result = await module.main();
    assert.equal(result.exitCode, 0); assert.equal(result.summary.failed, 1); assert.equal(calls, 2);
    const record = result.report.results[0];
    assert.equal(record.assessment_attempts, 2); assert.equal(record.rating.labels.garment_structure_error, "MAJOR");
    assert.equal(record.rating.quality_percent, 40); assert.equal(record.rating.successful, "NO");
    assert.deepEqual(record.rating.critical_issues, contradictoryGlitter.critical_issues);
  });
});

test("repeatedly inconsistent severity stops after one correction and preserves both replies", async () => {
  const root = path.join(temporary, "uncorrected-glitter"); makeCase(root);
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async module => {
    let calls = 0; globalThis.fetch = async () => { calls++; return response(contradictoryGlitter); };
    const result = await module.main();
    assert.equal(result.exitCode, 1); assert.equal(result.summary.errors, 1); assert.equal(calls, 2);
    const record = result.report.results[0];
    assert.equal(record.rating, null); assert.equal(record.assessment_attempts, 2);
    assert.equal(record.assessment_validation_errors.length, 2);
    assert(record.assessment_validation_errors.every(item => JSON.parse(item.raw_output_text).critical_issues[0] === contradictoryGlitter.critical_issues[0]));
  });
});

test("truncated judgments and missing original people are errors", async () => {
  for (const missingModel of [false, true]) {
    const root = path.join(temporary, `invalid-${missingModel}`); makeCase(root, { missingModel });
    await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async module => {
      let calls = 0; globalThis.fetch = async () => { calls++; return response(clean(), "length"); };
      const result = await module.main(); assert.equal(result.exitCode, 1); assert.equal(result.summary.errors, 1);
      assert.equal(calls, missingModel ? 0 : 1);
    });
  }
});

test("rate-limited main requests retry before completing both checks", async () => {
  const root = path.join(temporary, "retry"); makeCase(root);
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root, OPENAI_MAX_RETRIES: "2" }, async module => {
    let calls = 0;
    globalThis.fetch = async (_url, options) => {
      if (++calls === 1) return new Response("Rate limit", { status: 429, headers: { "retry-after": "0" } });
      return response(JSON.parse(options.body).response_format.json_schema.name === "tryon_artifact_audit" ? cleanAudit() : clean());
    };
    assert.equal((await module.main()).exitCode, 0); assert.equal(calls, 3);
  });
});

test("artifact provenance filters categories and prevents silent omissions", async () => {
  const root = path.join(temporary, "manifest"); makeCase(root); makeCase(root, { category: "lower" });
  fs.writeFileSync(path.join(root, "source-run.json"), JSON.stringify({ run_id: 123, artifact_id: 456, selected_categories: ["upper", "full"] }));
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root, ANALYSIS_REPORT_MODE: "gallery" }, async module => {
    const result = await module.main(); assert.equal(result.summary.total, 1); assert.equal(result.exitCode, 1);
    assert.match(result.summary.source_errors[0], /no full test cases/);
    assert.equal(result.report.results[0].source_run.run_id, 123);
  });
});

test("image URLs encode filename fragments and query characters", async () => {
  await withAnalyzer({}, async module => {
    const html = module.renderImageCard("Garment", "../test #1/garment?name.png");
    assert.match(html, /test%20%231\/garment%3Fname.png/);
  });
});

function reportEntry(garment, model, overrides = {}) {
  return {
    folder: `${garment}-${model}`, source_folder: `${garment}/${model}`,
    garment_filename: garment, garment_run_key: "full", model_filename: model,
    evaluation_ok: true, evaluation_mode: "llm", selenium_status: "success",
    ai_successful: "YES", quality_percent: 100, critical_issues: [], minor_issues: [], positives: [],
    files: {}, ...overrides,
  };
}

test("clothing groups keep all models together and average only completed judgments including zero", () => {
  const groups = groupByGarment([
    reportEntry("Blue dress.jpg", "Model 2.png", { quality_percent: 80, garment_category: "dress" }),
    reportEntry("Red coat.jpg", "Model 1.png"),
    reportEntry("Blue dress.jpg", "Model 1.png", { quality_percent: 0, ai_successful: "NO", garment_category: "outfit" }),
    reportEntry("Blue dress.jpg", "Model 3.png", { evaluation_mode: "generation_failed", selenium_status: "failed", ai_successful: null, quality_percent: null }),
    reportEntry("Blue dress.jpg", "Model 4.png", { evaluation_ok: false, ai_successful: null, quality_percent: null }),
  ]);
  assert.deepEqual(groups.map(group => group.name), ["Blue dress", "Red coat"]);
  assert.deepEqual(groups[0].entries.map(entry => entry.model_filename), ["Model 1.png", "Model 2.png", "Model 3.png", "Model 4.png"]);
  assert.deepEqual(groups[0].stats, { total: 4, model_count: 4, evaluated: 2, passed: 1, failed: 1, generation_failed: 1, errors: 1, skipped: 0, average_score: 40 });
});

test("missing garment names do not merge unrelated cases and intended transfer modes stay distinct", () => {
  const groups = groupByGarment([
    reportEntry(null, "Model 1.png", { source_folder: "case-one" }),
    reportEntry(null, "Model 2.png", { source_folder: "case-two" }),
    reportEntry("Coat.jpg", "Model 1.png", { garment_run_key: "upper" }),
    reportEntry("Coat.jpg", "Model 2.png", { garment_run_key: "full" }),
  ]);
  assert.equal(groups.length, 4);
});

test("common problems count cases once per theme and exclude failures, errors, notes and positives", () => {
  const summary = summarizeProblems([
    reportEntry("Blue dress.jpg", "Model 1.png", { critical_issues: ["arms slimmed", "upper arm thickness changed"], minor_issues: ["forearm shape changed", "Pocket details missing"] }),
    reportEntry("Red coat.jpg", "Model 2.png", { minor_issues: ["Arms slightly narrowed"], notes: "Face changed", positives: ["No background damage"] }),
    reportEntry("Clean shirt.jpg", "Model 3.png"),
    reportEntry("Blue dress.jpg", "Model 4.png", { evaluation_ok: false, ai_successful: null, critical_issues: ["Arms changed"] }),
    reportEntry("Blue dress.jpg", "Model 5.png", { evaluation_mode: "generation_failed", ai_successful: null, critical_issues: ["Arms changed"] }),
  ]);
  assert.equal(summary.evaluated_results, 3);
  assert.equal(summary.problems.length, 2);
  assert.equal(summary.problems[0].key, "arms");
  assert.equal(summary.problems[0].count, 2); assert.equal(summary.problems[0].critical_count, 1);
  assert.equal(summary.problems[0].minor_count, 1); assert.equal(summary.problems[0].garment_count, 2);
  assert.equal(summary.problems[0].percent, 67);
});

test("problem summary preserves unrecognized findings and distinguishes clothing details from body changes", () => {
  const summary = summarizeProblems([
    reportEntry("Dress.jpg", "Model 1.png", { minor_issues: ["Waist seam detail is missing", "Missing garment patch/logo"] }),
    reportEntry("Pants.jpg", "Model 2.png", { critical_issues: ["Original wide-leg, full-length silhouette is lost"] }),
    reportEntry("Shirt.jpg", "Model 3.png", { critical_issues: ["Shoulder width reduced", "Unexplained duplicate bag"] }),
  ]);
  assert.equal(summary.problems.find(problem => problem.key === "construction").count, 1);
  assert(summary.problems.some(problem => problem.key === "shape_length"));
  assert(summary.problems.some(problem => problem.key === "body_proportions"));
  assert(summary.problems.some(problem => problem.label === "Unexplained duplicate bag"));
  assert(!summary.problems.some(problem => problem.key === "legs" || problem.key === "garment_identity"));
});

test("rendered report puts problem highlights first and completes each garment before the next", async () => {
  await withAnalyzer({}, async module => {
    const entries = [
      reportEntry("Blue dress.jpg", "Model 2.png", { critical_issues: ["Arms slimmed"] }),
      reportEntry("Red coat.jpg", "Model 1.png", { minor_issues: ["<script>alert(1)</script>"] }),
      reportEntry("Blue dress.jpg", "Model 1.png", { critical_issues: ["Forearm shape changed"] }),
    ];
    const html = module.buildReviewHtml(entries, { total: 3, successful: 3, failed: 0, errors: 0, generation_failed: 0 }, { reportMode: "review", generatedAt: "2026-11-25" });
    assert(html.indexOf("Most common reported problems") < html.indexOf("Clothing overview"));
    const first = html.indexOf('class="garment-group" id="garment-1"');
    const second = html.indexOf('class="garment-group" id="garment-2"');
    assert(first > 0 && second > first);
    const blueGroup = html.slice(first, second);
    assert(blueGroup.indexOf("Model 1</h3>") < blueGroup.indexOf("Model 2</h3>"));
    assert(!html.includes("<script>alert(1)</script>"));
    assert(html.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
    assert(html.includes('href="#garment-1"'));
    assert(html.includes("2</strong><span>of 3 results"));
  });
});

test("saved reviews can be regrouped offline without changing judgments and retain their original evaluator settings", async () => {
  const root = path.join(temporary, "saved-review");
  const caseDirectory = makeCase(root, { name: "test_1_upper" });
  const inputDirectory = path.join(root, "outputs"); fs.mkdirSync(inputDirectory, { recursive: true });
  const relative = file => path.relative(root, file).replaceAll("\\", "/").replace("/test_1_upper/", "/test_1_upper /");
  const source = {
    generated_at: "2026-11-25", report_mode: "review", evaluator_model: "saved-evaluator", scoring_policy: { passScore: 75, maxMinorLabels: 2 },
    summary: { total: 1, successful: 1, failed: 0, errors: 0, generation_failed: 0 },
    results: [{
      folder: "test_1_upper", source_folder: relative(caseDirectory), evaluation_mode: "llm", ok: true,
      metadata: { garment_filename: "Saved coat.jpg", model_filename: "Saved model.png", garment_run_key: "upper", status: "success" },
      rating: { ...clean(), quality_percent: 80, successful: "YES", notes: "Keep this exact saved judgment." },
      files: Object.fromEntries(["model", "garment", "result"].map(role => [role, { relative_path: relative(path.join(caseDirectory, role, `${role}.png`)) }])),
    }],
  };
  const input = path.join(inputDirectory, "analysis.json"); fs.writeFileSync(input, JSON.stringify(source));
  await withAnalyzer({}, async () => {
    const { renderSavedReview } = await import("../scripts/render-review.mjs");
    const output = path.join(temporary, "regrouped-review");
    const result = renderSavedReview(input, output);
    assert.equal(result.missing_assets, 0); assert.equal(result.garments, 1);
    assert.deepEqual(result.report.results, source.results);
    assert.deepEqual(JSON.parse(fs.readFileSync(input, "utf8")), source);
    assert.equal(result.report.summary.by_garment[0].average_score, 80);
    const html = fs.readFileSync(path.join(output, "index.html"), "utf8");
    assert.match(html, /saved-evaluator/); assert.match(html, /Pass: 75%/);
    assert.match(html, /Keep this exact saved judgment/);
  });
});

const run = (id, branch = "openAi", quality = "standard") => ({ id, status: "completed", head_branch: branch, head_sha: "abc", display_title: `premium=${quality === "premium"} | turbo=${quality === "turbo"}`, html_url: `https://github.com/example/repo/actions/runs/${id}` });
const artifact = (id, keys, profile = "default") => ({ id, name: `siz3r-${keys}-${profile}-results`, expired: false });

test("manual assessment selects separate latest upper/lower/full runs", async () => {
  const artifacts = { 13: [artifact(113, "full")], 12: [artifact(112, "lower")], 11: [artifact(111, "upper")] };
  const selected = await selectArtifacts([run(11), run(13), run(12)], id => artifacts[id], { branch: "openAi" });
  assert.deepEqual(selected.map(item => item.run_id), [13, 12, 11]);
  assert.deepEqual(selected.map(item => item.selected_categories[0]), ["full", "lower", "upper"]);
});

test("latest-per-category avoids duplicate cases when one artifact covers several categories", async () => {
  const selected = await selectArtifacts([run(4), run(3)], id => id === 4 ? [artifact(40, "upper")] : [artifact(30, "all")]);
  assert.deepEqual(selected[0].selected_categories, ["upper"]);
  assert.deepEqual(selected[1].selected_categories, ["lower", "full"]);
});

test("branch, quality, profile and expiration filters cannot silently select another run", async () => {
  const candidates = [run(6, "other"), run(5, "openAi", "premium"), run(4), run(3)];
  const selected = await selectArtifacts(candidates, id => id === 4 ? [{ ...artifact(40, "all"), expired: true }] : [artifact(id * 10, "all")], { branch: "openAi", quality: "standard", profile: "default" });
  assert.equal(selected[0].run_id, 3);
  await assert.rejects(selectArtifacts([run(1)], () => [artifact(10, "upper")]), /lower, full/);
  await assert.rejects(selectArtifacts([run(1)], () => [artifact(10, "all")], { profile: "advanced_segmentation_free_30" }), /No matching/);
});

test("latest run, exact IDs and legacy names remain supported", async () => {
  const selected = await selectArtifacts([run(2), run(1)], () => [artifact(20, "upper")], { mode: "latest_run" });
  assert.equal(selected.length, 1); assert.equal(selected[0].run_id, 2);
  const legacy = await selectArtifacts([run(1)], () => [{ id: 10, name: "siz3r-test-results" }], { mode: "run_ids" });
  assert.equal(legacy[0].artifact_name, "siz3r-test-results");
  assert.deepEqual(parseRunIds("123,https://github.com/example/repo/actions/runs/456"), [123, 456]);
  assert.throws(() => parseRunIds("not-a-run"));
  assert.equal(artifactDetails(artifact(1, "upper,lower")).categories.length, 2);
});

test("ZIP entry validation prevents paths escaping the artifact directory", () => {
  const destination = path.join(temporary, "zip");
  validateArchiveEntries(["test_results_upper/test_1/metadata.json"], destination);
  for (const name of ["../escape", "/absolute", "C:/escape", "..\\escape"]) assert.throws(() => validateArchiveEntries([name], destination));
});

function coreStub() {
  const variables = {};
  const summary = { addHeading() { return this; }, addTable() { return this; }, async write() {} };
  return { variables, summary, info() {}, exportVariable(key, value) { variables[key] = value; } };
}

test("one pasted link downloads that exact run without searching newer runs", async () => {
  const root = path.join(temporary, "download");
  const core = coreStub();
  const github = {
    rest: { actions: {
      async getWorkflowRun({ run_id }) {
        assert.equal(run_id, 11);
        return { data: { ...run(11, "older-generation-branch"), path: ".github/workflows/selenium.yml", head_repository: { full_name: "example/repo" } } };
      },
      async listWorkflowRuns() { throw new Error("A linked assessment must not search for the latest run."); },
      listWorkflowRunArtifacts() {},
      async downloadArtifact({ artifact_id }) { assert.equal(artifact_id, 111); return { data: Buffer.from("test archive") }; },
    } },
    async paginate(_method, { run_id }) { assert.equal(run_id, 11); return [artifact(111, "upper")]; },
  };
  await withAnalyzer({}, async module => {
    const previous = process.env.ANALYSIS_RUN_URL;
    process.env.ANALYSIS_RUN_URL = "https://github.com/example/repo/actions/runs/11";
    try {
      const selected = await downloadArtifacts({ github, core, context: { eventName: "workflow_dispatch", ref: "refs/heads/main", repo: { owner: "example", repo: "repo" } }, workingDirectory: root,
        unpack(_zip, destination) { makeCase(destination, { category: "upper" }); },
      });
      assert.equal(selected.length, 1); assert.equal(selected[0].run_id, 11);
      assert.equal(core.variables.ANALYZE_SOURCE_DIR, path.join(root, "test_results"));
      const entries = module.collectSourceEntries([core.variables.ANALYZE_SOURCE_DIR]).entries;
      assert.equal(entries.length, 1); assert.equal(entries[0].sourceRun.run_id, 11);
      assert.equal(entries[0].sourceRun.branch, "older-generation-branch");
    } finally { if (previous === undefined) delete process.env.ANALYSIS_RUN_URL; else process.env.ANALYSIS_RUN_URL = previous; }
  });
});

test("run links accept normal copied URLs and reject missing or unrelated links", () => {
  const repo = { owner: "example", repo: "repo" };
  for (const suffix of ["", "/", "?check_suite_focus=true", "#artifacts", "/job/55", "/attempts/2"]) {
    assert.equal(parseRunUrl("https://github.com/example/repo/actions/runs/11" + suffix, repo), 11);
  }
  for (const link of ["", "11", "https://example.com/example/repo/actions/runs/11", "https://github.com/example/repo/actions", "https://github.com/example/repo/actions/runs/11,https://github.com/example/repo/actions/runs/12"]) {
    assert.throws(() => parseRunUrl(link, repo), /Paste a GitHub generation run link/);
  }
  assert.throws(() => parseRunUrl("https://github.com/other/repo/actions/runs/11", repo), /from this repository/);
});

test("completed model tests and other automatic events cannot start a judgment", async () => {
  const core = coreStub();
  let requests = 0;
  const github = {
    rest: { actions: {
      async getWorkflowRun() { requests++; throw new Error("Automatic events must not fetch results."); },
    } },
  };
  for (const eventName of ["workflow_run", "push", "repository_dispatch"]) {
    await assert.rejects(downloadArtifacts({ github, core,
      context: { eventName, ref: "refs/heads/main", repo: { owner: "example", repo: "repo" }, payload: { workflow_run: { id: 77 } } },
      workingDirectory: path.join(temporary, "automatic-event"), unpack() {},
    }), /must be started manually/);
  }
  assert.equal(requests, 0);
});

test("assessment workflow is valid YAML and includes all runtime dependencies", () => {
  const workflow = YAML.parseDocument(fs.readFileSync(path.join(repo, ".github/workflows/analyze-with-llm.yml"), "utf8"));
  assert.equal(workflow.errors.length, 0);
  const config = workflow.toJS();
  assert.equal(config.permissions.actions, "read");
  assert.deepEqual(Object.keys(config.on), ["workflow_dispatch"]);
  assert.equal(config.jobs.analyze.if, "github.event_name == 'workflow_dispatch'");
  assert.deepEqual(Object.keys(config.on.workflow_dispatch.inputs), ["run_url"]);
  assert.equal(config.on.workflow_dispatch.inputs.run_url.required, true);
  assert(config.jobs.analyze.steps.some(step => step.if === "always()"));
  assert(fs.existsSync(path.join(repo, ".github/scripts/analysis-artifacts.cjs")));
});

after(() => {
  const resolved = path.resolve(temporary);
  assert.equal(path.dirname(resolved), path.resolve(os.tmpdir()));
  assert(path.basename(resolved).startsWith("siz3r-assessment-"));
  fs.rmSync(resolved, { recursive: true, force: true });
});
