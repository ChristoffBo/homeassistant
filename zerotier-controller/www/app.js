const API_BASE = "/api";

function fetchAndDisplay(endpoint, elementId) {
  fetch(`${API_BASE}/${endpoint}`)
    .then(res => res.json())
    .then(data => {
      const el = document.getElementById(elementId);
      if (data.success) {
        el.textContent = data.output || data.identity || JSON.stringify(data, null, 2);
      } else {
        el.textContent = "Error: " + (data.error || "Unknown");
      }
    })
    .catch(err => {
      document.getElementById(elementId).textContent = "Request failed: " + err;
    });
}

function joinNetwork() {
  const id = document.getElementById("joinId").value.trim();
  if (!id) return alert("Enter a network ID to join.");
  fetch(`${API_BASE}/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ network_id: id })
  })
    .then(res => res.json())
    .then(data => {
      alert(data.success ? "Joined network!" : `Error: ${data.error}`);
      fetchAndDisplay("networks", "networks");
    });
}

function leaveNetwork() {
  const id = document.getElementById("leaveId").value.trim();
  if (!id) return alert("Enter a network ID to leave.");
  fetch(`${API_BASE}/leave`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ network_id: id })
  })
    .then(res => res.json())
    .then(data => {
      alert(data.success ? "Left network!" : `Error: ${data.error}`);
      fetchAndDisplay("networks", "networks");
    });
}

// Initial fetch
fetchAndDisplay("identity", "identity");
fetchAndDisplay("status", "status");
fetchAndDisplay("networks", "networks");