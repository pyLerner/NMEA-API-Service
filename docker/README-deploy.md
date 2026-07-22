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
- `/opt/navigator/db/` — SQLite (`gnrmc.db`, `qr_geo.db`)

Если `.env` или `db/` ещё нет, скрипт **не падает**: `db/` создаётся пустым, для `.env` пишется предупреждение.

3. Отредактировать конфиги и секрет (после **первой** установки или ротации токена):

```bash
sudo nano /opt/navigator/etc/navapiserv-config.toml
sudo nano /opt/navigator/etc/ndtp-client.toml

# Если .env ещё нет:
sudo cp /path/to/repo/docker/.env.example /opt/navigator/.env
sudo nano /opt/navigator/.env   # NAVAPI_API_TOKEN=<секрет>
sudo chmod 600 /opt/navigator/.env
```

4. Перезапустить (если правили `.env` / compose после install):

```bash
cd /opt/navigator && sudo docker compose up -d --force-recreate --no-build
```

Повторные обновления bundle с `--copy-to-opt` сохраняют уже существующие `.env` и `db/`.

## Структура на host

```
/opt/navigator/
  docker-compose.yml
  .env            # NAVAPI_API_TOKEN (не в git; сохраняется при обновлении)
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
Повторный `install-docker-from-tar.sh --copy-to-opt` **не** удаляет `.env`.

Полная проверка с камерой и QR-reader — на стендовой среде.

## Локальная dev-сборка на плате

```bash
cd docker
cp .env.example .env   # задать NAVAPI_API_TOKEN
docker compose -f docker-compose.dev.yml up -d --build
```
