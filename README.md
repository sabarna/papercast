# PaperCast

**Turn an arXiv paper — or any PDF — into a narrated slideshow video.**

Give PaperCast an arXiv ID or a PDF and get back an `.mp4`: AI-written narration,
slides that surface the paper's figures, and typeset equations. Everything runs
on your own machine — you bring your own API key.

Use it two ways:

- **Command line** — `python3 -m app.cli 1706.03762` (or `... paper.pdf`) and a video pops out.
- **Web UI** — `python3 -m app.web`, then open the browser and watch progress live.

---

## How it works

1. **Ingest** — downloads the paper's LaTeX source tarball from arXiv.
2. **Parse** — walks the LaTeX, pulling out sections, figures, and equations.
3. **Narrative** — an OpenAI model writes a ~7-minute script mapped to visuals beat-by-beat.
4. **Slides** — each beat is rendered from an HTML template via headless Chromium.
5. **Voiceover** — OpenAI TTS narrates each beat; slide time = narration length.
6. **Assemble** — `ffmpeg` stitches the slides and audio into one `.mp4`.

> For **PDF inputs**, steps 1–2 are replaced by a PDF parser (pdfplumber +
> pypdfium2) that extracts text and figures from the pages and captures
> equations as cropped images.

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full design.

---

## Inputs

PaperCast takes three kinds of input and picks the best path automatically:

- **arXiv ID or URL** — e.g. `1706.03762`. Downloads the paper's **LaTeX source**: real captions, typeset equations, exact section structure. Best quality.
- **Local PDF** — e.g. `~/Downloads/paper.pdf`. Parsed directly.
- **PDF URL** — e.g. `https://example.com/paper.pdf`. Downloaded, then parsed.

PDFs have no LaTeX, so text and figures are extracted from the pages and
equations are captured as cropped images. The web UI accepts arXiv IDs and PDF
URLs; local file paths are command-line only.

---

## Requirements

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) on your PATH
- An **OpenAI API key** — powers both the narration script and the text-to-speech ([how to get one](#getting-an-openai-api-key))

---

## Getting an OpenAI API key

PaperCast uses the OpenAI API for **both** the narration script and the spoken
voiceover, so you'll need your own API key.

1. Go to **[platform.openai.com/api-keys](https://platform.openai.com/api-keys)** and sign in (or create an account).
2. Click **Create new secret key**, give it a name (e.g. `papercast`), and **copy it now** — OpenAI only shows it once. It looks like `sk-...`.
3. Add a payment method and a little credit at **[platform.openai.com/settings/organization/billing](https://platform.openai.com/settings/organization/billing)**.

> **Important:** the API is billed per use and is **separate from ChatGPT Plus** —
> a Plus subscription does *not* include API credit. Without a small balance,
> calls fail with an `insufficient_quota` error. Turning one paper into a video
> typically costs well under **$1**.

You'll paste this key into your `.env` file during install (below). It stays on
your machine — `.env` is git-ignored and never committed.

---

## Install

Python 3.11+ required. A virtual environment is strongly recommended so the
install stays self-contained and the commands resolve correctly.

```bash
git clone https://github.com/sabarna/papercast.git
cd papercast

# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# 2. Install PaperCast and its Python dependencies
python3 -m pip install -e .

# 3. Install the headless browser used to render slides
playwright install chromium

# 4. Install ffmpeg (system package)
#    macOS:   brew install ffmpeg
#    Ubuntu:  sudo apt install ffmpeg

# 5. Create your env file
cp .env.example .env
```

Now open `.env` in a text editor and set your key. `.env` is a **hidden file**
(the leading dot), so a file browser may not show it — open it from the terminal:

```bash
open -e .env        # macOS (TextEdit)
nano .env           # Linux/macOS — or: vi .env, code .env
```

Set this line and save:

```
OPENAI_API_KEY=sk-your-real-key-here
```

> `.env` is git-ignored — your key stays on your machine and is never committed.
> You can also export `OPENAI_API_KEY` as an environment variable instead of
> using the file. In macOS Finder, press **Cmd + Shift + .** to reveal hidden files.

Keep the virtual environment active whenever you use PaperCast. In a new
terminal, re-activate it with `source .venv/bin/activate`.

---

## Usage — command line

Run from the project folder. Each new terminal starts *without* the environment,
so if your prompt doesn't show `(.venv)`, activate it first:

```bash
cd papercast
source .venv/bin/activate            # Windows: .venv\Scripts\activate
```

Then generate a video. The first argument is your paper — an **arXiv ID**, an
**arXiv URL**, a **local PDF path**, or a **PDF URL**:

```bash
# an arXiv paper, by its arXiv ID  ->  writes ./1706.03762.mp4
# (1706.03762 is the arXiv ID of "Attention Is All You Need")
python3 -m app.cli 1706.03762

# the same paper via its arXiv URL, choosing the output filename
python3 -m app.cli https://arxiv.org/abs/1706.03762 -o attention.mp4

# a PDF on your computer
python3 -m app.cli ~/Downloads/paper.pdf

# a PDF hosted online
python3 -m app.cli https://example.com/paper.pdf -o talk.mp4

# tune length (seconds), voice, and model
python3 -m app.cli 1706.03762 --duration 300 --voice nova --model gpt-5.5

# keep the intermediate slides / audio to inspect them
python3 -m app.cli 1706.03762 --keep-workspace -v
```

> An **arXiv ID** looks like `1706.03762` (or `2504.13837`) — the number in an
> arXiv URL such as `arxiv.org/abs/1706.03762`.

`python3 -m app.cli --help` lists every option. A good first paper to try is
`1706.03762` (*Attention Is All You Need*).

> **Shortcut command:** after `pip install -e .` you can also run
> `papercast <id>` and `papercast-web`. If either reports
> `ModuleNotFoundError: No module named 'app'`, your shell is resolving a
> different environment — use the `python3 -m app.cli` / `python3 -m app.web`
> forms instead (they always work from the project folder). See
> [Troubleshooting](#troubleshooting).

---

## Usage — web UI

```bash
source .venv/bin/activate            # if your prompt doesn't already show (.venv)
python3 -m app.web
# then open http://127.0.0.1:8000
```

Paste an arXiv ID, and the page streams live status while the video builds, then
plays it inline with a download link.

Exposing the UI beyond localhost? Set `APP_USERNAME` and `APP_PASSWORD` in `.env`
to require a login so nobody else can spend your API credits.

---

## Troubleshooting

- **`command not found: pip`** — use `python3 -m pip ...` instead of bare `pip`.
- **`ModuleNotFoundError: No module named 'app'`** when running `papercast` /
  `papercast-web` — the shortcut is resolving to a different virtual environment.
  Run `python3 -m app.cli <id>` (or `python3 -m app.web`) from the project
  folder, or recreate the venv:
  ```bash
  python3 -m venv .venv && source .venv/bin/activate && python3 -m pip install -e .
  ```
- **`ffmpeg: command not found` / the video won't encode** — install ffmpeg
  (`brew install ffmpeg` on macOS, `sudo apt install ffmpeg` on Ubuntu).
- **`insufficient_quota` from OpenAI** — add billing credit; the API is separate
  from ChatGPT Plus (see [Getting an OpenAI API key](#getting-an-openai-api-key)).
- **The model name is rejected** — set `NARRATIVE_MODEL` in `.env` to a model your
  account can access (a current `gpt-...` id from your OpenAI dashboard).
- **Some equations render as plain upright text** — PaperCast typesets math with
  KaTeX, which covers a subset of LaTeX. Commands from packages not in the arXiv
  source fall back to readable upright text rather than breaking the slide.

---

## Limitations

- **arXiv** uses LaTeX (best quality); **PDFs** are supported too, but extraction is
  inherently messier — multi-column layouts, section splitting, and figure/equation
  detection are heuristic.
- For PDFs, equations become **images** (no LaTeX). Narration aligns to figures and
  equations via their captions, so a figure with no caption may be placed loosely.
- arXiv equations render with **KaTeX** (a LaTeX subset), so very custom notation may
  render approximately.
- Uses the **paid OpenAI API** — expect roughly well under $1 per paper.

---

## Development

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
ruff check .
```

---

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

[MIT](./LICENSE) © 2026 Sabarna Choudhuri
