# 🧩 Ansible Semaphore — Home Assistant Add-on

This add-on runs the official Semaphore Docker image inside Home Assistant.  
It exposes the web UI on port 8055 (no ingress).  
It uses BoltDB stored under /share/ansible_semaphore.  
It auto-creates the admin user on first boot.

✅ Features
- Semaphore v2.16.17 web UI
- Persistent DB and playbooks under /share
- Auto admin creation on first boot
- Direct port access on 8055

📁 Paths
- Database: /share/ansible_semaphore/database.boltdb
- Playbooks: /share/ansible_semaphore/playbooks
- Temp (inside container): /tmp/semaphore

⚠️ First-Time Setup
1. SSH into your Home Assistant host  
2. Create required directories:  
   mkdir -p /share/ansible_semaphore/playbooks  
3. Create an empty DB file:  
   touch /share/ansible_semaphore/database.boltdb  
4. Fix permissions if needed:  
   chmod -R 0777 /share/ansible_semaphore  

🧪 Set Admin Credentials
In your add-on’s config.json environment section set:  
- SEMAPHORE_ADMIN = admin  
- SEMAPHORE_ADMIN_NAME = Admin  
- SEMAPHORE_ADMIN_EMAIL = admin@example.com  
- SEMAPHORE_ADMIN_PASSWORD = ChangeMe!123  

(You may change values as desired.)

🧹 Force Fresh First Boot (to ensure admin is created)
rm -f /share/ansible_semaphore/database.boltdb

🌍 Access
- URL: http://<homeassistant-ip>:8055  
- Username: admin (or the SEMAPHORE_ADMIN you set)  
- Password: ChangeMe!123 (or the SEMAPHORE_ADMIN_PASSWORD you set)  

🔑 Change this password immediately in the UI after first login.