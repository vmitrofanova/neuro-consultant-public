# Контракты инфраструктуры

Все адреса, схемы данных и учётные записи в Compose предназначены для локального демонстрационного окружения. Сервисы внутри сети Compose обращаются друг к другу по DNS-именам.

## Подключения

| Сервис | Протокол и конфигурация | Что можно проверить в демо |
| --- | --- | --- |
| FastAPI | HTTP, `GET /system/healthcheck` для liveness, `GET /ready` для readiness | OpenAPI на `/docs` и реальный HTTP-запрос поставщику |
| Redis | RESP на порту 6379, `REDIS_URL`. Атомарный счётчик с TTL для фиксированного окна лимита | `POST /sync/jobs` возвращает `429` и `Retry-After` после исчерпания лимита для IP |
| RabbitMQ | AMQP 0-9-1 на порту 5672, `RABBITMQ_URL`. Durable-очередь `catalog.sync`, JSON в теле, persistent delivery, явное подтверждение | `POST /sync/jobs` публикует задание. Воркер подтверждает его после записи в БД |
| MongoDB | MongoDB Wire Protocol и BSON на порту 27017, `MONGO_URI`. Граница документного хранилища для контекста аккаунта, сессий, сообщений и авторизации | Подключение и `ping` через PyMongo |
| PostgreSQL | PostgreSQL Wire Protocol на порту 5432, `POSTGRES_DSN`. Таблицы `products` и `sync_jobs` | Каталог и статусы доступны через API. Воркер сохраняет результат и статус в одной транзакции |
| Weaviate | HTTP REST на порту 8080 и gRPC на порту 50051. `WEAVIATE_HOST`, `WEAVIATE_REST_PORT`, `WEAVIATE_GRPC_PORT`. Граница векторного хранилища для коллекций, импорта объектов и поиска | Подключение официальным клиентом с проверкой обоих транспортов |
| Prometheus и Grafana | Prometheus scrapes `/metrics` у backend, RabbitMQ и экспортёров Redis и MongoDB. Grafana подключается к HTTP API Prometheus | Метрики FastAPI и состояние scrape-целей |
| Локальная LLM | OpenAI-совместимый JSON/HTTP. `GET /health` и `POST /v1/chat/completions` | Локальный сервер отдаёт фиксированный ответ, принимает текстовые сообщения. URL healthcheck указывается в `LLM_HEALTH_URL` |

Сообщение задания содержит `task_id` в формате UUID. Тип AMQP-сообщения — `catalog.sync`. API возвращает `202` после подтверждения публикации брокером и фиксации записи задания. В PostgreSQL воркер ждёт фиксации этой записи, прежде чем менять статус.

При ошибке поставщика воркер фиксирует `failed` и отклоняет сообщение без повторной постановки. Оно попадает в `catalog.sync.failed`, как и некорректное сообщение. Если соединение прервётся раньше подтверждения, RabbitMQ может доставить задание повторно. Воркер возобновляет `running` и подтверждает повторную доставку `succeeded` без нового импорта.

## Внешние API

| Интеграция | Контракт на границе приложения | Реализация в демо |
| --- | --- | --- |
| HTTP-поставщик | Bearer-авторизация и JSON. Получение списка записей, отдельные операции входа и обновления токена | Локальный поставщик и рабочий HTTP-клиент для импорта. Вход и обновление токена описаны интерфейсом `PartnerIdentity` |
| Telegram Bot API | JSON Update через `POST /webhook/telegram/`, исходящая отправка сообщения по ID чата | Модель `TelegramUpdate` и интерфейс `TelegramGateway` |
| YooKassa | HTTP/JSON для создания платежа с ключом идемпотентности, проверки статуса и приёма уведомлений на `POST /webhook/yookassa` | Модели заказа, платежа и уведомления, интерфейс `PaymentGateway` |
| Notisend | HTTP/JSON для отправки письма с bearer-токеном и идентификатором в ответе | Модель `Email` и интерфейс `MailGateway` |
| OpenAI и совместимый сервер | HTTP/JSON Chat Completions. Ролевые сообщения и текстовый ответ | Модель `ChatRequest` и отдельный локальный сервер |
| GigaChat | API с авторизацией для генерации текста, мультимодального ввода и эмбеддингов | Интерфейсы `CompletionGateway`, `MediaCompletionGateway` и `EmbeddingGateway` |
| Yandex Foundation Models | HTTP/JSON с bearer-токеном и ID каталога. Операции `completion` и `textEmbedding` | Интерфейсы `CompletionGateway` и `EmbeddingGateway` |

Модели и интерфейсы внешних интеграций находятся в `app/external_contracts.py`. HTTP-адаптеры для Telegram, платежей, почты и облачных LLM в демо не подключены.
