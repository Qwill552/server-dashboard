#!/usr/bin/env bash
# Apply the privileged service configuration after a release is deployed.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi

release=/opt/server-dashboard/current
if [[ ! -f "$release/deploy/server-dashboard.service" ]]; then
  echo "Dashboard release not found at $release." >&2
  exit 1
fi

install -d -m 0700 -o root -g root /var/lib/server-dashboard
if ! command -v tmux >/dev/null 2>&1; then
  apt-get update && apt-get install -y tmux || echo "tmux unavailable; terminal sessions will not persist." >&2
fi
install -m 0644 "$release/deploy/server-dashboard.service" /etc/systemd/system/server-dashboard.service
systemctl daemon-reload
systemctl restart server-dashboard.service

for attempt in {1..20}; do
  if curl --silent --fail http://127.0.0.1:5100/api/health >/dev/null; then
    echo "Server console is ready."
    exit 0
  fi
  sleep 0.5
done

echo "Service did not become healthy. Check: journalctl -u server-dashboard.service -n 80" >&2
exit 1
