# skills/vision/image_generator.py
import os
import requests

def generate_image(prompt: str, style: str = "realistic") -> str:
    try:
        API_URL = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
        headers = {"Authorization": f"Bearer {os.getenv('HUGGINGFACE_API_KEY', '')}"}
        
        payload = {
            "inputs": prompt,
            "parameters": {"width": 1024, "height": 1024}
        }
        
        response = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        
        if response.status_code == 200:
            output_path = "data/generated_images"
            os.makedirs(output_path, exist_ok=True)
            
            import hashlib
            filename = f"img_{hashlib.md5(prompt.encode()).hexdigest()[:8]}.png"
            file_path = os.path.join(output_path, filename)
            
            with open(file_path, "wb") as f:
                f.write(response.content)
            
            return f"✅ Image generated! Saved to: {file_path}"
        else:
            return f"❌ Image generation failed: {response.text}"
            
    except Exception as e:
        return f"️ Error: {str(e)}"
