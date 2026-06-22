FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared config loader — must be in place before the app starts
COPY _env_loader.py .
COPY entrypoint.py .
RUN chmod +x entrypoint.py

COPY . .

EXPOSE 8000
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "./entrypoint.py", "--service", "server", "--run-migrations", "--"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
