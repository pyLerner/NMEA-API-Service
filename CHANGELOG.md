# Changelog

## v2-kalman-ecef

Спецификация: [plan/KALMAN-ECEF-PLAN.md](plan/KALMAN-ECEF-PLAN.md).

- Fusion-слой: GNRMC (истина) + gated Kalman CV в ENU + ECEFPOSVEL при паузах RMC.
- Online-выдача координат (по умолчанию 10 Гц); backfill не применяется.
- `[Navigation]` в главном TOML + профили в `etc/VehicleProfiles.toml` (`tram` / `bus` / `custom`).
- Столбец `quality` в SQLite и API (`GOOD` | `KF_ECEF` | `COAST` | `DEGRADED` | `LOST`).
- Рестарт serial при длительном отсутствии GNRMC без очистки кэша.
- Docker-образ: `navigator:2-kalman-ecef`; deploy bundle: `NavigatorDockerApp-KF-ECEF/`.

## v2-rawlog

- Секция `[Log]` в TOML: `LogDir`, `LogName`, `LogLevel`, `MaxLogs`, `MaxSize`, `LogRowNMEA`, `RowNMEA`.
- Опциональный сырой лог NMEA (`LogRowNMEA = yes`) — все строки с входа в отдельный файл с общей ротацией.
- `[Memory].ResidualCache` — после flush в кэше остаются новейшие записи; в БД уходит `CacheRecords - ResidualCache` старейших без дублирования.
- Docker-образ: `navigator:2-rawlog`.

Подробности деплоя: [docker/docker/Changelog](docker/docker/Changelog).
