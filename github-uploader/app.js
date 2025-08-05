document.getElementById("uploadForm").onsubmit = async function(event) {
  event.preventDefault();
  const formData = new FormData(document.getElementById("uploadForm"));
  const res = await fetch("/upload", {
    method: "POST",
    body: formData
  });
  const json = await res.json();
  document.getElementById("status").innerText = json.status === "success" ? "✅ Uploaded." : "❌ Failed.";
}