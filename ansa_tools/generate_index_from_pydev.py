"""Rebuild ansa_api_index.json from the ANSA v25.1.4 pydev autocomplete stubs.

Source of truth:  .../ansa_v25.1.4/.../_downloads/autocomplete/py_dev/pydev_ansa/ansa/*.py
These stubs are what `import ansa` exposes at runtime, so they are the authoritative
v25.1.4 API surface (functions, classes, module-level constants, methods).

This script is dependency-free (stdlib only) at runtime and needs NO network / API key:
- categories reuse the project's `CategoryAssigner` (generate_index.py)
- keywords are generated deterministically offline (CamelCase split + EN->CN dict),
  and any keyword set already present in the OLD index (matched by function name) is
  carried over so the high-quality AI keywords are preserved.

Usage:
    python ansa_tools/generate_index_from_pydev.py
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
import warnings
from collections import OrderedDict
from datetime import datetime, timezone

warnings.filterwarnings("ignore", category=SyntaxWarning)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# NOTE: we intentionally do NOT import generate_index (it transitively imports
# bs4 via parse_html). The category/save helpers below are inlined (copied
# verbatim from generate_index.py) so this generator is stdlib-only and needs
# no network / API key / bs4 at runtime.
from ansa_tools.generate_keywords import _EN_TO_CN, _add_chinese_keywords  # noqa: E402


# --------------------------------------------------------------------------- #
# Inlined from generate_index.py (CategoryAssigner / assign_categories / save_index)
# --------------------------------------------------------------------------- #
class CategoryAssigner:
    @classmethod
    def _assign_mesh_cat(cls, name: str) -> str:
        patterns = {
            "mesh_create": ["Create", "MeshCreate", "New"],
            "mesh_edit": ["Edit", "Modify", "Set", "Delete", "Remove", "Clear",
                          "Move", "Rotate", "Transform", "Align", "Offset", "Project"],
            "mesh_quality": ["Quality", "Check", "Find", "Penetration", "Intersect", "Overlap"],
            "mesh_query": ["Get", "Collect", "Count", "List", "Info", "Exist", "Is"],
            "mesh_special": ["Skin", "Offset", "Extrude", "Revolve", "Spline", "Fill", "Map"],
        }
        for cat, keys in patterns.items():
            if any(k in name for k in keys):
                return cat
        return "mesh_misc"

    @classmethod
    def _assign_base_cat(cls, name: str) -> str:
        if "Check" in name:
            return "base_check"
        if any(k in name for k in ["Get", "Collect", "Find", "Query", "Info", "Exist", "Count"]):
            return "base_query"
        if any(k in name for k in ["Set", "Create", "New", "Add", "Make"]):
            return "base_create"
        if any(k in name for k in ["Delete", "Remove", "Clear", "Destroy"]):
            return "base_delete"
        if any(k in name for k in ["Edit", "Modify", "Update", "Change"]):
            return "base_edit"
        return "base_misc"

    @classmethod
    def from_name(cls, name: str) -> str:
        base = [
            ("Check", "check"), ("Quality", "quality"), ("Penetration", "penetration"),
            ("Find", "find"), ("Search", "search"), ("Get", "get"), ("Collect", "collect"),
            ("Create", "create"), ("New", "new"), ("Add", "add"), ("Set", "set"),
            ("Delete", "delete"), ("Remove", "remove"), ("Edit", "edit"), ("Modify", "modify"),
            ("Import", "import"), ("Export", "export"), ("Save", "save"), ("Load", "load"),
            ("Mesh", "mesh"), ("Element", "element"), ("Node", "node"), ("Connection", "connection"),
            ("Report", "report"), ("Calculate", "calculate"), ("Compute", "compute"),
            ("Transform", "transform"), ("Align", "align"), ("Project", "project"),
            ("Batch", "batch"), ("Run", "run"), ("Execute", "execute"),
        ]
        for key, cat in base:
            if key in name:
                return cat
        return "unknown"


def assign_categories(functions):
    for func in functions:
        name = func.get("name", "")
        module = func.get("module", "")
        if module == "ansa.mesh":
            func["category"] = CategoryAssigner._assign_mesh_cat(name)
        elif module == "ansa.base":
            func["category"] = CategoryAssigner._assign_base_cat(name)
        else:
            cat = CategoryAssigner.from_name(name)
            if cat == "unknown":
                func["category"] = module.split(".")[-1] + "_misc"
            else:
                func["category"] = cat
    return functions


def save_index(functions, output_path, api_version, modules):
    index = {
        "metadata": {
            "api_version": api_version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_functions": len(functions),
            "modules": modules,
        },
        "functions": functions,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

PYDEV = r"D:\Programs\BETA_CAE_Systems\ansa_v25.1.4\docs\extending\python_api\html\_downloads\autocomplete\py_dev\pydev_ansa\ansa"
API_VERSION = "v25.1.4"
OLD_INDEX = os.path.join(HERE, "ansa_api_index.json")  # the one we are about to replace

# Modules we deliberately exclude (META GUI toolkit / pure re-export shim)
EXCLUDE_MODULES = {"ansa.guitk", "ansa.script"}


# --------------------------------------------------------------------------- #
# Docstring parsing (NumPy style: Parameters / Returns / Examples)
# --------------------------------------------------------------------------- #
def _split_sections(doc: str):
    """Return dict with keys desc/parameters/returns/examples from a NumPy docstring."""
    out = {"desc": "", "parameters": [], "returns": "", "examples": ""}
    if not doc:
        return out
    lines = doc.splitlines()
    # find header positions
    sections = {}  # name -> start_line_index (first content line after the ---)
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if i + 1 < n:
            nxt = lines[i + 1].strip()
            if line in ("Parameters", "Returns", "Examples", "Attributes", "Raises", "Notes", "See Also") \
                    and re.fullmatch(r"[-=]{3,}", nxt):
                # content starts after the dash line
                j = i + 2
                while j < n and lines[j].strip() == "":
                    j += 1
                sections[line] = j
                i = j
                continue
        i += 1

    # description = everything before first section header
    first_section_line = min(sections.values()) if sections else n
    # find the header line index (line before the dash)
    desc_end = n
    for idx, ln in enumerate(lines):
        s = ln.strip()
        if s in ("Parameters", "Returns", "Examples", "Attributes", "Raises", "Notes", "See Also") \
                and idx + 1 < n and re.fullmatch(r"[-=]{3,}", lines[idx + 1].strip()):
            desc_end = idx
            break
    out["desc"] = "\n".join(lines[:desc_end]).strip()

    # Parameters
    if "Parameters" in sections:
        start = sections["Parameters"]
        end = n
        for name in ("Returns", "Examples", "Attributes", "Raises", "Notes", "See Also"):
            if name in sections and sections[name] > start:
                end = min(end, sections[name])
                break
        block = lines[start:end]
        cur = None
        for bl in block:
            if not bl.strip():
                continue
            # param header line: "name : type"
            m = re.match(r"^(\w+)\s*:\s*(.*)$", bl)
            if m and not bl.startswith(" ") and not bl.startswith("\t"):
                cur = {"name": m.group(1), "type": m.group(2).strip(), "desc": ""}
                out["parameters"].append(cur)
            elif cur is not None:
                cur["desc"] = (cur["desc"] + " " + bl.strip()).strip()
        # clean param types that contain newlines
        for p in out["parameters"]:
            p["type"] = p["type"].replace("\n", " ").strip()

    # Returns
    if "Returns" in sections:
        start = sections["Returns"]
        end = n
        for name in ("Examples", "Attributes", "Raises", "Notes", "See Also"):
            if name in sections and sections[name] > start:
                end = min(end, sections[name])
                break
        ret_lines = [l.strip() for l in lines[start:end] if l.strip()]
        # first line often the type, rest the description
        out["returns"] = " ".join(ret_lines).strip()

    # Examples
    if "Examples" in sections:
        start = sections["Examples"]
        ex = []
        for l in lines[start:]:
            # strip the "::" marker line
            if l.strip() == "::":
                continue
            ex.append(l)
        # drop leading blank lines
        while ex and ex[0].strip() == "":
            ex.pop(0)
        # dedent
        nonempty = [l for l in ex if l.strip() != ""]
        if nonempty:
            indent = min(len(l) - len(l.lstrip()) for l in nonempty)
            ex = [l[indent:] if len(l) >= indent else l for l in ex]
        out["examples"] = "\n".join(ex).strip()

    return out


# --------------------------------------------------------------------------- #
# Signature reconstruction from AST
# --------------------------------------------------------------------------- #
def _ann(node):
    if node is None:
        return "any"
    try:
        return ast.unparse(node)
    except Exception:
        return "any"


def _sig_from_args(args, module, name, self_in_first=True):
    parts = []
    all_pos = list(args.posonlyargs) + list(args.args)
    defaults = list(args.defaults)
    n_no_def = len(all_pos) - len(defaults)
    started = False
    for i, a in enumerate(all_pos):
        ann = _ann(a.annotation)
        if i >= n_no_def:
            default = defaults[i - n_no_def]
            parts.append(f"{a.arg}: {ann} = {_ann(default)}")
        else:
            parts.append(f"{a.arg}: {ann}")
    if args.vararg:
        parts.append(f"*{args.vararg.arg}: {_ann(args.vararg.annotation)}")
    # kwonly
    for i, a in enumerate(args.kwonlyargs):
        ann = _ann(a.annotation)
        dflt = args.kw_defaults[i]
        if dflt is not None:
            parts.append(f"{a.arg}: {ann} = {_ann(dflt)}")
        else:
            parts.append(f"{a.arg}: {ann}")
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}: {_ann(args.kwarg.annotation)}")
    # drop leading self/cls
    if self_in_first and parts and parts[0].split(":")[0].strip() in ("self", "cls"):
        parts = parts[1:]
    sig = f"{module}.{name}({', '.join(parts)})"
    return sig


def _build_sig(func_node, module, name, self_in_first=True):
    sig = _sig_from_args(func_node.args, module, name, self_in_first)
    ret = _ann(func_node.returns)
    if ret and ret != "any":
        sig += f" -> {ret}"
    return sig


# --------------------------------------------------------------------------- #
# Parse one pydev module file
# --------------------------------------------------------------------------- #
def parse_module_file(path: str, module: str) -> list[dict]:
    src = open(path, encoding="utf-8", errors="ignore").read()
    tree = ast.parse(src)
    entries = []

    def make_entry(name, sig, doc, is_method=False, parent_class=None):
        d = _split_sections(doc)
        entry = {
            "name": name,
            "module": module,
            "signature": sig,
            "description": d["desc"],
            "parameters": d["parameters"],
            "returns": d["returns"],
            "examples": d["examples"],
        }
        return entry

    for idx, node in enumerate(tree.body):
        if isinstance(node, ast.FunctionDef):
            if node.name.startswith("_"):
                continue
            sig = _build_sig(node, module, node.name, self_in_first=False)
            entries.append(make_entry(node.name, sig, ast.get_docstring(node)))

        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            doc = ast.get_docstring(node) or ""
            init = None
            methods = []
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef):
                    if sub.name == "__init__":
                        init = sub
                    elif not sub.name.startswith("_"):
                        methods.append(sub)
            if init is not None:
                sig = _build_sig(init, module, node.name, self_in_first=True)
            else:
                sig = f"{module}.{node.name}()"
            d = _split_sections(doc)
            entries.append({
                "name": node.name,
                "module": module,
                "signature": sig,
                "description": d["desc"],
                "parameters": d["parameters"],
                "returns": d["returns"],
                "examples": d["examples"],
            })
            # also expose the class's public methods as their own searchable entries
            # (e.g. spdrm.process.Run, vr.VR.Create, base.Check.run) — these are the
            # real callable API surface in ANSA.
            for m in methods:
                md = _split_sections(ast.get_docstring(m) or "")
                msig = _build_sig(m, module, f"{node.name}.{m.name}", self_in_first=True)
                entries.append({
                    "name": f"{node.name}.{m.name}",
                    "module": module,
                    "signature": msig,
                    "description": md["desc"],
                    "parameters": md["parameters"],
                    "returns": md["returns"],
                    "examples": md["examples"],
                })

        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            # module-level constant (e.g. ansa.constants.NASTRAN)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value if isinstance(node, ast.Assign) else node.value
            # pydev puts the docstring in a following Expr string node
            doc = ""
            nxt = tree.body[idx + 1] if idx + 1 < len(tree.body) else None
            if isinstance(nxt, ast.Expr) and isinstance(getattr(nxt, "value", None), ast.Constant) \
                    and isinstance(nxt.value.value, str):
                doc = nxt.value.value
            for t in targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    val = _ann(value) if value is not None else ""
                    sig = f"{module}.{t.id} = {val}" if val else f"{module}.{t.id}"
                    d = _split_sections(doc)
                    entries.append({
                        "name": t.id,
                        "module": module,
                        "signature": sig,
                        "description": d["desc"],
                        "parameters": [],
                        "returns": "",
                        "examples": d["examples"],
                    })
    return entries


# --------------------------------------------------------------------------- #
# Keyword generation (offline)
# --------------------------------------------------------------------------- #
def _name_tokens(name: str) -> list[str]:
    # split CamelCase and underscores
    parts = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z][a-z]*|[a-z]+|\d+", name)
    toks = [p.lower() for p in parts if p]
    # also keep the raw lowercased name
    return toks


def build_keywords(name: str, module: str, description: str, carryover: list[str] | None) -> list[str]:
    kws: list[str] = []
    seen = set()

    def add(k):
        if not k:
            return
        k = k.strip()
        if not k:
            return
        kl = k.lower()
        if kl not in seen:
            seen.add(kl)
            kws.append(k)

    # carry over existing high-quality keywords if present
    if carryover:
        for k in carryover:
            add(k)

    # name tokens (English)
    toks = _name_tokens(name)
    for t in toks:
        add(t)
    # module tokens
    for m in module.split("."):
        if m and m != "ansa":
            add(m)
    # Chinese translations of name tokens
    cn = []
    for t in toks:
        if t in _EN_TO_CN:
            cn.append(_EN_TO_CN[t])
    for c in cn:
        add(c)
    # module-level CN (ansa.mesh -> 网格 etc.)
    for m in module.split("."):
        if m in _EN_TO_CN:
            add(_EN_TO_CN[m])
    # generic: if description mentions key CN terms
    return kws


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    # 1) load OLD index keyword map (carry over by function name)
    old_kw_by_name: dict[str, list[str]] = {}
    if os.path.exists(OLD_INDEX):
        try:
            old = json.load(open(OLD_INDEX, encoding="utf-8"))
            for f in old.get("functions", []):
                kws = f.get("keywords")
                if kws:
                    old_kw_by_name.setdefault(f["name"], kws)
        except Exception as e:
            print(f"  (warn) could not read old index for keyword carryover: {e}")

    # 2) parse all pydev modules
    functions: list[dict] = []
    pydev_modules = sorted(
        f for f in os.listdir(PYDEV) if f.endswith(".py") and f != "__init__.py"
    )
    for fn in pydev_modules:
        stem = fn[:-3]
        module = "ansa." + stem
        if module in EXCLUDE_MODULES:
            print(f"  skip {module}")
            continue
        entries = parse_module_file(os.path.join(PYDEV, fn), module)
        functions.extend(entries)
        print(f"  {module}: {len(entries)} entries")

    # also include ansa top-level re-exports from __init__.py (skip if it just re-imports)
    init_path = os.path.join(PYDEV, "__init__.py")
    if os.path.exists(init_path):
        init_entries = parse_module_file(init_path, "ansa")
        # keep only genuine functions/constants, not re-imports
        init_entries = [e for e in init_entries if not e["signature"].endswith("= <unknown>")]
        functions.extend(init_entries)
        print(f"  ansa (top-level): {len(init_entries)} entries")

    # 3) categories (reuse project logic)
    assign_categories(functions)

    # 4) keywords (offline + carryover)
    for f in functions:
        carry = old_kw_by_name.get(f["name"])
        f["keywords"] = build_keywords(f["name"], f["module"], f.get("description", ""), carry)

    # 5) sort by module then name for stable output
    functions.sort(key=lambda f: (f["module"], f["name"]))

    # 6) save
    modules = sorted(OrderedDict((f["module"], 1) for f in functions).keys())
    save_index(
        functions=functions,
        output_path=os.path.join(HERE, "ansa_api_index.json"),
        api_version=API_VERSION,
        modules=modules,
    )
    # also write root copy
    import shutil
    shutil.copyfile(
        os.path.join(HERE, "ansa_api_index.json"),
        os.path.join(ROOT, "ansa_api_index.json"),
    )

    # 7) regenerate txt_docs for Layer 3 consistency
    regenerate_txt_docs(functions, os.path.join(HERE, "txt_docs"))

    kw_total = sum(1 for f in functions if f.get("keywords"))
    print(f"\nDONE. {len(functions)} functions across {len(modules)} modules "
          f"(api_version={API_VERSION}). {kw_total} have keywords.")
    print(f"Index -> {os.path.join(HERE, 'ansa_api_index.json')}")


def regenerate_txt_docs(functions: list[dict], txt_dir: str):
    os.makedirs(txt_dir, exist_ok=True)
    by_mod: dict[str, list[dict]] = {}
    for f in functions:
        by_mod.setdefault(f["module"], []).append(f)
    # clear old txt files
    for old in os.listdir(txt_dir):
        if old.endswith(".txt"):
            os.remove(os.path.join(txt_dir, old))
    for mod, entries in by_mod.items():
        fname = mod + ".txt"
        lines = [f"# Module: {mod}", ""]
        for e in entries:
            lines.append(e["name"])
            lines.append(e["signature"])
            if e.get("description"):
                lines.append(e["description"])
            for p in e.get("parameters", []):
                lines.append(f"- {p.get('name')} ({p.get('type','any')}): {p.get('desc','')}")
            if e.get("returns"):
                lines.append(f"Returns: {e['returns']}")
            if e.get("examples"):
                lines.append("Example:")
                lines.append(e["examples"])
            lines.append("")
        with open(os.path.join(txt_dir, fname), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
    print(f"  txt_docs regenerated: {len(by_mod)} module files in {txt_dir}")


if __name__ == "__main__":
    main()
