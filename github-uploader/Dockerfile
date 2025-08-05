FROM python:3.10-alpine

RUN apk add --no-cache bash git && \
    pip install flask PyGithub

COPY run.sh /run.sh
COPY uploader.py /uploader.py
COPY index.html /index.html
COPY style.css /style.css
COPY app.js /app.js

RUN chmod +x /run.sh

CMD ["/run.sh"]