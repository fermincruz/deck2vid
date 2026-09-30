# deck2vid

CLI to generate narrated videos from a PDF of slides and a YAML script.
Converts each page of the PDF into a video slide, synthesizes the narration
with [VoxCPM 2](https://github.com/OpenBMB/VoxCPM), and assembles the result
with FFmpeg (transitions, pauses, audio included).

VoxCPM lets you clone your own voice from just a few seconds of reference
audio, without any training or fine-tuning. Once a voice is cloned, it can
narrate text in other languages too, so a single reference sample is enough
to voice a whole video regardless of the language of the script.

For voice cloning, it is recommended recording approximately 30 seconds of
narrated audio. The tone and prosody you use in this recording will be
imitated when generating your video narration, so record it in the style you
want the videos to have.

A complete working example is in the [example](example) folder, including the resulting output video. 

## Requirements

- Python `>=3.10,<3.13`
- [FFmpeg](https://ffmpeg.org/download.html) installed and available on the
  `PATH`. Quick install:
  - Windows (winget): `winget install --id Gyan.FFmpeg`
  - macOS (Homebrew): `brew install ffmpeg`
  - Linux (apt, Debian/Ubuntu): `sudo apt install ffmpeg`
- Optional: NVIDIA GPU with CUDA drivers (speeds up voice synthesis a lot;
  it also works without a GPU, just slower)
- ~5 GB of free disk space for the VoxCPM model, downloaded automatically on
  first run and cached locally (usually under `~/.cache/huggingface`)

## Installation

Create a virtual environment and install the dependencies. There are two
variants depending on whether the machine has an NVIDIA GPU or not:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**No GPU (CPU only):**

```powershell
python -m pip install -r requirements-cpu.txt
python -m pip install -e .
```

**With NVIDIA GPU (CUDA):**

`requirements-gpu.txt` installs PyTorch for CUDA `cu130`. If your GPU/drivers
need a different CUDA version, edit the first line of the file
(`--extra-index-url https://download.pytorch.org/whl/cuXXX`) to point at the
matching index before installing; you can check which CUDA version your
drivers support with `nvidia-smi` and look up available builds on the
[PyTorch installation page](https://pytorch.org/get-started/locally/).

```powershell
python -m pip install -r requirements-gpu.txt
python -m pip install -e .
```

Check that everything installed correctly:

```powershell
deck2vid --help
```

## Usage

The example bundle in [example/](example/) contains a PDF and a script ready
to try:

```powershell
deck2vid build --pdf example/slides.pdf --script example/script.yaml `
  --output example/output.mp4 --device auto --resolution 1080p --overwrite
```

### Available commands

**`validate`** — checks that a PDF and a script are consistent with each
other, without loading the voice model (fast, useful for reviewing the YAML):

```powershell
deck2vid validate --pdf example/slides.pdf --script example/script.yaml
```

**`init-script`** — generates a script template with one silent entry per PDF
page, to fill in by hand:

```powershell
deck2vid init-script --pdf example/slides.pdf --output script.yaml
```

**`generate-voice`** — generates a sample WAV from a voice description
(without needing a reference audio beforehand). Useful for creating a voice
"from scratch" and then reusing it consistently (see
[consistent voice](#consistent-voice-description--cloning) below):

```powershell
deck2vid generate-voice `
  --description "a young woman, gentle and sweet voice" `
  --text "Welcome to this presentation." `
  --output voice.wav --device auto
```

| Option | Description |
| --- | --- |
| `--description` | Voice description, e.g. `"a young woman, gentle and sweet voice"`. |
| `--text` | Text to read aloud in the generated sample. |
| `--output` | Where to save the resulting WAV. |
| `--device` | `auto`, `cuda`, or `cpu` for voice synthesis. |
| `--inference-timesteps` | Inference steps of the VoxCPM model, `10`–`30` (default `10`). |
| `--overwrite` | Overwrites the output WAV if it already exists. |
| `--verbose` | Shows VoxCPM's own model loading logs (hidden by default; the inference progress bar is always shown). |

**`build`** — synthesizes the narration for each slide, renders the video
clips, and assembles the final MP4:

```powershell
deck2vid build --pdf example/slides.pdf --script example/script.yaml `
  --output output.mp4 --resolution 1080p --fps 30 --device auto `
  --cache-dir .cache/deck2vid --overwrite --keep-temp
```

| Option | Description |
| --- | --- |
| `--pdf` | Path to the slide PDF. |
| `--script` | Path to the YAML script. |
| `--output` | Path to the output MP4. |
| `--resolution` | `720p`, `1080p`, or `4k`. |
| `--fps` | Frames per second of the video (default `30`). |
| `--device` | `auto`, `cuda`, or `cpu` for voice synthesis. |
| `--cache-dir` | Folder where intermediate images, clips, and audio are stored. |
| `--overwrite` | Overwrites the output MP4 if it already exists. |
| `--keep-temp` | Keeps the intermediate PNG images and MP4 clips. |
| `--verbose` | Shows VoxCPM's own model loading logs (hidden by default; the inference progress bar is always shown). |

Audio paths in the script (`prompt_wav_path`, `reference_wav_path`) are
resolved relative to the folder containing the YAML. Synthesized WAV files
are cached in `<cache-dir>/audio` using a content-based key, so rebuilding
the same unchanged script does not repeat the synthesis.

## Consistent voice: description + cloning

If you use `voice.description` directly in the script, each slide is
synthesized independently, and VoxCPM can generate a slightly different
voice each time, resulting in a video with an inconsistent narration.

The recommended workflow to keep the same voice throughout the video is:

1. Generate a voice sample once with `generate-voice`, from a description.
2. Use that WAV as `prompt_wav_path` (with `prompt_text` equal to the text
   used to generate it) in the script, in cloning mode.
3. Build the video with `build`: every slide will clone that same reference
   voice.

## YAML script guide

A script has two top-level keys: `config` and `slides`. Any unrecognized key
fails validation (the models use `extra="forbid"`).

### `config.voice`

Defines the voice used for all slides with text. You must choose a single
mode: cloned voice (`prompt_wav_path`) or described voice (`description`).

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `prompt_wav_path` | path | Cloning mode | Reference WAV to clone the voice from. Incompatible with `description`. |
| `prompt_text` | string | Yes, if `prompt_wav_path` is set | Exact transcript of the audio in `prompt_wav_path`. |
| `reference_wav_path` | path | No | Additional reference WAV (e.g. for denoising); optional. |
| `denoise` | bool | No (`true`) | Applies noise reduction to the reference audio. |
| `description` | string | Description mode | Voice description (e.g. `"a warm-toned female voice"`) used instead of cloning a WAV. Incompatible with `prompt_wav_path`. |

Paths (`prompt_wav_path`, `reference_wav_path`) are relative to the folder
containing the YAML.

### `config.defaults`

Default values applied to all slides; some can be overridden per slide (see
below).

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `pre_pause` | float ≥ 0 | `0.3` | Seconds of silence before narrating the slide. |
| `post_pause` | float ≥ 0 | `0.7` | Seconds of silence after the narration ends. |
| `transition` | `cut` \| `fade` \| `wipeleft` | `fade` | Transition to the next slide. |
| `transition_duration` | float ≥ 0 | `0.5` | Duration in seconds of the transition. |
| `split_paragraphs` | bool | `false` | If `true`, each paragraph (separated by blank lines) is synthesized separately and concatenated with a pause between them. |
| `paragraph_pause` | float ≥ 0 | `0.3` | Seconds of silence inserted between paragraphs when `split_paragraphs` is enabled. |
| `inference_timesteps` | int, 10–30 | `10` | Inference steps of the VoxCPM model. Higher values (up to 30) can improve audio quality at the cost of more generation time; 10 is the recommended default. |

### `slides`

List of slides, each with its page number. Numbers must be unique, and the
PDF must have at least as many pages as the highest `slide` referenced.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `slide` | int ≥ 1 | Yes | PDF page number (1-indexed). |
| `text` | string \| `null` | Yes | Text to narrate. Use `null` for a silent slide (no audio). |
| `duration` | float > 0 | Only if `text` is `null` | Fixed duration in seconds for silent slides. |
| `pre_pause` | float ≥ 0 | No | Overrides `config.defaults.pre_pause` for this slide. |
| `post_pause` | float ≥ 0 | No | Overrides `config.defaults.post_pause` for this slide. |
| `transition` | `cut` \| `fade` \| `wipeleft` | No | Overrides `config.defaults.transition` for the transition to the next slide. |
| `transition_duration` | float ≥ 0 | No | Overrides `config.defaults.transition_duration` for this slide. |

If `text` is not `null`, it cannot be empty or contain only whitespace.
`inference_timesteps`, `split_paragraphs`, and `paragraph_pause` are only
configured at the `config.defaults` level and apply to all slides.

A complete, working example is in [example/script.yaml](example/script.yaml).

