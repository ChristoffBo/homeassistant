# Home Assistant add-on for Ansible Semaphore
# Base: official upstream image (no package installs, no chmod)
FROM semaphoreui/semaphore:latest

USER root

# Copy a tiny wrapper that ensures persistent dirs then execs semaphore
# We will invoke it with /bin/sh, so executable bit is not required.
COPY run.sh /usr/local/bin/run.sh

# Workdir points to where we persist, but semaphore uses env paths below
WORKDIR /share/ansible_semaphore

# No ENTRYPOINT change; just run our wrapper with sh (no chmod)
CMD ["/bin/sh", "/usr/local/bin/run.sh"]