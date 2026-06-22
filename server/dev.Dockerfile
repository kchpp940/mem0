FROM python:3.12

WORKDIR /app

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

# Copy requirements first for better caching
COPY server/requirements.txt .
RUN pip install -r requirements.txt

# Install mem0 in editable mode using Poetry
WORKDIR /app/packages
COPY pyproject.toml .
COPY poetry.lock .
COPY README.md .
COPY mem0 ./mem0
RUN pip install -e .[graph]

# Return to app directory and copy server code
WORKDIR /app/server
COPY server .

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "./entrypoint.py", "--service", "server", "--run-migrations", "--"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
