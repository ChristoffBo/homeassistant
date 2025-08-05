document.getElementById("uploadForm").onsubmit = async function(event) {
  event.preventDefault();

  const form = document.getElementById("uploadForm");
  const formData = new FormData(form);

  try {
    const res = await fetch("/upload", {
      method: "POST",
      body: formData
    });

    const json = await res.json();

    if (json.status === "success") {
      const lines = json.results.join("\n");
      document.getElementById("status").innerText = "✅ Upload complete:\n" + lines;
    } else {
      document.getElementById("status").innerText = "❌ Upload failed: " + json.message;
    }
  } catch (e) {
    document.getElementById("status").innerText = "❌ Upload error: " + e.message;
  }
};