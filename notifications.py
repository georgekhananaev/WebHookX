# notification.py

import smtplib
import requests
import yaml
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

# Import and set up logging configuration
from logging_config import setup_logging

# Initialize logging
setup_logging()
logger = logging.getLogger(__name__)


def load_config(path: str) -> dict:
    """
    Load configuration from a YAML file.

    Parameters:
    - path (str): Path to the YAML configuration file.

    Returns:
    - dict: Configuration dictionary.
    """
    try:
        with open(path, 'r') as file:
            config = yaml.safe_load(file)
            logger.debug(f"Loaded config: {config}")  # Be cautious with sensitive data
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
        """
        Initialize the Notifications class by loading configurations.

        Parameters:
        - config_path (str): Path to the YAML configuration file.
        """
        self.config = load_config(config_path)
        self.slack_webhook_url = self.config.get('notifications', {}).get('slack_webhook_url')
        email_config = self.config.get('notifications', {}).get('email', {})
        self.email_enabled = bool(email_config)
        if self.email_enabled:
            self.smtp_server = email_config.get('smtp_server')
            self.smtp_port = email_config.get('smtp_port', 587)
            self.use_tls = email_config.get('use_tls', True)
            self.username = email_config.get('username')
            self.password = email_config.get('password')
            self.sender = email_config.get('sender_email', self.username)  # Allow separate sender_email
            self.recipients = email_config.get('recipients', [])
            logger.debug(
                f"Email Config - Server: {self.smtp_server}, Port: {self.smtp_port}, "
                f"Use TLS: {self.use_tls}, Username: {self.username}, Sender: {self.sender}, "
                f"Recipients: {self.recipients}"
            )

    def send_slack_message(self, message: str):
        """
        Send a message to Slack via a webhook URL.

        Parameters:
        - message (str): The message content to send.
        """
        if not self.slack_webhook_url:
            logger.debug("Slack webhook URL not configured. Skipping Slack notification.")
            return
        payload = {"text": message}
        try:
            response = requests.post(self.slack_webhook_url, json=payload)
            if response.status_code != 200:
                logger.error(
                    f"Failed to send Slack message. Status Code: {response.status_code}, Response: {response.text}")
            else:
                logger.info("Slack message sent successfully.")
        except requests.RequestException as e:
            logger.error(f"Exception while sending Slack message: {e}")

    def send_email(self, subject: str, body: str):
        """
        Send an email to the configured recipients.

        Parameters:
        - subject (str): Subject line of the email.
        - body (str): Body content of the email.
        """
        if not self.email_enabled:
            logger.debug("Email notifications not configured. Skipping Email notification.")
            return

        # Validate essential email configurations
        if not all([self.smtp_server, self.username, self.password, self.recipients]):
            logger.error("Email configuration is incomplete. Please check your config.yaml.")
            return

        msg = MIMEMultipart()
        msg['From'] = self.sender  # Use sender_email if provided, else username
        msg['To'] = ", ".join(self.recipients)
        msg['Subject'] = subject

        msg.attach(MIMEText(body, 'plain'))

        try:
            if self.smtp_port == 465:
                # Use SMTP_SSL for ports like 465
                server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
                logger.debug("Using SMTP_SSL for port 465.")
            else:
                # Use SMTP with starttls() for ports like 587
                server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10)
                server.ehlo()
                if self.use_tls:
                    server.starttls()
                    server.ehlo()
                    logger.debug("Upgraded to TLS using starttls().")
                else:
                    logger.debug("TLS not enabled. Proceeding without encryption.")

            # Log in to the server
            server.login(self.username, self.password)
            logger.debug("Logged in to SMTP server successfully.")

            # Send the email
            server.send_message(msg)
            logger.info(f"Email sent successfully to {self.recipients} with subject '{subject}'.")

            # Close the connection
            server.quit()
            logger.debug("SMTP server connection closed.")
        except smtplib.SMTPAuthenticationError as e:
            error_message = e.smtp_error.decode() if e.smtp_error else str(e)
            logger.error(f"SMTP Authentication Error: {error_message}")
        except smtplib.SMTPConnectError as e:
            logger.error(f"SMTP Connection Error: {e}")
        except smtplib.SMTPException as e:
            logger.error(f"SMTP Error: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred while sending email: {e}")

    def notify_webhook_event(self, event: str, repo: str, branch: str, pusher: str):
        """
        Notify about a webhook event via Slack and Email.

        Parameters:
        - event (str): The type of webhook event (e.g., push, pull_request).
        - repo (str): Repository name.
        - branch (str): Branch name.
        - pusher (str): Username of the pusher.
        """
        message = (
            f"🔔 **Webhook Event**\n"
            f"- **Repository**: {repo}\n"
            f"- **Branch**: {branch}\n"
            f"- **Pusher**: {pusher}\n"
            f"- **Event**: {event}"
        )
        logger.debug(f"Preparing to send webhook event notification: {message}")
        self.send_slack_message(message)
        subject = f"Webhook Event: {event} on {repo}"
        self.send_email(subject, message)

    def notify_deploy_event(self, repo: str, branch: str, status: str, details: Optional[str] = ""):
        """
        Notify about a deployment event via Slack and Email.

        Parameters:
        - repo (str): Repository name.
        - branch (str): Branch name.
        - status (str): Deployment status (e.g., successful, failed).
        - details (Optional[str]): Additional details about the deployment.
        """
        message = (
            f"🚀 **Deploy Event**\n"
            f"- **Repository**: {repo}\n"
            f"- **Branch**: {branch}\n"
            f"- **Status**: {status}\n"
            f"- **Details**: {details}"
        )
        logger.debug(f"Preparing to send deploy event notification: {message}")
        self.send_slack_message(message)
        subject = f"Deploy Event: {status} on {repo}"
        self.send_email(subject, message)


# Main block for testing
if __name__ == "__main__":
    logger.info("Starting NotificationManager local test...")

    # Initialize the Notifications class with the path to your config.yaml
    notifier = Notifications(config_path='config.yaml')

    # Test sending a webhook event notification
    logger.info("Sending test webhook event notification...")
    notifier.notify_webhook_event(
        event="push",
        repo="example-repo",
        branch="main",
        pusher="johndoe"
    )

    # Test sending a deploy event notification
    logger.info("Sending test deploy event notification...")
    notifier.notify_deploy_event(
        repo="example-repo",
        branch="main",
        status="successful",
        details="Deployment completed without issues."
    )

    logger.info("NotificationManager local test completed.")
