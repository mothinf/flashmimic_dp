#!/usr/bin/env bash
# C++ inference check; Python only resolves YAML, no Python ONNX Runtime needed.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${PYTHON:-python3}" "$HERE/run_checks.py" numeric "$@"
