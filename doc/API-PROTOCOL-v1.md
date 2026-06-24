# API-PROTOCOL-v1

Протокол HTTP API сервиса `NMEA-API-Service` версии `v1`.

## 1. Общие положения

- Базовый URL формируется из параметров `[API].Host` и `[API].HTTP_Port`.
- Формат обмена: `application/json`.
- Все эндпоинты требуют Bearer-аутентификацию.
- Текущий набор эндпоинтов:
  - `GET /LastCoords`
  - `GET /AllCoords`
  - `DELETE /DeleteRecord/{record_id}`

## 2. Аутентификация

### 2.1 Требование

В каждый запрос должен передаваться заголовок:

```http
Authorization: Bearer <token>
```

`<token>` должен совпадать со значением `[API].Token` в TOML-конфиге.

### 2.2 Ошибка авторизации

Если заголовок отсутствует, имеет неверный формат или токен не совпадает:

- HTTP статус: `401 Unauthorized`
- Пример ответа:

```json
{"detail":"Authorization header missing or invalid"}
```

или

```json
{"detail":"Unauthorized"}
```

## 3. Формат данных записи

API возвращает записи в формате (совместимость со старым контрактом):

- `record_id` (`integer`) — идентификатор записи; `0` если запись ещё не сброшена в БД.
- `time` (`string | null`) — ISO8601 UTC timestamp.
- `is_valid` (`"A" | "V" | null`) — валидность фикса.
- `latitude` (`number`) — широта в decimal degrees, **7** знаков после запятой; `null` в источнике → `0.0`.
- `lat_hemisphere` (`"N" | "S" | null`) — полушарие широты.
- `longitude` (`number`) — долгота в decimal degrees, **7** знаков после запятой; `null` в источнике → `0.0`.
- `lon_hemisphere` (`"E" | "W" | null`) — полушарие долготы.
- `speed` (`number`) — скорость **км/ч**, **1** знак после запятой; `null` в источнике → `0.0`.
- `direction` (`number`) — курс (градусы), **1** знак после запятой; `null` в источнике → `0.0`.
- `mode` (`"E" | "D" | "A" | "N" | null`) — режим.
- `satellites_count` (`integer`) — число спутников; `null` в источнике → `0`.
- `source` (`string | null`) — источник данных (`nmea` — RMC, `ecef` — ECEFPOSVEL).

## 4. Эндпоинты

## 4.1 GET /LastCoords

Возвращает последнюю запись из in-memory кэша.

### Запрос

```bash
curl -s \
  -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:7000/LastCoords"
```

### Успех (есть данные)

- HTTP статус: `200 OK`
- Пример:

```json
{
  "result": true,
  "record": {
    "record_id": 0,
    "time": "2026-04-10T10:15:00+00:00",
    "is_valid": "A",
    "latitude": 46.05123,
    "lat_hemisphere": "N",
    "longitude": 14.50678,
    "lon_hemisphere": "E",
    "speed": 0.8,
    "direction": 176.5,
    "mode": "A",
    "satellites_count": 9
  }
}
```

### Успех (данных нет)

- HTTP статус: `200 OK`
- Пример:

```json
{"result":false,"error":"no data"}
```

## 4.2 GET /AllCoords

Возвращает список записей с учетом `limit`.

Логика:
- сначала берутся записи из кэша (свежие, в порядке от новых к старым);
- если кэша недостаточно, недостающее количество добирается из SQLite.

### Параметры запроса

- `limit` (`integer`, optional, default `10`, range `1..1000`)

### Запрос

```bash
curl -s \
  -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:7000/AllCoords?limit=100"
```

### Успех

- HTTP статус: `200 OK`
- Пример:

```json
{
  "result": true,
  "count": 2,
  "data": [
    {
      "record_id": 0,
      "time": "2026-04-10T10:15:00+00:00",
      "is_valid": "A",
      "latitude": 46.05123,
      "lat_hemisphere": "N",
      "longitude": 14.50678,
      "lon_hemisphere": "E",
      "speed": 0.8,
      "direction": 176.5,
      "mode": "A",
      "satellites_count": 9
    },
    {
      "record_id": 124,
      "time": "2026-04-10T10:14:59+00:00",
      "is_valid": "A",
      "latitude": 46.05111,
      "lat_hemisphere": "N",
      "longitude": 14.50655,
      "lon_hemisphere": "E",
      "speed": 0.7,
      "direction": 175.9,
      "mode": "A",
      "satellites_count": 9
    }
  ]
}
```

### Ошибка валидации параметров

Если `limit` вне диапазона:
- HTTP статус: `422 Unprocessable Entity`
- формат ошибки стандартный для FastAPI.

## 4.3 DELETE /DeleteRecord/{record_id}

Удаляет запись по `record_id` (`key_id`) в SQLite.

Важно:
- операция влияет на БД;
- in-memory кэш этим эндпоинтом не очищается.

### Параметры пути

- `record_id` (`integer`, required)

### Запрос

```bash
curl -s -X DELETE \
  -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:7000/DeleteRecord/124"
```

### Успех (удалено)

- HTTP статус: `200 OK`

```json
{"result":true,"detail":"record 124 deleted"}
```

### Успех (не найдено)

- HTTP статус: `200 OK`

```json
{"result":false,"detail":"record 124 not found"}
```

### Внутренняя ошибка

- HTTP статус: `500 Internal Server Error`

```json
{"detail":"<error_text>"}
```

## 5. Коды ответа

- `200 OK` — успешная обработка запроса (включая сценарий `not found` для delete).
- `401 Unauthorized` — ошибка Bearer-аутентификации.
- `422 Unprocessable Entity` — неверные параметры запроса.
- `500 Internal Server Error` — внутренняя ошибка обработки.

## 6. Обратная совместимость и версионирование

Этот документ описывает контракт `v1`.

Правила:
- Минорные расширения допускаются без breaking changes (например, добавление новых полей в ответ).
- Изменение/удаление существующих полей или изменение semantics требует новой версии протокола (`v2`) и отдельного документа.
- До появления path-versioning текущие изменения версий фиксируются через отдельный файл спецификации (`API-PROTOCOL-vN.md`).
