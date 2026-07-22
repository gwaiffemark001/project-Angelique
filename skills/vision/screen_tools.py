import pyautogui
import pytesseract
from PIL import Image
import tempfile
import os
import re

def read_screen() -> str:
    """Takes a screenshot, runs OCR, and returns the cleaned text."""
    try:
        # Take screenshot
        screenshot = pyautogui.screenshot()
        
        # Save to a temporary file for Tesseract to read
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            screenshot.save(tmp.name)
            tmp_path = tmp.name
            
        # Run OCR
        text = pytesseract.image_to_string(Image.open(tmp_path))
        os.unlink(tmp_path) # Clean up temp file
        
        # Clean the text (remove weird symbols that confuse the LLM)
        clean_text = re.sub(r'[^a-zA-Z0-9\s\.\,\:\;\-\_\(\)\/]', ' ', text)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        
        if not clean_text:
            return "The screen appears to be blank or contains no readable text."
            
        return clean_text
    except Exception as e:
        return f"Error reading screen: {str(e)}"