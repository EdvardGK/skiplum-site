# syntax=docker/dockerfile:1
# Self-hosted image for skiplum-apps-1 (see skiplum/internal/infra/apps-server).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# streamlit + ifcopenshell pinned to the combination the Fargekoding image runs;
# the rest resolves from requirements.txt (ifcfast, pyproj, folium, plotly...).
COPY requirements.txt ./
RUN pip install streamlit==1.58.0 ifcopenshell==0.8.5 && pip install -r requirements.txt

COPY app.py ./
COPY core ./core
COPY frontend ./frontend
COPY .streamlit ./.streamlit

RUN useradd -m app && mkdir -p /app/output && chown -R app /app
USER app

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3).read()==b'ok' else 1)"

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
