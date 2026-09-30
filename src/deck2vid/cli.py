"""Command-line interface for deck2vid."""

import shutil
from pathlib import Path

import fitz
import soundfile as sf
import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from .composer import RESOLUTIONS, assemble, render_clip
from .models import SlideScript, load_script
from .pdf import page_count, render_pages
from .tts import VoiceSynthesizer
from .utils import require_file, require_ffmpeg, validate_wav

app = typer.Typer(no_args_is_help=True, help="Create narrated videos from PDF slides.")
console = Console()


def _validate(pdf: Path, script_path: Path, check_ffmpeg: bool = True) -> SlideScript:
    require_file(pdf, "PDF")
    require_file(script_path, "script")
    if check_ffmpeg:
        require_ffmpeg()
    script = load_script(script_path)
    if page_count(pdf) < max(slide.slide for slide in script.slides):
        raise ValueError("the PDF has fewer pages than the script references")
    if script.config.voice.prompt_wav_path:
        validate_wav(script.config.voice.prompt_wav_path, "prompt_wav_path")
    if script.config.voice.reference_wav_path:
        validate_wav(script.config.voice.reference_wav_path, "reference_wav_path")
    return script


def _print_build_summary(pdf: Path, script_path: Path, output: Path, resolution: str, fps: int, device: str, cache_dir: Path, loaded: SlideScript) -> None:
    voice = loaded.config.voice
    defaults = loaded.config.defaults
    voice_mode = f"cloned ({voice.prompt_wav_path.name})" if voice.prompt_wav_path else f"described ({voice.description!r})"
    console.print("[bold]Configuration summary[/bold]")
    console.print(f"  PDF: {pdf}")
    console.print(f"  Script: {script_path}")
    console.print(f"  Output: {output}")
    console.print(f"  Resolution: {resolution} | FPS: {fps} | Device: {device}")
    console.print(f"  Cache: {cache_dir}")
    console.print(f"  Voice: {voice_mode}, denoise={voice.denoise}")
    console.print(
        f"  Defaults: pre_pause={defaults.pre_pause}s, post_pause={defaults.post_pause}s, "
        f"transition={defaults.transition} ({defaults.transition_duration}s), "
        f"split_paragraphs={defaults.split_paragraphs}, paragraph_pause={defaults.paragraph_pause}s, "
        f"inference_timesteps={defaults.inference_timesteps}"
    )
    console.print(f"  Slides: {len(loaded.slides)}")


@app.command()
def validate(pdf: Path = typer.Option(...), script: Path = typer.Option(...)) -> None:
    """Validate a PDF/script pair without loading the TTS model."""
    try:
        loaded = _validate(pdf, script)
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"[green]Valid:[/green] {len(loaded.slides)} scripted slides, {page_count(pdf)} PDF pages")


@app.command("init-script")
def init_script(pdf: Path = typer.Option(...), output: Path = typer.Option(...)) -> None:
    """Create a YAML template with one entry per PDF page."""
    require_file(pdf, "PDF")
    count = page_count(pdf)
    slides = "\n".join(f"  - slide: {index}\n    text: null\n    duration: 4.0" for index in range(1, count + 1))
    output.write_text(f"config:\n  voice:\n    prompt_wav_path: voice/voice.wav\n    prompt_text: \"Write the reference text here.\"\n    reference_wav_path: voice/voice.wav\n    denoise: true\n  defaults:\n    pre_pause: 0.3\n    post_pause: 0.7\n    transition: fade\n    transition_duration: 0.5\n    inference_timesteps: 10\n\nslides:\n{slides}\n", encoding="utf-8")
    console.print(f"Created {output} with {count} slides")


@app.command("generate-voice")
def generate_voice(
    description: str = typer.Option(..., help="Voice description, e.g. 'a young woman, gentle and sweet voice'"),
    text: str = typer.Option(..., help="Text to read aloud in the generated sample"),
    output: Path = typer.Option(..., help="Where to save the resulting WAV"),
    device: str = typer.Option("auto"),
    inference_timesteps: int = typer.Option(10, min=10, max=30),
    overwrite: bool = typer.Option(False),
    verbose: bool = typer.Option(False, help="Show the model's own loading/generation logs instead of hiding them"),
) -> None:
    """Generate a one-off WAV from a voice description, to reuse as a clone reference.

    Building a full video with `--description` alone can produce a different
    voice on every synthesized slide. Generate a sample once with this
    command, then point `build`'s `prompt_wav_path`/`prompt_text` at it so the
    same voice is reused consistently across the whole video.
    """
    if device not in {"auto", "cuda", "cpu"}:
        raise typer.BadParameter("device must be auto, cuda, or cpu")
    if output.exists() and not overwrite:
        raise typer.BadParameter(f"output already exists: {output}; use --overwrite")
    console.print(f"[cyan]Generating voice sample...[/cyan] {description!r}")
    wav, samplerate = VoiceSynthesizer.generate_sample(description, text, device, inference_timesteps, verbose)
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, wav, samplerate)
    console.print(f"[green]Created:[/green] {output}")
    console.print(
        f"Use prompt_wav_path: {output.name} and prompt_text: {text!r} in your script "
        "to clone this voice consistently across the whole video."
    )


@app.command()
def build(pdf: Path = typer.Option(...), script: Path = typer.Option(...), output: Path = typer.Option(...), resolution: str = typer.Option("1080p"), fps: int = typer.Option(30, min=1), cache_dir: Path = typer.Option(Path(".cache/deck2vid")), device: str = typer.Option("auto"), keep_temp: bool = typer.Option(False), overwrite: bool = typer.Option(False), verbose: bool = typer.Option(False, help="Show the model's own loading/generation logs instead of hiding them")) -> None:
    """Synthesize narration, render clips, and assemble the final MP4."""
    if resolution not in RESOLUTIONS:
        raise typer.BadParameter(f"resolution must be one of: {', '.join(RESOLUTIONS)}")
    if device not in {"auto", "cuda", "cpu"}:
        raise typer.BadParameter("device must be auto, cuda, or cpu")
    if output.exists() and not overwrite:
        raise typer.BadParameter(f"output already exists: {output}; use --overwrite")
    loaded = _validate(pdf, script)
    _print_build_summary(pdf, script, output, resolution, fps, device, cache_dir, loaded)
    work_dir = cache_dir / "work"
    audio_dir = cache_dir / "audio"
    images = render_pages(pdf, work_dir / "images")
    synthesizer = VoiceSynthesizer(loaded.config.voice, audio_dir, device, verbose)
    clips: list[Path] = []
    durations: list[float] = []
    for slide in loaded.slides:
        if slide.text is not None:
            console.print(f"[cyan]Slide {slide.slide}:[/cyan] processing audio...")
            audio, reused = synthesizer.synthesize(slide.text, audio_dir, loaded.config.defaults.split_paragraphs, loaded.config.defaults.paragraph_pause, loaded.config.defaults.inference_timesteps)
            status = "reusing already generated audio" if reused else "audio generated"
            console.print(f"  -> {status}: {audio.name}")
        else:
            audio = None
        clip = work_dir / f"clip-{slide.slide:04d}.mp4"
        duration = render_clip(images[slide.slide - 1], audio, slide, loaded, clip, resolution, fps)
        clips.append(clip)
        durations.append(duration)
    output.parent.mkdir(parents=True, exist_ok=True)
    console.print("[bold cyan]All audio has been processed. Building the final video...[/bold cyan]")
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Assembling video", total=100)

        def on_progress(fraction: float) -> None:
            progress.update(task, completed=fraction * 100)

        assemble(clips, loaded, durations, output, fps, overwrite, on_progress)
    if not keep_temp:
        shutil.rmtree(work_dir, ignore_errors=True)
    console.print(f"[green]Created:[/green] {output}")


if __name__ == "__main__":
    app()