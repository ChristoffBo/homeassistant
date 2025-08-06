window.onload = async () => {
  try {
    const res = await fetch("/config");
    const config = await res.json();

    document.getElementById("github_url").value = config.github_url || "";
    document.getElementById("github_token").value = config.github_token || "";
    document.getElementById("gitea_url").value = config.gitea_url || "";
    document.getElementById("gitea_token").value = config.gitea_token || "";
    document.getElementById("repository").value = config.repository || "";
    document.getElementById("commit_message").value = config.commit_message || "";
  } catch (err) {
    console.error("Failed to load config:", err);
  }
};
