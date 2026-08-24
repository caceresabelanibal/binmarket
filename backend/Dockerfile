FROM python:3.11-slim

WORKDIR /app

COPY shared /app/shared
RUN pip install --no-cache-dir -e /app/shared

COPY database /app/database

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/app /app/backend/app
COPY backend/entrypoint.sh /app/backend/entrypoint.sh
RUN chmod +x /app/backend/entrypoint.sh

WORKDIR /app/backend
EXPOSE 8000

CMD ["/app/backend/entrypoint.sh"]
