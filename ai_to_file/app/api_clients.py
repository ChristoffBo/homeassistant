import os
import requests
from typing import Optional

class ChatClient:
    def __init__(self):
        self.sessions = {}

    def get_response(self, model: str, message: str, conversation_id: Optional[str] = None):
        raise NotImplementedError

class FreeChatGPTClient(ChatClient):
    BASE_URL = "https://api.chatgpt.com/v1/free"
    
    def get_response(self, model: str, message: str, conversation_id: Optional[str] = None):
        try:
            response = requests.post(
                self.BASE_URL,
                json={
                    "message": message,
                    "model": model,
                    "conversation_id": conversation_id
                },
                timeout=30
            )
            response.raise_for_status()
            return response.json().get('response', "No response from ChatGPT")
        except Exception as e:
            return f"ChatGPT Error: {str(e)}"

class FreeDeepSeekClient(ChatClient):
    BASE_URL = "https://api.deepseek.com/v1/free"
    
    def get_response(self, model: str, message: str, conversation_id: Optional[str] = None):
        try:
            response = requests.post(
                self.BASE_URL,
                json={
                    "prompt": message,
                    "model": "deepseek-free"
                },
                timeout=30
            )
            response.raise_for_status()
            return response.json().get('output', "No response from DeepSeek")
        except Exception as e:
            return f"DeepSeek Error: {str(e)}"

class APIManager:
    def __init__(self):
        self.clients = {
            'chatgpt': FreeChatGPTClient(),
            'deepseek': FreeDeepSeekClient()
        }
        self.custom_apis = {}
    
    def get_client(self, model: str):
        if model in self.custom_apis:
            # In a real implementation, return custom client
            pass
        return self.clients.get(model, self.clients['chatgpt'])
