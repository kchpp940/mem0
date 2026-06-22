FROM python:3.12-slim

LABEL org.opencontainers.image.name="mem0/openmemory-mcp"

WORKDIR /usr/src/openmemory

COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy shared config loader — must be in place before the app starts
COPY _env_loader.py .
COPY entrypoint.py .
RUN chmod +x entrypoint.py

COPY config.json .
COPY . .

EXPOSE 8765
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "./entrypoint.py", "--service", "openmemory-api", "--run-migrations", "--"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8765"]
