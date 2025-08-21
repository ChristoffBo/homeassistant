FROM adguard/adguardhome:latest

# Our wrapper becomes the container entrypoint
COPY run.sh /run.sh
RUN chmod +x /run.sh

# IMPORTANT: override base entrypoint so /run.sh is executed,
# and clear CMD so nothing is appended as an argument.
ENTRYPOINT ["/run.sh"]
CMD []