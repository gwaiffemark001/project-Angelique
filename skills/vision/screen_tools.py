import tempfile
import os
import re

def read_screen(region=None, save_to_file=None):
    """Takes a screenshot, runs OCR, and returns cleaned text.

    Args:
        region: Optional tuple (x, y, width, height) to capture a specific area.
        save_to_file: Optional path to save the screenshot image.
    """
    try:
        import pyautogui
        import pytesseract
        from PIL import Image
        if region:
            screenshot = pyautogui.screenshot(region=region)
        else:
            screenshot = pyautogui.screenshot()

        if save_to_file:
            screenshot.save(save_to_file)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            screenshot.save(tmp.name)
            tmp_path = tmp.name

        raw_text = pytesseract.image_to_string(Image.open(tmp_path))
        os.unlink(tmp_path)

        clean_text = re.sub(r'[^a-zA-Z0-9\s\.\,\:\;\-\_\(\)\/\n\']', ' ', raw_text)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()

        if not clean_text or len(clean_text) < 3:
            return "The screen appears blank or no readable text was found."

        if len(clean_text) > 3000:
            return clean_text[:3000] + "\n...[Screen text truncated]"

        return clean_text

    except Exception as e:
        return f"Error reading screen: {str(e)}. Ensure tesseract-ocr and pillow are installed."


def read_screen_region(x, y, w, h, save_to_file=None):
    """Capture a specific screen region and extract text via OCR."""
    return read_screen(region=(x, y, w, h), save_to_file=save_to_file)


def find_on_screen(search_text, region=None):
    """Search for specific text on the visible screen using OCR."""
    text = read_screen(region=region)
    lines = text.split('\n')
    matches = [line.strip() for line in lines if search_text.lower() in line.lower()]
    if matches:
        return f"Found {len(matches)} match(es): " + "; ".join(matches[:5])
    return f"'{search_text}' not found on screen."


def capture_and_analyze(region=None):
    """Screenshot then return both the raw OCR text and a structured summary."""
    full_text = read_screen(region=region)
    lines = [l.strip() for l in full_text.split('\n') if l.strip()]

    summary = {
        "line_count": len(lines),
        "total_chars": len(full_text),
        "first_lines": lines[:5],
        "contains_numbers": any(c.isdigit() for c in full_text),
        "contains_email": bool(re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', full_text)),
        "contains_url": bool(re.search(r'https?://\S+', full_text)),
    }

    return {
        "full_text": full_text,
        "summary": summary,
    }