# Loan Default Risk Early Warning System — FastAPI service
FROM python:3.12-slim

# Keep Python lean and logs unbuffered for container-friendly output.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first so this layer is cached unless requirements change.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source.
COPY . .

# Run as a non-root user.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Configuration (e.g. LLM_API_TOKEN) is supplied at runtime via env / .env.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
