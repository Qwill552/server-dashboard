#!/usr/bin/env bash
# Run manually once on the VPS: sudo bash scripts/bootstrap-server.sh
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi

if ! getent group dashboard-app >/dev/null; then
  groupadd --system dashboard-app
fi
if ! id dashboard-app >/dev/null 2>&1; then
  useradd --system --gid dashboard-app --home-dir /nonexistent --shell /usr/sbin/nologin dashboard-app
fi
if ! getent group dashboard-deploy >/dev/null; then
  groupadd dashboard-deploy
fi
if ! id dashboard-deploy >/dev/null 2>&1; then
  useradd --create-home --gid dashboard-deploy --shell /bin/bash dashboard-deploy
fi

install -d -m 0755 -o dashboard-deploy -g dashboard-deploy /opt/server-dashboard
install -d -m 0755 -o dashboard-deploy -g dashboard-deploy /opt/server-dashboard/releases
install -d -m 0700 -o root -g root /var/lib/server-dashboard
install -d -m 0700 -o dashboard-deploy -g dashboard-deploy /home/dashboard-deploy/.ssh
touch /home/dashboard-deploy/.ssh/authorized_keys
chown dashboard-deploy:dashboard-deploy /home/dashboard-deploy/.ssh/authorized_keys
chmod 0600 /home/dashboard-deploy/.ssh/authorized_keys

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install -m 0644 "$script_dir/../deploy/server-dashboard.service" /etc/systemd/system/server-dashboard.service
cat >/etc/sudoers.d/server-dashboard-deploy <<'EOF'
dashboard-deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart server-dashboard.service
EOF
chmod 0440 /etc/sudoers.d/server-dashboard-deploy
visudo -cf /etc/sudoers.d/server-dashboard-deploy
systemctl daemon-reload
systemctl enable server-dashboard.service

echo "Server prepared. Add the public deployment key to /home/dashboard-deploy/.ssh/authorized_keys."
echo "The dashboard service will start with the first successful deployment."
