# eval: контрольні тендери і пілот OpenRouter

Усе тут запускається з кореня репо інтерпретатором `back-end\.venv\Scripts\python.exe`.
Якщо консоль показує кракозябри: `$env:PYTHONIOENCODING="utf-8"`.

## Файли

| Файл | Призначення |
| --- | --- |
| `control_tenders.json` | 10 контрольних тендерів (C01–C10) |
| `find_control_tenders.py` | пошук кандидатів у контрольні тендери через Prozorro |
| `collect_candidates.py` | для кожної позиції тендерів шукає товари парсерами магазинів (без LLM, потрібна мережа) |
| `data/candidates.jsonl` | усі знайдені кандидати (у git) |
| `build_pairs.py` | з кандидатів будує `data/pairs_pilot.jsonl` (60 пар, відбір зафіксовано в скрипті, без мережі) |
| `data/pairs_pilot.jsonl` | пари для розмітки (у git) |
| `label_pairs.py` | консольна розмітка пар (1 same / 2 analog / 3 no) і типів позицій (1 product / 2 service / 3 work) |
| `data/labels.json` | розмітка (v2, після виправлень), прогрес зберігається після кожної відповіді |
| `data/labels_v1.json`, `data/labels_changelog.md` | перший прохід розмітки і журнал 14 виправлень |
| `find_classification_items.py` | добирає з Prozorro 10 робіт (CPV 45*) і 10 послуг (CPV 50*–98*) для задачі класифікації |
| `data/classification_items.json` | ці 20 позицій з мітками (у git) |
| `build_router_questions.py`, `data/router_questions.json` | 18 питань «чи продається позиція в мережі X» з еталоном і підставою |
| `openrouter_pilot.py` | сам пілот: 10 моделей × 4 набори запитів (валідація, класифікація, роутер з описом мереж і без) |
| `results/pilot_summary.md` | зведення пілоту (у git); сирі відповіді в `results/pilot/` не в git |

Тип тендера `mixed` не розмічається: його обчислює код з типів позицій.

**Правило розмітки типу позиції (класифікація):** мітка береться з розділу CPV позиції, а не з тексту. 03–44 → `product`, 45 → `work`, 50–98 → `service`.
Тому «Послуга з поточного ремонту…» з CPV 45* має мітку `work`, а така сама за формулюванням з CPV 50* — `service`.
Усі 66 позицій контрольних тендерів — `product` (CPV 15*, 22*, 30*, 39*, 42*, 44*).

## `data/raw_store/` локальний

Сирі відповіді магазинів (≈100 МБ, по файлу на пару «позиція + магазин») у git **не додаються** (є в `.gitignore`).
Для повторного запуску пілоту вони не потрібні: пілот читає лише `pairs_pilot.jsonl` і `labels.json`.
Відтворити (потрібна мережа, ≈10 хвилин, магазини можуть віддати інші товари, ніж у `candidates.jsonl`):

```powershell
back-end\.venv\Scripts\python.exe eval\collect_candidates.py
```

Скрипт перезапише `data/candidates.jsonl`. Щоб не втратити зафіксований набір, перед відтворенням закомітьте або
скопіюйте поточний `candidates.jsonl`. Пари в `pairs_pilot.jsonl` після цього лишаються, бо містять копію тексту
товару, а не посилання на кандидата.

## Розмітка

```powershell
back-end\.venv\Scripts\python.exe eval\label_pairs.py          # типи позицій, потім пари
back-end\.venv\Scripts\python.exe eval\label_pairs.py --pairs  # лише пари
back-end\.venv\Scripts\python.exe eval\label_pairs.py --items  # лише типи позицій
back-end\.venv\Scripts\python.exe eval\label_pairs.py --stats  # прогрес
```
Клавіші: `s` пропустити (повернеться наприкінці й у наступному запуску), `b` назад, `q` вихід.

## `eval/snapshots/` локальний, без терміну зберігання

Тут зберігаються знімки, на яких зроблено висновки диплома: сирі відповіді Prozorro (JSON тендера і завантажені документи) для 10 контрольних тендерів та сирі відповіді джерел і моделей усіх експериментів диплома. Тендери в Prozorro і ціни в магазинах змінюються, тому порівняння роблять на знімках, а не на живих даних. Каталог у `.gitignore` (у git не додається) і **не має терміну зберігання**: його не чистять ні після аналізів, ні після захисту. Це окремо від політики знімків продакшну (90 днів, крок E6.11 плану).

Структура:

```
eval/snapshots/
  control_tenders/<C01…C10>/tender.json, documents/…
  experiments/<назва>/<дата>/…      сирі відповіді експерименту + файл README.txt (команда, дата, хеш коміту)
```
Знімок не перезаписують: нова версія йде в новий підкаталог з датою.

Як відтворити:
1. **Контрольні тендери.** Знімок створює крок E0.7 першим прогоном на 10 тендерах (скрипт з'явиться в цьому кроці). Вручну: `GET https://public.api.openprocurement.org/api/2.5/tenders/<hex_id>` (`hex_id` лежить у `eval/control_tenders.json`) зберегти в `tender.json`, а документи завантажити за `data.documents[].url`. Тендер міг змінитися після відбору (відбір 12 листопада 2026), тому живий запит може дати інші дані: зберігайте знімок одразу.
2. **Експерименти.** Кожен експеримент пише сирі відповіді в `experiments/<назва>/<дата>/` і описує команду у своєму розділі цього README. Уже проведений пілот OpenRouter скопійовано (копія, не переміщення) в `experiments/openrouter_pilot/2026-11-23/`: `pilot/` (відповіді моделей), `raw_store/` (відповіді магазинів) і `README.txt` з командою. Зведення відновлюється з копії без мережі й ключа: `openrouter_pilot.py --summarize --raw-dir <копія>/pilot --summary-out <файл>` (перевірено: збігається з `eval/results/pilot_summary.md`, крім рядка з часом). Оригінали в `eval/results/pilot/` і `eval/data/raw_store/` лишаються на місці. Повторний запуск `openrouter_pilot.py` дасть інші відповіді (моделі не детерміновані, ціни й версії моделей змінюються), тож з нуля відтворити їх неможливо: тримайте копію.
3. **Резервна копія.** Каталог поза git, тому робіть архів і зберігайте його на іншому диску.

## Пілот OpenRouter

Ключ `OPENROUTER_API_KEY` лежить лише в `.env` (або в змінній середовища), він чужий і тільки для експериментів: скрипт читає його сам,
нікуди не друкує й не пише в результати, у `Settings` і код застосунку він не потрапляє.

```powershell
back-end\.venv\Scripts\python.exe eval\openrouter_pilot.py --dry-run      # оцінка викликів і вартості, чат-запитів немає
back-end\.venv\Scripts\python.exe eval\openrouter_pilot.py --models anthropic/claude-haiku-5.5 --limit 3 --budget 0.1   # димовий тест
back-end\.venv\Scripts\python.exe eval\openrouter_pilot.py --budget 2     # повний прогін (стоп-кран: зупиняється перед викликом, що перевищить бюджет)
back-end\.venv\Scripts\python.exe eval\openrouter_pilot.py --summarize    # перебудувати eval/results/pilot_summary.md
back-end\.venv\Scripts\python.exe eval\openrouter_pilot.py --summarize --raw-dir <каталог з відповідями> --summary-out <файл>   # те саме з копії зі знімків
back-end\.venv\Scripts\python.exe eval\openrouter_pilot.py --export-haiku-fixtures   # відповіді Haiku 5.5 як фікстури тестів розбору JSON
```
Прогін відновлюваний: завершені виклики пропускаються. Дорогі моделі стоять у списку останніми, щоб стоп-кран відсікав саме їх.
Промпти валідації й класифікації імпортуються із застосунку (`claude_validator`, `tender_classifier`), не копіюються.

### Провайдер Anthropic напряму

Якщо під рукою ключ Anthropic (`sk-ant-…`), а не OpenRouter (`sk-or-…`), можна прогнати лише Haiku 5.5 і Sonnet 5.5 напряму через Anthropic API:
```powershell
back-end\.venv\Scripts\python.exe eval\openrouter_pilot.py --provider anthropic --dry-run
back-end\.venv\Scripts\python.exe eval\openrouter_pilot.py --provider anthropic --models anthropic-api/claude-haiku-5-5 --limit 3 --budget 0.1
```
Змінна з ключем задається `--key-var` (за замовчуванням `OPENROUTER_API_KEY`). Скрипт перевіряє префікс ключа й не надсилає його провайдеру, якому він не належить.
Міркування вимкнено: `thinking: disabled` (Haiku 5.5) і `between_tools` (Sonnet 5.5 відхиляє `disabled`); `temperature` не передається. Запити йдуть на `api.anthropic.com`, проксі застосунку (`ANTHROPIC_BASE_URL`) не використовується.
