#!/usr/bin/env bash
# Zaxira nusxa: Postgres bazasi + rasm/video papkalari. Oxirgi 14 kunlik nusxa saqlanadi.
#   qo'lda:   ./backup.sh
#   har kecha (crontab -e):   30 3 * * * /home/jarvis/baaz/deploy/backup.sh >> /home/jarvis/baaz/deploy/backups/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"
# .env shell fayli emas (qiymatlarda bo'sh joy, $, & bo'lishi mumkin) — faqat kerakli qiymatlarni xavfsiz o'qiymiz.
envval() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"; }
PG_USER="$(envval POSTGRES_USER)"; PG_DB="$(envval POSTGRES_DB)"
mkdir -p backups
ts=$(date +%F_%H%M)

docker compose exec -T db pg_dump -U "${PG_USER:-truckbot}" "${PG_DB:-truck_factory}" | gzip > "backups/db_${ts}.sql.gz"
for vol in bot_media web_media; do
  docker run --rm -v "baaz_${vol}:/data:ro" -v "$PWD/backups:/out" alpine \
    tar czf "/out/${vol}_${ts}.tgz" -C /data .
done
find backups -type f \( -name '*.gz' -o -name '*.tgz' \) -mtime +14 -delete
echo "[$(date '+%F %T')] zaxira tayyor: backups/*_${ts}.*"
