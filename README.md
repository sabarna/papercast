# PaperCast

**Turn an arXiv paper into a narrated slideshow video.**

Give PaperCast an arXiv ID and get back an `.mp4`: AI-written narration, slides
that surface the paper's figures, and typeset equations. Everything runs on your
own machine — you bring your own API keys.

Use it two ways:

- **Command line** — `papercast 2301.07041` and a video pops out.
- **Web UI** — `papercast-web`, paste an ID in the browser, watch progress live.

---

## How it works

1. **Ingest** — downloads the paper's LaTeX source tarball from arXiv.
2. **Parse** — walks the LaTeX, pulling out sections, figures, and equations.
3. **Narrative** — Claude writes a ~7-minute script mapped to visuals beat-by-beat.
4. **Slides** — each beat is rendered from an HTML template via headless Chromium.
5. **Voiceover** — OpenAI TTS narrates each beat; slide time = narration length.
6. **Assemble** — `ffmpeg` stitches the slides and audio into one `.mp4`.

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full design.

---

## Requirements

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) on your PATH
- An **Anthropic API key** (narration) and an **OpenAI API key** (text-to-speech)

---

## Install

```bash
git clone https://github.com/sabarna/papercast.git
cd papercast

# 1. Install the package (creates the `papercast` and `papercast-web` commands)
pip install -e .

# 2. Install the headless browser used to render slides
playwright install chromium

# 3. Install ffmpeg (system package)
#    macOS:   brew install ffmpeg
#    Ubuntu:  sudo apt install ffmpeg

# 4. Add your API keys
cp .env.example .env
#    then edit .env and set ANTHROPIC_API_KEY and OPENAI_API_KEY
```

> Keys are read from a local `.env` file (or ordinary environment variables).
> `.env` is git-ignored — your keys never get committed.

---

## Command-line usage

```bash
# simplest — writes ./2301.07041.mp4
papercast 2301.07041

# a URL works too, and you can choose the output path
papercast https://arxiv.org/abs/2301.07041 -o talk.mp4

# tune length, voice, and model
papercast 2301.07041 --duration 300 --voice nova --model claude-sonnet-4-6

# keep the intermediate slides / audio for inspection
papercast 2301.07041 --keep-workspace -v
```

Run `papercast --help` for the full list of options.

---

## Web UI

```bash
papercast-web
# open http://127.0.0.1:8000
```

Paste an arXiv ID, and the page streams live status while the video builds, then
plays it inline with a download link.

Exposing the UI beyond localhost? Set `APP_USERNAME` and `APP_PASSWORD` in `.env`
to require a login so nobody else can spend your API credits.

---

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

---

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

[MIT](./LICENSE) © 2026 Sabarna Choudhuri
