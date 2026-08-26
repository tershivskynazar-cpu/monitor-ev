# EVBOOST Server Monitor

Це серверна версія моніторингу для GitHub Actions. Вона запускається кожні 5 хвилин, збирає статуси станцій EVBOOST і складає історію в `data/evboost_history.csv`.

## Як запустити безкоштовно

1. Створи новий GitHub repository. Краще `public`, тоді GitHub Actions не витрачає приватні безкоштовні хвилини.
2. Завантаж усі файли з цієї папки в корінь repository.
3. Відкрий вкладку `Actions`.
4. Якщо GitHub попросить, натисни `I understand my workflows, go ahead and enable them`.
5. Вибери workflow `EVBOOST monitor`.
6. Натисни `Run workflow`, щоб перевірити вручну.

Після цього workflow запускатиметься автоматично кожні 5 хвилин.

## Де будуть дані

- `data/evboost_history.csv` - усі зібрані заміри.
- `data/evboost_report.txt` - поточна статистика.

## Як зупинити через тиждень

В GitHub відкрий:

`Actions` -> `EVBOOST monitor` -> `...` -> `Disable workflow`

Або видали файл `.github/workflows/evboost-monitor.yml`.

## Важливо

GitHub Actions schedule не гарантує запуск рівно секунда-в-секунду, але для дослідження завантаженості конкурентів кожні 5 хвилин цього достатньо.
