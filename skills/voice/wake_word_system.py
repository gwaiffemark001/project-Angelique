# skills/voice/wake_word_system.py
"""
Wake-word system removed. Angelique now stays active and responsive
without requiring any activation phrase or clap confirmation.
"""
import threading

IS_AWAKE = True
WAKE_LOCK = threading.Lock()


def wake_up():
    global IS_AWAKE
    with WAKE_LOCK:
        IS_AWAKE = True


def sleep():
    global IS_AWAKE
    with WAKE_LOCK:
        IS_AWAKE = False


def is_awake() -> bool:
    with WAKE_LOCK:
        return IS_AWAKE


async def activation_protocol(audio_text: str, audio_samples=None) -> bool:
    return True