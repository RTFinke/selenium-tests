# Siz3r Model Testing - LLM Analysis Guide

## Aktualny lokalny workflow

`analyze_quality.js` domyślnie szuka wyników w `test_results/` (a jeśli go nie ma, to w `images/`).

Po analizie dostajesz:
- `outputs/evals.jsonl` - wszystkie rekordy oceny
- `outputs/analysis_summary.json` - zbiorcze statystyki
- `outputs/review/` - jeden wygodny folder do ręcznego przeglądu

W `outputs/review/` znajdziesz:
- `index.html` - galeria z podglądem modelu, ubrania, wyniku i oceną AI
- `index.csv` - szybki eksport do tabeli
- `index.json` - pełny indeks danych
- osobny podfolder dla każdego testu z `model.*`, `garment.*`, `result.*`, `quality.json`, `summary.txt`

Przydatne zmienne środowiskowe:
- `ANALYZE_SOURCE_DIR` - wymusza katalog wejściowy
- `ANALYSIS_OUTPUT_DIR` - zmienia katalog `outputs/`
- `ANALYSIS_REVIEW_DIR` - zmienia nazwę folderu review
- `OPENAI_CONCURRENCY` - liczba równoległych ocen

## Struktura wyników

Po każdym teście GitHub Actions generuje artifacts z następującą strukturą:
```
test_results/
├── summary.json                          # Ogólne podsumowanie
├── test_1_women_model123/
│   ├── metadata.json                     # Info o teście
│   ├── garment/garment.jpg              # Użyte ubranie
│   ├── model/model.jpg                  # Użyty model (osoba)
│   └── result/result.png                # Wygenerowany wynik
├── test_2_men_model456/
│   └── ...
└── test_62_women_model789/
    └── ...
```

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
  "status": "success",  // lub "failed"
  "result_path": "/path/to/result.png",
  "error": "..."  // jeśli failed
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

## Jak dodać LLM analysis do Actions

Stwórz osobny workflow `.github/workflows/analyze-results.yml`:
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
    
    - name: Setup Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Install dependencies
      run: |
        pip install anthropic pillow
    
    - name: Run LLM analysis
      env:
        ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      run: |
        python analyze_with_llm.py
    
    - name: Upload analysis report
      uses: actions/upload-artifact@v3
      with:
        name: llm-analysis-report
        path: analysis_report.md
```

## Przykładowy analyze_with_llm.py
```python
import anthropic
import json
import os
from pathlib import Path

client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

# Load summary
with open('test_results/summary.json') as f:
    summary = json.load(f)

# Analyze each test
results = []
for test_dir in Path('test_results').glob('test_*'):
    if not test_dir.is_dir():
        continue
    
    metadata_path = test_dir / 'metadata.json'
    if not metadata_path.exists():
        continue
    
    with open(metadata_path) as f:
        metadata = json.load(f)
    
    # TODO: Load images and send to Claude for vision analysis
    # Sprawdź: czy wynik wygląda realistycznie, czy są artifakty, itp.
    
    results.append(metadata)

# Generate report
# ...
```
