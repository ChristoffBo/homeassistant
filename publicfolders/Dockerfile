ARG BUILD_FROM
FROM $BUILD_FROM

# Install node js
RUN \
  apk add --no-cache \
    nodejs npm

#Copy node file
COPY package.json /
COPY index.js /

# Copy run file
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
