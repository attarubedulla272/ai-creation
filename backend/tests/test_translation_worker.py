"""Model-free tests for the isolated translation worker contract."""

import asyncio
import importlib.util
import sys
from pathlib import Path
from threading import Event
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

WORKER_PATH = Path(__file__).parents[1] / "translation_worker" / "app.py"


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location("acs_translation_worker", WORKER_PATH)
    if specification is None or specification.loader is None:
        raise RuntimeError("Could not import the isolated translation worker.")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    monkeypatch.delenv("INDICTRANS_EN_INDIC_MODEL_PATH", raising=False)
    monkeypatch.delenv("INDICTRANS_INDIC_EN_MODEL_PATH", raising=False)
    module.runtime = module.IndicTransRuntime()
    return module


def test_translation_worker_does_not_download_models(worker: ModuleType) -> None:
    assert worker.runtime.configured_directions() == []
    assert asyncio.run(worker.health()) == {
        "status": "model_not_configured",
        "provider": "indictrans2-worker",
        "configured_directions": [],
        "model_downloads_enabled": False,
    }


def test_worker_only_reports_complete_pinned_local_snapshots(
    worker: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model_spec = worker.MODEL_SPECS["en-indic"]
    snapshot = tmp_path / model_spec["revision"]
    snapshot.mkdir()
    for filename in worker.REQUIRED_MODEL_FILES:
        (snapshot / filename).touch()
    monkeypatch.setenv(model_spec["environment_variable"], str(snapshot))

    assert worker.runtime.configured_directions() == ["en-indic"]
    monkeypatch.setenv(model_spec["environment_variable"], str(tmp_path))
    assert worker.runtime.configured_directions() == []


def test_glossary_term_is_preserved_exactly(worker: ModuleType, monkeypatch) -> None:
    runtime = worker.IndicTransRuntime()
    monkeypatch.setattr(runtime, "_translate_plain", lambda text, source, target: text.upper())
    term = worker.GlossaryItem(source="AI Creator Studio", translation="एआई क्रिएटर स्टूडियो")

    translated = runtime._translate_with_glossary(
        "Build with AI Creator Studio today.",
        "eng_Latn",
        "hin_Deva",
        [term],
    )

    assert translated == "BUILD WITH एआई क्रिएटर स्टूडियो TODAY."


def test_glossary_falls_back_to_exact_term_splicing(worker: ModuleType, monkeypatch) -> None:
    runtime = worker.IndicTransRuntime()

    def remove_protected_marker(text: str, source: str, target: str) -> str:
        return text.replace("ACSXGLOSSARY0000TERM", "")

    monkeypatch.setattr(runtime, "_translate_plain", remove_protected_marker)
    term = worker.GlossaryItem(source="Acme", translation="एक्मे")

    translated = runtime._translate_with_glossary(
        "Acme Studio",
        "eng_Latn",
        "hin_Deva",
        [term],
    )

    assert translated == "एक्मे Studio"


def test_worker_rejects_unsupported_indic_to_indic_pair(worker: ModuleType) -> None:
    payload = worker.TranslationRequest(
        text="नमस्ते",
        source_language="hi",
        target_language="te",
    )

    with pytest.raises(ValueError, match="Indic-to-Indic"):
        asyncio.run(worker.runtime.translate(payload))


def test_authenticated_worker_api_returns_model_provenance(worker: ModuleType) -> None:
    worker.worker_token = "worker-test-token"

    async def translate(payload):
        return worker.TranslationResponse(
            translated_text=f"{payload.target_language}: translated",
            provider="indictrans2-worker",
            model=worker.MODEL_SPECS["en-indic"]["name"],
            model_version=worker.MODEL_SPECS["en-indic"]["revision"],
            model_license=worker.MODEL_LICENSE,
        )

    worker.runtime.translate = translate
    with TestClient(worker.app) as client:
        unauthorized = client.post(
            "/translate",
            json={
                "text": "Good morning.",
                "source_language": "en",
                "target_language": "hi",
            },
        )
        assert unauthorized.status_code == 401
        response = client.post(
            "/translate",
            headers={"Authorization": "Bearer worker-test-token"},
            json={
                "text": "Good morning.",
                "source_language": "en",
                "target_language": "hi",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "translated_text": "hi: translated",
        "provider": "indictrans2-worker",
        "model": worker.MODEL_SPECS["en-indic"]["name"],
        "model_version": worker.MODEL_SPECS["en-indic"]["revision"],
        "model_license": worker.MODEL_LICENSE,
    }


def test_cancellation_waits_for_inference_thread_before_releasing_model_lock(
    worker: ModuleType,
) -> None:
    runtime = worker.IndicTransRuntime()
    payload = worker.TranslationRequest(
        text="A sentence.",
        source_language="en",
        target_language="hi",
    )
    inference_started = Event()
    allow_inference_to_finish = Event()
    active_inferences = 0
    max_active_inferences = 0

    def run_inference(*_args):
        nonlocal active_inferences, max_active_inferences
        active_inferences += 1
        max_active_inferences = max(max_active_inferences, active_inferences)
        inference_started.set()
        allow_inference_to_finish.wait(timeout=2)
        active_inferences -= 1
        return worker.TranslationResponse(
            translated_text="एक वाक्य।",
            provider="indictrans2-worker",
            model=worker.MODEL_SPECS["en-indic"]["name"],
            model_version=worker.MODEL_SPECS["en-indic"]["revision"],
            model_license=worker.MODEL_LICENSE,
        )

    runtime._translate_sync = run_inference

    async def exercise_cancellation() -> None:
        first = asyncio.create_task(runtime.translate(payload))
        assert await asyncio.to_thread(inference_started.wait, 1)
        first.cancel()
        second = asyncio.create_task(runtime.translate(payload))
        await asyncio.sleep(0.02)
        assert not first.done()
        assert not second.done()
        allow_inference_to_finish.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second

    asyncio.run(exercise_cancellation())
    assert max_active_inferences == 1
