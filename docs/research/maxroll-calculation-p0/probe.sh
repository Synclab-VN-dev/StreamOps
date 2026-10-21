#!/usr/bin/env bash
set -uo pipefail

# Connectivity/profile probe only. This script intentionally does not automate
# /d4/planner: maxroll.gg/robots.txt disallows that path for generic agents.

if [[ $# -ne 1 || ! "$1" =~ ^[A-Za-z0-9]+$ ]]; then
  printf 'Usage: %s PUBLIC_BUILD_ID\n' "$0" >&2
  exit 2
fi

build_id=$1
profile_url="https://planners.maxroll.gg/profiles/load/d4/${build_id}"
tmp_body=$(mktemp)
tmp_headers=$(mktemp)
trap 'rm -f "$tmp_body" "$tmp_headers"' EXIT

printf 'timestamp=%s\n' "$(date --iso-8601=seconds)"

for host in maxroll.gg planners.maxroll.gg; do
  printf '\n[DNS] %s\n' "$host"
  getent ahosts "$host" || true

  printf '[TLS] %s\n' "$host"
  timeout 20 openssl s_client \
    -connect "${host}:443" \
    -servername "$host" \
    -verify_return_error </dev/null 2>&1 \
    | grep -E '^(Verification:|Verify return code:)' || true

  printf '[HTTP] https://%s/\n' "$host"
  curl --silent --show-error --location --output /dev/null \
    --connect-timeout 15 --max-time 30 \
    --write-out 'http_code=%{http_code}\ncontent_type=%{content_type}\nremote_ip=%{remote_ip}\nssl_verify_result=%{ssl_verify_result}\n' \
    "https://${host}/" || true
done

printf '\n[PROFILE] %s\n' "$profile_url"
curl --silent --show-error --location --max-time 30 \
  --dump-header "$tmp_headers" --output "$tmp_body" "$profile_url"
grep -Ei '^(HTTP/|date:|content-type:|content-length:|cache-control:)' \
  "$tmp_headers" || true
printf 'bytes=%s\n' "$(wc -c < "$tmp_body")"
printf 'sha256=%s\n' "$(sha256sum "$tmp_body" | cut -d' ' -f1)"

if jq -e . "$tmp_body" >/dev/null; then
  printf 'valid_json=true\n'
  jq '{
    top_level_type: type,
    top_level_schema: (with_entries(.value |= type)),
    nested_data_schema: (.data | fromjson | with_entries(.value |= type))
  }' "$tmp_body"
else
  printf 'valid_json=false\n'
  exit 1
fi
