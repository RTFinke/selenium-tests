const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
const text = value => typeof value === "string" ? value.trim() : "";
const normalized = value => text(value).normalize("NFC").toLowerCase().replace(/\s+/g, " ");
const basename = value => text(value).split(/[\\/]/).pop();

function mode(entry) {
  const value = normalized(entry.garment_run_key || entry.garment_mode_requested);
  return ["upper", "lower", "full"].includes(value) ? value : "unknown";
}

export function garmentKey(entry) {
  const filename = basename(entry.garment_filename || entry.metadata?.garment_filename);
  // An absent garment filename is not evidence that two unrelated cases share
  // the same clothing. Keep those cases separate using their source identity.
  const identity = filename || entry.source_folder || entry.files?.garment || entry.test_id || entry.folder;
  if (!identity) return null;
  return `${mode(entry)}:${normalized(identity)}`;
}

export function groupByGarment(entries) {
  const groups = new Map();
  entries.forEach((entry, index) => {
    const key = garmentKey(entry) || `unknown:${index}`;
    if (!groups.has(key)) {
      const filename = basename(entry.garment_filename || entry.metadata?.garment_filename);
      groups.set(key, { key, filename: filename || null, name: filename ? filename.replace(/\.[^.]+$/, "") : "Unidentified garment", run_mode: mode(entry), entries: [] });
    }
    groups.get(key).entries.push(entry);
  });
  const result = [...groups.values()].sort((a, b) => collator.compare(a.name, b.name) || collator.compare(a.run_mode, b.run_mode));
  for (const [index, group] of result.entries()) {
    group.id = `garment-${index + 1}`;
    group.entries.sort((a, b) =>
      collator.compare(a.model_filename || a.metadata?.model_filename || a.folder || "", b.model_filename || b.metadata?.model_filename || b.folder || "") ||
      collator.compare(a.gender || "", b.gender || "") ||
      collator.compare(a.source_folder || a.folder || "", b.source_folder || b.folder || ""));
    const models = new Set();
    const scores = [];
    const stats = { total: group.entries.length, model_count: 0, evaluated: 0, passed: 0, failed: 0, generation_failed: 0, errors: 0, skipped: 0, average_score: null };
    for (const entry of group.entries) {
      const model = entry.model_filename || entry.metadata?.model_filename || entry.files?.model || entry.source_folder || entry.folder;
      models.add(`${entry.gender || ""}:${model}`);
      if (entry.evaluation_mode === "generation_failed" || entry.selenium_status === "failed") stats.generation_failed++;
      else if (entry.evaluation_ok === false) stats.errors++;
      else if (["YES", "NO"].includes(entry.ai_successful)) {
        stats.evaluated++;
        if (entry.ai_successful === "YES") stats.passed++; else stats.failed++;
        if (Number.isFinite(entry.quality_percent)) scores.push(entry.quality_percent);
      } else stats.skipped++;
    }
    stats.model_count = models.size;
    if (scores.length) stats.average_score = Math.round(scores.reduce((sum, score) => sum + score, 0) / scores.length * 10) / 10;
    group.stats = stats;
  }
  return result;
}

// These rules only summarize already reported issues. They never change labels,
// scores, or pass/fail decisions. Unknown wording retains its own named bucket.
const themes = [
  ["old_clothing", "Added layers or clothing remnants", /\b(leftover|remnant|residual|old clothing|ghost (clothing|garment)|extra (layer|garment)|invented (layer|garment)|added (layer|garment|shorts|skirt|leggings))\b/i],
  ["boundaries", "Blending or boundary artifacts", /\b(blend\w*|boundar\w*|ghosting|merged|merging|floating|detached)\b/i],
  ["face_identity", "Face or identity changes", /\b(face|facial|identity|expression|eyes?|mouth|nose)\b/i],
  ["hands", "Hand or finger defects", /\b(hands?|fingers?|thumbs?)\b/i],
  ["arms", "Arm shape or size changes", /\b(arms?|upper[ -]arms?|forearms?|elbows?|wrists?)\b/i],
  ["legs", "Leg or foot changes", /\b(legs?|feet|foot|ankles?|knees?)\b.{0,40}\b(slim\w*|thin\w*|thick\w*|reshap\w*|elongat\w*|shorten\w*|deform\w*|distort\w*|anatomy|skin|missing|extra|changed)\b|\b(extra|missing|deformed|distorted|elongated) (legs?|feet|foot|ankles?|knees?)\b/i],
  ["body_proportions", "Body shape or proportions changed", /\b(body|proportions?|torso|anatomy|limbs?)\b|\b(narrowed|reshaped|slimmed|widened|reduced|enlarged) (shoulders?|hips?|waist)\b|\b(shoulders?|hips?|waist)(?:\s+(?:width|size|shape))? (are |is |were |was )?(narrowed|reshaped|slimmed|widened|reduced|enlarged|changed)\b/i],
  ["hair_skin", "Hair or skin alterations", /\b(hair|skin|skin[ -]tone)\b/i],
  ["scene", "Background or scene changes", /\b(background|scene|wall|floor|shadow\w*|lighting)\b/i],
  ["other_items", "Non-target clothing or accessory changes", /\b(non[ -]target|other clothing|accessor\w*|shoes?|socks?|watch|jewell?ery)\b/i],
  ["garment_identity", "Wrong or incomplete garment", /\b(wrong|different|incorrect) garment (type|identity)|\b(missing|lost|removed) (garment|outfit|piece|jacket|shirt|pants|trousers|dress)\b(?!\s+(pockets?|seams?|buttons?|zippers?|details?|patch|logo))|\b(shorts?|pants|skirt|dress|jacket|shirt)\b.{0,12}\b(instead of|rather than|not)\b.{0,12}\b(shorts?|pants|skirt|dress|jacket|shirt)\b/i],
  ["neckline", "Neckline or collar differences", /\b(neckline|collar|neck|v[ -]neck|cowl|hood)\b/i],
  ["sleeves", "Sleeve or cuff differences", /\b(sleeve\w*|cuffs?|armholes?)\b/i],
  ["construction", "Pocket, seam or closure details", /\b(pockets?|seams?|buttons?|zippers?|closures?|plackets?|trims?|patch|logo|stitch\w*|construction|alignment|misaligned)\b/i],
  ["pattern_color", "Print, pattern or colour differences", /\b(prints?|patterns?|stripes?|motifs?|colou?r\w*)\b/i],
  ["fabric", "Fabric or material detail differences", /\b(fabric|textur\w*|material|glitter|sparkle|shimmer|sheen|sheer|transparen\w*|drape|ribbing|knit\w*|lace)\b/i],
  ["fit", "Fit or placement problems", /\b(fit|fitting|tight\w*|loose\w*|oversized|placement|position\w*)\b/i],
  ["shape_length", "Garment shape or length differences", /\b(silhouette|hem\w*|length|shorter|longer|shape|cut|structure|contour)\b/i],
];

function issueTheme(issue) {
  for (const [key, label, pattern] of themes) if (pattern.test(issue)) return { key, label };
  const key = normalized(issue).replace(/[.!?]+$/, "");
  return { key: `reported:${key}`, label: text(issue).replace(/[.!?]+$/, "") };
}

export function summarizeProblems(entries) {
  const buckets = new Map();
  const reviewed = entries.filter(entry => entry.evaluation_ok !== false && ["YES", "NO"].includes(entry.ai_successful));
  for (const entry of reviewed) {
    const caseThemes = new Map();
    for (const [severity, issues] of [["critical", entry.critical_issues], ["minor", entry.minor_issues]]) {
      for (const issue of issues || []) {
        if (!text(issue)) continue;
        const theme = issueTheme(issue);
        if (!caseThemes.has(theme.key)) caseThemes.set(theme.key, { ...theme, severity, examples: [] });
        const found = caseThemes.get(theme.key);
        if (severity === "critical") found.severity = "critical";
        if (!found.examples.includes(issue)) found.examples.push(issue);
      }
    }
    for (const found of caseThemes.values()) {
      if (!buckets.has(found.key)) buckets.set(found.key, { key: found.key, label: found.label, count: 0, critical_count: 0, minor_count: 0, garments: new Set(), examples: [] });
      const bucket = buckets.get(found.key);
      bucket.count++;
      bucket[`${found.severity}_count`]++;
      bucket.garments.add(garmentKey(entry));
      for (const example of found.examples) if (bucket.examples.length < 3 && !bucket.examples.some(item => normalized(item) === normalized(example))) bucket.examples.push(example);
    }
  }
  const problems = [...buckets.values()].map(({ garments, ...bucket }) => ({
    ...bucket, garment_count: garments.size, percent: reviewed.length ? Math.round(bucket.count / reviewed.length * 100) : 0,
  })).sort((a, b) => b.count - a.count || b.critical_count - a.critical_count || collator.compare(a.label, b.label));
  return { evaluated_results: reviewed.length, problems };
}

export function summarizeGarments(groups) {
  return groups.map(({ id, filename, name, run_mode, stats }) => ({ id, garment_filename: filename, name, run_mode, ...stats }));
}
