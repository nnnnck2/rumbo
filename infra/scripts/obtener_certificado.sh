#!/usr/bin/env bash
# Obtiene el primer certificado de Let's Encrypt para $DOMINIO (método webroot).
# Lo llama desplegar.sh solo si todavía no existe un certificado real.
#
# Problema del huevo y la gallina: nginx no arranca sin certificado, y Let's Encrypt necesita
# nginx respondiendo en el puerto 80. Solución: certificado autofirmado temporal → arrancar
# nginx → borrar el temporal → pedir el real → recargar nginx.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

dc() { docker compose "$@"; }
VIVO="/etc/letsencrypt/live/$DOMINIO"

if dc run --rm --no-deps --entrypoint sh certbot -c "test -f $VIVO/fullchain.pem && test -f /etc/letsencrypt/renewal/$DOMINIO.conf"; then
    echo "✔ Ya existe un certificado de Let's Encrypt para $DOMINIO."
    exit 0
fi

echo "▶ Certificado temporal autofirmado"
dc run --rm --no-deps --entrypoint sh certbot -c "
    mkdir -p $VIVO &&
    openssl req -x509 -nodes -newkey rsa:2048 -days 1 -subj '/CN=$DOMINIO' \
        -keyout $VIVO/privkey.pem -out $VIVO/fullchain.pem"

echo "▶ Arrancando nginx"
dc up -d nginx
sleep 3

echo "▶ Borrando el temporal"
dc run --rm --no-deps --entrypoint sh certbot -c "rm -rf $VIVO /etc/letsencrypt/archive/$DOMINIO /etc/letsencrypt/renewal/$DOMINIO.conf"

echo "▶ Pidiendo el certificado a Let's Encrypt"
STAGING=()
[ "${LETSENCRYPT_STAGING:-0}" = "1" ] && STAGING=(--staging)
dc run --rm --no-deps certbot certonly --webroot -w /var/www/acme \
    -d "$DOMINIO" --email "$CORREO_LETSENCRYPT" \
    --agree-tos --no-eff-email --rsa-key-size 4096 --non-interactive "${STAGING[@]}"

dc exec nginx nginx -s reload
echo "✔ Certificado instalado. Renovación automática: servicio certbot (cada 12 h)."
