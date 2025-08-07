document.getElementById("uploadForm").addEventListener("submit", function(e) {
    e.preventDefault();
    const fileInput = document.getElementById("fileInput");
    const file = fileInput.files[0];
    if (!file) return alert("No file selected");

    const formData = new FormData();
    formData.append("file", file);

    fetch("/upload", {
        method: "POST",
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        const resBox = document.getElementById("response");
        if (data.success) {
            resBox.innerText = "Upload successful";
        } else {
            resBox.innerText = "Error: " + data.error;
        }
    });
});
