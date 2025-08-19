# Use the official upstream Semaphore container
FROM semaphoreui/semaphore:latest

# Add a minimal wrapper that prepares /share persistence and then execs Semaphore
# Use BuildKit COPY mode to avoid chmod issues in HA build env
COPY --chmod=0755 run.sh /usr/local/bin/run.sh

# Run our wrapper (it execs 'semaphore server --no-config')
ENTRYPOINT ["/usr/local/bin/run.sh"]