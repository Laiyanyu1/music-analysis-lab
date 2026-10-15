#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
VENV_DIR="$PROJECT_DIR/.venv-score-form"

PYTHON_BIN="/Users/lyy/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN=$(command -v python3)
fi
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip wheel setuptools
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

mkdir -p "$SCRIPT_DIR/vendor"
if [ ! -d "$SCRIPT_DIR/vendor/Taking-Form/.git" ]; then
  git clone --depth 1 https://github.com/MarkGotham/Taking-Form.git "$SCRIPT_DIR/vendor/Taking-Form"
fi
if [ ! -d "$SCRIPT_DIR/vendor/msaf/.git" ]; then
  git clone --depth 1 https://github.com/urinieto/msaf.git "$SCRIPT_DIR/vendor/msaf"
fi
"$VENV_DIR/bin/pip" install --no-deps -e "$SCRIPT_DIR/vendor/msaf" || true

AUDIVERIS_BIN="$SCRIPT_DIR/vendor/audiveris-macos/Audiveris/Audiveris.app/Contents/MacOS/Audiveris"
if [ ! -x "$AUDIVERIS_BIN" ] && [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  DMG_PATH="/private/tmp/Audiveris-5.11.0-macosx-arm64.dmg"
  curl -L --fail -o "$DMG_PATH" "https://github.com/Audiveris/audiveris/releases/download/5.11.0/Audiveris-5.11.0-macosx-arm64.dmg"
  mkdir -p "$SCRIPT_DIR/vendor/audiveris-macos"
  7z x -y "$DMG_PATH" 'Audiveris/Audiveris.app/*' -o"$SCRIPT_DIR/vendor/audiveris-macos"
fi
chmod +x "$SCRIPT_DIR/audiveris-cli.sh" 2>/dev/null || true

printf '%s\n' "Installed score-form backend dependencies in $VENV_DIR"
printf '%s\n' "MusicXML and image-score analysis dependencies are ready."
