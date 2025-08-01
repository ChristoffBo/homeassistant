from flask import Flask, request, jsonify, send_from_directory
import subprocess
import tempfile
import os
import logging
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Chat message history
chat_history = []

@app.route('/')
def serve_ui():
    return send_from_directory('templates', 'index.html')

# Chat API endpoints
@app.route('/api/chat/send', methods=['POST'])
def chat_send():
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        
        if not message:
            return jsonify({"error": "Message cannot be empty"}), 400
            
        # Add to history (limit to 20 messages)
        chat_history.append({
            "timestamp": datetime.now().isoformat(),
            "user": message,
            "ai": f"AI response to: {message}"
        })
        
        if len(chat_history) > 20:
            chat_history.pop(0)
            
        return jsonify({"status": "success", "response": chat_history[-1]['ai']})
        
    except Exception as e:
        logging.error(f"Chat error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Git push endpoint
@app.route('/api/code/push', methods=['POST'])
def git_push():
    try:
        data = request.get_json()
        required = ['code', 'filename', 'commit_message']
        if not all(k in data for k in required):
            return jsonify({"error": "Missing required fields"}), 400
            
        # Validate filename
        filename = secure_filename(data['filename'])
        if not filename:
            return jsonify({"error": "Invalid filename"}), 400
            
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Clone repo
            repo_url = f"https://github.com/{config['code']['git_repo']}.git"
            subprocess.run([
                'git', 'clone',
                '--depth', '1',
                repo_url,
                tmp_dir
            ], check=True, capture_output=True)
            
            # Write file
            filepath = os.path.join(tmp_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(data['code'])
                
            # Git operations
            subprocess.run(['git', '-C', tmp_dir, 'config', 'user.name', 'AI Assistant'], check=True)
            subprocess.run(['git', '-C', tmp_dir, 'config', 'user.email', 'ai-assistant@homeassistant'], check=True)
            subprocess.run(['git', '-C', tmp_dir, 'add', '.'], check=True)
            subprocess.run([
                'git', '-C', tmp_dir,
                'commit', '-m', data['commit_message']
            ], check=True)
            subprocess.run([
                'git', '-C', tmp_dir,
                'push', 'origin', config['code'].get('git_branch', 'main')
            ], check=True)
            
        return jsonify({"status": "success"})
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Git error: {e.stderr.decode().strip()}"
        logging.error(error_msg)
        return jsonify({"error": error_msg}), 500
    except Exception as e:
        logging.error(f"Push error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Teaching material generation
@app.route('/api/teach/generate', methods=['POST'])
def generate_lesson():
    try:
        data = request.get_json()
        lesson_type = data.get('type', 'grammar')
        topic = data.get('topic', '').strip()
        
        if not topic:
            return jsonify({"error": "Topic cannot be empty"}), 400
            
        # Generate lesson content
        lesson = {
            "title": f"{lesson_type.capitalize()} Lesson: {topic}",
            "content": [
                {"type": "warmup", "text": f"Discuss: What do you know about {topic}?"},
                {"type": "explanation", "text": f"Explanation of {topic}"},
                {"type": "practice", "text": f"Practice exercises for {topic}"}
            ],
            "created_at": datetime.now().isoformat()
        }
        
        return jsonify(lesson)
        
    except Exception as e:
        logging.error(f"Lesson error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)