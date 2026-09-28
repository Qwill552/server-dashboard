#!/usr/bin/env bash
# Called on the VPS by GitHub Actions as dashboard-deploy.
set -euo pipefail
umask 022

sha="${1:-}"
if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Expected a 40-character commit SHA." >&2
  exit 1
fi

base=/opt/server-dashboard
release="$base/releases/$sha"
if [[ ! -f "$release/requirements.txt" || ! -f "$release/dashboard/__main__.py" ]]; then
  echo "Incomplete release: $release" >&2
  exit 1
fi

python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install --disable-pip-version-check --no-input -r "$release/requirements.txt"

previous="$(readlink -f "$base/current" 2>/dev/null || true)"
ln -sfnT "$release" "$base/.current-$sha"
mv -Tf "$base/.current-$sha" "$base/current"
sudo -n /usr/bin/systemctl restart server-dashboard.service

for attempt in {1..20}; do
  if python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:5100/api/health", timeout=1)' >/dev/null 2>&1; then
    echo "Deployed $sha successfully."
    exit 0
  fi
  sleep 0.5
done

echo "Health check failed after deploying $sha." >&2
if [[ -n "$previous" && -d "$previous" ]]; then
  ln -sfnT "$previous" "$base/.rollback-$sha"
  mv -Tf "$base/.rollback-$sha" "$base/current"
  sudo -n /usr/bin/systemctl restart server-dashboard.service
  echo "Previous release restored: $previous" >&2
fi
exit 1
