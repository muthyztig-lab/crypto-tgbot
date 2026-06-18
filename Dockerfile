FROM python:3.12-slim

# cairo не обов'язковий: є власний растеризатор на Pillow.
# Але якщо хочете якісніший SVG->PNG — розкоментуйте libcairo2.
# RUN apt-get update && apt-get install -y --no-install-recommends libcairo2 \
#     && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Дані (БД, обране) — у томі, щоб переживали перезапуск
VOLUME ["/app/data"]

CMD ["python", "bot.py"]
