# sales-ki (12.11.2026): Claude Code hinter einer Ollama-kompatiblen Schnittstelle
# (ki_tor.py). Vorbild: Debugger-Claw auf der VM (Claude Code 2.1.268, Node 22
# aus NodeSource, weil bookworms Node 18 nicht reicht).
FROM python:3.12-slim-bookworm

ARG CLAUDE_CODE_VERSION=2.1.268
ARG NODE_MAJOR=22

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
 && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /usr/share/keyrings/nodesource.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
      > /etc/apt/sources.list.d/nodesource.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends nodejs \
 && apt-get purge -y curl gnupg \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# --engine-strict: verlangt claude-code eine neuere Node-Version, bricht der Build ab.
RUN npm install -g --engine-strict "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && npm cache clean --force \
 && claude --version

# Eigener Nutzer ohne Rechte; HOME beschreibbar, weil Claude Code dort seinen
# Zustand ablegt (geht mit dem Container, keine Sitzungen: --no-session-persistence).
RUN useradd --create-home --uid 10001 ki
WORKDIR /app
COPY ki_tor.py /app/ki_tor.py
USER ki
ENV PYTHONUNBUFFERED=1 DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
EXPOSE 11434
CMD ["python", "/app/ki_tor.py"]
