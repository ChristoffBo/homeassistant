// Mode Management  
let currentMode = 'chat';  

function setMode(mode) {  
  try {  
    if (!['chat', 'code', 'teach'].includes(mode)) {  
      throw new Error(`Invalid mode: ${mode}`);  
    }  
    currentMode = mode;  
    document.querySelectorAll('.mode-content').forEach(el => {  
      el.style.display = el.id === `mode-${mode}` ? 'block' : 'none';  
    });  
    document.querySelectorAll('.mode-btn').forEach(btn => {  
      btn.classList.toggle('active', btn.dataset.mode === mode);  
    });  
  } catch (err) {  
    console.error("Mode switch failed:", err);  
  }  
}  

// Git Push (Code Mode)  
async function pushToGit() {  
  try {  
    const code = document.getElementById('code-editor').value;  
    if (!code.trim()) {  
      throw new Error("Code cannot be empty!");  
    }  

    const filename = prompt("Filename (e.g., 'my_addon.py'):")?.trim();  
    if (!filename || !/\.(py|yaml|json)$/i.test(filename)) {  
      throw new Error("Filename must end with .py, .yaml, or .json");  
    }  

    const response = await fetch('/git_push', {  
      method: 'POST',  
      headers: { 'Content-Type': 'application/json' },  
      body: JSON.stringify({ code, filename })  
    });  

    const result = await response.json();  
    if (!response.ok) throw new Error(result.error || "Push failed");  
    alert("✅ Pushed to Git successfully!");  
  } catch (err) {  
    alert(`❌ Error: ${err.message}`);  
    console.error("Git push failed:", err);  
  }  
}  

// Initialize  
document.addEventListener('DOMContentLoaded', () => {  
  try {  
    // Set default mode  
    const savedMode = localStorage.getItem('aiAssistantMode') || 'chat';  
    setMode(savedMode);  

    // Event listeners  
    document.querySelectorAll('.mode-btn').forEach(btn => {  
      btn.addEventListener('click', () => {  
        const mode = btn.dataset.mode;  
        setMode(mode);  
        localStorage.setItem('aiAssistantMode', mode);  
      });  
    });  

    // Code mode setup  
    if (document.getElementById('git-push-btn')) {  
      document.getElementById('git-push-btn').addEventListener('click', pushToGit);  
    }  
  } catch (err) {  
    console.error("Initialization failed:", err);  
  }  
});  
