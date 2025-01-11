# routers/tests.py

from fastapi import APIRouter, Depends, HTTPException, status
from dependencies import get_list_files_api_key
from config import REPO_DEPLOY_MAP
from utils import run_command
import os
import traceback
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/test-command", summary="Test Command Execution")
def test_command(api_key: str = Depends(get_list_files_api_key)):
    logger.info("Test command endpoint was called.")
    try:
        git_command = "git --version"
        git_stdout, git_stderr = run_command(git_command, cwd=os.getcwd())
        git_version = git_stdout if git_stdout else "No output"

        docker_command = "docker-compose --version"
        docker_stdout, docker_stderr = run_command(docker_command, cwd=os.getcwd())
        docker_version = docker_stdout if docker_stdout else "No output"

        return {
            "git_version": git_version,
            "docker_compose_version": docker_version
        }

    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"Test command failed: {str(e)}\n{error_trace}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/list-files", summary="List Files in Deployment Directory")
def list_files(repository_full_name: str, branch: str = None, api_key: str = Depends(get_list_files_api_key)):
    logger.info(f"Listing files for repository: {repository_full_name}, branch: {branch or 'default'}")

    if repository_full_name not in REPO_DEPLOY_MAP:
        logger.warning(f"Repository '{repository_full_name}' not found in configuration")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Repository not found in configuration"
        )

    deploy_config = REPO_DEPLOY_MAP[repository_full_name]
    deploy_dir = deploy_config.get("deploy_dir")
    expected_branch = deploy_config.get("branch", "master")

    if not deploy_dir:
        logger.error(f"Deploy directory not specified for repository '{repository_full_name}'")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Deploy directory not specified for repository '{repository_full_name}'"
        )

    if branch and branch != expected_branch:
        logger.info(f"Listing files for branch '{branch}' ignored (expected '{expected_branch}')")
        return {"message": f"Listing files for branch '{branch}' ignored. Expected branch '{expected_branch}'."}

    try:
        if not os.path.isdir(deploy_dir):
            logger.error(f"Deploy directory '{deploy_dir}' does not exist.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Deploy directory '{deploy_dir}' does not exist."
            )

        files = os.listdir(deploy_dir)
        logger.debug(f"Files in '{deploy_dir}': {files}")
        return {"files": files}

    except Exception as e:
        logger.error(f"Failed to list files: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
