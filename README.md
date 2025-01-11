
# WebHookX
<img src="logo.webp" alt="WebHookX Logo (The Logo Made with AI)" width="160px">


WebHookX is a simple yet powerful tool for automating deployments of your GitHub repositories. It works with GitHub webhooks to make updating your staging or production environments a breeze. Whether you’re managing Docker services, keeping branches in sync, or triggering manual deployments, WebHookX has your back.


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

If you run into any issues or have questions, feel free to [open an issue](https://github.com/georgekhananaev/webhookx/issues) or email us at `support@webhookx.io`. We’re here to help!


## Support Me

If you find my work helpful, consider supporting me by buying me a coffee at [Buy Me A Coffee](https://www.buymeacoffee.com/georgekhananaev).
Your support helps me continue to create and maintain useful projects.

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/georgekhananaev)

Thank you!