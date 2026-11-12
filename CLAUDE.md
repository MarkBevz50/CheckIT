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
- **Видалення гілок:** перед видаленням гілки перевірити стан PR через `gh pr view <номер>` (потрібен `state: MERGED`). Гілку відкритого PR не видаляти ніколи: GitHub закриває PR.
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
      authorization.py       /auth/register, /auth/login (префікс /auth задано лише в роутері), JWT, get_current_user
      tender_router.py       /tenders: CRUD, /import/{prozorro_id}, /{id}/analyze, /{id}/price-history
      prozorro_router.py     /stores/available, /search-tender/{id}, /analyze-documents/{ua_id}, UA→hex через Clarity Project
      ai_assistant.py        чат-помічник на Hugging Face (/perform-task) і /analyze-risks
    services/
      llm_validator.py       фасад: Claude → резерв Gemini
      claude_validator.py    Anthropic SDK: валідація збігів, витяг позицій, аналіз документації
      gemini_validator.py    Gemini (резерв)
      parser_service.py      AVAILABLE_PARSERS, пошук по магазинах (asyncio.to_thread), _simplify_product_name, save_price_history
      risk_analyzer.py       відхилення ціни, вимоги документації, агрегований ризик
      tender_classifier.py   тип тендера: product/service/work/mixed (regex + LLM)
      cache.py               Redis-кеш (без REDIS_URL вимкнений)
    prozorro_functionality/  prozorro.py: Prozorro API, завантаження документів, OCR (ocrmypdf/tesseract), .doc→PDF (LibreOffice)
  alembic/                   міграції Alembic (versions/0001_baseline.py: users, tenders, tender_items, price_history)
  Dockerfile                 збирається з КОРЕНЯ репо (context: .), бо копіює і scraper/
scraper/parsers/             RozetkaParser, SilpoParser, EpicentrParser (sync, requests), ProductInfo
scraper/tests/               unittest-тести парсерів (ходять у живу мережу)
front-project/               Vue 3 + Vite + Pinia (src/views, components, stores, api/config.js), nginx.conf, Dockerfile
docker-compose.yml           db, redis, backend, frontend
PLAN/                        план робіт
```

Залежності бекенду: `back-end/requirements.in` (прямі, без версій) і згенерований з нього `back-end/requirements.txt` (усе з точними версіями, Python 3.12; Dockerfile ставить лише його). Оновлення: інструкція в шапці `requirements.in`.

## Запуск

Усе разом (Docker, рекомендовано):
```bash
cp .env.example .env        # заповнити ключі
docker compose up --build   # фронт :80, API :8000 (/docs), postgres :5433 (хост) → 5432 (контейнер), redis :6379
```

Бекенд локально (потрібні Postgres і, за бажання, Redis; `PYTHONPATH` має містити корінь репо і `back-end`):
```bash
cd back-end
pip install -r requirements.txt     # усі залежності, зафіксовані
PYTHONPATH=..:. uvicorn app.main:app --reload --port 8000
```
Для OCR та .doc потрібні системні tesseract (ukr, eng), ghostscript і libreoffice-writer (у Docker-образі вони є).
Локально Postgres із compose слухає порт **5433** на хості (`DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/check_it`); порт 5432 на Windows може займати локальна служба PostgreSQL, тому compose його не публікує.

Фронтенд: `cd front-project && npm install && npm run dev` (Vite, :5173; `VITE_API_URL`, за замовчуванням `http://localhost:8000`).

Міграції (схема змінюється лише через Alembic, застосунок її не створює):
- У Docker бекенд сам виконує `alembic upgrade head` перед стартом (`CMD` у `back-end/Dockerfile`).
- Нова міграція: змінити модель, далі `alembic revision --autogenerate -m "опис"` у `back-end` (потрібен доступний Postgres, `DATABASE_URL` з `.env`), перевірити згенерований файл, `alembic check` не має знаходити розбіжностей.
  З хоста Postgres із compose доступний на `localhost:5433` (див. «Запуск»).
- Назви обмежень і індексів задає `NAMING_CONVENTION` у `app/database.py` (ix, uq, ck, fk, pk).
- База, створена до E0.3 через `create_all` (без `alembic_version`), позначається один раз: `alembic stamp head` (у Docker: `docker compose run --rm backend alembic stamp head`). Порожню базу достатньо запустити.
- Інтеграційний тест міграцій пропускається без `TEST_DATABASE_URL` (порожня БД Postgres): `upgrade head`, `alembic check`, `downgrade base`. Приклад: `docker compose up -d db`, створити базу `check_it_test`, `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5433/check_it_test`.

## Тести

- Бекенд (у віртуальному середовищі `back-end/.venv`, воно в `.gitignore`; системний Python не чіпати). Windows PowerShell:
  ```powershell
  cd back-end
  python -m venv .venv                      # один раз
  .\.venv\Scripts\Activate.ps1             # активація (якщо заборонено скрипти: Set-ExecutionPolicy -Scope Process Bypass)
  pip install -r requirements-dev.txt       # усі залежності + pytest, більше нічого ставити не треба
  python -m pytest                          # або без активації: .\.venv\Scripts\python.exe -m pytest
  ```
  Без мережі й без БД: `conftest.py` ставить фіктивні `DATABASE_URL` і `SECRET_KEY`, вимикає ключі LLM і Redis та забороняє з'єднання з будь-яким хостом, окрім loopback. Записані відповіді Prozorro і магазинів лежать у `tests/fixtures/` (оновлення: `python back-end/tests/fixtures/record_fixtures.py` з кореня, потрібна мережа).
  Покриття: `python -m pytest --cov=app --cov-report=term`; для модулів, що не переписуються в E1–E2 (див. E0.2 у плані):
  `python -m pytest --cov=app.core --cov=app.database --cov=app.models --cov=app.schemas --cov=app.routers.authorization --cov=app.services.cache --cov=app.services.llm_validator --cov=app.services.risk_analyzer --cov=app.services.tender_classifier`. `app/db_test.py` — не тест, а перевірка підключення. Тести: налаштування, авторизація, імпорт тендера, ризик-аналіз, класифікатор, кеш, розбір відповідей LLM, скрапери на записаних відповідях.
- `scraper/tests/` — unittest-класи, **потребують живої мережі**; `scraper/tests/conftest.py` ставить їм маркер `live`.
  Запуск через pytest з `back-end`: `python -m pytest ../scraper/tests -m live` (живі), `-m "not live"` (їх виключає; так буде в CI).
  9 застарілих тестів (`info_about_product`) пропущені до E2.2, `test_category_search` для Rozetka позначений `xfail(strict=True)` до E2.2.
  `python -m unittest discover -s scraper/tests -t .` (з кореня репо) запускає все без маркерів і, як і раніше, дає 1 failure + 9 errors.
- Фронтенд: `cd front-project && npm run test:unit -- --run` (vitest; тести в `src/**/__tests__/`). Лінт: `npm run lint`.
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

## Пастки середовища

- **PowerShell 5.1 і BOM.** `Set-Content -Encoding utf8` (і `Out-File -Encoding utf8`) пишуть файл з BOM, що ламає TOML, JSON та інші
  формати (так зламався `pyproject.toml`). Файли створювати й редагувати інструментами для файлів (Write/Edit). Якщо без PowerShell
  не обійтись: `[System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))` (UTF-8 без BOM).
- **Heredoc у PowerShell.** `python - <<'EOF'` у PowerShell не працює (парсер падає, і не виконується нічого). Скрипти на Python запускати
  через Bash-інструмент або зберігати у файл.
- **Docker Desktop** не стартує автоматично після перезавантаження; `docker` може бути поза PATH у поточному терміналі
  (`C:\Program Files\Docker\Docker\resources\bin`).

## Конвенції

- Бекенд повністю async; блокувальні виклики (парсери на `requests`, OCR) зараз обгорнуті в `asyncio.to_thread`.
- Ціна позиції має `price_source`: `tender` | `market_estimate` | `manual` | `unknown`; `unknown` не йде в ризик-аналіз.
- Тип тендера: `product` | `service` | `work` | `mixed`; одна таблиця `tender_items` з nullable-полями під тип + `extra_data` JSON.
- У текстах інтерфейсу — «ознаки ризику», а не «корупція».
- Не коммітити `*.log`, тимчасові PDF (`prozorro_functionality/temp_pdf/`) та `.env`.
