FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY andina ./andina
COPY samples ./samples
# APP elige qué componente ejecuta este contenedor: gateway | facturacion | inventario | monolito
ENV APP=monolito PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "if [ \"$APP\" = monolito ]; then MOD=andina.monolito; else MOD=andina.$APP.api; fi; exec uvicorn $MOD:create_app --factory --host 0.0.0.0 --port ${PORT}"]
