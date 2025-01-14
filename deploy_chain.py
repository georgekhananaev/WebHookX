# Filename: deploy_chain.py

import logging
import os
import paramiko
from utils import run_command  # Removed restart_containers since we'll handle locally

logger = logging.getLogger(__name__)


def deploy_chain(repo_name: str, push_branch: str, servers_config: dict, notifier):
    """
    Iterates over server1, server2, ... in servers_config
    and deploys each one sequentially.
    """
    server_keys = sorted(servers_config.keys())
    for server_key in server_keys:
        server_info = servers_config[server_key]
        logger.info(f"=== Deploying {server_key} for repo '{repo_name}' ===")

        # Skip non-"serverX" keys
        if not server_key.startswith("server"):
            logger.info(f"Skipping '{server_key}' as it's not recognized as a server definition.")
            continue

        config_branch = server_info.get("branch", "main")
        if push_branch != config_branch:
            msg = f"Push branch '{push_branch}' does not match '{config_branch}'. Skipping {server_key}."
            logger.info(msg)
            notifier.notify_deploy_event(repo_name, push_branch, "ignored", msg)
            continue

        try:
            target = server_info.get("target")
            if target == "local":
                deploy_local(server_info, repo_name, push_branch, notifier)
            elif target == "remote":
                deploy_remote(server_info, repo_name, push_branch, notifier)
            else:
                msg = f"Unknown target '{target}' for {server_key}. Skipping."
                logger.warning(msg)
                notifier.notify_deploy_event(repo_name, push_branch, "failed", msg)
                continue

            # Optional additional tasks
            tasks = server_info.get("additional_terminal_tasks", [])
            if tasks:
                if target == "local":
                    run_local_tasks(tasks, server_info.get("deploy_dir"), notifier, repo_name, push_branch)
                else:
                    run_remote_tasks(tasks, server_info, notifier, repo_name, push_branch)

            logger.info(f"=== Finished {server_key} ===\n")
        except Exception as e:
            logger.error(f"Deployment failed on {server_key}: {e}")
            # Uncomment raise if you want to stop on first error.
            # raise


# -------------------------------------------------------------------
# LOCAL DEPLOY
# -------------------------------------------------------------------
def deploy_local(server_info, repo_name, push_branch, notifier):
    """
    1) Ensure the repo directory is present or create/clone it.
    2) Perform 'git pull' from that directory.
    3) If changes found or force_rebuild, rebuild containers with sudo if configured.
    """
    try:
        deploy_dir = server_info["deploy_dir"]
        branch = server_info.get("branch", "main")
        clone_url = server_info.get("clone_url")
        create_dir = server_info.get("create_dir", False)
        force_rebuild = server_info.get("force_rebuild", False)
        use_sudo = server_info.get("sudo", False)  # Read sudo flag from config

        _ensure_local_repo(deploy_dir, clone_url, create_dir, branch)

        # Step 2: Git Pull
        git_cmd = f"git pull origin {branch}"
        out, err = run_command(git_cmd, cwd=deploy_dir)
        logger.info(out)

        # Step 3: Rebuild if needed.
        if "Already up to date." not in out or force_rebuild:
            docker_prefix = "sudo " if use_sudo else ""
            # Execute docker-compose down and up commands using run_command.
            down_cmd = f"cd {deploy_dir} && {docker_prefix}docker-compose down --remove-orphans"
            logger.info(f"Running local down command: {down_cmd}")
            run_command(down_cmd, cwd=deploy_dir)

            up_cmd = f"cd {deploy_dir} && {docker_prefix}docker-compose up -d --build --remove-orphans"
            logger.info(f"Running local up command: {up_cmd}")
            run_command(up_cmd, cwd=deploy_dir)
        else:
            logger.info("No changes found locally, skipping Docker rebuild.")

        notifier.notify_deploy_event(repo_name, push_branch, "successful", "Local deployment completed.")
    except Exception as e:
        logger.error(f"Local deploy error: {e}")
        notifier.notify_deploy_event(repo_name, push_branch, "failed", str(e))
        raise


def _ensure_local_repo(deploy_dir: str, clone_url: str, create_dir: bool, branch: str):
    """
    Checks if 'deploy_dir' exists locally. If not:
      - If create_dir is False: raise an error.
      - If create_dir is True: 'git clone' from clone_url into that path.
    """
    if os.path.isdir(deploy_dir):
        logger.info(f"Local directory '{deploy_dir}' already exists.")
        return

    if not create_dir:
        msg = (
            f"Directory '{deploy_dir}' does not exist locally. "
            f"Set 'create_dir: true' if you want to attempt creating and cloning the repository."
        )
        raise FileNotFoundError(msg)

    if not clone_url:
        raise ValueError(f"'clone_url' is not specified, cannot clone into '{deploy_dir}'.")

    parent_dir = os.path.dirname(deploy_dir)
    if parent_dir and not os.path.isdir(parent_dir):
        logger.info(f"Creating local parent directory: {parent_dir}")
        os.makedirs(parent_dir, exist_ok=True)

    clone_cmd = f"git clone --branch {branch} {clone_url} \"{deploy_dir}\""
    logger.info(f"Local directory '{deploy_dir}' not found. Cloning: {clone_cmd}")
    run_command(clone_cmd, cwd=parent_dir or ".")


# -------------------------------------------------------------------
# REMOTE DEPLOY
# -------------------------------------------------------------------
def deploy_remote(server_info, repo_name, push_branch, notifier):
    """
    1) Ensure the repo directory is present on remote or clone if needed.
    2) Git pull from the existing directory.
    3) If changes found or force_rebuild, perform docker-compose down/up with sudo if configured.
    """
    host = server_info["host"]
    port = server_info.get("port", 22)
    user = server_info["user"]
    key_type = server_info.get("key_type", "pem")
    key_path = server_info["key_path"]
    branch = server_info.get("branch", "main")
    deploy_dir = server_info["deploy_dir"]
    clone_url = server_info.get("clone_url")
    create_dir = server_info.get("create_dir", False)
    force_rebuild = server_info.get("force_rebuild", False)
    use_sudo = server_info.get("sudo", False)  # Read sudo flag from config

    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Load private key based on key type.
    if key_type.lower() == "pem":
        private_key = paramiko.RSAKey.from_private_key_file(key_path)
    elif key_type.lower() == "ppk":
        private_key = paramiko.RSAKey.from_private_key_file(key_path)
    else:
        raise ValueError(f"Unsupported key_type '{key_type}'. Use 'pem' or 'ppk'.")

    try:
        ssh_client.connect(hostname=host, port=port, username=user, pkey=private_key, timeout=15)
        logger.info(f"SSH connected to {host} as {user}")

        _ensure_remote_repo(ssh_client, deploy_dir, clone_url, create_dir, branch)

        # Step 2: Git pull.
        pull_cmd = f"cd {deploy_dir} && git pull origin {branch}"
        pull_output = _exec_ssh_command(ssh_client, pull_cmd)
        logger.debug(f"Remote pull output: {pull_output}")

        do_rebuild = force_rebuild or ("Already up to date." not in pull_output)
        if do_rebuild:
            logger.info("Remote changes found OR force_rebuild=True -> taking down containers & rebuilding...")
        else:
            logger.info("No changes found on remote, skipping Docker rebuild...")

        # Detect docker-compose binary.
        docker_compose_bin = _detect_docker_compose_binary(ssh_client)

        # Use the sudo prefix from config, or fallback on OS detection if not set.
        if use_sudo:
            docker_prefix = "sudo "
        else:
            os_type = _exec_ssh_command(ssh_client, "uname -s").strip()
            docker_prefix = "sudo " if "Linux" in os_type else ""

        if do_rebuild:
            down_cmd = f"cd {deploy_dir} && {docker_prefix}{docker_compose_bin} down --remove-orphans"
            _exec_ssh_command(ssh_client, down_cmd, allow_benign_errors=True)
            up_cmd = f"cd {deploy_dir} && {docker_prefix}{docker_compose_bin} up -d --build --remove-orphans"
            _exec_ssh_command(ssh_client, up_cmd)
        else:
            up_cmd = f"cd {deploy_dir} && {docker_prefix}{docker_compose_bin} up -d"
            _exec_ssh_command(ssh_client, up_cmd)

        notifier.notify_deploy_event(repo_name, push_branch, "successful", f"Remote server {host} updated.")
    except Exception as e:
        logger.error(f"Remote deploy error on {host}: {e}")
        notifier.notify_deploy_event(repo_name, push_branch, "failed", str(e))
        raise
    finally:
        ssh_client.close()
        logger.info(f"SSH disconnected from {host}")


def _ensure_remote_repo(ssh_client, deploy_dir: str, clone_url: str, create_dir: bool, branch: str):
    """
    Checks if 'deploy_dir' exists on remote. If not:
      - If create_dir is False, raise an error.
      - If create_dir is True, 'git clone' from clone_url into that path.
    """
    check_cmd = f'[ -d "{deploy_dir}" ] && echo "EXISTS" || echo "NOT_EXISTS"'
    result = _exec_ssh_command(ssh_client, check_cmd).strip()
    if result == "EXISTS":
        logger.info(f"Remote directory '{deploy_dir}' already exists.")
        return

    if not create_dir:
        msg = (
            f"Directory '{deploy_dir}' does not exist on remote. "
            f"Set 'create_dir: true' to attempt cloning the repository."
        )
        raise FileNotFoundError(msg)

    if not clone_url:
        raise ValueError(f"'clone_url' is not specified, cannot clone into '{deploy_dir}'.")

    parent_dir = os.path.dirname(deploy_dir)
    if parent_dir:
        mk_parent = f'mkdir -p "{parent_dir}"'
        logger.info(f"Creating remote parent directory: {parent_dir}")
        _exec_ssh_command(ssh_client, mk_parent)

    clone_cmd = f'cd "{parent_dir or "/"}" && git clone --branch {branch} {clone_url} "{deploy_dir}"'
    logger.info(f"Remote directory '{deploy_dir}' not found. Cloning with command: {clone_cmd}")
    _exec_ssh_command(ssh_client, clone_cmd)


def _detect_docker_compose_binary(ssh_client) -> str:
    """
    Checks for 'docker compose' vs 'docker-compose' on the remote machine.
    Returns whichever is found first.
    """
    try:
        _exec_ssh_command(ssh_client, "which docker", timeout=5)
        version_out = _exec_ssh_command(ssh_client, "docker compose version", timeout=5)
        if "Docker Compose version" in version_out:
            return "docker compose"
    except Exception as e:
        logger.debug(f"'docker compose' not found or not working: {e}")

    try:
        _exec_ssh_command(ssh_client, "which docker-compose", timeout=5)
        return "docker-compose"
    except Exception:
        pass

    raise RuntimeError("Neither 'docker compose' nor 'docker-compose' found on the remote system.")


# -------------------------------------------------------------------
# TASKS
# -------------------------------------------------------------------
def run_local_tasks(tasks, cwd, notifier, repo_name, push_branch):
    for cmd in tasks:
        try:
            out, err = run_command(cmd, cwd=cwd)
            if out:
                logger.info(out)
            if err:
                logger.warning(err)
        except Exception as e:
            logger.error(f"Error running local task '{cmd}': {e}")
            notifier.notify_deploy_event(repo_name, push_branch, "failed", f"Task '{cmd}' failed.")
            raise


def run_remote_tasks(tasks, server_info, notifier, repo_name, push_branch):
    host = server_info["host"]
    port = server_info.get("port", 22)
    user = server_info["user"]
    key_path = server_info["key_path"]

    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        private_key = paramiko.RSAKey.from_private_key_file(key_path)
        ssh_client.connect(hostname=host, port=port, username=user, pkey=private_key, timeout=15)

        for cmd in tasks:
            try:
                _exec_ssh_command(ssh_client, cmd)
            except Exception as e:
                logger.error(f"Error running remote task '{cmd}' on {host}:{port}: {e}")
                notifier.notify_deploy_event(repo_name, push_branch, "failed", f"Remote task '{cmd}' failed.")
                raise
    finally:
        ssh_client.close()


def _exec_ssh_command(ssh_client, cmd, timeout=30, allow_benign_errors=False):
    """
    Execute an SSH command and return its combined stdout as a string.
    Raises RuntimeError if the command fails (unless the error is benign).
    """
    stdin, stdout, stderr = ssh_client.exec_command(cmd, timeout=timeout)

    output_lines = []
    error_lines = []

    while not stdout.channel.exit_status_ready():
        if stdout.channel.recv_ready():
            output = stdout.channel.recv(1024).decode()
            output_lines.append(output)
            logger.info(f"[SSH STDOUT] {output.strip()}")

        if stderr.channel.recv_ready():
            error = stderr.channel.recv(1024).decode()
            error_lines.append(error)
            logger.warning(f"[SSH STDERR] {error.strip()}")

    exit_status = stdout.channel.recv_exit_status()
    full_error_output = "".join(error_lines).strip()

    if exit_status != 0:
        benign_markers = [
            "No container found",
            "No containers to remove",
            "has active endpoints",
        ]
        if allow_benign_errors and any(marker in full_error_output for marker in benign_markers):
            logger.warning(f"Ignoring benign error while running '{cmd}': {full_error_output}")
        else:
            raise RuntimeError(
                f"Command '{cmd}' failed with exit code {exit_status}. Error: {full_error_output}"
            )

    return "".join(output_lines).strip()

# # Filename: deploy_chain.py
#
# import logging
# import os
# import paramiko
# from utils import run_command, restart_containers
#
# logger = logging.getLogger(__name__)
#
#
# def deploy_chain(repo_name: str, push_branch: str, servers_config: dict, notifier):
#     """
#     Iterates over server1, server2, ... in servers_config
#     and deploys each one sequentially.
#     """
#     server_keys = sorted(servers_config.keys())
#     for server_key in server_keys:
#         server_info = servers_config[server_key]
#         logger.info(f"=== Deploying {server_key} for repo '{repo_name}' ===")
#
#         # Skip non-"serverX" keys
#         if not server_key.startswith("server"):
#             logger.info(f"Skipping '{server_key}' as it's not recognized as a server definition.")
#             continue
#
#         target = server_info.get("target")
#         config_branch = server_info.get("branch", "main")
#         if push_branch != config_branch:
#             msg = f"Push branch '{push_branch}' does not match '{config_branch}'. Skipping {server_key}."
#             logger.info(msg)
#             notifier.notify_deploy_event(repo_name, push_branch, "ignored", msg)
#             continue
#
#         try:
#             # Deploy
#             if target == "local":
#                 deploy_local(server_info, repo_name, push_branch, notifier)
#             elif target == "remote":
#                 deploy_remote(server_info, repo_name, push_branch, notifier)
#             else:
#                 msg = f"Unknown target '{target}' for {server_key}. Skipping."
#                 logger.warning(msg)
#                 notifier.notify_deploy_event(repo_name, push_branch, "failed", msg)
#                 continue
#
#             # Optional additional tasks
#             tasks = server_info.get("additional_terminal_tasks", [])
#             if tasks:
#                 if target == "local":
#                     run_local_tasks(tasks, server_info.get("deploy_dir"), notifier, repo_name, push_branch)
#                 else:
#                     run_remote_tasks(tasks, server_info, notifier, repo_name, push_branch)
#
#             logger.info(f"=== Finished {server_key} ===\n")
#         except Exception as e:
#             # If any error happens for this server, log it. (You can re-raise if desired.)
#             logger.error(f"Deployment failed on {server_key}: {e}")
#             # raise  # <- Uncomment if you want to stop the entire chain on first error.
#
#
# # -------------------------------------------------------------------
# # LOCAL DEPLOY
# # -------------------------------------------------------------------
# def deploy_local(server_info, repo_name, push_branch, notifier):
#     """
#     1) Ensure the repo directory is present or create/clone it.
#     2) Perform 'git pull' from that directory.
#     3) If changes found or force_rebuild, rebuild containers.
#     """
#     try:
#         deploy_dir = server_info["deploy_dir"]
#         branch = server_info.get("branch", "main")
#         clone_url = server_info.get("clone_url")
#         create_dir = server_info.get("create_dir", False)
#         force_rebuild = server_info.get("force_rebuild", False)
#
#         _ensure_local_repo(deploy_dir, clone_url, create_dir, branch)
#
#         # Step 2: Git Pull
#         git_cmd = f"git pull origin {branch}"
#         out, err = run_command(git_cmd, cwd=deploy_dir)
#         logger.info(out)
#
#         # Step 3: Rebuild if needed
#         if "Already up to date." not in out or force_rebuild:
#             restart_containers(deploy_dir)  # calls docker-compose down/up internally
#         else:
#             logger.info("No changes found locally, skipping Docker rebuild.")
#
#         notifier.notify_deploy_event(repo_name, push_branch, "successful", "Local deployment completed.")
#     except Exception as e:
#         logger.error(f"Local deploy error: {e}")
#         notifier.notify_deploy_event(repo_name, push_branch, "failed", str(e))
#         raise
#
#
# def _ensure_local_repo(deploy_dir: str, clone_url: str, create_dir: bool, branch: str):
#     """
#     Checks if 'deploy_dir' exists locally. If not:
#       - If create_dir is False: raise an error.
#       - If create_dir is True: 'git clone' from clone_url into that path.
#     """
#     if os.path.isdir(deploy_dir):
#         logger.info(f"Local directory '{deploy_dir}' already exists.")
#         return
#
#     if not create_dir:
#         msg = (
#             f"Directory '{deploy_dir}' does not exist locally. "
#             f"Set 'create_dir: true' if you want to attempt creating and cloning the repository."
#         )
#         raise FileNotFoundError(msg)
#
#     if not clone_url:
#         raise ValueError(f"'clone_url' is not specified, cannot clone into '{deploy_dir}'.")
#
#     # Attempt to create parent dirs if needed
#     parent_dir = os.path.dirname(deploy_dir)
#     if parent_dir and not os.path.isdir(parent_dir):
#         logger.info(f"Creating local parent directory: {parent_dir}")
#         os.makedirs(parent_dir, exist_ok=True)
#
#     # 'git clone <URL> <deploy_dir>'
#     clone_cmd = f"git clone --branch {branch} {clone_url} \"{deploy_dir}\""
#     logger.info(f"Local directory '{deploy_dir}' not found. Cloning: {clone_cmd}")
#     run_command(clone_cmd, cwd=parent_dir or ".")
#
#
# # -------------------------------------------------------------------
# # REMOTE DEPLOY
# # -------------------------------------------------------------------
# def deploy_remote(server_info, repo_name, push_branch, notifier):
#     """
#     1) Ensure the repo directory is present on remote or clone if needed.
#     2) Git pull from the existing directory.
#     3) If changes found or force_rebuild, docker-compose down/up with sudo if needed.
#     """
#     host = server_info["host"]
#     port = server_info.get("port", 22)
#     user = server_info["user"]
#     key_type = server_info.get("key_type", "pem")
#     key_path = server_info["key_path"]
#     branch = server_info.get("branch", "main")
#     deploy_dir = server_info["deploy_dir"]
#     clone_url = server_info.get("clone_url")
#     create_dir = server_info.get("create_dir", False)
#     force_rebuild = server_info.get("force_rebuild", False)
#
#     # Prepare SSH
#     ssh_client = paramiko.SSHClient()
#     ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
#
#     # Load private key
#     if key_type.lower() == "pem":
#         private_key = paramiko.RSAKey.from_private_key_file(key_path)
#     elif key_type.lower() == "ppk":
#         private_key = paramiko.RSAKey.from_private_key_file(key_path)
#     else:
#         raise ValueError(f"Unsupported key_type '{key_type}'. Use 'pem' or 'ppk'.")
#
#     try:
#         ssh_client.connect(hostname=host, port=port, username=user, pkey=private_key, timeout=15)
#         logger.info(f"SSH connected to {host} as {user}")
#
#         # Step 1: Ensure repo directory
#         _ensure_remote_repo(ssh_client, deploy_dir, clone_url, create_dir, branch)
#
#         # Step 2: Git pull
#         pull_cmd = f"cd {deploy_dir} && git pull origin {branch}"
#         pull_output = _exec_ssh_command(ssh_client, pull_cmd)
#         logger.debug(f"Remote pull output: {pull_output}")
#
#         # Step 3: Docker compose
#         do_rebuild = force_rebuild or ("Already up to date." not in pull_output)
#         if do_rebuild:
#             logger.info("Remote changes found OR force_rebuild=True -> taking down containers & rebuilding...")
#         else:
#             logger.info("No changes found on remote, skipping Docker rebuild...")
#
#         # Detect which docker-compose tool is installed (docker-compose vs docker compose)
#         docker_compose_bin = _detect_docker_compose_binary(ssh_client)
#
#         # Check OS to see if we need sudo
#         os_type = _exec_ssh_command(ssh_client, "uname -s").strip()
#         docker_prefix = ""
#         if "Linux" in os_type:
#             docker_prefix = "sudo "
#
#         if do_rebuild:
#             # docker-compose down
#             down_cmd = f"cd {deploy_dir} && {docker_prefix}{docker_compose_bin} down --remove-orphans"
#             _exec_ssh_command(ssh_client, down_cmd, allow_benign_errors=True)
#             # docker-compose up --build
#             up_cmd = f"cd {deploy_dir} && {docker_prefix}{docker_compose_bin} up -d --build --remove-orphans"
#             _exec_ssh_command(ssh_client, up_cmd)
#         else:
#             # docker-compose up
#             up_cmd = f"cd {deploy_dir} && {docker_prefix}{docker_compose_bin} up -d"
#             _exec_ssh_command(ssh_client, up_cmd)
#
#         notifier.notify_deploy_event(repo_name, push_branch, "successful", f"Remote server {host} updated.")
#     except Exception as e:
#         logger.error(f"Remote deploy error on {host}: {e}")
#         notifier.notify_deploy_event(repo_name, push_branch, "failed", str(e))
#         raise
#     finally:
#         ssh_client.close()
#         logger.info(f"SSH disconnected from {host}")
#
#
# def _ensure_remote_repo(ssh_client, deploy_dir: str, clone_url: str, create_dir: bool, branch: str):
#     """
#     Checks if 'deploy_dir' exists on remote. If not:
#       - If create_dir is False, raise an error.
#       - If create_dir is True, git clone from clone_url into that path.
#     """
#     check_cmd = f'[ -d "{deploy_dir}" ] && echo "EXISTS" || echo "NOT_EXISTS"'
#     result = _exec_ssh_command(ssh_client, check_cmd).strip()
#     if result == "EXISTS":
#         logger.info(f"Remote directory '{deploy_dir}' already exists.")
#         return
#
#     if not create_dir:
#         msg = (
#             f"Directory '{deploy_dir}' does not exist on remote. "
#             f"Set 'create_dir: true' to attempt cloning the repository."
#         )
#         raise FileNotFoundError(msg)
#
#     if not clone_url:
#         raise ValueError(f"'clone_url' is not specified, cannot clone into '{deploy_dir}'.")
#
#     # Create parent directory if needed
#     parent_dir = os.path.dirname(deploy_dir)
#     if parent_dir:
#         mk_parent = f'mkdir -p "{parent_dir}"'
#         logger.info(f"Creating remote parent directory: {parent_dir}")
#         _exec_ssh_command(ssh_client, mk_parent)
#
#     # Git clone
#     clone_cmd = f'cd "{parent_dir or "/"}" && git clone --branch {branch} {clone_url} "{deploy_dir}"'
#     logger.info(f"Remote directory '{deploy_dir}' not found. Cloning with command: {clone_cmd}")
#     _exec_ssh_command(ssh_client, clone_cmd)
#
#
# # -------------------------------------------------------------------
# # HELPERS: Docker Compose Detection
# # -------------------------------------------------------------------
# def _detect_docker_compose_binary(ssh_client) -> str:
#     """
#     Checks for 'docker compose' vs 'docker-compose' on the remote machine.
#     Returns whichever is found first (prefers 'docker compose' if possible).
#     Raises an error if neither is installed.
#     """
#     # Try 'docker compose' (v2) first
#     try:
#         _exec_ssh_command(ssh_client, "which docker", timeout=5)
#         version_out = _exec_ssh_command(ssh_client, "docker compose version", timeout=5)
#         if "Docker Compose version" in version_out:
#             return "docker compose"
#     except Exception as e:
#         logger.debug(f"'docker compose' not found or not working: {e}")
#
#     # Fallback to 'docker-compose' (v1)
#     try:
#         _exec_ssh_command(ssh_client, "which docker-compose", timeout=5)
#         return "docker-compose"
#     except Exception:
#         pass
#
#     # If neither is found, raise an error
#     raise RuntimeError("Neither 'docker compose' nor 'docker-compose' found on the remote system.")
#
#
# # -------------------------------------------------------------------
# # TASKS
# # -------------------------------------------------------------------
# def run_local_tasks(tasks, cwd, notifier, repo_name, push_branch):
#     for cmd in tasks:
#         try:
#             out, err = run_command(cmd, cwd=cwd)
#             if out:
#                 logger.info(out)
#             if err:
#                 logger.warning(err)
#         except Exception as e:
#             logger.error(f"Error running local task '{cmd}': {e}")
#             notifier.notify_deploy_event(repo_name, push_branch, "failed", f"Task '{cmd}' failed.")
#             raise
#
#
# def run_remote_tasks(tasks, server_info, notifier, repo_name, push_branch):
#     host = server_info["host"]
#     port = server_info.get("port", 22)
#     user = server_info["user"]
#     key_path = server_info["key_path"]
#
#     ssh_client = paramiko.SSHClient()
#     ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
#
#     try:
#         private_key = paramiko.RSAKey.from_private_key_file(key_path)
#         ssh_client.connect(hostname=host, port=port, username=user, pkey=private_key, timeout=15)
#
#         for cmd in tasks:
#             try:
#                 _exec_ssh_command(ssh_client, cmd)
#             except Exception as e:
#                 logger.error(f"Error running remote task '{cmd}' on {host}:{port}: {e}")
#                 notifier.notify_deploy_event(repo_name, push_branch, "failed", f"Remote task '{cmd}' failed.")
#                 raise
#     finally:
#         ssh_client.close()
#
#
# # -------------------------------------------------------------------
# # SSH Utility
# # -------------------------------------------------------------------
# def _exec_ssh_command(ssh_client, cmd, timeout=30, allow_benign_errors=False):
#     """
#     Execute an SSH command and return its combined stdout as a string.
#     If the command fails with a non-zero exit code, raise RuntimeError
#     unless we detect known benign errors (when allow_benign_errors=True).
#     """
#     stdin, stdout, stderr = ssh_client.exec_command(cmd, timeout=timeout)
#
#     output_lines = []
#     error_lines = []
#
#     # Continuously read from stdout/stderr until command completes
#     while not stdout.channel.exit_status_ready():
#         if stdout.channel.recv_ready():
#             output = stdout.channel.recv(1024).decode()
#             output_lines.append(output)
#             logger.info(f"[SSH STDOUT] {output.strip()}")
#
#         if stderr.channel.recv_ready():
#             error = stderr.channel.recv(1024).decode()
#             error_lines.append(error)
#             logger.warning(f"[SSH STDERR] {error.strip()}")
#
#     exit_status = stdout.channel.recv_exit_status()
#     full_error_output = "".join(error_lines).strip()
#
#     if exit_status != 0:
#         # Check if we should ignore known "benign" errors
#         benign_markers = [
#             "No container found",
#             "No containers to remove",
#             "has active endpoints",
#         ]
#         if allow_benign_errors and any(marker in full_error_output for marker in benign_markers):
#             logger.warning(f"Ignoring benign error while running '{cmd}': {full_error_output}")
#         else:
#             raise RuntimeError(
#                 f"Command '{cmd}' failed with exit code {exit_status}. "
#                 f"Error: {full_error_output}"
#             )
#
#     return "".join(output_lines).strip()
