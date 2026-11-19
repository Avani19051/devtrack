#!/usr/bin/env bash
# Full regression: build the C++ core, run GoogleTest + pytest, and triage any failures.
#   ./scripts/run_regression.sh            # everything
#   SKIP_CPP=1 ./scripts/run_regression.sh # Python only (pure-Python core fallback)
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p reports
LOG=reports/regression.log
: > "$LOG"
status=0

run() {  # run a step, tee its output into the log, remember failures
    echo "==> $*" | tee -a "$LOG"
    if ! "$@" 2>&1 | tee -a "$LOG"; then status=1; fi
}

if [[ "${SKIP_CPP:-0}" != "1" ]]; then
    run cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
    run cmake --build build -j"$(nproc 2>/dev/null || echo 2)"
    run ctest --test-dir build --output-on-failure --output-junit "$ROOT/reports/ctest.xml"
fi

run python3 -m pytest -q --junitxml=reports/pytest.xml

if [[ $status -ne 0 ]]; then
    echo -e "\n==> Regression FAILED. Triage:" | tee -a "$LOG"
    python3 -m devtrack.cli triage "$LOG" | tee reports/triage.txt
else
    echo -e "\n==> Regression PASSED" | tee -a "$LOG"
fi
exit $status
