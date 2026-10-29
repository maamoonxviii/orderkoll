#!/usr/bin/env bash
# Run the modules' Odoo tests locally, the same way CI does: the OCA CI image for the chosen
# Odoo version and a throwaway PostgreSQL, both in Docker (Odoo is never installed on the host).
#
#   tools/test_odoo.sh [odoo version] [addons dir] [extra mount ...]
#   tools/test_odoo.sh 19.0 .                                          # this repository
#   tools/test_odoo.sh 19.0 ../orderkoll-pro /abs/orderkoll:/build/vendor/orderkoll   # Pro with this core
#
# Extra mounts are passed to `docker run -v` as given. The log is printed and kept in
# /tmp/orderkoll-test-<version>.log; the exit code is the test run's.
set -euo pipefail
VERSION=${1:-19.0}
ADDONS=$(cd "${2:-.}" && pwd)
shift $(( $# > 2 ? 2 : $# ))
IMAGE=ghcr.io/oca/oca-ci/py3.10-odoo${VERSION}:latest
NET=orderkoll-test-$$
LOG=/tmp/orderkoll-test-${VERSION}.log
MOUNTS=()
for m in "$@"; do MOUNTS+=(-v "$m"); done
# a git worktree keeps its git data in the main checkout: mount that at the same path
if [ -f "$ADDONS/.git" ]; then
  COMMON=$(git -C "$ADDONS" rev-parse --path-format=absolute --git-common-dir)
  MOUNTS+=(-v "$COMMON:$COMMON:ro")
fi

cleanup() { docker rm -f "${NET}-pg" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create "$NET" >/dev/null
docker run -d --name "${NET}-pg" --network "$NET" --network-alias postgres \
  -e POSTGRES_USER=odoo -e POSTGRES_PASSWORD=odoo -e POSTGRES_DB=odoo postgres:15 >/dev/null

# The same steps as .github/workflows/ci.yml (odoo-tests job).
docker run --rm --network "$NET" -v "$ADDONS:/build" "${MOUNTS[@]}" -w /build "$IMAGE" bash -c '
  set -e
  rm -f test-constraints.txt .coverage            # leftovers of an earlier run
  oca_install_addons >/dev/null
  pip install -q -r requirements.txt -U "pyOpenSSL>=24.2" "cryptography>=42" "urllib3>=1.26.20,<2"
  oca_init_test_database >/dev/null
  oca_run_tests
' 2>&1 | tee "$LOG"
STATUS=${PIPESTATUS[0]}
rm -f "$ADDONS/test-constraints.txt" "$ADDONS/.coverage"
exit "$STATUS"
