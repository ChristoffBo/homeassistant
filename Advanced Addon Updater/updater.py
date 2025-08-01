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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class AdvancedAddonUpdater:
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
        """Send notification via Home Assistant API"""
        if not self.config.get('notify', False):
            return
            
        try:
            token = os.environ.get('SUPERVISOR_TOKEN')
            if not token:
                logger.warning("No supervisor token available")
                return

            title = "Addon Update: Success" if success else "Addon Update: Failed"
            data = {
                "title": title,
                "message": message,
                "notification_id": "addon_updater"
            }

            response = requests.post(
                'http://supervisor/notifications',
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                },
                json=data,
                timeout=10
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Notification failed: {e}")

    def _check_gitea_health(self):
        """Verify Gitea instance is reachable"""
        if not self.config.get('gitea', {}).get('health_check', False):
            return True
            
        gitea_url = self.config['gitea'].get('url', '')
        if not gitea_url:
            return True

        try:
            response = requests.get(
                f"{gitea_url.rstrip('/')}/api/v1/health",
                timeout=15
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Gitea health check failed: {e}")
            return False

    def _get_last_version(self, repo_url):
        """Check for updates using lastversion"""
        try:
            result = subprocess.run(
                ['lastversion', '--version', repo_url],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"Version check failed: {e.stderr}")
            return None

    def _prepare_git_url(self, repo_url):
        """Add authentication for Gitea repos"""
        gitea_url = self.config.get('gitea', {}).get('url', '')
        if not gitea_url or urlparse(repo_url).netloc != urlparse(gitea_url).netloc:
            return repo_url

        token = self.config['gitea'].get('token', '')
        if not token:
            return repo_url

        parsed = urlparse(repo_url)
        return f"{parsed.scheme}://{token}@{parsed.netloc}{parsed.path}"

    def _update_addon(self, addon_name, addon_config):
        """Process individual addon update"""
        repo_url = addon_config['url']
        branch = addon_config.get('branch', 'main')
        addon_path = self.addons_dir / addon_name

        # Version check if enabled
        if addon_config.get('version_check', False):
            latest_version = self._get_last_version(repo_url)
            if latest_version:
                logger.info(f"Latest version for {addon_name}: {latest_version}")

        # Prepare authenticated URL if needed
        auth_url = self._prepare_git_url(repo_url)

        try:
            if addon_path.exists():
                logger.info(f"Updating {addon_name} (branch: {branch})")
                subprocess.run(['git', '-C', str(addon_path), 'fetch'], check=True)
                subprocess.run(['git', '-C', str(addon_path), 'checkout', branch], check=True)
                subprocess.run(['git', '-C', str(addon_path), 'pull', 'origin', branch], check=True)
            else:
                logger.info(f"Cloning {addon_name} (branch: {branch})")
                subprocess.run([
                    'git', 'clone', '-b', branch, auth_url, str(addon_path)
                ], check=True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Update failed for {addon_name}: {e.stderr}")
            return False

    def run(self):
        """Main execution flow"""
        if not self._check_gitea_health():
            self._send_notification("Gitea health check failed", False)
            return False

        success = True
        for addon_name, addon_config in self.config.get('addons', {}).items():
            if not self._update_addon(addon_name, addon_config):
                success = False

        message = "All addons updated successfully" if success else "Some addons failed to update"
        self._send_notification(message, success)
        return success

if __name__ == '__main__':
    updater = AdvancedAddonUpdater()
    updater.run()
