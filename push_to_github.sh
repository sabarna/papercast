#!/usr/bin/env bash
# Initialise git history and push Readel to a new GitHub repo.
# Run this on your own machine (not needed if you push manually).
#
#   ./push_to_github.sh <github-username> [repo-name]
#
# Requires: git, and either the GitHub CLI (`gh`) OR an already-created empty
# GitHub repo you have push access to.
set -euo pipefail

USER="${1:?usage: ./push_to_github.sh <github-username> [repo-name]}"
REPO="${2:-readel}"

# point project URLs at the real repo
if command -v sed >/dev/null; then
  sed -i.bak "s#github.com/OWNER/readel#github.com/${USER}/${REPO}#g" pyproject.toml README.md CONTRIBUTING.md 2>/dev/null || true
  rm -f pyproject.toml.bak README.md.bak CONTRIBUTING.md.bak 2>/dev/null || true
fi

git init -b main
git add .
git commit -m "Initial commit: Readel — arXiv paper to narrated video (CLI + web UI)"

if command -v gh >/dev/null; then
  # Creates the repo as PUBLIC and pushes in one step.
  gh repo create "${USER}/${REPO}" --public --source=. --remote=origin --push
  echo "✓ Pushed to https://github.com/${USER}/${REPO}"
else
  echo "GitHub CLI (gh) not found."
  echo "1) Create an EMPTY public repo at https://github.com/new  (name: ${REPO})"
  echo "2) Then run:"
  echo "     git remote add origin https://github.com/${USER}/${REPO}.git"
  echo "     git push -u origin main"
fi
