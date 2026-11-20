#!/usr/bin/env sh
# Back up the bot's SQLite database from the running container (run on the server, from the
# project folder). A plain file copy of a database in use can be broken, so the copy is made by
# SQLite itself; the last 14 copies are kept in ./backups.
#
#   sh scripts/backup_db.sh
#   # every night at 04:00:  crontab -e  ->  0 4 * * * cd /opt/foxella && sh scripts/backup_db.sh
set -eu

mkdir -p backups
stamp=$(date +%Y-%m-%d_%H%M)

docker compose exec -T bot python -c "
import sqlite3
source = sqlite3.connect('/app/storage/nutrition_bot.db')
target = sqlite3.connect('/app/storage/backup.db')
source.backup(target)
target.close()
source.close()
"
docker compose cp bot:/app/storage/backup.db "backups/nutrition_bot_$stamp.db"
docker compose exec -T bot rm -f /app/storage/backup.db

ls -1t backups/nutrition_bot_*.db | tail -n +15 | xargs -r rm -f
echo "saved backups/nutrition_bot_$stamp.db"
