#!/usr/bin/env bash
# Python/C++ parity with configurable deployment and geometry inputs; no DDS.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${PYTHON:-python3}" "$HERE/run_checks.py" parity "$@"
