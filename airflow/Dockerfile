FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY summarizer/ ./summarizer/

ENV LLM_MODEL=default
ENV LLM_API_BASE=http://localhost:8000
ENV LLM_API_KEY=sk-placeholder

ENTRYPOINT ["python", "-m", "summarizer.main"]
