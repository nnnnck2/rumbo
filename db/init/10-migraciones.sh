#!/bin/bash
# Aplica las migraciones al crear la base por primera vez.
set -euo pipefail
PGHOST=/var/run/postgresql bash /scripts/migrar.sh
