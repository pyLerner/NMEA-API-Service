# Changelog

## v2-rawlog

- Секция `[Log]` в TOML: `LogDir`, `LogName`, `LogLevel`, `MaxLogs`, `MaxSize`, `LogRowNMEA`, `RowNMEA`.
- Опциональный сырой лог NMEA (`LogRowNMEA = yes`) — все строки с входа в отдельный файл с общей ротацией.
- `[Memory].ResidualCache` — после flush в кэше остаются новейшие записи; в БД уходит `CacheRecords - ResidualCache` старейших без дублирования.
- Docker-образ: `navigator:2-rawlog`.

Подробности деплоя: [docker/docker/Changelog](docker/docker/Changelog).
