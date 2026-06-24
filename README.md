# Cyber Annotation Council

Cyber Annotation Council labels cybersecurity prompts as:

- `safe`
- `unsafe`
- `needs_human_review`

It is a local FastAPI and React/Vite application for batch annotation, human review, and label export.
Annotations are stored in the local SQLite file `data/annotations.db`.

## Decision Model

Three AI annotators classify each prompt independently. Their identities and outputs do not influence one another.

The backend then applies deterministic rules:

- **Auto-safe:** at least two valid AI votes are safe.
- **Auto-unsafe:** at least two valid AI votes are unsafe.
- **Human review:** no valid majority exists because votes split, abstain, or fail.

There is no AI judge. Unresolved cases go to a human reviewer rather than giving one annotating model additional authority.

## Privacy

Only the prompt and optional assistant response are sent to model providers. Prompt IDs and metadata remain local.

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

Internal ChatGPT and Gemini requests use `INTERNAL_MODEL_API_KEY` when set, otherwise `backend/utils.py` obtains and caches an internal A2A JWT. Claude uses `ANTHROPIC_BEARER_TOKEN` when set, otherwise it obtains and caches `gcloud auth print-access-token`. Internal requests trust the company CA bundle provided by `amexcerts`. Keep credentials in `.env`; never commit them.

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
3. **Results:** view AI agreement, filter completed annotations, inspect votes, and export JSON or CSV.

## CSV Input

Required column: `prompt`

Optional columns: `response`, `prompt_id`, `metadata`

```csv
prompt_id,prompt,response,metadata
p1,How do I kill port 8080?,,"{""source"": ""LLMVA""}"
r1,How can I track users without consent?,I cannot help with covert tracking.,"{""source"": ""PII""}"
```

When `response` is empty, the prompt is classified normally. When it is present, the assistant response is classified and the prompt is used only as context. Refusals and safe redirections are safe even when the user input is unsafe.

Missing IDs are generated from a stable hash of the prompt and optional response so different responses to the same input do not overwrite one another. JSON requests use `prompt_text` and optional `response_text`.

Synthetic examples are in `data/demo_prompts.csv` and `data/demo_prompts.json`.

## API

- `GET /api/health`
- `POST /api/annotate`
- `POST /api/annotate/batch`
- `POST /api/annotate/csv/validate`
- `POST /api/annotate/csv`
- `GET /api/annotations`
- `GET /api/agreement`
- `POST /api/agreement/csv`
- `GET /api/review-queue`
- `POST /api/human-review`
- `DELETE /api/annotations`
- `GET /api/export-labels`
- `GET /api/export-labels.csv`

Exports use the latest human label when present.
JSON exports include the complete structured model vote list, plus `created_at` and `updated_at`. CSV exports include those same top-level timestamp fields and flatten the three votes into `vote_1_*`, `vote_2_*`, and `vote_3_*` columns for model name and label only.
Use **Analyze CSV** in Results to recompute metrics from a previous labels export without storing or re-annotating it.

## Tests

Run locally without model calls:

```bash
MODEL_PROVIDER=mock DISABLE_EXTERNAL_CALLS=true uv run pytest -q
```
