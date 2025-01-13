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

    if signature is None:
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

        logger.debug(f"Command executed successfully: {command}")
        return stdout_decoded, stderr_decoded

    except subprocess.CalledProcessError as e:
        error_message = f"Command failed: {command}\nError: {e.stderr.strip()}"
        logger.error(error_message)
        raise Exception(error_message)

    except Exception as e:
        logger.error(f"Unexpected error during command execution: {str(e)}")
        raise Exception(str(e))


def get_docker_compose_command():
    # Assemble the command for 'up'
    command = f"{DOCKER_COMPOSE_PATH} {DOCKER_COMPOSE_OPTIONS}"
    if sys.platform.startswith("linux"):
        command = f"sudo {command}"
    return command


def get_docker_compose_down_command():
    # Assemble the command for 'down' including the --remove-orphans flag.
    base_cmd = DOCKER_COMPOSE_PATH
    if sys.platform.startswith("linux"):
        base_cmd = f"sudo {base_cmd}"
    return f"{base_cmd} down --remove-orphans"


def safe_down_containers(deploy_dir: str):
    """
    Attempts to shut down docker containers.
    If the error indicates active endpoints, it logs a warning and ignores it.
    """
    down_command = get_docker_compose_down_command()
    logger.info("Attempting to take down running containers (if any)...")
    try:
        run_command(down_command, cwd=deploy_dir)
    except Exception as e:
        err_message = str(e)
        if "has active endpoints" in err_message:
            logger.warning(
                "Encountered active endpoints error when removing network. "
                "Continuing despite the following error: %s", err_message
            )
        else:
            raise e


def restart_containers(deploy_dir: str):
    """
    Restarts containers:
      1. Takes down any running containers (ignoring active endpoint errors)
      2. Rebuilds and starts containers using docker-compose up.
    """
    safe_down_containers(deploy_dir)
    up_command = get_docker_compose_command()
    logger.info("Rebuilding and starting containers...")
    run_command(up_command, cwd=deploy_dir)
