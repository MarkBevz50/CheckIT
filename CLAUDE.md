# CheckIT

Система аналізу цін у тендерах Prozorro: імпортує тендер за UA-ID, шукає ринкові ціни в магазинах,
валідує збіги через LLM і рахує ознаки цінового ризику. Дипломний проєкт, ціль — продакшн за кілька місяців.
Стек: FastAPI (async SQLAlchemy + asyncpg) · Vue 3 (Vite, Pinia) · PostgreSQL 16 · Redis 7.

**Мова спілкування з власником — українська.**

## Правила роботи (обов'язкові)

План робіт: `PLAN/Plan.md` (етапи E0–E8). Нотатки для диплома: `PLAN/DIPLOMA_NOTES.md`.

- Працюємо строго за планом, **по одному кроку за раз**. Нічого з інших кроків не робити, навіть якщо
  це очевидно корисно. Таке записувати в розділ «Помічено» в кінці відповіді.
- **Перед зміною коду** показати план: які файли зміню, що додам, які ризики. Чекати «ок».
- Кожен крок — окрема гілка `feature/eX-Y-назва` від `dev` (наприклад `feature/e0-7-own-api-key`) і окремий pull request у `dev`.
- Кожен крок закінчується тестами. Запускати **весь** набір, не лише нові.
- Після кроку: поставити `[x]` у `PLAN/Plan.md` і додати 3–5 речень у `PLAN/DIPLOMA_NOTES.md`
  (що змінилось, чому, цифри до/після, якщо є).
- Якщо крок неможливо виконати так, як написано, — не імпровізувати мовчки: пояснити проблему
  і запропонувати правку кроку в плані.
- **Ніколи не комітити секрети.** Ключі лише в `.env` (він у `.gitignore`), у репо лише `.env.example`.
- Нові залежності — лише з поясненням, навіщо, і після підтвердження власника.
- Комміти й пуш — лише коли власник попросить (у межах узгодженого flow нижче).

## Git і гілки

Єдиний репозиторій: `origin` = https://github.com/MarkBevz50/CheckIT.git.
`old-origin` (mr-world-one/pyman) — застарілий, не використовувати.

Спрощений git flow:
- `main` — стабільна гілка, з неї йде продакшн. `dev` — інтеграційна гілка, з неї йде staging.
- Кроки: `feature/eX-Y-назва` від `dev`, злиття в `dev` лише через pull request (`gh pr create --base dev`).
- Pull request у `dev` зливаються **squash-ом**, гілку після злиття видаляємо.
- `dev` → `main` лише після закриття етапу, з тегом версії.
- Термінові виправлення: `hotfix/назва` від `main`, зливаються в `main` і в `dev`.
- Прямих комітів у `main` і `dev` немає (виняток: службові правки плану/документації, якщо власник дозволив).

## Структура

```
back-end/
  app/
    main.py                  FastAPI-застосунок, CORS, startup (init_db), POST /excel-page
    core/config.py           Settings (єдине місце читання змінних середовища)
    database.py              єдиний async engine, SessionLocal, Base, get_db
    db_test.py               перевірка підключення до БД на старті
    models/                  model.py (User), tender.py (Tender, TenderItem, PriceHistory)
    schemas/                 Pydantic-схеми
    routers/
      authorization.py       /auth/register, /auth/login, JWT, get_current_user
      tender_router.py       /tenders: CRUD, /import/{prozorro_id}, /{id}/analyze, /{id}/price-history
      prozorro_router.py     /stores/available, /search-tender/{id}, /analyze-documents/{ua_id}, UA→hex через Clarity Project
      ai_assistant.py        чат-помічник на Hugging Face (/perform-task) і /analyze-risks
      crud.py                /api/users (службове)
    services/
      llm_validator.py       фасад: Claude → резерв Gemini
      claude_validator.py    Anthropic SDK: валідація збігів, витяг позицій, аналіз документації
      gemini_validator.py    Gemini (резерв)
      parser_service.py      AVAILABLE_PARSERS, пошук по магазинах (asyncio.to_thread), _simplify_product_name, save_price_history
      risk_analyzer.py       відхилення ціни, вимоги документації, агрегований ризик
      tender_classifier.py   тип тендера: product/service/work/mixed (regex + LLM)
      cache.py               Redis-кеш (без REDIS_URL вимкнений)
    prozorro_functionality/  prozorro.py: Prozorro API, завантаження документів, OCR (ocrmypdf/tesseract), .doc→PDF (LibreOffice)
  alembic/                   міграції (зараз лише 001_add_price_history)
  Dockerfile                 збирається з КОРЕНЯ репо (context: .), бо копіює і scraper/
scraper/parsers/             RozetkaParser, SilpoParser, EpicentrParser (sync, requests), ProductInfo
scraper/tests/               unittest-тести парсерів (ходять у живу мережу)
front-project/               Vue 3 + Vite + Pinia (src/views, components, stores, api/config.js), nginx.conf, Dockerfile
host_prozorro.py             окремий застарілий скрипт у корені (не частина API)
docker-compose.yml           db, redis, backend, frontend
PLAN/                        план робіт
```

Кореневі `package.json`, `babel.config.js`, `vue.config.js`, `jsconfig.json`, `requirements.txt`, `*.log` —
залишки старого scaffold; реальний фронтенд у `front-project/`, реальні залежності бекенду в `back-end/requirements.txt`.

## Запуск

Усе разом (Docker, рекомендовано):
```bash
cp .env.example .env        # заповнити ключі
docker compose up --build   # фронт :80, API :8000 (/docs), postgres :5432, redis :6379
```

Бекенд локально (потрібні Postgres і, за бажання, Redis; `PYTHONPATH` має містити корінь репо і `back-end`):
```bash
cd back-end
pip install -r requirements.txt     # у Dockerfile частина пакетів ставиться окремо (anthropic, google-generativeai, redis, pandas, openpyxl, PyMuPDF, ocrmypdf, asyncpg)
PYTHONPATH=..:. uvicorn app.main:app --reload --port 8000
```
Для OCR та .doc потрібні системні tesseract (ukr, eng) і libreoffice-writer.

Фронтенд: `cd front-project && npm install && npm run dev` (Vite, :5173; `VITE_API_URL`, за замовчуванням `http://localhost:8000`).

Міграції: `cd back-end && alembic upgrade head` (`DATABASE_URL` береться з `.env`).
**Увага:** схема зараз створюється через `Base.metadata.create_all` + `ALTER TABLE` у `startup`,
а єдина міграція створює лише `price_history` — повноцінні міграції це крок E0.3.

## Тести

- Бекенд: `cd back-end && pip install -r requirements-dev.txt && python -m pytest` (зараз лише тести `Settings`; решта — крок E0.2). Без мережі й без БД. `app/db_test.py` — не тест, а перевірка підключення.
- `scraper/tests/` — unittest, **потребують живої мережі** і можуть падати при зміні розмітки магазинів:
  `python -m unittest discover -s scraper/tests -t .` (з кореня репо).
- Фронтенд: `cd front-project && npm run test:unit` (vitest налаштований, тестових файлів немає). Лінт: `npm run lint`.
- CI відсутній (крок E0.5).

## Змінні середовища

Усі змінні читає лише `back-end/app/core/config.py` (`Settings`, pydantic-settings); `os.getenv` в іншому місці
забороняє тест. Порядок: змінні процесу → `.env` у корені → `back-end/.env`. Шаблон — `.env.example`.
Обов'язкові (без дефолтів, застосунок не стартує і називає відсутню змінну): `DATABASE_URL`, `SECRET_KEY`.
У Docker `DATABASE_URL` збирає `docker-compose.yml`; локально без Docker її треба додати в `.env`.

| Змінна | Призначення |
| --- | --- |
| `DATABASE_URL` (`postgresql+asyncpg://…`) | **обов'язкова**, єдиний async engine в `database.py`, alembic |
| `SECRET_KEY` | **обов'язкова**, підпис JWT, без fallback |
| `DB_ECHO` | логувати SQL (за замовчуванням `false`) |
| `ALGORITHM` (HS256), `FRONTEND_URL` | JWT, CORS |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`, `ANTHROPIC_MODEL_SMART` | Claude (дефолти моделей застарілі, оновить E0.7) |
| `GEMINI_API_KEY`, `GEMINI_MODELS` | Gemini (резерв) |
| `HUGGINGFACE_API_KEY` | чат-помічник (буде видалено в E6.6) |
| `REDIS_URL`, `CACHE_TTL_SECONDS` (7200) | кеш; без `REDIS_URL` вимкнений |
| `POSTGRES_USER/PASSWORD/DB` | лише для контейнера `db` у compose, не для коду |
| `VITE_API_URL` | фронтенд (`front-project/src/api/config.js`, у `.env.production` — `/api`) |

## Конвенції

- Бекенд повністю async; блокувальні виклики (парсери на `requests`, OCR) зараз обгорнуті в `asyncio.to_thread`.
- Ціна позиції має `price_source`: `tender` | `market_estimate` | `manual` | `unknown`; `unknown` не йде в ризик-аналіз.
- Тип тендера: `product` | `service` | `work` | `mixed`; одна таблиця `tender_items` з nullable-полями під тип + `extra_data` JSON.
- У текстах інтерфейсу — «ознаки ризику», а не «корупція».
- Не коммітити `*.log`, тимчасові PDF (`prozorro_functionality/temp_pdf/`) та `.env`.
