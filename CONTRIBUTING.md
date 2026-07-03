# Contributing to PaperCast

Thanks for your interest in improving PaperCast! Contributions of all sizes are
welcome — bug reports, docs, and code.

## Getting set up

```bash
git clone https://github.com/sabarna/papercast.git
cd papercast
pip install -e ".[dev]"
playwright install chromium
cp .env.example .env   # add your API keys
```

## Before you open a pull request

- Run the tests: `pytest`
- Lint: `ruff check .`
- Keep pull requests focused; describe what changed and why.
- If you're adding a feature, a short note in the README helps users find it.

## Reporting bugs

Open an issue with the arXiv ID you were processing, the command you ran, and the
full error output. Papers with unusual LaTeX are especially useful test cases.

## Code of conduct

Be respectful and constructive. We want this to be a welcoming project.
