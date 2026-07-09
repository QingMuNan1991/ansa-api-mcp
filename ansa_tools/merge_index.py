"""Merge the legacy (v24.1.1) index with the freshly generated v25.1.4 pydev index.

Why merge instead of replace:
- The v25.1.4 pydev autocomplete stubs are INCOMPLETE: they omit ~180 functions
  that the legacy HTML-derived index documented (checks like AbaqusDependency,
  Connections, Contacts, Cracks, Coupling, ...). Replacing the old index would
  silently drop those.
- Neither pydev nor the v25.1.4 HTML `generated` dir contains a few core
  functions (e.g. DeleteElements / MeshCreateShell) — those were never in the
  MCP index at all, so there is no regression there.

Strategy: keep ALL legacy functions as the base (rich HTML descriptions +
high-quality AI keywords + categories), then add only the pydev functions whose
*name* is not already present. Pydev additions get offline keywords + categories.

Usage:
    python ansa_tools/merge_index.py [path_to_legacy_index.json]
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from generate_index_from_pydev import (  # noqa: E402
    assign_categories, build_keywords, regenerate_txt_docs,
)

NEW_PATH = os.path.join(HERE, "ansa_api_index.json")  # pydev-generated v25.1.4
API_VERSION = "v25.1.4"
LEGACY_DEFAULT = r"C:\Users\xumao\WorkBuddy\2026-07-09-09-55-40\old_index_v2411.json"


def main():
    legacy_path = sys.argv[1] if len(sys.argv) > 1 else LEGACY_DEFAULT
    if not os.path.exists(legacy_path):
        # fall back to the committed version via git
        import subprocess
        print(f"  legacy file not found at {legacy_path}; trying git HEAD...")
        legacy_path = os.path.join(ROOT, "_legacy_tmp.json")
        subprocess.run(
            ["git", "show", "HEAD:ansa_tools/ansa_api_index.json"],
            cwd=ROOT, stdout=open(legacy_path, "w", encoding="utf-8"), check=True,
        )

    old = json.load(open(legacy_path, encoding="utf-8"))
    new = json.load(open(NEW_PATH, encoding="utf-8"))
    old_funcs = old["functions"]
    new_funcs = new["functions"]
    old_names = {f["name"] for f in old_funcs}

    merged = list(old_funcs)  # base: preserve rich docs + AI keywords + categories
    added = 0
    for f in new_funcs:
        if f["name"] in old_names:
            continue
        assign_categories([f])
        if not f.get("keywords"):
            f["keywords"] = build_keywords(
                f["name"], f["module"], f.get("description", ""), None)
        merged.append(f)
        added += 1

    merged.sort(key=lambda f: (f["module"], f["name"]))

    # Backfill keywords for any function that lacks them (legacy entries that
    # never received AI keywords, plus any new pydev entry missed above).
    for f in merged:
        if not f.get("keywords"):
            f["keywords"] = build_keywords(
                f["name"], f["module"], f.get("description", ""), None)

    modules = sorted({f["module"] for f in merged})
    index = {
        "metadata": {
            "api_version": API_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_functions": len(merged),
            "modules": modules,
            "note": ("Merged legacy v24.1.1 core (rich docs + AI keywords) with "
                     "v25.1.4 pydev autocomplete-stub additions."),
        },
        "functions": merged,
    }
    with open(NEW_PATH, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2)
    shutil.copyfile(NEW_PATH, os.path.join(ROOT, "ansa_api_index.json"))

    regenerate_txt_docs(merged, os.path.join(HERE, "txt_docs"))

    print(f"Merged index: {len(old_funcs)} legacy + {added} new pydev "
          f"= {len(merged)} total across {len(modules)} modules "
          f"(api_version={API_VERSION}).")
    print(f"  -> {NEW_PATH}")


if __name__ == "__main__":
    main()
