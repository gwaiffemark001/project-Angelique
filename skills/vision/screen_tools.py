import pyautogui
import pytesseract
from PIL import Image
import tempfile
import os
import re

def read_screen() -> str:
    """Takes a screenshot of the current screen, runs OCR, and returns cleaned text."""
    try:
        # 1. Take screenshot
        screenshot = pyautogui.screenshot()
        
        # 2. Save to a temporary file for Tesseract to process
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            screenshot.save(tmp.name)
            tmp_path = tmp.name
            
        # 3. Run OCR (Optical Character Recognition)
        raw_text = pytesseract.image_to_string(Image.open(tmp_path))
        
        # 4. Clean up the temporary file
        os.unlink(tmp_path)
        
        # 5. Clean the text: remove weird OCR artifacts, keep only readable characters
        clean_text = re.sub(r'[^a-zA-Z0-9\s\.\,\:\;\-\_\(\)\/\n]', ' ', raw_text)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        
        if not clean_text or len(clean_text) < 10:
            return "The screen appears to be blank, or I couldn't read any meaningful text from it."
            
        # Truncate if it's massively long to avoid overwhelming the LLM context window
        if len(clean_text) > 2000:
            return clean_text[:2000] + "\n...[Screen text truncated for brevity]..."
            
        return clean_text
        
    except Exception as e:
        return f"Error reading screen: {str(e)}. Please ensure 'tesseract-ocr' is installed on your system."