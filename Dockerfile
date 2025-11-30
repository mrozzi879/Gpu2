# Dockerfile — Ubuntu base, Python + Tesseract
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install system deps and tesseract
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    tesseract-ocr \
    libtesseract-dev \
    libjpeg-dev \
    libpng-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create app user and directory
RUN useradd -m botuser
WORKDIR /app
COPY requirements.txt /app/requirements.txt

# Install python deps
RUN python3 -m pip install --upgrade pip
RUN python3 -m pip install -r /app/requirements.txt

# Copy bot code
COPY bot.py /app/bot.py
RUN chown -R botuser:botuser /app
USER botuser

# Expose port for health check
ENV PORT=8080
EXPOSE 8080

CMD ["python3", "bot.py"]
