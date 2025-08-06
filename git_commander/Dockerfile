FROM python:3.11-slim
WORKDIR /data
COPY uploader.py /data/uploader.py
COPY www /data/www
RUN pip install flask
EXPOSE 8099
CMD ["python3", "/data/uploader.py"]
