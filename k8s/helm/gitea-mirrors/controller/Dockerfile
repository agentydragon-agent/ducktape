FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY gitea_mirror_controller.py .

CMD ["python", "-u", "gitea_mirror_controller.py"]