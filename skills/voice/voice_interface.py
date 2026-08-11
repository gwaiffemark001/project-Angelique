import os
import sys
import tempfile
import asyncio
import subprocess
import threading
import re
import socket
from typing import Any

# ==========================================
# NUCLEAR OPTION: SUPPRESS ALSA/JACK SPAM
# ==========================================
# Redirect stderr to /dev/null at the C-level BEFORE importing audio libraries.
# This completely kills the PortAudio/ALSA spam on Linux.
devnull_fd = os.open(os.devnull, os.O_WRONLY)
os.dup2(devnull_fd, 2)
os.close(devnull_fd)

import speech_recognition as sr
from dotenv import load_dotenv
load_dotenv()
from core import config

ELEVENLABS_API_KEY = config.ELEVENLABS_API_KEY
ELEVENLABS_VOICE_ID = config.ELEVENLABS_VOICE_ID
ELEVENLABS_MODEL = config.ELEVENLABS_MODEL
EDGE_TTS_VOICE = config.EDGE_TTS_VOICE

IS_SPEAKING = False
SPEECH_ENABLED = True
speech_lock = threading.Lock()


def is_speech_enabled() -> bool:
    return SPEECH_ENABLED


def set_speech_enabled(enabled: bool):
    global SPEECH_ENABLED
    SPEECH_ENABLED = bool(enabled)


def _is_online() -> bool:
    try:
        with socket.create_connection((config.NETWORK_CHECK_HOST, config.NETWORK_CHECK_PORT), timeout=1):
            return True
    except Exception:
        return False


async def _generate_edge_tts(text: str, voice: str, output_file: str):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)

def _play_audio_file(file_path: str):
    players = [
        ["mpv", "--no-video", "--quiet", file_path],
        ["paplay", file_path],
        ["aplay", "-q", file_path]
    ]
    for player_cmd in players:
        try:
            subprocess.run(player_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue

def speak(text: str):
    global IS_SPEAKING

    if not SPEECH_ENABLED:
        print("⚠️ [Voice] Speech output disabled by user.")
        return

    if not _is_online():
        print("⚠️ [Voice] Offline mode: speech output disabled.")
        return
    
    clean_text = re.sub(r'```.*?```', '', text, flags=re.DOTALL).strip()
    clean_text = re.sub(r'\[ACTION:.*?\]', '', clean_text).strip()
    clean_text = clean_text.replace("*", "").replace("_", "")
    
    if not clean_text:
        return

    with speech_lock:
        IS_SPEAKING = True

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
        temp_mp3 = temp_file.name

    spoke_successfully = False
    temp_file_created = True

    # ==========================================
    # 1. TRY EDGE-TTS FIRST (Free & Unlimited)
    # ==========================================
    try:
        asyncio.run(_generate_edge_tts(clean_text, EDGE_TTS_VOICE, temp_mp3))
        if os.path.exists(temp_mp3) and os.path.getsize(temp_mp3) > 0:
            spoke_successfully = True
    except Exception as e:
        print(f"\n⚠️ [Voice] Edge-TTS failed: {e}. Falling back to ElevenLabs...")

    # ==========================================
    # 2. FALLBACK TO ELEVENLABS (Premium Backup)
    # ==========================================
    if not spoke_successfully and ELEVENLABS_API_KEY:
        try:
            from elevenlabs.client import ElevenLabs
            client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
            audio_stream = client.text_to_speech.convert(
                voice_id=ELEVENLABS_VOICE_ID,
                text=clean_text[:2000],
                model_id=ELEVENLABS_MODEL,
                output_format="mp3_44100_64"
            )
            with open(temp_mp3, "wb") as f:
                for chunk in audio_stream:
                    if chunk:
                        f.write(chunk)
            spoke_successfully = True
        except Exception as e:
            print(f"\n⚠️ [Voice] ElevenLabs also failed: {e}")

    # ==========================================
    # 3. LOCAL FALLBACK TTS
    # ==========================================
    if not spoke_successfully:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.say(clean_text)
            engine.runAndWait()
            spoke_successfully = True
        except Exception:
            pass

    # ==========================================
    # 4. PLAY AUDIO
    # ==========================================
    if spoke_successfully and os.path.exists(temp_mp3):
        _play_audio_file(temp_mp3)

    if temp_file_created and os.path.exists(temp_mp3):
        try:
            os.unlink(temp_mp3)
        except Exception:
            pass

    with speech_lock:
        IS_SPEAKING = False

def listen() -> str:
    global IS_SPEAKING

    if not SPEECH_ENABLED:
        return ""

    if not _is_online():
        return ""
    
    with speech_lock:
        if IS_SPEAKING:
            return ""

    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 1.5
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True

    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.listen(source, timeout=4, phrase_time_limit=12)
                
        text = recognizer.recognize_google(audio)  # type: ignore[attr-defined]
        return text
        
    except sr.WaitTimeoutError:
        return ""
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as e:
        print(f"\n⚠️ [Voice] Google STT API error: {e}")
        try:
            return recognizer.recognize_sphinx(audio)
        except Exception:
            return ""
    except Exception:
        try:
            return recognizer.recognize_sphinx(audio)
        except Exception:
            return ""
