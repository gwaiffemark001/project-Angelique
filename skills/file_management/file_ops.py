# skills/file_management/file_ops.py
import os
import shutil

def manage_files(action: str, path: str, content: str = "", new_path: str = "") -> str:
    try:
        if action == "create":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully created file at {path}"
        elif action == "read":
            if not os.path.exists(path):
                return f"File not found: {path}"
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return "Invalid action"
    except Exception as e:
        return f"File operation failed: {str(e)}"
