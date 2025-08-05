window.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("uploadForm");
  const statusDiv = document.getElementById("status");

  if (!form) {
    console.error("Upload form not found.");