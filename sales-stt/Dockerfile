# sales-stt (01.09.2026) — Sprache zu Text, LOKAL.
#
# Eigenes Image statt Einbau in sales-mcp: faster-whisper bringt 431 MB
# mit, und das sales-mcp-Image steckt in SECHS Diensten (mcp, ui, inbox,
# dispatch, mail, linkedin). Sie alle um ein halbes Gigabyte wachsen zu
# lassen, damit einer davon transkribieren kann, waere teuer und falsch.
#
# Der Dienst hat KEINE Datenbank, KEINE Schluessel, KEINEN Netzzugang
# nach draussen (T5a-Haltung): er bekommt Audio, gibt Text zurueck.
FROM python:3.12-slim

# ffmpeg dekodiert die WhatsApp-Opus-Dateien; faster-whisper braucht es.
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Das Modell liegt im Volume (HF_HOME), nicht im Image: so bleibt das
# Image schlank und ein Neubau laedt nicht 300 MB neu.
ENV HF_HOME=/modelle
EXPOSE 2790
CMD ["python", "stt.py"]
