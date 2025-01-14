from pydantic import BaseModel
from typing import Optional


class DeployRequest(BaseModel):
    repository_full_name: str
    branch: Optional[str] = None
