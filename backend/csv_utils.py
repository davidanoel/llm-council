"""CSV helpers for batch annotation."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import List

from .schemas import AnnotationRequest


def parse_csv_annotations(csv_text: str) -> List[AnnotationRequest]:
    """Parse CSV rows into annotation requests."""

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV must include a required prompt column.")

    fieldnames = {name.strip().lower(): name for name in reader.fieldnames}
    prompt_column = next(
        (
            fieldnames[name]
            for name in ("prompt", "dialogue_history", "text")
            if name in fieldnames
        ),
        None,
    )
    if not prompt_column:
        raise ValueError(
            "CSV must include a required 'prompt', 'dialogue_history', or 'text' column."
        )

    response_column = next(
        (
            fieldnames[name]
            for name in ("response", "model_output")
            if name in fieldnames
        ),
        None,
    )

    requests = []
    for index, row in enumerate(reader, start=1):
        prompt = (row.get(prompt_column) or "").strip()
        if not prompt:
            continue

        response = (
            (row.get(response_column) or "").strip() or None
            if response_column
            else None
        )
        prompt_id = (row.get("prompt_id") or "").strip() or deterministic_prompt_id(
            prompt, response
        )
        metadata = parse_metadata(row.get("metadata"))
        requests.append(
            AnnotationRequest(
                prompt_id=prompt_id,
                prompt_text=prompt,
                response_text=response,
                metadata=metadata,
            )
        )

    return requests


def deterministic_prompt_id(prompt: str, response: str | None = None) -> str:
    """Build a stable ID that does not collide between unrelated CSV uploads."""

    content = f"{prompt}\n{response or ''}"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return f"prompt_{digest}"


def parse_metadata(raw_metadata: str | None) -> dict:
    """Parse optional metadata JSON object."""

    if not raw_metadata or not raw_metadata.strip():
        return {}
    parsed = json.loads(raw_metadata)
    if not isinstance(parsed, dict):
        raise ValueError("CSV metadata column must contain a JSON object.")
    return parsed
