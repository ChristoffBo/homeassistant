const express = require('express');
const multer = require('multer');
const axios = require('axios');
const fs = require('fs');
const path = require('path');
const app = express();
const upload = multer({ dest: '/tmp/uploads/' });

app.use(express.json());
app.use(express.static('public'));

// Serve the main UI
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// Handle zip file upload
app.post('/upload', upload.single('zipfile'), async (req, res) => {
  const githubUrl = process.env.GITHUB_URL;
  const githubToken = process.env.GITHUB_TOKEN;
  const githubUsername = process.env.GITHUB_USERNAME;
  const repoName = githubUrl.split('/').slice(-2).join('/');

  try {
    // Extract zip to pi_zip folder
    const unzipPath = '/data/pi_zip';
    await exec(`unzip -o ${req.file.path} -d ${unzipPath}`);

    // Upload to GitHub
    const files = fs.readdirSync(unzipPath, { recursive: true });
    for (const file of files) {
      const filePath = path.join(unzipPath, file);
      if (fs.lstatSync(filePath).isFile()) {
        const content = fs.readFileSync(filePath, { encoding: 'base64' });
        await axios.put(
          `https://api.github.com/repos/${repoName}/contents/pi_zip/${file}`,
          {
            message: `Add ${file} from zip upload`,
            content: content,
            committer: { name: githubUsername, email: `${githubUsername}@users.noreply.github.com` }
          },
          { headers: { Authorization: `token ${githubToken}` } }
        );
      }
    }
    res.json({ message: 'Zip file uploaded and extracted to GitHub' });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Download repo as zip
app.get('/download', async (req, res) => {
  const githubUrl = process.env.GITHUB_URL;
  const repoName = githubUrl.split('/').slice(-2).join('/');
  const downloadUrl = `https://github.com/${repoName}/archive/refs/heads/main.zip`;
  res.json({ downloadUrl });
});

app.listen(80, () => console.log('Server running on port 80'));
