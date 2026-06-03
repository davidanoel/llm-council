"""CSV helpers for batch annotation."""

from __future__ import annotations

import csv
import io
import json
from typing import List

from .schemas import AnnotationRequest


def parse_csv_annotations(csv_text: str) -> List[AnnotationRequest]:
    """Parse CSV rows into annotation requests."""

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames or "prompt" not in reader.fieldnames:
        raise ValueError("CSV must include a required 'prompt' column.")

    requests = []
    for index, row in enumerate(reader, start=1):
        prompt = (row.get("prompt") or "").strip()
        if not prompt:
            continue

        prompt_id = (row.get("prompt_id") or "").strip() or f"row_{index}"
        metadata = parse_metadata(row.get("metadata"))
        requests.append(
            AnnotationRequest(
                prompt_id=prompt_id,
                prompt_text=prompt,
                metadata=metadata,
            )
        )

    return requests


def parse_metadata(raw_metadata: str | None) -> dict:
    """Parse optional metadata JSON object."""

    if not raw_metadata or not raw_metadata.strip():
        return {}
    parsed = json.loads(raw_metadata)
    if not isinstance(parsed, dict):
        raise ValueError("CSV metadata column must contain a JSON object.")
    return parsed
