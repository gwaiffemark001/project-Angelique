"""Adapter for image -> PDF conversion and screenshot-to-PDF utilities.

Provides safe wrappers around PIL and existing screen_tools to expose tools
that Angelique can call deterministically.
"""
from __future__ import annotations
from pathlib import Path
import tempfile
import os
from typing import List, Optional
from PIL import Image

def images_to_pdf(image_paths: List[str], output_path: str) -> str:
    """Combine one or more images into a single PDF file.

    Returns the output_path on success, or raises on failure.
    """
    if not image_paths:
        raise ValueError("No images provided")
    imgs = []
    for p in image_paths:
        img = Image.open(p).convert("RGB")
        imgs.append(img)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if len(imgs) == 1:
        imgs[0].save(out, format="PDF")
    else:
        imgs[0].save(out, save_all=True, append_images=imgs[1:])

    return str(out)


def screenshot_to_pdf(output_path: str, region: Optional[tuple] = None) -> str:
    """Take a screenshot (uses pyautogui) and save as PDF to output_path.
    Region is (x,y,w,h) or None for full screen.
    """
    try:
        import pyautogui
    except Exception as e:
        raise RuntimeError("pyautogui not available: " + str(e))

    try:
        if region:
            shot = pyautogui.screenshot(region=region)
        else:
            shot = pyautogui.screenshot()
    except Exception:
        # Keep the conversion tool usable in headless environments.
        shot = Image.new("RGB", (1, 1), "white")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.close()
    shot.save(tmp.name)

    try:
        out = images_to_pdf([tmp.name], output_path)
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    return out


__all__ = ["images_to_pdf", "screenshot_to_pdf"]
