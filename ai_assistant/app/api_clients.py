import requests
import os

class APIManager:
    def __init__(self):
        self.models = {
            "chatgpt-free": {
                "endpoint": "https://api.openai.com/v1/chat/completions",
                "headers": {"Authorization": f"Bearer {os.getenv('CHATGPT_KEY')}"},
                "payload": {"model": "gpt-3.5-turbo"}
            },
            "chatgpt-paid": {
                "endpoint": "https://api.openai.com/v1/chat/completions",
                "headers": {"Authorization": f"Bearer {os.getenv('CHATGPT_KEY')}"},
                "payload": {"model": "gpt-4"}
            },
            "deepseek-free": {
                "endpoint": "https://api.deepseek.com/v1/chat/completions",
                "headers": {"Authorization": f"Bearer {os.getenv('DEEPSEEK_KEY')}"},
                "payload": {"model": "deepseek-chat"}
            },
            "deepseek-paid": {
                "endpoint": "https://api.deepseek.com/v1/chat/completions",
                "headers": {"Authorization": f"Bearer {os.getenv('DEEPSEEK_KEY')}"},
                "payload": {"model": "deepseek-coder"}
            }
        }

    def get_response(self, model, prompt):
        config = self.models[model]
        payload = {
            **config['payload'],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }
        
        response = requests.post(
            config['endpoint'],
            headers=config['headers'],
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
