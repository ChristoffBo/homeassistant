FROM python:3.11-slim

WORKDIR /

RUN pip install flask PyGithub

COPY uploader.py /
COPY index.html /
COPY style.css /
COPY app.js /

EXPOSE 8080

CMD ["python3", "/uploader.py"]