from pydantic import BaseModel
from typing import Dict, Any


class GitHubWebhook(BaseModel):
    ref: str
    repository: Dict[str, Any]
