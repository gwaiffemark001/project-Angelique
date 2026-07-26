import os
import img2pdf
from docx2pdf import convert as docx2pdf_convert

def convert_images_to_pdf(image_paths: list, output_path: str) -> str:
    """Converts a list of image file paths into a single PDF."""
    try:
        valid_paths = [p for p in image_paths if os.path.exists(p)]
        if not valid_paths:
            return "No valid image files found at the provided paths."
        
        with open(output_path, "wb") as f:
            f.write(img2pdf.convert(valid_paths))
        return f"Successfully created PDF at {output_path} from {len(valid_paths)} images."
    except Exception as e:
        return f"Failed to convert images to PDF: {str(e)}"

def convert_word_to_pdf(docx_path: str, pdf_path: str) -> str:
    """Converts a Word document (.docx) to a PDF."""
    try:
        if not os.path.exists(docx_path):
            return f"Word document not found at {docx_path}."
        
        docx2pdf_convert(docx_path, pdf_path)
        return f"Successfully converted {docx_path} to {pdf_path}."
    except Exception as e:
        return f"Failed to convert Word to PDF: {str(e)}. Ensure MS Word or LibreOffice is installed."
