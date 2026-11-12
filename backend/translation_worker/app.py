"""Optional local IndicTrans2 worker. It only loads pre-downloaded model files."""

from __future__ import annotations

import asyncio
import gc
import hmac
import logging
import os
import re
from collections.abc import Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

LANGUAGES = {
    "en": "eng_Latn",
    "hi": "hin_Deva",
    "te": "tel_Telu",
    "ta": "tam_Taml",
    "kn": "kan_Knda",
    "ml": "mal_Mlym",
}

MODEL_SPECS = {
    "en-indic": {
        "name": "ai4bharat/indictrans2-en-indic-dist-200M",
        "environment_variable": "INDICTRANS_EN_INDIC_MODEL_PATH",
        "revision": "2cfd0a20057756d756bf3e53528f492afc52f91a",
    },
    "indic-en": {
        "name": "ai4bharat/indictrans2-indic-en-dist-200M",
        "environment_variable": "INDICTRANS_INDIC_EN_MODEL_PATH",
        "revision": "d66a2122ad6d28184f3dc3797b652bd80ae3f65f",
    },
}

MODEL_LICENSE = "MIT (declared by the model repository; verify before deployment)"
MAX_TEXT_LENGTH = 4_000
REQUIRED_MODEL_FILES = (
    "config.json",
    "model.safetensors",
    "model.SRC",
    "model.TGT",
    "configuration_indictrans.py",
    "modeling_indictrans.py",
    "tokenization_indictrans.py",
)

logger = logging.getLogger(__name__)


class GlossaryItem(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    translation: str = Field(min_length=1, max_length=200)


class TranslationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    source_language: str = Field(min_length=2, max_length=16)
    target_language: str = Field(min_length=2, max_length=16)
    glossary: list[GlossaryItem] = Field(default_factory=list, max_length=100)


class TranslationResponse(BaseModel):
    translated_text: str
    provider: str
    model: str
    model_version: str
    model_license: str


class IndicTransRuntime:
    """Load at most one direction-specific model into memory at a time."""

    def __init__(self) -> None:
        self._active_direction: str | None = None
        self._model: Any = None
        self._tokenizer: Any = None
        self._processor: Any = None
        self._torch: Any = None
        self._device: Any = None
        self._lock = asyncio.Lock()

    def configured_directions(self) -> list[str]:
        configured = []
        for direction, spec in MODEL_SPECS.items():
            path = os.environ.get(spec["environment_variable"])
            model_path = Path(path).expanduser().resolve() if path else None
            if (
                model_path
                and model_path.name == spec["revision"]
                and model_path.is_dir()
                and all((model_path / filename).is_file() for filename in REQUIRED_MODEL_FILES)
            ):
                configured.append(direction)
        return configured

    async def translate(self, payload: TranslationRequest) -> TranslationResponse:
        source = LANGUAGES.get(payload.source_language)
        target = LANGUAGES.get(payload.target_language)
        if source is None or target is None or source == target:
            raise ValueError("The requested source/target language pair is not supported.")
        if source == "eng_Latn":
            direction = "en-indic"
        elif target == "eng_Latn":
            direction = "indic-en"
        else:
            raise ValueError("Indic-to-Indic translation is not available in this worker.")
        async with self._lock:
            operation = asyncio.create_task(
                asyncio.to_thread(self._translate_sync, payload, direction, source, target)
            )
            try:
                return await asyncio.shield(operation)
            except asyncio.CancelledError:
                try:
                    await asyncio.shield(operation)
                except Exception:
                    logger.exception("Translation inference failed while cancellation was pending.")
                raise

    def _translate_sync(
        self,
        payload: TranslationRequest,
        direction: str,
        source: str,
        target: str,
    ) -> TranslationResponse:
        self._load_direction(direction)
        translated = self._translate_with_glossary(
            payload.text,
            source,
            target,
            payload.glossary,
        )
        return TranslationResponse(
            translated_text=translated,
            provider="indictrans2-worker",
            model=MODEL_SPECS[direction]["name"],
            model_version=MODEL_SPECS[direction]["revision"],
            model_license=MODEL_LICENSE,
        )

    def _load_direction(self, direction: str) -> None:
        if self._active_direction == direction:
            return
        model_path_value = os.environ.get(MODEL_SPECS[direction]["environment_variable"])
        if not model_path_value:
            raise RuntimeError(f"Local model path is not configured for {direction}.")
        model_path = Path(model_path_value).expanduser().resolve(strict=True)
        if model_path.name != MODEL_SPECS[direction]["revision"]:
            raise RuntimeError(
                f"The local IndicTrans2 {direction} model must use the pinned "
                "repository revision directory."
            )
        if not model_path.is_dir() or any(
            not (model_path / name).is_file() for name in REQUIRED_MODEL_FILES
        ):
            raise RuntimeError(f"The local IndicTrans2 {direction} model directory is incomplete.")

        if self._model is not None:
            del self._model, self._tokenizer, self._processor
            self._model = self._tokenizer = self._processor = None
            self._active_direction = None
            gc.collect()
            if self._torch is not None and self._torch.backends.mps.is_available():
                self._torch.mps.empty_cache()

        import torch
        from IndicTransToolkit.processor import IndicProcessor
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(model_path),
            local_files_only=True,
            trust_remote_code=True,
        )
        self._model = AutoModelForSeq2SeqLM.from_pretrained(
            str(model_path),
            local_files_only=True,
            trust_remote_code=True,
            torch_dtype=torch.float32,
        ).to(device)
        self._model.eval()
        self._processor = IndicProcessor(inference=True)
        self._torch = torch
        self._device = device
        self._active_direction = direction

    def _translate_with_glossary(
        self,
        text: str,
        source: str,
        target: str,
        glossary: Sequence[GlossaryItem],
    ) -> str:
        replacements: dict[str, str] = {}
        protected = text
        candidates = sorted(glossary, key=lambda item: len(item.source), reverse=True)
        for index, term in enumerate(candidates):
            marker = f"ACSXGLOSSARY{index:04}TERM"
            pattern = re.compile(re.escape(term.source), re.IGNORECASE)
            protected, count = pattern.subn(marker, protected)
            if count:
                replacements[marker] = term.translation

        translated = self._translate_plain(protected, source, target)
        if replacements and any(marker not in translated for marker in replacements):
            return self._translate_preserving_glossary(text, source, target, candidates)
        for marker, preferred_translation in replacements.items():
            translated = translated.replace(marker, preferred_translation)
        return translated.strip()

    def _translate_preserving_glossary(
        self,
        text: str,
        source: str,
        target: str,
        glossary: Sequence[GlossaryItem],
    ) -> str:
        terms = sorted(glossary, key=lambda item: len(item.source), reverse=True)
        if not terms:
            return self._translate_plain(text, source, target)
        pattern = re.compile("|".join(re.escape(term.source) for term in terms), re.IGNORECASE)
        by_casefold = {term.source.casefold(): term for term in terms}
        output: list[str] = []
        last_end = 0
        for match in pattern.finditer(text):
            if match.start() > last_end:
                output.append(self._translate_plain(text[last_end : match.start()], source, target))
            term = by_casefold[match.group().casefold()]
            output.append(term.translation)
            last_end = match.end()
        if last_end < len(text):
            output.append(self._translate_plain(text[last_end:], source, target))
        return "".join(output).strip()

    def _translate_plain(self, text: str, source: str, target: str) -> str:
        if not text:
            return ""
        prepared = self._processor.preprocess_batch([text], src_lang=source, tgt_lang=target)
        inputs = self._tokenizer(
            prepared,
            truncation=True,
            padding="longest",
            max_length=256,
            return_tensors="pt",
            return_attention_mask=True,
        ).to(self._device)
        with self._torch.inference_mode():
            generated = self._model.generate(
                **inputs,
                use_cache=True,
                min_length=0,
                max_length=256,
                num_beams=4,
                num_return_sequences=1,
            )
        decoded = self._tokenizer.batch_decode(
            generated,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=True,
        )
        return self._processor.postprocess_batch(decoded, lang=target)[0]


runtime = IndicTransRuntime()
worker_token = os.environ.get("TRANSLATION_WORKER_API_TOKEN", "")


def verify_worker_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if not worker_token or not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid worker token."
        )
    if not hmac.compare_digest(authorization[7:], worker_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid worker token."
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="AI Creator Studio Local Translation Worker", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, object]:
    directions = runtime.configured_directions()
    return {
        "status": "ready" if directions else "model_not_configured",
        "provider": "indictrans2-worker",
        "configured_directions": directions,
        "model_downloads_enabled": False,
    }


@app.post("/translate", response_model=TranslationResponse)
async def translate(
    payload: TranslationRequest,
    _: Annotated[None, Depends(verify_worker_token)],
) -> TranslationResponse:
    try:
        return await runtime.translate(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
