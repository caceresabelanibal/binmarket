FROM python:3.11-slim

WORKDIR /app

COPY shared /app/shared
RUN pip install --no-cache-dir -e /app/shared

COPY market-data/requirements.txt /app/market-data/requirements.txt
RUN pip install --no-cache-dir -r /app/market-data/requirements.txt

COPY market-data/app /app/market-data/app
COPY market-data/main.py /app/market-data/main.py

WORKDIR /app/market-data
CMD ["python", "-u", "main.py"]
