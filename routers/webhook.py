import asyncio
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

# Dictionary to track currently running tasks keyed by (repo_full_name, branch)
running_tasks = {}


async def run_deploy_chain(repo_full_name: str, push_branch: str, sub_config: dict):
    """
    Runs the deployment chain in an executor to avoid blocking the event loop.
    """
    loop = asyncio.get_running_loop()
    try:
        # Run the synchronous deploy_chain in an executor.
        await loop.run_in_executor(
            None,
            deploy_chain,
            repo_full_name,
            push_branch,
            sub_config,
            notifier
        )
        # Notify only if deployment finished successfully.
        notifier.notify_deploy_event(
            repo_full_name, push_branch, "successful", "All servers deployed successfully."
        )
        logger.info(f"Deployment chain completed for {repo_full_name} on branch {push_branch}.")
    except asyncio.CancelledError:
        logger.info(f"Deployment chain for {repo_full_name} on branch {push_branch} was cancelled.")
        # Cancellation notifications are skipped per requirements.
        raise
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"Deployment chain failed: {str(e)}\n{error_trace}")
        notifier.notify_deploy_event(
            repo_full_name, push_branch, "failed", f"Error: {str(e)}"
        )


def cancel_existing_task(repo_full_name: str, push_branch: str):
    """
    If there is an existing deployment task for the same repository and branch, cancel it.
    """
    key = (repo_full_name, push_branch)
    existing_task = running_tasks.get(key)
    if existing_task and not existing_task.done():
        logger.info(f"Cancelling existing deployment for {repo_full_name} on branch {push_branch}.")
        existing_task.cancel()


@router.post("/webhook", summary="GitHub Webhook Endpoint")
async def handle_webhook(
        request: Request,
        x_hub_signature_256: str = Header(None),
        x_github_event: str = Header(None)
):
    logger.info("Webhook endpoint was called.")
    body_bytes = await request.body()

    # 1. Verify signature.
    if not x_hub_signature_256:
        logger.error("Missing X-Hub-Signature-256 header.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing signature header"
        )
    if not verify_signature(body_bytes, x_hub_signature_256):
        logger.warning("Invalid signature.")
        # Do not send notifications for invalid signatures.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature"
        )

    # 2. Parse payload.
    content_type = request.headers.get("Content-Type", "")
    payload = None # Initialize payload to None/Clean memory # Noqa
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )

    # 3. Handle ping events.
    if x_github_event == "ping" or "zen" in payload:
        logger.info("Received ping event from GitHub.")
        return {"message": "Ping successful.", "zen": payload.get("zen")}

    # 4. Validate payload using the pydantic model.
    try:
        webhook = GitHubWebhook(**payload)
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"Invalid payload: {str(e)}\n{error_trace}")
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )

    sub_config = REPO_DEPLOY_MAP[repo_full_name]

    # 5. Check if the push branch is allowed for deployment (if configured).
    allowed_branches = sub_config.get("branches")
    if allowed_branches and push_branch not in allowed_branches:
        logger.info(
            f"Branch '{push_branch}' is not configured for deployment for repository '{repo_full_name}'. Deployment skipped."
        )
        # Do not send any notifications if the build is skipped.
        return {"message": f"Deployment skipped for branch '{push_branch}'."}

    # 6. Cancel any existing deployment task for the same repository and branch.
    cancel_existing_task(repo_full_name, push_branch)

    # 7. Start the deployment chain as an asynchronous background task.
    key = (repo_full_name, push_branch)
    task = asyncio.create_task(run_deploy_chain(repo_full_name, push_branch, sub_config))
    running_tasks[key] = task

    # 8. Respond immediately to GitHub.
    return {"message": f"Deployment chain started for {repo_full_name} on branch {push_branch}."}

# import asyncio
# import logging
# import traceback
# import json
# from urllib.parse import parse_qs
# from fastapi import APIRouter, Request, Header, HTTPException, status
# from models.github_webhook import GitHubWebhook
# from notifications import Notifications
# from utils import verify_signature
# from config import REPO_DEPLOY_MAP
# from deploy_chain import deploy_chain
#
# router = APIRouter()
# logger = logging.getLogger(__name__)
# notifier = Notifications(config_path="config.yaml")
#
# # Dictionary to track currently running tasks keyed by (repo_full_name, branch)
# running_tasks = {}
#
#
# async def run_deploy_chain(repo_full_name: str, push_branch: str, sub_config: dict):
#     """
#     Runs the deployment chain in an executor to avoid blocking the event loop.
#     """
#     loop = asyncio.get_running_loop()
#     try:
#         # Run the synchronous deploy_chain in an executor.
#         await loop.run_in_executor(
#             None,
#             deploy_chain,
#             repo_full_name,
#             push_branch,
#             sub_config,
#             notifier
#         )
#         notifier.notify_deploy_event(
#             repo_full_name, push_branch, "successful", "All servers deployed."
#         )
#         logger.info(f"Deployment chain completed for {repo_full_name} on branch {push_branch}.")
#     except asyncio.CancelledError:
#         notifier.notify_deploy_event(
#             repo_full_name, push_branch, "failed", "Deployment canceled due to a new trigger."
#         )
#         logger.info(f"Deployment chain for {repo_full_name} on branch {push_branch} was canceled.")
#         raise
#     except Exception as e:
#         error_trace = traceback.format_exc()
#         logger.error(f"Deployment chain failed: {str(e)}\n{error_trace}")
#         notifier.notify_deploy_event(repo_full_name, push_branch, "failed", str(e))
#
#
# def cancel_existing_task(repo_full_name: str, push_branch: str):
#     """
#     If there is an existing deployment task for the same repository and branch, cancel it.
#     """
#     key = (repo_full_name, push_branch)
#     existing_task = running_tasks.get(key)
#     if existing_task and not existing_task.done():
#         logger.info(f"Cancelling existing deployment for {repo_full_name} on branch {push_branch}.")
#         existing_task.cancel()
#
#
# @router.post("/webhook", summary="GitHub Webhook Endpoint")
# async def handle_webhook(
#         request: Request,
#         x_hub_signature_256: str = Header(None),
#         x_github_event: str = Header(None)
# ):
#     logger.info("Webhook endpoint was called.")
#     body_bytes = await request.body()
#
#     # 1. Verify signature
#     if not x_hub_signature_256:
#         logger.error("Missing X-Hub-Signature-256 header.")
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Missing signature header"
#         )
#     if not verify_signature(body_bytes, x_hub_signature_256):
#         logger.warning("Invalid signature.")
#         notifier.notify_deploy_event("unknown", "unknown", "failed", "Invalid signature.")
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Invalid signature"
#         )
#
#     # 2. Parse payload
#     content_type = request.headers.get("Content-Type", "")
#     payload = None
#     try:
#         if "application/json" in content_type:
#             payload = await request.json()
#         elif "application/x-www-form-urlencoded" in content_type:
#             form_data = parse_qs(body_bytes.decode("utf-8"))
#             if "payload" in form_data:
#                 payload_str = form_data["payload"][0]
#                 payload = json.loads(payload_str)
#             else:
#                 raise ValueError("No payload parameter in form data")
#         else:
#             raise ValueError(f"Unsupported Content-Type: {content_type}")
#     except Exception as e:
#         error_trace = traceback.format_exc()
#         logger.error(f"Could not decode JSON payload: {str(e)}\n{error_trace}")
#         notifier.notify_deploy_event("unknown", "unknown", "failed", "Invalid JSON payload.")
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Invalid JSON payload"
#         )
#
#     # 3. Handle ping events
#     if x_github_event == "ping" or "zen" in payload:
#         logger.info("Received ping event from GitHub.")
#         return {"message": "Ping successful.", "zen": payload.get("zen")}
#
#     # 4. Validate payload using your pydantic model
#     try:
#         webhook = GitHubWebhook(**payload)
#     except Exception as e:
#         error_trace = traceback.format_exc()
#         logger.error(f"Invalid payload: {str(e)}\n{error_trace}")
#         notifier.notify_deploy_event("unknown", "unknown", "failed", "Invalid payload.")
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Invalid payload"
#         )
#
#     repo_full_name = webhook.repository.get("full_name", "")
#     branch_ref = webhook.ref or ""
#     push_branch = branch_ref.split('/')[-1] if branch_ref else ""
#
#     logger.info(f"Received webhook for repo: {repo_full_name}, branch: {push_branch}")
#
#     if repo_full_name not in REPO_DEPLOY_MAP:
#         message = f"Repository '{repo_full_name}' not configured for deployment."
#         logger.warning(message)
#         notifier.notify_deploy_event(repo_full_name, push_branch, "failed", message)
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=message
#         )
#
#     sub_config = REPO_DEPLOY_MAP[repo_full_name]
#
#     # 5. Cancel any existing deployment task for the same repository and branch.
#     cancel_existing_task(repo_full_name, push_branch)
#
#     # 6. Start the deployment chain as an asynchronous background task.
#     key = (repo_full_name, push_branch)
#     task = asyncio.create_task(run_deploy_chain(repo_full_name, push_branch, sub_config))
#     running_tasks[key] = task
#
#     # 7. Respond immediately to GitHub.
#     return {"message": f"Deployment chain started for {repo_full_name} on branch {push_branch}."}
