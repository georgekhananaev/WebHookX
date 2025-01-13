import os
import logging
import traceback

from fastapi import APIRouter, Request, Header, HTTPException, status

from models.github_webhook import GitHubWebhook  # Adjust import as needed
from utils import verify_signature, run_command, get_docker_compose_command  # Adjust imports as needed
from config import REPO_DEPLOY_MAP
from notifications import Notifications

router = APIRouter()
logger = logging.getLogger(__name__)
notifier = Notifications(config_path="config.yaml")


@router.post("/webhook", summary="GitHub Webhook Endpoint")
async def handle_webhook(
    request: Request,
    x_hub_signature_256: str = Header(None),
    x_github_event: str = Header(None)
):
    logger.info("Webhook endpoint was called.")

    # Read the raw request body and log it for debugging
    body = await request.body()
    logger.debug(f"Raw request body: {body}")

    # Ensure the signature header is provided
    if not x_hub_signature_256:
        logger.error("Missing X-Hub-Signature-256 header.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing signature header"
        )

    # Verify the signature using the shared secret from the config
    if not verify_signature(body, x_hub_signature_256):
        logger.warning("Invalid signature.")
        notifier.notify_deploy_event("unknown", "unknown", "failed", "Invalid signature.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature"
        )

    # Decode the JSON payload
    try:
        payload = await request.json()
        logger.debug(f"Decoded JSON payload: {payload}")
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"Could not decode JSON payload: {str(e)}\n{error_trace}")
        notifier.notify_deploy_event("unknown", "unknown", "failed", "Invalid JSON payload.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )

    # Handle ping events separately
    if x_github_event == "ping" or "zen" in payload:
        logger.info("Received ping event from GitHub.")
        return {"message": "Ping successful.", "zen": payload.get("zen")}

    # Try parsing the payload into the GitHubWebhook model
    try:
        webhook = GitHubWebhook(**payload)
        logger.debug(f"Parsed webhook payload: {webhook}")
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"Invalid payload: {str(e)}\n{error_trace}")
        notifier.notify_deploy_event("unknown", "unknown", "failed", "Invalid payload.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payload"
        )

    # Extract repository full name and verify that it is configured for deployment
    repo_full_name = webhook.repository.get("full_name")
    logger.info(f"Received webhook for repository: {repo_full_name}")

    if repo_full_name not in REPO_DEPLOY_MAP:
        message = f"Repository '{repo_full_name}' not configured for deployment."
        logger.warning(message)
        notifier.notify_deploy_event(repo_full_name, "unknown", "failed", message)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )

    deploy_config = REPO_DEPLOY_MAP[repo_full_name]
    deploy_dir = deploy_config.get("deploy_dir")
    branch = deploy_config.get("branch", "master")
    force_rebuild = deploy_config.get("force_rebuild", False)

    if not deploy_dir:
        message = f"Deploy directory not specified for repository '{repo_full_name}'."
        logger.error(message)
        notifier.notify_deploy_event(repo_full_name, branch, "failed", message)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=message
        )

    deploy_dir = os.path.abspath(deploy_dir)

    # Ensure that the payload has a "ref" field
    if not hasattr(webhook, "ref") and "ref" not in payload:
        message = "Missing 'ref' field in payload."
        logger.error(message)
        notifier.notify_deploy_event(repo_full_name, "unknown", "failed", message)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    # Determine which branch was pushed to
    push_branch = payload.get("ref", "").split('/')[-1]
    logger.info(f"Pushed to branch: {push_branch}")

    # If the pushed branch doesn't match the expected branch, skip deployment
    if push_branch != branch:
        message = f"Push to branch '{push_branch}' ignored. Expected branch '{branch}'."
        logger.info(message)
        notifier.notify_deploy_event(repo_full_name, push_branch, "ignored", message)
        return {"message": message}

    # Pull the latest changes and rebuild if necessary
    try:
        git_command = f"git pull origin {branch}"
        logger.info(f"Running command: {git_command} in {deploy_dir}")
        git_stdout, git_stderr = run_command(git_command, cwd=deploy_dir)
        logger.debug(f"git pull stdout: {git_stdout}")
        logger.debug(f"git pull stderr: {git_stderr}")

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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

    # If deployment is successful, notify and return a success message
    logger.info("Deployment successful.")
    notifier.notify_deploy_event(repo_full_name, branch, "successful", "Deployment completed successfully.")
    return {"message": "Deployment successful."}
