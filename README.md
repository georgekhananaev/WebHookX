
# WebHookX
<img src="logo.webp" alt="WebHookX Logo (The Logo Made with AI)" width="160px">

WebHookX is a flexible deployment automation tool designed to simplify workflows. It integrates seamlessly with GitHub webhooks for automatic updates to staging or production environments with flexible logic and also supports manual deployments through API calls. With the ability to deploy across multiple servers—local or remote—it provides a robust framework for managing complex deployment scenarios. WebHookX allows chaining deployment events, executing custom commands post-deployment, and is built on Docker Compose, ensuring compatibility with modern CI/CD pipelines. Its modular design makes it suitable for automating diverse deployment processes efficiently and reliably.

_**Note:** WebHookX is under active development and may still contain bugs and incomplete logic. Ongoing improvements aim to enhance its stability, functionality, and overall reliability over time._

---

## Features

- **Automatic Deployments**: Set it up once, and WebHookX will handle deployments every time you push to GitHub.
- **Branch Filtering**: Only deploy from branches you care about to avoid unintended updates.
- **Docker Integration**: Automatically rebuild and restart Docker services with your code changes.
- **Manual Deployments**: Kick off a deployment anytime with a secure API.
- **Secure API Keys**: Protect access to deployments with API key authentication.
- **Logs You Can Count On**: Every step is logged in a lightweight SQLite database so you can debug and track deployments easily.
- **Notifications**: Get instant updates via Slack and email about deployment successes or failures.

---

## What You’ll Need

- **Python 3.8+**: WebHookX is built in Python, so you’ll need it installed.
- **FastAPI**: The framework powering WebHookX.
- **Docker (Optional)**: Recommended if you’re working with containerized applications.
- **Git**: For pulling changes from your repositories.

---

## Getting Started

### 1. Clone the Repository

Start by cloning the WebHookX repository:

```bash
git clone https://github.com/georgekhananaev/webhookx.git
cd webhookx
```

### 2. Install Dependencies

Use pip to install everything you need:

```bash
pip install -r requirements.txt
```

### 3. Configure WebHookX

Copy the example config file and update it:

```bash
cp config.yaml.example config.yaml
```

Edit `config.yaml` to include your webhook secrets, repository mappings, and notification settings. Here’s a quick example:

```yaml
# GitHub Webhook Secret
github_webhook_secret: "your-webhook-secret"

# Repository Deployment Map
repo_deploy_map:
  "your-username/your-repo":
    deploy_dir: "/path/to/deploy"
    branch: "main"
    force_rebuild: true

# Notifications
notifications:
  slack:
    webhook_url: "https://hooks.slack.com/services/your/slack/webhook"
    channel: "#deployments"
    username: "WebHookX Bot"
  email:
    enabled: true
    smtp_server: "smtp.gmail.com"
    smtp_port: 465
    use_ssl: true
    username: "your-email@gmail.com"
    password: "your-email-password"
    from_addr: "webhookx@example.com"
    to_addrs:
      - "recipient1@example.com"
      - "recipient2@example.com"
```

### 4. Run the App

Fire up WebHookX using Uvicorn:

```bash
uvicorn main:app --reload
```

---

## How It Works

### Health Check

Make sure WebHookX is running:

```bash
GET /health
```

### GitHub Webhook Integration

Set up a webhook in your GitHub repository to point to:

```
POST /webhook
```

WebHookX will automatically handle deployments when it receives a webhook event.

### Manual Deployment

Trigger a deployment anytime using the API:

```bash
POST /deploy
Headers:
  X-API-Key: your-deploy-api-key
Body (JSON):
{
  "repository_full_name": "your-username/your-repo",
  "branch": "main"
}
```

### Notifications

- **Slack**: Get updates directly in your Slack channel. Make sure to configure your `webhook_url` in `config.yaml`.
- **Email**: Receive email notifications for deployment statuses. Set `enabled: true` and provide SMTP settings in `config.yaml`.

---

## Usage and Variables Documentation

### Global Configuration

| Variable                           | Type    | Usage                                                                                                 | Example                                                       |
|------------------------------------|---------|-------------------------------------------------------------------------------------------------------|---------------------------------------------------------------|
| `github_webhook_secret`            | String  | A secure token used to verify the GitHub webhook signature. Must match the secret set in GitHub.      | `"deploy_API_key_ABC123XYZ"`                                  |
| `docker_compose_options`           | String  | Command-line options for Docker Compose (e.g., pulling images, building, running in detached mode).   | `"up -d --build --remove-orphans"`                            |
| `docker_compose_path`              | String  | The command or full path to your Docker Compose executable (e.g., if in PATH, use `"docker-compose"`).| `"docker-compose"`                                            |
| `git_branch`                       | String  | The default Git branch used when not otherwise specified in a repository configuration.               | `"main"`                                                      |
| `deploy_api_key`                   | String  | A secure API key for accessing manual deployment endpoints.                                           | `"deploy_API_key_ABC123XYZ"`                                  |
| `tests_api_key`                    | String  | A secure API key for accessing file listing or testing endpoints.                                     | `"tests_DEF456UVW"`                                           |
| `log_level`                        | String  | Sets the verbosity level for logging (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).               | `"INFO"`                                                      |
| `max_retries`                      | Integer | Number of retries for failed tasks or requests before aborting.                                       | `3`                                                           |

---

### Notifications Settings

#### Slack

| Variable                     | Type   | Usage                                                   | Example                                      |
|------------------------------|--------|---------------------------------------------------------|----------------------------------------------|
| `notifications.slack_webhook_url` | String | URL used for sending Slack notifications.                | `"https://hooks.slack.com/services/your/slack/webhook"` |

#### Email

| Property         | Type    | Usage                                                                                   | Example                     |
|-------------------|---------|-----------------------------------------------------------------------------------------|-----------------------------|
| `smtp_server`     | String  | SMTP server host.                                                                       | `"smtp.gmail.com"`          |
| `smtp_port`       | Integer | SMTP port (e.g., `465` for SSL or `587` for TLS).                                       | `465`                       |
| `use_tls`         | Boolean | Set to `true` if using TLS (typically for port 587) or `false` for SSL (port 465).      | `false`                     |
| `username`        | String  | Credentials for your email account.                                                    | `"your-email@gmail.com"`    |
| `password`        | String  | Password for your email account.                                                       | `"your-email-password"`     |
| `sender_email`    | String  | The email address used as the sender (can be the same as `username` or different).      | `"webhookx@example.com"`    |
| `recipients`      | List    | A list of email addresses to send notifications to.                                     | `["recipient1@example.com", "recipient2@example.com"]` |

---

### Repository Deployment Map (`repo_deploy_map`)

| Property                  | Type           | Usage                                                                                           | Example                                    |
|---------------------------|----------------|-------------------------------------------------------------------------------------------------|--------------------------------------------|
| `target`                  | String         | Specifies the deployment target: `local` for local execution, `remote` for remote via SSH.      | `"local"`                                  |
| `clone_url`               | String         | The Git repository URL used to pull updates. (Often includes a Personal Access Token for private repos.) | `"https://yourPAT@github.com/your/repo.git"` |
| `create_dir`              | Boolean        | Indicates whether to create the `deploy_dir` if it does not already exist.                      | `true`                                     |
| `deploy_dir`              | String         | The directory path where the repository is deployed.                                            | `"/path/to/deploy"`                        |
| `branch`                  | String         | The Git branch that triggers a deployment. Only deploys if the push event’s branch matches.     | `"main"`                                   |
| `force_rebuild`           | Boolean        | Forces Docker rebuilds even when Git reports \"Already up to date.\"                            | `true`                                     |
| `additional_terminal_tasks` | List of Strings | Extra shell commands to execute after the main deployment steps.                                | `["cd frontend && ping -n 3 google.com"]`  |

#### For Remote Targets

| Property     | Type   | Usage                                    | Example                  |
|--------------|--------|------------------------------------------|--------------------------|
| `host`       | String | The IP address or hostname of the remote server. | `"192.168.1.10"`         |
| `port`       | Integer| The SSH port to connect to.              | `22`                     |
| `user`       | String | The SSH username.                       | `"ubuntu"`               |
| `key_type`   | String | The type of SSH private key: `"pem"` or `"ppk"`. | `"pem"`                  |
| `key_path`   | String | The file path to the SSH private key.    | `"/path/to/key.pem"`     |

## Logs

WebHookX stores logs in a local SQLite database (`logs.db`). This keeps everything lightweight and easy to manage.

### Viewing Logs

To view logs, use any SQLite tool or run:

```bash
sqlite3 logs.db

# Inside SQLite
.tables
SELECT * FROM logs;
```

---

## Contributing 🤝

We’d love your help to make WebHookX even better! To contribute:

1. Fork the repository.
2. Create a new branch for your feature: `git checkout -b feature-name`.
3. Commit your changes: `git commit -m "Add awesome feature"`.
4. Push your branch: `git push origin feature-name`.
5. Open a pull request and tell us about your changes.

---

## License

WebHookX is licensed under the MIT License. See the `LICENSE` file for details.

---

## Need Help?

If you run into any issues or have questions, feel free to [open an issue](https://github.com/georgekhananaev/webhookx/issues).


## Support Me

If you find my work helpful, consider supporting me by buying me a coffee at [Buy Me A Coffee](https://www.buymeacoffee.com/georgekhananaev).
Your support helps me continue to create and maintain useful projects.

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/georgekhananaev)

Thank you!
