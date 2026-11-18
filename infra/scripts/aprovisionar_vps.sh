#!/usr/bin/env bash
# Prepara un VPS nuevo con Ubuntu 24.04 LTS para Rumbo (SCRUM-15). Se ejecuta UNA vez, como root:
#
#   curl -fsSL https://raw.githubusercontent.com/nnnnck2/rumbo/main/infra/scripts/aprovisionar_vps.sh -o aprovisionar.sh
#   sudo bash aprovisionar.sh "ssh-ed25519 AAAA... clave-publica-del-equipo"
#
# Qué hace: actualiza el sistema, instala Docker (repositorio oficial), crea el usuario "rumbo",
# cortafuegos (solo 22, 80, 443), fail2ban, actualizaciones de seguridad automáticas,
# zona horaria de Ecuador, swap de 2 GB y deja el repositorio en /opt/rumbo.
# Es idempotente: se puede volver a ejecutar sin romper nada.
set -euo pipefail

CLAVE_SSH="${1:-}"
REPO_URL="${REPO_URL:-https://github.com/nnnnck2/rumbo.git}"
USUARIO=rumbo
DESTINO=/opt/rumbo

[ "$(id -u)" -eq 0 ] || { echo "Ejecutar como root (sudo)." >&2; exit 1; }
. /etc/os-release
[ "${ID:-}" = "ubuntu" ] || echo "⚠ Probado en Ubuntu 24.04; este sistema es ${PRETTY_NAME:-desconocido}."

echo "▶ Sistema base"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -yq
apt-get install -yq ca-certificates curl git ufw fail2ban unattended-upgrades cron
timedatectl set-timezone America/Guayaquil

echo "▶ Docker (repositorio oficial)"
if ! command -v docker >/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -q
    apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
# Rotación de logs de contenedores para que no llenen el disco
cat > /etc/docker/daemon.json <<'JSON'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "5" } }
JSON
systemctl enable --now docker
systemctl restart docker

echo "▶ Usuario $USUARIO"
id "$USUARIO" >/dev/null 2>&1 || adduser --disabled-password --gecos "" "$USUARIO"
usermod -aG docker "$USUARIO"
if [ -n "$CLAVE_SSH" ]; then
    install -d -m 700 -o "$USUARIO" -g "$USUARIO" /home/$USUARIO/.ssh
    grep -qxF "$CLAVE_SSH" /home/$USUARIO/.ssh/authorized_keys 2>/dev/null \
        || echo "$CLAVE_SSH" >> /home/$USUARIO/.ssh/authorized_keys
    chown "$USUARIO:$USUARIO" /home/$USUARIO/.ssh/authorized_keys
    chmod 600 /home/$USUARIO/.ssh/authorized_keys
fi

echo "▶ SSH: sin root ni contraseñas (solo si ya hay una clave instalada)"
if [ -s /home/$USUARIO/.ssh/authorized_keys ]; then
    cat > /etc/ssh/sshd_config.d/90-rumbo.conf <<'CONF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
CONF
    systemctl reload ssh || systemctl reload sshd
else
    echo "  ⚠ No se pasó clave SSH: se deja el acceso por contraseña. Vuelva a ejecutar con la clave."
fi

echo "▶ Cortafuegos"
# Docker publica puertos saltándose ufw; por eso la base y Redis NO publican puertos a internet
# (la base solo en 127.0.0.1, Redis en red interna).
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "▶ fail2ban (SSH)"
cat > /etc/fail2ban/jail.d/rumbo.conf <<'CONF'
[sshd]
enabled  = true
maxretry = 5
findtime = 10m
bantime  = 1h
CONF
systemctl enable --now fail2ban
systemctl restart fail2ban

echo "▶ Actualizaciones de seguridad automáticas"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF

echo "▶ Swap de 2 GB"
if ! swapon --show | grep -q /swapfile; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "▶ Repositorio en $DESTINO"
if [ ! -d "$DESTINO/.git" ]; then
    git clone "$REPO_URL" "$DESTINO"
fi
chown -R "$USUARIO:$USUARIO" "$DESTINO"
install -d -o "$USUARIO" -g "$USUARIO" /var/log/rumbo

cat <<FIN

✔ VPS listo. Siguientes pasos (como usuario $USUARIO):
  1. cd $DESTINO/db    && cp .env.example .env    # claves reales (openssl rand -base64 32)
  2. cd $DESTINO/infra && cp .env.example .env    # DOMINIO, CORREO_LETSENCRYPT, REDIS_PASSWORD
  3. Verificar que el DNS del dominio apunta a esta IP:  $(curl -fsS -4 https://ifconfig.me || echo '?')
  4. bash $DESTINO/infra/scripts/desplegar.sh
FIN
