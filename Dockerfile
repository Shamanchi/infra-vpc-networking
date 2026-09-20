FROM python:3.11-slim AS base
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser
ENTRYPOINT ["python", "-m", "app.main"]
CMD ["plan", "--cidr", "10.0.0.0/16", "--azs", "2", "--newbits", "8", "--out", "plan.json"]

FROM base AS dev
CMD ["plan", "--cidr", "10.0.0.0/16", "--azs", "2", "--newbits", "8", "--out", "plan.json"]
