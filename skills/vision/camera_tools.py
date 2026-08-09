import cv2
import numpy as np
from PIL import Image
import pytesseract
import tempfile
import os
import re
from typing import Any

_YOLO_MODEL = None


def _get_yolo_model():
    global _YOLO_MODEL
    if _YOLO_MODEL is None:
        try:
            from ultralytics import YOLO
            model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "yolov8n.pt")
            if os.path.exists(model_path):
                _YOLO_MODEL = YOLO(model_path)
            else:
                _YOLO_MODEL = YOLO("yolov8n.pt")
        except Exception:
            _YOLO_MODEL = None
    return _YOLO_MODEL


def _get_camera_indices(max_tries=3):
    available = []
    for i in range(max_tries):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            available.append(i)
            cap.release()
    return available


def analyze_camera_scene() -> str:
    """Captures a frame from the webcam and detects objects, lighting, text, and colors."""
    indices = _get_camera_indices()
    if not indices:
        return "I couldn't access any webcam (tried indices 0-2). Please check permissions."

    cap = None
    for idx in indices:
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            break

    if cap is None or not cap.isOpened():
        return "I couldn't open any webcam. Please check permissions or connections."

    ret, frame = cap.read()
    cap.release()

    if not ret:
        return "Failed to capture an image from the camera."

    analysis = []
    h, w = frame.shape[:2]
    analysis.append(f"Image: {w}x{h} pixels, {frame.shape[2]} channels")

    # 1. YOLO object detection (lazy-loaded)
    model = _get_yolo_model()
    detected_objects = {}
    if model is not None:
        try:
            results = model(frame, verbose=False)
            for r in results:
                boxes = getattr(r, 'boxes', None)
                names = getattr(r, 'names', None)
                if boxes is None:
                    continue
                for box in boxes:
                    try:
                        class_id = int(getattr(box, 'cls', [0])[0])
                        class_name = names[class_id] if names and class_id < len(names) else str(class_id)
                        conf = float(getattr(box, 'conf', [0])[0])
                        if conf > 0.3:
                            detected_objects[class_name] = detected_objects.get(class_name, 0) + 1
                    except Exception:
                        continue
        except Exception:
            pass

    if detected_objects:
        obj_list = [f"{count} {name}{'s' if count > 1 else ''}" for name, count in sorted(detected_objects.items(), key=lambda x: -x[1])]
        analysis.append("Detected: " + ", ".join(obj_list))
    else:
        analysis.append("No distinct objects recognized.")

    # 2. Lighting analysis
    avg_brightness = frame.mean()
    if avg_brightness < 50:
        analysis.append("Scene is very dark.")
    elif avg_brightness < 100:
        analysis.append("Scene is dimly lit.")
    elif avg_brightness > 200:
        analysis.append("Scene is very brightly lit.")
    else:
        analysis.append("Scene lighting is normal.")

    # 3. Dominant colors
    pixels = frame.reshape(-1, 3).astype(np.float32)
    from collections import Counter
    color_buckets = Counter()
    for r, g, b in pixels:
        bucket = (int(r // 64) * 64, int(g // 64) * 64, int(b // 64) * 64)
        color_buckets[bucket] += 1
    dominant = color_buckets.most_common(3)
    color_desc = []
    for (r, g, b), count in dominant:
        pct = count / len(pixels) * 100
        color_desc.append(f"RGB({r},{g},{b}) ({pct:.1f}%)")
    analysis.append("Dominant colors: " + "; ".join(color_desc))

    # 4. OCR for text
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            cv2.imwrite(tmp.name, frame)
            tmp_path = tmp.name
        raw_text = pytesseract.image_to_string(Image.open(tmp_path))
        clean_text = re.sub(r'[^a-zA-Z0-9\s]', ' ', raw_text).strip()
        clean_text = re.sub(r'\s+', ' ', clean_text)
        os.unlink(tmp_path)
        if clean_text and len(clean_text) > 5:
            analysis.append(f"Visible text: '{clean_text[:200]}'")
    except Exception:
        pass

    return " | ".join(analysis)


def capture_photo(save_path=None):
    """Capture a single photo from the webcam and save it."""
    indices = _get_camera_indices()
    if not indices:
        return "No webcam available."

    cap = cv2.VideoCapture(indices[0])
    if not cap.isOpened():
        return "Could not open webcam."

    ret, frame = cap.read()
    cap.release()

    if not ret:
        return "Failed to capture photo."

    if save_path is None:
        save_path = os.path.join(str(config.CAMERA_CAPTURE_DIR), f"capture_{int(time.time())}.jpg")

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    cv2.imwrite(save_path, frame)
    return f"📸 Photo saved to {save_path}"


import time