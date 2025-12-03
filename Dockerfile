# Dockerfile — Ubuntu base, Python + Tesseract
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install system deps and tesseract
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tesseract-ocr \
    libtesseract-dev \
    libjpeg-dev \
    libpng-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create app user and directory
RUN useradd -m botuser
WORKDIR /app

# Copy whole repo so test_env.py + bot.py are available
COPY . /app

# Install python deps
RUN python3 -m pip install --upgrade pip
RUN python3 -m pip install -r /app/requirements.txt

# Permissions and non-root user
RUN chown -R botuser:botuser /app
USER botuser

# Use the same PORT that Render sets (10000) — or set Render env to match this
ENV PORT=10000
EXPOSE 10000

# Start the bot (unbuffered stdout/stderr so logs appear live)
CMD ["python3", "-u", "bot.py"]
