//Modules
const fs = require('fs');
const http = require('http');
const path = require('path');

//Config
const PORT = process.env.PORT;
const FOLDERS = process.env.FOLDERS;

//Directory Mappings
const directories = { };

for (let str of FOLDERS.split("\n"))
{
	let split = str.split(":");
	directories[split[0]] = split[1];
}

//Error Handler
const error = (req, res, code) => {
	res.writeHead(200);
    res.end(code, 'utf-8');
};

//Handler:
const handler = (req, res) => {
	
	console.log("URL:", req.url);

	let parts = req.url.split("/");
	if (parts[0] == "") parts.shift();

	let location = parts.shift();
	if (!location) return error(req, res, "404");

	let base = directories[location];
	if (!base) return error(req, res, "404");

	let filepath = path.join(location, ...parts);

    fs.readFile(filepath, (err, data) => {
        if (err && err.code == 'ENOENT') return error(req, res, "404")
  		if (err) return error(req, res, "401");
       
        res.writeHead(200);
        res.end(data, 'utf-8');
    });
};

//Create http server.
console.log(`Starting HTTP server on port ${PORT}`);

http.createServer(handler).listen(PORT, () => {
	console.log(`HTTP server started.`);
});



