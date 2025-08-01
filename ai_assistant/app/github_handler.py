from github import Github
import base64
import os

class GitHubHandler:
    def __init__(self):
        token = os.getenv('GITHUB_TOKEN')
        self.client = Github(token) if token else None

    def create_file(self, repo, path, content):
        if not self.client:
            raise Exception("GitHub token not configured")
        
        repo = self.client.get_repo(repo)
        repo.create_file(
            path=path,
            message=f"Add {path} via AI Assistant",
            content=content,
            branch="main"
        )
        return f"https://github.com/{repo}/blob/main/{path}"
