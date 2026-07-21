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

3. Отредактировать конфиги:

```bash
sudo nano /opt/navigator/etc/navapiserv-config.toml
sudo nano /opt/navigator/etc/ndtp-client.toml
```

4. Перезапустить:

```bash
cd /opt/navigator && sudo docker compose up -d --no-build
```

## Структура на host

```
/opt/navigator/
  docker-compose.yml
  etc/          → /etc/navigator (ro)
  db/           → /db (rw)
  log/          → /log (rw)
```

## Структура внутри контейнера

```
/app/                     # WORKDIR
/bin/naviapiserv.bin
/bin/NDTP_Client
/bin/NDTPClient           # symlink
/etc/navigator/*.toml
/db/
/log/
```

## Локальная dev-сборка на плате

```bash
cd docker
docker compose -f docker-compose.dev.yml up -d --build
```
