# Reproduce Maxroll calculation P0

Run from the repository root on Linux. These commands reproduce the permitted
connectivity and public-profile checks; they do not automate the planner UI.

## Prerequisites

Required commands: Bash, `getent`, `curl`, `openssl`, `timeout`, `sha256sum`,
and `jq`. No Maxroll credentials are used.

## All permitted probes

Use a build ID from a documented public planner link, not a random value:

```bash
bash docs/research/maxroll-calculation-p0/probe.sh zj6zc20q
```

The evidence run sourced `zj6zc20q` from:
`https://www.reddit.com/r/D4Barbarian/comments/1wqem82/i_can_probably_go_faster_what_do_you_think/`.

## Individual NET tests

```bash
getent ahosts maxroll.gg
getent ahosts planners.maxroll.gg

openssl s_client -connect maxroll.gg:443 \
  -servername maxroll.gg -verify_return_error </dev/null
openssl s_client -connect planners.maxroll.gg:443 \
  -servername planners.maxroll.gg -verify_return_error </dev/null

curl --silent --show-error --location --output /dev/null \
  --write-out 'http=%{http_code} type=%{content_type} ip=%{remote_ip} tls_verify=%{ssl_verify_result}\n' \
  https://maxroll.gg/
curl --silent --show-error --location --output /dev/null \
  --write-out 'http=%{http_code} type=%{content_type} ip=%{remote_ip} tls_verify=%{ssl_verify_result}\n' \
  https://planners.maxroll.gg/
```

## API-01 and API-02

The temporary files are deleted when the shell exits. Response headers are
filtered so cookies are not printed or persisted.

```bash
profile_body=$(mktemp)
profile_headers=$(mktemp)
trap 'rm -f "$profile_body" "$profile_headers"' EXIT

curl --silent --show-error --location --max-time 30 \
  --dump-header "$profile_headers" --output "$profile_body" \
  https://planners.maxroll.gg/profiles/load/d4/zj6zc20q

grep -Ei '^(HTTP/|date:|content-type:|content-length:|cache-control:)' \
  "$profile_headers"
jq -e . "$profile_body" >/dev/null
wc -c "$profile_body"
sha256sum "$profile_body"
jq '{top_level_schema: with_entries(.value |= type),
     nested_data_schema: (.data | fromjson | with_entries(.value |= type))}' \
  "$profile_body"
```

## CALC-01 through CALC-04

Do not run Playwright against `/d4/planner/*` without written permission from
the site owner. Re-check the live policy before any future attempt:

```bash
curl --silent --show-error https://maxroll.gg/robots.txt
```

At the evidence timestamp, the published text prohibited automated retrieval
without written permission and the generic-agent rules explicitly disallowed
`/d4/planner/*`. Therefore calculation endpoint discovery, modifier A/B tests,
three-run consistency checks, screenshots, and calculation traces have no
reproduction command in this run.
