from fastapi import APIRouter, Depends, HTTPException, status
from dependencies import get_deploy_api_key
from models.deploy_request import DeployRequest
from utils import run_command, get_docker_compose_command
from config import REPO_DEPLOY_MAP
from notifications import Notifications
import os
import logging
import traceback
from fastapi.responses import JSONResponse

router = APIRouter()
logger = logging.getLogger(__name__)
notifier = Notifications(config_path="config.yaml")


@router.post("/deploy", summary="Manual Deployment Endpoint")
def manual_deploy(deploy_request: DeployRequest, api_key: str = Depends(get_deploy_api_key)):
    repo_full_name = deploy_request.repository_full_name
    branch = deploy_request.branch or REPO_DEPLOY_MAP.get(repo_full_name, {}).get("branch", "master")

    logger.info(f"Manual deployment triggered for repository: {repo_full_name}, branch: {branch}")

    if repo_full_name not in REPO_DEPLOY_MAP:
        logger.warning(f"Repository '{repo_full_name}' not configured for deployment")
        notifier.notify_deploy_event(repo_full_name, branch, "failed", "Repository not configured for deployment")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Repository not configured for deployment"
        )

    deploy_config = REPO_DEPLOY_MAP[repo_full_name]
    deploy_dir = deploy_config.get("deploy_dir")
    expected_branch = deploy_config.get("branch", "master")
    force_rebuild = deploy_config.get("force_rebuild", False)

    if not deploy_dir:
        logger.error(f"Deploy directory not specified for repository '{repo_full_name}'")
        notifier.notify_deploy_event(repo_full_name, branch, "failed", "Deploy directory not specified")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Deploy directory not specified for repository '{repo_full_name}'"
        )

    deploy_dir = os.path.abspath(deploy_dir)

    if branch != expected_branch:
        message = f"Deployment to branch '{branch}' ignored. Expected branch '{expected_branch}'."
        logger.info(message)
        notifier.notify_deploy_event(repo_full_name, branch, "ignored", message)
        return {"message": message}

    try:
        git_command = f"git pull origin {branch}"
        logger.info(f"Running command: {git_command} in {deploy_dir}")
        git_stdout, git_stderr = run_command(git_command, cwd=deploy_dir)

        if "Already up to date." in git_stdout:
            logger.info("No updates from git pull.")
            if force_rebuild:
                logger.info("'force_rebuild' is enabled. Proceeding to rebuild Docker services.")
                docker_up_command = get_docker_compose_command()
                logger.info(f"Running command: {docker_up_command} in {deploy_dir}")
                run_command(docker_up_command, cwd=deploy_dir)
            else:
                logger.info("'force_rebuild' is disabled. Skipping Docker rebuild.")
        else:
            logger.info("Updates pulled from git. Proceeding to rebuild Docker services.")
            docker_up_command = get_docker_compose_command()
            logger.info(f"Running command: {docker_up_command} in {deploy_dir}")
            run_command(docker_up_command, cwd=deploy_dir)

    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"Manual deployment failed: {str(e)}\n{error_trace}")
        notifier.notify_deploy_event(repo_full_name, branch, "failed", str(e))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": f"Manual deployment failed: {str(e)}"}
        )

    logger.info("Manual deployment successful")
    notifier.notify_deploy_event(repo_full_name, branch, "successful", "Deployment completed successfully.")
    return {"message": "Manual deployment successful"}