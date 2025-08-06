FROM python:3.11-slim

WORKDIR /app

COPY uploader.py /app/uploader.py
COPY toolkit.py /app/toolkit.py
COPY www /app/www

RUN pip install flask

EXPOSE 8099

CMD ["python3", "/app/uploader.py"]

