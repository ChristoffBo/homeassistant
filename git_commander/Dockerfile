FROM python:3.10-slim

WORKDIR /app
COPY uploader.py /app/
COPY toolkit.py /app/
COPY www /app/www

RUN pip install flask

CMD ["python3", "/app/uploader.py"]