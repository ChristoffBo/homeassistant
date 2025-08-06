// app.js

function showTab(tabName) {
    const tabs = document.querySelectorAll('.tab');
    tabs.forEach(tab => tab.style.display = 'none');
    document.getElementById(tabName).style.display = 'block';
}

async function uploadZip() {
    const file = document.getElementById('zipFile').files[0];
    if (!file) return alert('No file selected');
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch('/upload', { method: 'POST', body: formData });
    const result = await res.json();
    alert(result.message || result.error);
}

async function pushToGit() {
    const token = document.getElementById('git_token').value;
    const remote = document.getElementById('git_remote').value;
    const author = document.getElementById('git_author').value;
    const email = document.getElementById('git_email').value;
    const res = await fetch('/push', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, remote, author, email })
    });
    const result = await res.json();
    alert(result.message || result.error);
}

async function runCommand(cmd) {
    const res = await fetch(`/git/${cmd}`);
    const result = await res.json();
    document.getElementById('gitOutput').textContent = result.stdout || result.error || 'No output';
}

async function commit() {
    const message = document.getElementById('commitMsg').value;
    const res = await fetch('/git/commit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message })
    });
    const result = await res.json();
    document.getElementById('gitOutput').textContent = result.stdout || result.error || 'No output';
}

async function downloadBackup() {
    window.location = '/backup';
}

async function uploadBackup() {
    const file = document.getElementById('restoreFile').files[0];
    if (!file) return alert('No file selected');
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch('/restore', { method: 'POST', body: formData });
    const result = await res.json();
    alert(result.message || result.error);
}

// Load config into fields
fetch('/config').then(res => res.json()).then(cfg => {
    document.getElementById('git_token').value = cfg.token || '';
    document.getElementById('git_remote').value = cfg.remote || '';
    document.getElementById('git_author').value = cfg.author || '';
    document.getElementById('git_email').value = cfg.email || '';
});
