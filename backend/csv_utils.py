"""CSV helpers for batch annotation."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from typing import List

from .schemas import AnnotationRequest


@dataclass
class CsvAnnotationParseResult:
    """Parsed CSV records plus lightweight validation details."""

    prompts: List[AnnotationRequest]
    valid_rows: int
    rows_with_response: int
    rows_without_response: int
    skipped_empty_prompt_rows: int
    task_type: str
    mixed_task_warning: str | None = None


def parse_csv_annotations(csv_text: str) -> List[AnnotationRequest]:
    """Parse CSV rows into annotation requests."""

    return parse_csv_annotation_file(csv_text).prompts


def parse_csv_annotation_file(csv_text: str) -> CsvAnnotationParseResult:
    """Parse CSV rows into annotation requests and validation details."""

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
    skipped_empty_prompt_rows = 0
    rows_with_response = 0
    rows_without_response = 0
    for index, row in enumerate(reader, start=1):
        prompt = (row.get(prompt_column) or "").strip()
        if not prompt:
            skipped_empty_prompt_rows += 1
            continue

        response = (
            (row.get(response_column) or "").strip() or None
            if response_column
            else None
        )
        if response:
            rows_with_response += 1
        else:
            rows_without_response += 1
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

    task_type = infer_task_type(rows_with_response, rows_without_response)
    return CsvAnnotationParseResult(
        prompts=requests,
        valid_rows=len(requests),
        rows_with_response=rows_with_response,
        rows_without_response=rows_without_response,
        skipped_empty_prompt_rows=skipped_empty_prompt_rows,
        task_type=task_type,
        mixed_task_warning=(
            "Mixed prompt and response rows detected. Rows with responses classify the response; rows without responses classify the prompt."
            if task_type == "mixed"
            else None
        ),
    )


def infer_task_type(rows_with_response: int, rows_without_response: int) -> str:
    """Infer the run task type from response-column usage."""

    if rows_with_response and rows_without_response:
        return "mixed"
    if rows_with_response:
        return "response_classification"
    return "prompt_classification"


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
