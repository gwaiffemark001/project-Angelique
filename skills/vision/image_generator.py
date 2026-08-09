import os
import hashlib
import requests
from PIL import Image
from io import BytesIO
from core import config


def generate_image(prompt: str, style: str = "realistic", width: int = 1024, height: int = 1024) -> str:
    """Generate an image using multiple AI backends with fallback."""
    output_dir = str(config.GENERATED_IMAGES_DIR)
    os.makedirs(output_dir, exist_ok=True)

    result = _try_huggingface(prompt, style, width, height, output_dir)
    if result:
        return result

    result = _try_nvidia(prompt, style, width, height, output_dir)
    if result:
        return result

    return "❌ All image generation backends failed. No API key configured or all services unavailable."


def _try_huggingface(prompt, style, width, height, output_dir):
    api_key = config.HUGGINGFACE_API_KEY
    if not api_key:
        return None
    try:
        API_URL = config.HUGGINGFACE_MODEL_URL
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {"inputs": prompt, "parameters": {"width": width, "height": height, "num_inference_steps": 20}}
        response = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        if response.status_code == 200 and response.content:
            filename = f"img_{hashlib.md5(prompt.encode()).hexdigest()[:8]}.png"
            file_path = os.path.join(output_dir, filename)
            with open(file_path, "wb") as f:
                f.write(response.content)
            return f"✅ Image generated via HuggingFace! Saved to: {file_path}"
    except Exception as e:
        print(f"⚠️ [ImageGen] HuggingFace failed: {e}")
    return None


def _try_nvidia(prompt, style, width, height, output_dir):
    api_key = config.NVIDIA_API_KEY
    if not api_key:
        return None
    try:
        from brain.llm_interface import query_llm
        image_prompt = f"Describe in detail an image that would represent: {prompt}. Give a vivid description of colors, composition, and mood."
        description = query_llm([{"role": "user", "content": image_prompt}], temperature=0.8)
        if description:
            filename = f"img_{hashlib.md5(prompt.encode()).hexdigest()[:8]}.txt"
            file_path = os.path.join(output_dir, filename)
            with open(file_path, "w") as f:
                f.write(f"Prompt: {prompt}\nStyle: {style}\nAI Description: {description}")
            return f"✅ Image concept generated via NVIDIA. Description saved to: {file_path}\n\n{description}"
    except Exception as e:
        print(f"⚠️ [ImageGen] NVIDIA failed: {e}")
    return None