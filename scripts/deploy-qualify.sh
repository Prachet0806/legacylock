#!/usr/bin/env bash
# LegacyLock Phase D deployment qualification (Render + Vercel).
# Usage:
#   scripts/deploy-qualify.sh --api https://api.example.com --app https://app.example.com
#   QUALIFY_OWNER_PASSWORD=<secret> scripts/deploy-qualify.sh --api ... --app ... --owner-email ...
# Phase 1 (anonymous) always runs. Phase 2 (authenticated) runs only when
# owner creds are provided. Never triggers or resets the vault.
set -euo pipefail

API=""; APP=""; EMAIL=""; PASSWORD="${QUALIFY_OWNER_PASSWORD:-}"; SKIP_APP=0; EXPECT_HSTS=0
while [ $# -gt 0 ]; do
  case "$1" in
    --api) API="$2"; shift 2;;
    --app) APP="$2"; shift 2;;
    --owner-email) EMAIL="$2"; shift 2;;
    --owner-password) PASSWORD="$2"; shift 2;;
    --skip-app) SKIP_APP=1; shift;;
    --expect-hsts) EXPECT_HSTS=1; shift;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
[ -n "$API" ] || { echo "usage: $0 --api URL [--app URL | --skip-app] [--owner-email E --owner-password P]" >&2; exit 2; }
if [ "$SKIP_APP" = "0" ] && [ -z "$APP" ]; then echo "usage: $0 --api URL [--app URL | --skip-app]" >&2; exit 2; fi

pass=0; fail=0
ok() { echo "PASS $1"; pass=$((pass+1)); }
no() { echo "FAIL $1${2:+ ($2)}"; fail=$((fail+1)); }

echo "== Phase D.1 anonymous =="
body="$(curl -fsS --max-time 15 "$API/health" || true)"
case "$body" in *'"status"'*'"ok"'*) ok "api /health cheap ok";; *) no "api /health cheap ok" "$body";; esac

body="$(curl -fsS --max-time 15 "$API/readyz" || true)"
case "$body" in *'"status"'*'"ready"'*) ok "api /readyz db-ready";; *) no "api /readyz db-ready" "$body";; esac

if [ "$SKIP_APP" = "0" ]; then
body="$(curl -fsS --max-time 15 "$APP/api/health" || true)"
case "$body" in *'"status"'*'"ok"'*) ok "app /api/health via rewrite";; *) no "app /api/health via rewrite" "$body";; esac

body="$(curl -fsS --max-time 15 "$APP/api/readyz" || true)"
case "$body" in *'"status"'*'"ready"'*) ok "app /api/readyz via rewrite";; *) no "app /api/readyz via rewrite" "$body";; esac
fi

hdrs="$(curl -fsS --max-time 15 -D - -o /dev/null "$API/health" | tr -d '\r' || true)"
case "$hdrs" in
  *[Cc][Oo][Nn][Tt][Ee][Nn][Tt]-[Ss][Ee][Cc][Uu][Rr][Ii][Tt][Yy]-[Pp][Oo][Ll][Ii][Cc][Yy]*"script-src 'self'"*) ok "api csp same-origin scripts";;
  *) no "api csp same-origin scripts";;
esac
case "$hdrs" in
  *unsafe-*) no "api csp no unsafe-*";;
  *) ok "api csp no unsafe-*";;
esac
if printf '%s' "$hdrs" | grep -qi "referrer-policy"; then ok "api referrer-policy"; else no "api referrer-policy"; fi
if printf '%s' "$hdrs" | grep -qi "x-content-type-options:[[:space:]]*nosniff"; then ok "api nosniff"; else no "api nosniff"; fi
if [ "$EXPECT_HSTS" = "1" ]; then
  if printf '%s' "$hdrs" | grep -qi "strict-transport-security"; then ok "api hsts (prod tls)"; else no "api hsts (prod tls)"; fi
fi
if curl -fsS --max-time 15 -X OPTIONS "$API/auth/login" -H "Origin: ${APP:-$API}" -H "Access-Control-Request-Method: POST" -D - -o /dev/null | grep -qi "access-control-allow-origin"; then ok "api cors app-origin"; else no "api cors app-origin"; fi

code="$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' -X POST "$API/auth/test-issue-verification" -H 'Content-Type: application/json' -d '{"email":"nobody@example.com"}')"
[ "$code" = "404" ] && ok "test-endpoint absent (404)" || no "test-endpoint absent" "got $code"

code="$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' -X POST "$API/auth/login" -H 'Content-Type: application/json' -H 'Origin: https://evil.example.com' -d '{"email":"x@example.com","password":"0123456789ab"}')"
[ "$code" = "403" ] && ok "origin-check rejects evil origin" || no "origin-check" "got $code want 403"

if [ -n "$EMAIL" ] && [ -n "$PASSWORD" ]; then
  [ -n "$APP" ] || { echo "Authenticated qualification requires --app for the same-origin cookie contract" >&2; exit 2; }
  echo "== Phase D.2 authenticated =="
  umask 077
  jar="$(mktemp)"; payload="$(mktemp)"; trap 'rm -f "$jar" "$payload"' EXIT
  # Keep credentials out of curl argv and produce correct JSON for all characters.
  QUALIFY_EMAIL="$EMAIL" QUALIFY_OWNER_PASSWORD="$PASSWORD" "${PYTHON_BIN:-python3}" -c 'import os,json; print(json.dumps({"email":os.environ["QUALIFY_EMAIL"],"password":os.environ["QUALIFY_OWNER_PASSWORD"]}))' > "$payload"
  auth_base="$APP/api"
  code="$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' -c "$jar" -X POST "$auth_base/auth/login" -H "Origin: $APP" -H 'Content-Type: application/json' --data-binary "@$payload")"
  [ "$code" = "200" ] && ok "owner login 200" || no "owner login" "got $code"
  if grep -qi "legacylock_owner_session" "$jar" && grep -qi "legacylock_owner_refresh" "$jar"; then ok "owner session cookies set"; else no "owner session cookies"; fi
  body="$(curl -fsS --max-time 15 -b "$jar" "$auth_base/vault/status" || true)"
  case "$body" in *'"status"'*) ok "vault status reachable";; *) no "vault status reachable" "$body";; esac
  body="$(curl -fsS --max-time 15 -b "$jar" "$auth_base/heartbeat" || true)"
  case "$body" in *'interval_days'*) ok "heartbeat config reachable";; *) no "heartbeat config reachable" "$body";; esac
  code="$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' -b "$jar" -c "$jar" -X POST "$auth_base/auth/refresh" -H "Origin: $APP")"
  [ "$code" = "200" ] && ok "same-origin refresh" || no "same-origin refresh" "got $code"
  code="$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' -b "$jar" -c "$jar" -X POST "$auth_base/auth/logout" -H "Origin: $APP")"
  [ "$code" = "200" ] && ok "same-origin logout" || no "same-origin logout" "got $code"
  code="$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' -b "$jar" "$auth_base/auth/me")"
  [ "$code" = "401" ] && ok "logged-out session denied" || no "logged-out session denied" "got $code"
fi

echo "== $pass passed, $fail failed =="
[ "$fail" -eq 0 ]
