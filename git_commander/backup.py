from flask import Flask, send_file
import shutil, os

backup = Flask(__name__)

@backup.route('/api/backup', methods=['GET'])
def backup_zip():
    source_dir = "/data"
    output_file = "/data/git_backup.zip"
    shutil.make_archive("/data/git_backup", 'zip', source_dir)
    return send_file(output_file, as_attachment=True)

backup.run(host="0.0.0.0", port=8083)
