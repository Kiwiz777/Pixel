#!/usr/bin/env bash
#
# smoke_test.sh - verify a compiled build actually works.
#
# The point of this script is one specific risk: FastAPI introspects your
# endpoints at runtime (inspect.signature) and resolves the string annotations
# that `from __future__ import annotations` produces (typing.get_type_hints).
# Nuitka's compiled functions implement that protocol, but it is the most
# likely thing to break. The PUT /api/settings check below exercises the full
# chain - Pydantic v2 body model + Depends() injection - so if it passes, the
# rest of the API will too.
#
# Usage:  cd backend && ./smoke_test.sh [path-to-build]
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="${1:-$HERE/build/run.dist}"
BIN="$DIST/pixel"
PORT="${PB_PORT:-8901}"
TOKEN="${PB_ADMIN_TOKEN:-smoke-test-token}"
STATE="$(mktemp -d)"
BASE="http://127.0.0.1:$PORT"
FAILED=0

[ -x "$BIN" ] || { echo "!! no binary at $BIN - run ./build_pi.sh first" >&2; exit 1; }

cleanup() {
  [ -n "${PID:-}" ] && kill "$PID" 2>/dev/null || true
  wait "${PID:-}" 2>/dev/null || true
  rm -rf "$STATE"
}
trap cleanup EXIT

check() { # check <name> <actual> <expected>
  if [ "$2" = "$3" ]; then
    echo "  PASS  $1"
  else
    echo "  FAIL  $1 (got '$2', want '$3')"
    FAILED=1
  fi
}

echo "==> Booting $BIN (state=$STATE, port=$PORT)"
PB_DATA_DIR="$STATE" PB_PORT="$PORT" PB_ADMIN_TOKEN="$TOKEN" "$BIN" >"$STATE/log" 2>&1 &
PID=$!

for _ in $(seq 1 40); do
  curl -fsS "$BASE/api/health" >/dev/null 2>&1 && break
  kill -0 "$PID" 2>/dev/null || { echo "!! process died:"; cat "$STATE/log"; exit 1; }
  sleep 0.5
done

echo "==> Checks"

# 1. Server is alive and the DB initialised in the *writable* state dir.
check "GET /api/health" \
  "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/health")" "200"
check "DB created outside the bundle" \
  "$([ -f "$STATE/photobooth.db" ] && echo yes || echo no)" "yes"

# 2. THE critical one: Pydantic body model + Depends() through compiled code.
check "PUT /api/settings (pydantic + depends)" \
  "$(curl -s -o /dev/null -w '%{http_code}' -X PUT "$BASE/api/settings" \
      -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
      -d '{"bot_face_visible": true}')" "200"

# 3. Validation must still reject bad bodies, proving the model is real and
#    not silently degraded to "accept anything". SettingsUpdate is extra=allow
#    so it can never 422 - use ChatRequest, which has a required `prompt`.
#    Validation fails before the handler runs, so no provider call is made.
check "POST /api/ai/chat rejects missing field" \
  "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/ai/chat" \
      -H 'Content-Type: application/json' -d '{}')" "422"

# 4. Auth dependency still gates.
check "PUT /api/settings without token" \
  "$(curl -s -o /dev/null -w '%{http_code}' -X PUT "$BASE/api/settings" \
      -H 'Content-Type: application/json' -d '{}')" "401"

# 5. Frontend was bundled and is served from inside the binary's directory.
check "GET / serves the SPA shell" \
  "$(curl -s "$BASE/" | grep -c 'id="app"')" "1"
check "GET /admin deep-link falls back to index" \
  "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/admin")" "200"
check "GET /api/settings/public" \
  "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/settings/public")" "200"

# 6. Graceful degradation survived: optional natives resolve or degrade, but
#    never crash the app.
echo "  INFO  health: $(curl -s "$BASE/api/health")"

echo
if [ "$FAILED" -eq 0 ]; then
  echo "==> ALL PASSED - the compiled build is good."
else
  echo "==> FAILURES above. Server log:"
  cat "$STATE/log"
  exit 1
fi
