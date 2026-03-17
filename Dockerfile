FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py .
COPY templates/ templates/

# Volume for SQLite persistence
VOLUME ["/data"]

CMD ["python", "main.py"]
