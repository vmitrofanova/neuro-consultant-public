# Catalog Sync API

Backend на FastAPI для импорта каталога товаров из API поставщика. Демо-поставщик поднимается отдельным процессом и отдаёт два вымышленных товара. Backend обращается к нему по HTTP, проверяет ответ и сохраняет товары. В профиле Compose используется PostgreSQL, а задания можно отправлять в RabbitMQ отдельному воркеру.

## Стек Docker Compose

```bash
docker compose up --build -d
curl -fsS http://127.0.0.1:8000/ready
curl -fsS -X POST http://127.0.0.1:8000/sync/jobs
docker compose logs --tail 20 worker
curl -fsS http://127.0.0.1:8000/products
```

`/ready` вернёт `200`, когда Redis, RabbitMQ, MongoDB, PostgreSQL, Weaviate и демо-LLM готовы. После публикации задания API возвращает `202` с `task_id`. Воркер записывает товары в PostgreSQL и подтверждает сообщение. Запрос списка товаров покажет их после завершения задания.

Интерфейсы доступны локально. [Swagger UI](http://127.0.0.1:8000/docs), [Prometheus](http://127.0.0.1:9090/targets), [Grafana](http://127.0.0.1:3000). Переменные `DEMO_API_PORT`, `DEMO_PROMETHEUS_PORT` и `DEMO_GRAFANA_PORT` задают порты на хосте.

Контракты хранилищ, очереди, наблюдаемости и внешних API перечислены отдельно. [Инфраструктура](docs/infrastructure.md).

## Быстрый запуск с SQLite

Понадобятся Python 3.11+ и `uv`. Выполните команды из корня репозитория.

```bash
uv sync --locked
```

Запустите поставщика и backend в двух терминалах. В примере поставщик проверяет тестовый bearer-токен, который backend отправляет в HTTP-заголовке.

```bash
SUPPLIER_TOKEN=local-demo uv run --locked uvicorn app.demo_supplier:app --port 8001
```

```bash
SUPPLIER_TOKEN=local-demo uv run --locked uvicorn app.main:create_app --factory --port 8000
```

Откройте [Swagger UI](http://127.0.0.1:8000/docs) или выполните запросы в терминале.

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS -X POST http://127.0.0.1:8000/sync
curl -fsS http://127.0.0.1:8000/products
```

## Поведение

- `POST /sync` получает товары через `GET /v1/products` поставщика. Его поля `code`, `title` и `amount` преобразуются в `sku`, `name` и `price_cents`.
- Импорт проверяет все записи до сохранения. Одна транзакция добавляет новые SKU и обновляет существующие. Повторный импорт тех же данных даёт тот же каталог. Товары, пропущенные в очередном ответе, остаются в каталоге.
- При тайм-ауте backend отдаёт `504`. Ошибка запроса к поставщику или некорректные данные дают `502`. В обоих случаях прежний каталог сохраняется.
- `GET /products` читает сохранённый каталог из выбранной БД. Поле `processed` в ответе синхронного импорта показывает число записей в ответе поставщика.

| Переменная | Назначение | Значение по умолчанию |
| --- | --- | --- |
| `SUPPLIER_URL` | Базовый URL API поставщика | `http://127.0.0.1:8001` |
| `SUPPLIER_TOKEN` | Bearer-токен для запроса к поставщику | Пусто |
| `DATABASE_PATH` | Путь к SQLite | `data/catalog.sqlite3` |
| `POSTGRES_DSN` | DSN для хранения каталога в PostgreSQL | Пусто |

## Код и тесты

- `app/main.py` содержит HTTP-маршруты и настройку зависимостей.
- `app/supplier.py` содержит HTTP-клиент и преобразование ответа поставщика.
- `app/catalog.py` содержит модель товара и адаптеры SQLite и PostgreSQL.
- `app/queue.py` и `app/worker.py` содержат публикацию и обработку заданий RabbitMQ.

```bash
uv run --locked pytest -q
uv run --locked ruff check .
```

Тесты подменяют транспорт HTTP-клиента и используют временную SQLite. Они проверяют токен в исходящем запросе, повторную синхронизацию, сохранение данных после перезапуска приложения и ошибки поставщика.
