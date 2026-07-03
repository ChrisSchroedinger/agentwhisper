"""Configuration: TOML file at ~/.config/agentwhisper/config.toml.

Loading is strict: unknown keys and invalid values are collected and
reported together, so a typo'd config never half-applies silently.
"""

from __future__ import annotations

import dataclasses
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "agentwhisper" / "config.toml"

# v1 is English-only, so only the English-optimized models are offered.
# Multilingual support is a designed-for future step (see DESIGN.md).
MODELS = ["tiny.en", "base.en", "small.en", "medium.en"]
MODES = ["hold", "toggle"]

class ConfigError(Exception):
    """Raised with a message listing every problem found in the config."""


@dataclass
class Config:
    model: str = "base.en"
    device: str = "cpu"
    compute_type: str = "int8"
    hotkey: str = "f12"
    mode: str = "hold"
    auto_type: bool = True
    notifications: bool = True
    max_record_seconds: int = 60

    def validate(self) -> list[str]:
        problems = []
        if self.model not in MODELS:
            problems.append(f"whisper.model {self.model!r} is not one of {', '.join(MODELS)}")
        if self.device not in ("cpu", "cuda"):
            problems.append(f"whisper.device {self.device!r} is not 'cpu' or 'cuda'")
        if self.mode not in MODES:
            problems.append(f"hotkey.mode {self.mode!r} is not one of {', '.join(MODES)}")
        if not isinstance(self.max_record_seconds, int) or self.max_record_seconds < 1:
            problems.append("limits.max_record_seconds must be a positive integer")
        return problems


# Maps [section][key] in the TOML file to Config field names.
_SCHEMA: dict[str, dict[str, str]] = {
    "whisper": {"model": "model", "device": "device", "compute_type": "compute_type"},
    "hotkey": {"key": "hotkey", "mode": "mode"},
    "output": {"auto_type": "auto_type", "notifications": "notifications"},
    "limits": {"max_record_seconds": "max_record_seconds"},
}


def load(path: Path = CONFIG_PATH) -> Config:
    """Load and validate the config; raise ConfigError listing all problems.

    A missing file is fine (all defaults); a broken one is not.
    """
    if not path.exists():
        return Config()

    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: not valid TOML: {e}") from e

    problems: list[str] = []
    values: dict[str, object] = {}
    field_types = {f.name: f.type for f in dataclasses.fields(Config)}

    for section, entries in data.items():
        if section not in _SCHEMA:
            problems.append(f"unknown section [{section}]")
            continue
        if not isinstance(entries, dict):
            problems.append(f"[{section}] must be a section, not a value")
            continue
        for key, value in entries.items():
            field = _SCHEMA[section].get(key)
            if field is None:
                problems.append(f"unknown key {key!r} in [{section}]")
                continue
            expected = field_types[field]
            if expected == "bool" and not isinstance(value, bool):
                problems.append(f"{section}.{key} must be true or false")
                continue
            if expected == "int" and (isinstance(value, bool) or not isinstance(value, int)):
                problems.append(f"{section}.{key} must be an integer")
                continue
            if expected == "str" and not isinstance(value, str):
                problems.append(f"{section}.{key} must be a string")
                continue
            values[field] = value

    config = Config(**values)  # type: ignore[arg-type]
    problems.extend(config.validate())
    if problems:
        raise ConfigError(f"{path}:\n  - " + "\n  - ".join(problems))
    return config


def _render(config: Config) -> str:
    """The config file text: every setting fully explained, with the
    given config's values filled in. Used for both the initial default
    file and every save, so the explanations never get lost."""
    return f"""\
# AgentWhisper configuration.
# The app rewrites this file when you change settings from the tray
# menu — your values are always kept. After editing it by hand,
# restart AgentWhisper (agentwhisper quit, then start it again).

[whisper]
# The speech recognition model. Bigger = more accurate but slower.
# Downloaded automatically on first use (into ~/.cache/huggingface,
# shared with other Whisper tools). Possible values:
#   tiny.en     ~75 MB   fastest, okay for short phrases
#   base.en    ~140 MB   fast, good accuracy (default)
#   small.en   ~460 MB   noticeably slower, very good accuracy
#   medium.en  ~1.5 GB   slow without a GPU, best accuracy
model = "{config.model}"

# Where transcription runs:
#   cpu   works everywhere (default)
#   cuda  NVIDIA GPU; requires cuDNN 9 for CUDA 12
device = "{config.device}"

# Number precision for the model:
#   int8     the right choice for cpu (default)
#   float16  the right choice for cuda
compute_type = "{config.compute_type}"

[hotkey]
# The push-to-talk key: f1 .. f12, scroll_lock, pause, insert, menu.
# AgentWhisper reserves this key exclusively while it runs — other
# programs won't see it. Ctrl/Alt combinations keep working elsewhere.
key = "{config.hotkey}"

# How recording is triggered:
#   hold    push-to-talk: hold the key, speak, release (default)
#   toggle  press once to start recording, press again to stop
mode = "{config.mode}"

[output]
# true   type the transcript into the focused window automatically
# false  only copy it to the clipboard (paste it with Ctrl+V)
auto_type = {str(config.auto_type).lower()}

# true   show a desktop notification after each dictation
#        ("Typed & copied" with a preview, "No speech detected", errors)
# false  stay silent (the tray icon still shows what's happening)
notifications = {str(config.notifications).lower()}

[limits]
# Hard cap on a single recording, in seconds (1 or higher), so a stuck
# key cannot record forever. Recordings under ~0.3s are ignored as
# accidental taps.
max_record_seconds = {config.max_record_seconds}
"""


DEFAULT_CONFIG_TOML = _render(Config())


def write_default(path: Path = CONFIG_PATH) -> None:
    """Write the commented default config if none exists."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG_TOML)


def save(config: Config, path: Path = CONFIG_PATH) -> None:
    """Persist the config (used when settings change via the tray menu).

    Rewrites the file from the standard commented template with the
    current values — explanations survive every save; hand-written
    custom comments do not.
    """
    problems = config.validate()
    if problems:
        raise ConfigError("refusing to save invalid config:\n  - " + "\n  - ".join(problems))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(config))
