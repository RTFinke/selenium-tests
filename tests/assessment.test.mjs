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
import { embedReviewImages } from "../lib/review-images.js";
import {
  validateAndNormalizeRating, validateAssessmentVerification, parseRetryAfterMs,
  envNumber, fileToDataUrl,
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
const finding = (overrides = {}) => ({
  category: "artifact_error", subject: "BODY_SHAPE", severity: "MAJOR", confidence: "CONFIRMED",
  comparison_basis: "COMPARABLE_EXPOSED_SKIN",
  original_observation: "Exposed upper arm is broad between the same elbow and sleeve landmarks.",
  result_observation: "The same exposed upper arm is substantially narrower relative to the unchanged head.",
  clothing_or_pose_explanation_ruled_out: true,
  description: "The exposed upper arm is visibly slimmed.", ...overrides,
});
const contourFinding = (overrides = {}) => finding({
  comparison_basis: "COMPARABLE_BODY_CONTOUR",
  original_observation: "The thin original shirt follows a rounded lower abdomen between the same waistband and elbow landmarks.",
  result_observation: "The corresponding abdomen is materially flatter and narrower while the head, hands and trousers remain aligned.",
  description: "The readable lower-abdomen contour is substantially flattened and narrowed.",
  ...overrides,
  contour_evidence: {
    region: "lower abdomen and waist",
    original_surface: "BODY_FOLLOWING", result_surface: "BODY_FOLLOWING",
    scale_and_pose_comparable: true,
    landmark_corroboration: "The head size, hand positions and trouser waistband align, while the same waist and abdomen region narrows.",
    clothing_explanation_exclusion: "Both thin surfaces reveal the local body contour; removed fabric ease, padding, pose and lighting do not explain the material narrowing.",
    ...overrides.contour_evidence,
  },
});
const bodyShapeReview = () => Object.fromEntries(["chest", "waist_and_abdomen", "hips"].map(region => [region, {
  original_observation: `The saved test reply does not establish readable ${region} contour in the original.`,
  result_observation: `The saved test reply does not establish comparable ${region} contour in the result.`,
  original_surface: "UNCLEAR", result_surface: "UNCLEAR",
  comparison_basis: "NOT_COMPARABLE", conclusion: "NOT_COMPARABLE",
  explanation: "This offline fixture provides no regional visual comparison; preservation is not inferred.",
  finding_index: null,
}]));
const verification = (rating = clean(), overrides = {}) => ({
  garment_type: rating.garment_type, garment_category: rating.garment_category,
  intended_fit: rating.intended_fit, silhouette_preserved: rating.silhouette_preserved,
  coverage: {
    garment_design: "Target garment type, silhouette and visible design compared.",
    fit_and_drape: "Placement and natural fabric drape compared.",
    person_integrity: "Comparable identity and exposed anatomy checked; covered anatomy is not assessable.",
    scene_and_other_items: "Non-target items, boundaries and scene checked.",
  },
  body_shape_review: bodyShapeReview(),
  findings: Object.entries(rating.labels).filter(([, severity]) => severity !== "NONE").flatMap(([category, severity]) => {
    const issues = severity === "MAJOR" ? rating.critical_issues : rating.minor_issues;
    return (issues.length ? issues : [`Confirmed ${category} difference.`]).map(description => finding({
      category, severity, description, subject: category === "artifact_error" ? "SCENE_OR_BOUNDARY" : "GARMENT",
      comparison_basis: category === "artifact_error" ? "VISIBLE_OTHER" : "VISIBLE_GARMENT",
      original_observation: "The relevant reference feature is clearly visible.",
      result_observation: "The corresponding result feature visibly differs.",
    }));
  }),
  positives: rating.positives, notes: rating.notes, rejected_claims: [], ...overrides,
});
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
  const incomplete = verification(); delete incomplete.coverage.person_integrity;
  assert.equal(validateAssessmentVerification(incomplete).ok, false);
});

test("loose sleeves and covered chest contours cannot establish body reshaping", () => {
  for (const description of ["Sweater sleeves make arms appear thicker.", "Padded jacket chest appears broader."]) {
    const result = validateAssessmentVerification(verification(clean(), { findings: [finding({
      description, comparison_basis: "VISIBLE_GARMENT", clothing_or_pose_explanation_ruled_out: false,
    })] }));
    assert.equal(result.ok, true);
    assert.equal(result.rating.labels.artifact_error, "NONE");
    assert.equal(result.rating.quality_percent, 100); assert.equal(result.rating.successful, "YES");
    assert.deepEqual(result.rating.critical_issues, []);
    assert.equal(result.excluded_findings.length, 1);
  }
});

test("uncertain, hidden or unexplained anatomy comparisons do not receive body penalties", () => {
  for (const unsupported of [
    { confidence: "UNCERTAIN" },
    { comparison_basis: "NOT_COMPARABLE" },
    { clothing_or_pose_explanation_ruled_out: false },
    { original_observation: "" },
    { result_observation: "" },
  ]) {
    const result = validateAssessmentVerification(verification(clean(), { findings: [finding(unsupported)] }));
    assert.equal(result.ok, true);
    assert.equal(result.rating.labels.artifact_error, "NONE");
    assert.equal(result.excluded_findings.length, 1);
    assert.equal(result.rating.successful, "YES");
  }
});

test("confirmed comparable exposed anatomy and real anatomical landmarks still establish major damage", () => {
  for (const comparison_basis of ["COMPARABLE_EXPOSED_SKIN", "COMPARABLE_ANATOMICAL_LANDMARKS"]) {
    const result = validateAssessmentVerification(verification(clean(), { findings: [finding({ comparison_basis })] }));
    assert.equal(result.ok, true);
    assert.equal(result.rating.labels.artifact_error, "MAJOR");
    assert.equal(result.rating.quality_percent, 60); assert.equal(result.rating.successful, "NO");
    assert.deepEqual(result.rating.critical_issues, ["The exposed upper arm is visibly slimmed."]);
    assert.equal(result.excluded_findings.length, 0);
  }
});

test("confirmed body-following contour evidence can establish torso damage without exposed abdominal skin", () => {
  const torso = contourFinding();
  const result = validateAssessmentVerification(verification(clean(), { findings: [torso] }));
  assert.equal(result.ok, true);
  assert.equal(result.rating.labels.artifact_error, "MAJOR");
  assert.equal(result.rating.quality_percent, 60); assert.equal(result.rating.successful, "NO");
  assert.deepEqual(result.rating.critical_issues, [torso.description]);
  assert.equal(result.accepted_findings.length, 1); assert.equal(result.excluded_findings.length, 0);
});

test("a supported volume contradiction remains assessable when the target garment is oversized", () => {
  const torso = contourFinding({
    result_observation: "The generated oversized tee is boxy above the chest but its lower sides sit inside the original readable belly contour at matched scale.",
    contour_evidence: {
      result_surface: "INSUFFICIENT_SPACE_FOR_ORIGINAL_BODY",
      clothing_explanation_exclusion: "A loose soft tee could add room or obscure curvature, but its materially narrower lower outline cannot contain the original abdomen at the same scale; no compression, structured shaping or occlusion explains this.",
    },
  });
  const result = validateAssessmentVerification(verification(clean(), { intended_fit: "oversized", findings: [torso] }));
  assert.equal(result.ok, true);
  assert.equal(result.rating.labels.artifact_error, "MAJOR");
  assert.equal(result.rating.quality_percent, 60); assert.equal(result.rating.successful, "NO");
  assert.deepEqual(result.rating.critical_issues, [torso.description]);
});

test("loose, padded or unreadable outlines and unsupported contour comparisons cannot establish body damage", () => {
  for (const unsupported of [
    { contour_evidence: { original_surface: "LOOSE_OR_STRUCTURED" } },
    { contour_evidence: { original_surface: "UNCLEAR" } },
    { contour_evidence: { result_surface: "LOOSE_OR_STRUCTURED" } },
    { contour_evidence: { result_surface: "UNCLEAR" } },
    { contour_evidence: { scale_and_pose_comparable: false } },
    { contour_evidence: { landmark_corroboration: " " } },
    { contour_evidence: { clothing_explanation_exclusion: " " } },
    { contour_evidence: { region: " " } },
    { confidence: "UNCERTAIN" },
    { clothing_or_pose_explanation_ruled_out: false },
    { original_observation: "" },
    { result_observation: "" },
  ]) {
    const result = validateAssessmentVerification(verification(clean(), { findings: [contourFinding(unsupported)] }));
    assert.equal(result.ok, true, JSON.stringify(unsupported));
    assert.equal(result.rating.labels.artifact_error, "NONE", JSON.stringify(unsupported));
    assert.equal(result.rating.quality_percent, 100); assert.equal(result.rating.successful, "YES");
    assert.deepEqual(result.rating.critical_issues, []);
    assert.equal(result.accepted_findings.length, 0); assert.equal(result.excluded_findings.length, 1);
  }
});

test("the body-contour schema requires its evidence and cannot be relabelled as a garment or identity claim", () => {
  const missingEvidence = contourFinding(); delete missingEvidence.contour_evidence;
  const missingScale = contourFinding(); delete missingScale.contour_evidence.scale_and_pose_comparable;
  for (const invalid of [
    missingEvidence, missingScale,
    contourFinding({ category: "fit_error" }),
    contourFinding({ subject: "GARMENT" }),
    contourFinding({ subject: "IDENTITY_OR_ANATOMY" }),
  ]) {
    assert.equal(validateAssessmentVerification(verification(clean(), { findings: [invalid] })).ok, false);
  }
});

test("verification retains garment defects when rejecting a clothing-only body claim", () => {
  const wrongPrint = finding({ category: "garment_structure_error", subject: "GARMENT", comparison_basis: "VISIBLE_GARMENT", description: "The target's large striped print is replaced with a plain surface." });
  const result = validateAssessmentVerification(verification(clean(), { findings: [
    finding({ comparison_basis: "VISIBLE_GARMENT", description: "Loose sleeve outline appears thicker." }), wrongPrint,
  ] }));
  assert.equal(result.ok, true);
  assert.equal(result.rating.labels.artifact_error, "NONE");
  assert.equal(result.rating.labels.garment_structure_error, "MAJOR");
  assert.equal(result.rating.quality_percent, 40); assert.equal(result.rating.successful, "NO");
  assert.deepEqual(result.rating.critical_issues, [wrongPrint.description]);
});

test("malformed hands and damaged non-target items are actionable without a body-size inference", () => {
  for (const [subject, description] of [
    ["IDENTITY_OR_ANATOMY", "Generated hand has fused fingers and an extra thumb."],
    ["NON_TARGET_ITEM", "The original shoes are erased despite remaining outside the transferred top."],
    ["SCENE_OR_BOUNDARY", "The generated sleeve merges visibly into the background wall."],
  ]) {
    const result = validateAssessmentVerification(verification(clean(), { findings: [finding({ subject, description, comparison_basis: "VISIBLE_OTHER", clothing_or_pose_explanation_ruled_out: false })] }));
    assert.equal(result.ok, true);
    assert.equal(result.rating.labels.artifact_error, "MAJOR");
    assert.equal(result.rating.successful, "NO");
    assert.deepEqual(result.rating.critical_issues, [description]);
  }
});

test("body findings cannot evade evidence checks through a garment scoring category", () => {
  const result = validateAssessmentVerification(verification(clean(), { findings: [finding({ category: "fit_error" })] }));
  assert.equal(result.ok, false);
});

test("visible garment blending can receive an artifact penalty while fabric contours cannot establish body damage", () => {
  const boundary = finding({
    subject: "GARMENT", category: "artifact_error", severity: "MINOR", comparison_basis: "VISIBLE_GARMENT",
    original_observation: "The original wrist is cleanly separated from the clothing cuff.",
    result_observation: "The sweater cuff visibly smears into the hand at the wrist.",
    description: "Visible blending at the sweater cuff and hand boundary.",
  });
  const bodyWidth = finding({ comparison_basis: "VISIBLE_GARMENT", description: "Loose sleeves make the covered arms appear thicker." });
  const result = validateAssessmentVerification(verification(clean(), { findings: [boundary, bodyWidth] }));
  assert.equal(result.ok, true);
  assert.equal(result.rating.labels.artifact_error, "MINOR");
  assert.equal(result.rating.quality_percent, 95); assert.equal(result.rating.successful, "YES");
  assert.deepEqual(result.rating.critical_issues, []);
  assert.deepEqual(result.rating.minor_issues, [boundary.description]);
  assert.equal(result.excluded_findings.length, 1);
  assert.equal(result.excluded_findings[0].subject, "BODY_SHAPE");
});

test("saved sweater and jacket verification replies retain minor boundary artifacts without inventing body changes", () => {
  const fixture = JSON.parse(fs.readFileSync(path.join(repo, "tests/fixtures/verification-clothing-boundaries.json"), "utf8"));
  assert.deepEqual(fixture.cases.map(item => item.test_number), [90, 119]);
  for (const item of fixture.cases) {
    // Preserve historical replies; supply explicit limits for the regional
    // comparisons that their older response format did not record.
    const result = validateAssessmentVerification({ ...item.verification, body_shape_review: bodyShapeReview() });
    assert.equal(result.ok, true);
    assert.equal(result.rating.labels.artifact_error, "MINOR");
    assert.equal(result.rating.labels.construction_alignment_error, "MINOR");
    assert.equal(result.rating.quality_percent, 80); assert.equal(result.rating.successful, "YES");
    assert.deepEqual(result.rating.critical_issues, []);
    assert.equal(result.rating.minor_issues.length, 2);
    assert(result.accepted_findings.every(finding => finding.subject !== "BODY_SHAPE"));
    assert.equal(result.excluded_findings.length, 0);
  }
});

test("an evidence basis cannot score a different subject merely by having a confirmed severity", () => {
  for (const [subject, category, comparison_basis] of [
    ["GARMENT", "garment_structure_error", "COMPARABLE_EXPOSED_SKIN"],
    ["BODY_SHAPE", "artifact_error", "VISIBLE_OTHER"],
    ["IDENTITY_OR_ANATOMY", "artifact_error", "VISIBLE_GARMENT"],
    ["NON_TARGET_ITEM", "artifact_error", "VISIBLE_GARMENT"],
    ["SCENE_OR_BOUNDARY", "artifact_error", "VISIBLE_GARMENT"],
  ]) {
    const result = validateAssessmentVerification(verification(clean(), { findings: [finding({ subject, category, comparison_basis })] }));
    assert.equal(result.ok, true);
    assert.equal(result.excluded_findings.length, 1);
    assert.equal(result.rating.labels[category], "NONE");
    assert.equal(result.rating.quality_percent, 100);
    assert.deepEqual(result.rating.critical_issues, []);
  }
});

test("verification requires nonempty coverage for clothing, fit, person and scene", () => {
  for (const area of ["garment_design", "fit_and_drape", "person_integrity", "scene_and_other_items"]) {
    const incomplete = verification(); incomplete.coverage[area] = "  ";
    assert.equal(validateAssessmentVerification(incomplete).ok, false);
  }
});

test("a generic person-preserved assertion cannot replace mandatory regional body comparisons", () => {
  const missing = verification(); delete missing.body_shape_review;
  assert.equal(validateAssessmentVerification(missing).ok, false);
  for (const region of ["chest", "waist_and_abdomen", "hips"]) {
    const incomplete = verification(); delete incomplete.body_shape_review[region];
    assert.equal(validateAssessmentVerification(incomplete).ok, false);
    for (const field of ["original_observation", "result_observation", "explanation"]) {
      const empty = verification(); empty.body_shape_review[region][field] = " ";
      assert.equal(validateAssessmentVerification(empty).ok, false);
    }
    const hidden = verification(); hidden.body_shape_review[region].conclusion = "NO_MATERIAL_CHANGE";
    assert.equal(validateAssessmentVerification(hidden).ok, false);
  }
  const comparable = verification();
  comparable.body_shape_review.chest = {
    original_observation: "The original thin top reveals chest fullness above the waistband.",
    result_observation: "The result reveals similar fullness and torso transitions relative to head and hips.",
    original_surface: "BODY_FOLLOWING", result_surface: "BODY_FOLLOWING",
    comparison_basis: "COMPARABLE_BODY_CONTOUR", conclusion: "NO_MATERIAL_CHANGE",
    explanation: "Comparable pose and local body-following fabric support the same shape despite different seams.",
    finding_index: null,
  };
  const result = validateAssessmentVerification(comparable);
  assert.equal(result.ok, true); assert.equal(result.rating.successful, "YES");
  assert.equal(result.rating.quality_percent, 100);
  for (const surface of ["LOOSE_OR_STRUCTURED", "UNCLEAR", "INSUFFICIENT_SPACE_FOR_ORIGINAL_BODY"]) {
    const concealed = structuredClone(comparable); concealed.body_shape_review.chest.result_surface = surface;
    assert.equal(validateAssessmentVerification(concealed).ok, false);
  }
  const concealedOriginal = structuredClone(comparable); concealedOriginal.body_shape_review.chest.original_surface = "LOOSE_OR_STRUCTURED";
  assert.equal(validateAssessmentVerification(concealedOriginal).ok, false);
  const clothAsAnatomy = structuredClone(comparable); clothAsAnatomy.body_shape_review.chest.comparison_basis = "COMPARABLE_ANATOMICAL_LANDMARKS";
  assert.equal(validateAssessmentVerification(clothAsAnatomy).ok, false);
});

test("confirmed regional flattening must link to a supported major body finding rather than silently pass", () => {
  const torso = contourFinding();
  const review = verification(clean(), { findings: [torso] });
  review.body_shape_review.waist_and_abdomen = {
    original_observation: torso.original_observation, result_observation: torso.result_observation,
    original_surface: "BODY_FOLLOWING", result_surface: "BODY_FOLLOWING",
    comparison_basis: torso.comparison_basis, conclusion: "MATERIAL_CHANGE",
    explanation: torso.contour_evidence.clothing_explanation_exclusion, finding_index: 0,
  };
  const result = validateAssessmentVerification(review);
  assert.equal(result.ok, true); assert.equal(result.rating.successful, "NO");
  assert.equal(result.rating.labels.artifact_error, "MAJOR");
  for (const index of [null, -1, 1, 0.5, "0"]) {
    const invalid = structuredClone(review); invalid.body_shape_review.waist_and_abdomen.finding_index = index;
    assert.equal(validateAssessmentVerification(invalid).ok, false, String(index));
  }
  for (const overrides of [
    { severity: "MINOR" }, { confidence: "UNCERTAIN" },
    { clothing_or_pose_explanation_ruled_out: false },
    { contour_evidence: { result_surface: "LOOSE_OR_STRUCTURED" } },
  ]) {
    const invalid = structuredClone(review); invalid.findings = [contourFinding(overrides)];
    assert.equal(validateAssessmentVerification(invalid).ok, false, JSON.stringify(overrides));
  }
  const wrongBasis = structuredClone(review);
  wrongBasis.body_shape_review.waist_and_abdomen.comparison_basis = "COMPARABLE_EXPOSED_SKIN";
  assert.equal(validateAssessmentVerification(wrongBasis).ok, false);
  const wrongSubject = structuredClone(review);
  wrongSubject.findings = [finding({ subject: "GARMENT", comparison_basis: "VISIBLE_GARMENT" })];
  assert.equal(validateAssessmentVerification(wrongSubject).ok, false);
  const noChange = structuredClone(review);
  noChange.body_shape_review.waist_and_abdomen.conclusion = "NO_MATERIAL_CHANGE";
  assert.equal(validateAssessmentVerification(noChange).ok, false);
  const mismatched = structuredClone(review);
  mismatched.findings[0].contour_evidence.result_surface = "INSUFFICIENT_SPACE_FOR_ORIGINAL_BODY";
  assert.equal(validateAssessmentVerification(mismatched).ok, false);
  mismatched.body_shape_review.waist_and_abdomen.result_surface = "INSUFFICIENT_SPACE_FOR_ORIGINAL_BODY";
  assert.equal(validateAssessmentVerification(mismatched).ok, true);
});

test("confirmed material body damage cannot use a minor label even without a regional link", () => {
  const result = validateAssessmentVerification(verification(clean(), { findings: [finding({ severity: "MINOR" })] }));
  assert.equal(result.ok, false); assert.match(result.error, /requires MAJOR/);
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
    assert(!html.includes("data-review-image=")); // Generation galleries retain their original images.
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

test("passing cases include full context, structured output and balanced verification", async () => {
  const root = path.join(temporary, "success"); makeCase(root, { category: "full" }); makeCase(root, { category: "full", failed: true });
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async (module, output) => {
    const requests = [];
    globalThis.fetch = async (_url, options) => {
      const request = JSON.parse(options.body); requests.push(request);
      const primary = { ...clean(), garment_category: "outfit" };
      return response(request.response_format.json_schema.name === "tryon_assessment_verification" ? verification(primary) : primary);
    };
    const result = await module.main();
    assert.equal(result.exitCode, 0); assert.equal(result.summary.successful, 1); assert.equal(result.summary.generation_failed, 1); assert.equal(requests.length, 2);
    assert(requests.every(request => request.response_format.type === "json_schema" && request.response_format.json_schema.strict));
    assert(requests.every(request => request.messages[0].content.filter(part => part.type === "image_url").length === 3));
    assert(requests.every(request => request.messages[0].content.filter(part => part.type === "image_url").every(part => part.image_url.detail === "high")));
    assert(requests.every(request => request.messages[0].content.filter(part => part.type === "image_url").every(part => part.image_url.url === `data:image/png;base64,${png.toString("base64")}`)));
    assert(requests.every(request => request.messages[0].content.some(part => part.type === "text" && part.text.includes("Transfer mode: FULL") && part.text.includes("turbo"))));
    assert.equal(requests[0].messages[0].content[0].text, fs.readFileSync(path.join(repo, "prompts/tryon-judgment.txt"), "utf8").trim());
    assert.equal(requests[1].messages[0].content[0].text, fs.readFileSync(path.join(repo, "prompts/tryon-integrity-audit.txt"), "utf8").trim());
    assert(requests[1].messages[0].content.some(part => part.type === "text" && /"garment_category"\s*:\s*"outfit"/.test(part.text)));
    assert.equal(result.report.prompts.judgment.file, "prompts/tryon-judgment.txt");
    assert.match(result.report.prompts.integrity_audit.sha256, /^[a-f0-9]{64}$/);
    const html = fs.readFileSync(path.join(output, "index.html"), "utf8");
    assert.match(html, /Quality: turbo/); assert.match(html, /Steps: 30/); assert.match(html, /Generation timed out/);
    assert.equal((html.match(/data-review-image=/g) || []).length, 3);
    assert.equal(Object.keys(JSON.parse(html.match(/id="review-images" type="application\/json">(.*?)<\/script>/s)[1])).length, 1);
    assert.equal(result.report.results.find(record => record.rating).metadata.flat_enabled, true);
  });
});

test("the default verification catches exposed arm damage even when clothing details already failed", async () => {
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
      return response(request.response_format.json_schema.name === "tryon_assessment_verification"
        ? verification(previous, { findings: [finding({ description: bodyFinding }), ...verification(previous).findings], notes: bodyFinding })
        : previous);
    };
    const result = await module.main();
    const record = result.report.results[0];
    assert.equal(calls, 2); assert.equal(result.exitCode, 0);
    assert.equal(record.verification_status, "completed");
    assert.equal(record.rating.labels.artifact_error, "MAJOR");
    assert.equal(record.rating.critical_issues[0], bodyFinding);
    assert(record.rating.notes.startsWith(bodyFinding));
  });
});

test("balanced verification can add a missed torso-contour failure while retaining an independent garment detail", async () => {
  const root = path.join(temporary, "missed-torso-contour"); makeCase(root);
  const primary = clean();
  primary.labels.construction_alignment_error = "MINOR";
  primary.minor_issues = ["The target cuff stripe is misplaced."];
  const torso = contourFinding({ contour_evidence: { result_surface: "INSUFFICIENT_SPACE_FOR_ORIGINAL_BODY" } });
  const cuff = finding({ category: "construction_alignment_error", subject: "GARMENT", severity: "MINOR", comparison_basis: "VISIBLE_GARMENT", description: primary.minor_issues[0] });
  const finalReview = verification(primary, { findings: [torso, structuredClone(torso), cuff] });
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root, ANALYZE_ENABLE_ARTIFACT_AUDIT: "true" }, async (module, output) => {
    let calls = 0; globalThis.fetch = async () => response(++calls === 1 ? primary : finalReview);
    const result = await module.main();
    const record = result.report.results[0];
    assert.equal(result.exitCode, 0); assert.equal(calls, 2);
    assert.equal(record.primary_rating.labels.artifact_error, "NONE");
    assert.equal(record.rating.labels.artifact_error, "MAJOR");
    assert.equal(record.rating.labels.construction_alignment_error, "MINOR");
    assert.equal(record.rating.labels.fit_error, "NONE");
    assert.equal(record.rating.quality_percent, 45); assert.equal(record.rating.successful, "NO");
    assert.deepEqual(record.rating.critical_issues, [torso.description]);
    assert.deepEqual(record.rating.minor_issues, [cuff.description]);
    const html = fs.readFileSync(path.join(output, "index.html"), "utf8");
    assert.match(html, /lower-abdomen contour/); assert.match(html, /target cuff stripe/);
  });
});

test("lost chest and waist curves in a fitted shirt fail an initially passing review with one body penalty", async () => {
  const root = path.join(temporary, "flattened-shirt"); makeCase(root);
  const primary = clean();
  primary.labels.construction_alignment_error = "MINOR"; primary.labels.artifact_error = "MINOR";
  primary.minor_issues = ["Cuff details are blurred.", "Minor waistband blending."];
  const torso = contourFinding({
    original_observation: "The original body-following black top reveals chest fullness and a rounded waist transition above the jeans.",
    result_observation: "The fitted denim shirt follows a flatter chest and straighter waist at comparable head, hand and hip scale.",
    description: "Chest and waist curves are materially flattened after try-on.",
    contour_evidence: { region: "chest and waist", clothing_explanation_exclusion: 'Local body-following fabric reveals the lost fullness; fabric bridging, compression, scale & pose do not explain it. <script>untrusted</script>' },
  });
  const cuff = finding({ subject: "GARMENT", category: "construction_alignment_error", comparison_basis: "VISIBLE_GARMENT", severity: "MINOR", description: primary.minor_issues[0] });
  const finalReview = verification(primary, { findings: [torso, cuff], positives: ["Denim collar and chest pockets match the target."] });
  for (const region of ["chest", "waist_and_abdomen"]) finalReview.body_shape_review[region] = {
    original_observation: torso.original_observation, result_observation: torso.result_observation,
    original_surface: "BODY_FOLLOWING", result_surface: "BODY_FOLLOWING",
    comparison_basis: "COMPARABLE_BODY_CONTOUR", conclusion: "MATERIAL_CHANGE",
    explanation: torso.contour_evidence.clothing_explanation_exclusion, finding_index: 0,
  };
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async (module, output) => {
    let calls = 0; globalThis.fetch = async () => response(++calls === 1 ? primary : finalReview);
    const result = await module.main(); const record = result.report.results[0];
    assert.equal(result.exitCode, 0); assert.equal(calls, 2); assert.equal(result.report.schema_version, 4);
    assert.equal(record.primary_rating.successful, "YES"); assert.equal(record.primary_rating.quality_percent, 80);
    assert.equal(record.rating.successful, "NO"); assert.equal(record.rating.quality_percent, 45);
    assert.equal(record.rating.labels.artifact_error, "MAJOR"); assert.equal(record.rating.labels.fit_error, "NONE");
    assert.deepEqual(record.rating.critical_issues, [torso.description]);
    assert.deepEqual(record.verification.body_shape_review, finalReview.body_shape_review);
    const html = fs.readFileSync(path.join(output, "index.html"), "utf8");
    assert.match(html, /Body shape comparison/); assert.match(html, /Chest: Material change confirmed/);
    assert.match(html, /Waist and abdomen: Material change confirmed/); assert.match(html, /Hips: Not comparable/);
    assert.match(html, /Garment silhouette:/); assert.match(html, /scale &amp; pose/);
    assert.match(html, /&lt;script&gt;untrusted&lt;\/script&gt;/); assert(!html.includes("<script>untrusted</script>"));
  });
});

test("failed verification never leaves a successful score", async () => {
  const root = path.join(temporary, "audit-failure"); makeCase(root);
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async (module, output) => {
    let calls = 0;
    globalThis.fetch = async () => ++calls === 1 ? response(clean()) : new Response("Verification unavailable", { status: 401 });
    const result = await module.main();
    assert.equal(result.exitCode, 1); assert.equal(result.summary.successful, 0);
    assert.equal(result.report.results[0].rating, null); assert.match(result.report.results[0].verification_error, /401/);
    const html = fs.readFileSync(path.join(output, "index.html"), "utf8");
    assert.match(html, /verification failed/); assert(!html.includes("Score: 100"));
  });
});

test("confirmed body damage replaces contradictory prose while retaining valid garment strengths", async () => {
  const root = path.join(temporary, "conflicting-body-claims"); makeCase(root);
  const primary = clean();
  primary.positives = ["Person's face and body proportions are well preserved."];
  primary.notes = "Body proportions are well preserved.";
  const bodyFinding = "Both exposed upper arms are visibly narrower than in PERSON.";
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async (module, output) => {
    let calls = 0;
    const finalReview = verification(primary, { findings: [finding({ description: bodyFinding })], notes: bodyFinding, positives: ["The target vest's quilting and zipper are preserved."] });
    globalThis.fetch = async () => response(++calls === 1 ? primary : finalReview);
    const result = await module.main();
    const record = result.report.results[0];
    assert.equal(calls, 2); assert.equal(record.rating.successful, "NO");
    assert.equal(record.rating.notes, bodyFinding); assert.deepEqual(record.rating.positives, finalReview.positives);
    assert.deepEqual(record.primary_rating.positives, primary.positives);
    assert.equal(record.primary_rating.notes, primary.notes);
    const html = fs.readFileSync(path.join(output, "index.html"), "utf8");
    assert(!html.includes("Body proportions are well preserved."));
    assert.match(html, /quilting and zipper are preserved/);
    assert(!html.includes("Earlier positive claims are withheld"));
  });
});

test("verification can retract a first-pass sleeve-body false positive without preserving its penalty or prose", async () => {
  const root = path.join(temporary, "rejected-sleeve-claim"); makeCase(root);
  const primary = clean();
  primary.labels.artifact_error = "MAJOR";
  primary.critical_issues = ["The upper arms became thicker inside the sweater sleeves."];
  primary.notes = primary.critical_issues[0];
  const finalReview = verification(clean(), {
    notes: "Loose sleeves account for the wider contour; covered upper-arm shape cannot be assessed. The target sweater is preserved.",
    rejected_claims: ["The claimed upper-arm enlargement is unsupported because only the clothing outline is visible."],
  });
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root, ANALYZE_ENABLE_ARTIFACT_AUDIT: "true" }, async (module, output) => {
    let calls = 0;
    globalThis.fetch = async () => response(++calls === 1 ? primary : finalReview);
    const result = await module.main();
    const record = result.report.results[0];
    assert.equal(calls, 2); assert.equal(result.exitCode, 0);
    assert.equal(record.verification_status, "completed");
    assert.equal(record.primary_rating.labels.artifact_error, "MAJOR");
    assert.equal(record.rating.labels.artifact_error, "NONE");
    assert.equal(record.rating.successful, "YES"); assert.equal(record.rating.quality_percent, 100);
    assert.deepEqual(record.rating.critical_issues, []);
    assert.deepEqual(record.verification.rejected_claims, finalReview.rejected_claims);
    assert(!fs.readFileSync(path.join(output, "index.html"), "utf8").includes(primary.notes));
  });
});

test("balanced verification finds a missed major garment defect even when the first pass says the person is preserved", async () => {
  const root = path.join(temporary, "missed-garment-defect"); makeCase(root);
  const wrongGarment = finding({
    category: "garment_structure_error", subject: "GARMENT", comparison_basis: "VISIBLE_GARMENT",
    original_observation: "The target is a jacket with a large contrasting check pattern.",
    result_observation: "The result is a plain jacket with the check pattern entirely missing.",
    description: "The target jacket's defining check pattern is missing.",
  });
  const finalReview = verification(clean(), { findings: [wrongGarment], notes: wrongGarment.description });
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async module => {
    let calls = 0;
    globalThis.fetch = async () => response(++calls === 1 ? clean() : finalReview);
    const result = await module.main();
    const record = result.report.results[0];
    assert.equal(calls, 2); assert.equal(result.exitCode, 0);
    assert.equal(record.rating.labels.artifact_error, "NONE");
    assert.equal(record.rating.labels.garment_structure_error, "MAJOR");
    assert.equal(record.rating.successful, "NO"); assert.equal(record.rating.quality_percent, 40);
    assert.deepEqual(record.rating.critical_issues, [wrongGarment.description]);
  });
});

test("an incomplete verification cannot silently reuse a passing first assessment", async () => {
  const root = path.join(temporary, "incomplete-verification"); makeCase(root);
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async module => {
    const incomplete = verification(); delete incomplete.coverage.scene_and_other_items;
    let calls = 0; globalThis.fetch = async () => response(++calls === 1 ? clean() : incomplete);
    const result = await module.main();
    const record = result.report.results[0];
    assert.equal(calls, 2); assert.equal(result.exitCode, 1);
    assert.equal(record.rating, null); assert.match(record.verification_error, /scene_and_other_items/);
    assert.equal(record.primary_rating.successful, "YES");
  });
});

test("unsupported free-form verifier accusations remain diagnostic and cannot contradict a clean scored verdict", async () => {
  const root = path.join(temporary, "unsupported-verifier-prose"); makeCase(root);
  const accusation = "Both arms and the covered chest were substantially reshaped by the generation.";
  const finalReview = verification(clean(), { findings: [], notes: accusation });
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async (module, output) => {
    let calls = 0; globalThis.fetch = async () => response(++calls === 1 ? clean() : finalReview);
    const result = await module.main();
    const record = result.report.results[0];
    assert.equal(calls, 2); assert.equal(result.exitCode, 0);
    assert.equal(record.rating.successful, "YES"); assert.equal(record.rating.quality_percent, 100);
    assert.deepEqual(record.rating.critical_issues, []); assert.deepEqual(record.rating.minor_issues, []);
    assert.match(record.rating.notes, /No confirmed actionable defects/);
    assert(!record.rating.notes.includes(accusation));
    assert.equal(record.verification.notes, accusation);
    assert(!fs.readFileSync(path.join(output, "index.html"), "utf8").includes(accusation));
  });
});

test("review evidence is escaped and separate from scored findings while legacy entries remain compatible", async () => {
  const root = path.join(temporary, "review-evidence"); makeCase(root);
  const coverage = 'Covered <script>alert("coverage")</script> & not comparable.';
  const rejected = 'Rejected <img src=x onerror="alert(1)"> sleeve-width claim.';
  const unsupported = 'Unsupported <svg onload="alert(2)"> covered chest-width claim.';
  const scoredIssue = "The target's contrasting cuff stripe is visibly shortened.";
  const finalReview = verification();
  finalReview.coverage.person_integrity = coverage;
  finalReview.rejected_claims = [rejected];
  finalReview.findings = [
    finding({ description: unsupported, comparison_basis: "VISIBLE_GARMENT" }),
    finding({ category: "construction_alignment_error", subject: "GARMENT", severity: "MINOR", comparison_basis: "VISIBLE_GARMENT", description: scoredIssue }),
  ];
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async (module, output) => {
    let calls = 0; globalThis.fetch = async () => response(++calls === 1 ? clean() : finalReview);
    const result = await module.main();
    const record = result.report.results[0];
    assert.equal(result.exitCode, 0); assert.equal(calls, 2);
    assert.deepEqual(record.rating.critical_issues, []);
    assert.deepEqual(record.rating.minor_issues, [scoredIssue]);
    assert.equal(record.rating.quality_percent, 85);
    assert.equal(record.excluded_findings.length, 1);
    const html = fs.readFileSync(path.join(output, "index.html"), "utf8");
    const details = html.match(/<details class="review-evidence">[\s\S]*?<\/details>/);
    assert(details); assert.match(details[0], /Review evidence and limitations/);
    assert.match(details[0], /&lt;script&gt;alert\(&quot;coverage&quot;\)&lt;\/script&gt; &amp; not comparable/);
    assert.match(details[0], /Rejected &lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/);
    assert.match(details[0], /Unsupported &lt;svg onload=&quot;alert\(2\)&quot;&gt;/);
    assert(!html.includes(coverage)); assert(!html.includes(rejected)); assert(!html.includes(unsupported));
    const scoredHtml = html.replace(details[0], "");
    assert(!scoredHtml.includes("coverage&quot;"));
    assert(!scoredHtml.includes("sleeve-width claim")); assert(!scoredHtml.includes("covered chest-width claim"));
    const legacyHtml = module.buildReviewHtml([reportEntry("Legacy coat.jpg", "Legacy model.png")],
      { total: 1, successful: 1, failed: 0, errors: 0, generation_failed: 0 }, { reportMode: "review", generatedAt: "2026-11-25" });
    assert(!legacyHtml.includes('class="review-evidence"'));
  });
});

test("body-contour corroboration and clothing explanations appear escaped in the HTML evidence", async () => {
  const root = path.join(temporary, "torso-contour-html"); makeCase(root);
  const corroboration = 'Head & hands align; <script>alert("landmarks")</script> is untrusted text.';
  const exclusion = 'Fabric ease cannot explain this <svg onload="alert(1)"> contour difference.';
  const torso = contourFinding({ contour_evidence: { landmark_corroboration: corroboration, clothing_explanation_exclusion: exclusion } });
  const finalReview = verification(clean(), { findings: [torso] });
  await withAnalyzer({ ANALYZE_SOURCE_DIR: root }, async (module, output) => {
    let calls = 0; globalThis.fetch = async () => response(++calls === 1 ? clean() : finalReview);
    const result = await module.main();
    assert.equal(result.exitCode, 0); assert.equal(calls, 2);
    const html = fs.readFileSync(path.join(output, "index.html"), "utf8");
    const details = html.match(/<details class="review-evidence">[\s\S]*?<\/details>/);
    assert(details);
    assert.match(details[0], /Reference: The thin original shirt follows a rounded lower abdomen/);
    assert.match(details[0], /Result: The corresponding abdomen is materially flatter and narrower/);
    assert.match(details[0], /Head &amp; hands align; &lt;script&gt;alert\(&quot;landmarks&quot;\)&lt;\/script&gt;/);
    assert.match(details[0], /Fabric ease cannot explain this &lt;svg onload=&quot;alert\(1\)&quot;&gt;/);
    assert(!html.includes(corroboration)); assert(!html.includes(exclusion));
    const verdict = html.replace(details[0], "");
    assert(!verdict.includes("landmarks&quot;")); assert(!verdict.includes("Fabric ease cannot explain"));
  });
});

const contradictoryGlitter = JSON.parse(fs.readFileSync(path.join(repo, "tests/fixtures/contradictory-glitter-assessment.json"), "utf8"));

test("archived inconsistent glitter judgment is corrected once before verification", async () => {
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
      return response(verification(corrected));
    };
    const result = await module.main();
    assert.equal(result.exitCode, 0); assert.equal(result.summary.errors, 0); assert.equal(requests.length, 3);
    const record = result.report.results[0];
    assert.equal(record.assessment_attempts, 2); assert.equal(record.assessment_validation_errors.length, 1);
    assert.equal(record.assessment_validation_errors[0].code, "INCONSISTENT_SEVERITY");
    assert.equal(record.rating.quality_percent, 80); assert.equal(record.verification_status, "completed");
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
      return response(JSON.parse(options.body).response_format.json_schema.name === "tryon_assessment_verification" ? verification() : clean());
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

test("portable reviews resize and deduplicate display images without modifying source images or entries", async () => {
  const root = path.join(temporary, "portable-images"); fs.mkdirSync(root);
  const original = await sharp({ create: { width: 2400, height: 1200, channels: 3, background: "#6699cc" } }).png().toBuffer();
  fs.writeFileSync(path.join(root, "large.png"), original);
  fs.writeFileSync(path.join(root, "duplicate.png"), original);
  fs.writeFileSync(path.join(root, "small.png"), png);
  const entries = [1, 2].map(() => ({ files: { model: "large.png", garment: "duplicate.png", result: "small.png" } }));
  const before = structuredClone(entries);
  const embedded = await embedReviewImages(entries, root);
  assert.deepEqual(embedded.warnings, []);
  assert.deepEqual(entries, before);
  assert.equal(Object.keys(embedded.images).length, 2);
  assert.equal(embedded.entries[0].files.model.id, embedded.entries[1].files.garment.id);
  const model = embedded.entries[0].files.model;
  const small = embedded.entries[0].files.result;
  const preview = Buffer.from(embedded.images[model.id].split(",")[1], "base64");
  const info = await sharp(preview).metadata();
  assert.equal(info.format, "webp"); assert.equal(info.width, 1600); assert.equal(info.height, 800);
  assert.equal(small.width, 16); assert.equal(small.height, 16);
  assert(preview.length < original.length);
  assert.deepEqual(fs.readFileSync(path.join(root, "large.png")), original);
});

test("unreadable review images leave a usable report and explain the missing preview", async () => {
  const root = path.join(temporary, "unreadable-images"); fs.mkdirSync(root);
  fs.writeFileSync(path.join(root, "broken.png"), "not an image");
  fs.writeFileSync(path.join(root, "good.png"), png);
  const embedded = await embedReviewImages([{ files: { model: "broken.png", garment: "good.png", result: null } }], root);
  assert.equal(embedded.entries[0].files.model, null);
  assert.equal(embedded.entries[0].files.result, null);
  assert.equal(Object.keys(embedded.images).length, 1);
  assert.equal(embedded.warnings.length, 1); assert.match(embedded.warnings[0], /broken.png/);
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
    const result = await renderSavedReview(input, output);
    assert.equal(result.missing_assets, 0); assert.equal(result.garments, 1);
    assert.deepEqual(result.report.results, source.results);
    assert.deepEqual(JSON.parse(fs.readFileSync(input, "utf8")), source);
    assert.equal(result.report.summary.by_garment[0].average_score, 80);
    const html = fs.readFileSync(path.join(output, "index.html"), "utf8");
    assert.match(html, /saved-evaluator/); assert.match(html, /Pass: 75%/);
    assert.match(html, /Keep this exact saved judgment/);
    const sources = [...html.matchAll(/<img src="([^"]+)"/g)].map(match => match[1]);
    assert.equal(sources.length, 3); assert(sources.every(source => source.startsWith("data:image/")));
    assert.equal((html.match(/data-review-image=/g) || []).length, 3);
    const images = JSON.parse(html.match(/id="review-images" type="application\/json">(.*?)<\/script>/s)[1]);
    assert.equal(Object.keys(images).length, 1);
    assert(Object.values(images).every(source => source.startsWith("data:image/webp;base64,")));
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
  const upload = config.jobs.analyze.steps.find(step => step.uses?.startsWith("actions/upload-artifact@"));
  assert.equal(upload.with.path, "outputs/index.html");
  assert(fs.existsSync(path.join(repo, ".github/scripts/analysis-artifacts.cjs")));
});

after(() => {
  const resolved = path.resolve(temporary);
  assert.equal(path.dirname(resolved), path.resolve(os.tmpdir()));
  assert(path.basename(resolved).startsWith("siz3r-assessment-"));
  fs.rmSync(resolved, { recursive: true, force: true });
});
