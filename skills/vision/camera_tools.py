import cv2
import pytesseract
from PIL import Image
import tempfile
import os
import re

def capture_and_analyze_scene() -> str:
    """
    Captures image from webcam and analyzes what's in the scene.
    Returns a description of objects, text, and general scene content.
    """
    try:
        # Open camera
        cap = cv2.VideoCapture(0)
        
        if not cap.isOpened():
            return "I couldn't access your camera. Please make sure it's connected and permissions are granted."
        
        # Capture frame
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return "Failed to capture image from camera."
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            cv2.imwrite(tmp.name, frame)
            tmp_path = tmp.name
        
        # Extract text using OCR
        text = pytesseract.image_to_string(Image.open(tmp_path))
        os.unlink(tmp_path)
        
        # Analyze the scene
        analysis = []
        
        # Check for text
        clean_text = re.sub(r'[^a-zA-Z0-9\s]', ' ', text).strip()
        if clean_text:
            analysis.append(f"I can see text that says: '{clean_text}'")
        
        # Basic scene analysis (colors, brightness)
        height, width, _ = frame.shape
        avg_color = frame.mean(axis=(0, 1))
        
        if avg_color[0] > 150 and avg_color[1] > 150 and avg_color[2] > 150:
            analysis.append("The scene appears to be bright/well-lit")
        else:
            analysis.append("The lighting appears to be moderate or dim")
        
        # Detect if there are people (simple face detection would go here)
        # For now, just report basic info
        analysis.append(f"The image resolution is {width}x{height} pixels")
        
        if not analysis:
            return "I captured an image from your camera, but I can't make out specific details. The scene might be too dark or unclear."
        
        return " | ".join(analysis)
        
    except Exception as e:
        return f"Error analyzing camera scene: {str(e)}"

def detect_faces() -> str:
    """Detects faces in the camera view"""
    try:
        cap = cv2.VideoCapture(0)
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return "Failed to capture image."
        
        # Load face cascade
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Detect faces
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)
        
        if len(faces) == 0:
            return "I don't see any faces in the camera view right now."
        elif len(faces) == 1:
            return "I can see one person in front of the camera."
        else:
            return f"I can see {len(faces)} people in front of the camera."
            
    except Exception as e:
        return f"Error detecting faces: {str(e)}"