document.getElementById("uploadForm").addEventListener("submit", async function (e) {
  e.preventDefault();
  const form = e.target;
  const status = document.getElementById("status");
  status.textContent = "Uploading...";

  const data = new FormData(form);
  try {
    const res = await fetch("/upload", {
      method: "POST",
      body: data
    });

    const text = await res.text();
    try {
      const json = JSON.parse(text);
      if (json.status === "success") {
        status.textContent = "Upload complete:\n" + json.results.join("\n");
      } else {
        status.textContent = "Error:\n" + json.message;
      }
    } catch {
      status.textContent = "Invalid response format:\n" + text;
    }
  } catch (err) {
    status.textContent = "Upload failed:\n" + err.message;
  }
});