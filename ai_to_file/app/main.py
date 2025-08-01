from flask import Flask, render_template, request, jsonify, send_file
from .api_clients import APIManager
from .config_manager import ConfigManager
import os
import time
from io import BytesIO

app = Flask(__name__, template_folder='templates', static_folder='static')
config_manager = ConfigManager()
api_manager = APIManager()

MODELS = {
    'chatgpt': 'OpenAI ChatGPT',
    'deepseek': 'DeepSeek'
}

@app.route('/')
def index():
    config = config_manager.get_config()
    return render_template(
        'index.html',
        models=MODELS,
        current_model=config.get('default_model', 'chatgpt'),
        api_config=config.get('apis', {})
    )

@app.route('/api/send_message', methods=['POST'])
def send_message():
    data = request.json
    message = data.get('message', '')
    model = data.get('model', 'chatgpt')
    
    client = api_manager.get_client(model)
    response = client.get_response(model, message)
    
    return jsonify({
        'response': response,
        'model': model,
        'timestamp': int(time.time())
    })

@app.route('/api/update_config', methods=['POST'])
def update_config():
    try:
        data = request.json
        new_config = {
            "port": data.get('port', 5000),
            "default_model": data.get('default_model', 'chatgpt'),
            "apis": {
                "chatgpt": {
                    "type": data.get('chatgpt_api_type', 'free'),
                    "api_key": data.get('chatgpt_api_key', '')
                },
                "deepseek": {
                    "type": data.get('deepseek_api_type', 'free'),
                    "api_key": data.get('deepseek_api_key', '')
                }
            }
        }
        config_manager.save_config(new_config)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/copy_to_clipboard', methods=['POST'])
def copy_to_clipboard():
    data = request.json
    content = data.get('content', '')
    return jsonify({'status': 'success'})

@app.route('/api/download_file', methods=['POST'])
def download_file():
    data = request.json
    content = data.get('content', '')
    filename = data.get('filename', 'ai_export.txt')
    
    file = BytesIO(content.encode('utf-8'))
    file.seek(0)
    
    return send_file(
        file,
        as_attachment=True,
        download_name=filename,
        mimetype='text/plain'
    )

@app.route('/api/save_to_ha', methods=['POST'])
def save_to_ha():
    data = request.json
    content = data.get('content', '')
    filename = data.get('filename', 'ai_export.txt')
    
    try:
        save_path = os.path.join('/config/www', filename)
        with open(save_path, 'w') as f:
            f.write(content)
        return jsonify({
            'status': 'success',
            'path': save_path,
            'saved_at': int(time.time())
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    config = config_manager.get_config()
    app.run(host='0.0.0.0', port=config.get('port', 5000))
