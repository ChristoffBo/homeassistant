function showTab(tabId) {
  document.querySelectorAll('.tab').forEach(t => t.style.display = 'none');
  document.getElementById(tabId).style.display = 'block';
}

window.onload = () => {
  showTab('uploader');
  fetch('/config').then(res => res.json()).then(data => {
    document.getElementById('configOutput').innerText = JSON.stringify(data, null, 2);
  });
};