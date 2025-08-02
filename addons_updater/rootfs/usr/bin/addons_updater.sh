#!/usr/bin/env python3
import os
import json
import logging
import requests
import semver
import time
import re
from datetime import datetime
from git import Repo, GitCommandError

# Configure logging
logger = logging.getLogger(__name__)

class AddonUpdater:
    def __init__(self):
        self.config = self.load_config()
        self.repo_path = "/data/repo"
        self.token = os.environ.get("SUPERVISOR_TOKEN", "")
        self.headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        self.registries = ["dockerhub", "ghcr", "linuxserver"]
        self.repo = None
        self.start_time = time.time()
        self.dry_run = self.config.get("dry_run", False)
        
        # Configure logging
        log_level = logging.DEBUG if self.config.get("verbose", False) else logging.INFO
        logging.basicConfig(level=log_level)
        logger.info("Addon Updater initialized")

    def load_config(self):
        try:
            with open("/data/options.json") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading config: {str(e)}")
            return {}

    def setup_git(self):
        try:
            repo_url = f"https://github.com/{self.config['repository']}.git"
            logger.info(f"Using repository URL: {repo_url}")
            
            if os.path.exists(self.repo_path):
                self.repo = Repo(self.repo_path)
                self.repo.remotes.origin.pull()
            else:
                self.repo = Repo.clone_from(repo_url, self.repo_path, branch="main")
            
            with self.repo.config_writer() as config:
                config.set_value("user", "name", self.config.get("gituser", "Addon Updater"))
                config.set_value("user", "email", self.config.get("gitmail", "updater@home-assistant"))
            
            logger.info("Git repository initialized")
            return True
        except GitCommandError as e:
            logger.error(f"Git command error: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Git setup error: {str(e)}")
            return False

    def get_latest_tag(self, image):
        latest_version = None
        
        for registry in self.registries:
            try:
                if registry == "dockerhub":
                    url = f"https://registry.hub.docker.com/v2/repositories/{image}/tags"
                    response = requests.get(url, timeout=15)
                    tags = [tag['name'] for tag in response.json().get('results', [])]
                elif registry == "ghcr":
                    url = f"https://ghcr.io/v2/{image}/tags/list"
                    response = requests.get(url, timeout=15)
                    tags = response.json().get('tags', [])
                elif registry == "linuxserver":
                    url = f"https://registry.hub.docker.com/v2/repositories/linuxserver/{image}/tags"
                    response = requests.get(url, timeout=15)
                    tags = [tag['name'] for tag in response.json().get('results', [])]
                
                for tag in tags:
                    try:
                        clean_tag = re.sub(r'^v', '', tag).split('-')[0]
                        if semver.VersionInfo.isvalid(clean_tag):
                            ver = semver.VersionInfo.parse(clean_tag)
                            if not latest_version or ver > latest_version:
                                latest_version = ver
                    except ValueError:
                        continue
            except Exception as e:
                logger.error(f"Registry {registry} error: {str(e)}")
        
        return str(latest_version) if latest_version else None

    def get_current_version(self, addon_dir):
        versions = {}
        for file in ["config.json", "build.json", "update.json"]:
            path = os.path.join(addon_dir, file)
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        data = json.load(f)
                        version = data.get("version") or data.get("tag")
                        if version: versions[file] = version
                except Exception as e:
                    logger.error(f"Error reading {path}: {str(e)}")
        return versions

    def update_file_version(self, path, new_version):
        try:
            with open(path, "r+") as f:
                data = json.load(f)
                filename = os.path.basename(path)
                if filename == "update.json":
                    if "version" in data: data["version"] = new_version
                    elif "tag" in data: data["tag"] = new_version
                elif filename == "build.json":
                    if "version" in data: data["version"] = new_version
                    elif "tag" in data: data["tag"] = new_version
                else:  # config.json
                    if "version" in data: data["version"] = new_version
                f.seek(0)
                json.dump(data, f, indent=2)
                f.truncate()
            return True
        except Exception as e:
            logger.error(f"Error updating {path}: {str(e)}")
            return False

    def update_changelog(self, addon_dir, addon_name, old_version, new_version):
        changelog_path = os.path.join(addon_dir, "CHANGELOG.md")
        today = datetime.today().strftime('%Y-%m-%d')
        entry = f"## {new_version} - {today}\n- Updated from {old_version} to {new_version}\n- [Docker Image](https://hub.docker.com/r/{addon_name})\n\n"
        
        try:
            if os.path.exists(changelog_path):
                with open(changelog_path, "r+") as f:
                    content = f.read()
                    f.seek(0)
                    f.write(entry + content)
            else:
                with open(changelog_path, "w") as f:
                    f.write(f"# {addon_name} Changelog\n\n{entry}")
            return True
        except Exception as e:
            logger.error(f"Error updating changelog: {str(e)}")
            return False

    def process_addons(self):
        if not self.repo: return [], []
        addons_path = os.path.join(self.repo_path, "addons")
        if not os.path.exists(addons_path):
            logger.error("Addons directory not found")
            return [], []
            
        processed = []; updated = []
        
        for addon_slug in os.listdir(addons_path):
            addon_dir = os.path.join(addons_path, addon_slug)
            if not os.path.isdir(addon_dir): continue
            
            addon_data = {"name": addon_slug}
            try:
                # Get current versions
                current_versions = self.get_current_version(addon_dir)
                if not current_versions:
                    addon_data["status"] = "no_versions"
                    processed.append(addon_data)
                    continue
                
                current_version = list(current_versions.values())[0]
                addon_data["current_version"] = current_version
                
                # Get image name
                config_path = os.path.join(addon_dir, "config.json")
                if not os.path.exists(config_path):
                    addon_data["status"] = "missing_config"
                    processed.append(addon_data)
                    continue
                
                with open(config_path) as f:
                    image = json.load(f).get("image", "").split("/")[-1]
                if not image:
                    addon_data["status"] = "missing_image"
                    processed.append(addon_data)
                    continue
                
                # Get latest version
                latest_version = self.get_latest_tag(image)
                if not latest_version:
                    addon_data["status"] = "no_registry_version"
                    processed.append(addon_data)
                    continue
                
                addon_data["latest_version"] = latest_version
                
                # Compare versions
                clean_current = re.sub(r'^v', '', current_version).split('-')[0]
                clean_latest = re.sub(r'^v', '', latest_version).split('-')[0]
                
                if semver.compare(clean_latest, clean_current) <= 0:
                    addon_data["status"] = "up_to_date"
                    processed.append(addon_data)
                    continue
                
                # Update files
                files_updated = 0
                for file in current_versions.keys():
                    if self.update_file_version(os.path.join(addon_dir, file), latest_version):
                        files_updated += 1
                        self.repo.git.add(os.path.join(addon_dir, file))
                
                if files_updated == 0:
                    addon_data["status"] = "update_failed"
                    processed.append(addon_data)
                    continue
                
                # Update changelog
                if self.update_changelog(addon_dir, addon_slug, current_version, latest_version):
                    self.repo.git.add(os.path.join(addon_dir, "CHANGELOG.md"))
                
                # Commit changes
                if not self.dry_run:
                    self.repo.index.commit(f"Update {addon_slug} to {latest_version}")
                
                addon_data.update({
                    "status": "updated",
                    "old_version": current_version,
                    "new_version": latest_version
                })
                updated.append(addon_data)
                processed.append(addon_data)
                
                logger.info(f"Updated {addon_slug} from {current_version} to {latest_version}")
                
            except Exception as e:
                addon_data["status"] = "error"
                addon_data["error"] = str(e)
                processed.append(addon_data)
                logger.error(f"Error processing {addon_slug}: {str(e)}")
        
        return processed, updated

    def push_changes(self):
        if self.dry_run or not self.repo: return False
        try:
            self.repo.remotes.origin.push()
            logger.info("Changes pushed to remote")
            return True
        except GitCommandError as e:
            logger.error(f"Git push failed: {str(e)}")
            return False

    def trigger_reload(self):
        if self.dry_run or not self.token: return False
        try:
            requests.post("http://supervisor/store/reload", headers=self.headers, timeout=10)
            logger.info("Triggered store reload")
            return True
        except Exception as e:
            logger.error(f"Error triggering reload: {str(e)}")
            return False

    def send_notification(self, processed, updated):
        if not self.config.get("enable_notifications", False): return
        
        gotify_url = self.config.get("gotify_url", "").strip()
        gotify_token = self.config.get("gotify_token", "").strip()
        if not gotify_url or not gotify_token: return
        
        # Build notification message
        message = "### 🚀 Addon Update Report\n\n"
        message += f"**Total Addons Processed:** {len(processed)}\n"
        message += f"**Addons Updated:** {len(updated)}\n\n"
        
        if updated:
            message += "#### 🔄 Updated Addons:\n"
            for addon in updated:
                message += f"- **{addon['name']}**: {addon['old_version']} → {addon['new_version']}\n"
            message += "\n"
        
        message += "#### 🔍 Detailed Status:\n"
        for addon in processed:
            status_icon = "🟢" if addon["status"] == "updated" else "🔵" if addon["status"] == "up_to_date" else "🔴"
            version_info = f"{addon.get('current_version', '')}"
            if "latest_version" in addon: version_info += f" → {addon['latest_version']}"
            message += f"- {status_icon} **{addon['name']}**: {addon['status'].replace('_', ' ').title()} - {version_info}\n"
        
        try:
            requests.post(
                f"{gotify_url}/message?token={gotify_token}",
                json={
                    "title": "Home Assistant Addon Updates",
                    "message": message,
                    "priority": 5,
                    "extras": {"client::display": {"contentType": "text/markdown"}}
                }
            )
            logger.info("Sent Gotify notification")
        except Exception as e:
            logger.error(f"Error sending notification: {str(e)}")

    def run(self):
        try:
            if not self.setup_git(): return
            processed, updated = self.process_addons()
            if updated: 
                self.push_changes()
                self.trigger_reload()
            self.send_notification(processed, updated)
            logger.info("Update process completed")
        except Exception as e:
            logger.error(f"Critical error: {str(e)}")

if __name__ == "__main__":
    AddonUpdater().run()
