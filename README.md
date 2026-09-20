# Kenshi RU — Переводчик модов (для пользователя)

Английские моды из Steam Workshop → на русский. Локальный ИИ (qwen) переводит, ты можешь
сам править каждую фразу в `translate.csv` и пересобирать .mod. Ничего не копируется в
`mods\` — перевод пишется **на месте**, в папке мода в Steam, резервная копия оригинала —
рядом (`.orig_<хэш>.backup`).

---

## 📦 Установка (что нужно и как настроить)

Проект рассчитан на **Windows 10/11**. Стоимость: **0 ₽** — всё работает локально (кроме самого Kenshi в Steam).

### 1. Системные требования

| Компонент | Версия | Зачем |
|---|---|---|
| **Windows** | 10/11 | C#-CLI таргет `net9.0-windows` |
| **Python** | 3.10+ (тест на 3.11) | Пайплайн перевода и CSV |
| **.NET SDK** | **9.x** | Собрать `kenshi-modtranslate.dll` (C#-парсер .mod) |
| **Steam + Kenshi** | установленная игра | Моды в `steamapps/workshop/content/233860` |
| **LLM локально** | OpenAI-совместимый, `http://localhost:11234/v1` | Переводчик (qwen3.8:27b и т.п.) |
| **Диск** | ~5 ГБ свободно | Собрка + кеш + резервные копии |

### 2. Шаг за шагом

#### 2.1. Клонировать проект (или скопировать папку)
```
git clone https://github.com/KorolevOl/KenshiModTranslate.git
cd KenshiModTranslate
```

#### 2.2. Python
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

#### 2.3. .NET SDK 9
Установить **.NET 9 SDK** (dotnet.microsoft.com → Downloads → .NET 9 → SDK).
Проверить:
```
dotnet --version          # 9.0.xxx
```
Для сборки C#-CLI нужен **родственный проект `KenshiTranslator`** (csproj ссылается на
`..\KenshiTranslator\KenshiCore`). Структура на диске:
```
папка\\
├─ KenshiModTranslate\\      ← этот репо
│   └─ kenshi-modtranslate.csproj  (ProjectReference: ..\KenshiTranslator\KenshiCore)
└─ KenshiTranslator\\
    └─ KenshiCore\\KenshiCore.csproj
```
Если `KenshiTranslator` ещё нет — скачать (`git clone` того, что у вас в работе, или взять
у того, у кого уже собрана папка), положить **рядом** с `KenshiModTranslate`.
Собрать:
```
cd KenshiModTranslate
dotnet build -c Release
# => bin\Release\net9.0-windows\kenshi-modtranslate.dll
```
> Если `bin\Release\net9.0-windows\kenshi-modtranslate.dll` уже есть — пропустить.

#### 2.4. LLM-сервер (локальный)
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

#### 2.5. Пути в `config.json`
Указать **свои** реальные пути:
```json
"paths": {
  "game":     "E:\\steamlibrary\\steamapps\\common\\kenshi",
  "workshop": "E:\\steamlibrary\\steamapps\\workshop\\content\\233860",
  "dotnet":   "C:\\Program Files\\dotnet\\dotnet.exe",   ← ТВОЙ dotnet
  "modtranslate_cli": "C:\\...\\KenshiModTranslate\\bin\\Release\\net9.0-windows\\kenshi-modtranslate.dll",  ← ТВОЙ DLL
  "state":    "C:\\...\\KenshiModTranslate\\state",
  "mods_dir": "E:\\steamlibrary\\steamapps\\common\\kenshi\\mods"
}
```
| Поле | Что |
|---|---|
| `game` | Каталог игры ( Kenshi, `kenshi.exe` внутри ) |
| `workshop` | Папка Steam Workshop — `content\233860` ( appId Kenshi = 233860 ) |
| `dotnet` | Полный путь к `dotnet.exe` (или `dotnet` в PATH) |
| `modtranslate_cli` | Полный путь к `kenshi-modtranslate.dll` (после `dotnet build`) |
| `state` | Где кеш переводов — можно оставить по умолчанию в папке проекта |

#### 2.6. (Опционально) Словарь / Чёрный список / Промт
Файлы уже есть с разумными дефолтами, можно править:
- `dict.json` — свои «канонические» термины (`exact`, `words` — см. раздел «Словарь терминов»)
- `exclude.txt` — регулярные выражения, какие моды не трогать
- `prompt.txt` — инструкции ИИ (тон, правила, адаптация)

### 3. Прогнать самопроверку (0 LLM, без переводов)
```
verify_translations.bat                # проверит структуру + кеш — если кеш пуст, «нет данных»
python search_mods.py "test"           # проверит, что .mod читаются
```
Если ничего не падает с ошибками — всё готово, можно переводить:
```
translate_mods.bat "Pocket Change 2.0"
```

### 4. Типичные ошибки установки

| Симптом | Причина / Fix |
|---|---|
| `python not found in PATH` | Python не добавлен в PATH — переустановить с галкой |
| `dotnet: command not found` | .NET не в PATH — добавить `C:\Program Files\dotnet` в PATH |
| `dotnet CLI failed: The application to execute does not exist` | `paths.modtranslate_cli` в `config.json` неверен или DLL не собран – `dotnet build -c Release` |
| `KenshiCore.csproj` не найден при сборке | Нет соседнего `..\KenshiTranslator\KenshiCore\KenshiCore.csproj` – скачать рядом |
| `Connection refused: localhost:11234` | LLM-сервер не запущен – поднять ollama/ollama-weldbook |
| `404 /v1/models` | `base_url` в `config.json` неверен |
| `Mod not found` (мод не в списке) | `paths.workshop` не та папка или мод отключён в Steam |

### 5. Обновление проекта
```
cd KenshiModTranslate
git pull
pip install -r requirements.txt    # если requirements.txt поменялся
dotnet build -c Release            # если Program.cs / csproj поменялись
```
Редкий случай: если структура кешей (`state/`) менялась — очистить `state/` (кеш можно терять, LLM переведёт заново).

---

## 📁 Файлы, которые ты трогаешь

| Файл | Зачем |
|---|---|
| `translate_mods.bat` | **Главная кнопка** — переводить мод(ы) |
| `export_mod_csv.bat` | Выгрузить текущий перевод мода в `translate.csv` |
| `assemble_mod.bat` | **Пересобрать .mod** из правленого `translate.csv` |
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

- Пустая 2‑я колонка = строка **не переводится** (остаётся английской).
- Правка = меняешь 2‑ю колонку (1‑ю не трогай — это «якорь»).

### Пересобрать .mod из своего CSV
```
assemble_mod.bat "Pocket Change 2.0"
```
Скрипт берёт `translate.csv` из папки мода, переписывает .mod на месте.
**Старый .mod резервируется** (`.prev`) — откат всегда возможен.

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
| `translate.max_batch_lines` | Макс. строк в одном ИИ-запросе (по умолчанию 180) |
| `translate.temperature` | Креативность (0.7–0.9) |
| `dict` | Ссылка на словарь |
| `exclude_file` | Ссылка на чёрный список |

Меняешь `config.json` → следующий запуск подхватит.

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
| `po_hints_max` | `30` | максимум строк подсказок на чанк |

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
| `dotnet CLI failed` | Нужна `H:\dotnet9\dotnet.exe` (см. `config.json`) |
| Ложный-мод / пустой кеш | `verify_translations.bat --details`, затем `--fix` |
| Неверный порядок/потеря строк | `fix_translations.bat "имя"` — починит только битое |
| Удалить кеш мода | `verify_translations.bat --purge "имя"` |
| Перевести заново | `translate_mods.bat --force "имя"` (резервный остаётся) |

### Резервные копии (на месте, в папке мода)
```
<имя>.mod                       ← текущий (обычно RU)
<имя>.mod.orig_<хэш>.backup    ← оригинал EN (из Steam)
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
# проверить
verify_translations.bat [--details] [--fix] [--purge]
# поиск
python search_mods.py "фраза" [--en|--ru|--dll]
# список доступных имён/ID
python csv_mod.py import --list
```
