import pytest

from backend.csv_utils import parse_csv_annotations


def test_csv_parsing_with_required_prompt_column():
    records = parse_csv_annotations('prompt_id,prompt,metadata\np1,"Review fraud alerts","{""source"": ""csv""}"\n')

    assert len(records) == 1
    assert records[0].prompt_id == "p1"
    assert records[0].prompt_text == "Review fraud alerts"
    assert records[0].metadata == {"source": "csv"}


def test_csv_parsing_optional_response_column():
    records = parse_csv_annotations(
        'prompt_id,prompt,response\nr1,"Track users without consent","I cannot help with covert tracking."\n'
    )

    assert records[0].prompt_text == "Track users without consent"
    assert records[0].response_text == "I cannot help with covert tracking."


def test_csv_parsing_missing_prompt_column():
    with pytest.raises(ValueError, match="prompt"):
        parse_csv_annotations("prompt_id,text\np1,hello\n")


def test_csv_rows_without_prompt_id_get_deterministic_ids():
    records = parse_csv_annotations("prompt\nfirst prompt\nsecond prompt\n")

    assert all(record.prompt_id.startswith("prompt_") for record in records)
    assert records[0].prompt_id != records[1].prompt_id
    assert records[0].prompt_id == parse_csv_annotations("prompt\nfirst prompt\n")[0].prompt_id


def test_different_responses_to_same_prompt_get_different_ids():
    records = parse_csv_annotations(
        'prompt,response\n"same prompt","first response"\n"same prompt","second response"\n'
    )

    assert records[0].prompt_id != records[1].prompt_id
