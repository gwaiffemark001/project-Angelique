import os
from docx import Document

def write_text_file(file_path: str, content: str, mode: str = "w") -> str:
    """Writes or appends content to a plain text file."""
    try:
        with open(file_path, mode, encoding="utf-8") as f:
            f.write(content)
        action = "Appended to" if mode == "a" else "Wrote to"
        return f"{action} text file at {file_path}."
    except Exception as e:
        return f"Failed to write text file: {str(e)}"

def write_word_document(file_path: str, content: str) -> str:
    """Creates or overwrites a Word document (.docx) with the given content."""
    try:
        doc = Document()
        # Split content by newlines to create distinct paragraphs
        paragraphs = content.split('\n')
        for p in paragraphs:
            doc.add_paragraph(p)
        
        doc.save(file_path)
        return f"Successfully created Word document at {file_path}."
    except Exception as e:
        return f"Failed to write Word document: {str(e)}"
