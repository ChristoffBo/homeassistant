async function uploadZip() {
  const file = document.getElementById("zipfile").files[0];
  if (!file) return alert("Select a ZIP file first.");

  const formData = new FormData();
  formData.append("zipfile", file);

  const res = await fetch("/upload", {
    method: "POST",
    body: formData,
  });

  const data = await res.json();
  alert(data.success || data.error);
}

async function runGitCommand() {
  const cmd = document.getElementById("git_cmd").value;
  const res = await fetch("/git", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command: cmd }),
  });

  const data = await res.json();
  document.getElementById("git_output").innerText = data.stdout || data.stderr || data.error;
}

async function downloadBackup() {
  const res = await fetch("/backup");
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "git_commander_backup.tar.gz";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function uploadBackup() {
  const file = document.getElementById("restore_file").files[0];
  if (!file) return alert("Choose a backup file first.");

  const formData = new FormData();
  formData.append("backupfile", file);

  const res = await fetch("/restore", {
    method: "POST",
    body: formData,
  });

  const data = await res.json();
  alert(data.success || data.error);
}

window.onload = async () => {
  const res = await fetch("/config");
  const config = await res.json();

  document.getElementById("github_url").value = config.github_url || "";
  document.getElementById("gitea_url").value = config.gitea_url || "";
  document.getElementById("repository").value = config.repository || "";
};
