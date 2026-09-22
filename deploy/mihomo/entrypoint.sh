#!/bin/sh
set -eu

readonly template=/etc/mihomo/config.yaml
readonly profile=/etc/mihomo/koala-profile.yaml
readonly runtime_dir=/tmp/mihomo
readonly runtime_config="$runtime_dir/config.yaml"
readonly last_known_good="$runtime_dir/config.last-known-good.yaml"
readonly readiness_marker=/run/mihomo/notion-ready

fail() {
  printf '%s\n' "notion-proxy: $1" >&2
  exit 1
}

mkdir -p "$runtime_dir/providers"
umask 077
next_config="$runtime_dir/config.next.yaml"
if [ -s "$profile" ]; then
  awk '
    /^mixed-port:/ { print "mixed-port: 7890"; seen_mixed=1; next }
    /^allow-lan:/ { print "allow-lan: true"; seen_allow=1; next }
    /^bind-address:/ { print "bind-address: \"0.0.0.0\""; seen_bind=1; next }
    /^mode:/ { print "mode: rule"; seen_mode=1; next }
    { print }
    END {
      if (!seen_mixed) print "mixed-port: 7890"
      if (!seen_allow) print "allow-lan: true"
      if (!seen_bind) print "bind-address: \"0.0.0.0\""
      if (!seen_mode) print "mode: rule"
    }
  ' "$profile" >"$next_config"
else
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
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      *"__VPN_SUB_URL__"*) printf '%s\n' "    url: \"$VPN_SUB_URL\"" ;;
      *) printf '%s\n' "$line" ;;
    esac
  done <"$template" >"$next_config"
fi

if /mihomo -d "$runtime_dir" -t -f "$next_config" >/dev/null 2>&1; then
  mv -f "$next_config" "$runtime_config"
  cp "$runtime_config" "$last_known_good"
elif [ -f "$last_known_good" ]; then
  rm -f "$next_config"
  cp "$last_known_good" "$runtime_config"
else
  rm -f "$next_config"
  fail "subscription configuration validation failed"
fi

/mihomo -d "$runtime_dir" -f "$runtime_config" &
mihomo_pid=$!
trap 'kill "$mihomo_pid" 2>/dev/null || true; wait "$mihomo_pid" 2>/dev/null || true' INT TERM EXIT

for _ in 1 2 3; do
  sleep 1
  kill -0 "$mihomo_pid" 2>/dev/null || fail "Mihomo exited during startup"
done

# The official image contains no HTTP client. A read-only Notion API probe is
# performed from the backend during deployment verification instead.
: >"$readiness_marker"
wait "$mihomo_pid"
