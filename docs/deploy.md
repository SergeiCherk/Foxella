# Запуск на сервере (Ubuntu 24.04 + Docker)

Бот работает через long polling: он сам ходит в Telegram за сообщениями, поэтому открывать порты на сервере не нужно. База SQLite лежит в томе Docker `bot_data` и переживает пересборку и перезапуск.

Все команды ниже выполняются на сервере под `root` (или с `sudo`).

## 1. Подготовка (один раз)

```bash
docker compose version          # если ошибка "compose is not a docker command":
apt update && apt install -y docker-compose-v2 git
```

## 2. Код

```bash
cd /opt
git clone https://github.com/SergeiCherk/foxella.git
cd foxella
```

Если `git clone` спрашивает логин и пароль, репозиторий закрытый. Создайте на GitHub токен только для чтения (Settings → Developer settings → Fine-grained tokens, доступ Contents: Read-only к этому репозиторию) и введите его вместо пароля.

## 3. Настройки и секреты

```bash
cp .env.example .env
nano .env        # BOT_TOKEN, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_EXTRA_BODY
chmod 600 .env   # читать файл может только root
```

Значения те же, что в `.env` на компьютере. Файл `.env` никогда не попадает в git и в образ Docker (`.dockerignore`).

## 4. Запуск

**Сначала остановите бота на компьютере.** Telegram отдаёт сообщения только одному экземпляру с этим токеном; если работают два, оба получают ошибку `Conflict` в журнале.

```bash
docker compose up -d --build
docker compose logs -f bot       # ждём "Run polling for bot @..."; выход: Ctrl+C
```

Первая сборка идёт несколько минут. При запуске бот сам применяет миграции и заполняет таблицу продуктов. Затем напишите боту `/start` в Telegram.

## 5. Обновление

```bash
cd /opt/foxella
git pull
docker compose up -d --build
```

Данные не теряются: база в томе `bot_data`. Незаконченные разговоры тоже продолжаются после обновления.

## 6. Резервные копии базы

```bash
sh scripts/backup_db.sh          # копия в /opt/foxella/backups, хранятся последние 14
```

Каждую ночь автоматически: `crontab -e` и строка

```
0 4 * * * cd /opt/foxella && sh scripts/backup_db.sh >> backups/backup.log 2>&1
```

Копии стоит иногда забирать с сервера к себе (`scp root@адрес:/opt/foxella/backups/*.db .`), иначе при потере сервера пропадут и они.

## 7. Полезное

| Что | Команда |
|---|---|
| Журнал | `docker compose logs -f --tail 100 bot` |
| Перезапустить | `docker compose restart bot` |
| Остановить | `docker compose down` (данные остаются) |
| Статистика и обращения в Telegram | `/admin` и отзывы приходят владельцу из `ADMIN_IDS` в `.env`, затем `docker compose up -d` |
| Статистика беты | `docker compose exec bot python scripts/beta_report.py` |
| Состояние | `docker compose ps` |

## 8. Безопасность сервера (рекомендуется)

Боту не нужны открытые порты, поэтому можно закрыть всё, кроме SSH:

```bash
ufw allow OpenSSH
ufw enable
```

Вход по SSH лучше перевести на ключ вместо пароля (в панели Timeweb: SSH-ключи). Не храните на сервере копии `.env` в других местах и не отправляйте его содержимое в чаты.
