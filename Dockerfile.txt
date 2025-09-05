# Imagem leve com Python 3.11
FROM python:3.11-slim

# Configs básicas
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Depêndencias do sistema (mínimas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copia requisitos e instala
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copia o app
COPY . .

# Exponha a porta padrão do uvicorn
EXPOSE 8000

# Render injeta $PORT; use 0.0.0.0 para aceitar tráfego externo
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
