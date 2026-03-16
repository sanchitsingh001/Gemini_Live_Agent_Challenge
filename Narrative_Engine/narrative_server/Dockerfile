# Narrative server: trigger pipeline job, poll status. Build from Narrative_Engine root.
FROM python:3.11-slim
WORKDIR /app
COPY narrative_server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY narrative_server/ /app/narrative_server/
COPY gemini_client.py /app/
ENV PYTHONPATH=/app
ENV PORT=8080
EXPOSE 8080
CMD exec uvicorn narrative_server.main:app --host 0.0.0.0 --port ${PORT}
