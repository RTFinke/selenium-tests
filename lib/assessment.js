import fs from "node:fs/promises";
import sharp from "sharp";

export const LABEL_KEYS = ["garment_structure_error", "construction_alignment_error", "fit_error", "artifact_error"];
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
export const AUDIT_RESPONSE_FORMAT = responseFormat("tryon_artifact_audit", strictObject({
  artifact_present: enumSchema(["YES", "NO"]),
  artifact_severity: enumSchema(severities),
  artifact_reasons: stringsSchema,
  notes: { type: "string" },
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

export function mergeNotes(first, second) {
  return appendUniqueStrings([first], [second]).join(" ").slice(0, 350);
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
      if (!Array.isArray(value) || value.some(item => typeof item !== "string")) return `${label} must be an array of strings.`;
    } else if (typeof value !== spec.type) return `Invalid ${label}.`;
  }
  return null;
}

export function validateAndNormalizeRating(raw, policy) {
  const error = validateObject(raw, RATING_RESPONSE_FORMAT.json_schema.schema);
  if (error) return { ok: false, error };
  if (raw.critical_issues.length && !LABEL_KEYS.some(key => raw.labels[key] === "MAJOR")) {
    return { ok: false, error: "Critical issues require at least one MAJOR severity label." };
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

export function validateArtifactAudit(raw) {
  const error = validateObject(raw, AUDIT_RESPONSE_FORMAT.json_schema.schema);
  if (error) return { ok: false, error };
  if ((raw.artifact_present === "NO") !== (raw.artifact_severity === "NONE")) {
    return { ok: false, error: "Artifact presence and severity contradict each other." };
  }
  return { ok: true, audit: { ...raw, artifact_reasons: appendUniqueStrings([], raw.artifact_reasons, 4), notes: raw.notes.trim().slice(0, 240) } };
}

export function applyArtifactAuditToRating(rating, audit, policy) {
  if (audit.artifact_present === "NO") return rating;
  const labels = { ...rating.labels };
  if (severities.indexOf(audit.artifact_severity) > severities.indexOf(labels.artifact_error)) labels.artifact_error = audit.artifact_severity;
  const reasons = audit.artifact_reasons.length ? audit.artifact_reasons : [audit.notes || "Artifact audit detected damage."];
  return finalizeRating({
    ...rating, labels,
    critical_issues: audit.artifact_severity === "MAJOR" ? appendUniqueStrings(rating.critical_issues, reasons) : rating.critical_issues,
    minor_issues: audit.artifact_severity === "MINOR" ? appendUniqueStrings(rating.minor_issues, reasons) : rating.minor_issues,
    notes: mergeNotes(rating.notes, audit.notes),
  }, policy);
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
