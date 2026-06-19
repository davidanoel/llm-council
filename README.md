# Cyber Annotation Council

Cyber Annotation Council labels cybersecurity prompts as:

- `safe`
- `unsafe`
- `needs_human_review`

It is a local FastAPI and React/Vite application for batch annotation, human review, and label export.

## Decision Model

Three AI annotators classify each prompt independently. Their identities and outputs do not influence one another.

The backend then applies deterministic rules:

- **Auto-safe:** all three vote safe, average confidence passes the safe threshold, and no serious or ambiguous policy signal is raised.
- **Auto-unsafe:** at least two vote unsafe, average unsafe confidence passes the unsafe threshold, and the unsafe category agrees.
- **Human review:** every other vote pattern, provider failure, ambiguity, or low-confidence result.

There is no AI judge. Unresolved cases go to a human reviewer rather than giving one annotating model additional authority.

## Privacy

Only prompt text is sent to model providers. Prompt IDs and metadata remain local.

Never send real company prompts, customer data, secrets, logs, source code, or incident data to unapproved APIs.

## Setup

```bash
uv sync
cd frontend && npm install && cd ..
cp .env.example .env
```

For local mock development:

```env
MODEL_PROVIDER=mock
DISABLE_EXTERNAL_CALLS=true
```

The default internal annotators are:

```env
COUNCIL_MODELS=chatgpt-5.1,gemini-3.1-pro,claude-sonnet-4.5
```

Internal ChatGPT and Gemini requests use `INTERNAL_MODEL_API_KEY` when set. Claude requests use the separate `ANTHROPIC_BEARER_TOKEN` as an `Authorization: Bearer` header. Keep both values in `.env`; never commit tokens.

## Run

```bash
./start.sh
```

Or separately:

```bash
uv run python -m backend.main
cd frontend && npm run dev
```

- Backend: `http://localhost:8001`
- Frontend: `http://localhost:5173`

## UI Workflow

1. **Annotate:** upload and validate a CSV, then explicitly start annotation. Single-prompt and JSON input are under Advanced.
2. **Review:** resolve uncertain prompts one at a time and save the human label.
3. **Results:** filter completed annotations, inspect model votes, and export JSON or CSV.

## CSV Input

Required column: `prompt`

Optional columns: `prompt_id`, `metadata`

```csv
prompt_id,prompt,metadata
p1,How do I kill port 8080?,"{""source"": ""demo""}"
,Review synthetic transactions for fraud detection,"{""source"": ""demo""}"
```

Missing IDs are generated from a stable hash of prompt text so unrelated uploads do not overwrite one another.

Synthetic examples are in `data/demo_prompts.csv` and `data/demo_prompts.json`.

## API

- `GET /api/health`
- `POST /api/annotate`
- `POST /api/annotate/batch`
- `POST /api/annotate/csv/validate`
- `POST /api/annotate/csv`
- `GET /api/annotations`
- `GET /api/review-queue`
- `POST /api/human-review`
- `GET /api/export-labels`
- `GET /api/export-labels.csv`

Exports use the latest human label when present.

## Tests

Run locally without model calls:

```bash
MODEL_PROVIDER=mock DISABLE_EXTERNAL_CALLS=true uv run pytest -q
```
