async function loadNetworks() {
    const res = await fetch('/api/networks');
    const data = await res.json();
    const tbody = document.getElementById('networks').querySelector('tbody');
    tbody.innerHTML = '';
    data.forEach(net => {
        const row = `<tr>
            <td>${net.id}</td>
            <td>${net.name}</td>
            <td>${net.memberCount}</td>
            <td><button onclick="viewNetwork('${net.id}')">View</button></td>
        </tr>`;
        tbody.innerHTML += row;
    });
}

function viewNetwork(id) {
    alert("Feature coming soon: View network " + id);
}

window.onload = loadNetworks;