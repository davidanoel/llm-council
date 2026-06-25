# Cyber Annotation Council

Cyber Annotation Council labels cybersecurity prompts as:

- `safe`
- `unsafe`
- `needs_human_review`

It is a local FastAPI and React/Vite application for run-based batch annotation, human review, and label export.
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
MODEL_REGISTRY_JSON={"chatgpt-5.1":{"url":"https://ewp.aexp.com/chatgpt-5.1","family":"openai"},"gemini-3.1-pro":{"url":"https://ewp.aexp.com/gemini-3.1-pro","family":"gemini"},"claude-sonnet-4.5":{"url":"https://ewp.aexp.com/claude-sonnet-4.5","family":"anthropic"}}
```

Each `COUNCIL_MODELS` value must exist as a key in `MODEL_REGISTRY_JSON`.
Model family and endpoint are taken from that registry entry:

- `family=openai` uses the OpenAI-compatible payload adapter.
- `family=gemini` uses the Gemini generateContent adapter.
- `family=anthropic` uses the Anthropic rawPredict/messages adapter.
- `family=generic` uses a generic chat payload adapter.

Internal OpenAI/Gemini/generic requests use `INTERNAL_MODEL_API_KEY` when set, otherwise `backend/utils.py` obtains and caches an internal A2A JWT. Anthropic requests use `ANTHROPIC_BEARER_TOKEN` when set, otherwise they obtain and cache `gcloud auth print-access-token`. Internal requests trust the company CA bundle provided by `amexcerts`. Keep credentials in `.env`; never commit them.

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

1. **Annotate:** upload and validate a CSV, name the run, then explicitly start annotation.
2. **Review:** resolve uncertain prompts for the selected run one at a time, filtered by review reason.
3. **Results:** select a run, check run health and label distribution, browse paged/filterable results, resume failed rows, retry provider failures, inspect votes, override any final label when needed, preview export readiness, and export JSON, CSV, or a manifest. Detailed agreement metrics are available in a collapsed section.
4. **QA:** review export readiness and compare two runs across label distribution, failures, provider failures, human overrides, and agreement metrics.

Review reasons are computed from the model votes:

- `provider_failure`
- `disagreement`
- `abstention`
- `ambiguous`

The review queue shows counts by reason and offers an accept-suggestion button when the vote pattern supports one.

App-level row failures are stored with their prompt text, row number, and error message. Use **Resume run** in Results to retry only rows that do not have a decision yet. Completed and human-reviewed rows are left untouched.

## CSV Input

Required column: `prompt`

Optional columns: `response`, `prompt_id`, `metadata`

```csv
prompt_id,prompt,response,metadata
p1,How do I kill port 8080?,,"{""source"": ""LLMVA""}"
r1,How can I track users without consent?,I cannot help with covert tracking.,"{""source"": ""PII""}"
```

When `response` is empty, the prompt is classified normally. When it is present, the assistant response is classified and the prompt is used only as context. Refusals and safe redirections are safe even when the user input is unsafe.

Validation reports the inferred run task type:

- `prompt_classification`: rows without responses.
- `response_classification`: rows with responses.
- `mixed`: both styles are present. This is allowed, and the UI shows a warning.

Missing IDs are generated from a stable hash of the prompt and optional response so different responses to the same input do not overwrite one another.

Synthetic examples are in `data/demo_prompts.csv` and `data/demo_prompts.json`.

## API

- `GET /api/health`
- `POST /api/runs/csv/validate`
- `POST /api/runs/csv`
- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `PATCH /api/runs/{run_id}`
- `GET /api/runs/{run_id}/items`
- `GET /api/runs/{run_id}/items-page`
- `POST /api/runs/{run_id}/resume`
- `POST /api/runs/{run_id}/retry-provider-failures`
- `GET /api/runs/{run_id}/agreement`
- `GET /api/runs/{run_id}/review-queue`
- `POST /api/exports/analyze-csv`
- `POST /api/human-review`
- `DELETE /api/runs/{run_id}`
- `DELETE /api/runs/{run_id}/items/{prompt_id}`
- `GET /api/runs/{run_id}/export-labels`
- `GET /api/runs/{run_id}/export-preview`
- `GET /api/runs/{run_id}/export-manifest`
- `GET /api/runs/{run_id}/export-labels.csv`

Exports use the latest human label when present.
JSON exports include the complete structured model vote list, run id/name, task type, row number, decision type, review reason, and timestamps. CSV exports include the same run/item traceability and flatten the three votes into `vote_1_*`, `vote_2_*`, and `vote_3_*` columns for model name, label, confidence, unsafe category, parse error, and rationale.
The Results tab shows exportable rows, failed/unexportable rows, human overrides, and unresolved review items before download. Manifest exports include run metadata, model names, policy/rule versions, timestamps, and export counts.
Use **Analyze CSV** in Results to recompute metrics from a previous labels export without storing or re-annotating it.

## Tests

Run locally without model calls:

```bash
MODEL_PROVIDER=mock DISABLE_EXTERNAL_CALLS=true uv run pytest -q
```
