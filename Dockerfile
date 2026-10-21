# ---- build stage: install deps, fetch data, run ETL and train the model ----
FROM python:3.12-slim AS build
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 FLEETLENS_DATA_DIR=/app/data
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --prefix=/install . && pip install .
RUN fleetlens all

# ---- runtime stage: only the installed package and built artifacts ----
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    FLEETLENS_DB_PATH=/app/data/fleetlens.db \
    FLEETLENS_MODEL_PATH=/app/data/mpg_model.joblib
COPY --from=build /install /usr/local
COPY --from=build /app/data/fleetlens.db /app/data/mpg_model.joblib /app/data/
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
CMD ["fleetlens", "serve", "--host", "0.0.0.0", "--port", "8000"]
