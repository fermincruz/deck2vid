"""Small filesystem, dependency, and cache helpers."""

import hashlib
import shutil
import wave
from pathlib import Path


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")


def require_ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("ffmpeg was not found on PATH")
    return executable


def validate_wav(path: Path, label: str) -> None:
    require_file(path, label)
    try:
        with wave.open(str(path), "rb") as audio:
            if audio.getnframes() == 0:
                raise ValueError("audio contains no frames")
    except (wave.Error, OSError) as exc:
        raise ValueError(f"{label} is not a readable WAV file: {path}") from exc


def cache_key(text: str, prompt: Path | None, reference: Path | None, denoise: bool, inference_timesteps: int) -> str:
    digest = hashlib.sha256()
    digest.update(text.encode("utf-8"))
    if prompt is not None:
        digest.update(_file_digest(prompt))
    if reference:
        digest.update(_file_digest(reference))
    digest.update(str(denoise).encode("ascii"))
    digest.update(str(inference_timesteps).encode("ascii"))
    return digest.hexdigest()


def _file_digest(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()