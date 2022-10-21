FROM https://hub.docker.com/r/technitium/dns-server:latest





ENV CONFIG_PATH=/data    
  
COPY install.sh /
RUN chmod a+x /install.sh
CMD [ "/install.sh" ]



