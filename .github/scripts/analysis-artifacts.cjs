const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const CATEGORIES = ["upper", "lower", "full"];

function parseCategories(value = "upper,lower,full") {
  const categories = [...new Set(String(value).split(/[\s,;]+/).filter(Boolean))];
  if (!categories.length || categories.some(category => !CATEGORIES.includes(category))) throw new Error("run_keys must contain upper, lower, full, or a comma-separated subset.");
  return categories;
}

function parseRunIds(value = "") {
  return [...new Set(String(value).trim().split(/[\s,;]+/).filter(Boolean).map(part => {
    const match = part.match(/^(?:https:\/\/github\.com\/[^/]+\/[^/]+\/actions\/runs\/)?(\d+)\/?(?:\?[^\s]*)?$/);
    const id = Number(match?.[1]);
    if (!Number.isSafeInteger(id) || id < 1) throw new Error("run_ids must contain workflow run IDs or GitHub Actions run URLs.");
    return id;
  }))];
}

function parseRunUrl(value, repo) {
  const invalid = "Paste a GitHub generation run link, such as https://github.com/owner/repo/actions/runs/123456789.";
  let url;
  try { url = new URL(String(value || "").trim()); } catch { throw new Error(invalid); }
  const match = url.pathname.match(/^\/([^/]+)\/([^/]+)\/actions\/runs\/(\d+)(?:\/(?:job|attempts)\/\d+)?\/?$/);
  if (url.protocol !== "https:" || url.hostname !== "github.com" || url.port || url.username || url.password || !match) throw new Error(invalid);
  if (repo && `${match[1]}/${match[2]}`.toLowerCase() !== `${repo.owner}/${repo.repo}`.toLowerCase()) {
    throw new Error("Use a generation run link from this repository.");
  }
  return parseRunIds(match[3])[0];
}

function artifactDetails(artifact) {
  if (artifact.expired) return null;
  if (artifact.name === "siz3r-test-results") return { ...artifact, categories: null, profile: null };
  const match = artifact.name.match(/^siz3r-(all|(?:upper|lower|full)(?:,(?:upper|lower|full))*)-(.+)-results$/);
  if (!match) return null;
  return { ...artifact, categories: match[1] === "all" ? [...CATEGORIES] : parseCategories(match[1]), profile: match[2] };
}

function runQuality(run) {
  const premium = (run.display_title || "").match(/\bpremium=(true|false)\b/)?.[1];
  const turbo = (run.display_title || "").match(/\bturbo=(true|false)\b/)?.[1];
  if (turbo === "true") return "turbo";
  if (premium === "true") return "premium";
  return premium === "false" && turbo === "false" ? "standard" : null;
}

async function selectArtifacts(runs, artifactsForRun, options = {}) {
  const requested = parseCategories(options.categories);
  const mode = options.mode || "latest_per_category";
  if (!["latest_per_category", "latest_run", "run_ids", "triggered"].includes(mode)) throw new Error("Invalid selection mode.");
  const needed = new Set(requested);
  const selected = [];
  for (const run of [...runs].sort((a, b) => Number(b.id) - Number(a.id))) {
    if (run.status !== "completed") {
      if (["triggered", "run_ids"].includes(mode)) throw new Error(`Run ${run.id} has not completed.`);
      continue;
    }
    if (options.branch && run.head_branch !== options.branch) {
      if (mode === "run_ids") throw new Error(`Run ${run.id} is on ${run.head_branch}, not ${options.branch}.`);
      continue;
    }
    if (options.quality && options.quality !== "any" && runQuality(run) !== options.quality) {
      if (mode === "run_ids") throw new Error(`Run ${run.id} does not match quality mode ${options.quality}.`);
      continue;
    }
    const candidates = (await artifactsForRun(run.id)).map(artifactDetails).filter(Boolean)
      .filter(artifact => !options.profile || options.profile === "any" || artifact.profile === options.profile);
    const before = selected.length;
    for (const artifact of candidates) {
      // Legacy names cannot identify categories, so use an exact run/latest run.
      if (mode === "latest_per_category" && !artifact.categories) continue;
      const categories = (artifact.categories || requested).filter(category => requested.includes(category) && (mode !== "latest_per_category" || needed.has(category)));
      if (!categories.length) continue;
      selected.push({
        run_id: run.id, run_url: run.html_url, branch: run.head_branch, commit: run.head_sha,
        run_title: run.display_title, created_at: run.created_at, quality_mode: runQuality(run),
        artifact_id: artifact.id, artifact_name: artifact.name, generation_profile: artifact.profile,
        selected_categories: artifact.categories ? categories : null,
      });
      for (const category of categories) needed.delete(category);
    }
    if (["triggered", "run_ids"].includes(mode) && selected.length === before) throw new Error(`Run ${run.id} has no available generation results. Its artifact may have expired.`);
    if (mode === "latest_run" && selected.length > before) break;
    if (mode === "latest_per_category" && !needed.size) break;
  }
  if (mode === "latest_per_category" && needed.size) throw new Error(`No matching unexpired generation found for: ${[...needed].join(", ")}. Choose a different branch/filter, fewer run_keys, or provide run_ids.`);
  if (!selected.length) throw new Error("No matching generation artifacts found. Artifacts may have expired.");
  return selected;
}

function validateArchiveEntries(entries, destination) {
  const root = path.resolve(destination) + path.sep;
  for (const name of entries) {
    if (!name) continue;
    const resolved = path.resolve(destination, name);
    if (name.includes("\\") || /^[a-z]:/i.test(name) || path.isAbsolute(name) || !resolved.startsWith(root)) throw new Error(`Unsafe artifact path: ${name}`);
  }
}

function extractArchive(zipPath, destination) {
  validateArchiveEntries(execFileSync("unzip", ["-Z1", zipPath], { encoding: "utf8", maxBuffer: 16 * 1024 * 1024 }).split("\n"), destination);
  const listing = execFileSync("unzip", ["-Z", "-l", zipPath], { encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
  if (/^l[rwx-]{9}\s/m.test(listing)) throw new Error("Generation artifacts must not contain symbolic links.");
  execFileSync("unzip", ["-q", "-o", zipPath, "-d", destination]);
}

async function downloadArtifacts({ github, context, core, workingDirectory = process.cwd(), unpack = extractArchive }) {
  const repo = context.repo;
  const triggered = context.eventName === "workflow_run";
  const run_id = triggered ? context.payload.workflow_run.id : parseRunUrl(process.env.ANALYSIS_RUN_URL, repo);
  const { data: run } = await github.rest.actions.getWorkflowRun({ ...repo, run_id });
  if (run.path?.split("@")[0] !== ".github/workflows/selenium.yml") throw new Error("This is not a Siz3r generation run. Paste a link from Siz3r Model Tests.");
  if (run.head_repository?.full_name && run.head_repository.full_name.toLowerCase() !== `${repo.owner}/${repo.repo}`.toLowerCase()) throw new Error(`Run ${run_id} is from another repository.`);
  const selected = await selectArtifacts([run], id => github.paginate(github.rest.actions.listWorkflowRunArtifacts, { ...repo, run_id: id, per_page: 100 }), {
    mode: triggered ? "triggered" : "run_ids",
  });
  const root = path.resolve(workingDirectory, "test_results"), temporary = process.env.RUNNER_TEMP || root;
  fs.mkdirSync(root, { recursive: true });
  for (const selection of selected) {
    const destination = path.join(root, `run-${selection.run_id}`, `artifact-${selection.artifact_id}`);
    const zipPath = path.join(temporary, `assessment-${selection.artifact_id}.zip`);
    core.info(`Downloading ${selection.artifact_name} from ${selection.run_url || selection.run_id}`);
    const response = await github.rest.actions.downloadArtifact({ ...repo, artifact_id: selection.artifact_id, archive_format: "zip" });
    fs.writeFileSync(zipPath, Buffer.from(response.data));
    fs.mkdirSync(destination, { recursive: true });
    await unpack(zipPath, destination);
    fs.writeFileSync(path.join(destination, "source-run.json"), JSON.stringify(selection, null, 2));
    fs.unlinkSync(zipPath);
  }
  fs.writeFileSync(path.join(root, "analysis-sources.json"), JSON.stringify(selected, null, 2));
  core.exportVariable("ANALYZE_SOURCE_DIR", root);
  await core.summary.addHeading("Generation runs selected for assessment").addTable([
    [{ data: "Run", header: true }, { data: "Artifact", header: true }, { data: "Categories", header: true }, { data: "Branch", header: true }],
    ...selected.map(item => [String(item.run_id), item.artifact_name, item.selected_categories?.join(", ") || "legacy artifact", item.branch]),
  ]).write();
  return selected;
}

module.exports = { parseCategories, parseRunIds, parseRunUrl, artifactDetails, runQuality, selectArtifacts, validateArchiveEntries, downloadArtifacts };
