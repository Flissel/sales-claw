# Laedt das Whisper-Modell vor dem ersten echten Termin (Download von
# HuggingFace beim ersten Aufruf, danach liegt es im Volume vexa-whisper-modelle).
# Schickt eine Sekunde Stille als model=whisper-1, genau wie Vexa es tut; der
# Server ordnet das dem eingestellten Modell zu (faster-whisper-server,
# routers/stt.py). Aufruf (Runbook), liest das Skript von stdin:
#
#   docker exec -i vexa-lite-whisper python3 - < deploy/vexa/whisper-aufwaermen.py
#
# Gibt "whisper warm: HTTP 200" aus. Der erste Lauf kann mehrere Minuten dauern.
import io
import urllib.request
import uuid
import wave

ZIEL = "http://127.0.0.1:8000/v1/audio/transcriptions"

roh = io.BytesIO()
with wave.open(roh, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(16000)
    w.writeframes(b"\x00\x00" * 16000)

grenze = uuid.uuid4().hex
kopf = (
    f'--{grenze}\r\nContent-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n'
    f'--{grenze}\r\nContent-Disposition: form-data; name="file"; filename="stille.wav"\r\n'
    "Content-Type: audio/wav\r\n\r\n"
).encode()
koerper = kopf + roh.getvalue() + f"\r\n--{grenze}--\r\n".encode()
anfrage = urllib.request.Request(
    ZIEL, data=koerper, headers={"Content-Type": f"multipart/form-data; boundary={grenze}"}
)
with urllib.request.urlopen(anfrage, timeout=900) as antwort:
    print(f"whisper warm: HTTP {antwort.status}")
