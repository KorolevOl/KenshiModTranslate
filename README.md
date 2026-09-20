# Kenshi RU — Переводчик модов

Моды Steam Workshop → на русский (или другой язык). Локальный ИИ переводит, ты можешь
сам править каждую фразу в `translate.csv` и пересобирать `.mod`. Ничего не копируется
в `mods\` — перевод пишется **на месте**, в папке мода в Steam.
Резервная копия оригинала — рядом (`.orig_<хэш>.backup`).
Поддерживается **любая пара языков**, которую понимает подключённая LLM.
---

## 🚀 Коротко: запуск за 10 минут (для новичка)

> **Вам не нужно собирать DLL** — она уже лежит в репозитории:
> `bin\Release\net9.0-windows\kenshi-modtranslate.dll`.

**Список «поставить один раз» (Windows):**

| # | Что | Откуда | Сколько |
|---|-----|--------|---------|
| 1 | **Python 3.10+** | [python.org](https://python.org) → Windows → installer → галка **«Add Python to PATH»** → Install | ~30 сек |
| 2 | **.NET Desktop Runtime 9** (x64) | [dotnet.microsoft.com/download/dotnet/9.0](https://dotnet.microsoft.com/download/dotnet/9.0) → «.NET **Desktop** Runtime» → «x64» | ~30 сек |
| 3 | **Steam** (если ещё нет) | [steampowered.com](https://steampowered.com) | ~1 мин |
| 4 | **Kenshi** в Steam (если ещё нет) | [steampowered.com](https://store.steampowered.com) | ~5 мин |
| 5 | **LLM-сервер** (локальный или облачный) | см. ниже Шаг 4 | — |

> .NET **SDK** НЕ нужен. SDK — только если хочешь править C#-код (сборка нового .mod-парсера).
> Для **запуска** достаточно Desktop Runtime.

**Теперь — три команды в терминале** (или просто двойной клик по `translate_mods.bat`):
```
pip install -r requirements.txt              # одна библиотека (tqdm + requests)
# отредактируйте paths.game и paths.workshop в config.json (2 строки)
translate_mods.bat                           # начать перевод всех модов
```

Готово. Дальше — двойные клики по `.bat`, никаких «собери/компилируй».

---

## 📦 Установочные шаги (подробно)

Проект рассчитан на **Windows 10/11**. Стоимость: **0 ₽** — всё работает локально
(кроме самого Kenshi в Steam и LLM-сервера, если он у вас платный/облачный).

### Шаг 1. Получить проект

**Вариант A — Git (рекомендуется):**
```
git clone https://github.com/KorolevOl/KenshiModTranslate.git
cd KenshiModTranslate
```

**Вариант B — просто скопировать папку** (без Git):
Скачайте ZIP с GitHub (зелёная кнопка «Code» → «Download ZIP») → распакуйте
в папку, например `C:\KenshiModTranslate`. Дальше — то же самое.

> ⚠️ При копировании вручную убедитесь, что папка содержит:
> `translate_mods.bat`, `translate_mods.py`, `config.json`,
> `bin\Release\net9.0-windows\kenshi-modtranslate.dll`,
> `bin\Release\net9.0-windows\KenshiCore.dll`.


### Шаг 2. Python
Установить **Python 3.10+** с галкой «Add Python to PATH» (python.org → Windows → installer).
Проверить:
```
python --version          # 3.10+
pip --version
```
Зависимости (всего 1 пакет — tqdm):
```
pip install -r requirements.txt
```
> Если tqdm уже есть — `pip install -r requirements.txt` скажет «already satisfied», это ок.

### Шаг 3. .NET 9 Desktop Runtime
**DLL уже в этом репо** — `bin\Release\net9.0-windows\kenshi-modtranslate.dll` закоммичен
вместе с зависимостями ( `KenshiCore.dll`, `*.runtimeconfig.json`, `*.deps.json` ).
Вам нужен только **.NET 9 Desktop Runtime** на машине (не SDK — только для запуска):
```
# Скачать: https://dotnet.microsoft.com/download/dotnet/9.0  →  .NET Desktop Runtime 9.0.x  →  x64
# Установить. После установки:
dotnet --list-runtimes    # содержит Microsoft.WindowsDesktop.App 9.0.x
```
> `dotnet` = команда-запускатель рантайма, не отдельное приложение — ставится вместе с `Desktop Runtime` в `%ProgramFiles%\dotnet`.
> В `config.json` укажите полный путь к нему, если `dotnet` не в `PATH`: `"dotnet": "C:\\Program Files\\dotnet\\dotnet.exe"`.

**Если хотите менять C#-код** (добавить фичи, патчить) — тогда нужен **.NET 9 SDK** + соседний
репо `KenshiTranslator`:
```
папка\\
├─ KenshiModTranslate\\      ← этот репо (ksm csproj ссылается на ..\KenshiTranslator\KenshiCore)
└─ KenshiTranslator\\
    └─ KenshiCore\\KenshiCore.csproj
```
```
cd KenshiModTranslate
dotnet build -c Release
# => bin\Release\net9.0-windows\kenshi-modtranslate.dll (новый)
git add bin/Release/net9.0-windows/kenshi-modtranslate.dll && git commit
```

### Шаг 4. LLM-сервер (локальный)
В `config.json`:
```json
"llm": {
  "base_url": "http://localhost:11234/v1",
  "model":    "qwen3.8:27b",
  "api_key":  null
}
```
Проверить, что сервер отвечает:
```
curl http://localhost:11234/v1/models
```
Должен вернуть JSON со списком моделей. Если сервер под другим именем/портом — поправь `base_url`.

### Шаг 5. Пути в `config.json`
Правило: **абсолютные** — только для каталогов **вне** папки проекта (game, workshop на `E:`); **относительные к папке проекта** — для всего, что рядом (`state`, `dotnet`, `modtranslate_cli`).
```json
"paths": {
  "game":     "E:\\steamlibrary\\steamapps\\common\\kenshi",
  "workshop": "E:\\steamlibrary\\steamapps\\workshop\\content\\233860",
  "dotnet":   "../dotnet9/dotnet.exe",
  "modtranslate_cli": "bin/Release/net9.0-windows/kenshi-modtranslate.dll",
  "state":    "state"
}
```
| Поле | Что (пример значения в этом репо) |
|---|---|
| `game` | Каталог игры ( Kenshi, `kenshi.exe` внутри ) — абсолютный, на твоём диске |
| `workshop` | Папка Steam Workshop — `content\233860` ( appId Kenshi = 233860 ) — абсолютный |
| `dotnet` | `../dotnet9/dotnet.exe` **относительно папки проекта** (или просто абсолютный, если dotnet где-то ещё) |
| `modtranslate_cli` | `bin/Release/net9.0-windows/kenshi-modtranslate.dll` (относительно папки проекта, после `dotnet build`) |
| `state` | `state` — кеш переводов, **по умолчанию внутри папки проекта** |

> Относительные пути всегда резолвятся **относительно папки проекта**, где лежит
> `config.json` — работает из любого CWD и из любого `.bat`.

### Шаг 6. (Опционально) Словарь / Чёрный список / Промт
Файлы уже есть с разумными дефолтами, можно править:
- `dict.json` — свои «канонические» термины (`exact`, `words` — см. раздел «Словарь терминов»)
- `exclude.txt` — регулярные выражения, какие моды не трогать
- `prompt.txt` — инструкции ИИ (тон, правила, адаптация)

### Шаг 7. Самопроверка (без LLM, без переводов)
```
verify_translations.bat
python search_mods.py "test"
```
Если ничего не падает — можно переводить:
```
translate_mods.bat "Pocket Change 2.0"
```

### Шаг 8. Обновление проекта (когда появится новый релиз)
```
cd KenshiModTranslate
git pull
pip install -r requirements.txt    # если requirements.txt поменялся
```
> `dotnet build` **НЕ нужен** в 99% случаев — DLL уже в репозитории и обновляется
> вместе с кодом при новом релизе. Нужен только если вы **сами** правите `Program.cs`.

### Типичные ошибки установки

| Симптом | Причина / Fix |
|---|---|
| `python not found in PATH` | Python не добавлен в PATH — переустановить с галкой |
| `dotnet: command not found` | .NET не в PATH — добавить `C:\Program Files\dotnet` в PATH |
| `dotnet CLI failed: The application to execute does not exist` | `paths.modtranslate_cli` в `config.json` неверен — проверьте, что `bin\Release\net9.0-windows\kenshi-modtranslate.dll` существует (в репо) |
| `You must install or update .NET` | Не установлен **.NET Desktop Runtime 9** — ставится с dotnet.microsoft.com |
| `KenshiCore.csproj` не найден при сборке | Нет соседнего `..\KenshiTranslator\KenshiCore\KenshiCore.csproj` – скачать рядом |
| `Connection refused: localhost:11234` | LLM-сервер не запущен – поднять ollama/ollama-weldbook |
| `404 /v1/models` | `base_url` в `config.json` неверен |
| `Mod not found` (мод не в списке) | `paths.workshop` не та папка или мод отключён в Steam |

---

## 📁 Файлы, которые ты трогаешь

| Файл | Зачем |
|---|---|
| `translate_mods.bat` | **Главная кнопка** — переводить мод(ы) |
| `export_mod_csv.bat` | Выгрузить текущий перевод мода в `translate.csv` |
| `assemble_mod.bat` | **Пересобрать .mod** из правленого `translate.csv` |
| `rebuild.bat` | **Пересобрать все (или один) .mod** из кеша `state/` (без LLM, без CSV) |
| `verify_translations.bat` | Проверить, что всё переведено (и поправить) |
| `fix_translations.bat` | Починить только битые/пустые строки |
| `search_mods.py` | Поиск по тексту во всех модах |
| `config.json` | Настройки (путь к игре, модель ИИ, лимиты) |
| `dict.json` | Словарь терминов (канонические русские названия) — **живёт в промпте всегда** |
| `po_hints.py` | Динамические подсказки из руслокализации игры (персонально под чанк) — **не раздувает контекст** |
| `prefilter.py` | Pre-LLM фильтр: нечего переводить (regex) + уже переведено (reuse) — экономят токены/время |
| `exclude.txt` | Чёрный список — какие моды НЕ переводить |
| `prompt.txt` | Инструкции ИИ (тон, правила, адаптация игры слов) |

Все `*.bat` запускаются двойным кликом или из терминала. `*.py` — через `python`.

---

## 🚀 Запуск перевода

```
translate_mods.bat                        # все моды (спросит [y/N])
translate_mods.bat "Pocket Change 2.0"    # один мод по имени
translate_mods.bat 1173662576             # один мод по Steam-ID
```

### Флаги

| Флаг | Что делает |
|---|---|
| `--force` | **Пере-перевести всё заново** (игнорирует кэш, резервную копию не трогает) |
| `--include-excluded` | Переводить даже моды из `exclude.txt` |
| `--list-file файл.txt` | Список модов (одна строка = имя-или-ID) |

Примеры:
```
translate_mods.bat --force "Heavy Crossbow"
translate_mods.bat --force --list-file мои_моды.txt
```

### Прогресс
Два прогресс-бара в терминале (верхний `ALL` — все моды, нижний `NOW` — текущий мод),
счёт — **в токенах**. Можно прервать `Ctrl+C` — прогресс сохранится в кеше (`state/`).
Повторный запуск того же мода **продолжит с того места**, где остановился.

---

## 🗣 Как «разговаривать» с модом — CSV

После **любого** перевода (а также по команде `export`) в папке мода в Steam
появляется `translate.csv`:

| Колонка 1 | Колонка 2 |
|---|---|
| оригинал (EN) | перевод (RU) |

Разделитель — **`|`**. Открыть в Excel/LibreOffice.

- Пустая 2‑я колонка = строка **не переводится** (остаётся исходной).
- Правка = меняешь 2‑ю колонку (1‑ю не трогай — это «якорь»).

### Пересобрать .mod из своего CSV
```
assemble_mod.bat "Pocket Change 2.0"
```
Скрипт берёт `translate.csv` из папки мода, переписывает .mod на месте.
**Старый .mod резервируется** (`.prev`) — откат всегда возможен.

### Пересобрать всё из кеша (без LLM, без CSV)
```
rebuild.bat                      # все 223 мода из state/
rebuild.bat 1173662576           # один мод по Steam-ID
rebuild.bat cross                # все, чьё имя содержит «cross»
```
Эквивалент `assemble_mod.bat`, но берёт RU-переводы из `state\<hash>_mapping.json`
(кеш) — не нужен `translate.csv`, LLM не зовётся. RU уже финален (в нём уже
учтены `dict.json`, `validate_translation`, поправки фиксаторов) — rebuild
просто выкладывает его в `.mod`. Удобно после изменения `Program.cs`, изменения
кеша вручную, или для пересинхронизации всех `.mod` в один мах.

---

## 🔍 Проверка и ремонт

### Только проверить (без ИИ, быстро)
```
verify_translations.bat                     # все моды: что пусто / эхо / латынь
verify_translations.bat --details           # + печатает конкретные проблемные строки
verify_translations.bat "Pocket Change"     # только один мод
```

### Починить (перевести только битое)
```
fix_translations.bat                        # все моды
fix_translations.bat "Factions"             # один мод
```
Уже-хорошие строки ИИ **не трогаёт** — только пустые/повтор/потерянные-плейсхолдеры.

### Убрать мод из кеша
```
verify_translations.bat --purge "Название"
```
(удаляет кеш перевода + копия в `mods\`, если есть; ИИ не зовёт)

---

## 🧭 Поиск по тексту

Где во всех модах лежит фраза?
```
python search_mods.py "Heavy Crossbow"
python search_mods.py "little help" --ru    # только русские переводы
python search_mods.py "кашлянула" --dll     # + в .dll (медленно)
```

---

## ⚙️ Настройки — `config.json`

| Поле | Что это |
|---|---|
| `paths.game` | Папка игры (kenshi) |
| `paths.workshop` | Папка Workshop-модов (233860 = appId Kenshi) |
| `llm.base_url` | `http://localhost:11234/v1` (ollama) |
| `llm.model` | `qwen3.8:27b` |
| `translate.max_batch_lines` | Макс. строк в одном ИИ-запросе (по умолчанию 50) |
| `translate.temperature` | Креативность (по умолчанию 0.5) |
| `dict` | Ссылка на словарь |
| `exclude_file` | Ссылка на чёрный список |

Меняешь `config.json` → следующий запуск подхватит.

### ➕ Любая внешняя LLM (OpenAI-совместимый API)

Конвейер ходит по **одной точке**: `POST <base_url>/chat/completions` в формате
OpenAI. Поэтому подойдёт **любой сервер с OpenAI-совместимым API** — локальный
(ollama, llama.cpp /server, vLLM, LM Studio, text-generation-webui, ollama-weldbook)
или облачный (OpenAI, OpenRouter, Groq, Mistral, Together, DeepSeek и т.п.).

Нужно поменять в `config.json` только блок `llm` (+ при желании модель из `translate`):
```json
"llm": {
  "base_url": "https://api.openai.com/v1",          // ← любой OpenAI-совместимый
  "model":    "gpt-4o-mini",                         // ← нужная тебе модель
  "api_key":  "sk-...",                              // ← ключ (null если локальный, без ключа)
  "http_timeout_s": 600
}
```
`api_key` — опционален: если `null`, заголовок `Authorization: Bearer …` не ставится
(локальные серверы часто не требуют). Если задан — уходит как bearer-token.

**Условия совместимости** (всё, что конвейер реально шлёт и читает):
- принимает `POST /v1/chat/completions` (или путь, зашитый в `base_url`) и отдаёт
  `choices[0].message.content` (+ `finish_reason`, `usage`);
- поддерживает поле `temperature` и достаточный контекст (чанк до `max_batch_lines`
  строк + словарь терминов);
- **лишние для него** поля — отправляем всегда и часть серверов их молча игнорирует:
  - `max_tokens` (потолок ответа),
  - `reasoning_effort` (`"none"` → без «рассуждений»; понимают qwen3 / llama3.1+),
  - `chat_template_kwargs.enable_thinking` (вкл/выкл «thinking» у qwen3) —
    для чужих моделей просто игнорируется.

Практика:
- **Локальная без ключа** — `api_key: null`, `base_url = http://localhost:<port>/v1`.
- **Облачная** — вставь реальный `base_url` + `model` + `api_key`; модель обязана
  «держать» ~200k токенов контекста и отдавать JSON-массив переводов без «рассуждений».
- Если сервер ругается на неизвестные поля (строгие OpenAI-клоны) — просто убедись,
  что включён режим, игнорирующий лишние (`reasoning_effort`, `chat_template_kwargs`),
  либо временно закомментируй соответствующие ключи в `config.json` (см. блок `translate`).

Программа не привязана к конкретному вендору: подставляй endpoint — и конвейер,
prefilter (reuse без LLM) и словарь работают как есть.

### 🌍 Не только английский → русский

Ядро конвейера **не знает языков**: оно берёт строку из `.mod`, отправляет её в LLM
и забирает ответ. HTTP-протокол, батчинг, ретраи, `apply`/`rebuild` — полностью
независимы от пары языков. Поэтому подойдёт **любой язык-исходник**, который понимает
подключённая LLM, а целевой язык — любой, на который она умеет отвечать.

> По умолчанию настроено **EN → RU**: промпт, словарь и prefilter-фильтр оптимизированы
> под пару английский → русский. Чтобы переключить на другую пару (например, японский →
> русский или немецкий → русский):
>
> 1. **`prompt.txt`** — перепиши system-промпт: «переведи с *<язык>* на *<язык-цели>*»
>    + правила (термины, имена, стиль).
> 2. **`prefilter.py` → SLOI 1** — проверка «нет латиницы → нечего переводить»
>    предполагает латиницу в исходнике. Для CJK/кириллических исходников
>    включи `"pre_filter": false` в `config.json` или переделай regex на свой алфавит.
> 3. **`validate_translation.py`** — уровень `latin` ищет латиницу в переводе
>    (а `echo` — совпадение с оригиналом, не зависит от языка). Для не-латинских
>    пар ослабь/отключи уровень `latin` в `BAD_FIX_LEVELS`.
> 4. **`dict.json`** — если нужен словарь, занесите пары `<исходный_текст> → <перевод>`
>    для своей пары языков.
>
> Всё остальное — батчинг, retry, `apply`, `rebuild`, `state/`-кеш — работает без изменений.

---

## 📖 Словарь терминов — `dict.json`

Чтобы «Holy Citizen» всегда был «Святым гражданином», а не «Гражданином-святым»,
прописываешь:

```json
{
  "exact": { "holy citizen": "Святой гражданин" },
  "words": { "mercenary": "наёмник" }
}
```

- `exact` — **всё строковое** (EN целиком) → заменяется на RU.
- `words` — **слово внутри строки** → скрипт подставит после ИИ.

Добавь свои «канонические» названия — ИИ будет стараться, а скрипт подстрахует.

---

## 🎯 Динамические подсказки из RU-локализации игры (`po_hints.py`)

Помимо `dict.json`, каждый чанк подгоняется под официальную русскую локализацию игры:

```
{game}/locale/ru_RU/gamedata.po           — названия объектов/рас/фракций/построек
{game}/locale/ru_RU/LC_MESSAGES/main.po   — UI, категории, диалоги
```

При сборке промпта для LLM `translate_mods.py` берёт из этих файлов **только те EN→RU
пары, которые пересекаются со словами текущего чанка** — и только те, которых ещё нет
в `dict.json`. Это даёт ИИ канонический вариант для редких названий (Cat-Lon, Gorillo,
Riceweed …), но **не раздувает промпт** статично (в .po 4000+ пар, а под чанк попадает
обычно 5–15).

Параметры (в `config.json → translate`):

| ключ | по-умолчанию | смысл |
|------|--------------|-------|
| `po_hints` | `true` | включать ли вообще (false — только `dict.json`) |
| `po_hints_max` | `50` | максимум строк подсказок на чанк |

**Правило редкости**: пара считается подсказкой, только если содержит хотя бы одно
**редкое** слово (встречается во всех строках `.po` ≤ 10 раз). Частые «общие» слова
(town/stone/guard/water — 17–37 вхождений) НЕ дают вклада и отсекаются.

Отключить: `"po_hints": false` в `config.json`.


---

## 🛡 Pre-LLM фильтр — `prefilter.py` (экономия токенов + консистентность)

Прежде чем `translate_mods.py` отправляет строки в LLM, он **дважды проверяет их**:

**СЛОЙ 1 — «нечего переводить»** (regex): если в строке **нет ни одной латинской
буквы** (кириллица/знаки/числа/CJK/эмодзи — после вычистки BBCode `[...]` и
движковых слэш-тегов `/AAA/`), то в ней нечего переводить. Строка **не уходит
в LLM** (passthrough — в `.mod` останется оригинал).

```
"Привет, как дела?"   → нет латиницы → passthrough (не LLM)
"!!!", "123 456"       → нет латиницы → passthrough (не LLM)
"[h1]Привет[/h1]"      → нет латиницы (тег вычищен) → passthrough (не LLM)
"hello world"          → есть латиница → ищем перевод
```

**СЛОЙ 2 — «уже переведено»** (переиспользование): если EN-строка точно совпадает
(без учёта регистра) с готовым RU-переводом, берём тот RU и **НЕ спрашиваем LLM**:
- `dict.json exact` (канон: build-меню, имена/фракции);
- `.po` игры (`gamedata.po` + `LC_MESSAGES/main.po`) — официальные RU;
- кеш уже переведённых модев (`state\*_entries.json` + `_mapping.json`).

Приоритет источников: `dict.json` > `.по игры` > кеш модев. Эхо (`RU==EN`) и
**ГРЯЗНЫЙ RU** (кириллица в `/.../`, BBCode-мусор) отбраковываются фильтром
и не используются как переиспользуемый перевод.

```
"Furniture"          → dict.json: "Мебель"          (не LLM)
"Storage"            → dict.json: "ХРАНЕНИЕ"        (не LLM)
"Mercenary Heavy"    → .по игры: "Крепыш"           (не LLM)
"Anti-Slavers"       → dict.json: "Противники рабства" (не LLM)
```

**Выгода**: экономия токенов + времени LLM, ДЕРЖИМ КОНСИСТЕНТНОЕ написание
имён/фракций (те же переводы, что уже были в модов/локализации игры).

Все строки, прошедшие prefilter-фильтры, всё равно проходят `audit_map`/
`validate_batch` — единая валидация без регрессии.


---

## 🚫 Чёрный список — `exclude.txt`

Одна **регулярка** на строку. Совпало по имени мода или имени файла `.mod` → пропуск.
Без учёта регистра. Разделители `-` `_` ` ` `( )` учитываются (их пробуют заменить пробелом).

Текущий `exclude.txt`:
```
\b(rus)\b          # «…RUS…»
ru$                   # имя кончается на «ru»
\brussian\b           # «…russian…»
\bрусск\w*            # «русский», «русских»…
^[\u0400-\u04FF]+$    # строка целиком на кириллице
\bkenshitranslator\b  # конкретный мод
```

---

## 🤖 Промт ИИ — `prompt.txt`

Отдельный файл, редактируется без правки кода. Секции:
`[SYSTEM]` — системные правила; `[USER]` — шаблон запроса.
Плейсхолдеры: `{{DICT}}` (вставляется словарь), `{{COUNT}}` (кол-во строк).

Всё, что между `/.../` **в тексте мода** (теги вроде `/HOLYGREET/`) — **НЕ переводится**,
это игровые команды.

---

## 🆘 «Что-то не работает»

| Симптом | Что делать |
|---|---|
| `python not found in PATH` | Установи Python 3.10+ и добавь в PATH |
| `dotnet CLI failed` | .NET Desktop Runtime 9 не установлен, либо `bin\Release
et9.0-windows\kenshi-modtranslate.dll` отсутствует (должна быть в репо) |
| Ложный-мод / пустой кеш | `verify_translations.bat --details`, затем `--fix` |
| Неверный порядок/потеря строк | `fix_translations.bat "имя"` — починит только битое |
| Удалить кеш мода | `verify_translations.bat --purge "имя"` |
| Перевести заново | `translate_mods.bat --force "имя"` (резервный остаётся) |

### Резервные копии (на месте, в папке мода)
```
<имя>.mod                       ← текущий (обычно RU)
<имя>.mod.orig_<хэш>.backup    ← оригинал (из Steam)
<имя>.mod.prev                 ← предыдущая RU (откат: переназвать назад)
<имя>.mod.new                 ← временный (появляется при apply)
```

---

## 🔄 Полный цикл «сделал — поправил — собрал»

1. `translate_mods.bat "Pocket Change 2.0"` — перевести (или уже переведено)
2. Открыть `.../1173662576/translate.csv` в Excel
3. Править 2‑ю колонку (RU), сохранить
4. `assemble_mod.bat "Pocket Change 2.0"` — пересобрать .mod из CSV
5. Запустить игру

Если что-то пошло не так — откат:
```
ren "Pocket Change 2.0.mod" "Pocket Change 2.0.mod.broken"
ren "Pocket Change 2.0.mod.prev" "Pocket Change 2.0.mod"
```

---

## 📌 Краткая шпаргалка

```
# перевести
translate_mods.bat "имя" | --force | --list-file f.txt | --include-excluded
# выгрузить CSV
export_mod_csv.bat "имя"
# пересобрать из CSV
assemble_mod.bat "имя"
# пересобрать ВСЕ из кеша (без LLM, без CSV)
rebuild.bat | <Steam-ID> | <имя>
# проверить
verify_translations.bat [--details] [--fix] [--purge]
# поиск
python search_mods.py "фраза" [--en|--ru|--dll]
# список доступных имён/ID
python csv_mod.py --list
```
