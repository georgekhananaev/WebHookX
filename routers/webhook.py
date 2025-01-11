from fastapi import APIRouter, Request, Header, HTTPException, status
import logging
from models.github_webhook import GitHubWebhook
from utils import verify_signature, run_command, get_docker_compose_command
from config import REPO_DEPLOY_MAP
from notifications import Notifications
import os
import traceback

router = APIRouter()
logger = logging.getLogger(__name__)
notifier = Notifications(config_path="config.yaml")


@router.post("/webhook", summary="GitHub Webhook Endpoint")
async def handle_webhook(request: Request, x_hub_signature_256: str = Header(None)):
    logger.info("Webhook endpoint was called.")
    body = await request.body()
    logger.debug(f"Raw request body: {body}")

    if not verify_signature(body, x_hub_signature_256):
        logger.warning("Invalid signature.")
        notifier.notify_deploy_event("unknown", "unknown", "failed", "Invalid signature.")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")

    try:
        payload = await request.json()
        webhook = GitHubWebhook(**payload)
        logger.debug(f"Parsed webhook payload: {payload}")
    except Exception as e:
        logger.error(f"Invalid payload: {e}")
        notifier.notify_deploy_event("unknown", "unknown", "failed", "Invalid payload.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")

    repo_full_name = webhook.repository.get("full_name")
    logger.info(f"Received webhook for repository: {repo_full_name}")

    if repo_full_name not in REPO_DEPLOY_MAP:
        logger.warning(f"Repository '{repo_full_name}' not configured for deployment")
        notifier.notify_deploy_event(repo_full_name, "unknown", "failed", "Repository not configured for deployment")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Repository not configured for deployment"
        )

    deploy_config = REPO_DEPLOY_MAP[repo_full_name]
    deploy_dir = deploy_config.get("deploy_dir")
    branch = deploy_config.get("branch", "master")
    force_rebuild = deploy_config.get("force_rebuild", False)

    if not deploy_dir:
        logger.error(f"Deploy directory not specified for repository '{repo_full_name}'")
        notifier.notify_deploy_event(repo_full_name, branch, "failed", "Deploy directory not specified")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Deploy directory not specified for repository '{repo_full_name}'"
        )

    deploy_dir = os.path.abspath(deploy_dir)
    push_branch = webhook.ref.split('/')[-1]
    logger.info(f"Pushed to branch: {push_branch}")

    if push_branch != branch:
        message = f"Push to branch '{push_branch}' ignored. Expected branch '{branch}'."
        logger.info(message)
        notifier.notify_deploy_event(repo_full_name, push_branch, "ignored", message)
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
        logger.error(f"Deployment failed: {str(e)}\n{error_trace}")
        notifier.notify_deploy_event(repo_full_name, branch, "failed", str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    logger.info("Deployment successful")
    notifier.notify_deploy_event(repo_full_name, branch, "successful", "Deployment completed successfully.")
    return {"message": "Deployment successful"}