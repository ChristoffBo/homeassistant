import json
import os
from typing import Dict, Any

CONFIG_FILE = '/data/options.json'

class ConfigManager:
    def __init__(self):
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {
            "port": 5000,
            "default_model": "chatgpt",
            "apis": {
                "chatgpt": {
                    "type": "free",
                    "api_key": ""
                },
                "deepseek": {
                    "type": "free",
                    "api_key": ""
                }
            }
        }
    
    def get_config(self) -> Dict[str, Any]:
        return self.config
    
    def get_api_config(self, model: str) -> Dict[str, str]:
        return self.config.get('apis', {}).get(model, {"type": "free", "api_key": ""})
    
    def save_config(self, new_config: Dict[str, Any]):
        self.config = new_config
        with open(CONFIG_FILE, 'w') as f:
            json.dump(new_config, f)
