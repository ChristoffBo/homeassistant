FROM python:3.11-slim

RUN pip install flask requests

COPY uploader.py /app/uploader.py
COPY www/ /app/www/

WORKDIR /app
EXPOSE 8080

CMD ["python", "uploader.py"]
