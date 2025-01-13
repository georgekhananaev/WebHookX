# utils.py

import hmac
import hashlib
import subprocess
import logging
import sys

from config import WEBHOOK_SECRET, DOCKER_COMPOSE_PATH, DOCKER_COMPOSE_OPTIONS

logger = logging.getLogger(__name__)


def verify_signature(request_body: bytes, signature: str) -> bool:
    if not WEBHOOK_SECRET:
        logger.debug("Webhook secret is disabled. Skipping signature verification.")
        return True

    if not signature:
        logger.warning("No signature provided.")
        return False

    try:
        sha_name, signature = signature.split('=')
    except ValueError:
        logger.warning("Invalid signature format.")
        return False

    if sha_name != 'sha256':
        logger.warning(f"Unsupported signature type: {sha_name}")
        return False

    mac = hmac.new(WEBHOOK_SECRET.encode(), msg=request_body, digestmod=hashlib.sha256)
    is_valid = hmac.compare_digest(mac.hexdigest(), signature)
    if is_valid:
        logger.debug("Webhook signature verified successfully.")
    else:
        logger.warning("Webhook signature verification failed.")

    return is_valid


def run_command(command: str, cwd: str):
    logger.debug(f"Executing command: {command} in {cwd}")
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout_decoded = result.stdout.strip()
        stderr_decoded = result.stderr.strip()

        if stdout_decoded:
            logger.debug(f"Command stdout: {stdout_decoded}")
        if stderr_decoded:
            logger.debug(f"Command stderr: {stderr_decoded}")

        return stdout_decoded, stderr_decoded

    except subprocess.CalledProcessError as e:
        error_message = f"Command failed: {command}\nError: {e.stderr.strip()}"
        logger.error(error_message)
        raise

    except Exception as e:
        logger.error(f"Unexpected error during command execution: {str(e)}")
        raise


def get_docker_compose_command():
    command = f"{DOCKER_COMPOSE_PATH} {DOCKER_COMPOSE_OPTIONS}"
    if sys.platform.startswith("linux"):
        command = f"sudo {command}"
    return command


def get_docker_compose_down_command():
    base_cmd = DOCKER_COMPOSE_PATH
    if sys.platform.startswith("linux"):
        base_cmd = f"sudo {base_cmd}"
    return f"{base_cmd} down --remove-orphans"


def restart_containers(deploy_dir: str):
    """
    Example logic to:
      1) docker-compose down (ignore errors with active endpoints if desired)
      2) docker-compose up with build
    """
    down_cmd = get_docker_compose_down_command()
    logger.info("Taking down running containers...")
    try:
        subprocess.run(down_cmd, cwd=deploy_dir, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        err = e.stderr or ""
        if "has active endpoints" in err:
            logger.warning("Encountered active endpoints error, ignoring.")
        else:
            logger.error(f"Error taking down containers: {err}")
            raise

    up_cmd = get_docker_compose_command()
    logger.info("Rebuilding and starting containers...")
    subprocess.run(up_cmd, cwd=deploy_dir, shell=True, check=True)