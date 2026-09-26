#!/bin/bash
# Droplet setup, once, as root (after cloud-init.yml): swap, Node 22, Caddy, firewall, clone to /opt/transpeaktation.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
# swap: next build + osmnx peaks on a 2 GB box
if ! swapon --show | grep -q /swapfile; then fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab; fi
apt-get update -q
apt-get install -y -q python3-venv python3-dev git ufw debian-keyring debian-archive-keyring apt-transport-https curl gnupg
# Node 22
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y -q nodejs
# Caddy (automatic HTTPS)
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
apt-get update -q && apt-get install -y -q caddy
# firewall: ssh + web only (api/web listen on 127.0.0.1 behind Caddy)
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
# app user + code
id tp
mkdir -p /opt/transpeaktation && chown tp:tp /opt/transpeaktation
sudo -u tp bash -c 'cd /opt/transpeaktation && (test -d .git || git clone -q https://github.com/No-Way-Mo/transpeaktation.git .) && git pull -q --ff-only'
echo PROVISION_DONE
