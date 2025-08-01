#!/usr/bin/env python3
import os
import json
import logging
import subprocess
import requests
from pathlib import Path
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AddonUpdater:
    def __init__(self):
        self.config = self._load_config()
        self.addons_dir = Path("/addons")
        self.addons_dir.mkdir(exist_ok=True)
        
    def _load_config(self):
        """Load configuration from options.json"""
        try:
            with open('/data/options.json') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Config load error: {e}")
            return {}

    def _send_notification(self, message, success=True):
        """Send notification via Gotify or Supervisor"""
        if not self.config.get('notify', False):
            return

        # Try Gotify first if configured
        if self._send_gotify(message, success):
            return
            
        # Fallback to Supervisor notifications
        self._send_supervisor(message, success)

    def _send_gotify(self, message, success):
        """Send Gotify notification"""
        cfg = self.config.get('gotify', {})
        if not cfg.get('url') or not cfg.get('token'):
            return False
            
        try:
            resp = requests.post(
                f"{cfg['url'].rstrip('/')}/message",
                headers={'X-Gotify-Key': cfg['token']},
                json={
                    "title": "Addon Update: " + ("Success" if success else "Failed"),
                    "message": message,
                    "priority": 5 if not success else 2
                },
                timeout=10
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Gotify notification failed: {e}")
            return False

    def _send_supervisor(self, message, success):
        """Send Supervisor notification"""
        try:
            token = os.environ.get('SUPERVISOR_TOKEN')
            if not token:
                return

            requests.post(
                'http://supervisor/notifications',
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                },
                json={
                    "title": "Addon Update",
                    "message": message,
                    "notification_id": "addon_updater"
                },
                timeout=10
            )
        except Exception as e:
            logger.error(f"Supervisor notification failed: {e}")

    def _check_gitea(self):
        """Check Gitea instance health"""
        gitea = self.config.get('gitea', {})
        if not gitea.get('health_check', False):
            return True
            
        try:
            resp = requests.get(
                f"{gitea['url'].rstrip('/')}/api/v1/health",
                timeout=15
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Gitea health check failed: {e}")
            return False

    def _get_version(self, repo_url):
        """Get latest version using lastversion"""
        try:
            result = subprocess.run(
                ['lastversion', '--version', repo_url],
                check=True,
                capture_output=True,
                text=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"Version check failed: {e.stderr}")
            return None

    def _update_addon(self, addon):
        """Update single addon"""
        path = self.addons_dir / addon['slug']
        branch = addon.get('branch', 'main')
        
        # Version check
        if addon.get('version_check', False):
            if version := self._get_version(addon['url']):
                logger.info(f"Latest version for {addon['slug']}: {version}")

        # Git operations
        try:
            if path.exists():
                cmds = [
                    ['git', '-C', str(path), 'fetch'],
                    ['git', '-C', str(path), 'checkout', branch],
                    ['git', '-C', str(path), 'pull', 'origin', branch]
            else:
                cmds = [['git', 'clone', '-b', branch, addon['url'], str(path)]]
                
            for cmd in cmds:
                subprocess.run(cmd, check=True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Update failed for {addon['slug']}: {e.stderr}")
            return False

    def run(self):
        """Main execution flow"""
        if not self._check_gitea():
            self._send_notification("Gitea health check failed", False)
            return False

        results = [self._update_addon(a) for a in self.config.get('addons', [])]
        success = all(results)
        
        msg = ("All addons updated" if success 
              else f"Failed on {results.count(False)}/{len(results)} addons")
        self._send_notification(msg, success)
        return success

if __name__ == '__main__':
    AddonUpdater().run()
