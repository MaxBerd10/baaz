#!/usr/bin/env bash
# Test ma'lumotlarini tozalash (production'dan oldin). FAQAT ADMINLAR qoladi; ishchilar va QC botda yangidan,
# selfi bilan ro'yxatdan o'tadi. Oldin avtomatik ZAXIRA olinadi.
#   ko'rish (hech narsa o'chmaydi):  ./reset-data.sh --dry
#   tozalash:                        ./reset-data.sh
set -euo pipefail
cd "$(dirname "$0")"
envval() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"; }
PG_USER="$(envval POSTGRES_USER)"; PG_DB="$(envval POSTGRES_DB)"
q() { docker compose exec -T db psql -U "${PG_USER:-truckbot}" -d "${PG_DB:-truck_factory}" -v ON_ERROR_STOP=1 -At -c "$1"; }

show() {
  echo "  trucklar:            $(q 'select count(*) from trucks')"
  echo "  bosqich yozuvlari:   $(q 'select count(*) from truck_steps')"
  echo "  rasm/video yozuvlar: $(q 'select count(*) from truck_step_media')"
  echo "  ishchilar:           $(q "select count(*) from users where role::text = 'worker'")"
  echo "  QC:                  $(q "select count(*) from users where role::text = 'qc'")"
  echo "  takliflar:           $(q 'select count(*) from invites')"
  echo "  adminlar (QOLADI):   $(q "select count(*) from users where role::text = 'admin'")"
  q "select '    - ' || full_name || ' (' || telegram_id || ')' from users where role::text = 'admin' order by id"
}

echo "HOZIR bazada:"; show
[[ "${1:-}" == "--dry" ]] && { echo "(--dry: hech narsa o'chirilmadi)"; exit 0; }

echo
echo "⚠️  Yuqoridagi trucklar, ishchilar, QC, takliflar va ularning rasm/videolari O'CHADI. Adminlar va model katalogi qoladi."
read -r -p "Davom etish uchun TOZALASH deb yozing: " ans
[[ "$ans" == "TOZALASH" ]] || { echo "Bekor qilindi."; exit 1; }

echo "1/4 zaxira olinmoqda…"
./backup.sh

echo "2/4 baza tozalanmoqda…"
docker compose exec -T db psql -U "${PG_USER:-truckbot}" -d "${PG_DB:-truck_factory}" -v ON_ERROR_STOP=1 -q < reset-data.sql

echo "3/4 rasm/video fayllari tozalanmoqda…"
# adminlarning selfi fayllari saqlanadi
keep="$(q "select coalesce(photo_path, '') from users where role::text = 'admin' and photo_path is not null" | tr '\n' ' ')"
docker compose exec -T -e KEEP="$keep" bot sh -c '
  rm -rf /app/media/trucks
  if [ -d /app/media/users ]; then
    find /app/media/users -type f | while read -r f; do
      case " $KEEP " in *" $f "*) ;; *) rm -f "$f";; esac
    done
  fi'
docker compose exec -T web sh -c 'rm -rf /app/media/tgcache' || true

echo "4/4 tayyor. Hozir bazada:"; show
echo
echo "Endi ishchilar va QC botga taklif havolasi orqali kirib, ro'yxatdan o'tadi (ism, telefon, selfi)."
