from pydantic import BaseModel
from typing import Dict


class GitHubWebhook(BaseModel):
    ref: str
    repository: Dict[str, str]
    # Optionally add pusher, commits, etc. if needed
