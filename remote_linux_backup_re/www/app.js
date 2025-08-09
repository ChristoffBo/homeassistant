async function api(path, opts={}) {
  const r = await fetch(path, Object.assign({headers: {"Content-Type":"application/json"}}, opts));
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function loadOptions() {
  const data = await api("/api/options");
  // Expect textarea inputs with ids matching keys
  document.getElementById("known_hosts").value = (data.known_hosts||[]).join("\n");
  document.getElementById("server_presets").value = (data.server_presets||[]).join("\n");
  document.getElementById("jobs").value = (data.jobs||[]).join("\n");
  document.getElementById("nas_mounts").value = (data.nas_mounts||[]).join("\n");
  // Show read-only HA options for reference
  document.getElementById("ui_port").textContent = data.ui_port;
}

async function saveOptions() {
  const payload = {
    known_hosts: document.getElementById("known_hosts").value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean),
    server_presets: document.getElementById("server_presets").value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean),
    jobs: document.getElementById("jobs").value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean),
    nas_mounts: document.getElementById("nas_mounts").value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean)
  };
  const res = await api("/api/options", {method:"POST", body: JSON.stringify(payload)});
  document.getElementById("save_status").textContent = res.ok ? "Saved." : "Failed.";
  await loadOptions(); // reload to confirm persisted values
}

document.addEventListener("DOMContentLoaded", () => {
  loadOptions().catch(console.error);
  document.getElementById("save_btn").addEventListener("click", (e) => {
    e.preventDefault(); saveOptions().catch(err => {
      document.getElementById("save_status").textContent = "Error: " + err.message;
    });
  });
});
