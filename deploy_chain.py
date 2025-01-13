# deploy_chain.py

import logging
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

        if target == "local":
            deploy_local(server_info, repo_name, push_branch, notifier)
        elif target == "remote":
            deploy_remote(server_info, repo_name, push_branch, notifier)
        else:
            msg = f"Unknown target '{target}' for {server_key}. Skipping."
            logger.warning(msg)
            notifier.notify_deploy_event(repo_name, push_branch, "failed", msg)
            continue

        tasks = server_info.get("additional_terminal_tasks", [])
        if tasks:
            if target == "local":
                run_local_tasks(tasks, server_info.get("deploy_dir"), notifier, repo_name, push_branch)
            else:
                run_remote_tasks(tasks, server_info, notifier, repo_name, push_branch)

        logger.info(f"=== Finished {server_key} ===\n")


def deploy_local(server_info, repo_name, push_branch, notifier):
    try:
        deploy_dir = server_info["deploy_dir"]
        branch = server_info.get("branch", "main")
        force_rebuild = server_info.get("force_rebuild", False)

        git_cmd = f"git pull origin {branch}"
        out, err = run_command(git_cmd, cwd=deploy_dir)
        logger.info(out)

        if "Already up to date." not in out or force_rebuild:
            restart_containers(deploy_dir)
        else:
            logger.info("No changes found, skipping Docker rebuild.")

        notifier.notify_deploy_event(repo_name, push_branch, "successful", "Local deployment completed.")
    except Exception as e:
        logger.error(f"Local deploy error: {e}")
        notifier.notify_deploy_event(repo_name, push_branch, "failed", str(e))
        raise


def deploy_remote(server_info, repo_name, push_branch, notifier):
    """
    SSH into remote server, run git pull + docker logic, etc.
    """
    import logging
    import paramiko

    logger = logging.getLogger(__name__)

    host = server_info["host"]
    user = server_info["user"]
    key_type = server_info.get("key_type", "pem")
    key_path = server_info["key_path"]
    branch = server_info.get("branch", "main")
    deploy_dir = server_info["deploy_dir"]
    force_rebuild = server_info.get("force_rebuild", False)

    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Load private key
    if key_type.lower() == "pem":
        private_key = paramiko.RSAKey.from_private_key_file(key_path)
    elif key_type.lower() == "ppk":
        private_key = paramiko.RSAKey.from_private_key_file(key_path)  # Use .ppk as is
    else:
        raise ValueError(f"Unsupported key_type '{key_type}'. Use 'pem' or 'ppk'.")

    try:
        ssh_client.connect(hostname=host, username=user, pkey=private_key, timeout=15)
        logger.info(f"SSH connected to {host} as {user}")

        # 1) Git pull
        git_cmd = f"cd {deploy_dir} && git pull origin {branch}"
        pull_output = _exec_ssh_command(ssh_client, git_cmd)  # Capture output
        logger.debug(f"Remote pull output: {pull_output}")

        # 2) Determine if we should do a full Docker rebuild (down + up --build)
        #    or just skip it. This matches your local logic:
        #    - If "Already up to date." is NOT found or force_rebuild is True, do a rebuild
        #    - Otherwise skip.
        do_rebuild = force_rebuild or ("Already up to date." not in pull_output)

        if do_rebuild:
            logger.info("Remote changes found OR force_rebuild=True -> Taking down containers & rebuilding...")
        else:
            logger.info("No changes found on remote, skipping Docker rebuild...")

        # Check if Linux for sudo
        os_check_cmd = "uname -s"
        stdin, stdout, stderr = ssh_client.exec_command(os_check_cmd)
        os_type = stdout.read().decode().strip()
        docker_prefix = "sudo " if os_type == "Linux" else ""

        if do_rebuild:
            # EXACT same logic as local "restart_containers":
            # Step A: docker-compose down
            down_cmd = f"cd {deploy_dir} && {docker_prefix}docker-compose down --remove-orphans"
            _exec_ssh_command(ssh_client, down_cmd)

            # Step B: docker-compose up -d --build
            up_cmd = f"cd {deploy_dir} && {docker_prefix}docker-compose up -d --build --remove-orphans"
            _exec_ssh_command(ssh_client, up_cmd)
        else:
            # If skipping rebuild, at least ensure containers are up:
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
    port = server_info.get("port", 22)  # Default to port 22 if not provided
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


def _exec_ssh_command(ssh_client, cmd, timeout=30):
    """
    Execute an SSH command and return its output. Handle commands that produce continuous or large output.
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

    if exit_status != 0:
        raise RuntimeError(
            f"Command '{cmd}' failed with exit code {exit_status}. "
            f"Error: {''.join(error_lines).strip()}"
        )

    return "".join(output_lines).strip()