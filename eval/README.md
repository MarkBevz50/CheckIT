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
