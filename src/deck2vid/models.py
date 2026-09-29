"""Pydantic models and YAML loading for slide scripts."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


Transition = Literal["cut", "fade", "wipeleft"]


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_wav_path: Path | None = None
    prompt_text: str | None = Field(default=None, min_length=1)
    reference_wav_path: Path | None = None
    denoise: bool = True
    description: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def require_clone_or_description(self) -> "VoiceConfig":
        if self.prompt_wav_path is not None and self.description is not None:
            raise ValueError("voice.description cannot be combined with prompt_wav_path; choose one voice mode")
        if self.prompt_wav_path is not None and self.prompt_text is None:
            raise ValueError("voice.prompt_text is required when prompt_wav_path is set")
        if self.prompt_wav_path is None and self.description is None:
            raise ValueError("voice must set either prompt_wav_path (cloned voice) or description (non-cloned voice)")
        return self


class DefaultsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pre_pause: float = Field(default=0.3, ge=0)
    post_pause: float = Field(default=0.7, ge=0)
    transition: Transition = "fade"
    transition_duration: float = Field(default=0.5, ge=0)
    split_paragraphs: bool = False
    paragraph_pause: float = Field(default=0.3, ge=0)
    inference_timesteps: int = Field(default=10, ge=10, le=30)


class ScriptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice: VoiceConfig
    defaults: DefaultsConfig = DefaultsConfig()


class Slide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide: int = Field(ge=1)
    text: str | None = None
    duration: float | None = Field(default=None, gt=0)
    pre_pause: float | None = Field(default=None, ge=0)
    post_pause: float | None = Field(default=None, ge=0)
    transition: Transition | None = None
    transition_duration: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_duration_for_silent_slide(self) -> "Slide":
        if self.text is None and self.duration is None:
            raise ValueError("duration is required when text is null")
        if self.text is not None and not self.text.strip():
            raise ValueError("text must not be empty; use null for a silent slide")
        return self


class SlideScript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: ScriptConfig
    slides: list[Slide] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_slide_numbers(self) -> "SlideScript":
        numbers = [slide.slide for slide in self.slides]
        if len(numbers) != len(set(numbers)):
            raise ValueError("slide numbers must be unique")
        return self


def load_script(path: Path) -> SlideScript:
    """Load and validate a YAML script, resolving voice paths relative to it."""
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    script = SlideScript.model_validate(data)
    base = path.parent.resolve()
    if script.config.voice.prompt_wav_path:
        script.config.voice.prompt_wav_path = _resolve(base, script.config.voice.prompt_wav_path)
    if script.config.voice.reference_wav_path:
        script.config.voice.reference_wav_path = _resolve(base, script.config.voice.reference_wav_path)
    return script


def _resolve(base: Path, value: Path) -> Path:
    return value if value.is_absolute() else (base / value).resolve()