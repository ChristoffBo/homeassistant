# 🧩 Rundeck — Home Assistant Add-on

Rundeck is an automation and orchestration platform that lets you run jobs, scripts, and workflows across your servers, containers, and services from a single web interface. It is often used for routine operations, scheduled tasks, incident response, and self-service automation. With Rundeck you can securely run commands, manage nodes, control access, and create repeatable automation jobs that are logged and auditable.

✅ Brings Rundeck automation & orchestration with its full Web UI  
✅ Based on official Docker image (rundeck/rundeck)  
✅ Persistent storage via /config  

🔑 First start login:  
Username: admin  
Password: admin  

📁 Key Paths:  
- /config/rundeck → stores Rundeck data  

⚙️ Example options.json:  
{  
  "ui_port": 4440  
}  

🌍 Web UI:  
- Open Ingress from the HA sidebar  
- Or use: http://homeassistant.local:4440  

🧠 Fully self-hosted — runs Rundeck automation inside Home Assistant.
