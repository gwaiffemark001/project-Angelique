# skills/vision/file_analyzer.py
import os
import mimetypes
from typing import Dict, Any

def analyze_file(file_path: str) -> Dict[str, Any]:
    try:
        if not os.path.exists(file_path):
            return {"error": "File not found"}
        
        file_info = {
            "name": os.path.basename(file_path),
            "size": os.path.getsize(file_path),
            "type": mimetypes.guess_type(file_path)[0] or "unknown"
        }
        
        if file_info["type"].startswith("image/"):
            return {**file_info, "analysis": "Image file detected"}
        elif file_info["type"] in ["text/plain", "text/csv"]:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(500)
            return {**file_info, "content_preview": content}
        
        return file_info
        
    except Exception as e:
        return {"error": f"Analysis failed: {str(e)}"}
