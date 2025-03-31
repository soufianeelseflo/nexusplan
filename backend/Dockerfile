# Use a specific, stable Python slim image version
FROM python:3.11.9-slim

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
# Set default encoding
ENV PYTHONIOENCODING=UTF-8
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# Set working directory
WORKDIR /app

# Install system dependencies
# - build-essential & libpq-dev are common for some Python packages with C extensions
# - curl, gnupg, wget needed for Chrome install (if uncommented)
# - procps needed for process management/debugging inside container
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       # libpq-dev # Uncomment if using PostgreSQL
       curl \
       gnupg \
       wget \
       procps \
    && rm -rf /var/lib/apt/lists/*

# --- OPTIONAL: Install Google Chrome & ChromeDriver for Selenium ---
# Uncomment this section ONLY if dynamic scraping with Selenium is essential
# This significantly increases image size (~500MB+)
# RUN apt-get update && apt-get install -y --no-install-recommends fonts-liberation libu2f-udev \
#     && wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
#     && apt-get install -y ./google-chrome-stable_current_amd64.deb \
#     && rm google-chrome-stable_current_amd64.deb \
#     # Install ChromeDriver using webdriver-manager during runtime is often easier
#     # Or install a specific version matching the Chrome version above
#     # && CHROME_VERSION=$(google-chrome --version | cut -d' ' -f3) \
#     # && CHROME_MAJOR_VERSION=$(echo $CHROME_VERSION | cut -d'.' -f1) \
#     # && DRIVER_VERSION=$(curl -sS https://chromedriver.storage.googleapis.com/LATEST_RELEASE_${CHROME_MAJOR_VERSION}) \
#     # && wget -q https://chromedriver.storage.googleapis.com/${DRIVER_VERSION}/chromedriver_linux64.zip \
#     # && unzip chromedriver_linux64.zip -d /usr/local/bin/ \
#     # && rm chromedriver_linux64.zip \
#     # && chmod +x /usr/local/bin/chromedriver \
#     && rm -rf /var/lib/apt/lists/*
# --- END OPTIONAL CHROME INSTALL ---

# Upgrade pip and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user for security
RUN useradd --create-home appuser
WORKDIR /home/appuser/app
USER appuser

# Copy application code as non-root user
COPY --chown=appuser:appuser ./app /home/appuser/app/app

# Expose the port the application runs on (matching Uvicorn command)
EXPOSE 8000

# Set the default command to run the application using Uvicorn
# Use --workers 1 initially for simplicity with schedule/threading
# For higher load, consider Gunicorn with Uvicorn workers and a separate process/queue for scheduled tasks
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]