ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG C.UTF-8


RUN apk --no-cache --no-progress upgrade && \
    apk --no-cache --no-progress add jq openvpn \
    rm -rf /tmp/*


COPY run.sh /
RUN chmod a+x /run.sh
CMD [ "/run.sh" ]



