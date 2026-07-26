# Deploy Navigator Docker stack (RK3588 / Ubuntu 20.04)

## Сборка (dev-машина)

1. Положить бинарники:
   - `NavAPIServer/bin/naviapiserv.bin`
   - `NDTPClient/bin/NDTP_Client`
2. Запустить cross-build:

```bash
bash docker/docker/build-off-board.sh
```

Артефакты в каталоге `docker/`:

- `navigator-2-rawlog-YYYYMMDD.tar.gz` — Docker-образ (`navigator:2-rawlog`)
- `NavigatorDockerApp-YYYYMMDD.tar.gz` — deploy bundle

## Установка на целевой машине

1. Распаковать bundle:

```bash
tar -xzf NavigatorDockerApp-YYYYMMDD.tar.gz
cd NavigatorDockerApp
```

2. Установить и запустить:

```bash
sudo ./install-docker-from-tar.sh --copy-to-opt
```

При `--copy-to-opt` содержимое bundle копируется в `/opt/navigator` через `rsync --delete`, но **не затираются**:

- `/opt/navigator/.env` — Bearer-токен (`NAVAPI_API_TOKEN`)
- `/opt/navigator/.terminal-id` — идентификатор терминала для NDTP (`PeerAddrFile`)
- `/opt/navigator/db/` — SQLite (`gnrmc.db`, `qr_geo.db`)

После копирования (до запуска контейнера) скрипт интерактивно настраивает:

1. **`.terminal-id`**
   - файл есть и непустой — предлагает текущее значение как default (Enter = оставить);
   - нет или пуст — сообщает, что значение не задано, и запрашивает ввод.
2. **`.env`**
   - файл есть и непустой — сообщает, что найден (содержимое **не** печатается);
   - нет или пуст — предлагает создать из `.env.example` из bundle (по умолчанию **Y**), затем `chmod 600` и владелец как у `/opt/navigator`.

В bundle должен лежать `.env.example` (из `docker/.env.example` при сборке).

`db/` при отсутствии создаётся пустым.

3. Отредактировать конфиги и секрет (после **первой** установки или ротации токена):

```bash
sudo nano /opt/navigator/etc/navapiserv-config.toml
sudo nano /opt/navigator/etc/ndtp-client.toml
sudo nano /opt/navigator/.env   # NAVAPI_API_TOKEN=<секрет>
```

4. Перезапустить (если правили `.env` / compose после install):

```bash
cd /opt/navigator && sudo docker compose up -d --force-recreate --no-build
```

Повторные обновления bundle с `--copy-to-opt` сохраняют уже существующие `.env`, `.terminal-id` и `db/`.

## Структура на host

```
/opt/navigator/
  docker-compose.yml
  .env            # NAVAPI_API_TOKEN (не в git; сохраняется при обновлении)
  .env.example    # шаблон из bundle
  .terminal-id    # NDTP PeerAddrFile → /.terminal-id в контейнере
  etc/          → /etc/navigator (ro)
  db/           → /db (rw)  # gnrmc.db + qr_geo.db (сохраняется при обновлении)
  log/          → /log (rw)
```

## Структура внутри контейнера

```
/app/                     # WORKDIR
/bin/naviapiserv.bin
/bin/NDTP_Client
/bin/NDTPClient           # symlink
/etc/navigator/*.toml
/db/                      # gnrmc.db, qr_geo.db
/log/
```

## Токен API

Compose передаёт `NAVAPI_API_TOKEN` из `.env` в контейнер (`env_file` + `environment`). Это один Bearer для legacy и `/api/qr-geo`.

Ротация: сменить значение в `/opt/navigator/.env` → `docker compose up -d --force-recreate --no-build` → обновить клиенты.  
Повторный `install-docker-from-tar.sh --copy-to-opt` **не** удаляет `.env` и `.terminal-id`.

Полная проверка с камерой и QR-reader — на стендовой среде.

## Локальная dev-сборка на плате

```bash
cd docker
cp .env.example .env   # задать NAVAPI_API_TOKEN
docker compose -f docker-compose.dev.yml up -d --build
```
