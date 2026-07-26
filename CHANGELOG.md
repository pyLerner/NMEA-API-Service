# Changelog

## Deploy: `.terminal-id` и `.env` при `--copy-to-opt`

- `install-docker-from-tar.sh`: после rsync в `/opt/navigator` — интерактивный `terminal-id` (default из существующего файла); для отсутствующего/пустого `.env` — предложение создать из `.env.example` (`chmod 600`).
- `rsync --exclude`: `.env`, `.terminal-id`, `db/` не затираются.
- [docker/README-deploy.md](docker/README-deploy.md) обновлён.

## v2.3-qr-geo

Провайдер `qr` и управление справочником координат.

### QrGeo

- Отдельный SQLite `qr_geo` (`GeoDbPath`), RAM `QrGeoLookup`.
- `POST /api/qr-geo/v1/catalog:replace` и `catalog:append` (CSV/JSON, Bearer).
- `QrGeoAdapter`: SSE QR-reader → lookup → `PositionHub` с `source=qr`.
- Токен: `NAVAPI_API_TOKEN` (compose `.env`), fallback `[API].Token`.

### Документация

- [doc/API-PROTOCOL-v2.md](doc/API-PROTOCOL-v2.md) §6; [plan/04_QR-GEO-PROVIDER.md](plan/04_QR-GEO-PROVIDER.md).

## v2.2-multi-source-hub

Каркас нескольких источников навигации и API `/api/navigator/v2/`.

### Position Hub и провайдеры

- Пакет [`src/sources/`](src/sources/): `PositionHub`, `NavPositionEvent`, Protocol адаптера, factory.
- Общий поток (interleave): все включённые провайдеры пишут в один `RecordsCache`.
- NMEA вынесен в `NmeaSerialAdapter` (reader + fusion tick → Hub).
- Stubs (без публикации координат): `imu`, `triangulation-http` — при `Enabled=true` только warning «not implemented». Провайдер `qr-geo` реализован отдельно (см. v2.3).
- Составное поле `source` на всех API: `nmea/rmc`, `nmea/ecef`, `nmea/fusion`, а также `qr` / `imu` / `triangulation`.

### Конфигурация

- `[Hardware]` перенесён в `[Sources.nmea]` (`HardwarePort`, `Baud`).
- Секции `[Sources.qr-geo]`, `[Sources.imu]`, `[Sources.triangulation]` в шаблонах TOML.
- Legacy: если есть только `[Hardware]` без `[Sources.nmea]` — смапится во включённый nmea.
- `[API].SseKeepaliveSec` — интервал SSE ping (по умолчанию `15`).

### API

- `GET /api/navigator/v2/last-coords?provider=` — SSE: `data:` в формате тела v1/last-coords; при простое — `event: ping`.
- `GET /api/navigator/v2/all-coords?provider=&from=&to=` — до 1000 точек; все параметры опциональны.
- Фильтр `provider` — семейство `source` (сегмент до `/`).
- Пути `/api/navigator/v2/*` публичные (без Bearer), как `/v1/`.
- Legacy и `/api/navigator/v1/` без смены путей; в `source` — новый составной формат.

### Документация

- [doc/API-PROTOCOL-v2.md](doc/API-PROTOCOL-v2.md): Hub, `source`, SSE, all-coords filters, `[Sources.*]`.

## v2.1-kalman-fusion

Спецификация: [plan/KALMAN-ECEF-FUSION-v2.md](plan/KALMAN-ECEF-FUSION-v2.md).

### Fusion v2

- `PublishMode` в `[Navigation]`: `measurement` (default) | `timer` | `hybrid` — политика записи в кэш.
- Predict Kalman внутренний; по умолчанию публикация только при accept RMC/ECEF.
- Гейты RMC от последнего seen RMC (`dt ≥ 0.5` с), не от 10 Гц publish.
- Доверенный RMC (`is_valid=A`, `mode ∈ RmcTrustModes`) — hard reset при kinematic conflict.
- Standstill и обнуление скорости на стоянке в `ingest_rmc`.
- `speed`/`direction` в API: из RMC/ECEF при `GOOD`; не синтетический `_speed_course`.
- Reject недоверенного RMC → `nav-quality` `COAST`/`DEGRADED`.
- `VehicleProfiles`: `RmcSpeedZeroKmh`, `RmcTrustModes`.
- `[API].Workers = 1` (обязательно для согласованности in-memory кэша); warning при `Workers > 1`.

### Документация и конфигурация

- Подробные комментарии (UTF-8) в шапках `etc/gnrmc-provider.toml`, `docker/etc/navapiserv-config.toml`, `VehicleProfiles.toml`.
- [doc/API-PROTOCOL-v2.md](doc/API-PROTOCOL-v2.md): `PublishMode`, источник `speed`/`direction`, поведение `last-coords`.
- [README.md](README.md): секция `[Navigation]`, fusion v2, ссылка на спецификацию.
- Русскоязычные докстринги в модулях fusion, runner, config, API.

## v2-kalman-ecef

Спецификация: [plan/KALMAN-ECEF-PLAN.md](plan/KALMAN-ECEF-PLAN.md).

### Fusion и конфигурация

- Fusion-слой: GNRMC (истина) + gated Kalman CV в ENU + ECEFPOSVEL при паузах RMC.
- Online-выдача координат (по умолчанию 10 Гц); backfill не применяется.
- `[Navigation]` в главном TOML + профили в `etc/VehicleProfiles.toml` (`tram` / `bus` / `custom`).
- `SerialRestartAfterSec` — только в `[Navigation]` главного TOML (по умолчанию `90` с); убран из `VehicleProfiles.toml`.
- Столбец `quality` в SQLite и API (`GOOD` | `KF_ECEF` | `COAST` | `DEGRADED` | `LOST`, v2: `nav-quality`).
- Рестарт serial при длительном отсутствии GNRMC без очистки кэша.

### API (совместимость с Go-клиентом)

- Нормализация полей в ответах `LastCoords` / `AllCoords` (кэш и SQLite): [`src/api/record_format.py`](src/api/record_format.py).
- `record_id` — целое; `null` → `0`.
- `latitude` / `longitude` — 7 знаков после запятой.
- `speed` — км/ч, 1 знак после запятой; `direction` — 1 знак после запятой.
- `satellites_count` — целое; `null` → `0`.
- Документация: [doc/API-PROTOCOL-v1.md](doc/API-PROTOCOL-v1.md), [doc/API-PROTOCOL-v2.md](doc/API-PROTOCOL-v2.md).

### Docker / deploy

- Образ: `navigator:2-kalman-ecef`; bundle: `NavigatorDockerApp-KF-ECEF/`.
- `entrypoint.sh`: NDTP только для TOML с секцией `[NDTP]` (`VehicleProfiles.toml` не запускается как NDTP).
- `install-docker-from-tar.sh`: `docker compose up --pull never`; тег образа в compose подставляется из `docker load`.
- `docker-compose.yml`: `pull_policy: never` (offline deploy).
- `docker/etc/navapiserv-config.toml`: альтернативный serial (`ttyS3`/`9600`) в комментариях; `SerialRestartAfterSec = 90`.

### Исправления

- Startup-лог в `main.py`: format string для `Profile` и `OutputHz` (устранён `TypeError` в контейнере).

## v2-rawlog

- Секция `[Log]` в TOML: `LogDir`, `LogName`, `LogLevel`, `MaxLogs`, `MaxSize`, `LogRowNMEA`, `RowNMEA`.
- Опциональный сырой лог NMEA (`LogRowNMEA = yes`) — все строки с входа в отдельный файл с общей ротацией.
- `[Memory].ResidualCache` — после flush в кэше остаются новейшие записи; в БД уходит `CacheRecords - ResidualCache` старейших без дублирования.
- Docker-образ: `navigator:2-rawlog`.

Подробности деплоя: [docker/docker/Changelog](docker/docker/Changelog).
