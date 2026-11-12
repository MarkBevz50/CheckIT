# Фікстури

Реальні відповіді зовнішніх сервісів, записані `record_fixtures.py` (потрібна мережа, ключі не потрібні).

- `prozorro/` відповіді публічного API Prozorro (`/api/2.5/tenders/{id}`). Контактні дані замовника (`contactPoint`, `signerInfo`, `email`, `telephone`, `faxNumber`) замінено на `REDACTED`.
  - `tender_with_unit_price.json`: тендер типу `reporting`, одна позиція з ціною за одиницю;
  - `tender_single_item_no_unit_price.json`: одна позиція без ціни за одиницю (ціна = сума / кількість);
  - `tender_many_items_no_unit_price.json`: 11 позицій без цін (ціни беруться з документів або ринку).
- `stores/` відповіді Rozetka, Сільпо й Епіцентру на пошук «сік садочок» (як `requests.get` викликав скрапер) і відповідь Rozetka на «iphone 15» з `meta.navigateTo` (переадресація на категорію без `goods`; знадобиться в E2.2).

Фікстури відтворюються через `tests/helpers.py` (`replay_requests`).
