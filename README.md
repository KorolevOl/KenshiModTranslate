# Kenshi RU — Переводчик модов

![kenshi-mod-translate](docs/kenshi-mod-translate.svg)

Моды Steam Workshop → на русский. Локальный ИИ переводит, ты можешь править
каждую фразу в `<имя-мода>.translate.csv` (Excel) и пересобирать `.mod`. Перевод пишется
**на месте** — в папке мода в Steam, в `mods\` ничего не копируется.
Резервная копия оригинала — рядом (`.orig_<хэш>.backup`).

---

## 🚀 Запуск: 3 шага

**Шаг 1. Установка (один раз, ~2 минуты).** Двойной клик по:

```
install.bat
```

Он сам:
- проверит Python и поставит зависимости;
- проверит .NET 9 — если нет, **сам скачает** (~50 МБ, без админ-прав, в папку проекта);
- найдёт Kenshi и Workshop-моды в Steam и **сам впишет пути** в `config.json`.

Финал окна: «[ OK ]» по всем пунктам + «Установлено».
(Если нет Python — поставить один раз: python.org → Windows installer →
галка **«Add Python to PATH»** → Install, затем повторить `install.bat`.)

**Шаг 2. Кто переводит (один раз).** В `config.json` прописать блок `llm` —
любой OpenAI-совместимый сервер ИИ (локальный, локальная GPU, облачный):
```json
"llm": {
  "base_url": "http://localhost:11234/v1",
  "model":    "qwen3.8:27b",
  "api_key":  null
}
```
Сервер должен быть запущен; проверьте: `curl http://localhost:11234/v1/models`.

**Шаг 3. Переводить.** Двойной клик по:

```
./translate_mods.bat
```

Прогресс-бары ALL/NOW (счётчик — в токенах). `Ctrl+C` останавливает без потери
прогресса; повторный запуск продолжает с того же места.

---

## 🗣 Повседневное использование

| Что хотите | Что запустить (двойной клик) |
|---|---|
| Перевести все моды | `./translate_mods.bat` |
| Только один мод | `./translate_mods.bat "имя мода"` |
| Пере-перевести заново (игнорируя кеш) | `./translate_mods.bat --force "имя мода"` |
| Только создать CSV для ручного перевода (без ИИ) | `./translate_mods.bat --no-llm "имя мода"` |
| Посмотреть/поправить перевод | файл `<имя-мода>.translate.csv` в папке мода (Excel) → сохранить → `./assemble_mod.bat "имя мода"` |
| Пересобрать все `.mod` из кеша (без ИИ) | `./rebuild.bat` |
| Проверить качество / починить | `./verify_translations.bat`, `./fix_translations.bat "имя мода"` |
| Убрать мод из кеша | `./verify_translations.bat --purge "имя мода"` |
| Найти, где во всех модах И В ФАЙЛАХ ИГРЫ лежит фраза (реализация поиска по `kenshi\data\*.mod`, `kenshi\mods\<мод>`, `.po`), затем выбрать номера и запустить перевод | `./search_mods.bat "фраза"` → вводишь номера → перевод запускается |

**`<имя-мода>.translate.csv`** — Excel-таблица мода (названа по имени `.mod`-файла:
`Pocket Change 2.0.mod` → `Pocket Change 2.0.translate.csv`): разделитель `|`, столбец 1 = оригинал
(«якорь», **не трогать**), столбец 2 = перевод (пусто = строка остаётся как была).

**Полный цикл**: перевести → поправить CSV в Excel → `./assemble_mod.bat` → игра.
Откат: вернуть `имя.mod.prev` обратно в `имя.mod`.

---

## ⚙️ Настройки — `config.json`

| Поле | Что |
|---|---|
| `llm.base_url` / `llm.model` / `llm.api_key` | сервер и модель ИИ (шаг 2). Локальному серверу `api_key: null` |
| `paths.game` | папка Kenshi (обычно вписал `install.bat`) |
| `paths.workshop` | папка Workshop-модов `content\233860` (аналогично) |

Правило путей: **относительные** — от папки проекта, **абсолютные** — каталоги на
другом диске. Изменил файл → следующий запуск подхватит.
Остальные параметры уже разумные по умолчанию (см. «Детали»).

## 🆘 «Что-то не работает»

| Симптом | Что делать |
|---|---|
| `python not found in PATH` | Установи Python 3.10+ и добавь в PATH |
| `dotnet CLI failed` | .NET Desktop Runtime 9 не установлен, либо `bin\Release
et9.0-windows\kenshi-modtranslate.dll` отсутствует (должна быть в репо) |
| Ложный-мод / пустой кеш | `./verify_translations.bat --details`, затем `--fix` |
| Неверный порядок/потеря строк | `./fix_translations.bat "имя"` — починит только битое |
| Удалить кеш мода | `./verify_translations.bat --purge "имя"` |
| Перевести заново | `./translate_mods.bat --force "имя"` (резервный остаётся) |

### Резервные копии (на месте, в папке мода)
```
<имя>.mod                       ← текущий (обычно RU)
<имя>.mod.orig_<хэш>.backup    ← оригинал (из Steam)
<имя>.mod.prev                 ← предыдущая RU (откат: переназвать назад)
<имя>.mod.new                 ← временный (появляется при apply)
```

---

## 🔄 Полный цикл «сделал — поправил — собрал»

1. `./translate_mods.bat "Pocket Change 2.0"` — перевести (или уже переведено)
2. Посмотреть перевод: в игре или в `.../1173662576/<имя мода>.translate.csv` (открыть в Excel)
   — **если всё устраивает, останавливаемся здесь**. Остальные шаги не нужны.

   > `_id_` в URL/путь (например, `1173662576`) **— это Steam ID мода**.
   > У каждого мода Workshop есть уникальный цифровой ID (виден в ссылке
   > steamcommunity.com/shared/filedetails/**1173662576**), по нему названа папка
   > в Steam. В этой папке и лежит `<имя мода>.translate.csv`.
3. (Только если что-то не так) Править 2‑ю колонку (RU) в `<имя мода>.translate.csv`, сохранить
4. `./assemble_mod.bat "Pocket Change 2.0"` — пересобрать .mod из CSV
5. Запустить игру снова

Если что-то пошло не так — откат (переименовать файлы):

```bat
:: в cmd (Command Prompt):
move /Y "Pocket Change 2.0.mod" "Pocket Change 2.0.mod.broken"
move /Y "Pocket Change 2.0.mod.prev" "Pocket Change 2.0.mod"
```

```powershell
# в PowerShell:
move -Force "Pocket Change 2.0.mod"  "Pocket Change 2.0.mod.broken"
move -Force "Pocket Change 2.0.mod.prev" "Pocket Change 2.0.mod"
```

> `move` — встроенная команда, которая есть у всех Windows (ставится вместе
> с ОС, ничего доустанавливать не нужно). В **cmd** добавьте `/Y` (не
> спрашивать «заменить? да»), в **PowerShell** — `-Force` (разрешить
> перезапись). Вариант `ren` (cmd) работает аналогично, но в PowerShell
> нет — `move` универсальнее.

---

## 📌 Краткая шпаргалка

```
# перевести
./translate_mods.bat "имя" | --force | --no-llm | --list-file f.txt | --include-excluded
# выгрузить CSV
./export_mod_csv.bat "имя"
# пересобрать из CSV
./assemble_mod.bat "имя"
# пересобрать ВСЕ из кеша (без LLM, без CSV)
./rebuild.bat | <Steam-ID> | <имя>
# проверить
./verify_translations.bat [--details] [--fix] [--purge]
# поиск по МОДАМ И ФАЙЛАМ ИГРЫ (kenshi\data\*.mod, kenshi\mods\<мод>, .po)
./search_mods.bat "фраза"                       # поиск + список номеров
./search_mods.bat "фраза" --no-translate        # только поиск (без запуска)
./search_mods.bat "фраза" --yes                 # авто-«все номера»
./search_mods.bat "фраза" --force               # пере-перевести всё заново
./search_mods.bat "a" --ru                      # только RU-совпадения в кеше
# список доступных имён/ID
py .\csv_mod.py --list
```

---

# 📚 Детали для продвинутых

Всего выше достаточно, чтобы запустить и пользоваться. Здесь — как устроено
внутри, ручная установка «от руки» и тонкие настройки. Новичок может
смело пролистать этот отдел.

## ⚙️ Как это устроено внутри (кратко)

- **Словарь `dict.json`** — ваши канонические термины (`exact` = точные строки,
  `words` = слова); вставляется в промпт LLM, подстраховывает перевод скриптом.
- **Показатели из локали игры** — для чанков подтяиваются соответствующие пары
  EN→RU из `gamedata.po` / `main.po` (названия рас, фракций, зданий) — не влезая
  в контекст полностью.
- **Пред-LM фильтры** — строки без латиницы и уже переведённые (в словаре, в локали
  игры, в кеше других модов) **не отправляются** в LLM — экономит токены и время.
- **Чёрный список `exclude.txt`** — моды, которые не переводить (регулярки).
- **Промт `prompt.txt`** — инструкции LLM; текст между `/…/` (теги вроде
  `/HOLYGREET/`) **не переводится**.
- **Сборка перевода** — `.mod` переписывается на месте, старые — сохраняются
  как `.orig_<hash>.backup` / `.prev`.

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
./verify_translations.bat
./search_mods.bat "test"
```
Если ничего не падает — можно переводить:
```
./translate_mods.bat "Pocket Change 2.0"
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

## 🚀 Запуск перевода

```
./translate_mods.bat                        # все моды (спросит [y/N])
./translate_mods.bat "Pocket Change 2.0"    # один мод по имени
./translate_mods.bat 1173662576             # один мод по **Steam-ID** (уникальный номер мода в Workshop,
                                                                 # виден в ссылке steamcommunity.com/shared/filedetails/...)
```

### Флаги

| Флаг | Что делает |
|---|---|
| `--force` | **Пере-перевести всё заново** (игнорирует кэш, резервную копию не трогает) |
| `--no-llm` | **Не ходить в LLM** — только извлечь строки и создать `<имя>.translate.csv` (пустая колонка RU для ручного перевода). Затем правь Excel → `./assemble_mod.bat "имя"` |
| `--include-excluded` | Переводить даже моды из `exclude.txt` |
| `--list-file файл.txt` | Список модов (одна строка = имя-или-ID) |

Примеры:
```
./translate_mods.bat --force "Heavy Crossbow"
./translate_mods.bat --force --list-file мои_моды.txt
./translate_mods.bat --no-llm "Heavy Crossbow"    # только CSV, переведёшь сам
```

### Прогресс
Два прогресс-бара в терминале (верхний `ALL` — все моды, нижний `NOW` — текущий мод),
счёт — **в токенах**. Можно прервать `Ctrl+C` — прогресс сохранится в кеше (`state/`).
Повторный запуск того же мода **продолжит с того места**, где остановился.

---