"""Lazy, single-instance VoxCPM synthesis with content-addressed caching."""

import hashlib
from pathlib import Path
from threading import Lock

import numpy as np
import soundfile as sf

from .models import VoiceConfig
from .utils import cache_key


class VoiceSynthesizer:
    """Load VoxCPM at most once and reuse generated WAV files."""

    _model = None
    _lock = Lock()

    def __init__(self, voice: VoiceConfig, cache_dir: Path, device: str = "auto") -> None:
        self.voice = voice
        self.cache_dir = cache_dir
        self.device = device

    def synthesize(self, text: str, output_dir: Path, split_paragraphs: bool = False, paragraph_pause: float = 0.3, inference_timesteps: int = 10) -> tuple[Path, bool]:
        output_dir.mkdir(parents=True, exist_ok=True)
        paragraphs = [paragraph.strip() for paragraph in text.split("\n") if paragraph.strip()] if split_paragraphs else [text]
        if len(paragraphs) <= 1:
            return self._synthesize_one(text, output_dir, inference_timesteps)
        results = [self._synthesize_one(paragraph, output_dir, inference_timesteps) for paragraph in paragraphs]
        parts = [path for path, _ in results]
        all_parts_reused = all(reused for _, reused in results)
        destination, concat_reused = self._concatenate(parts, output_dir, paragraph_pause)
        return destination, all_parts_reused and concat_reused

    def _synthesize_one(self, text: str, output_dir: Path, inference_timesteps: int = 10) -> tuple[Path, bool]:
        # a voice description prefix drives non-cloned generation instead of a prompt WAV
        full_text = f"({self.voice.description}){text}" if self.voice.description else text
        key = cache_key(full_text, self.voice.prompt_wav_path, self.voice.reference_wav_path, self.voice.denoise, inference_timesteps)
        destination = output_dir / f"{key}.wav"
        if destination.exists():
            return destination, True
        model = self._get_model()
        kwargs = {
            "text": full_text,
            "prompt_wav_path": str(self.voice.prompt_wav_path) if self.voice.prompt_wav_path else None,
            "prompt_text": self.voice.prompt_text,
            "reference_wav_path": str(self.voice.reference_wav_path) if self.voice.reference_wav_path else None,
            "denoise": self.voice.denoise,
            "inference_timesteps": inference_timesteps,
        }
        wav = model.generate(**{key: value for key, value in kwargs.items() if value is not None})
        sf.write(destination, wav, model.tts_model.sample_rate)
        return destination, False

    def _concatenate(self, parts: list[Path], output_dir: Path, paragraph_pause: float) -> tuple[Path, bool]:
        key = hashlib.sha256("".join(part.stem for part in parts).encode("ascii") + str(paragraph_pause).encode("ascii")).hexdigest()
        destination = output_dir / f"{key}.wav"
        if destination.exists():
            return destination, True
        samplerate = None
        segments: list[np.ndarray] = []
        for index, part in enumerate(parts):
            data, samplerate = sf.read(part)
            if index > 0:
                gap_shape = (int(paragraph_pause * samplerate),) + data.shape[1:]
                segments.append(np.zeros(gap_shape, dtype=data.dtype))
            segments.append(data)
        sf.write(destination, np.concatenate(segments), samplerate)
        return destination, False

    def _get_model(self):
        if self.__class__._model is None:
            with self.__class__._lock:
                if self.__class__._model is None:
                    from voxcpm import VoxCPM

                    selected_device = self.device
                    if selected_device == "auto":
                        import torch

                        selected_device = "cuda" if torch.cuda.is_available() else "cpu"
                    kwargs = {"device": selected_device}
                    self.__class__._model = VoxCPM.from_pretrained(
                        "openbmb/VoxCPM2", load_denoiser=False, **kwargs
                    )
        return self.__class__._model

    @classmethod
    def generate_sample(cls, description: str, text: str, device: str = "auto", inference_timesteps: int = 10) -> tuple[np.ndarray, int]:
        """Generate a one-off WAV sample from a voice description, without caching."""
        instance = cls(VoiceConfig(description=description), Path("."), device)
        model = instance._get_model()
        wav = model.generate(text=f"({description}){text}", inference_timesteps=inference_timesteps)
        return wav, model.tts_model.sample_rate