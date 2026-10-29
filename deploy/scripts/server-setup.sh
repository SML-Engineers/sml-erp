#!/usr/bin/env bash
# One-time preparation of a new Hostinger Ubuntu VPS (24.04 LTS) for SML ERP (P1-10).
# Run as root, once, after adding your SSH public key in the Hostinger panel:
#   curl -fsSL https://raw.githubusercontent.com/SML-Engineers/sml-erp/main/deploy/scripts/server-setup.sh -o setup.sh
#   sudo bash setup.sh
# It installs security updates and Docker, creates the "deploy" user (who runs the ERP),
# turns on the firewall (SSH, HTTP, HTTPS only) and allows SSH sign-in with keys only.
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
say() { printf '\n== %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Run this as root: sudo bash $0"; exit 1; }
. /etc/os-release
[ "$ID" = "ubuntu" ] || { echo "This script is for Ubuntu."; exit 1; }

say "Security updates"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get -y -q upgrade
apt-get install -y -q ca-certificates curl git ufw fail2ban unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades
timedatectl set-timezone Asia/Colombo

say "Docker (from Docker's own repository)"
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'JSON'
{ "log-driver": "json-file", "log-opts": { "max-size": "20m", "max-file": "5" } }
JSON
systemctl enable --now docker
systemctl restart docker

say "The $DEPLOY_USER user"
id "$DEPLOY_USER" >/dev/null 2>&1 || adduser --disabled-password --gecos "SML ERP" "$DEPLOY_USER"
usermod -aG docker "$DEPLOY_USER"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
KEYS="/home/$DEPLOY_USER/.ssh/authorized_keys"
if [ -s /root/.ssh/authorized_keys ]; then
  cat /root/.ssh/authorized_keys >> "$KEYS"
  sort -u -o "$KEYS" "$KEYS"
fi
chown "$DEPLOY_USER:$DEPLOY_USER" "$KEYS" 2>/dev/null || true
chmod 600 "$KEYS" 2>/dev/null || true
if [ ! -s "$KEYS" ]; then
  echo "No SSH key found for root. Add your public key in the Hostinger panel (VPS > Settings >"
  echo "SSH keys), then run this script again. Password sign-in has NOT been switched off."
  exit 1
fi
install -d -m 750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /srv/sml-erp

say "Swap space (helps during image builds on smaller servers)"
if ! swapon --show | grep -q .; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

say "Firewall: only SSH, HTTP and HTTPS"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
systemctl enable --now fail2ban

say "SSH: keys only (no passwords)"
cat > /etc/ssh/sshd_config.d/60-sml-erp.conf <<'SSHD'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
SSHD
sshd -t
systemctl reload ssh || systemctl reload sshd

say "Nightly backup at 01:30 (runs once backups are set up: docs/backups.md)"
cat > /etc/systemd/system/sml-erp-backup.service <<UNIT
[Unit]
Description=SML ERP nightly backup
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
User=$DEPLOY_USER
ExecStart=/srv/sml-erp/app/deploy/scripts/backup.sh
UNIT
cat > /etc/systemd/system/sml-erp-backup.timer <<'UNIT'
[Unit]
Description=SML ERP nightly backup at 01:30

[Timer]
OnCalendar=*-*-* 01:30:00
RandomizedDelaySec=10min
Persistent=true

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now sml-erp-backup.timer

say "Done"
cat <<NEXT
Next, sign in as $DEPLOY_USER (ssh $DEPLOY_USER@<server address>) and follow docs/hosting.md:
  step 4 (get the code), step 5 (environment file), step 6 (first start).
Keep this terminal open until you have checked that ssh $DEPLOY_USER@<server> works.
NEXT
