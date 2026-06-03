# Cyber Annotation Council

Cyber Annotation Council is a local prompt labelling tool for cybersecurity safety review. It classifies prompts as:

- `safe`
- `unsafe`
- `needs_human_review`

The app uses a simple council pattern:

1. Independent model votes.
2. Peer critique/disagreement pass.
3. Final adjudication.
4. Optional human override.
5. Label export.
6. Evaluation against human-majority labels.

The backend is FastAPI. The frontend is React/Vite. Local storage is JSON files in `data/annotations/`.

## Privacy

The default provider configuration is `internal` and points at company model URLs under `https://ewp.aexp.com/<modelname>`.

Never send real company prompts, customer data, secrets, logs, source code, incident data, or internal system details to external APIs without explicit approval.

For purely local development, set `MODEL_PROVIDER=mock` and `DISABLE_EXTERNAL_CALLS=true`.

## Setup

Install backend dependencies:

```bash
uv sync
```

Install frontend dependencies:

```bash
cd frontend
npm install
cd ..
```

Copy local environment defaults:

```bash
cp .env.example .env
```

## Run Backend

```bash
uv run python -m backend.main
```

Backend health:

```bash
curl http://localhost:8001/api/health
```

## Run Frontend

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173`.

## Internal Provider

Default internal configuration:

```bash
MODEL_PROVIDER=internal
COUNCIL_MODELS=chatgpt-5.1,gemini-3.1-pro,claude-sonnet-4.5
ADJUDICATOR_MODEL=gemini-3.1-pro
CHATGPT_5_1_URL=https://ewp.aexp.com/chatgpt-5.1
GEMINI_3_1_PRO_URL=https://ewp.aexp.com/gemini-3.1-pro
CLAUDE_SONNET_4_5_URL=https://ewp.aexp.com/claude-sonnet-4.5
```

Optional bearer auth:

```bash
INTERNAL_MODEL_API_KEY=
```

## Mock Provider

The mock provider is deterministic and synthetic. It is intended for UI development, storage testing, and evaluation plumbing.

```bash
MODEL_PROVIDER=mock
DISABLE_EXTERNAL_CALLS=true
```

## Annotate One Prompt

Use the frontend Single Annotation panel or call:

```bash
curl -X POST http://localhost:8001/api/annotate \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt_id": "demo-safe-port",
    "prompt_text": "How do I kill port 8080 on my laptop?",
    "metadata": {"source": "demo"}
  }'
```

## Batch Annotate

CSV upload is the primary batch path in the frontend.

Expected CSV format:

```csv
prompt_id,prompt,metadata
p1,How do I kill port 8080?,"{""source"": ""demo""}"
,Review synthetic transactions for fraud detection,"{""source"": ""demo""}"
```

The `prompt` column is required. `prompt_id` and `metadata` are optional. Missing `prompt_id` values become deterministic IDs such as `row_1`, `row_2`, and so on.

You can also call the CSV endpoint directly:

```bash
curl -X POST http://localhost:8001/api/annotate/csv \
  -H 'Content-Type: text/csv' \
  --data-binary @prompts.csv
```

JSON batch remains available:

```bash
curl -X POST http://localhost:8001/api/annotate/batch \
  -H 'Content-Type: application/json' \
  -d '{"prompts": [
    {
      "prompt_id": "demo-safe-port",
      "prompt_text": "How do I kill port 8080 on my laptop?",
      "metadata": {"source": "demo"}
    }
  ]}'
```

Synthetic demo prompts are available in `data/demo_prompts.json`.

## Review Human Queue

Prompts adjudicated as `human_review` appear at:

```bash
curl http://localhost:8001/api/review-queue
```

Save an override:

```bash
curl -X POST http://localhost:8001/api/human-review \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt_id": "demo-ambiguous-exploit",
    "label": "needs_human_review",
    "unsafe_category": "exploit_execution",
    "rationale": "Authorization is unclear.",
    "reviewer": "analyst"
  }'
```

The frontend clearly separates council label, human override, and final effective label.

## Export Labels

```bash
curl 'http://localhost:8001/api/export-labels?include_prompt_text=true'
```

Human overrides take precedence over council labels in export output.

## Evaluate Against Human-Majority Labels

The evaluation API compares stored predictions against supplied gold labels. `unsafe` is positive, `safe` is negative, and `needs_human_review` is treated as abstention.

```bash
curl -X POST http://localhost:8001/api/evaluate \
  -H 'Content-Type: application/json' \
  -d '{
    "labels": [
      {"prompt_id": "demo-safe-port", "label": "safe"}
    ]
  }'
```

The frontend Evaluation panel accepts records shaped like:

```json
[
  {
    "prompt_id": "demo-safe-port",
    "gold_label": "safe",
    "predicted_label": "safe"
  }
]
```

`predicted_label` is shown for analyst convenience in pasted records; the backend evaluates against stored exported predictions.

## Tests

```bash
uv run pytest -q
```
