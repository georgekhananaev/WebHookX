import logging
import os
import time
import paramiko
from utils import run_command  # Removed restart_containers since we'll handle locally

logger = logging.getLogger(__name__)

def deploy_chain(repo_name: str, push_branch: str, servers_config: dict, notifier):
    """
    Iterates over server definitions in servers_config and deploys sequentially.
    If `additional_tasks_only` is true in a server's config, skips all fetch/clone/docker-compose steps
    and executes only the additional_terminal_tasks.
    """
    server_keys = sorted(servers_config.keys())
    for server_key in server_keys:
        if not server_key.startswith("server"):
            logger.info(f"Skipping '{server_key}' as it's not a server definition.")
            continue

        server_info = servers_config[server_key]
        logger.info(f"=== Deploying {server_key} for repo '{repo_name}' ===")

        # Check branch match
        config_branch = server_info.get("branch", "main")
        if push_branch != config_branch:
            msg = (
                f"Push branch '{push_branch}' does not match configured branch "
                f"'{config_branch}'. Skipping {server_key}."
            )
            logger.info(msg)
            notifier.notify_deploy_event(repo_name, push_branch, "ignored", msg)
            continue

        try:
            additional_tasks_only = server_info.get("additional_tasks_only", False)
            target = server_info.get("target")

            # If additional_tasks_only is enabled, skip main deployment steps.
            if not additional_tasks_only:
                if target == "local":
                    deploy_local(server_info, repo_name, push_branch, notifier)
                elif target == "remote":
                    deploy_remote(server_info, repo_name, push_branch, notifier)
                else:
                    msg = f"Unknown target '{target}' for {server_key}. Skipping."
                    logger.warning(msg)
                    notifier.notify_deploy_event(repo_name, push_branch, "failed", msg)
                    continue
            else:
                logger.info(f"additional_tasks_only is enabled for {server_key}; skipping fetch/clone/docker operations.")

            # Execute additional tasks (if any)
            tasks = server_info.get("additional_terminal_tasks", [])
            if tasks:
                if target == "local":
                    run_local_tasks(tasks, server_info.get("deploy_dir"), notifier, repo_name, push_branch)
                elif target == "remote":
                    run_remote_tasks(tasks, server_info, notifier, repo_name, push_branch)
                else:
                    # When target is not specified, run tasks locally in the current working directory.
                    run_local_tasks(tasks, os.getcwd(), notifier, repo_name, push_branch)

            logger.info(f"=== Finished deployment for {server_key} ===\n")
        except Exception as e:
            logger.error(f"Deployment failed on {server_key}: {e}", exc_info=True)
            notifier.notify_deploy_event(repo_name, push_branch, "failed", str(e))
            # Optionally, decide whether to continue with other servers or abort.
            # continue


# ===================================================================
# LOCAL DEPLOYMENT
# ===================================================================
def deploy_local(server_info, repo_name, push_branch, notifier):
    """
    Executes local deployment steps:
      1) Ensures the repository directory exists (or clones if allowed)
      2) Pulls updates from git
      3) Rebuilds containers if changes are detected or forced.
    """
    deploy_dir = server_info.get("deploy_dir")
    branch = server_info.get("branch", "main")
    clone_url = server_info.get("clone_url")
    create_dir = server_info.get("create_dir", False)
    force_rebuild = server_info.get("force_rebuild", False)
    use_sudo = server_info.get("sudo", False)

    try:
        _ensure_local_repo(deploy_dir, clone_url, create_dir, branch)
    except Exception as e:
        raise RuntimeError(f"Failed to ensure local repository at {deploy_dir}: {e}")

    # Pull latest changes
    git_pull_cmd = f"git pull origin {branch}"
    out, err = run_command(git_pull_cmd, cwd=deploy_dir)
    logger.info(f"Git pull output:\n{out}")
    if err:
        logger.warning(f"Git pull stderr:\n{err}")

    # Determine if rebuild is necessary
    if "Already up to date." in out and not force_rebuild:
        logger.info("No changes found locally. Skipping docker-compose rebuild.")
    else:
        logger.info("Changes detected or forced rebuild. Starting container rebuild...")

        docker_prefix = ""
        if use_sudo:
            if _can_run_sudo_local():
                docker_prefix = "sudo "
            else:
                logger.warning("Sudo requested but not available locally. Proceeding without sudo.")

        down_cmd = f"cd {deploy_dir} && {docker_prefix}docker-compose down --remove-orphans"
        logger.info(f"Running local down command: {down_cmd}")
        run_command(down_cmd, cwd=deploy_dir)

        up_cmd = f"cd {deploy_dir} && {docker_prefix}docker-compose up -d --build --remove-orphans"
        logger.info(f"Running local up command: {up_cmd}")
        run_command(up_cmd, cwd=deploy_dir)

    notifier.notify_deploy_event(repo_name, push_branch, "successful", "Local deployment completed.")


def _ensure_local_repo(deploy_dir: str, clone_url: str, create_dir: bool, branch: str):
    """
    Ensures that the local deployment directory exists. Clones if needed.
    """
    if os.path.isdir(deploy_dir):
        logger.info(f"Local directory already exists: {deploy_dir}")
        return

    if not create_dir:
        msg = (
            f"Directory '{deploy_dir}' does not exist. "
            "Set 'create_dir: true' to clone repository automatically."
        )
        raise FileNotFoundError(msg)

    if not clone_url:
        raise ValueError(f"'clone_url' must be specified to clone into '{deploy_dir}'.")

    parent_dir = os.path.dirname(deploy_dir)
    if parent_dir and not os.path.isdir(parent_dir):
        logger.info(f"Creating parent directory: {parent_dir}")
        os.makedirs(parent_dir, exist_ok=True)

    clone_cmd = f"git clone --branch {branch} {clone_url} \"{deploy_dir}\""
    logger.info(f"Cloning repository with command: {clone_cmd}")
    run_command(clone_cmd, cwd=parent_dir or ".")


def _can_run_sudo_local():
    """
    Checks whether sudo can run non-interactively on the local machine.
    Runs: sudo -n true
    """
    try:
        run_command("sudo -n true")
        return True
    except Exception as e:
        logger.warning(f"Local sudo test failed: {e}")
        return False


# ===================================================================
# REMOTE DEPLOYMENT
# ===================================================================
def deploy_remote(server_info, repo_name, push_branch, notifier):
    """
    Executes remote deployment steps via SSH:
      1) Connects via SSH.
      2) Ensures the repository exists on remote (cloning if allowed).
      3) Pulls updates from git.
      4) Rebuilds containers if changes are detected or forced.
    """
    host = server_info["host"]
    port = server_info.get("port", 22)
    user = server_info["user"]
    branch = server_info.get("branch", "main")
    deploy_dir = server_info["deploy_dir"]
    clone_url = server_info.get("clone_url")
    create_dir = server_info.get("create_dir", False)
    force_rebuild = server_info.get("force_rebuild", False)
    use_sudo = server_info.get("sudo", False)
    key_type = server_info.get("key_type", "pem")
    key_path = server_info["key_path"]

    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        private_key = _load_private_key(key_type, key_path)
        ssh_client.connect(
            hostname=host,
            port=port,
            username=user,
            pkey=private_key,
            timeout=15
        )
        logger.info(f"SSH connected to {host} as {user}")

        try:
            _ensure_remote_repo(ssh_client, deploy_dir, clone_url, create_dir, branch)
        except Exception as repo_err:
            raise RuntimeError(f"Failed to ensure remote repository at {deploy_dir}: {repo_err}")

        # Pull the latest changes
        pull_cmd = f"cd {deploy_dir} && git pull origin {branch}"
        pull_output = _exec_ssh_command(ssh_client, pull_cmd)
        logger.info(f"Remote git pull output:\n{pull_output}")

        # Decide if we need to rebuild
        do_rebuild = force_rebuild or ("Already up to date." not in pull_output)
        docker_bin = _detect_docker_compose_binary(ssh_client)

        docker_prefix = ""
        if use_sudo:
            if _can_run_sudo_remote(ssh_client):
                docker_prefix = "sudo "
            else:
                logger.warning("Sudo requested but not available remotely. Proceeding without sudo.")
        else:
            docker_prefix = _default_docker_prefix(ssh_client)

        if do_rebuild:
            logger.info("Changes detected or forced rebuild on remote. Rebuilding containers.")
            down_cmd = f"cd {deploy_dir} && {docker_prefix}{docker_bin} down --remove-orphans"
            _exec_ssh_command(ssh_client, down_cmd, allow_benign_errors=True)

            up_cmd = f"cd {deploy_dir} && {docker_prefix}{docker_bin} up -d --build --remove-orphans"
            rebuild_output = _exec_ssh_command(ssh_client, up_cmd)
            logger.info(f"Docker rebuild output:\n{rebuild_output}")
        else:
            logger.info("No changes detected remotely. Bringing up containers without rebuilding.")
            up_cmd = f"cd {deploy_dir} && {docker_prefix}{docker_bin} up -d"
            up_output = _exec_ssh_command(ssh_client, up_cmd)
            logger.info(f"Docker up output:\n{up_output}")

        notifier.notify_deploy_event(repo_name, push_branch, "successful", f"Remote server {host} updated.")
    except Exception as e:
        logger.error(f"Remote deploy error on {host}: {e}", exc_info=True)
        notifier.notify_deploy_event(repo_name, push_branch, "failed", str(e))
        raise
    finally:
        ssh_client.close()
        logger.info(f"SSH disconnected from {host}")


def _load_private_key(key_type: str, key_path: str):
    """
    Loads a private key based on key type. Currently supports 'pem' and 'ppk'.
    """
    key_type = key_type.lower()
    if key_type in ("pem", "ppk"):
        return paramiko.RSAKey.from_private_key_file(key_path)
    raise ValueError(f"Unsupported key_type '{key_type}'. Use 'pem' or 'ppk'.")


def _ensure_remote_repo(ssh_client, deploy_dir: str, clone_url: str, create_dir: bool, branch: str):
    """
    Ensures that the remote deploy directory exists. Clones if needed.
    """
    check_cmd = f'[ -d "{deploy_dir}" ] && echo "EXISTS" || echo "NOT_EXISTS"'
    result = _exec_ssh_command(ssh_client, check_cmd).strip()
    if result == "EXISTS":
        logger.info(f"Remote directory exists: {deploy_dir}")
        return

    if not create_dir:
        msg = (
            f"Remote directory '{deploy_dir}' does not exist. "
            "Set 'create_dir: true' to clone the repository automatically."
        )
        raise FileNotFoundError(msg)

    if not clone_url:
        raise ValueError(f"'clone_url' must be specified to clone into remote '{deploy_dir}'.")

    parent_dir = os.path.dirname(deploy_dir)
    if parent_dir:
        mk_cmd = f'mkdir -p "{parent_dir}"'
        logger.info(f"Creating remote parent directory: {parent_dir}")
        _exec_ssh_command(ssh_client, mk_cmd)

    clone_cmd = f'cd "{parent_dir or "/"}" && git clone --branch {branch} {clone_url} "{deploy_dir}"'
    logger.info(f"Cloning remote repository with command: {clone_cmd}")
    _exec_ssh_command(ssh_client, clone_cmd)


def _default_docker_prefix(ssh_client) -> str:
    """
    Determines a default docker command prefix based on the remote OS.
    Returns "sudo " for Linux if necessary.
    """
    try:
        os_type = _exec_ssh_command(ssh_client, "uname -s", timeout=5).strip()
        return "sudo " if "Linux" in os_type else ""
    except Exception:
        return ""


def _can_run_sudo_remote(ssh_client) -> bool:
    """
    Checks if sudo can run non-interactively on the remote machine.
    Executes 'sudo -n true' remotely.
    """
    try:
        _exec_ssh_command(ssh_client, "sudo -n true", timeout=10, allow_benign_errors=True)
        return True
    except Exception as e:
        logger.warning(f"Remote sudo test failed: {e}")
        return False


def _detect_docker_compose_binary(ssh_client) -> str:
    """
    Detects whether 'docker compose' or 'docker-compose' is available on the remote.
    Returns the detected binary.
    """
    try:
        _exec_ssh_command(ssh_client, "which docker", timeout=5)
        version_out = _exec_ssh_command(ssh_client, "docker compose version", timeout=5, allow_benign_errors=True)
        if "Docker Compose version" in version_out:
            return "docker compose"
    except Exception as e:
        logger.debug(f"'docker compose' not available: {e}")

    try:
        _exec_ssh_command(ssh_client, "which docker-compose", timeout=5)
        return "docker-compose"
    except Exception:
        pass

    raise RuntimeError("Neither 'docker compose' nor 'docker-compose' found on the remote system.")


# ===================================================================
# TASK EXECUTION
# ===================================================================
def run_local_tasks(tasks, cwd, notifier, repo_name, push_branch):
    """
    Executes a list of local commands sequentially.
    """
    for cmd in tasks:
        logger.info(f"Executing local task: {cmd}")
        try:
            out, err = run_command(cmd, cwd=cwd)
            if out.strip():
                logger.info(f"Local task output:\n{out}")
            else:
                logger.info(f"Local task '{cmd}' returned no output.")
            if err.strip():
                logger.warning(f"Local task error output:\n{err}")
        except Exception as e:
            logger.error(f"Local task '{cmd}' failed: {e}", exc_info=True)
            notifier.notify_deploy_event(
                repo_name, push_branch, "failed", f"Local task '{cmd}' failed: {e}"
            )
            raise


def run_remote_tasks(tasks, server_info, notifier, repo_name, push_branch):
    """
    Executes a list of commands on a remote host via SSH and logs the output.
    Now uses get_pty=True so sudo can be used without silently failing.
    """
    host = server_info["host"]
    port = server_info.get("port", 22)
    user = server_info["user"]
    key_path = server_info["key_path"]
    key_type = server_info.get("key_type", "pem")

    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        private_key = _load_private_key(key_type, key_path)
        ssh_client.connect(hostname=host, port=port, username=user, pkey=private_key, timeout=15)

        for cmd in tasks:
            logger.info(f"Executing remote task on {host}: {cmd}")
            try:
                result = _exec_ssh_command(ssh_client, cmd)
                if result.strip():
                    logger.info(f"Remote task '{cmd}' output:\n{result}")
                else:
                    logger.info(f"Remote task '{cmd}' returned no output.")
            except Exception as e:
                logger.error(f"Remote task '{cmd}' failed on {host}: {e}", exc_info=True)
                notifier.notify_deploy_event(
                    repo_name, push_branch, "failed", f"Remote task '{cmd}' failed: {e}"
                )
                raise
    finally:
        ssh_client.close()
        logger.info(f"SSH disconnected from {host}")


def _exec_ssh_command(ssh_client, cmd, timeout=30, allow_benign_errors=False):
    """
    Executes an SSH command using exec_command(..., get_pty=True) and returns stdout as a string.

    - If the command fails (non-zero exit), raises a RuntimeError unless
      allow_benign_errors=True, in which case it only logs a warning.
    - Using get_pty=True helps with 'sudo' and other commands that need a TTY.
    - Both stdout and stderr are captured; if there's content in stderr and
      exit_status != 0, we treat it as an error (unless allow_benign_errors).
    """
    logger.debug(f"Executing SSH command (PTY): {cmd}")
    # We enable get_pty so that sudo and other interactive commands can run
    stdin, stdout, stderr = ssh_client.exec_command(cmd, timeout=timeout, get_pty=True)

    # It's good practice to close stdin if you don't plan to write to it
    stdin.channel.shutdown_write()

    # Wait for the command to complete
    exit_status = stdout.channel.recv_exit_status()

    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")

    logger.debug(f"Command '{cmd}' exit status: {exit_status}")
    if err.strip():
        logger.debug(f"Command '{cmd}' stderr:\n{err}")

    if exit_status != 0 and not allow_benign_errors:
        raise RuntimeError(f"Command '{cmd}' failed (exit {exit_status}): {err}")

    return out
