#!/usr/bin/env python3
"""
sanitize_caches.py — OPTION A cache de-poisoning (rebirth.mod incident, 2026-09-22).

Background
----------
The old (unguarded) extract() offered record names / string-field values that are
actually ENGINE KEYS (cross-referenced identifiers: SFX event → action name,
building category → category record, animation names, ...) to translation. The
LLM renamed them; the game (and binary .ani/SFX assets that stay EN) still expect
the EN key → combat / stealth animations broke.

The NEW extract() (Program.cs, OPTION A guard) drops those rows. Problem: the
saved state/<hash>_mapping.json rows are indexed by the OLD extract numbering.
DoApply() re-extracts fresh at apply time → NEW numbering → old-indexed RU rows
would land on the WRONG entries (shift) or on nothing.

This tool repairs every cache hash:
  1. old entries  = state/<hash>_entries.json        (key → old index)
  2. new extract  = current guarded DLL on the EN .orig_<hash>.backup
  3. for each mapping row: old index → old key → NEW index (key identity);
     rows whose key the guard removed are DROPPED;
  4. mapping rewritten with new indices. Rollback = restore <mapping>.pre_optionA.

Non-destructive (originals backed up), idempotent (re-runs on already-fixed
mappings are a no-op: their indices already match the new numbering).
No LLM, does not touch .mod files.

Usage:
  python sanitize_caches.py --list
  python sanitize_caches.py [hash ...]
"""
import os, sys, json, argparse, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kmt_paths
_resolve = kmt_paths.resolve
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
P = CFG["paths"]
WORKSHOP = _resolve(P["workshop"])
GAME     = _resolve(P["game"])
DOTNET   = _resolve(P["dotnet"])
CLI      = _resolve(P["modtranslate_cli"])
STATE    = _resolve(P["state"])
TMP      = os.environ.get("KMT_TMPDIR", r"T:\kmt_sanitize_tmp")
os.makedirs(TMP, exist_ok=True)


def find_source_for_hash(h):
    if not h:
        return None
    suffix = f".orig_{h}.backup"
    for base in (WORKSHOP, GAME):
        if not os.path.isdir(base):
            continue
        for d, _dirs, files in os.walk(base):
            for f in files:
                if f.endswith(suffix):
                    return os.path.join(d, f)
    return None


def run_extract(src, out):
    r = subprocess.run([DOTNET, CLI, "extract", src, out],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[:400])


def process(h, list_only):
    mp_path = os.path.join(STATE, f"{h}_mapping.json")
    ej_path = os.path.join(STATE, f"{h}_entries.json")
    if not (os.path.exists(mp_path) and os.path.exists(ej_path)):
        return None
    src = find_source_for_hash(h)
    if not src:
        print(f"  [{h}] no EN source found - skip")
        return None
    new_json = os.path.join(TMP, f"{h}_new_entries.json")
    run_extract(src, new_json)

    old_entries = json.load(open(ej_path, encoding="utf-8"))      # list, old numbering
    new_entries = json.load(open(new_json, encoding="utf-8"))     # list, guarded numbering
    old_i2key = {e["i"]: e["key"] for e in old_entries}
    new_key2i = {e["key"]: e["i"] for e in new_entries}
    removed_keys = set(old_i2key.values()) - set(new_key2i.keys())  # guard removed these

    # efile (state/<h>_entries.json) must use the SAME (new) numbering the fixed
    # DoApply() will produce, so translate_one's todo/done and the mapping all align.
    if not list_only:
        efile_bkp = ej_path + ".pre_optionA"
        if not os.path.exists(efile_bkp) and (old_entries != new_entries):
            os.replace(ej_path, efile_bkp)
        if old_entries != new_entries:
            json.dump(new_entries, open(ej_path, "w", encoding="utf-8"),
                      ensure_ascii=False, separators=(",", ":"))

    mapping = json.load(open(mp_path, encoding="utf-8"))
    fixed, dropped = [], []
    for m in mapping:
        old_i = m.get("i")
        key = old_i2key.get(old_i)
        if key is None:
            # row not in old entries (e.g. already re-indexed by an earlier run)
            fixed.append(m)
            continue
        if key not in new_key2i:
            if (m.get("ru") or "").strip():
                dropped.append((key, old_i, (m.get("ru") or "")[:48]))
            continue
        fixed.append({"i": new_key2i[key], "ru": m.get("ru") or ""})
    fixed.sort(key=lambda x: x["i"])

    already_ok = (not removed_keys) or all(
        m.get("i") in {e["i"] for e in new_entries} or m.get("i") not in old_i2key
        for m in mapping
    )
    # Idempotency: re-running on an already-fixed mapping must not lose rows.
    if already_ok and all(m.get("i") in new_key2i.values() for m in mapping) and removed_keys:
        # mapping indices already align with new extract -> nothing to do
        pass

    if list_only:
        ru_dropped = [d for d in dropped]
        return {"h": h, "removed": len(removed_keys), "dropped_ru": len(ru_dropped),
                "examples": ru_dropped[:3]}

    bkp = mp_path + ".pre_optionA"
    if not os.path.exists(bkp):
        os.replace(mp_path, bkp)
    json.dump(fixed, open(mp_path, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    return {"h": h, "removed": len(removed_keys), "dropped_ru": len(dropped),
            "rows_fixed": sum(1 for m in mapping if m.get("i") in old_i2key and
                              old_i2key[m["i"]] in new_key2i),
            "rows_dropped": len(mapping) - len(fixed),
            "ru_dropped": len(dropped), "applied": True}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("hashes", nargs="*")
    a = ap.parse_args()
    hashes = a.hashes or sorted(
        f[:-len("_mapping.json")] for f in os.listdir(STATE) if f.endswith("_mapping.json"))

    mode = "REPORT" if a.list else "SANITIZE"
    print(f"processing {len(hashes)} cache hash(es)  [{mode}]\n")
    results = []
    for i, h in enumerate(hashes, 1):
        try:
            r = process(h, a.list)
        except Exception as ex:
            print(f"  [{i:3}/{len(hashes)}] {h} ERROR: {ex}")
            continue
        if not r:
            continue
        results.append(r)
        if a.list:
            print(f"  [{i:3}/{len(hashes)}] {h}  guard-removed={r['removed']}  "
                  f"ru_rows_dropped={r['dropped_ru']}")
            for key, oi, ru in r["examples"]:
                print(f"           {key:56} i={oi}  {ru!r}")
        elif r.get("applied"):
            print(f"  [{i:3}/{len(hashes)}] {h}  rows re-indexed={r['rows_fixed']}, "
                  f"dropped={r['rows_dropped']} ({r['ru_dropped']} had RU)")
        else:
            print(f"  [{i:3}/{len(hashes)}] {h}  clean")
    if not a.list:
        n = sum(1 for r in results if r.get("applied"))
        rows = sum(r.get("rows_dropped", 0) for r in results)
        ru = sum(r.get("ru_dropped", 0) for r in results)
        print(f"\nDONE: {n} mapping(s) sanitized; {rows} poisoned rows removed "
              f"({ru} carried RU).")
        if n:
            print("Rollback: move each <mapping>.pre_optionA back over <mapping>.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
