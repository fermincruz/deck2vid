"""FFmpeg-based slide clip rendering and assembly."""

import re
import subprocess
from pathlib import Path
from typing import Callable

from .models import Slide, SlideScript
from .utils import require_ffmpeg


RESOLUTIONS = {"720p": (1280, 720), "1080p": (1920, 1080), "4k": (3840, 2160)}

_OUT_TIME_RE = re.compile(r"out_time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def run_ffmpeg(arguments: list[str], on_progress: Callable[[float], None] | None = None, total_duration: float | None = None) -> None:
    base = [require_ffmpeg(), "-hide_banner", "-loglevel", "error"]
    if on_progress is None or not total_duration:
        try:
            subprocess.run([*base, *arguments], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"ffmpeg failed: {exc.stderr.strip()}") from exc
        return
    process = subprocess.Popen([*base, "-progress", "pipe:1", "-nostats", *arguments], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert process.stdout is not None
    for line in process.stdout:
        match = _OUT_TIME_RE.search(line)
        if match:
            hours, minutes, seconds = match.groups()
            elapsed = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            on_progress(min(1.0, elapsed / total_duration))
    stderr = process.stderr.read() if process.stderr else ""
    if process.wait() != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr.strip()}")
    on_progress(1.0)


def render_clip(image: Path, audio: Path | None, slide: Slide, script: SlideScript, destination: Path, resolution: str, fps: int) -> float:
    width, height = RESOLUTIONS[resolution]
    pre = slide.pre_pause if slide.pre_pause is not None else script.config.defaults.pre_pause
    post = slide.post_pause if slide.post_pause is not None else script.config.defaults.post_pause
    duration = slide.duration if slide.text is None else None
    if duration is None:
        duration = _audio_duration(audio) + pre + post
    audio_input = ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo"] if audio is None else ["-i", str(audio)]
    audio_filter = f"adelay={round(pre * 1000)}:all=1,apad,atrim=duration={duration}"
    arguments = ["-y", "-loop", "1", "-i", str(image), *audio_input, "-t", str(duration), "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2", "-r", str(fps), "-af", audio_filter, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(destination)]
    run_ffmpeg(arguments)
    return duration


def assemble(clips: list[Path], script: SlideScript, durations: list[float], destination: Path, fps: int, overwrite: bool, on_progress: Callable[[float], None] | None = None) -> None:
    if all((slide.transition or script.config.defaults.transition) == "cut" for slide in script.slides[:-1]):
        concat_file = destination.parent / "concat.txt"
        concat_file.write_text("".join(f"file '{clip.as_posix()}'\n" for clip in clips), encoding="utf-8")
        total_duration = sum(durations)
        run_ffmpeg(["-y" if overwrite else "-n", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(destination)], on_progress, total_duration)
        return
    inputs = [item for clip in clips for item in ("-i", str(clip))]
    video = "[0:v]"
    audio = "[0:a]"
    filters: list[str] = []
    elapsed = durations[0]
    for index in range(1, len(clips)):
        transition = script.slides[index - 1].transition or script.config.defaults.transition
        duration = script.slides[index - 1].transition_duration
        if duration is None:
            duration = script.config.defaults.transition_duration
        vname = f"v{index}"
        aname = f"a{index}"
        filters.append(f"{video}[{index}:v]xfade=transition={transition}:duration={duration}:offset={max(0, elapsed - duration)}[{vname}]")
        # audio must shrink by the same overlap as the video xfade, or it drifts out of sync slide after slide
        if duration > 0:
            filters.append(f"{audio}[{index}:a]acrossfade=d={duration}[{aname}]")
        else:
            filters.append(f"{audio}[{index}:a]concat=n=2:v=0:a=1[{aname}]")
        video = f"[{vname}]"
        audio = f"[{aname}]"
        elapsed += durations[index] - duration
    run_ffmpeg(["-y" if overwrite else "-n", *inputs, "-filter_complex", ";".join(filters), "-map", video, "-map", audio, "-r", str(fps), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(destination)], on_progress, elapsed)


def _audio_duration(path: Path | None) -> float:
    import soundfile as sf

    if path is None:
        return 0.0
    info = sf.info(path)
    return info.frames / info.samplerate