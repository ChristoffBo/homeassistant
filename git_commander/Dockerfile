FROM python:3.11-slim

WORKDIR /data

COPY uploader.py ./uploader.py
COPY www ./www

RUN pip install flask

EXPOSE 8099

CMD ["python3", "uploader.py"]
