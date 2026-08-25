#!/bin/sh
set -eu

readonly template=/etc/mihomo/config.yaml
readonly runtime_dir=/tmp/mihomo
readonly runtime_config="$runtime_dir/config.yaml"
readonly last_known_good="$runtime_dir/config.last-known-good.yaml"
readonly readiness_marker=/run/mihomo/notion-ready

fail() {
  printf '%s\n' "notion-proxy: $1" >&2
  exit 1
}

[ -n "${VPN_SUB_URL:-}" ] || fail "VPN_SUB_URL is required"
case "$VPN_SUB_URL" in
  https://*) ;;
  *) fail "VPN_SUB_URL must use HTTPS" ;;
esac
case "$VPN_SUB_URL" in
  *\"*|*\\*)
    fail "VPN_SUB_URL contains unsupported characters"
    ;;
esac

mkdir -p "$runtime_dir/providers"
umask 077
next_config="$runtime_dir/config.next.yaml"
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    *"__VPN_SUB_URL__"*) printf '%s\n' "    url: \"$VPN_SUB_URL\"" ;;
    *) printf '%s\n' "$line" ;;
  esac
done <"$template" >"$next_config"

if mihomo -t -f "$next_config" >/dev/null 2>&1; then
  mv -f "$next_config" "$runtime_config"
  cp "$runtime_config" "$last_known_good"
elif [ -f "$last_known_good" ]; then
  rm -f "$next_config"
  cp "$last_known_good" "$runtime_config"
else
  rm -f "$next_config"
  fail "subscription configuration validation failed"
fi

mihomo -f "$runtime_config" &
mihomo_pid=$!
trap 'kill "$mihomo_pid" 2>/dev/null || true; wait "$mihomo_pid" 2>/dev/null || true' INT TERM EXIT

for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  response_file="$runtime_dir/notion-response.json"
  if curl --silent --show-error --max-time 10 --noproxy '' \
    --proxy http://127.0.0.1:7890 \
    --header 'Notion-Version: 2022-06-28' \
    --output "$response_file" \
    https://api.notion.com/v1/users/me >/dev/null 2>&1 &&
    grep -q '"object":"error"' "$response_file" &&
    ! grep -qiE 'cloudflare|<html' "$response_file"; then
    : >"$readiness_marker"
    wait "$mihomo_pid"
    exit $?
  fi
  sleep 2
done

fail "proxied Notion API readiness check failed"
