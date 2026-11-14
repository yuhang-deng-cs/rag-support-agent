#!/bin/sh
# Docker entrypoint hook: runs once, on first start of an empty data volume.
set -eu
psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_user="${APP_DB_USER:-rag_app}" \
     -v app_password="${APP_DB_PASSWORD:?APP_DB_PASSWORD must be set}" \
     -f /docker-entrypoint-initdb.d/app_role.psql
