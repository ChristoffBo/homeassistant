import os
import requests
from flask import Flask, request, render_template, send_file
from datetime import datetime

app = Flask(__name__)

# Free-tier API endpoints (override in config.json if needed)
FREETIER_API = {
    "chatgpt": {
        "url": "https://api.openai.com/v1/chat/completions",
        "default_key": "free-tier-key-123",  # Replace with actual key
        "payload": {"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": ""}]}
    },
    "deepseek": {
        "url": "https://api.deepseek.com/v1/chat",
        "default_key": "free-tier-key-456",  # Replace with actual key
        "payload": {"prompt": ""}
    }
}

def call_ai(ai_choice, prompt, user_key):
    """Call free-tier or custom API."""
    api = FREETIER_API[ai_choice]
    key = user_key if user_key.strip() else api["default_key"]
    
    try:
        payload = api["payload"].copy()
        if ai_choice == "chatgpt":
            payload["messages"][0]["content"] = prompt
        else:
            payload["prompt"] = prompt

        response = requests.post(
            api["url"],
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"] if ai_choice == "chatgpt" else response.json()["output"]
    except Exception as e:
        raise Exception(f"API error: {str(e)}")

@app.route("/", methods=["GET", "POST"])
def chat():
    if request.method == "POST":
        try:
            user_input = request.form.get("user_input", "").strip()
            ai_choice = request.form.get("ai_choice", "chatgpt")
            action = request.form.get("action", "ask")

            if not user_input:
                return render_template("index.html", error="Prompt cannot be empty")

            # Load user keys from HA config
            with open('/data/options.json') as f:
                config = json.load(f)
                openai_key = config.get("openai_key", "").strip()
                deepseek_key = config.get("deepseek_key", "").strip()

            # Call AI (falls back to free-tier if keys are empty)
            ai_response = call_ai(ai_choice, user_input, openai_key if ai_choice == "chatgpt" else deepseek_key)

            # Handle save/download
            if action in ["save", "download"]:
                filename = f"output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                filepath = os.path.join(config.get("output_dir", "/share/chat_to_file"), filename)
                
                with open(filepath, "w") as f:
                    f.write(ai_response)

                if action == "download":
                    return send_file(filepath, as_attachment=True)
                return render_template("index.html", response=ai_response, saved_file=filename)

            return render_template("index.html", response=ai_response)

        except Exception as e:
            return render_template("index.html", error=str(e))

    return render_template("index.html")
