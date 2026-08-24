# Siz3r Model Testing - LLM Analysis Guide

## Local workflow

`analyze_quality.js` looks for results in `test_results/` by default. If that folder does not exist, it falls back to `images/`.
You can also point it at multiple source directories by setting `ANALYZE_SOURCE_DIR` to a comma-, semicolon-, or newline-separated list.

After analysis you get:
- `outputs/index.html` - a single review report for manual QA

The report:
- shows the model, garment, and result images
- can render either a generation-only gallery or an AI review summary, depending on `ANALYSIS_REPORT_MODE`
- reads the original files directly from the source folders you provide
- does not create extra `json`, `csv`, or review subfolders

Useful environment variables:
- `ANALYZE_SOURCE_DIR` - force the input directory or directories
- `ANALYSIS_OUTPUT_DIR` - change the `outputs/` directory
- `ANALYSIS_REPORT_MODE` - `gallery` for generation-only HTML, `review` for AI evaluation HTML
- `OPENAI_CONCURRENCY` - number of parallel evaluations

GitHub Actions usage:
- `Siz3r Model Tests` should run with `ANALYZE_SOURCE_DIR=test_results_upper,test_results_lower,test_results_full` and `ANALYSIS_REPORT_MODE=gallery` so `outputs/index.html` is just the generation gallery
- The `run_keys` field accepts `upper`, `lower`, and `full`. Leave it blank to run all three, or provide a comma-separated subset such as `upper,lower`.
- The `fashn-turbo` workflow enables and verifies Turbo mode before every try-on. The selected Actions run name includes `mode=turbo` together with the garment runs, pairing mode, cap, and browser-session reuse setting.
- `Analyze with LLM` should run with `ANALYZE_SOURCE_DIR=test_results/test_results_upper,test_results/test_results_lower,test_results/test_results_full`, `ANALYSIS_REPORT_MODE=review`, and `OPENAI_API_KEY` for AI judgments

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

## GitHub Actions example

Create a dedicated workflow in `.github/workflows/analyze-results.yml`:

```yaml
name: Analyze Test Results with LLM

on:
  repository_dispatch:
    types: [test-results-ready]

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3

    - name: Download artifacts
      uses: actions/download-artifact@v3
      with:
        name: siz3r-test-results
        path: test_results/

    - name: Run LLM analysis
      env:
        ANALYZE_SOURCE_DIR: test_results/test_results_upper,test_results/test_results_lower,test_results/test_results_full
        OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      run: |
        npm ci
        node analyze_quality.js

    - name: Upload HTML report
      uses: actions/upload-artifact@v3
      with:
        name: llm-analysis-report
        path: outputs/index.html
```
