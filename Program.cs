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
            if (args.Length >= 4) return DoApply(args[1], args[2], args[3]);
            Console.Error.WriteLine("apply needs 3 args"); return 2;
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

static List<Entry> ExtractEntries(ModData data)
{
    var entries = new List<Entry>();
    var typeCodes = ModRecord.ModTypeCodes.Values;
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
            entries.Add(new Entry { i = entries.Count, key = $"record{record.StringId}_name", original = name });
        if (record.StringFields != null)
            foreach (var kvp in record.StringFields)
            {
                var v = kvp.Value ?? "";
                if (string.IsNullOrWhiteSpace(v) || Entry.Blacklist.Contains(kvp.Key) || Entry.KeyBlacklist.Contains(kvp.Key)) continue;
                entries.Add(new Entry { i = entries.Count, key = $"record{record.StringId}_{kvp.Key}", original = v });
            }
    }
    return entries;
}

static int DoExtract(string modPath, string outJson)
{
    if (!File.Exists(modPath)) { Console.Error.WriteLine($"mod not found: {modPath}"); return 1; }
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

static int DoApply(string modPath, string mappingJson, string outMod)
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
        var us = rest.IndexOf('_');
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
