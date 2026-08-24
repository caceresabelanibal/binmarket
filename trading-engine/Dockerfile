FROM python:3.11-slim

WORKDIR /app

COPY shared /app/shared
RUN pip install --no-cache-dir -e /app/shared

COPY trading-engine/requirements.txt /app/trading-engine/requirements.txt
RUN pip install --no-cache-dir -r /app/trading-engine/requirements.txt

COPY trading-engine/app /app/trading-engine/app
COPY trading-engine/main.py /app/trading-engine/main.py

WORKDIR /app/trading-engine
CMD ["python", "-u", "main.py"]
