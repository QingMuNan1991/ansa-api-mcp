"""MCP Server for searching ANSA Python API documentation.

Provides a three-layer search (keyword, fuzzy, txt fallback) over
a pre-built index of ANSA API functions.
"""

import json
import os
import re
import unicodedata
from importlib.resources import files
from pathlib import Path

from mcp.server.fastmcp import FastMCP


def _tokenize(text: str) -> list[str]:
    """Split text into tokens: words, individual CJK chars, punctuation-separated segments."""
    tokens: list[str] = []
    current: list[str] = []
    for ch in text:
        # CJK Unified Ideographs and extensions
        if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿":
            if current:
                tokens.append("".join(current))
                current = []
            tokens.append(ch)
        elif ch.isalnum() or ch == "_":
            current.append(ch)
        else:
            if current:
                tokens.append("".join(current))
                current = []
    if current:
        tokens.append("".join(current))
    return [t.lower() for t in tokens if t]


class AnsaApiSearcher:
    """Search ANSA API functions using a pre-built index with txt fallback."""

    def __init__(self, index_path: str, txt_docs_path: str = ""):
        self.txt_docs_path = txt_docs_path
        with open(index_path, encoding="utf-8") as f:
            data = json.load(f)
        self.metadata = data.get("metadata", {})
        self.functions: list[dict] = data.get("functions", [])
        # Pre-compute lowercased keywords for each function
        for func in self.functions:
            func["_keywords_lower"] = [kw.lower() for kw in func.get("keywords", [])]

    def search(
        self,
        query: str,
        module: str | None = None,
        category: str | None = None,
        top_n: int = 5,
    ) -> list[dict]:
        """Three-layer search: keyword -> fuzzy -> txt fallback."""
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        # Apply filters
        candidates = self.functions
        if module:
            candidates = [f for f in candidates if f.get("module") == module]
        if category:
            candidates = [f for f in candidates if f.get("category") == category]

        # Layer 1: keyword match with module / name relevance boost
        query_lower = query.lower()
        scored: list[tuple[int, dict]] = []
        for func in candidates:
            kw_lower = func["_keywords_lower"]
            score = 0
            mod_last = func["module"].split(".")[-1]
            name_lower = func["name"].lower()
            # Boost when the query names the module or the function itself — these
            # are the strongest relevance signals and stop loosely-tagged constants
            # (which carry broad keywords like "mesh"/"solver") from outranking the
            # functions users actually mean.
            for tok in query_tokens:
                if not tok:
                    continue
                if mod_last == tok or tok in mod_last or mod_last in tok:
                    score += 6
                if tok in name_lower or name_lower in tok:
                    score += 8
            # Keyword matches: an exact query token weighs more than a substring hit.
            for kw in kw_lower:
                if kw in query_lower:
                    score += 2 if kw in query_tokens else 1
            if score == 0:
                # Fallback: a query token appears inside a keyword.
                for tok in query_tokens:
                    if tok and tok in kw_lower:
                        score += 1
            if score > 0:
                scored.append((score, func))
        scored.sort(key=lambda x: -x[0])
        results = [func for _, func in scored]

        # Layer 2: fuzzy fallback on description + signature
        if len(results) < top_n:
            already = {id(f) for f in results}
            for func in candidates:
                if id(func) in already:
                    continue
                searchable = (func.get("description", "") + " " + func.get("signature", "")).lower()
                if any(tok in searchable for tok in query_tokens):
                    results.append(func)

        # Layer 3: txt file fallback
        if len(results) < top_n and self.txt_docs_path and os.path.isdir(self.txt_docs_path):
            already = {id(f) for f in results}
            found_names = {f["name"] for f in results}
            query_lower = query.lower()
            for fname in os.listdir(self.txt_docs_path):
                if not fname.endswith(".txt"):
                    continue
                fpath = os.path.join(self.txt_docs_path, fname)
                try:
                    with open(fpath, encoding="utf-8") as tf:
                        content = tf.read()
                except Exception:
                    continue
                if query_lower not in content.lower():
                    continue
                # Extract function names near matches
                for func in candidates:
                    if id(func) in already or func["name"] in found_names:
                        continue
                    if func["name"].lower() in content.lower():
                        results.append(func)
                        found_names.add(func["name"])

        # Trim to top_n
        results = results[:top_n]

        # Strip internal fields before returning
        clean: list[dict] = []
        for func in results:
            clean.append({k: v for k, v in func.items() if not k.startswith("_")})
        return clean

    def list_modules(self) -> list[dict]:
        """Return all modules with function counts."""
        modules = self.metadata.get("modules", [])
        if not modules:
            modules = sorted({f.get("module", "") for f in self.functions if f.get("module")})
        result = []
        for mod in modules:
            count = sum(1 for f in self.functions if f.get("module") == mod)
            result.append({"module": mod, "function_count": count})
        return result

    def list_categories(self) -> list[dict]:
        """Return all categories with function counts."""
        cats: dict[str, int] = {}
        for f in self.functions:
            cat = f.get("category", "")
            if cat:
                cats[cat] = cats.get(cat, 0) + 1
        return [{"category": k, "function_count": v} for k, v in sorted(cats.items())]


# Default paths
_PKG_DIR = files("ansa_tools")
_INDEX_PATH = str(_PKG_DIR.joinpath("ansa_api_index.json"))
_BUNDLED_TXT_DOCS = str(_PKG_DIR.joinpath("txt_docs"))
_TXT_DOCS_PATH = os.environ.get("ANSA_TXT_DOCS_PATH", _BUNDLED_TXT_DOCS)

# MCP server instance
mcp = FastMCP(
    "ansa-api",
    instructions="""This server provides search access to ANSA Python API documentation.
ANSA is the pre-processing tool from BETA CAE Systems for CAE mesh generation.

Available tools:
- search_ansa_api(query, module?, category?, top_n?): Search the ANSA API docs
- list_ansa_modules(): List all available ANSA API modules  
- list_ansa_categories(): List all ANSA API function categories
- get_ansa_function(function_name, module?): Get full docs for a specific function

Always use these tools when the user asks about ANSA API, mesh operations, or CAE pre-processing."""
)

# Module-level searcher (initialized if index exists)
_searcher: AnsaApiSearcher | None = None


def _get_searcher() -> AnsaApiSearcher:
    global _searcher
    if _searcher is None:
        if not os.path.exists(_INDEX_PATH):
            raise FileNotFoundError(f"Index file not found: {_INDEX_PATH}")
        _searcher = AnsaApiSearcher(_INDEX_PATH, _TXT_DOCS_PATH)
    return _searcher


def _format_result(func: dict) -> str:
    """Format a single search result as markdown."""
    lines = [f"### `{func['signature']}`"]
    lines.append(f"**Module:** {func.get('module', 'N/A')}")
    lines.append(f"**Category:** {func.get('category', 'N/A')}")
    lines.append("")
    lines.append(func.get("description", ""))
    lines.append("")

    params = func.get("parameters", [])
    if params:
        lines.append("**Parameters:**")
        for p in params:
            lines.append(f"- `{p['name']}` ({p.get('type', 'any')}): {p.get('desc', '')}")
        lines.append("")

    ret = func.get("returns", "")
    if ret:
        lines.append(f"**Returns:** {ret}")
        lines.append("")

    examples = func.get("examples", "")
    if examples:
        lines.append("**Example:**")
        lines.append("```python")
        lines.append(examples)
        lines.append("```")

    return "\n".join(lines)


@mcp.tool()
def search_ansa_api(
    query: str,
    module: str | None = None,
    category: str | None = None,
    top_n: int = 5,
) -> str:
    """Search the ANSA Python API documentation.

    Args:
        query: Search query (supports Chinese and English keywords)
        module: Filter by module name (e.g. "ansa.mesh", "ansa.base")
        category: Filter by category (e.g. "mesh_edit", "base_query")
        top_n: Maximum number of results to return (default 5)
    """
    searcher = _get_searcher()
    results = searcher.search(query, module=module, category=category, top_n=top_n)

    if not results:
        return f"No results found for query: `{query}`"

    header = f"## ANSA API Search Results for `{query}`\n"
    parts = [header]
    for i, func in enumerate(results, 1):
        parts.append(f"---\n\n**{i}. {func['name']}**\n")
        parts.append(_format_result(func))
        parts.append("")

    return "\n".join(parts)


def _normalize_ansa_module(module: str | None) -> str | None:
    """Ensure module name has 'ansa.' prefix if it looks like a short module name."""
    if module is None:
        return None
    # If it looks like a short name (no dots, or starts with known sub-module prefix)
    # Also handles cases like "mesh" → "ansa.mesh"
    if not module.startswith("ansa.") and module != "ansa":
        # Check if it matches a known module suffix
        known_modules = {m for m in _get_searcher().metadata.get("modules", [])}
        prefixed = f"ansa.{module}" if not module.startswith("ansa.") else module
        if prefixed in known_modules:
            return prefixed
        # Also check if any module ends with this name
        for m in known_modules:
            if m.endswith(f".{module}"):
                return m
    return module


@mcp.tool()
def list_ansa_modules() -> str:
    """List all available ANSA Python API modules.

    Returns a table of all modules and their function counts.
    Use this to discover what modules are available before searching.
    """
    try:
        searcher = _get_searcher()
    except FileNotFoundError as e:
        return f"Error: {e}"

    modules = searcher.list_modules()
    metadata = searcher.metadata

    lines = [
        "## ANSA API Modules",
        f"*Total functions: {metadata.get('total_functions', '?')}  |  "
        f"API version: {metadata.get('api_version', '?')}*",
        "",
    ]
    for item in modules:
        mod = item["module"]
        count = item["function_count"]
        lines.append(f"- `{mod}` — {count} functions")

    return "\n".join(lines)


@mcp.tool()
def list_ansa_categories() -> str:
    """List all available ANSA API function categories.

    Categories group functions by their purpose within a module.
    Use these as the `category` filter in search_ansa_api.
    """
    try:
        searcher = _get_searcher()
    except FileNotFoundError as e:
        return f"Error: {e}"

    categories = searcher.list_categories()
    lines = ["## ANSA API Categories", ""]
    for item in categories:
        cat = item["category"]
        count = item["function_count"]
        lines.append(f"- `{cat}` — {count} functions")

    return "\n".join(lines)


@mcp.tool()
def get_ansa_function(function_name: str, module: str | None = None) -> str:
    """Get full documentation for a specific ANSA API function by exact name.

    Args:
        function_name: Exact function name (case-sensitive).
                       Examples: "MeshCreateShell", "GetEntity", "base.GetEntity"
        module: Optional module to narrow the search (e.g. "ansa.mesh", "ansa.base")
    """
    try:
        searcher = _get_searcher()
    except FileNotFoundError as e:
        return f"Error: {e}"

    candidates = searcher.functions
    mod_filter = _normalize_ansa_module(module)
    if mod_filter:
        candidates = [f for f in candidates if f.get("module") == mod_filter]

    matches = [f for f in candidates if f.get("name") == function_name]

    if not matches:
        # Try case-insensitive
        matches = [f for f in candidates
                   if f.get("name", "").lower() == function_name.lower()]

    if not matches:
        # Try partial name match (function name might include module prefix)
        matches = [f for f in candidates
                   if f.get("name", "").endswith(f".{function_name}")
                   or function_name.endswith(f".{f.get('name', '')}")]

    if not matches:
        return f"Function `{function_name}` not found in ANSA API index."

    parts = [f"## `{function_name}` — ANSA API\n"]
    for func in matches:
        clean = {k: v for k, v in func.items() if not k.startswith("_")}
        parts.append(_format_result(clean))

    return "\n".join(parts)


def _install_mcp():
    """Register this MCP server in Claude Code settings."""
    import json as _json
    import shutil

    config_path = Path.home() / ".claude.json"

    # Read existing config
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            config = _json.load(f)
    else:
        config = {}

    servers = config.setdefault("mcpServers", {})

    # Check if already registered
    if "ansa-api" in servers:
        print("ansa-api MCP server is already registered in Claude Code.")
        print(f"  Config: {config_path}")
        return True

    # Find the installed executable
    exe = shutil.which("ansa-api-mcp")
    if not exe:
        print("Error: ansa-api-mcp executable not found in PATH.")
        print("  Make sure pip install completed successfully.")
        return False

    # Register the MCP server with full config format
    servers["ansa-api"] = {
        "type": "stdio",
        "command": exe,
        "args": [],
        "env": {},
    }

    # Write config back
    with open(config_path, "w", encoding="utf-8") as f:
        _json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"Successfully registered ansa-api MCP server in Claude Code!")
    print(f"  Config: {config_path}")
    print(f"  Command: {exe}")
    print()
    print("Restart Claude Code to start using it.")
    return True


def main():
    """Entry point for the MCP server.

    Usage:
        ansa-api-mcp          Start the MCP server (used by Claude Code)
        ansa-api-mcp install  Register this server in Claude Code settings
    """
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "install":
        success = _install_mcp()
        sys.exit(0 if success else 1)

    try:
        mcp.run()
    except (BrokenPipeError, EOFError, KeyboardInterrupt):
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
