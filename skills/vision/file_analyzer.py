import os
import mimetypes
import hashlib
from typing import Dict, Any

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg', '.ico'}
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.avi', '.mov', '.mkv', '.flv'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a'}
DOCUMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.txt', '.md', '.csv', '.xlsx', '.json', '.xml', '.html', '.css', '.js', '.py', '.sh', '.bat'}


def analyze_file(file_path: str) -> Dict[str, Any]:
    """Full analysis of a file including type detection, content preview, and metadata."""
    file_path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.exists(file_path):
        return {"error": "File not found", "path": file_path}

    stat = os.stat(file_path)
    file_info = {
        "name": os.path.basename(file_path),
        "path": file_path,
        "size": stat.st_size,
        "size_human": _human_size(stat.st_size),
        "type": mimetypes.guess_type(file_path)[0] or "unknown",
        "extension": os.path.splitext(file_path)[1].lower(),
        "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "is_readable": os.access(file_path, os.R_OK),
        "sha256": hashlib.sha256(open(file_path, 'rb').read()).hexdigest()[:16],
    }

    ext = file_info["extension"]
    if ext in IMAGE_EXTENSIONS:
        file_info["category"] = "image"
        file_info["analysis"] = _analyze_image(file_path)
    elif ext in VIDEO_EXTENSIONS:
        file_info["category"] = "video"
        file_info["analysis"] = f"Video file ({file_info['size_human']}). Duration and frame data require ffprobe."
    elif ext in AUDIO_EXTENSIONS:
        file_info["category"] = "audio"
        file_info["analysis"] = f"Audio file ({file_info['size_human']}). Metadata extraction requires mutagen."
    elif ext == '.pdf':
        file_info["category"] = "document"
        file_info["analysis"] = _analyze_pdf(file_path)
    elif ext in {'.py', '.js', '.ts', '.java', '.cpp', '.c', '.h'}:
        file_info["category"] = "code"
        file_info["analysis"] = _analyze_code(file_path)
    elif ext in {'.txt', '.md', '.csv', '.json', '.xml', '.html'}:
        file_info["category"] = "text"
        file_info["analysis"] = _analyze_text(file_path, max_preview=1000)
    elif ext in {'.doc', '.docx', '.xlsx', '.xls'}:
        file_info["category"] = "document"
        file_info["analysis"] = f"Microsoft Office document ({file_info['size_human']}). Full parsing requires python-docx/openpyxl."
    else:
        file_info["category"] = "unknown"
        file_info["analysis"] = f"Unrecognized file type ({ext}). Raw binary analysis available."

    return file_info


def analyze_directory(dir_path: str, recursive: bool = False) -> Dict[str, Any]:
    """Analyze a directory and return summary statistics."""
    dir_path = os.path.abspath(os.path.expanduser(dir_path))
    if not os.path.isdir(dir_path):
        return {"error": "Directory not found", "path": dir_path}

    total_size = 0
    file_count = 0
    dir_count = 0
    extensions = {}

    if recursive:
        for root, dirs, files in os.walk(dir_path):
            dir_count += len(dirs)
            for f in files:
                file_count += 1
                fp = os.path.join(root, f)
                try:
                    total_size += os.path.getsize(fp)
                    ext = os.path.splitext(f)[1].lower()
                    extensions[ext] = extensions.get(ext, 0) + 1
                except (OSError, PermissionError):
                    pass
    else:
        for item in os.listdir(dir_path):
            fp = os.path.join(dir_path, item)
            if os.path.isfile(fp):
                file_count += 1
                try:
                    total_size += os.path.getsize(fp)
                    ext = os.path.splitext(item)[1].lower()
                    extensions[ext] = extensions.get(ext, 0) + 1
                except (OSError, PermissionError):
                    pass
            elif os.path.isdir(fp):
                dir_count += 1

    return {
        "path": dir_path,
        "total_size": total_size,
        "total_size_human": _human_size(total_size),
        "file_count": file_count,
        "dir_count": dir_count,
        "extensions": dict(sorted(extensions.items(), key=lambda x: -x[1])[:10]),
    }


def _analyze_image(path):
    try:
        from PIL import Image
        img = Image.open(path)
        w, h = img.size
        mode = img.mode
        fmt = img.format
        return f"Image: {w}x{h}, mode={mode}, format={fmt}"
    except Exception as e:
        return f"Image analysis failed: {e}"


def _analyze_text(path, max_preview=500):
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read(max_preview * 2)
        preview = content[:max_preview]
        lines = content.split('\n')
        return f"Text file: {len(lines)} lines, {len(content)} chars. Preview:\n{preview}"
    except Exception as e:
        return f"Text analysis failed: {e}"


def _analyze_code(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        lines = content.split('\n')
        code_lines = [l for l in lines if l.strip() and not l.strip().startswith('#') and not l.strip().startswith('//')]
        return f"Code file: {len(lines)} lines ({len(code_lines)} code lines), {len(content)} chars"
    except Exception as e:
        return f"Code analysis failed: {e}"


def _analyze_pdf(path):
    try:
        import subprocess
        result = subprocess.run(['pdfinfo', path], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return f"PDF document. Info:\n{result.stdout[:500]}"
    except Exception:
        pass
    return "PDF file. Full text extraction requires pdfplumber or PyPDF2."


def _human_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


from datetime import datetime