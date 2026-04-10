# Adaptive Tool Log Intelligence Pipeline

AI-assisted semiconductor log parsing and schema normalization prototype.

## What This Prototype Includes
- FastAPI backend for log ingestion, parsing, normalization, storage, and retrieval
- Hybrid parsing:
  - Structured logs (`JSON`, `XML`, `CSV`) parsed with code
  - Unstructured text logs parsed with regex + optional LLM hook
- Semantic normalization and learned schema mapping (feedback loop)
- Human-readable explanation generation
- SQLite persistence (default)
- Optional anomaly detection (if `scikit-learn` is installed)
- Streamlit UI for demo
- Synthetic dataset for testing/demo

## Project Structure
```
.
├── app
│   ├── __init__.py
│   ├── anomaly.py
│   ├── db.py
│   ├── detector.py
│   ├── explainer.py
│   ├── llm.py
│   ├── main.py
│   ├── models.py
│   ├── parser.py
│   └── schema_mapper.py
├── data
│   └── synthetic_logs
│       ├── sample.csv
│       ├── sample.json
│       ├── sample.txt
│       └── sample.xml
├── docs
│   └── architecture.md
├── streamlit_app.py
└── requirements.txt
```

## How To Run
1. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Start the FastAPI backend:
   ```bash
   uvicorn app.main:app --reload
   ```
4. In a new terminal, start the Streamlit UI (optional):
   ```bash
   streamlit run streamlit_app.py
   ```
5. Open:
   - API docs: `http://127.0.0.1:8000/docs`
   - Streamlit UI: `http://127.0.0.1:8501`

## Quick API Test
Send raw text log:
```bash
curl -X POST "http://127.0.0.1:8000/upload-log" \
  -F "raw_text=ALARM 102: Vacuum pressure low at chamber 3 TEMP=87.2 P=0.8"
```

Send file log:
```bash
curl -X POST "http://127.0.0.1:8000/upload-log" \
  -F "file=@data/synthetic_logs/sample.txt"
```

## API Endpoints
- `POST /upload-log`:
  - multipart form upload (`file`) OR raw text (`raw_text`)
- `GET /logs`: list stored normalized log entries
- `GET /logs/{log_id}`: fetch a specific stored entry
- `POST /feedback`: add/update learned field mapping rule
- `GET /schema-rules`: show learned mapping rules
- `GET /stats`: ingestion and confidence summary
- `GET /anomaly-check`: optional anomaly scoring over stored logs

## Environment Variables
- `DB_PATH` (default: `log_pipeline.db`)
- `OPENAI_API_KEY` (optional, for LLM fallback in unstructured parsing/explanation)
- `OPENAI_MODEL` (default: `gpt-4o-mini`)

## Active Learning Loop
- Parser generates normalized output with confidence score.
- Low confidence results are flagged (`needs_review = true`).
- User can submit feedback via `/feedback` to map `raw_key -> canonical_key`.
- Future ingestions apply learned mapping automatically.

## Notes
- This is a practical prototype aligned to the challenge scope.
- It is **not** full autonomous retraining.
- Binary formats are out of scope in this prototype.
