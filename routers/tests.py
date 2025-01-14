from fastapi import APIRouter, Depends, HTTPException, status
from dependencies import get_tests_api_key
from config import REPO_DEPLOY_MAP
from utils import run_command
import paramiko
import os
import traceback
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


#
# 1) /test-command endpoint
#
@router.get("/test-command", summary="Test Command Execution")
def test_command(api_key: str = Depends(get_tests_api_key)):
    """
    Simple check of local commands: 'git --version' & 'docker-compose --version'.
    Ensures the environment has these commands installed and reachable.
    """
    logger.info("Test command endpoint was called.")
    try:
        git_command = "git --version"
        git_stdout, _ = run_command(git_command, cwd=os.getcwd())
        git_version = git_stdout if git_stdout else "No output"

        docker_command = "docker-compose --version"
        docker_stdout, _ = run_command(docker_command, cwd=os.getcwd())
        docker_version = docker_stdout if docker_stdout else "No output"

        return {
            "git_version": git_version,
            "docker_compose_version": docker_version
        }

    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"Test command failed: {str(e)}\n{error_trace}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


#
# 2) /test-servers endpoint
#
@router.get("/test-servers", summary="Test connectivity for all servers")
def test_servers(api_key: str = Depends(get_tests_api_key)):
    """
    Iterates over ALL repos and their servers in REPO_DEPLOY_MAP,
    testing each one in turn (local or remote).

    Returns a JSON object like:
    {
      "ttm-tech/moonholidays-frontend": {
        "server1": {
          "target": "remote",
          "success": true,
          "error": null
        },
        "server2": {
          "target": "local",
          "success": true,
          "error": null
        }
      },
      "some-other-repo": ...
    }
    """
    results = {}

    for repo_name, servers_config in REPO_DEPLOY_MAP.items():
        repo_result = {}
        # servers_config might look like:
        # {
        #   "server1": { "target": "remote", ... },
        #   "server2": { "target": "local",  ... }
        # }
        for server_key, server_info in servers_config.items():
            # Skip keys that don't start with 'server'
            if not server_key.startswith("server"):
                continue

            target_type = server_info.get("target")
            entry = {
                "target": target_type,
                "success": False,
                "error": None
            }

            try:
                if target_type == "local":
                    # Just check if the deploy_dir exists
                    _check_server_local(server_info)
                    entry["success"] = True

                elif target_type == "remote":
                    # Attempt to SSH in and run 'ls' or something trivial
                    _check_server_remote(server_info)
                    entry["success"] = True

                else:
                    entry["error"] = f"Unknown target '{target_type}'"

            except Exception as ex:
                logger.exception(f"Error testing {repo_name}.{server_key}")
                entry["error"] = str(ex)

            repo_result[server_key] = entry

        results[repo_name] = repo_result

    return results


def _check_server_local(server_info: dict):
    """
    Basic local check: confirm 'deploy_dir' is a valid directory.
    Raises exception if not.
    """
    deploy_dir = server_info.get("deploy_dir")
    if not deploy_dir:
        raise ValueError("No 'deploy_dir' specified for local server.")
    if not os.path.isdir(deploy_dir):
        raise FileNotFoundError(f"Local deploy_dir '{deploy_dir}' does not exist.")


def _check_server_remote(server_info: dict):
    """
    Connects via SSH to verify the remote server is accessible.
    Tries a trivial command like 'ls' in 'deploy_dir'.
    Raises exception on failure.
    """
    deploy_dir = server_info.get("deploy_dir")
    if not deploy_dir:
        raise ValueError("No 'deploy_dir' specified for remote server.")

    host = server_info.get("host")
    user = server_info.get("user")
    key_type = server_info.get("key_type", "pem")
    key_path = server_info.get("key_path")
    port = server_info.get("port", 22)

    if not all([host, user, key_path]):
        raise ValueError("Remote server config missing host/user/key_path.")

    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Load private key
    if key_type.lower() == "pem":
        private_key = paramiko.RSAKey.from_private_key_file(key_path)
    elif key_type.lower() == "ppk":
        private_key = paramiko.RSAKey.from_private_key_file(key_path)
    else:
        raise ValueError(f"Unsupported key_type '{key_type}'.")

    try:
        ssh_client.connect(hostname=host, port=port, username=user, pkey=private_key, timeout=15)
        logger.info(f"SSH connected to {host} as {user}")

        # trivial command to check directory presence
        cmd = f"ls {deploy_dir}"
        _, stdout, stderr = ssh_client.exec_command(cmd)
        exit_code = stdout.channel.recv_exit_status()

        if exit_code != 0:
            error = stderr.read().decode().strip()
            raise RuntimeError(f"Remote command failed with exit_code={exit_code}, error: {error}")
    finally:
        ssh_client.close()
        logger.info(f"SSH disconnected from {host}")


#
# 3) /list-files endpoint
#
@router.get("/test-list-files", summary="List local & remote files for a given repository")
def list_files(
        repository_full_name: str,
        api_key: str = Depends(get_tests_api_key)
):
    """
    Combines local and remote file listings in one response for a specific repo.

    Returns JSON:
    {
      "repository": "ttm-tech/moonholidays-frontend",
      "files_by_server": {
        "server1": {
          "target": "remote",
          "success": true,
          "files": [...],
          "error": null
        },
        "server2": {
          "target": "local",
          "success": true,
          "files": [...],
          "error": null
        }
      }
    }
    """
    logger.info(f"Listing files (local & remote) for '{repository_full_name}'")

    if repository_full_name not in REPO_DEPLOY_MAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Repository '{repository_full_name}' not found in configuration."
        )

    servers_config = REPO_DEPLOY_MAP[repository_full_name]
    files_by_server = {}

    for server_key, server_info in servers_config.items():
        if not server_key.startswith("server"):
            continue

        target_type = server_info.get("target")
        entry = {
            "target": target_type,
            "success": False,
            "files": [],
            "error": None
        }

        try:
            if target_type == "local":
                entry["files"] = _list_local_files(server_info)
                entry["success"] = True
            elif target_type == "remote":
                entry["files"] = _list_remote_files(server_info)
                entry["success"] = True
            else:
                entry["error"] = f"Unknown target: {target_type}"

        except Exception as ex:
            logger.error(f"Error listing files on '{server_key}': {ex}")
            entry["error"] = str(ex)

        files_by_server[server_key] = entry

    return {
        "repository": repository_full_name,
        "files_by_server": files_by_server
    }


#
# Helper: list local files
#
def _list_local_files(server_info: dict):
    deploy_dir = server_info.get("deploy_dir")
    if not deploy_dir:
        raise ValueError("No 'deploy_dir' specified for local server.")

    if not os.path.isdir(deploy_dir):
        raise FileNotFoundError(f"Local directory '{deploy_dir}' does not exist.")

    return os.listdir(deploy_dir)


#
# Helper: list remote files
#
def _list_remote_files(server_info: dict):
    """
    SSH in, run 'ls -la <deploy_dir>', parse out filenames.
    """
    deploy_dir = server_info.get("deploy_dir")
    if not deploy_dir:
        raise ValueError("No 'deploy_dir' specified for remote server.")

    host = server_info.get("host")
    user = server_info.get("user")
    key_type = server_info.get("key_type", "pem")
    key_path = server_info.get("key_path")
    port = server_info.get("port", 22)

    if not all([host, user, key_path]):
        raise ValueError("Remote server config missing host, user, or key_path.")

    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Load private key
    if key_type.lower() == "pem":
        private_key = paramiko.RSAKey.from_private_key_file(key_path)
    elif key_type.lower() == "ppk":
        private_key = paramiko.RSAKey.from_private_key_file(key_path)
    else:
        raise ValueError(f"Unsupported key_type '{key_type}'.")

    file_list = []
    try:
        logger.info(f"SSH connecting to {host}:{port} as {user}")
        ssh_client.connect(hostname=host, port=port, username=user, pkey=private_key, timeout=15)
        logger.info(f"SSH connected to {host} as {user}")

        cmd = f"ls -la {deploy_dir}"
        _, stdout, stderr = ssh_client.exec_command(cmd)
        exit_code = stdout.channel.recv_exit_status()

        lines = stdout.read().decode().splitlines()
        err_data = stderr.read().decode().strip()

        if exit_code != 0:
            raise RuntimeError(f"Command '{cmd}' failed (exit={exit_code}): {err_data}")

        for line in lines:
            # Typically looks like: "-rw-r--r-- 1 ubuntu ubuntu  1234 Jan 1 12:34 filename"
            parts = line.split(maxsplit=8)
            if len(parts) < 9:
                continue
            filename = parts[8]
            if filename not in ('.', '..'):
                file_list.append(filename)

    finally:
        ssh_client.close()
        logger.info(f"SSH disconnected from {host}")

    return file_list
