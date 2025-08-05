window.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("uploadForm");
  const statusDiv = document.getElementById("status");

  if (!form) {
    console.error("Upload form not found.");
    return;
  }

  form.onsubmit = async function (event) {
    event.preventDefault();

    const formData = new FormData(form);
    statusDiv.innerText = "⏳ Uploading...";

    try {
      const response = await fetch("/upload", {
        method: "POST",
        body: formData
      });

      const result = await response.json();
      if (result.status === "success") {
        statusDiv.innerText = result.results.join("\n");
      } else {
        statusDiv.innerText = "❌ Upload failed: " + result.message;
      }
    } catch (err) {
      console.error("Upload error:", err);
      statusDiv.innerText = "❌ Upload error: " + err.message;
    }
  };
});