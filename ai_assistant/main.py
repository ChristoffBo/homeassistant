from flask import Flask, request, jsonify, send_from_directory  
import subprocess  
import tempfile  
import os  
import logging  
from werkzeug.security import safe_join  

app = Flask(__name__)  
logging.basicConfig(level=logging.INFO)  

# Security headers  
@app.after_request  
def add_headers(response):  
    response.headers['X-Content-Type-Options'] = 'nosniff'  
    response.headers['X-Frame-Options'] = 'DENY'  
    response.headers['Content-Security-Policy'] = "default-src 'self'"  
    return response  

# Serve UI  
@app.route('/')  
def serve_ui():  
    return send_from_directory('templates', 'index.html')  

# Git Push Handler (Code Mode Only)  
@app.route('/git_push', methods=['POST'])  
def git_push():  
    try:  
        if not request.is_json:  
            return jsonify({"error": "Invalid content type"}), 400  

        data = request.get_json()  
        required = ['code', 'filename']  
        if not all(k in data for k in required):  
            return jsonify({"error": "Missing parameters"}), 400  

        # Validate filename  
        if not data['filename'].endswith(('.py', '.yaml', '.json')):  
            return jsonify({"error": "Invalid file type"}), 400  

        with tempfile.TemporaryDirectory() as tmp_dir:  
            repo_url = f"https://{os.environ.get('GIT_TOKEN')}@github.com/{config['code']['git_repo']}.git"  
            
            # Clone repo  
            result = subprocess.run(  
                ['git', 'clone', '--depth', '1', repo_url, tmp_dir],  
                capture_output=True,  
                text=True  
            )  
            if result.returncode != 0:  
                raise subprocess.CalledProcessError(result.returncode, result.args, result.stderr)  

            # Write file  
            filepath = safe_join(tmp_dir, data['filename'])  
            with open(filepath, 'w', encoding='utf-8') as f:  
                f.write(data['code'])  

            # Commit and push  
            subprocess.run(['git', '-C', tmp_dir, 'config', 'user.email', 'ai-assistant@homeassistant'], check=True)  
            subprocess.run(['git', '-C', tmp_dir, 'config', 'user.name', 'AI Assistant'], check=True)  
            subprocess.run(['git', '-C', tmp_dir, 'add', '.'], check=True)  
            subprocess.run([  
                'git', '-C', tmp_dir,  
                'commit', '-m', f"Add {data['filename']} via AI Assistant"  
            ], check=True)  
            subprocess.run([  
                'git', '-C', tmp_dir,  
                'push', 'origin', config['code'].get('git_branch', 'main')  
            ], check=True)  

        return jsonify({"status": "success"})  

    except subprocess.CalledProcessError as e:  
        logging.error(f"Git error: {e.stderr}")  
        return jsonify({"error": f"Git operation failed: {e.stderr}"}), 500  
    except Exception as e:  
        logging.error(f"System error: {str(e)}", exc_info=True)  
        return jsonify({"error": "Internal server error"}), 500  

if __name__ == '__main__':  
    app.run(host='0.0.0.0', port=5000, threaded=True)  