# skills/voice/wake_word_system.py
"""
Wake-word system: "Angelique" voice trigger + clap confirmation.
Enforces strict activation protocol before listening.
"""
import re
import numpy as np
import threading
import time
from collections import deque

# Global state
IS_AWAKE = False
WAKE_LOCK = threading.Lock()


def detect_wake_word(audio_text: str) -> bool:
    """
    Detect "Angelique" (case-insensitive, allows slight variations).
    Returns True if wake-word is detected.
    """
    if not audio_text:
        return False
    normalized = audio_text.strip().lower()
    # Match "Angelique" with optional pronouns/articles
    return bool(re.search(r'\b(?:hey\s+)?angelique\b', normalized))


def detect_clap(audio_samples: np.ndarray | None, sample_rate: int = 16000) -> bool:
    """
    Detect double clap using audio envelope analysis.
    A clap is a sudden loud burst followed by silence.
    Double clap = clap + ~0.5-1s silence + clap.
    """
    if audio_samples is None or len(audio_samples) == 0:
        return False

    try:
        # Compute RMS energy in 50ms windows
        window_size = int(sample_rate * 0.05)
        if window_size < 1:
            window_size = 1

        energies = []
        for i in range(0, len(audio_samples) - window_size, window_size):
            window = audio_samples[i : i + window_size]
            rms = np.sqrt(np.mean(window**2)) if len(window) > 0 else 0
            energies.append(rms)

        if len(energies) < 4:  # Not enough data
            return False

        energies = np.array(energies)
        mean_energy = np.mean(energies)
        threshold = mean_energy * 3  # 3x amplification

        # Find peaks (claps)
        clap_frames = [i for i, e in enumerate(energies) if e > threshold]
        if len(clap_frames) < 2:
            return False

        # Check if there are two distinct claps with silence in between
        clap_times = sorted(clap_frames)
        if len(clap_times) >= 2:
            # Claps should be separated by at least 200ms (silence gap)
            gap_frames = clap_times[1] - clap_times[0]
            gap_time = gap_frames * (window_size / sample_rate)
            return 0.2 < gap_time < 2.0  # 0.2 to 2 seconds

        return False
    except Exception:
        return False


def wake_up():
    """Set Angelique to awake state."""
    global IS_AWAKE
    with WAKE_LOCK:
        IS_AWAKE = True
    print("🌟 Angelique is now awake!")


def sleep():
    """Set Angelique to sleep state (no listening)."""
    global IS_AWAKE
    with WAKE_LOCK:
        IS_AWAKE = False
    print("😴 Angelique is now sleeping.")


def is_awake() -> bool:
    """Check if Angelique is awake."""
    with WAKE_LOCK:
        return IS_AWAKE


async def activation_protocol(audio_text: str, audio_samples: np.ndarray | None = None) -> bool:
    """
    Strict wake-word + clap protocol.
    1. Detect "Angelique" in speech
    2. Confirm with double clap
    Returns True if fully activated, False otherwise.
    """
    # Step 1: Detect wake word
    if not detect_wake_word(audio_text):
        return False

    # Step 2: Confirm with clap
    if not detect_clap(audio_samples):
        print("⚠️ Wake-word detected but no clap confirmation. Please clap twice to activate.")
        return False

    # Fully activated
    wake_up()
    return True
