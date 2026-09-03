FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends sqlite3 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config
COPY scripts ./scripts
COPY tests ./tests

CMD ["sh", "-lc", "if [ -n \"$TELEGRAM_BOT_TOKEN\" ]; then python -m app.telegram.bot; else echo 'TELEGRAM_BOT_TOKEN missing; container idle until configured'; tail -f /dev/null; fi"]
