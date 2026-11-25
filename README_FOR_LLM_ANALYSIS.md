# Siz3r Model Testing - AI Assessment

## API key

Locally, edit the project-root `.env` file and set:

```dotenv
OPENAI_API_KEY=your-api-key
```

For a new setup, copy `.env.example` to `.env` and replace the placeholder. Existing environment variables take precedence over `.env`. The example contains no real key; `.env` is ignored by Git.

On GitHub, open **Settings > Secrets and variables > Actions > Repository secrets** and create or update **`OPENAI_API_KEY`**. GitHub Actions reads this secret directly. Updating the local `.env` does not update the GitHub secret.

## Editing the judgment prompts

- `prompts/tryon-judgment.txt`: the main assessment instructions.
- `prompts/tryon-integrity-audit.txt`: the second-pass verification of the whole assessment, including unsupported claims and missed defects.

Edit these plain-text files to change the judging instructions. `analyze_quality.js` loads them directly; `analysis.json` records their filenames and content hashes so reports from different prompt revisions can be identified. Deploy the `prompts/` directory along with the evaluator.

Both prompts cover garment design, fit/drape, person integrity, and scene/non-target items. Body reshaping requires comparable exposed skin or actual anatomical landmarks visible in both images, after allowing for image scale, pose, perspective, and coverage. Loose sleeves, padded shoulders, and chest drape cannot establish hidden body size. Hidden or ambiguous anatomy remains unassessed; clear changes in visible anatomy still matter even when the result looks realistic.

The second pass checks the original images and treats the first assessment as proposed claims. It can reject an unsupported body accusation, retain a real garment defect, and add an overlooked problem elsewhere. Its structured evidence records what was observed in the reference and result, the comparison basis, certainty, and whether an ordinary clothing/pose explanation was ruled out. This reduces dependence on repeated body-region reminders in the prompt; it does not guarantee that every visual judgment is correct.

These instructions do not change the fixed scoring penalties in `lib/assessment.js`. Existing reports keep their original judgments; use a new manual assessment to evaluate a changed prompt.

## Local assessment

Use Node.js 22 or newer, run `npm ci`, then `npm run analyze`.

The script discovers `test_results_upper/`, `test_results_lower/`, `test_results_full/`, and unpacked artifacts under `test_results/`. It also supports the older flat `images/` layout. Each case is detected independently, so several artifacts can be unpacked into separate subfolders without overwriting each other.

Set `ANALYZE_SOURCE_DIR` to one artifact root, one test folder, or a comma-, semicolon-, or newline-separated list of roots to choose inputs explicitly. AI assessment requires the garment reference, original person, and generated result. AVIF inputs are converted for the API without changing the original files.

Outputs:

- `outputs/index.html`: a portable review with embedded pictures, generation settings, scores, explanations, and failures.
- `outputs/analysis.json`: judgments, source-run information, and diagnostic errors.

The HTML review groups results by garment filename and intended transfer mode, with all models for one garment together before the next. A clothing overview links to each group and shows model counts, pass/fail counts, average scores, and errors. Average scores use completed judgments only.

At the top, **Most common reported problems** groups the existing critical/minor findings into problem types and ranks them by the number of affected results. Each type counts once per evaluated result even if several findings describe it. Results with several different problem types contribute to each relevant count. Generation failures, incomplete assessments, notes, and positive statements do not inflate these counts. Unknown problem descriptions remain visible as separate types. No additional AI requests are needed for this summary, and it does not alter scores.

`analysis.json` also includes `summary.by_garment` and `summary.common_problems`. Deploy both `lib/review-summary.js` and `lib/review-images.js` with the evaluator.

The AI review stores each unique image once inside the HTML. Display copies use WebP quality 88 and a maximum width/height of 1600 pixels, without enlarging smaller images. This reduces repeated person/garment images and large result PNGs. The original files and the full-resolution images sent to the AI are unchanged. Generation-only galleries continue to reference the original images.

To rebuild the layout of an existing report without judging the images again:

```sh
npm run report -- "path/to/unpacked-report/outputs/analysis.json" "outputs/grouped-review"
```

This reuses the saved judgments and original model/threshold information. It makes no AI calls and does not change any scores. The original unpacked report must be available while rebuilding; afterward, the new HTML contains its own image copies.

Open or share `index.html` on its own. No image folders are needed for an AI review; use a browser with JavaScript enabled. `analysis.json` is also saved locally for diagnostics.

## Judge a generation on GitHub

1. Open the **Siz3r Model Tests** generation run you want to judge and copy its URL.
2. Open **Actions > Analyze with LLM > Run workflow**, using a branch with the updated workflow.
3. Paste the link into the only input, **`run_url`**.
4. Click **Run workflow**.

That link selects the exact generation, including its branch and available upper/lower/full results. No category, quality, or profile choices are needed. An empty or invalid link produces a clear error; the workflow never falls back to a newer run.

The selected generation must have completed and its result artifact must still be available. Both current artifact names and the older `siz3r-test-results` name work. The report records the source run, branch, commit, and generation settings.

Download the `llm-quality-analysis` artifact, unzip it, and open `index.html`. The judgment artifact contains only this HTML review. Original source images remain in the selected generation's artifact.

Judgments run only when you start **Analyze with LLM** manually. Finishing a model test does not start an assessment. Apply the manual-only workflow to the default branch (`main`) as well, since GitHub uses that branch's workflow to decide whether completed model tests should start another workflow. Manual runs can use an updated branch containing the evaluator and its dependencies.

The maintained workflow is `.github/workflows/analyze-with-llm.yml`.

## Judgment and failure handling

The API receives all three images and the intended upper/lower/full transfer mode. Full-outfit transfers may replace both upper and lower clothing. The first pass proposes an assessment with four severity labels. The second pass verifies the whole result and returns structured findings, observations for all four review areas, rejected preliminary claims, and a coherent final explanation. It can correct both overly harsh and overly lenient assessments.

The application starts at 100 and subtracts these fixed penalties:

| Label | MINOR penalty | MAJOR penalty |
| --- | ---: | ---: |
| Garment structure / silhouette | 20 | 60 |
| Construction / detail alignment | 15 | 40 |
| Fit | 10 | 30 |
| Artifacts / collateral damage | 5 | 40 |

Passing requires at least 80% by default, at most two MINOR labels, no MAJOR labels, and no critical issues. By default every valid assessment receives the second verification pass, including initial quality failures. The application derives the final labels and issue lists from supported, confirmed verification findings; it does not combine the harshest claims from both passes. Uncertain findings and comparisons without suitable evidence do not create penalties. Free-text keywords never create or remove defects.

For a body-shape finding, the evidence must identify comparable exposed skin or actual anatomical landmarks and rule out a clothing/pose explanation. Fabric outlines cannot satisfy that evidence requirement. Other defects, such as malformed anatomy or a damaged boundary, can rely on directly visible damage without inferring concealed body proportions. Non-body garment defects remain eligible for their usual penalties, even when a body accusation is rejected.

The final verdict notes are built from the same accepted findings as the score. Specific supported positives come from verification, so valid garment strengths need not disappear when another area fails. Each HTML entry has a collapsible **Review evidence and limitations** section with the four comparison areas, evidence for scored issues, and excluded claims. New `analysis.json` reports use schema version 3 and retain `primary_rating`, raw verification notes, and evidence for diagnostics. Existing reports keep their original judgments. If verification fails, the assessment is incomplete and has no final score. Conflicting or uncertain visual claims should still be checked against the images; offline code tests do not establish visual accuracy.

The default remains two AI requests per judged case, plus one correction request if the main reply contains inconsistent severity. For compatibility, the existing `ANALYZE_ENABLE_ARTIFACT_AUDIT=false` setting now limits whole-assessment verification to passing candidates; initially failing assessments then retain the primary verdict. Leave the default enabled for consistent verification of both passes and failures. The workflow uses this default. Image requests explicitly use high detail for visual comparison.

If the AI lists a critical issue but assigns only NONE/MINOR labels, it is asked once to correct its assessment using the same images. This adds one assessment request for the affected case. The application does not choose which severity is correct. A second inconsistent reply remains an assessment error; both the original reply and correction attempt are recorded in `analysis.json`.

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
- `ANALYZE_ENABLE_ARTIFACT_AUDIT`: legacy setting name; default `true` verifies the whole assessment for both passing and failing candidates. `false` verifies passing candidates only and retains primary verdicts for initial failures.
- `ANALYZE_SOURCE_DIR`: optional input root or list of roots.
- `ANALYSIS_OUTPUT_DIR`: report directory; default `outputs`.
- `ANALYSIS_REPORT_MODE`: `gallery`, `review` (default), or `comparison`.

For GitHub, set repository variables `OPENAI_MODEL` and `OPENAI_PASS_SCORE_THRESHOLD` to change the evaluator defaults. API keys belong in secrets. These settings do not appear in the run form.

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
