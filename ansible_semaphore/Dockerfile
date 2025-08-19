# Dockerfile – ensure we are root to create symlinks and install entrypoint
USER root
COPY run.sh /usr/local/bin/run.sh
RUN chmod 0755 /usr/local/bin/run.sh
ENTRYPOINT ["/usr/local/bin/run.sh"]