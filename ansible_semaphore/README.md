# 🧩 Ansible Semaphore — Home Assistant Add-on

This add-on runs the official Semaphore Docker image inside Home Assistant.  
It exposes the web UI on port **8055** (no ingress).  
It uses **Sqlite** stored under `/share/ansible_semaphore`.  
It auto-creates the **admin user** on first boot.

---

## What it is and what it is used for

**Ansible Semaphore** is a web-based user interface for **Ansible**. It lets you run playbooks, manage inventories, store SSH keys and variables, schedule jobs, and view results from a browser.  
Running Semaphore in **Home Assistant** makes sense because both are automation tools: Home Assistant handles smart‑home workflows, while Semaphore can automate your servers, VMs, containers, network gear, and OS tasks from the same box and with the same persistent storage.

---

## Features
- Semaphore web UI  
- Persistent DB and playbooks under `/share`  
- Auto admin creation on first boot  
- Direct port access on **8055**  
- Based on official `semaphoreui/semaphore:latest`  

---

## Paths
- **Database**: `/share/ansible_semaphore/semaphore.db`  
- **Playbooks**: `/share/ansible_semaphore/playbooks`  
- **Keys**: `/share/ansible_semaphore/keys`  
- **Logs**: `/share/ansible_semaphore/logs`  
- **Temp (inside container)**: `/tmp/semaphore`  

---

## First-Time Setup (required)

Semaphore runs as a non‑root user inside the container. It cannot create your persistence folders under `/share` by itself.  
Create them **once** before first boot:

```bash
mkdir -p /share/ansible_semaphore/{playbooks,keys,logs,tmp}
touch /share/ansible_semaphore/semaphore.db
chmod -R 0777 /share/ansible_semaphore
```

This ensures Semaphore can read/write its DB, playbooks, keys, and logs.

---

## Why BoltDB?

- **Simple & embedded** — single file (`database.boltdb`), no external DB service.  
- **Ideal for Home Assistant** — minimal dependencies; persists cleanly under `/share`.  
- **Lightweight & reliable** — fits the “appliance” model for add‑ons.

---

## Default First User

On first start, the add-on creates this admin account:

- **Username**: `admin`  
- **Password**: `ChangeMe!123`  
- **Email**: `admin@example.com`  
- **Name**: `Admin`  

---

## SECURITY WARNING

Immediately after your first login, change the admin password in the Semaphore web UI.  
The default credentials are public and **must not remain in use**.

---

## Force Fresh First Boot

To reset Semaphore and recreate the admin user:

```bash
rm -f /share/ansible_semaphore/database.boltdb
```

---

## Access
- **URL**: `http://<home-assistant>:8055`  
- **Login**: use the credentials above  
