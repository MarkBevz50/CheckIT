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
- **Після кожного етапу E1–E6 (і окремо після E1.10/E1.11):** `python eval/quality_report.py --stage "<мітка>" --mode replay` (`back-end\.venv\Scripts\python.exe`, з кореня репо, потрібні Postgres на :5433 і знімок `eval/snapshots/control/<дата>/`) і новий рядок у `eval/metrics/history.jsonl`; це частина критерію «готово» етапу. Порівняння між етапами лише в `--mode replay`, `--mode live` показує поточний ринок. Прапорці: `--stability` (3 прогони валідації 20 розмічених пар, коштує грошей), `--llm live` (усі запити до Claude справжні), `--budget` (стоп-кран, $1 за замовчуванням). Знімки не в git, історія метрик у git. У CI не запускаємо.
- **Крок, що змінює фронтенд,** готовий лише якщо змінений або новий екран працює на ширині 360 px без горизонтальної прокрутки сторінки, кнопки й посилання не менші за 44 px, модальні вікна на мобільних займають весь екран; точки переходу (breakpoints) задаються змінними в `front-project/src/assets/base.css`, а не числами в компонентах.
- Після кроку: поставити `[x]` у `PLAN/Plan.md` і додати 3–5 речень у `PLAN/DIPLOMA_NOTES.md`
  (що змінилось, чому, цифри до/після, якщо є).
- Якщо крок неможливо виконати так, як написано, — не імпровізувати мовчки: пояснити проблему
  і запропонувати правку кроку в плані.
- **Ніколи не комітити секрети.** Ключі лише в `.env` (він у `.gitignore`), у репо лише `.env.example`.
- Нові залежності — лише з поясненням, навіщо, і після підтвердження власника.
- Комміти й пуш — лише коли власник попросить (у межах узгодженого flow нижче). **Коміт і пуш лише після того, як повний набір тестів пройшов, окремою командою, не в одному ланцюжку з тестами** (ланцюжок через `;` комітить і при червоних тестах). Перед тестами з PostgreSQL перевірити, що Docker Desktop і база запущені (`docker compose ps`, `db` у стані healthy): із встановленою `TEST_DATABASE_URL` і вимкненою базою тести БД не пропускаються, а падають помилкою з'єднання.

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
- **Злиття і видалення гілки ніколи не в одному ланцюжку команд.** `gh pr merge` виконується окремо; потім `gh pr view <номер>` має показати `state: MERGED`; лише після цього, окремою командою, оновлюється `dev` і видаляється гілка (локальна й віддалена). Після будь-якої помилки чи тайм-ауту під час злиття (наприклад, 504 Gateway Timeout) зупинка і перевірка `gh pr view`: злиття могло відбутись. Гілка видаляється лише при `state: MERGED` (так закрився PR #15: код потрапив у `dev`, а PR отримав стан CLOSED).
- **Прямі коміти в `main` і `dev` заборонені, без винятків:** навіть дрібні правки документації й плану йдуть через гілку і pull request (`docs/назва` або `feature/…`). Захист гілок із обов'язковими перевірками CI вмикається після першого зеленого прогону окремим рішенням власника (E0.5b).

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
docker-compose.yml           db, redis, backend, frontend (розробка)
docker-compose.prod.yml      оверлей для staging/продакшну: лише Caddy назовні, healthcheck, ліміти пам'яті, ротація логів
Caddyfile                    автоматичний HTTPS для $DOMAIN (використовує docker-compose.prod.yml)
.env.staging.example         перелік змінних сервера без значень (реальний .env.staging лише на сервері, у .gitignore)
scripts/                     check_env_staging.py (перевірка .env.staging), check_sources.py (доступність магазинів з сервера)
docs/RUNBOOK.md              підготовка Ubuntu, перший деплой, оновлення, логи, зупинка, бекап
ruff.toml                    конфіг лінтера (E0.5b)
.github/workflows/ci.yml     CI: backend, frontend, gitleaks, docker-build
.gitleaksignore              відбитки історичних знахідок gitleaks (без значень секретів)
back-end/tools/              службові скрипти (check_coverage.py)
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
- Тест ізоляції користувачів (`tests/test_user_isolation.py`, E0.13) теж працює на реальному Postgres через `TEST_DATABASE_URL`: локально пропускається без неї, в CI її відсутність є помилкою. Інтеграційний тест міграцій пропускається без `TEST_DATABASE_URL` (порожня БД Postgres): `upgrade head`, `alembic check`, `downgrade base`. Приклад: `docker compose up -d db`, створити базу `check_it_test`, `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5433/check_it_test`.

## Staging і продакшн (E0.6)

Окремий оверлей, не змінює режим розробки: `docker compose --env-file .env.staging -f docker-compose.yml -f docker-compose.prod.yml up -d --build`. Назовні опубліковано лише Caddy (80/443), решта сервісів доступні тільки всередині мережі compose (опубліковані порти Docker обходять `ufw`, тому `ports:` до них додавати не можна). Паролі без дефолтів, healthcheck усіх сервісів, ліміти пам'яті (змінні `*_MEM_LIMIT`, типові значення для VPS на 4 ГБ), ротація логів. Потрібен Docker Compose не нижче 2.24 (тег `!reset`). Перед деплоєм: `python3 scripts/check_env_staging.py`; на новому сервері першим ділом `python3 scripts/check_sources.py`. Усі кроки: `docs/RUNBOOK.md`. Репетиція без сервера: окремий проєкт `-p pyman-stagingtest` з `DOMAIN=localhost` (внутрішній сертифікат Caddy), після неї `down` без `-v` і точкове видалення її томів за іменами (дозвіл власника потрібен щоразу).

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
  Запуск через pytest з `back-end`: `python -m pytest ../scraper/tests -m live` (живі), `-m "not live"` (їх виключає; так і в CI).
  9 застарілих тестів (`info_about_product`) пропущені до E2.2, `test_category_search` для Rozetka позначений `xfail(strict=True)` до E2.2.
  `python -m unittest discover -s scraper/tests -t .` (з кореня репо) запускає все без маркерів і, як і раніше, дає 1 failure + 9 errors.
- Фронтенд: `cd front-project && npm run test:unit -- --run` (vitest; тести в `src/**/__tests__/`). Лінт: `npm run lint`.
- **Лінтер:** `ruff check .` з кореня репо (конфіг `ruff.toml`, набір `E4,E7,E9,F`; `ruff` ставиться з `requirements-dev.txt`).
- **Перевірка покриття** (не нижче базової лінії `back-end/coverage_baseline.json`):
  ```powershell
  cd back-end
  .\.venv\Scripts\python.exe -m pytest tests ../scraper/tests -m "not live" --cov=app --cov-report=json:coverage.json
  .\.venv\Scripts\python.exe tools/check_coverage.py coverage.json            # --print-baseline показує поточні числа
  ```
  Базову лінію підвищують лише окремим комітом з числами з CI.
- **CI** (GitHub Actions, `.github/workflows/ci.yml`) на кожен pull request у `dev` і `main` та на push у них: `backend` (ruff, pytest з покриттям і перевіркою базової лінії, тест міграцій із Postgres), `frontend` (`eslint .` без `--fix`, vitest), `gitleaks` (нові коміти PR; на push уся історія; історичні знахідки лише відбитками в `.gitleaksignore`), `docker-build` (збірка образів без публікації, кеш buildx, `docker compose config -q`). Червоний CI означає, що PR не зливаємо. Нові знахідки gitleaks в `.gitleaksignore` не додавати без рішення власника.

## Змінні середовища

Усі змінні читає лише `back-end/app/core/config.py` (`Settings`, pydantic-settings); `os.getenv` в іншому місці
забороняє тест. Пріоритет: змінні процесу → `.env` у корені. **Єдиний файл конфігурації — кореневий `.env`** (його ж використовує Docker, E0.12). `back-end/.env` не читається: якщо він з'явиться, у лог при старті потрапить попередження з назвами його змінних (без значень), а сам файл треба видалити. Шаблон — `.env.example`.
Обов'язкові (без дефолтів, застосунок не стартує і називає відсутню змінну): `DATABASE_URL`, `SECRET_KEY`.
**Ключі LLM:** `ANTHROPIC_API_KEY` це власний ключ власника, призначений для застосунку (локально, на staging і в продакшні). `OPENROUTER_API_KEY` лише для скриптів у `eval/` (експерименти), **ніколи** в `Settings`, коді застосунку чи на staging (`.env.staging`).
У Docker `DATABASE_URL` збирає `docker-compose.yml` (хост `db`, порт 5432) і вона **завжди перекриває** значення з `.env` (перевірено `docker compose config`, тест у `test_env_file.py`). `DATABASE_URL` у кореневому `.env` (`…@localhost:5433/…`) потрібна **лише для локального `uvicorn`/alembic** без Docker; контейнер її не бачить.

| Змінна | Призначення |
| --- | --- |
| `DATABASE_URL` (`postgresql+asyncpg://…`) | **обов'язкова**, єдиний async engine в `database.py`, alembic |
| `SECRET_KEY` | **обов'язкова**, підпис JWT, без fallback; не менше 32 символів і не з опублікованих значень (застосунок не стартує, E0.11); згенерувати: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DB_ECHO` | логувати SQL (за замовчуванням `false`) |
| `ALGORITHM` (HS256), `FRONTEND_URL` | JWT, CORS |
| `ANTHROPIC_API_KEY` | Claude, ключ з platform.claude.com (завжди `api.anthropic.com`, роутера немає) |
| `LLM_FAST_MODEL` (claude-haiku-5-5), `LLM_SMART_MODEL` (claude-sonnet-5-5) | моделі Claude |
| `LLM_DOCUMENT_TIER` (`fast`/`smart`) | модель для аналізу документації; за замовчуванням fast |
| `LLM_THINKING_CLASSIFY/VALIDATE/EXTRACT/DOCUMENTS` (`disabled`/`between_tools`/`default`) | міркування Claude для кожної задачі окремо, не за назвою моделі: `disabled` для Haiku 5.5, `between_tools` для Sonnet 5.5 (він відхиляє `disabled`), `default` не надсилає параметр; за замовчуванням `disabled`; при `LLM_DOCUMENT_TIER=smart` для EXTRACT і DOCUMENTS ставити `between_tools` |
| `GEMINI_API_KEY`, `GEMINI_MODELS` | Gemini (резерв), ланцюжок моделей через кому |
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
- **Docker Desktop і його диск — на D:** (програма `D:\Docker\app`, віртуальний диск WSL `D:\Docker\wsl`). На C: його повертати не можна:
  за день він з'їв ~25 ГБ. Обсяг пам'яті WSL обмежує `C:\Users\<користувач>\.wslconfig` (`[wsl2]`, `memory=`).
- **Docker Desktop** не стартує автоматично після перезавантаження. `docker` має бути в PATH користувача; якщо термінал старий
  і команди `docker` не знаходить, його треба перезапустити.
- **`docker compose up --build` — лише для фінальної перевірки кроку.** Проміжні перевірки — `pytest` у `.venv`.
- **Прибирання після кожної Docker-перевірки:** `docker builder prune -f` і `docker image prune -f`. Після цього перевірити розмір
  `D:\Docker\wsl\disk\docker_data.vhdx` і вказати його у звіті; якщо він більший за 40 ГБ — повідомити власника.
- Томи compose іменовані: `pyman_postgres_data` (база) і `pyman_redis_data` (кеш Redis); безіменних томів `up` не створює.
- **Не передавати весь `.env` у `docker run --env-file`:** SDK Anthropic сам читає `ANTHROPIC_BASE_URL` зі середовища (старий URL роутера з `.env` перенаправив усі запити, «Connection error»). `docker compose` не використовує `env_file` і передає лише перелічені змінні (тест `test_env_file.py`); для запусків у контейнері поза compose (`eval/quality_report.py`) робити відфільтрований файл лише з потрібними змінними.
- **`wsl --shutdown` не виконувати, поки працює Docker Desktop:** команда зупиняє всі розподіли WSL, зокрема `docker-desktop`, тож двигун і контейнери падають, а перенаправлення портів після перезапуску може лишитись зламаним (порт 80 слухає, але не відповідає; допомагає `docker compose restart frontend`). Для перевірок у Linux запускати окремий розподіл командою `wsl -d Ubuntu -- ...` і нічого не вимикати.
- **Ніколи** не виконувати `docker volume prune`, `docker system prune --volumes` чи `docker compose down -v` без прямого дозволу власника
  (знищують дані БД).

## Конвенції

- Бекенд повністю async; блокувальні виклики (парсери на `requests`, OCR) зараз обгорнуті в `asyncio.to_thread`.
- Ціна позиції має `price_source`: `tender` | `market_estimate` | `manual` | `unknown`; `unknown` не йде в ризик-аналіз.
- Тип тендера: `product` | `service` | `work` | `mixed`; одна таблиця `tender_items` з nullable-полями під тип + `extra_data` JSON.
- У текстах інтерфейсу — «ознаки ризику», а не «корупція».
- Не коммітити `*.log`, тимчасові PDF (`prozorro_functionality/temp_pdf/`) та `.env`.
