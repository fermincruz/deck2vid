from pathlib import Path

from deck2vid.models import load_script


def test_load_script_resolves_voice_paths(tmp_path: Path) -> None:
    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        """config:\n  voice:\n    prompt_wav_path: voice.wav\n    prompt_text: Reference\nslides:\n  - slide: 1\n    text: Hello\n""",
        encoding="utf-8",
    )

    script = load_script(script_path)

    assert script.slides[0].text == "Hello"
    assert script.config.voice.prompt_wav_path == tmp_path / "voice.wav"