import os
from pathlib import Path


def list_files(path: str = ".") -> str:
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"❌ Path not found: {p}"
        if p.is_file():
            return f"❌ Path is a file, not a directory: {p}"
        entries = sorted(p.iterdir())
        if not entries:
            return f"(empty directory) {p}"
        lines = []
        for e in entries:
            marker = '/' if e.is_dir() else ''
            lines.append(f"{e.name}{marker}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing files: {e}"


def open_file(file_path: str, lines: int = 50) -> str:
    try:
        p = Path(file_path).expanduser()
        if not p.exists():
            return f"❌ File not found: {p}"
        if p.is_dir():
            return f"❌ Path is a directory, not a file: {p}"
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            out_lines = []
            for i, l in enumerate(f):
                out_lines.append(l.rstrip('\n'))
                if i + 1 >= lines:
                    break
        return "\n".join(out_lines) or "(file is empty)"
    except Exception as e:
        return f"Error opening file: {e}"


def cat_file(file_path: str, max_size: int = 200000) -> str:
    try:
        p = Path(file_path).expanduser()
        if not p.exists():
            return f"❌ File not found: {p}"
        if p.is_dir():
            return f"❌ Path is a directory, not a file: {p}"
        size = p.stat().st_size
        if size > max_size:
            return f"❌ File too large ({size} bytes). Limit is {max_size} bytes."
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"Error reading file: {e}"


def _normalize_search_root(root: str | None) -> str:
    if not root:
        return os.path.expanduser("~")
    candidate = os.path.expanduser(root.strip())
    if not os.path.isabs(candidate):
        candidate = os.path.abspath(candidate)
    return candidate


def search_files(query: str, root: str | None = None, max_results: int = 100, max_depth: int = 12) -> str:
    """Find files/directories by name anywhere below *root*.

    The old implementation silently missed projects nested deeper than six
    levels and relied only on substring matching. This version gives exact
    basename matches priority, is case-insensitive, prunes common virtual
    trees, and then falls back to substring/path matching.
    """
    try:
        root_dir = _normalize_search_root(root)
        if not os.path.isdir(root_dir):
            return f"❌ Root path not found or not a directory: {root_dir}"
        query = (query or "").strip().strip('\"\'')
        if not query:
            return "Please provide a search query for files or folders."

        query_lower = query.casefold()
        results: list[tuple[int, str, str]] = []
        root_dir = os.path.abspath(root_dir)
        root_depth = root_dir.rstrip(os.sep).count(os.sep)
        ignored = {'.cache', '.git', '__pycache__', '.venv', 'node_modules', '.npm', '.local/share/Trash'}

        for dirpath, dirnames, filenames in os.walk(root_dir, topdown=True, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in ignored and not d.startswith('.Trash')]
            current_depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
            if current_depth >= max_depth:
                dirnames[:] = []
            for name in dirnames + filenames:
                name_cf = name.casefold()
                path = os.path.join(dirpath, name)
                if name_cf == query_lower:
                    priority = 0
                elif query_lower in name_cf:
                    priority = 1
                elif query_lower in path.casefold():
                    priority = 2
                else:
                    continue
                kind = "dir" if os.path.isdir(path) else "file"
                results.append((priority, kind, path))

        results.sort(key=lambda row: (row[0], row[2].casefold()))
        results = results[:max_results]
        if not results:
            return f"No matching files or folders found for '{query}' under {root_dir}."
        lines = [f"{kind}: {path}" for _, kind, path in results]
        if len(results) >= max_results:
            lines.append(f"...stopped after {max_results} results. Narrow the query or increase max_results.")
        return "\n".join(lines)
    except Exception as e:
        return f"Error during file search: {e}"
