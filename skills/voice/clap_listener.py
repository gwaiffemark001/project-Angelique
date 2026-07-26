import os
import time

try:
    import audioop
except Exception:  # pragma: no cover - very defensive fallback
    audioop = None

try:
    import pyaudio
except Exception:  # pragma: no cover - microphone backend may not be present
    pyaudio = None


CLAP_MIN_INTERVAL = 0.05
CLAP_MAX_INTERVAL = 0.45
CLAP_SILENCE_SECONDS = 0.12
CLAP_THRESHOLD = 1500

def is_double_clap_interval(delta_seconds: float) -> bool:
    return CLAP_MIN_INTERVAL <= delta_seconds <= CLAP_MAX_INTERVAL


class ClapListener:
    def __init__(self, threshold: int = CLAP_THRESHOLD) -> None:
        self.threshold = threshold
        self._available = pyaudio is not None and audioop is not None

    def is_available(self) -> bool:
        return self._available

    def detect_double_clap(self, timeout: float = 2.5) -> bool:
        if not self._available:
            return False

        pyaudio_module = pyaudio
        if pyaudio_module is None:
            return False

        try:
            audio = pyaudio_module.PyAudio()
            stream = audio.open(
                format=pyaudio_module.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=1024,
            )
        except Exception:
            return False

        start_time = time.monotonic()
        last_clap_time: float | None = None
        detected_claps = 0

        try:
            while time.monotonic() - start_time < timeout:
                chunk = stream.read(1024, exception_on_overflow=False)
                if audioop is None:
                    continue

                rms = audioop.rms(chunk, 2)
                if rms < self.threshold:
                    time.sleep(0.01)
                    continue

                now = time.monotonic()
                if last_clap_time is None:
                    last_clap_time = now
                    detected_claps = 1
                    continue

                delta = now - last_clap_time
                if is_double_clap_interval(delta):
                    return True

                if delta > CLAP_MAX_INTERVAL:
                    last_clap_time = now
                    detected_claps = 1
                    continue

                last_clap_time = now
                detected_claps = 1
                time.sleep(CLAP_SILENCE_SECONDS)
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
            try:
                audio.terminate()
            except Exception:
                pass

        return False
