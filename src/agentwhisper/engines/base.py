"""The Engine contract every speech-to-text backend implements.

Future engines (cloud STT, an LLM 'agent mode' engine) drop in behind
this interface without the daemon changing.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np


class EngineError(Exception):
    """Transcription cannot work; the message says why."""


class Engine(Protocol):
    @property
    def status(self) -> str:
        """One of: 'not loaded', 'loading', 'ready', or 'error: ...'."""
        ...

    def load(self) -> None:
        """Blocking: acquire the model. Called once, from a background
        thread, at daemon startup. Errors are reflected in status."""
        ...

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        """Mono int16 samples → text. Blocks; waits for load() if needed.
        Returns '' when no speech is detected. Raises EngineError."""
        ...
