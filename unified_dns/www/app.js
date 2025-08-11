document.addEventListener("DOMContentLoaded", function () {
    const basePath = window.location.pathname.replace(/\/$/, '');

    // Elements
    const addServerBtn = document.getElementById("add-server");
    const saveServerBtn = document.getElementById("save-server");
    const serverNameInput = document.getElementById("server-name");
    const serverTypeInput = document.getElementById("server-type");
    const serversList = document.getElementById("servers-list");

    // Load existing config
    fetch(`${basePath}/api/options`)
        .then(r => r.json())
        .then(data => {
            console.log("Loaded config:", data);
            renderServers(data.servers || []);
        });

    // Save server
    saveServerBtn.addEventListener("click", function () {
        const name = serverNameInput.value.trim();
        const type = serverTypeInput.value.trim();

        if (!name || !type) {
            alert("Please enter server name and type.");
            return;
        }

        fetch(`${basePath}/api/options`)
            .then(r => r.json())
            .then(config => {
                config.servers = config.servers || [];
                config.servers.push({
                    name: name,
                    type: type,
                    primary: false
                });
                return fetch(`${basePath}/api/options`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(config)
                });
            })
            .then(r => r.json())
            .then(resp => {
                if (resp.status === "ok") {
                    alert("Server saved.");
                    fetch(`${basePath}/api/options`)
                        .then(r => r.json())
                        .then(data => renderServers(data.servers || []));
                } else {
                    alert("Error saving server: " + resp.message);
                }
            })
            .catch(err => alert("Failed to save: " + err));
    });

    function renderServers(servers) {
        serversList.innerHTML = "";
        servers.forEach(srv => {
            const li = document.createElement("li");
            li.textContent = `${srv.name} (${srv.type})`;
            serversList.appendChild(li);
        });
    }
});