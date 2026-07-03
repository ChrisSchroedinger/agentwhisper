"""Local speech-to-text via faster-whisper. Private, offline, free.

The first load downloads the model from Hugging Face
(~40MB tiny.en … ~1.5GB medium.en) into ~/.cache/huggingface; after
that everything is offline.
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

from agentwhisper.engines.base import EngineError

log = logging.getLogger("agentwhisper.engine")

# How long transcribe() waits for the model to finish loading before
# giving up (first-ever run may be downloading on slow connections).
LOAD_WAIT_SECONDS = 600


class WhisperLocalEngine:
    def __init__(self, model: str, device: str = "cpu", compute_type: str = "int8"):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._status = "not loaded"
        self._loaded = threading.Event()

    @property
    def status(self) -> str:
        return self._status

    def load(self) -> None:
        from faster_whisper import WhisperModel

        self._status = "loading"
        log.info("loading whisper model %r (first run downloads it)", self.model_name)
        started = time.time()
        try:
            self._model = WhisperModel(
                self.model_name, device=self.device, compute_type=self.compute_type
            )
        except Exception as e:
            self._status = f"error: {e}"
            log.error("model load failed: %s", e)
        else:
            self._status = "ready"
            log.info("model %r ready in %.1fs", self.model_name, time.time() - started)
        finally:
            self._loaded.set()

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        if not self._loaded.wait(timeout=LOAD_WAIT_SECONDS):
            raise EngineError("the model is still loading — try again shortly")
        if self._model is None:
            raise EngineError(f"the model failed to load ({self._status})")
        if sample_rate != 16_000:
            raise EngineError(f"expected 16kHz audio, got {sample_rate}Hz")

        audio = samples.astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(
            audio, language="en", beam_size=5, vad_filter=True
        )
        return " ".join(s.text.strip() for s in segments).strip()
