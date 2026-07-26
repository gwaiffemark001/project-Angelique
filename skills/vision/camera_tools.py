import cv2
import pytesseract
from PIL import Image
import tempfile
import os
import re
from typing import Any

# Lazy-loaded YOLO model to avoid heavy startup cost when the module is imported.
_YOLO_MODEL = None

def _get_yolo_model():
    global _YOLO_MODEL
    if _YOLO_MODEL is None:
        try:
            from ultralytics import YOLO
            _YOLO_MODEL = YOLO("yolov8n.pt")
        except Exception as e:
            _YOLO_MODEL = None
    return _YOLO_MODEL

def analyze_camera_scene() -> str:
    """Captures a frame from the webcam and detects real objects, lighting, and text."""
    try:
        # Try default camera (0), fallback to external (1) if it fails
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            cap = cv2.VideoCapture(1)
            
        if not cap.isOpened():
            return "I couldn't access your webcam (tried indices 0 and 1). Please check permissions or connections."
        
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return "Failed to capture an image from the camera."
        
        analysis = []
        
        # 1. REAL OBJECT DETECTION using YOLOv8 (lazy-loaded)
        model = _get_yolo_model()
        results = []
        if model is not None:
            try:
                results = model(frame, verbose=False)
            except Exception:
                results = []
        detected_objects = {}
        
        for r in results:
            # results entries can vary by ultralytics version; guard attribute access
            boxes = getattr(r, 'boxes', None)
            names = getattr(r, 'names', None)
            if boxes is None:
                continue
            for box in boxes:
                try:
                    class_id = int(getattr(box, 'cls', [0])[0])
                    class_name = names[class_id] if names and class_id < len(names) else str(class_id)
                    detected_objects[class_name] = detected_objects.get(class_name, 0) + 1
                except Exception:
                    continue
                
        if detected_objects:
            # Format the detected objects into a natural sentence
            object_list = [f"{count} {name}{'s' if count > 1 else ''}" for name, count in detected_objects.items()]
            analysis.append(f"I can clearly see: {', '.join(object_list)}.")
        else:
            analysis.append("I don't see any distinct, recognizable objects in the camera view right now.")
            
        # 2. Basic Lighting Check (to help context, e.g., if it's too dark to see objects)
        avg_brightness = frame.mean()
        if avg_brightness < 50:
            analysis.append("However, the scene is very dark, which might be hiding some details.")
        elif avg_brightness > 200:
            analysis.append("The scene is very brightly lit.")
            
        # 3. OCR for Text (Bonus: reads any visible text like book titles or signs)
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                cv2.imwrite(tmp.name, frame)
                tmp_path = tmp.name
                
            raw_text = pytesseract.image_to_string(Image.open(tmp_path))
            clean_text = re.sub(r'[^a-zA-Z0-9\s]', ' ', raw_text).strip()
            clean_text = re.sub(r'\s+', ' ', clean_text)
            
            if clean_text and len(clean_text) > 15:
                analysis.append(f"I also see some text in the scene that reads: '{clean_text[:80]}...'")
            else:
                analysis.append("I don't see any clear, readable text.")
            os.unlink(tmp_path)
        except Exception:
            pass # Tesseract might fail, that's okay
            
        analysis.append(f"(Image resolution: {frame.shape[1]}x{frame.shape[0]} pixels)")
        
        return " | ".join(analysis)
        
    except Exception as e:
        return f"Error analyzing camera scene: {str(e)}"