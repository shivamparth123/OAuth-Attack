FROM python:3.11-slim
WORKDIR /app
RUN pip install flask requests --no-cache-dir
COPY app.py .
COPY app_hardened.py .
EXPOSE 8083
CMD ["python", "app.py"]
