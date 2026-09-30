"""Small filesystem, dependency, and cache helpers."""

import contextlib
import hashlib
import logging
import os
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


_NOISY_LOGGERS = ("transformers", "huggingface_hub", "urllib3", "torch")


@contextlib.contextmanager
def suppress_model_output():
    """Hide the model/library noise (loading logs, progress bars, warnings) printed by VoxCPM and its dependencies.

    Only redirects Python-level stdout/stderr (not OS file descriptors): dup2-ing
    the real file descriptors was found to crash native CUDA/torch code on
    Windows after the first generation, so this trades off catching some
    native prints for not killing the process.
    """
    env_overrides = {
        "HF_HUB_DISABLE_PROGRESS_BARS": "1",
        "TRANSFORMERS_VERBOSITY": "error",
        "TOKENIZERS_PARALLELISM": "false",
    }
    previous_env = {key: os.environ.get(key) for key in env_overrides}
    previous_levels = {name: logging.getLogger(name).level for name in _NOISY_LOGGERS}
    os.environ.update(env_overrides)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.ERROR)
    try:
        with open(os.devnull, "w", encoding="utf-8") as devnull:
            with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                yield
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for name, level in previous_levels.items():
            logging.getLogger(name).setLevel(level)


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