using System.Text;
using System.Text.Json;
using KenshiCore.Mods;
using KenshiCore.ReverseEngineering;

// kenshi-modtranslate: extract translatable strings from a .mod and apply translations back.
//   extract <mod> <entries.json>
//   apply   <mod> <mapping.json> <out.mod>


if (args.Length < 3)
{
    Console.Error.WriteLine("usage: kenshi-modtranslate extract <mod> <entries.json>");
    Console.Error.WriteLine("       kenshi-modtranslate apply <mod> <mapping.json> <out.mod>");
    return 2;
}
try
{
    switch (args[0])
    {
        case "extract": return DoExtract(args[1], args[2]);
        case "apply":
            if (args.Length >= 4) return DoApply(args[1], args[2], args[3], args.Length >= 5 ? args[4] : null);
            Console.Error.WriteLine("apply needs 3 args [optional 4th: keep-only record-id substring]"); return 2;
        default:
            Console.Error.WriteLine($"unknown verb: {args[0]}");
            return 2;
    }
}
catch (Exception ex)
{
    Console.Error.WriteLine($"ERROR: {ex.Message}");
    return 1;
}

// (KEY_NAME_TYPES moved inside ExtractEntries: top-level program cannot hold fields)
static List<Entry> ExtractEntries(ModData data)
{
    var entries = new List<Entry>();
    var typeCodes = ModRecord.ModTypeCodes.Values;

    // OPTION A (2026-09-22, rebirth.mod incident): cross-reference guard.
    // A string that is BOTH a record.Name AND a field value of some record is a
    // key other records reference (SFX events -> action names, building category
    // -> category record name, ...). Renaming one side without the other desyncs
    // the binding (combat/stealth animations, technique triggers, SFX). Exclude
    // every such string from the translatable set. Normalization: trim + casefold.
    var nameSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    var valueSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    if (data.Records != null)
    {
        foreach (var r in data.Records)
        {
            if (!string.IsNullOrWhiteSpace(r.Name)) nameSet.Add(r.Name.Trim());
            if (r.StringFields != null)
                foreach (var kv in r.StringFields)
                    if (!string.IsNullOrWhiteSpace(kv.Value)) valueSet.Add(kv.Value.Trim());
        }
    }
    int xrefExcluded = 0, animKeyExcluded = 0;
    // Heuristic (2026-09-22, «Buried Treasure» incident, Bury Your Treasure mod):
    // an xref string (both record.Name and a field value) is a KEY (do not translate)
    // only if it LOOKS like an identifier: underscore/dash (wood_dex_dummy_pole,
    // house03-base) or a no-space token with digits (T34, Mk.II). Xref strings that
    // look like display text (spaces, no _) are internal name<->field pairs (building
    // groups, quest flags) — both sides live in the same .mod and are translated
    // consistently together (DoApply applies ONE translation to all equal originals).
    // Animation-type names stay excluded unconditionally (external .ani refs).
    static bool IsKeyLike(string? v)
    {
        if (v == null) return true;
        var s = v.Trim();
        if (s.Contains('_') || s.Contains('-')) return true;
        if (s.Any(c => c >= '0' && c <= '9') && !s.Any(char.IsWhiteSpace)) return true;
        return false;
    }
    // Record types whose Name is ALWAYS an engine key (animation asset refs),
    // never user-visible text. (KenshiCore.ModTypeCodes: 5=ANIMAL_ANIMATION, 24=ANIMATION,
    // 105=ANIMATION_EVENT, 112=ANIMATION_FILE, 17=COMBAT_TECHNIQUE)
    var keyNameTypes = new HashSet<int> { 5, 17, 24, 105, 112 };
    static bool IsXref(string? v, HashSet<string> n, HashSet<string> vals)
        => v != null && !string.IsNullOrWhiteSpace(v)
           && n.Contains(v.Trim()) && vals.Contains(v.Trim());
    // 2026-09-19: FileType 16 И 17. v17 хранит Description в блоке Details
    // (ReverseEngineer.TryParseDetails выносит его в Header.Description).
    // Раньше условие ==16 молча пропускало ВСЕ v17-моды (31 «no mapping»).
    if (data.Header != null && (data.Header.FileType == 16 || data.Header.FileType == 17)
        && !string.IsNullOrEmpty(data.Header.Description))
    {
        var desc = data.Header.Description;
        if (desc.Length > 999) desc = desc.Substring(0, 999);
        entries.Add(new Entry { i = entries.Count, key = "description", original = desc });
    }
    if (data.Records == null) return entries;
    foreach (var record in data.Records)
    {
        var name = record.Name ?? "";
        if (!string.IsNullOrEmpty(name) && !typeCodes.Any(s => name.Contains(s)))
        {
            // OPTION A: skip names that are engine keys (anim types) or cross-referenced strings
            if (keyNameTypes.Contains(record.RecordType)) { animKeyExcluded++; continue; }
            if (IsXref(name, nameSet, valueSet) && IsKeyLike(name)) { xrefExcluded++; continue; }
            entries.Add(new Entry { i = entries.Count, key = $"record{record.StringId}_name", original = name });
        }
        if (record.StringFields != null)
            foreach (var kvp in record.StringFields)
            {
                var v = kvp.Value ?? "";
                if (string.IsNullOrWhiteSpace(v) || Entry.Blacklist.Contains(kvp.Key) || Entry.KeyBlacklist.Contains(kvp.Key)) continue;
                // OPTION A: also skip field values that are cross-referenced names
                //   AND look like identifiers (SFX/bone/mesh keys). Display-text xrefs
                //   (building groups etc.) are translated — both sides move together.
                if (IsXref(v, nameSet, valueSet) && IsKeyLike(v)) { xrefExcluded++; continue; }
                entries.Add(new Entry { i = entries.Count, key = $"record{record.StringId}_{kvp.Key}", original = v });
            }
    }
    if (xrefExcluded > 0 || animKeyExcluded > 0)
        Console.Error.WriteLine($"guards: excluded {xrefExcluded} cross-referenced strings, {animKeyExcluded} anim-key names");
    return entries;
}

static int DoExtract(string modPath, string outJson)
{
    if (!File.Exists(modPath)) { Console.Error.WriteLine($"mod not found: {modPath}"); return 1; }
    // 2026-09-26 SAFETY: выходной JSON НИКОГДА не должен писать поверх .mod
    // (инцидент: неверный 2-й аргумент = путь к .mod → JSON-дамп затирал бинарный мод,
    //  три файла пострадали; восстановление только по бэкапам).
    var oj = outJson.Trim();
    if (oj.EndsWith(".mod", System.StringComparison.OrdinalIgnoreCase))
    {
        Console.Error.WriteLine($"REFUSED: outJson '{outJson}' заканчивается .mod — extract пишет JSON, не мод. Укажи .json-файл (2 аргумента: <modfile> <out.json>).");
        return 2;
    }
    var re = new ReverseEngineer();
    re.LoadModFile(modPath);
    if (re.modData == null) { Console.Error.WriteLine("no modData parsed"); return 1; }
    if (re.modData.Records == null) { Console.Error.WriteLine("no records parsed"); return 1; }

    var entries = ExtractEntries(re.modData);
    var json = JsonSerializer.Serialize(entries, new JsonSerializerOptions
    {
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping
    });
    File.WriteAllText(outJson, json, new UTF8Encoding(false));

    Console.Error.WriteLine($"records: {re.modData.Records.Count}");
    Console.Error.WriteLine($"translatable entries: {entries.Count}");
    var byType = re.modData.Records.GroupBy(r => ModRecord.ModTypeCodes.TryGetValue(r.RecordType, out var nm) ? nm : $"T{r.RecordType}").OrderByDescending(g => g.Count())
        .Select(g => $"{g.Key}:{g.Count()}").Take(10);
    Console.Error.WriteLine("types: " + string.Join("  ", byType));
    Console.Error.WriteLine($"wrote {outJson}");
    return 0;
}

static int DoApply(string modPath, string mappingJson, string outMod, string? keepOnly = null)
{
    if (!File.Exists(modPath)) { Console.Error.WriteLine($"mod not found: {modPath}"); return 1; }
    if (!File.Exists(mappingJson)) { Console.Error.WriteLine($"mapping not found: {mappingJson}"); return 1; }

    var re = new ReverseEngineer();
    re.LoadModFile(modPath);
    if (re.modData == null || re.modData.Records == null) { Console.Error.WriteLine("no mod data"); return 1; }

    var entries = ExtractEntries(re.modData);
    var map = JsonSerializer.Deserialize<List<MappingEntry>>(File.ReadAllText(mappingJson, Encoding.UTF8))!
        .Where(m => m.ru != null && m.ru.Length > 0)
        .ToDictionary(m => m.i, m => m.ru);

    int applied = 0;
    var records = re.modData.Records;
    bool keepOnlyActive = keepOnly != null && keepOnly.Length > 0;
    int dropped = 0;
    // (2026-09-24) keepOnly: если задан substring (например "Medieval_Crossbows"),
    // из output удаляются ВСЕ чужие записи — только объект-записи этого мода
    // остаются. Это защищает translation-оверлей от перезаписи базовой локали
    // игры (Sand Ninja→«Ниндзя» и т.п. не должны слетать из-за перевода мода).
    // НОВЫЙ РЕЖИМ 2026-09-24: keepOnly = JSON-массив точных StringId записей
    // (["id1","id2",...]) — keep ТОЛЬКО их. Точный режим нужен, когда внутреннее
    // имя-namespace записи НЕ равно видимому имени мода (Great Beak Things:
    // строки лежат в ns "High Beak Things.mod" + "rebirth.mod" — substring
    // "Great Beak Things" ничего не находит → оверлей выходит пустым, только
    // description). Python строит список из mapping (i → entries[i].key).
    if (keepOnlyActive)
    {
        int before = records.Count;
        if (keepOnly.TrimStart().StartsWith("["))
        {
            try
            {
                var ids = JsonSerializer.Deserialize<HashSet<string>>(keepOnly,
                    new JsonSerializerOptions { Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping });
                re.modData.Records = records.Where(r =>
                    r.StringId != null && ids.Contains(r.StringId)
                ).ToList();
            }
            catch
            {
                re.modData.Records = records.Where(r =>
                    r.StringId != null && r.StringId.Contains(keepOnly, StringComparison.OrdinalIgnoreCase)
                ).ToList();
            }
        }
        else
        {
            re.modData.Records = records.Where(r =>
                r.StringId != null && r.StringId.Contains(keepOnly, StringComparison.OrdinalIgnoreCase)
            ).ToList();
        }
        dropped = before - re.modData.Records.Count;
        bool exactMode = keepOnly.TrimStart().StartsWith("[");
        Console.Error.WriteLine($"keepOnly: {re.modData.Records.Count} осталось, {dropped} удалено (режим: {(exactMode ? "точные StringId" : "substring")})");
        records = re.modData.Records;
    }
    // (2026-09-22) NOTE on the rebirth incident: extract() is the enforced guard —
    // it excludes cross-referenced names and anim-type names from `entries`. apply()
    // only writes what extract() returned, so stale/poisoned mapping rows for those
    // keys are simply ignored here (map index not in the live entries set).
    foreach (var e in entries)
    {
        if (!map.TryGetValue(e.i, out var trans)) continue;
        if (e.key == "description")
        {
            re.modData.Header!.Description = trans;
            applied++;
            continue;
        }
        var rest = e.key.Substring("record".Length);
        var us = rest.LastIndexOf('_');
        if (us <= 0) continue;
        var idPart = rest.Substring(0, us);
        var field = rest.Substring(us + 1);
        var record = records.FirstOrDefault(r => r.StringId == idPart);
        if (record == null) continue;
        if (field == "name") { record.Name = trans; applied++; }
        else if (record.StringFields != null && record.StringFields.ContainsKey(field))
        { record.StringFields[field] = trans; applied++; }
    }

    Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outMod))!);
    re.SaveModFile(outMod);
    Console.Error.WriteLine($"applied: {applied} / {entries.Count} non-empty translations");
    Console.Error.WriteLine($"wrote {outMod}");
    return 0;
}

class Entry
{
    public static readonly HashSet<string> Blacklist = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "bone name", "placeholder", "particle system", "slave anim", "anim name",
        "filenames prefix", "carry bone", "stringvar", "class name",
        "layout exterior", "layout interior",
    };
    public static readonly HashSet<string> KeyBlacklist = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "file name", "image file", "sound file", "texture", "prefab name",
        "prefab file", "mesh file", "skin file", "script file", "data file", "animation file"
    };
    public int i { get; set; }
    public string key { get; set; } = "";
    public string original { get; set; } = "";
}
class MappingEntry
{
    public int i { get; set; }
    public string ru { get; set; } = "";
}
