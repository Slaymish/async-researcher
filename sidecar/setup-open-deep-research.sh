#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install "open-deep-research"

cat <<EOF
Open Deep Research sidecar environment created.

Set Obsidian Researcher settings:
  Deep research runner: Sidecar process
  Sidecar command: ${VENV_DIR}/bin/python
  Sidecar engine: open_deep_research

Set provider/search API keys in your shell environment before launching Obsidian,
or use your OS launch environment tooling.
EOF
