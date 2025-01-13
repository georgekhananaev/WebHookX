# deploy.py

from fastapi import APIRouter, Depends, HTTPException, status
from dependencies import get_deploy_api_key
from models.deploy_request import DeployRequest
from config import REPO_DEPLOY_MAP
from deploy_chain import deploy_chain
import logging
from fastapi.responses import JSONResponse

from notifications import Notifications

router = APIRouter()
logger = logging.getLogger(__name__)
notifier = Notifications(config_path="config.yaml")


@router.post("/deploy", summary="Manual Deployment Endpoint")
def manual_deploy(deploy_request: DeployRequest, api_key: str = Depends(get_deploy_api_key)):
    """
    Manually trigger the deployment chain for a given repository and branch.
    """
    repo_full_name = deploy_request.repository_full_name
    requested_branch = deploy_request.branch

    logger.info(f"Manual deployment triggered for repo: {repo_full_name}, branch: {requested_branch}")

    if repo_full_name not in REPO_DEPLOY_MAP:
        message = f"Repository '{repo_full_name}' not configured for deployment."
        notifier.notify_deploy_event(repo_full_name, requested_branch or "?", "failed", message)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )

    sub_config = REPO_DEPLOY_MAP[repo_full_name]
    # We pass the branch to the chain. If server config has a different branch, it might skip or ignore.
    try:
        deploy_chain(repo_full_name, requested_branch, sub_config, notifier)
        notifier.notify_deploy_event(repo_full_name, requested_branch or "?", "successful", "All servers deployed.")
        return {"message": f"Deployment chain completed for {repo_full_name}, branch: {requested_branch}"}
    except Exception as e:
        logger.error(f"Manual deployment chain failed: {str(e)}")
        notifier.notify_deploy_event(repo_full_name, requested_branch or "?", "failed", str(e))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": str(e)}
        )