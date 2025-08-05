document.getElementById("uploadForm").addEventListener("submit", async function (e) {
  e.preventDefault();
  const form = e.target;
  const data = new FormData(form);
  const status = document.getElementById("status");

  status.textContent = "Uploading...";

  try {
    const res = await fetch("/upload", {
      method: "POST",
      body: data,
    });

    const json = await res.json();

    if (json.status === "success") {
      status.textContent = "Upload complete:\n" + json.results.join("\n");
    } else {
      status.textContent = "Error:\n" + json.message;
    }
  } catch (err) {
    status.textContent = "Error:\n" + err.toString();
  }
});