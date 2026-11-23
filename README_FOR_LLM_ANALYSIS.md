# Siz3r Model Testing - AI Assessment

## API key

Locally, edit the project-root `.env` file and set:

```dotenv
OPENAI_API_KEY=your-api-key
```

For a new setup, copy `.env.example` to `.env` and replace the placeholder. Existing environment variables take precedence over `.env`. The example contains no real key; `.env` is ignored by Git.

On GitHub, open **Settings > Secrets and variables > Actions > Repository secrets** and create or update **`OPENAI_API_KEY`**. GitHub Actions reads this secret directly. Updating the local `.env` does not update the GitHub secret.

## Local assessment

Use Node.js 22 or newer, run `npm ci`, then `npm run analyze`.

The script discovers `test_results_upper/`, `test_results_lower/`, `test_results_full/`, and unpacked artifacts under `test_results/`. It also supports the older flat `images/` layout. Each case is detected independently, so several artifacts can be unpacked into separate subfolders without overwriting each other.

Set `ANALYZE_SOURCE_DIR` to one artifact root, one test folder, or a comma-, semicolon-, or newline-separated list of roots to choose inputs explicitly. AI assessment requires the garment reference, original person, and generated result. AVIF inputs are converted for the API without changing the original files.

Outputs:

- `outputs/index.html`: pictures, generation settings, scores, explanations, and failures.
- `outputs/analysis.json`: judgments, source-run information, and diagnostic errors.

Keep the source images alongside the report when sharing it. Download and unpack the whole GitHub artifact, then open `outputs/index.html`.

## Assessing three separate generation runs on GitHub

Open **Actions > Analyze with LLM > Run workflow** and select a branch containing these fixes.

- Keep `selection=latest_per_category` to collect the latest **upper**, **lower**, and **full** runs into one report. A blank `source_branch` uses the selected workflow branch. The current local `fashn` branch tracks remote `openAi`; use the remote name on GitHub.
- Set `run_keys` to a subset such as `upper,lower` to request fewer categories.
- Use `quality_mode` and `generation_profile` to restrict selection, for example to Standard generations only. `any` accepts the latest matching run for each category; actual settings appear in the report.
- Paste generation **run IDs or run URLs**, separated by commas, into `run_ids` for precise selection. IDs override `selection`; a blank `source_branch` permits IDs from different branches. Each run must contain a matching artifact.
- Use `selection=latest_run` to assess only the newest matching run, including whichever requested categories it contains.
- Old `siz3r-test-results` artifacts remain supported by exact run IDs or `latest_run`; their names do not identify categories for `latest_per_category` selection.

The workflow downloads each artifact into its own run/artifact directory and records the run ID, branch, commit, and selected categories. If the newest run covers all categories, an older category is not assessed twice. Missing or expired requested categories produce explicit errors. The workflow summary lists the selected source runs.

Download the `llm-quality-analysis` artifact and unpack everything. Keep `test_results/` alongside `outputs/` so image links work.

Automatic assessment judges the exact triggering generation run. Automatic `workflow_run` execution uses the default branch: merge the updated workflow, `.github/scripts/analysis-artifacts.cjs`, `analyze_quality.js`, `lib/assessment.js`, `package.json`, `package-lock.json`, and `tests/assessment.test.mjs` into `main` to replace its old local-LLM assessment. Manual runs can use the updated branch before that merge.

The maintained workflow is `.github/workflows/analyze-with-llm.yml`.

## Judgment and failure handling

The API receives all three images and the intended upper/lower/full transfer mode. Full-outfit transfers may replace both upper and lower clothing. Structured responses supply category, fit, silhouette, explanations, and four severity labels.

The application starts at 100 and subtracts these fixed penalties:

| Label | MINOR penalty | MAJOR penalty |
| --- | ---: | ---: |
| Garment structure / silhouette | 20 | 60 |
| Construction / detail alignment | 15 | 40 |
| Fit | 10 | 30 |
| Artifacts / collateral damage | 5 | 40 |

Passing requires at least 80% by default, at most two MINOR labels, no MAJOR labels, and no critical issues. Free-text keywords never override structured labels. Passing candidates receive a second artifact audit. If that audit fails, the assessment is incomplete and has no final score.

Assessment errors make the command fail after saving the diagnostic report. Ordinary AI quality failures are valid completed judgments. Failed generations are skipped, retain their original failure reason, and do not trigger API requests. If every generation failed, an AI review cannot produce judgments and exits with an error.

`review` requires an API key. `gallery` generates an image gallery; `comparison` explicitly creates a no-AI review. Missing keys never silently turn an AI assessment into a successful comparison report.

## Configuration

- `OPENAI_API_KEY`: local `.env` value or GitHub Actions repository secret.
- `OPENAI_MODEL`: vision model with Structured Outputs support; default `gpt-4.1`.
- `OPENAI_PASS_SCORE_THRESHOLD`: passing score; default `80`.
- `OPENAI_MAX_MINOR_LABELS_FOR_PASS`: maximum MINOR labels on a pass; default `2`.
- `OPENAI_CONCURRENCY`: parallel evaluations; default `2`, workflow `1`.
- `OPENAI_DELAY_MS`: minimum spacing between API requests; default `750`.
- `OPENAI_TIMEOUT_MS`: timeout per request; default `180000`.
- `OPENAI_MAX_RETRIES`: total attempts per request; default `3`.
- `ANALYZE_ENABLE_ARTIFACT_AUDIT=true`: run the second audit on failing candidates too; passing candidates always receive it.
- `ANALYZE_SOURCE_DIR`: optional input root or list of roots.
- `ANALYSIS_OUTPUT_DIR`: report directory; default `outputs`.
- `ANALYSIS_REPORT_MODE`: `gallery`, `review` (default), or `comparison`.

For GitHub, the workflow also accepts an `openai_model` input and repository variables `OPENAI_MODEL` and `OPENAI_PASS_SCORE_THRESHOLD`. API keys belong in secrets.

Run `npm test` for offline regression checks. Tests use mocked AI responses and do not call the real API.

## Generation settings

- Check `premium` in the `Siz3r Model Tests` manual-run form to select Premium before every try-on. Unchecked (the default) preserves the site's quality default. Locally, use `TEST_PREMIUM=true`. Premium is selected before Advanced settings, and the test fails before generation if the Premium button is missing, disabled, or its selection cannot be confirmed.
- Check `turbo` in the manual-run form to select Turbo before every try-on, or set `TEST_TURBO=true` locally. Leave `premium` unchecked: enabling both modes is rejected before the run starts. Unchecked Turbo preserves the site's current mode. The test confirms Turbo selection before generating and records `turbo_requested`, `turbo_enabled`, and the selected quality mode in results.
- `Siz3r Model Tests` should run with `ANALYZE_SOURCE_DIR=test_results_upper,test_results_lower,test_results_full` and `ANALYSIS_REPORT_MODE=gallery` so `outputs/index.html` is just the generation gallery
- The `run_keys` field accepts `upper`, `lower`, and `full`. Leave it blank to run all three, or provide a comma-separated subset such as `upper,lower`.
- In the `Siz3r Model Tests` manual-run form, select `generation_profile=advanced_segmentation_free_30` to enable Advanced mode, select `segmentation_free`, and set `steps` to `30` before every try-on. Leave it as `default` to preserve the existing site defaults.
- Check `flat` in the manual-run form to enable Flat before every try-on, with either generation profile. Unchecked (the default) explicitly disables Flat. Locally, use `TEST_FLAT=true`. The test verifies the checkbox state and fails before generating if it cannot confirm it; results record `flat_requested` and `flat_enabled`.
- On GitHub, select the remote `openAi` branch under **Run workflow > Use workflow from**, or use `gh workflow run selenium.yml --ref openAi -F flat=true`. The local `fashn` branch tracks `origin/openAi`.

## Results structure

`Siz3r Model Tests` artifacts are expected in a structure like this:

```text
test_results_upper/
|-- summary.json
|-- test_1_upper_women_model123/
|   |-- metadata.json
|   |-- garment/garment.jpg
|   |-- model/model.jpg
|   `-- result/result.png
|-- test_2_upper_men_model456/
|   `-- ...
|
test_results_lower/
|-- summary.json
|-- test_1_lower_women_model123/
|   `-- ...
|
test_results_full/
|-- summary.json
|-- test_1_full_women_model123/
|   `-- ...
|
test_results_summary.json
`-- outputs/index.html
```

There is no merged `test_results/` copy in the artifact, so each test folder is stored only once.

## metadata.json format

```json
{
  "test_number": 1,
  "test_id": "test_1_women_abc123",
  "gender": "women",
  "model_filename": "model_abc123.jpg",
  "garment_filename": "garment_xyz.jpg",
  "user_email": "biztest_xyz@test.com",
  "timestamp": "2026-01-22 14:30:00",
  "status": "success",
  "result_path": "/path/to/result.png",
  "error": "..."
}
```

## summary.json format

```json
{
  "total_tests": 62,
  "successful": 58,
  "failed": 4,
  "success_rate": "93.5%",
  "timestamp": "2026-01-22 14:45:00",
  "test_results_folder": "./test_results"
}
```
