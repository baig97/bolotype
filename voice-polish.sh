#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

if [[ -n "${CONDA_ENV_NAME:-}" ]]; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "Error: CONDA_ENV_NAME is set, but conda was not found." >&2
    exit 1
  fi

  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate "$CONDA_ENV_NAME"
else
  if [[ ! -f .venv/bin/activate ]]; then
    echo "Error: .venv does not exist. Run the installer first." >&2
    exit 1
  fi

  source .venv/bin/activate
fi
exec python -m voice_typing.cli polish
