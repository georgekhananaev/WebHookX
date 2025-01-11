from pydantic import BaseModel, Field
from typing import Optional


class DeployRequest(BaseModel):
    repository_full_name: str = Field(..., example="georgekhananaev/moonholidays-frontend")
    branch: Optional[str] = Field(None, example="master")
