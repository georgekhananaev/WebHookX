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
    # Build the base command for "up" using the options from config.
    command = f"{DOCKER_COMPOSE_PATH} {DOCKER_COMPOSE_OPTIONS}"

    # Prepend `sudo` if running on Linux
    if sys.platform.startswith("linux"):
        command = f"sudo {command}"

    return command


def get_docker_compose_down_command():
    """
    Returns the docker-compose command to take down containers
    while removing orphan containers to avoid errors with active endpoints.
    """
    base_cmd = DOCKER_COMPOSE_PATH
    if sys.platform.startswith("linux"):
        base_cmd = f"sudo {base_cmd}"
    # Adding --remove-orphans to ensure any orphan endpoints are removed.
    return f"{base_cmd} down --remove-orphans"


def restart_containers(deploy_dir: str):
    """
    Takes down any running Docker containers (using the down command with --remove-orphans)
    and then rebuilds and starts them using the up command.

    :param deploy_dir: The directory containing your docker-compose.yaml file.
    """
    # Use the custom down command which removes orphan endpoints.
    down_command = get_docker_compose_down_command()
    logger.info("Taking down running containers (if any)...")
    run_command(down_command, cwd=deploy_dir)

    # Run the up command to rebuild and start containers.
    up_command = get_docker_compose_command()
    logger.info("Rebuilding and starting containers...")
    run_command(up_command, cwd=deploy_dir)
