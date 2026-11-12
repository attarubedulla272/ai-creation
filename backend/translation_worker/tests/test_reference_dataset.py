"""Sanity checks for provisional parallel examples; not model-quality tests."""

import json
from pathlib import Path

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "reference_translations.json"
EXPECTED_DIRECTIONS = {("en", "hi"), ("hi", "en"), ("en", "te"), ("te", "en")}


def test_reference_dataset_has_required_translation_directions() -> None:
    examples = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert {(item["source_language"], item["target_language"]) for item in examples} == (
        EXPECTED_DIRECTIONS
    )
    assert all(
        item["source_text"].strip()
        and item["reference_text"].strip()
        and item["reference_status"] == "provisional_project_reference"
        for item in examples
    )
