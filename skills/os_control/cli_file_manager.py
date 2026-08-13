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


def search_files(query: str, root: str | None = None, max_results: int = 100, max_depth: int = 6) -> str:
    try:
        root_dir = _normalize_search_root(root)
        if not os.path.isdir(root_dir):
            return f"❌ Root path not found or not a directory: {root_dir}"

        query = (query or "").strip()
        if not query:
            return "Please provide a search query for files or folders."

        query_lower = query.lower()
        results: list[tuple[str, str]] = []
        root_dir = os.path.abspath(root_dir)
        root_depth = root_dir.rstrip(os.sep).count(os.sep)

        for dirpath, dirnames, filenames in os.walk(root_dir):
            current_depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
            if current_depth > max_depth:
                dirnames[:] = []
                continue

            for name in dirnames + filenames:
                path = os.path.join(dirpath, name)
                if query_lower in name.lower() or query_lower in path.lower():
                    results.append(("dir" if os.path.isdir(path) else "file", path))
                    if len(results) >= max_results:
                        break
            if len(results) >= max_results:
                break

        if not results:
            return f"No matching files or folders found for '{query}' under {root_dir}."

        lines = [f"{typ}: {path}" for typ, path in results]
        if len(results) >= max_results:
            lines.append(f"...stopped after {max_results} results. Narrow the query or increase max_results.")
        return "\n".join(lines)
    except Exception as e:
        return f"Error during file search: {e}"
