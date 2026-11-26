import fs from "node:fs/promises";
import sharp from "sharp";

export const LABEL_KEYS = ["garment_structure_error", "construction_alignment_error", "fit_error", "artifact_error"];
export const BODY_REVIEW_REGIONS = { chest: "Chest", waist_and_abdomen: "Waist and abdomen", hips: "Hips" };
export const SCORE_PENALTIES = {
  garment_structure_error: { NONE: 0, MINOR: 20, MAJOR: 60 },
  construction_alignment_error: { NONE: 0, MINOR: 15, MAJOR: 40 },
  fit_error: { NONE: 0, MINOR: 10, MAJOR: 30 },
  artifact_error: { NONE: 0, MINOR: 5, MAJOR: 40 },
};
const severities = ["NONE", "MINOR", "MAJOR"];
const enumSchema = (values, nullable = false) => ({ type: nullable ? ["string", "null"] : "string", enum: nullable ? [...values, null] : values });
const stringsSchema = { type: "array", items: { type: "string" } };
const strictObject = properties => ({ type: "object", additionalProperties: false, properties, required: Object.keys(properties) });
const responseFormat = (name, schema) => ({ type: "json_schema", json_schema: { name, strict: true, schema } });
const findingProperties = {
  category: enumSchema(LABEL_KEYS),
  subject: enumSchema(["BODY_SHAPE", "IDENTITY_OR_ANATOMY", "GARMENT", "NON_TARGET_ITEM", "SCENE_OR_BOUNDARY"]),
  severity: enumSchema(["MINOR", "MAJOR"]),
  confidence: enumSchema(["CONFIRMED", "UNCERTAIN"]),
  comparison_basis: enumSchema(["COMPARABLE_EXPOSED_SKIN", "COMPARABLE_ANATOMICAL_LANDMARKS", "VISIBLE_GARMENT", "VISIBLE_OTHER", "NOT_COMPARABLE"]),
  original_observation: { type: "string" },
  result_observation: { type: "string" },
  clothing_or_pose_explanation_ruled_out: { type: "boolean" },
  description: { type: "string" },
};
// Keep the original evidence shape valid. Only a body-contour claim needs the
// extra explanation of what makes a clothed outline informative about size.
const findingSchema = { anyOf: [
  strictObject(findingProperties),
  strictObject({
    ...findingProperties,
    category: enumSchema(["artifact_error"]), subject: enumSchema(["BODY_SHAPE"]),
    comparison_basis: enumSchema(["COMPARABLE_BODY_CONTOUR"]),
    contour_evidence: strictObject({
      region: { type: "string" },
      original_surface: enumSchema(["BODY_FOLLOWING", "LOOSE_OR_STRUCTURED", "UNCLEAR"]),
      result_surface: enumSchema(["BODY_FOLLOWING", "INSUFFICIENT_SPACE_FOR_ORIGINAL_BODY", "LOOSE_OR_STRUCTURED", "UNCLEAR"]),
      scale_and_pose_comparable: { type: "boolean" },
      landmark_corroboration: { type: "string" },
      clothing_explanation_exclusion: { type: "string" },
    }),
  }),
] };

export const RATING_RESPONSE_FORMAT = responseFormat("tryon_assessment", strictObject({
  garment_type: { type: "string" },
  garment_category: enumSchema(["top", "pants", "dress", "skirt", "outerwear", "outfit", "other"]),
  intended_fit: enumSchema(["tight", "regular", "loose", "oversized"], true),
  silhouette_preserved: enumSchema(["YES", "PARTIAL", "NO"]),
  critical_issues: stringsSchema,
  minor_issues: stringsSchema,
  positives: stringsSchema,
  notes: { type: "string" },
  labels: strictObject(Object.fromEntries(LABEL_KEYS.map(key => [key, enumSchema(severities)]))),
}));
export const VERIFICATION_RESPONSE_FORMAT = responseFormat("tryon_assessment_verification", strictObject({
  garment_type: { type: "string" },
  garment_category: RATING_RESPONSE_FORMAT.json_schema.schema.properties.garment_category,
  intended_fit: RATING_RESPONSE_FORMAT.json_schema.schema.properties.intended_fit,
  silhouette_preserved: RATING_RESPONSE_FORMAT.json_schema.schema.properties.silhouette_preserved,
  coverage: strictObject(Object.fromEntries(["garment_design", "fit_and_drape", "person_integrity", "scene_and_other_items"].map(key => [key, { type: "string" }]))),
  body_shape_review: strictObject(Object.fromEntries(Object.keys(BODY_REVIEW_REGIONS).map(key => [key, strictObject({
    original_observation: { type: "string" },
    result_observation: { type: "string" },
    original_surface: enumSchema(["EXPOSED_ANATOMY", "BODY_FOLLOWING", "LOOSE_OR_STRUCTURED", "UNCLEAR"]),
    result_surface: enumSchema(["EXPOSED_ANATOMY", "BODY_FOLLOWING", "INSUFFICIENT_SPACE_FOR_ORIGINAL_BODY", "LOOSE_OR_STRUCTURED", "UNCLEAR"]),
    comparison_basis: enumSchema(["COMPARABLE_EXPOSED_SKIN", "COMPARABLE_ANATOMICAL_LANDMARKS", "COMPARABLE_BODY_CONTOUR", "NOT_COMPARABLE"]),
    conclusion: enumSchema(["NO_MATERIAL_CHANGE", "MATERIAL_CHANGE", "NOT_COMPARABLE"]),
    explanation: { type: "string" },
    finding_index: { type: ["integer", "null"] },
  })]))),
  findings: { type: "array", items: findingSchema },
  positives: stringsSchema,
  notes: { type: "string" },
  rejected_claims: stringsSchema,
}));

export function envNumber(env, name, fallback, { min = 0, max = Infinity, integer = true } = {}) {
  const raw = String(env[name] ?? "").trim();
  const number = raw ? Number(raw) : fallback;
  if (!Number.isFinite(number) || number < min || number > max || (integer && !Number.isInteger(number))) {
    throw new Error(`${name} must be ${integer ? "an integer" : "a number"} between ${min} and ${max}.`);
  }
  return number;
}

export function appendUniqueStrings(existing, incoming, maxItems = 6) {
  return [...new Map([...existing, ...incoming].filter(item => typeof item === "string" && item.trim())
    .map(item => [item.trim().toLowerCase(), item.trim()])).values()].slice(0, maxItems);
}

// Structured severity labels are the evidence. Free-text keywords must never
// create a defect or excuse one: negation and legitimate exceptions need vision.
export function finalizeRating(rating, { passScore = 80, maxMinorLabels = 2 } = {}) {
  const labels = { ...rating.labels };
  const major = LABEL_KEYS.filter(key => labels[key] === "MAJOR");
  const minor = LABEL_KEYS.filter(key => labels[key] === "MINOR");
  const descriptions = {
    garment_structure_error: "Garment structure or silhouette differs from the reference.",
    construction_alignment_error: "Garment details are missing or incorrectly aligned.",
    fit_error: "Garment fit or placement is incorrect.",
    artifact_error: "The result contains generation artifacts or damage.",
  };
  const critical = [...rating.critical_issues];
  const minorIssues = [...rating.minor_issues];
  if (!critical.length) critical.push(...major.map(key => descriptions[key]));
  if (!minorIssues.length) minorIssues.push(...minor.map(key => descriptions[key]));
  const score = Math.max(0, 100 - LABEL_KEYS.reduce((sum, key) => sum + SCORE_PENALTIES[key][labels[key]], 0));
  return {
    ...rating, labels, critical_issues: critical, minor_issues: minorIssues,
    quality_percent: score,
    successful: score >= passScore && !major.length && !critical.length && minor.length <= maxMinorLabels ? "YES" : "NO",
  };
}

function validateObject(raw, schema, location = "response") {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return `${location} must be an object.`;
  if (schema.anyOf) {
    const errors = schema.anyOf.map(branch => validateObject(raw, branch, location));
    return errors.includes(null) ? null : `${location} does not match a supported evidence format: ${errors.join(" ")}`;
  }
  for (const key of Object.keys(raw)) if (!(key in schema.properties)) return `Unexpected ${location}.${key}.`;
  for (const [key, spec] of Object.entries(schema.properties)) {
    const value = raw[key];
    const label = `${location}.${key}`;
    if (value === undefined) return `Missing ${label}.`;
    if (spec.enum) {
      if (!spec.enum.includes(value)) return `Invalid ${label}.`;
    } else if (spec.type === "object") {
      const error = validateObject(value, spec, label);
      if (error) return error;
    } else if (spec.type === "array") {
      if (!Array.isArray(value)) return `${label} must be an array.`;
      for (const [index, item] of value.entries()) {
        if (spec.items.type === "object" || spec.items.anyOf) {
          const error = validateObject(item, spec.items, `${label}[${index}]`);
          if (error) return error;
        } else if (typeof item !== spec.items.type) return `${label} must be an array of ${spec.items.type}s.`;
      }
    } else {
      const types = Array.isArray(spec.type) ? spec.type : [spec.type];
      const matches = types.some(type => type === "null" ? value === null : type === "integer" ? Number.isInteger(value) : typeof value === type);
      if (!matches) return `Invalid ${label}.`;
    }
  }
  return null;
}

export function validateAndNormalizeRating(raw, policy) {
  const error = validateObject(raw, RATING_RESPONSE_FORMAT.json_schema.schema);
  if (error) return { ok: false, error };
  if (raw.critical_issues.length && !LABEL_KEYS.some(key => raw.labels[key] === "MAJOR")) {
    return { ok: false, code: "INCONSISTENT_SEVERITY", error: "Critical issues require at least one MAJOR severity label." };
  }
  return { ok: true, rating: finalizeRating({
    ...raw,
    garment_type: raw.garment_type.trim().slice(0, 160),
    critical_issues: appendUniqueStrings([], raw.critical_issues),
    minor_issues: appendUniqueStrings([], raw.minor_issues),
    positives: appendUniqueStrings([], raw.positives),
    notes: raw.notes.trim().slice(0, 350),
  }, policy) };
}

export function validateAssessmentVerification(raw, policy) {
  const error = validateObject(raw, VERIFICATION_RESPONSE_FORMAT.json_schema.schema);
  if (error) return { ok: false, error };
  if (Object.values(raw.coverage).some(value => !value.trim())) return { ok: false, error: "Every review area needs an observation or a comparison limitation." };
  const accepted = [];
  const acceptedIndices = new Set();
  const excluded = [];
  const allowedBases = {
    BODY_SHAPE: ["COMPARABLE_EXPOSED_SKIN", "COMPARABLE_ANATOMICAL_LANDMARKS", "COMPARABLE_BODY_CONTOUR"],
    IDENTITY_OR_ANATOMY: ["COMPARABLE_EXPOSED_SKIN", "COMPARABLE_ANATOMICAL_LANDMARKS", "VISIBLE_OTHER"],
    GARMENT: ["VISIBLE_GARMENT"], NON_TARGET_ITEM: ["VISIBLE_OTHER"], SCENE_OR_BOUNDARY: ["VISIBLE_OTHER"],
  };
  for (const [index, finding] of raw.findings.entries()) {
    const garmentFinding = finding.subject === "GARMENT";
    if (!garmentFinding && finding.category !== "artifact_error") {
      return { ok: false, error: "Person, anatomy, other-item and scene findings need artifact_error." };
    }
    let reason = null;
    if (finding.confidence !== "CONFIRMED") reason = "The visual evidence is uncertain.";
    else if (finding.comparison_basis === "NOT_COMPARABLE") reason = "The relevant region is not comparable.";
    else if (![finding.description, finding.original_observation, finding.result_observation].every(value => value.trim())) reason = "The finding lacks concrete observations from both images.";
    else if (!allowedBases[finding.subject].includes(finding.comparison_basis)) reason = finding.subject === "BODY_SHAPE"
      ? "Clothing contours do not establish a change in hidden anatomy."
      : "The evidence basis does not support this type of finding.";
    else if (finding.subject === "BODY_SHAPE" && !finding.clothing_or_pose_explanation_ruled_out) reason = "Clothing, pose or perspective still explains the apparent body difference.";
    else if (finding.comparison_basis === "COMPARABLE_BODY_CONTOUR") {
      const evidence = finding.contour_evidence;
      if (evidence.original_surface !== "BODY_FOLLOWING") reason = "The original clothing does not reveal a comparable body contour.";
      else if (!["BODY_FOLLOWING", "INSUFFICIENT_SPACE_FOR_ORIGINAL_BODY"].includes(evidence.result_surface)) reason = "Loose, structured or unclear clothing does not establish the result's body contour.";
      else if (!evidence.scale_and_pose_comparable) reason = "The contour comparison does not establish comparable scale and pose.";
      else if (![evidence.region, evidence.landmark_corroboration, evidence.clothing_explanation_exclusion].every(value => value.trim())) reason = "A clothed body-contour claim needs a specific region, corroborating landmarks and an explanation excluding normal clothing changes.";
    }
    if (reason) excluded.push({ ...finding, exclusion_reason: reason });
    else {
      if (finding.subject === "BODY_SHAPE" && finding.severity !== "MAJOR") {
        return { ok: false, error: "A confirmed material body-shape change requires MAJOR severity." };
      }
      accepted.push({ ...finding, description: finding.description.trim() });
      acceptedIndices.add(index);
    }
  }
  // Regional comparisons are mandatory even when the preliminary assessment
  // proposed no body defect. A changed region cannot silently disappear when
  // findings are filtered, and an obscured region cannot claim preservation.
  for (const [region, review] of Object.entries(raw.body_shape_review)) {
    if (![review.original_observation, review.result_observation, review.explanation].every(value => value.trim())) {
      return { ok: false, error: `Body-shape review for ${region} needs original/result observations and an explanation.` };
    }
    if ((review.conclusion === "NOT_COMPARABLE") !== (review.comparison_basis === "NOT_COMPARABLE")) {
      return { ok: false, error: `Body-shape review for ${region} has inconsistent comparability and conclusion.` };
    }
    if (review.conclusion !== "NOT_COMPARABLE") {
      const contour = review.comparison_basis === "COMPARABLE_BODY_CONTOUR";
      const originalReadable = review.original_surface === (contour ? "BODY_FOLLOWING" : "EXPOSED_ANATOMY");
      const resultReadable = review.result_surface === (contour ? "BODY_FOLLOWING" : "EXPOSED_ANATOMY");
      const volumeContradiction = contour && review.conclusion === "MATERIAL_CHANGE" && review.result_surface === "INSUFFICIENT_SPACE_FOR_ORIGINAL_BODY";
      if (!originalReadable || (!resultReadable && !volumeContradiction)) {
        return { ok: false, error: `Body-shape review for ${region} needs readable local surfaces for its comparison; obscured shape is not established as preserved.` };
      }
    }
    if (review.conclusion === "MATERIAL_CHANGE") {
      const finding = raw.findings[review.finding_index];
      if (!acceptedIndices.has(review.finding_index) || finding?.subject !== "BODY_SHAPE") {
        return { ok: false, error: `Material body-shape change in ${region} requires a supported MAJOR BODY_SHAPE finding at finding_index.` };
      }
      if (finding.comparison_basis !== review.comparison_basis) {
        return { ok: false, error: `Body-shape review for ${region} must use the linked finding's comparison basis.` };
      }
      if (finding.contour_evidence && (review.original_surface !== finding.contour_evidence.original_surface || review.result_surface !== finding.contour_evidence.result_surface)) {
        return { ok: false, error: `Body-shape review for ${region} must agree with the linked finding's contour visibility.` };
      }
    } else if (review.finding_index !== null) {
      return { ok: false, error: `Body-shape review for ${region} must use a null finding_index unless a material change is confirmed.` };
    }
  }
  // Rebuild the complete verdict from verified findings. No first-pass penalty
  // survives merely because it appeared in the proposed assessment.
  const labels = Object.fromEntries(LABEL_KEYS.map(key => [key, "NONE"]));
  for (const finding of accepted) {
    if (severities.indexOf(finding.severity) > severities.indexOf(labels[finding.category])) labels[finding.category] = finding.severity;
  }
  const critical = accepted.filter(finding => finding.severity === "MAJOR").map(finding => finding.description);
  const minor = accepted.filter(finding => finding.severity === "MINOR").map(finding => finding.description);
  // The displayed verdict must describe the same findings as the score, even
  // if free-form model notes contradict its structured evidence. Retain those
  // raw notes in verification diagnostics, not the consolidated verdict.
  const verdict = [...critical, ...minor].join(" ") || "No confirmed actionable defects in the visible comparisons. See review evidence for comparison limits.";
  const notes = verdict + (excluded.length ? " Uncertain or unsupported comparisons did not affect the score." : "");
  const rating = finalizeRating({
    garment_type: raw.garment_type.trim().slice(0, 160), garment_category: raw.garment_category,
    intended_fit: raw.intended_fit, silhouette_preserved: raw.silhouette_preserved,
    labels, critical_issues: appendUniqueStrings([], critical, 12), minor_issues: appendUniqueStrings([], minor, 12),
    positives: appendUniqueStrings([], raw.positives), notes: notes.trim().slice(0, 350),
  }, policy);
  return { ok: true, rating, verification: raw, accepted_findings: accepted, excluded_findings: excluded };
}

export function parseRetryAfterMs(error, now = Date.now()) {
  const headers = error.headers || {};
  const milliseconds = Number(headers["retry-after-ms"]);
  if (headers["retry-after-ms"] !== undefined && Number.isFinite(milliseconds)) return Math.max(0, milliseconds);
  const retryAfter = headers["retry-after"];
  if (retryAfter !== undefined) {
    if (/^\d+(\.\d+)?$/.test(String(retryAfter).trim())) return Number(retryAfter) * 1000;
    const date = Date.parse(retryAfter);
    if (Number.isFinite(date)) return Math.max(0, date - now);
  }
  const duration = value => {
    const match = String(value || "").match(/^(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?(?:(\d+)ms)?$/);
    return match ? Number(match[1] || 0) * 60000 + Number(match[2] || 0) * 1000 + Number(match[3] || 0) : 0;
  };
  return Math.max(duration(headers["x-ratelimit-reset-tokens"]), duration(headers["x-ratelimit-reset-requests"]));
}

export async function fileToDataUrl(filePath) {
  const bytes = await fs.readFile(filePath);
  const image = sharp(bytes, { animated: true });
  const info = await image.metadata();
  if (!info.width || !info.height || (info.pages || 1) !== 1) throw new Error(`Invalid or animated image: ${filePath}`);
  const mime = { jpeg: "image/jpeg", png: "image/png", webp: "image/webp", gif: "image/gif" }[info.format];
  if (mime) return `data:${mime};base64,${bytes.toString("base64")}`;
  // AVIF is valid input for the generator, but the vision API needs PNG/JPEG/WEBP/GIF.
  const converted = await image.rotate().png().toBuffer();
  return `data:image/png;base64,${converted.toString("base64")}`;
}
