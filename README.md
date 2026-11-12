# checkIT

Сервіс для аудиту тендерних закупівель Prozorro. Автоматично порівнює позиції тендеру з ринковими цінами магазинів (Rozetka, Сільпо, Епіцентр), виявляє завищення та оцінює корупційні ризики за допомогою ШІ.

## Що вміє

- **Аналіз по ID Prozorro** — введіть ідентифікатор закупівлі, отримайте зведення позицій з ринковими цінами
- **Перевірка Excel-прайсів** — завантажте власний прайс-лист, система зіставить кожну позицію з ринком
- **Мультімагазинне порівняння** — Rozetka, Сільпо, Епіцентр, паралельний пошук
- **Ризик-аналіз** — відхилення цін, виявлення дискримінаційних вимог у специфікаціях (Claude / Gemini)
- **Експорт у XLSX** — готовий звіт для аудитора
- **Бейджі джерел ціни** — видно звідки взята ціна (тендер / ринок / оцінка)

## Стек

| Рівень | Технологія |
|--------|-----------|
| Frontend | Vue 3 + Vite + Pinia |
| Backend | FastAPI (Python 3.11) |
| База даних | PostgreSQL 16 |
| Кеш | Redis 7 |
| LLM (основний) | Anthropic Claude (haiku / sonnet) |
| LLM (резерв) | Google Gemini |
| Скрапери | BeautifulSoup + curl\_cffi |
| Контейнеризація | Docker Compose |

---

## Швидкий старт (Docker Compose)

### 1. Клонувати репозиторій

```bash
git clone <repo-url>
cd pyman
```

### 2. Налаштувати змінні середовища

```bash
cp .env.example .env
```

Відредагуйте `.env`:

```dotenv
# PostgreSQL
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_secure_password
POSTGRES_DB=check_it

# JWT (замініть на випадковий рядок у продакшені)
SECRET_KEY=your-super-secret-key-change-me

# Anthropic Claude — основний LLM (вмикає ШІ-функції)
ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_BASE_URL=https://api.anthropic.com   # змінити якщо використовується проксі
# ANTHROPIC_MODEL=claude-haiku-4-5               # швидка модель для валідації товарів
# ANTHROPIC_MODEL_SMART=claude-sonnet-4-6        # розумна модель для аналізу документів

# Google Gemini — резервний LLM (необов'язково)
GEMINI_API_KEY=

# Кеш Redis (необов'язково, за замовчуванням 2 години)
# CACHE_TTL_SECONDS=7200
```

> **Мінімум для запуску:** `POSTGRES_PASSWORD` та `SECRET_KEY`.  
> Без `ANTHROPIC_API_KEY` ШІ-функції (валідація відповідності товарів, ризик-аналіз) будуть вимкнені.

### 3. Запустити

```bash
docker compose up --build
```

Після старту:

| Сервіс | URL |
|--------|-----|
| Фронтенд | http://localhost |
| Backend API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |

### 4. Зареєструватися

Відкрийте http://localhost → **Розпочати** → зареєструйтеся та увійдіть.

---

## Локальна розробка (без Docker)

### Backend

```bash
cd back-end

# Створити virtualenv та встановити залежності
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt   # усі залежності з точними версіями (Python 3.12)

# Скопіювати та заповнити .env
cp .env.example .env
# Виправити DATABASE_URL і POSTGRES_HOST=localhost

# Запустити (PostgreSQL та Redis мають бути доступні)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd front-project

npm install
npm run dev
```

Фронтенд стартує на http://localhost:5173 та очікує API на http://localhost:8000.

---

## Структура проекту

```
pyman/
├── back-end/
│   ├── app/
│   │   ├── main.py                  # FastAPI застосунок, CORS, ініціалізація БД
│   │   ├── routers/
│   │   │   ├── authorization.py     # Реєстрація / логін (JWT)
│   │   │   ├── prozorro_router.py   # Аналіз закупівлі по ID Prozorro
│   │   │   ├── tender_router.py     # Управління збереженими тендерами
│   │   │   └── ai_assistant.py      # ШІ-асистент
│   │   ├── services/
│   │   │   ├── parser_service.py    # Оркестрація скраперів магазинів
│   │   │   ├── claude_validator.py  # LLM-валідація через Anthropic (з кешуванням)
│   │   │   ├── gemini_validator.py  # LLM-валідація через Gemini (резерв)
│   │   │   ├── llm_validator.py     # Загальний фасад LLM
│   │   │   ├── risk_analyzer.py     # Ризик-скоринг (ціни + дискримінаційні вимоги)
│   │   │   ├── tender_classifier.py # Класифікація типу тендеру
│   │   │   └── cache.py             # Redis-кеш результатів пошуку
│   │   ├── models/                  # SQLAlchemy-моделі
│   │   └── schemas/                 # Pydantic-схеми
│   ├── alembic/                     # Міграції БД
│   ├── Dockerfile
│   ├── requirements.in              # прямі залежності
│   └── requirements.txt             # усі залежності з версіями (генерується з .in)
├── scraper/
│   └── parsers/
│       ├── rozetka_parser.py
│       ├── silpo_parser.py
│       └── epicentr_parser.py
├── front-project/
│   ├── src/
│   │   ├── views/                   # Сторінки (Home, Prozorro, XPath, Tenders…)
│   │   └── components/              # UI-компоненти
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml
└── .env.example
```

---

## Змінні середовища

| Змінна | Обов'язкова | За замовчуванням | Опис |
|--------|:-----------:|-----------------|------|
| `POSTGRES_PASSWORD` | ✅ | — | Пароль PostgreSQL |
| `SECRET_KEY` | ✅ | — | Секрет для підпису JWT-токенів |
| `POSTGRES_USER` | | `postgres` | Користувач PostgreSQL |
| `POSTGRES_DB` | | `check_it` | Назва бази даних |
| `ANTHROPIC_API_KEY` | | — | API-ключ Claude (вмикає ШІ-функції) |
| `ANTHROPIC_BASE_URL` | | `https://api.anthropic.com` | Проксі для Anthropic |
| `ANTHROPIC_MODEL` | | `claude-haiku-4-5` | Модель для валідації товарів |
| `ANTHROPIC_MODEL_SMART` | | `claude-sonnet-4-6` | Модель для аналізу документів |
| `GEMINI_API_KEY` | | — | API-ключ Gemini (резервний LLM) |
| `REDIS_URL` | | `redis://redis:6379/0` | URL Redis |
| `CACHE_TTL_SECONDS` | | `7200` | TTL кешу пошуку в секундах |

---

## Excel-формат для перевірки прайсів

Файл `.xlsx` повинен мати перший рядок-заголовок з такими колонками:

| Назва товару | Кількість | Ціна | Сума |
|---|---|---|---|

Порожні рядки та рядки з некоректними числами пропускаються автоматично.

---

## Зупинити та прибрати

```bash
# Зупинити контейнери
docker compose down

# Видалити також дані БД
docker compose down -v
```
