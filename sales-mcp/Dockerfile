FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# noVNC fuer das Portal-Fenster (sales-ui). Der Hash des Release-Archivs wird beim ersten
# echten Bau beim Ausrollen eingetragen (Task 13) - nie geraten. Leer = der noVNC-Schritt
# entfaellt, das Image baut trotzdem, es gibt dann nur kein Fenster (NOVNC_DIR ohne rfb.js).
ARG NOVNC_VERSION=1.5.0
ARG NOVNC_SHA256=
RUN if [ -n "$NOVNC_SHA256" ]; then\
      python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], '/tmp/novnc.tar.gz')"\
        "https://github.com/novnc/noVNC/archive/refs/tags/v${NOVNC_VERSION}.tar.gz"\
      && echo "${NOVNC_SHA256}  /tmp/novnc.tar.gz" | sha256sum -c -\
      && mkdir -p /tmp/novnc /app/static/novnc\
      && tar -xzf /tmp/novnc.tar.gz -C /tmp/novnc --strip-components=1\
      && cp -r /tmp/novnc/core /tmp/novnc/vendor /tmp/novnc/LICENSE.txt /app/static/novnc/\
      && rm -rf /tmp/novnc /tmp/novnc.tar.gz;\
    fi
COPY . .
EXPOSE 8765
CMD ["python", "server.py"]
