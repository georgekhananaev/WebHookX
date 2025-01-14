import logging
import os
import paramiko
from utils import run_command, restart_containers

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

        target = server_info.get("target")
        config_branch = server_info.get("branch", "main")
        if push_branch != config_branch:
            msg = f"Push branch '{push_branch}' does not match '{config_branch}'. Skipping {server_key}."
            logger.info(msg)
            notifier.notify_deploy_event(repo_name, push_branch, "ignored", msg)
            continue

        # Deploy
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


# -------------------------------------------------------------------
# LOCAL DEPLOY
# -------------------------------------------------------------------
def deploy_local(server_info, repo_name, push_branch, notifier):
    """
    If 'deploy_dir' does not exist:
      - If 'create_dir' is true, we attempt a 'git clone' to that directory.
      - Otherwise, raise an error.
    Then proceed with a 'git pull', and if changes exist (or force_rebuild), restart containers.
    """
    try:
        deploy_dir = server_info["deploy_dir"]
        branch = server_info.get("branch", "main")
        clone_url = server_info.get("clone_url")
        create_dir = server_info.get("create_dir", False)
        force_rebuild = server_info.get("force_rebuild", False)

        # 1) Ensure the repo directory is present or can be created if create_dir=True
        ensure_local_repo(deploy_dir, clone_url, create_dir, branch)

        # 2) Git pull from the existing directory
        git_cmd = f"git pull origin {branch}"
        out, err = run_command(git_cmd, cwd=deploy_dir)
        logger.info(out)

        # 3) If changes found or forced, rebuild containers
        if "Already up to date." not in out or force_rebuild:
            restart_containers(deploy_dir)
        else:
            logger.info("No changes found, skipping Docker rebuild.")

        notifier.notify_deploy_event(repo_name, push_branch, "successful", "Local deployment completed.")

    except Exception as e:
        logger.error(f"Local deploy error: {e}")
        notifier.notify_deploy_event(repo_name, push_branch, "failed", str(e))
        raise


def ensure_local_repo(deploy_dir: str, clone_url: str, create_dir: bool, branch: str):
    """
    Checks if 'deploy_dir' exists locally. If not:
      - If create_dir is False: raise an error.
      - If create_dir is True: 'git clone' from clone_url into that path.
    """
    if os.path.isdir(deploy_dir):
        logger.info(f"Local directory '{deploy_dir}' already exists.")
        return  # No further action needed

    if not create_dir:
        msg = (
            f"Directory '{deploy_dir}' does not exist. "
            f"Set 'create_dir: true' if you want to attempt creating and cloning the repository."
        )
        raise FileNotFoundError(msg)

    if not clone_url:
        raise ValueError(f"'clone_url' is not specified, cannot clone into '{deploy_dir}'.")

    # Attempt to create parent dirs if needed
    parent_dir = os.path.dirname(deploy_dir)
    if parent_dir and not os.path.isdir(parent_dir):
        logger.info(f"Creating local parent directory: {parent_dir}")
        os.makedirs(parent_dir, exist_ok=True)

    # 'git clone <URL> <deploy_dir>'
    clone_cmd = f"git clone --branch {branch} {clone_url} \"{deploy_dir}\""
    logger.info(f"Local directory '{deploy_dir}' not found. Cloning: {clone_cmd}")
    run_command(clone_cmd, cwd=parent_dir or ".")


# -------------------------------------------------------------------
# REMOTE DEPLOY
# -------------------------------------------------------------------
def deploy_remote(server_info, repo_name, push_branch, notifier):
    """
    If 'deploy_dir' does not exist on remote:
      - If 'create_dir' is true, 'git clone' from clone_url into that path
      - Otherwise, raise an error
    Then do a 'git pull', and restart containers if changes found or forced.
    """
    host = server_info["host"]
    user = server_info["user"]
    key_type = server_info.get("key_type", "pem")
    key_path = server_info["key_path"]
    branch = server_info.get("branch", "main")
    deploy_dir = server_info["deploy_dir"]
    clone_url = server_info.get("clone_url")
    create_dir = server_info.get("create_dir", False)
    force_rebuild = server_info.get("force_rebuild", False)

    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Load private key
    if key_type.lower() == "pem":
        private_key = paramiko.RSAKey.from_private_key_file(key_path)
    elif key_type.lower() == "ppk":
        private_key = paramiko.RSAKey.from_private_key_file(key_path)
    else:
        raise ValueError(f"Unsupported key_type '{key_type}'. Use 'pem' or 'ppk'.")

    try:
        ssh_client.connect(hostname=host, username=user, pkey=private_key, timeout=15)
        logger.info(f"SSH connected to {host} as {user}")

        # 1) Ensure the repo directory is present or clone if needed
        ensure_remote_repo(ssh_client, deploy_dir, clone_url, create_dir, branch)

        # 2) Git pull from the existing directory
        git_cmd = f"cd {deploy_dir} && git pull origin {branch}"
        pull_output = _exec_ssh_command(ssh_client, git_cmd)
        logger.debug(f"Remote pull output: {pull_output}")

        # 3) Decide if we rebuild containers
        do_rebuild = force_rebuild or ("Already up to date." not in pull_output)
        logger.info(
            "Remote changes found OR force_rebuild=True -> Taking down containers & rebuilding..."
            if do_rebuild else
            "No changes found on remote, skipping Docker rebuild..."
        )

        # 4) Docker commands
        #    Determine if we need sudo
        os_type = _exec_ssh_command(ssh_client, "uname -s")
        docker_prefix = "sudo " if "Linux" in os_type else ""

        if do_rebuild:
            down_cmd = f"cd {deploy_dir} && {docker_prefix}docker-compose down --remove-orphans"
            _exec_ssh_command(ssh_client, down_cmd, allow_benign_errors=True)

            up_cmd = f"cd {deploy_dir} && {docker_prefix}docker-compose up -d --build --remove-orphans"
            _exec_ssh_command(ssh_client, up_cmd)
        else:
            up_cmd = f"cd {deploy_dir} && {docker_prefix}docker-compose up -d"
            _exec_ssh_command(ssh_client, up_cmd)

        notifier.notify_deploy_event(repo_name, push_branch, "successful", f"Remote server {host} updated.")
    except Exception as e:
        logger.error(f"Remote deploy error on {host}: {e}")
        notifier.notify_deploy_event(repo_name, push_branch, "failed", str(e))
        raise
    finally:
        ssh_client.close()
        logger.info(f"SSH disconnected from {host}")


def ensure_remote_repo(ssh_client, deploy_dir: str, clone_url: str, create_dir: bool, branch: str):
    """
    Checks if 'deploy_dir' exists on remote. If not:
      - If create_dir is False, raise an error.
      - If create_dir is True, run 'git clone' from clone_url into that path.
    """
    # 1) Check if directory exists on remote
    check_cmd = f'[ -d "{deploy_dir}" ] && echo "EXISTS" || echo "NOT_EXISTS"'
    result = _exec_ssh_command(ssh_client, check_cmd).strip()

    if result == "EXISTS":
        logger.info(f"Remote directory '{deploy_dir}' already exists.")
        return

    # If directory does NOT exist
    if not create_dir:
        msg = (
            f"Directory '{deploy_dir}' does not exist on remote. "
            f"Set 'create_dir: true' to attempt cloning the repository."
        )
        raise FileNotFoundError(msg)

    if not clone_url:
        raise ValueError(f"'clone_url' is not specified, cannot clone into '{deploy_dir}'.")

    # 2) Create parent directory if needed
    #    e.g., for '/home/ubuntu/moonholidays-frontend', parent is '/home/ubuntu'
    parent_dir = os.path.dirname(deploy_dir)
    if parent_dir:
        mk_parent = f'mkdir -p "{parent_dir}"'
        logger.info(f"Creating remote parent directory: {parent_dir}")
        _exec_ssh_command(ssh_client, mk_parent)

    # 3) Git clone
    clone_cmd = f'cd "{parent_dir or "/"}" && git clone --branch {branch} {clone_url} "{deploy_dir}"'
    logger.info(f"Remote directory '{deploy_dir}' not found. Cloning with command: {clone_cmd}")
    _exec_ssh_command(ssh_client, clone_cmd)


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


# -------------------------------------------------------------------
# SSH Utility
# -------------------------------------------------------------------
def _exec_ssh_command(ssh_client, cmd, timeout=30, allow_benign_errors=False):
    """
    Execute an SSH command and return its output.
    If the command fails with a non-zero exit code, raise RuntimeError
    unless we detect known benign errors (when allow_benign_errors=True).
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
        # Check if we should ignore known "benign" errors
        benign_markers = [
            "No container found",
            "No containers to remove",
            "has active endpoints",
            # Add more as needed
        ]
        if allow_benign_errors and any(marker in full_error_output for marker in benign_markers):
            logger.warning(f"Ignoring benign error while running '{cmd}': {full_error_output}")
        else:
            raise RuntimeError(
                f"Command '{cmd}' failed with exit code {exit_status}. "
                f"Error: {full_error_output}"
            )

    return "".join(output_lines).strip()

# # deploy_chain.py
#
# import logging
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
#         if target == "local":
#             deploy_local(server_info, repo_name, push_branch, notifier)
#         elif target == "remote":
#             deploy_remote(server_info, repo_name, push_branch, notifier)
#         else:
#             msg = f"Unknown target '{target}' for {server_key}. Skipping."
#             logger.warning(msg)
#             notifier.notify_deploy_event(repo_name, push_branch, "failed", msg)
#             continue
#
#         tasks = server_info.get("additional_terminal_tasks", [])
#         if tasks:
#             if target == "local":
#                 run_local_tasks(tasks, server_info.get("deploy_dir"), notifier, repo_name, push_branch)
#             else:
#                 run_remote_tasks(tasks, server_info, notifier, repo_name, push_branch)
#
#         logger.info(f"=== Finished {server_key} ===\n")
#
#
# def deploy_local(server_info, repo_name, push_branch, notifier):
#     try:
#         deploy_dir = server_info["deploy_dir"]
#         branch = server_info.get("branch", "main")
#         force_rebuild = server_info.get("force_rebuild", False)
#
#         git_cmd = f"git pull origin {branch}"
#         out, err = run_command(git_cmd, cwd=deploy_dir)
#         logger.info(out)
#
#         if "Already up to date." not in out or force_rebuild:
#             restart_containers(deploy_dir)
#         else:
#             logger.info("No changes found, skipping Docker rebuild.")
#
#         notifier.notify_deploy_event(repo_name, push_branch, "successful", "Local deployment completed.")
#     except Exception as e:
#         logger.error(f"Local deploy error: {e}")
#         notifier.notify_deploy_event(repo_name, push_branch, "failed", str(e))
#         raise
#
#
# def deploy_remote(server_info, repo_name, push_branch, notifier):
#     host = server_info["host"]
#     user = server_info["user"]
#     key_type = server_info.get("key_type", "pem")
#     key_path = server_info["key_path"]
#     branch = server_info.get("branch", "main")
#     deploy_dir = server_info["deploy_dir"]
#     force_rebuild = server_info.get("force_rebuild", False)
#
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
#         ssh_client.connect(hostname=host, username=user, pkey=private_key, timeout=15)
#         logger.info(f"SSH connected to {host} as {user}")
#
#         # 1) Git pull
#         git_cmd = f"cd {deploy_dir} && git pull origin {branch}"
#         pull_output = _exec_ssh_command(ssh_client, git_cmd)
#         logger.debug(f"Remote pull output: {pull_output}")
#
#         # 2) Should we do a full Docker rebuild?
#         do_rebuild = force_rebuild or ("Already up to date." not in pull_output)
#
#         if do_rebuild:
#             logger.info("Remote changes found OR force_rebuild=True -> Taking down containers & rebuilding...")
#         else:
#             logger.info("No changes found on remote, skipping Docker rebuild...")
#
#         # Determine if we need sudo
#         os_check_cmd = "uname -s"
#         stdin, stdout, stderr = ssh_client.exec_command(os_check_cmd)
#         os_type = stdout.read().decode().strip()
#         docker_prefix = "sudo " if os_type == "Linux" else ""
#
#         if do_rebuild:
#             # Step A: docker-compose down
#             # (use allow_benign_errors=True to skip 'no containers' errors)
#             down_cmd = f"cd {deploy_dir} && {docker_prefix}docker-compose down --remove-orphans"
#             _exec_ssh_command(ssh_client, down_cmd, allow_benign_errors=True)
#
#             # Step B: docker-compose up -d --build
#             up_cmd = f"cd {deploy_dir} && {docker_prefix}docker-compose up -d --build --remove-orphans"
#             _exec_ssh_command(ssh_client, up_cmd)
#         else:
#             # If skipping rebuild, just ensure containers are up
#             up_cmd = f"cd {deploy_dir} && {docker_prefix}docker-compose up -d"
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
#     port = server_info.get("port", 22)  # Default to port 22 if not provided
#     user = server_info["user"]
#     key_path = server_info["key_path"]
#
#     ssh_client = paramiko.SSHClient()
#     ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
#
#     try:
#         private_key = paramiko.RSAKey.from_private_key_file(key_path)
#
#         ssh_client.connect(hostname=host, port=port, username=user, pkey=private_key, timeout=15)
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
# def _exec_ssh_command(ssh_client, cmd, timeout=30, allow_benign_errors=False):
#     """
#     Execute an SSH command and return its output. If the command fails with
#     a non-zero exit code, raise RuntimeError unless we detect known benign errors
#     (when allow_benign_errors=True).
#     """
#     stdin, stdout, stderr = ssh_client.exec_command(cmd, timeout=timeout)
#
#     output_lines = []
#     error_lines = []
#
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
#         # e.g. "No container found", "No containers to remove", "has active endpoints"
#         benign_markers = [
#             "No container found",
#             "No containers to remove",
#             "has active endpoints",
#             # Add more as needed
#         ]
#
#         # If we're allowed to skip these errors and the error text matches
#         if allow_benign_errors and any(marker in full_error_output for marker in benign_markers):
#             logger.warning(f"Ignoring benign error while running '{cmd}': {full_error_output}")
#         else:
#             raise RuntimeError(
#                 f"Command '{cmd}' failed with exit code {exit_status}. "
#                 f"Error: {full_error_output}"
#             )
#
#     return "".join(output_lines).strip()
