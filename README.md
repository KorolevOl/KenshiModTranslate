# Kenshi RU — Переводчик модов

![kenshi-mod-translate](docs/kenshi-mod-translate.svg)

Workshop-моды, ручные моды (`kenshi\mods\<мод>`) и встроенные моды игры
(`kenshi\data\rebirth.mod`, `Dialogue.mod`, `Newwworld.mod`) → на русский.

Переводит локальный ИИ (любой OpenAI-совместимый сервер, с любого языка).
Ты можешь поправить каждую фразу в `<имя-мода>.translate.csv` (Excel)
и пересобрать результат одной командой.

**Workshop-моды: оригинальный EN-.mod НЕ трогается.** Перевод пишется в
отдельный **RU-оверлей** — папку `kenshi\mods\<имя> RUS\<имя> RUS.mod`,
который включается строкой **сразу после оригинала** в двух файлах:
`data\__mods.list` (каталог Workshop) и **`data\mods.cfg` (реальная
включённость — без строки здесь оверлей ВЫКЛЮЧЕН, даже если виден в
лаунчере)`. Обновление мода из Workshop **ничего не затирает** — оверлей
живёт отдельно.

**Встроенные моды** (`kenshi\data\*.mod`): перевод **в-place** (в сам файл),
бэкап рядом — `<имя>.mod.orig_<хэш>.backup`.

---

## 🚀 Старт: 3 шага (~5 минут)

**Шаг 1. Установка (один раз).** Двойной клик по:

```
install.bat
```

Поставит Python-зависимости, проверит .NET 9 (и сам скачает, если нет —
без админ-прав, в папку проекта), найдёт Kenshi и Workshop-моды в Steam
и сам впишет пути в `config.json`.
Финал окна: `[ OK ]` по всем пунктам + «Установлено».

> Если Python не установлен: python.org → Windows installer → галка
> **«Add Python to PATH»** → Install, затем повторить `install.bat`.

**Шаг 2. Кто переводит (один раз).** В `config.json` — блок `llm`:
любой OpenAI-совместимый сервер (локальный или облачный):

```json
"llm": {
  "base_url": "http://localhost:11234/v1",
  "model":    "qwen3.8:27b",
  "api_key":  null
}
```

Сервер должен быть запущен: проверь `curl http://localhost:11234/v1/models`.

**Шаг 3. Переводим.** Двойной клик по:

```
./translate_mods.bat
```

Откроется **интерактивное меню** — список **всех модов, у которых есть
непереведённые строки** (группами: Steam Workshop и `kenshi\mods`), с числами
`непереведено/всего`. Счёт — по всем источникам RU: твой кэш,
RU-близнец-моды (`… RUS`/`… RU` из Workshop или папки `mods`),
`.po` игры и словарь. Переведённые моды внизу — **не переводятся повторно**.

```
  === Kenshi Mod Translate — моды с непереведёнными строками ===
  --- Steam Workshop: непереведённых 250 из 259 ---
     1) Great Beak Things                         8/15
     2) Pocket Change 2.0                       31/239
     ...
  --- kenshi\mods: непереведённых 5 из 6 ---
   251) Animal Variations RUS                   91/185
   ...

  какие моды переводить?:
```

Вводишь **номера** нужных модов — через запятую, с диапазонами:

```
1, 5, 9-14      — выбранные по номерам из списка
name:crossbow   — по (частям) имени, через запятую
all / Enter     — все непереведённые моды
steam           — весь Steam Workshop (как --steam)
mods            — вся папка kenshi\mods (как --mods)
q               — выход без перевода
```

Два прогресс-бара (ALL/NOW), счёт — в токенах.
`Ctrl+C` не теряет прогресс — следующий запуск продолжит с того же места.

> Быстрый путь без меню: `--all` / `--steam` / `--mods` (всё в области)
> или имя мода (`./translate_mods.bat "Pocket Change 2.0"`).
> Отключить интерактив полностью: `config.json` → `translate.interactive_select: false`.

**Всё — моды переведены, оверлеи установлены, игра готова.**
В логе: `[OK] РУ-оверлей готов: <имя> RUS`. Ниже — ежедневные операции.

---

## 🧩 Как это работает (архитектура, для любопытных)

```
Workshop-мод (EN)               RU-оверлей
┌──────────────────┐            ┌────────────────────────────────────┐
│  Steam Workshop  │            │  kenshi\mods\<имя> RUS\            │
│  <имя>.mod       │── apply ──►│  <имя> RUS.mod                     │
│  (НЕ трогается)  │            │  (только СВОИ записи, кириллица)   │
└──────────────────┘            └────────────────────────────────────┘
                                         ▲
                                         │ insert
                                         ▼
                               kenshi\data\__mods.list        (каталог Workshop)
                               [первая строка: оригинал]
                               [вторая строка: оверлей RUS]  ← позже = победа по object-ID
                               +
                               kenshi\data\mods.cfg           (РЕАЛЬНАЯ включённость — BEEP/игра)
                               [первая строка: оригинал.mod]
                               [вторая строка: оверлей RUS.mod]  ← без неё оверлей ВЫКЛЮЧЕН
```

- **EN-.mod** — исходник, не изменяется. Steam Workshop-обновления
  работают как раньше.
- **RU-оверлей** — компактный .mod, содержит только записи,
  которые нужно переопределить (свои object-ID, кириллические тексты).
  Игра загружает и его, и оригинал; по object-ID оверлей (позже в списке)
  перебивает оригинал.
- **`__mods.list`** — каталог Workshop (включённые + выключенные, авто-синк
  со Steam). Строка оверлея вставляется **прямо после** оригинала.
  Бэкап — рядом (`kenshi\data\__mods.list.<ts>.bak`). Одного этого **не
  хватает** — оверлей будет виден в лаунчере, но выключен.
- **`mods.cfg`** — **реальная включённость** (только включённые; порядок =
  приоритет). Именно сюда BEEP Mod Manager пишет при смене load order
  (`saveLoadOrder`), и именно по строке здесь игра решит, грузиться или нет.
  Строка `<имя> RUS.mod` вставляется **прямо после** строки оригинала
  `<имя>.mod`; бэкап `kenshi\data\mods.cfg.<ts>.bak`.
- **Один откат** = `python overlay.py uninstall <имя>` — удаляет оверлей
  и строки из обоих файлов (бэкапы сохраняются).

Встроенные (`kenshi\data\*.mod`) и явные `--in-place`:
перевод пишется прямо в .mod, бэкап — рядом:
`<имя>.mod.orig_<хэш>.backup` → откат: `./revert_mods.bat "имя"`.

---

## 🗣 Повседневное использование

> ⚠️ **ВНИМАНИЕ — v2.0: логика переводов сильно изменилась.**
> В этой версии отбор «переводить/не переводить» строки стал **по object-ID из `.po`**,
> а не по тексту. Старый кэш (state/*, CSV, оверлеи), накопленный в v1.8 и раньше,
> **настроен под старую логику и может «отравлять» новый перевод**.
>
> **Перед первым запуском перевода в v2.0 выполни:**
> ```
> ./revert_mods.bat --full-clean --dry-run      # посмотреть план
> ./revert_mods.bat --full-clean                # выполнить (реверт модов + очистка CSV+кэша+оверлеев)
> ```
>
> Это безопасно: всё переносится в `kenshi\_kmt_full_clean_<ts>\`, сохраняются бэкапы
> рядом с `__mods.list` / `mods.cfg`. После этого — свежий перевод по новой логике.
>
> Если после v1.8 ты **уже перевёл** некоторые моды и они тебе нравятся,
> можно не делать полный `--full-clean` — просто **проверь, что CSV и кэш
> соответствуют текущему формату** (они должны быть созданы v1.8 и позже).

| Что хочешь сделать | Что запускаешь |
|---|---|
| Посмотреть, что не переведено, и выбрать моды | `./translate_mods.bat` (меню со списком, вводишь номера) |
| Перевести ВСЁ (все непереведённые) | `./translate_mods.bat` → `all`, или `./translate_mods.bat --all` |
| Перевести только Steam Workshop | `./translate_mods.bat --steam` |
| Перевести только ручные моды | `./translate_mods.bat --mods` |
| Перевести один мод по имени / ID | `./translate_mods.bat "имя"` или `./translate_mods.bat 1379852994` |
| Пере-перевести заново (без кэша) | `./translate_mods.bat --force "имя"` |
| Только CSV (без ИИ, без оверлея) | `./translate_mods.bat --no-llm --no-overlay "имя"` |
| Перевести в-place (старый способ) | `./translate_mods.bat --in-place "имя"` |
| Встроить произвольный .mod-файл | `./translate_mods.bat --file "C:\path\to.mod" --label "имя"` |
| Посмотреть / поправить перевод | CSV рядом с .mod → Excel → сохранить → `python overlay.py install "имя"` |
| Пересобрать .mod из кэша (in-place, без ИИ) | `./rebuild.bat` |
| Проверить качество переводов | `./verify_translations.bat` (read-only) |
| Починить битые строки | `./fix_translations.bat "имя"` |
| Очистить кэши исключённых модов (`exclude.txt`) | `./verify_translations.bat --purge` |
| Поиск фразы во всех модах и `.po` | `./search_mods.bat "фраза"` (EN→RU, если уже переведён, видно) |
| **Откатить RU-оверлей** (Workshop) | `python overlay.py uninstall "имя"` |
| **Список установленных оверлеев** | `python overlay.py list` |
| Откатить в-place (встроенные / `--in-place`) | `./revert_mods.bat "имя"` |
| Откатить в-place + вычистить кэш/CSV | `./revert_mods.bat --clean "имя"` |
| Откатить все в-place моды (y/N) | `./revert_mods.bat` |
| Показать, что можно откатить | `./revert_mods.bat --list` |
| По списку модов из файла | `./revert_mods.bat --list-file my_mods.txt` |
| Откатить любой .mod по пути | `./revert_mods.bat --file "E:\path\rebirth.mod"` |
| Убрать папки удалённых модов | `./revert_mods.bat --clean-orphans` |
| Полная чистка: кэш + CSV | `./clean_caches.bat --yes` |
| **Полная очистка v2.0** (все моды + CSV новый/legacy + весь кэш + оверлеи) | `./revert_mods.bat --full-clean` |
| ...то же, но только показать план | `./revert_mods.bat --full-clean --dry-run` |

---

## 📄 `<имя-мода>.translate.csv`

Названа как `.mod`: `Bury Your Treasure.mod` → `Bury Your Treasure.translate.csv`.
Лежит **рядом с оригиналом** (в Workshop-папке или `kenshi\data\`).

Разделитель `|`, столбец 1 = оригинал («якорь», **не менять**),
столбец 2 = перевод (пусто = строка остаётся на английском).

**Рабочий цикл (overlay-схема):**
перевести → поправить CSV в Excel → `python overlay.py install "имя"` → готово.

**Рабочий цикл (в-place / `--in-place`):**
перевести → поправить CSV → `./assemble_mod.bat "имя"` → готово.

> **Строки, уже переведённые в игре** (есть `msgstr` в `.po` игры — `locale\<target_lang>`)
> **не попадают** ни в CSV, ни в кэш, ни в .mod — они уже локализованы самой игрой.
> Их видно в `./search_mods.bat`.

---

## 🔑 Основные флаги `translate_mods.py`

```
./translate_mods.bat                        # МЕНЮ: [1] всё [2] steam [3] mods [0] выход
./translate_mods.bat --all                  # Steam Workshop + kenshi\mods\  (без меню)
./translate_mods.bat --steam                # только Steam Workshop (без меню)
./translate_mods.bat --mods                 # только kenshi\mods\ (без меню)
./translate_mods.bat "Pocket Change 2.0"    # один мод по имени
./translate_mods.bat 1173662576             # один мод по Steam-ID
./translate_mods.bat --file "C:\path\to.mod" --label "имя"   # произвольный .mod
```

| Флаг | Что делает |
|---|---|
| `--steam` | Только Workshop |
| `--mods` | Только `kenshi\mods\` |
| `--all` | Workshop + ручные моды |
| `--force` | Пере-перевести всё заново (игнорить кэш) |
| `--no-overlay` | Только кэш + CSV, **не строить оверлей** (ручной/частичный режим) |
| `--in-place` | **Старое поведение**: apply прямо в .mod (встроенные `kenshi\data` + экзотика) |
| `--no-llm` | Не ходить в LLM — только выгрузить CSV (RU-колонка пуста) |
| `--include-excluded` | Переводить моды из `exclude.txt` тоже |
| `--temperature <число>` | Переопределить температуру (0–2) на этот запуск |
| `--list-file файл.txt` | Список модов (одна строка = имя или ID) |
| `--lines "12,40-55,99"` | Пере-перевести ТОЛЬКО строки с этими номерами в CSV (1 = первая, как в Excel) |
| `--text "фраза"` | Точечный перевод по тексту (несколько `--text` можно; регистр не учитывается) |
| `--lines` + `--text` | Сочетать: строки, попавшие в ЛЮБОЕ из двух условий |

`--no-overlay` и `--in-place` — два **альтернативных** режима вывода:
- **overlay (по умолчанию Workshop)** → кэш + CSV + отдельный RU-оверлей, EN-.mod не трогается;
- `--in-place` → apply прямо в .mod (EN-оригинал модифицируется), без оверлея;
- `--no-overlay` → только кэш + CSV, **ни apply, ни оверлея** (ручной режим).

Встроенные (`kenshi\data\*.mod`) — всегда `--in-place`.

> **ВСТРОЕННЫЕ моды** (`kenshi\data\*.mod`) **никогда не входят**
> в «перевести всё» — только по явном имени (`./translate_mods.bat "rebirth"`).
> Причина: 3–10k строк каждый.

---

## 🔍 Управление оверлеями: `overlay.py`

| Команда | Что делает |
|---|---|
| `python overlay.py list` | Список установленных RU-оверлеев (`[вкл]` + имя) |
| `python overlay.py install "имя"` | Построить RU-оверлей из кэша (state/) и установить в `kenshi\mods\<имя> RUS\` |
| `python overlay.py uninstall "имя"` | **Откат**: удалить оверлей + строку из `__mods.list` + бэкап |
| `python overlay.py install "имя" --dry-run` | Показать план без действий |

Все бэкапы (`__mods.list.*.bak`, `.old_*`) лежат **рядом с игрой**
(`kenshi\data\` и `kenshi\`), не на RAM-диске T:.

---

## ⚙️ Настройки — `config.json`

| Поле | Что |
|---|---|
| `target_lang` | **целевой язык локали** (по умолчанию `ru_RU`). Из каталога `locale\<target_lang>\` берутся переводы для RU-колонки `search_mods` + подсказки `po_hints`. Сменить на `ja_JP`/`fr_FR` — и поиск/подсказки пойдут по этой локали |
| `translate.interactive_select` | **интерактивный выбор** модов (по умолчанию `true`): `translate_mods.bat` без аргументов → общий список непереведённых модов (Steam + `kenshi\\mods`) + выбор номеров. `false` — старое поведение (меню области + все моды целиком) |
| `translate.ignore_mod_description` | **NEW (v1.8)** (по умолчанию `true`): отключает описание СВОЕГО мода (top-level `description`) из поиска, перевода и кэша. Игровой текст (названия/описания предметов) — переводится. `false` — переводить и это. |
| `llm.base_url` / `llm.model` / `llm.api_key` | сервер и модель ИИ (шаг 2). Локальному серверу `api_key: null` |
| `paths.game` | папка Kenshi (обычно вписал `install.bat`) |
| `paths.workshop` | папка Workshop-модов `content\233860` (аналогично) |
| `paths.dotnet`, `paths.modtranslate_cli` | .NET и `kenshi-modtranslate.dll` (по умолчанию уже стоят) |
| `paths.state` | кэш переводов (по умолчанию `state\` в папке проекта) |

Правило путей: **относительные** — от папки проекта, **абсолютные** —
каталоги на другом диске. Изменил файл → следующий запуск подхватит.

### `state\` — кэш переводов

| Файл | Что в нём |
|---|---|
| `state\<hash>_entries.json` | переведённые строки мода (RU + номер записи) |
| `state\<hash>_mapping.json` | якорь (оригинал) → номер записи; «продолжить с места» |

`<hash>` — 12 символов, **из имени файла мода**. Кэши и оверлеи
независимы: обновил Workshop-мод → кэш жив, оверлей жив.
`clean_caches.bat` очищает кэши — оверлеи **не трогает**.

### Файлы: что где лежит

**Ядро:**

| Файл | Роль |
|---|---|
| `translate_mods.py` | конвейер (перевод, прогресс, CSV, оверлей) — основной |
| `overlay.py` | установка/откат/список RU-оверлеев (`overlay.py`) |
| `cli.py` | единая обёртка C# CLI (`kenshi-modtranslate.dll`) |
| `cache.py` | discovery модов: Workshop, game, resolve_mod |
| `exclude.py` | чёрный список модов + мутабельный `INCLUDE_EXCLUDED` |
| `prompt.py` | промпт LLM + словарь `dict.json` |

**Подсоставляющие:**

| Файл | Роль |
|---|---|
| `csv_mod.py` | CSV: выгрузка / импорт / `assemble_mod.bat` |
| `search_mods.py` | поиск фразы во всех слоях (моды/`.po`/кэш/описания) |
| `revert_mods.py` | откат **в-place** модов (Game mod + `--in-place`) |
| `rebuild_mods.py` | пересобрать все оверлеи из кэша |
| `verify_translations.py` | read-only аудит + `--fix` (через LLM) |
| `validate_translation.py` | единый классификатор «перевод / ключ / идентификатор» |
| `prefilter.py` | предварительная фильтрация (что в LLM, а что нет) |
| `po_hints.py` | подсказки из `.po` игры |
| `textutil.py` | утилиты (parse .po, regex) |
| `progress.py` | прогресс-бары (tqdm) |
| `kmt_paths.py` | резолвер путей из config.json |
| `clean_caches.py` | чистка кэшей (state/ + *.translate.csv) |
| `sanitize_caches.py` | «мёртвые» строки в старых кэшах |
| `install.py` / `install.bat` | установка (Python + .NET + пути) |
| `dict.json` | словарь терминов |
| `exclude.txt` | чёрный список (regex) |
| `prompt.txt` | инструкция LLM |
| `config.json` | настройки |

**`_dev/`** — утилиты для разработчиков (не нужны для работы).

---

## 📖 Словарь терминов — `dict.json`

Файл **канонических переводов**: «Holy Citizen» обязан звучать как
«Святой гражданин» во **всех** модах, даже если LLM хочет
«Гражданина-святого».

```json
{
  "exact": {
    "holy citizen": "Святой гражданин",
    "storage": "ХРАНЕНИЕ"
  },
  "words": {
    "holy citizen": "Святой гражданин",
    "mercenary": "наёмник"
  }
}
```

### `exact` — «строка целиком = термину»

Если **вся** строка мода (без учёта регистра) равна ключу — перевод
**всегда и точно** — значение из словаря, LLM даже не спрашивают.

Когда это важно:
- **Разделы меню и категории** (игра собирает меню по точному совпадению):
  `"storage": "ХРАНЕНИЕ"`. Иначе два мода переведут STORAGE по-разному —
  в игре два одинаковых раздела.
- **Имена рас, фракций, предметов**: `"cannibal skav": "Трупоед"`.

### `words` — «термин внутри фразы» (страховка)

LLM-перевод строки **проверяется**: если внутри перевода остался
английский термин из `words` (LLM иногда пропускает), скрипт подставляет
русское значение. В `words` **не** должны попадать короткие слова
(`food`, `power`) — иначе «great power» превратится в
«great ЭЛЕКТРИЧЕСТВО».

**Инвариант:** любой ключ в `words` **обязан** быть и в `exact`
с тем же значением (проверка: `python _dev/check_dict_invariant.py`).

### Как поправить

1. **Нашёл строку в CSV** → поправь 2-ю колонку → `python overlay.py install "имя"`.
2. **Массово во ВСЕХ модах** → добавь пару в `dict.json` (exact + words)
   → перевести заново: `./translate_mods.bat --force "имя"`.

**Коротко:** `exact` = **что** переводить, `words` = **где** разрешено
вставлять (внутри фразы). В `exact` **обязаны** быть **все** ключи `words`.

---

## 🛡 Защита от «системных значений»

В модах есть строки-ключи (имена анимаций, техник боя, SFX-событий,
категорий построек): другие записи и бинарные ассеты `.ani`/`.sfx`
ссылаются на них по точному EN-совпадению. Перевести — разорвать ссылку.

**Как конвейер это ловит:**

- **Cross-reference** — строка, которая одновременно `record.Name`
  и значением поля в том же моде, исключается из перевода.
- **Тип записи** — анимации (type 5, 24), события анимации (105, 112),
  техники боя (17): их `Name` ВСЕГДА ключ — не переводится.
- **Идентификаторы** (`_`, `-`, цифры) — не в CSV, не в кэш.

**Важно:** `building group`/`category` и другие **видимые в игре**
подписи **переводятся** (обе стороны ссылок внутри одного .mod,
переписываются согласованно).

Такие строки **не попадают** в `.translate.csv`.
Всё остальное (описания, диалоги, названия, **меню строительства**) —
переводится.

### CSV и кэш не держат «мёртвые» строки

**Единый классификатор** — `validate_translation.py`:
- `is_translatable_text(en)` — есть ли смысл переводить;
- `finished_row(en, ru)` — валидность строки в CSV;
- `has_real_translation(en, ru)` — валидность строки в кэше.

Гарантия: системные ключи **никогда** не пишутся в CSV/кэш;
настоящий перевод (даже если `en` похож на ключ) **всегда** сохраняется.

### Чистка старых кэшей

```
python clean_caches.py          # dry-run: что будет удалено
python clean_caches.py --yes    # удалить; перевод начнётся с нуля

python sanitize_caches.py --list   # отчёт по каждому кэшу
python sanitize_caches.py          # удалить «мёртвые» строки, переиндексировать
```

`sanitize_caches.py` идемпотентен, бэкап `.pre_optionA`, `.mod` не трогает.

---

## ➕ Любая внешняя LLM (OpenAI-совместимый API)

Конвейер ходит **в одну точку**: `POST <base_url>/chat/completions`.
Подойдёт **любой сервер с OpenAI-совместимым API** — локальный
(ollama, llama.cpp, vLLM, LM Studio, textgen-webui) или облачный
(OpenAI, OpenRouter, Groq, Mistral, Together, DeepSeek, …).

Меняешь в `config.json` только блок `llm`:

```json
"llm": {
  "base_url": "https://api.openai.com/v1",     // любой OpenAI-совместимый
  "model":    "gpt-4o-mini",                    // нужная модель
  "api_key":  "sk-...",                         // null для локального без ключа
  "http_timeout_s": 600
}
```

`api_key` опционален. `null` → заголовок `Authorization` не ставится.

### Несовместимые пары языков

Ядро конвейера **не знает языков**: берёт строку из `.mod`, шлёт в LLM,
забирает ответ. Подойдёт **любая пара языков**, которую понимает LLM.

По умолчанию настроено **EN → RU**: промпт, словарь, prefilter
оптимизированы под эту пару. Для другой (напр. JP → RU):

1. **`prompt.txt`** — перепиши system-промпт.
2. **`prefilter.py`** — проверка «нет латиницы → нечего переводить»
   предполагает латиницу. Для CJK — отключи (`"pre_filter": false`).
3. **`validate_translation.py`** — уровень `latin` ищет латиницу
   в переводе. Для не-латинских пар ослабь в `BAD_FIX_LEVELS`.
4. **`dict.json`** — словарь для своей пары языков.

Всё остальное (батчинг, retry, оверлей, кэш, rebuild) — работает без
изменений.

---

## 📦 Ручная установка

```
1. git clone https://github.com/KorolevOl/KenshiModTranslate.git
   (или ZIP → распаковать в C:\KenshiModTranslate)
2. install.bat                 # Python, .NET, пути — всё в один клик
3. config.json                 # llm + paths (install.bat впишет сам)
4. ./translate_mods.bat "имя"  # первый перевод
```

### Если хочется править C#-код

Нужен **.NET 9 SDK** и соседний репо `KenshiTranslator`:

```
папка\
├─ KenshiModTranslate\        ← этот репо (csproj ссылается на ..\KenshiTranslator\KenshiCore)
└─ KenshiTranslator\
   └─ KenshiCore\KenshiCore.csproj
```

```
cd KenshiModTranslate
dotnet build -c Release
# => bin\Release\net9.0-windows\kenshi-modtranslate.dll (новый)
git add bin/Release/net9.0-windows/kenshi-modtranslate.dll && git commit
```

В обычных сценариях `dotnet build` **не нужен** — DLL уже в репозитории.

---

## 🆘 «Что-то не работает»

| Симптом | Что делать |
|---|---|
| `python not found` | Python 3.10+ (галка «Add to PATH»), повторить `install.bat` |
| `dotnet: command not found` | `C:\Program Files\dotnet` в PATH (или `install.bat` сам найдёт) |
| `dotnet CLI failed` | .NET Desktop Runtime 9 не установлен (dotnet.microsoft.com) |
| `Connection refused: localhost:11234` | LLM-сервер не запущен — поднять ollama |
| `404 /v1/models` | `base_url` в `config.json` неверный |
| `Mod not found` | `paths.workshop` не та папка, либо мод отключён в Steam |
| RU-оверлей не появился в игре | `python overlay.py list` → статус `вкл`? (нет = строки нет в `data\mods.cfg`). Проверь `kenshi\mods\<имя> RUS\` + строки в `__mods.list` **и** `data\mods.cfg` |
| Оверлей виден в лаунчере, но не работает | Скорее всего нет строки в **`data\mods.cfg`** (реальная включённость). `python overlay.py install "имя"` вставит в оба файла |
| Перевод «завис» (LLM не отвечает) | `curl http://localhost:11234/v1/models`, увеличение `http_timeout_s` |
| Оверлей сломан (пустой/без кириллицы) | `python overlay.py uninstall "имя"` → `./translate_mods.bat --force "имя"` |

---

## 📊 Прогресс и возобновление

Два прогресс-бара в терминале:
- **ALL** — все моды (общий прогресс по сессии)
- **NOW** — текущий мод (по строкам / токенам)

`Ctrl+C` — **не теряет прогресс**. Следующий запуск того же мода
продолжает с того места, где остановился (кэш в `state\`).
Оверлеи и CSV **не зависят от кэша**: можно стереть кэш (`clean_caches.bat`),
оверлеи и переводы не пропадут.

---

## 🗒 Шпаргалка (все команды)

```
# Перевод
./translate_mods.bat                        # МЕНЮ
./translate_mods.bat "имя"                  # один мод по имени
./translate_mods.bat 1379852994             # один мод по Steam ID
./translate_mods.bat --file "C:\path\to.mod" --label "My Mod"  # произвольный файл
./translate_mods.bat --force "имя"          # заново (без кэша)
./translate_mods.bat --no-llm --no-overlay "имя"  # только CSV, без ИИ, без оверлея
./translate_mods.bat --in-place "имя"       # старое (в-place в .mod)
./translate_mods.bat --all                  # все (меню: [1])
./translate_mods.bat --steam                # только workshop (меню: [2])
./translate_mods.bat --mods                 # только kenshi\mods\ (меню: [3])
./translate_mods.bat "имя" --lines "12,40-55"  # только эти строки
./translate_mods.bat "имя" --text "фраза"  # по содержимому
./translate_mods.bat --list-file mods.txt   # из файла

# Оверлеи (Workshop)
python overlay.py list                      # список установленных
python overlay.py install "имя"             # построить из кэша
python overlay.py uninstall "имя"           # откат
python overlay.py install "имя" --dry-run   # просмотр без действий

# CSV
./export_mod_csv.bat "имя"                  # выгрузить CSV из кэша
./assemble_mod.bat "имя"                    # пересобрать в-place из CSV (старое)

# Пересборка / проверка
./rebuild.bat                        # пересобрать .mod (in-place) из кэша, без ИИ
./verify_translations.bat            # read-only аудит
./verify_translations.bat --fix "имя"       # починить (LLM)
./fix_translations.bat "имя"                # краткий способ

# Поиск фразы
./search_mods.bat "фраза"                   # поиск (EN/RU, слои)
./search_mods.bat "фраза" --all             # показать уже переведённые
./search_mods.bat "фраза" --no-translate    # не запускать перевод

# Откат (в-place)
./revert_mods.bat "имя"                     # откат в-place
./revert_mods.bat --clean "имя"             # откат + вычистить кэш/CSV
./revert_mods.bat --list                    # список + осиротевшие
./revert_mods.bat --dry-run "имя"           # показать, не выполнять
./revert_mods.bat --list-file mods.txt      # из файла

# Чистка
./clean_caches.bat --yes                    # удалить все кэши + CSV
python sanitize_caches.py --list            # отчёт по «мёртвым» строкам
python csv_mod.py --list                    # список доступных модов/ID
```
