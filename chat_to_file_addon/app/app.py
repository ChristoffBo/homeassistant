import os
import logging
from datetime import datetime
from flask import Flask, request, render_template, send_file

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    filename='/app/logs/chat_to_file.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Configuration
OUTPUT_DIR = "/share/chat_to_file"
os.makedirs(OUTPUT_DIR, exist_ok=True)

@app.route("/", methods=["GET", "POST"])
def chat():
    if request.method == "POST":
        try:
            user_input = request.form.get("user_input", "").strip()
            action = request.form.get("action", "ask")
            
            if not user_input:
                return render_template("index.html", error="Prompt cannot be empty")

            # Simulated AI response (replace with actual API call)
            ai_response = f"AI Response to: {user_input}\nGenerated at {datetime.now()}"
            
            if action in ["save", "download"]:
                filename = f"output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
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
            return render_template("index.html", error=str(e))
    
    return render_template("index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)