import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createReviewEntry, buildReviewHtml } from "../analyze_quality.js";
import { groupByGarment, summarizeProblems, summarizeGarments } from "../lib/review-summary.js";
import { embedReviewImages } from "../lib/review-images.js";

// Rebuild the presentation from saved judgments. This never runs the assessor.
export async function renderSavedReview(inputFile, outputDirectory) {
  const input = path.resolve(inputFile);
  const output = path.resolve(outputDirectory);
  const report = JSON.parse(fs.readFileSync(input, "utf8"));
  if (!Array.isArray(report.results) || !report.summary) throw new Error("Expected an analysis.json report with saved results and a summary.");
  const originalRoot = path.resolve(path.dirname(input), "..");
  let missingAssets = 0;
  const assetLink = source => {
    if (!source) return null;
    // Windows ZIP extraction can trim trailing spaces/dots from Linux-created
    // directory names. Only use that spelling when the exact path is absent.
    const extractedSpelling = source.split(/[\\/]/).map(part => part === "." || part === ".." ? part : part.replace(/[ .]+$/, "")).join(path.sep);
    const candidates = [path.resolve(originalRoot, source), path.resolve(originalRoot, extractedSpelling), path.resolve(process.cwd(), source), path.resolve(process.cwd(), extractedSpelling)];
    const existing = candidates.find(file => fs.existsSync(file) && fs.statSync(file).isFile());
    if (!existing) { missingAssets++; return null; }
    return path.relative(output, existing).replaceAll("\\", "/");
  };
  const entries = report.results.map(record => createReviewEntry(record, { files: {
    model: assetLink(record.files?.model?.relative_path),
    garment: assetLink(record.files?.garment?.relative_path),
    result: assetLink(record.files?.result?.relative_path),
    metadata: assetLink(record.files?.metadata),
  } }));
  const groups = groupByGarment(entries);
  const problems = summarizeProblems(entries);
  report.summary.by_garment = summarizeGarments(groups);
  report.summary.common_problems = problems.problems;
  report.summary.evaluated_for_problem_summary = problems.evaluated_results;
  report.rendered_at = new Date().toISOString();
  const embedded = await embedReviewImages(entries, output);
  fs.mkdirSync(output, { recursive: true });
  fs.writeFileSync(path.join(output, "index.html"), buildReviewHtml(embedded.entries, report.summary, {
    generatedAt: report.generated_at, reportMode: report.report_mode || "review",
    evaluatorModel: report.evaluator_model, scoringPolicy: report.scoring_policy,
    images: embedded.images,
  }));
  fs.writeFileSync(path.join(output, "analysis.json"), JSON.stringify(report, null, 2));
  return { output, cases: entries.length, garments: groups.length, missing_assets: missingAssets, warnings: embedded.warnings, report };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [, , input, output] = process.argv;
  if (!input || !output) {
    console.error('Usage: npm run report -- "path/to/outputs/analysis.json" "output-directory"');
    process.exitCode = 1;
  } else {
    try {
      const result = await renderSavedReview(input, output);
      console.log(`${result.cases} saved results grouped into ${result.garments} garments. No AI requests made.`);
      console.log(path.join(result.output, "index.html"));
      for (const warning of result.warnings) console.warn(warning);
      if (result.missing_assets) console.warn(`${result.missing_assets} source files are missing; keep the original images available alongside the saved report.`);
    } catch (error) { console.error(error.message); process.exitCode = 1; }
  }
}
