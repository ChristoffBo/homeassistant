# 🧩 Ansible Semaphore (Home Assistant Add-on)

This add-on runs [Ansible Semaphore](https://semaphoreui.com/), a modern web UI for managing and running Ansible playbooks.  
It uses a built-in SQLite database and is fully self-contained.

✅ Features
- Web UI for Ansible playbook automation
- Built-in SQLite backend (no external DB required)
- Configurable admin username, email, and password
- Ingress support (opens inside Home Assistant)
- Persistent storage under /config

📁 Paths
- Data: /config/ansible_semaphore
- Database: /config/ansible_semaphore/semaphore.db
- Playbooks: /config/ansible_semaphore/playbooks

⚙️ Configuration
```json
{
  "port": 10443,
  "admin_user": "admin",
  "admin_email": "admin@example.com",
  "admin_password": "changeme"
}
