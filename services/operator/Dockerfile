FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py repository.py queries.py support.py ./

EXPOSE 8502
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8502/_stcore/health')"
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8502"]
