# Home Assistant add-on that uses klutchell/dnscrypt-proxy
FROM klutchell/dnscrypt-proxy:latest

# Add jq + bash for option parsing
RUN apk add --no-cache jq bash

# Copy entry script
COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

ENTRYPOINT ["/usr/local/bin/run.sh"]