# webhook.py is the FastAPI router for handling GitHub webhook events.

import logging
import traceback
import json
from urllib.parse import parse_qs
from fastapi import APIRouter, Request, Header, HTTPException, status

from models.github_webhook import GitHubWebhook
from notifications import Notifications
from utils import verify_signature
from config import REPO_DEPLOY_MAP
from deploy_chain import deploy_chain

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
    body_bytes = await request.body()

    # 1. Verify signature
    if not x_hub_signature_256:
        logger.error("Missing X-Hub-Signature-256 header.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing signature header"
        )
    if not verify_signature(body_bytes, x_hub_signature_256):
        logger.warning("Invalid signature.")
        notifier.notify_deploy_event("unknown", "unknown", "failed", "Invalid signature.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature"
        )

    # 2. Parse payload
    content_type = request.headers.get("Content-Type", "")
    payload = None
    try:
        if "application/json" in content_type:
            payload = await request.json()
        elif "application/x-www-form-urlencoded" in content_type:
            form_data = parse_qs(body_bytes.decode("utf-8"))
            if "payload" in form_data:
                payload_str = form_data["payload"][0]
                payload = json.loads(payload_str)
            else:
                raise ValueError("No payload parameter in form data")
        else:
            raise ValueError(f"Unsupported Content-Type: {content_type}")
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"Could not decode JSON payload: {str(e)}\n{error_trace}")
        notifier.notify_deploy_event("unknown", "unknown", "failed", "Invalid JSON payload.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )

    # 3. Handle ping
    if x_github_event == "ping" or "zen" in payload:
        logger.info("Received ping event from GitHub.")
        return {"message": "Ping successful.", "zen": payload.get("zen")}

    # 4. Validate payload
    try:
        webhook = GitHubWebhook(**payload)
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"Invalid payload: {str(e)}\n{error_trace}")
        notifier.notify_deploy_event("unknown", "unknown", "failed", "Invalid payload.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payload"
        )

    repo_full_name = webhook.repository.get("full_name", "")
    branch_ref = webhook.ref or ""
    push_branch = branch_ref.split('/')[-1] if branch_ref else ""

    logger.info(f"Received webhook for repo: {repo_full_name}, branch: {push_branch}")

    if repo_full_name not in REPO_DEPLOY_MAP:
        message = f"Repository '{repo_full_name}' not configured for deployment."
        logger.warning(message)
        notifier.notify_deploy_event(repo_full_name, push_branch, "failed", message)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )

    # 5. Run the deployment chain for this repo
    try:
        sub_config = REPO_DEPLOY_MAP[repo_full_name]
        deploy_chain(repo_full_name, push_branch, sub_config, notifier)
        notifier.notify_deploy_event(repo_full_name, push_branch, "successful", "All servers deployed.")
        return {"message": f"Deployment chain completed for {repo_full_name} on branch {push_branch}."}
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"Deployment chain failed: {str(e)}\n{error_trace}")
        notifier.notify_deploy_event(repo_full_name, push_branch, "failed", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
