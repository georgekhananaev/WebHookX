# notifications.py

import smtplib
import requests
import yaml
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)


def load_config(path: str) -> dict:
    """
    Load configuration from a YAML file.
    """
    try:
        with open(path, 'r') as file:
            config = yaml.safe_load(file)
            logger.debug(f"Loaded config: {config}")
            return config
    except FileNotFoundError:
        logger.error(f"Configuration file '{path}' not found.")
    except yaml.YAMLError as e:
        logger.error(f"YAML error while parsing the config file: {e}")
    except Exception as e:
        logger.error(f"Unexpected error loading config file: {e}")
    return {}


class Notifications:
    def __init__(self, config_path: str = 'config.yaml'):
        self.config = load_config(config_path)
        self.slack_webhook_url = self.config.get('notifications', {}).get('slack_webhook_url', "")
        email_config = self.config.get('notifications', {}).get('email', {})
        self.email_enabled = bool(email_config)

        if self.email_enabled:
            self.smtp_server = email_config.get('smtp_server')
            self.smtp_port = email_config.get('smtp_port', 587)
            self.use_tls = email_config.get('use_tls', True)
            self.username = email_config.get('username')
            self.password = email_config.get('password')
            self.sender = email_config.get('sender_email', self.username)
            self.recipients = email_config.get('recipients', [])

            logger.debug(
                f"Email Config - Server: {self.smtp_server}, Port: {self.smtp_port}, "
                f"Use TLS: {self.use_tls}, Username: {self.username}, Sender: {self.sender}, "
                f"Recipients: {self.recipients}"
            )

    def send_slack_message(self, message: str):
        """
        Send a message to Slack via a webhook URL.
        """
        if not self.slack_webhook_url:
            logger.debug("Slack webhook URL not configured. Skipping Slack notification.")
            return
        payload = {"text": message}
        try:
            response = requests.post(self.slack_webhook_url, json=payload)
            if response.status_code != 200:
                logger.error(f"Failed to send Slack message. Code: {response.status_code}, Resp: {response.text}")
            else:
                logger.info("Slack message sent successfully.")
        except requests.RequestException as e:
            logger.error(f"Exception while sending Slack message: {e}")

    def send_email(self, subject: str, body: str):
        """
        Send an email to the configured recipients.
        """
        if not self.email_enabled:
            logger.debug("Email notifications not configured. Skipping Email notification.")
            return

        if not all([self.smtp_server, self.username, self.password, self.recipients]):
            logger.error("Email configuration is incomplete. Check config.yaml.")
            return

        msg = MIMEMultipart()
        msg['From'] = self.sender
        msg['To'] = ", ".join(self.recipients)
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        try:
            if self.smtp_port == 465:
                server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            else:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10)
                server.ehlo()
                if self.use_tls:
                    server.starttls()
                    server.ehlo()

            server.login(self.username, self.password)
            server.send_message(msg)
            logger.info(f"Email sent successfully to {self.recipients} with subject '{subject}'.")

            server.quit()
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP Authentication Error: {e}")
        except smtplib.SMTPConnectError as e:
            logger.error(f"SMTP Connection Error: {e}")
        except smtplib.SMTPException as e:
            logger.error(f"SMTP Error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error while sending email: {e}")

    def notify_webhook_event(self, event: str, repo: str, branch: str, pusher: str):
        """
        Notify about a webhook event (Slack + Email).
        """
        message = (
            f"🔔 **Webhook Event**\n"
            f"- **Repository**: {repo}\n"
            f"- **Branch**: {branch}\n"
            f"- **Pusher**: {pusher}\n"
            f"- **Event**: {event}"
        )
        self.send_slack_message(message)
        subject = f"Webhook Event: {event} on {repo}"
        self.send_email(subject, message)

    def notify_deploy_event(self, repo: str, branch: str, status: str, details: Optional[str] = ""):
        """
        Notify about a deployment event (Slack + Email).
        """
        message = (
            f"🚀 **Deploy Event**\n"
            f"- **Repository**: {repo}\n"
            f"- **Branch**: {branch}\n"
            f"- **Status**: {status}\n"
            f"- **Details**: {details}"
        )
        self.send_slack_message(message)
        subject = f"Deploy Event: {status} on {repo}"
        self.send_email(subject, message)
