FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY oddscore.py bot.py ./

# Run as a non-root user
RUN useradd --create-home botuser
USER botuser

# DISCORD_TOKEN (required) and PARLAY_API_KEY (recommended) are passed
# at run time: docker run -e DISCORD_TOKEN=... -e PARLAY_API_KEY=... image
CMD ["python3", "bot.py"]
