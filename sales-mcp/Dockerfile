FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# noVNC fuer das Portal-Fenster (sales-ui). Der Hash des Release-Archivs (GitHub-Archiv des
# Tags) wurde am 11.11.2026 beim Ausrollen (Task 13) auf PC und VM unabhaengig gemessen und
# stimmte ueberein - nie raten. Neue Version = neuen Hash so messen. Leer = der noVNC-Schritt
# entfaellt, das Image baut trotzdem, es gibt dann nur kein Fenster (NOVNC_DIR ohne rfb.js).
ARG NOVNC_VERSION=1.5.0
ARG NOVNC_SHA256=6a73e41f98388a5348b7902f54b02d177cb73b7e5eb0a7a0dcf688cc2c79b42a
RUN if [ -n "$NOVNC_SHA256" ]; then\
      python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], '/tmp/novnc.tar.gz')"\
        "https://github.com/novnc/noVNC/archive/refs/tags/v${NOVNC_VERSION}.tar.gz"\
      && echo "${NOVNC_SHA256}  /tmp/novnc.tar.gz" | sha256sum -c -\
      && mkdir -p /app/static/novnc\
      && tar -xzf /tmp/novnc.tar.gz -C /app/static/novnc --strip-components=1\
           "noVNC-${NOVNC_VERSION}/core" "noVNC-${NOVNC_VERSION}/vendor" "noVNC-${NOVNC_VERSION}/LICENSE.txt"\
      && rm -f /tmp/novnc.tar.gz;\
    fi
COPY . .
EXPOSE 8765
CMD ["python", "server.py"]
