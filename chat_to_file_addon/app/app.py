import os
import json
import logging
import requests
from flask import Flask, request, render_template, send_file
from datetime import datetime

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    filename='/app/logs/chat_to_file.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Load HA config
try:
    with open('/data/options.json') as f:
        config = json.load(f)
        OUTPUT_DIR = config.get('output_dir', '/share/chat_to_file')
        OPENAI_KEY = config.get('openai_key', '')
        DEEPSEEK_KEY = config.get('deepseek_key', '')
    os.makedirs(OUTPUT_DIR, exist_ok=True)
except Exception as e:
    logging.error(f"Config error: {e}")
    raise

def call_ai(ai_choice, prompt):
    """Call ChatGPT or DeepSeek API."""
    try:
        if ai_choice == "chatgpt":
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {OPENAI_KEY}"}
            data = {
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": prompt}]
            }
        else:
            url = "https://api.deepseek.com/v1/chat"
            headers = {"Authorization": f"Bearer {DEEPSEEK_KEY}"}
            data = {"prompt": prompt}

        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        
        if ai_choice == "chatgpt":
            return response.json()['choices'][0]['message']['content']
        return response.json()['output']
    except Exception as e:
        logging.error(f"API call failed: {e}")
        return f"API Error: {str(e)}"

@app.route("/", methods=["GET", "POST"])
def chat():
    if request.method == "POST":
        try:
            user_input = request.form.get("user_input", "").strip()
            ai_choice = request.form.get("ai_choice", "chatgpt")
            action = request.form.get("action", "ask")

            if not user_input:
                return render_template("index.html", error="Prompt cannot be empty")

            # Get AI response
            ai_response = call_ai(ai_choice, user_input)

            # Handle save/download
            if action in ["save", "download"]:
                custom_name = request.form.get("filename", "").strip() or "output"
                filename = f"{custom_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                filepath = os.path.join(OUTPUT_DIR, filename)

                with open(filepath, "w") as f:
                    f.write(ai_response)

                if action == "download":
                    return send_file(filepath, as_attachment=True)
                return render_template("index.html", 
                    response=ai_response, 
                    saved_file=filename)

            return render_template("index.html", response=ai_response)

        except Exception as e:
            logging.error(f"Error: {e}")
            return render_template("index.html", error=str(e))

    return render_template("index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)