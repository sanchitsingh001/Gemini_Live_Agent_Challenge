# Game server for Narrator Web Game (FastAPI).
# Build from Narrative_Engine root: docker build -f game_server/Dockerfile .
FROM python:3.11-slim
WORKDIR /app
COPY game_server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY gemini_client.py /app/
COPY game_server/npc_tts.py /app/npc_tts.py
COPY game_server/npc_voice_profiles.json /app/npc_voice_profiles.json
COPY game_server/main.py /app/main.py
ENV PYTHONPATH=/app
ENV PORT=8080
EXPOSE 8080
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}
