# backend/app/services/email_service.py
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.utils import formatdate
from app.core.config import settings
from app.services.humanizer_service import humanize_text # Import the humanizer function
from app.services.token_monitor_service import send_telegram_alert # For critical alerts
import time
import random
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

# --- SMTP Connection Pool (Conceptual - smtplib is generally synchronous) ---
# For high volume, consider libraries like 'aiosmtplib' or managing connections carefully.
# For low/moderate volume with delays, reconnecting each time is simpler and often sufficient.

async def send_authenticated_email(
    to_email: str,
    subject: str,
    html_content: str,
    attachment_path: Optional[str] = None,
    retry_attempts: int = 2,
    initial_delay_seconds: float = 1.0
) -> bool:
    """
    Sends an email using configured SMTP settings with STARTTLS.
    Includes humanization of subject/body and optional PDF attachment.
    Implements basic retry logic and random delays.
    """
    if not all([settings.DOMAIN_EMAIL_USER, settings.DOMAIN_EMAIL_PASSWORD, settings.DOMAIN_EMAIL_SMTP_SERVER]):
        logger.error("SMTP Email Service is not configured. Cannot send email.")
        return False

    logger.info(f"Preparing email for: {to_email} | Subject: {subject}")

    # --- Humanize Content (Best Effort) ---
    # This relies on the humanizer_service; if it fails or returns original, email is sent anyway.
    try:
        # Run humanization concurrently for subject and body if desired
        humanized_subject, humanized_body = await asyncio.gather(
            humanize_text(subject),
            humanize_text(html_content)
        )
        logger.info("Subject and body processed by humanizer service.")
    except Exception as humanizer_err:
        logger.warning(f"Humanizer service failed: {humanizer_err}. Sending original content.", exc_info=True)
        humanized_subject = subject
        humanized_body = html_content

    # --- Construct Email Message ---
    message = MIMEMultipart("alternative")
    message["Subject"] = humanized_subject
    message["From"] = settings.DOMAIN_EMAIL_USER
    message["To"] = to_email
    message["Date"] = formatdate(localtime=True)
    # Add standard headers to potentially improve deliverability
    message["Message-ID"] = smtplib.email.utils.make_msgid()
    message["MIME-Version"] = "1.0"

    # Attach HTML part
    message.attach(MIMEText(humanized_body, "html", _charset=settings.ENCODING))

    # Attach PDF if provided
    if attachment_path and os.path.exists(attachment_path):
        try:
            with open(attachment_path, "rb") as attachment_file:
                part = MIMEApplication(attachment_file.read(), Name=os.path.basename(attachment_path))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment_path)}"'
            message.attach(part)
            logger.info(f"Successfully attached file: {os.path.basename(attachment_path)}")
        except Exception as attach_err:
            logger.error(f"Failed to attach file {attachment_path}: {attach_err}", exc_info=True)
            # Decide whether to proceed without attachment or fail
            await send_telegram_alert(f"Failed to attach report {os.path.basename(attachment_path)} to email for {to_email}.")
            # return False # Option: Fail if attachment fails

    # --- Send Email with Retries and Delays ---
    current_attempt = 0
    last_exception = None
    while current_attempt <= retry_attempts:
        current_attempt += 1
        logger.info(f"Attempt {current_attempt}/{retry_attempts+1} to send email to {to_email}")
        context = ssl.create_default_context()
        server = None # Ensure server is defined for finally block
        try:
            # Connect and send (reconnect each time for simplicity)
            if settings.DOMAIN_EMAIL_SMTP_PORT == 465: # SSL Connection
                 server = smtplib.SMTP_SSL(settings.DOMAIN_EMAIL_SMTP_SERVER, settings.DOMAIN_EMAIL_SMTP_PORT, context=context, timeout=30)
            else: # Assuming STARTTLS (like port 587)
                 server = smtplib.SMTP(settings.DOMAIN_EMAIL_SMTP_SERVER, settings.DOMAIN_EMAIL_SMTP_PORT, timeout=30)
                 server.starttls(context=context)

            server.login(settings.DOMAIN_EMAIL_USER, settings.DOMAIN_EMAIL_PASSWORD)
            logger.info(f"SMTP Login successful for {settings.DOMAIN_EMAIL_USER}")
            server.sendmail(settings.DOMAIN_EMAIL_USER, [to_email], message.as_string()) # Pass recipient as list
            logger.info(f"Email successfully sent to {to_email} on attempt {current_attempt}.")
            return True # Success! Exit loop.

        except smtplib.SMTPAuthenticationError as e:
            logger.critical(f"SMTP Authentication Error for {settings.DOMAIN_EMAIL_USER}. Check credentials! Error: {e}", exc_info=True)
            await send_telegram_alert(f"CRITICAL: SMTP Authentication Failed for {settings.DOMAIN_EMAIL_USER}! Check config.")
            return False # Auth error is fatal, don't retry
        except smtplib.SMTPRecipientsRefused as e:
             logger.error(f"Recipient refused for {to_email}. Error: {e}", exc_info=True)
             return False # Recipient error is fatal for this email
        except smtplib.SMTPSenderRefused as e:
             logger.error(f"Sender refused for {settings.DOMAIN_EMAIL_USER}. Check server config/permissions. Error: {e}", exc_info=True)
             return False # Sender error likely fatal
        except smtplib.SMTPException as e: # Catch other SMTP errors for retry
            logger.warning(f"SMTP Error on attempt {current_attempt} sending to {to_email}: {e}", exc_info=True)
            last_exception = e
            if current_attempt <= retry_attempts:
                # Exponential backoff with jitter
                delay = initial_delay_seconds * (2 ** (current_attempt - 1)) + random.uniform(0, 1)
                logger.info(f"Waiting {delay:.2f} seconds before retry...")
                await asyncio.sleep(delay)
            else:
                 logger.error(f"Failed to send email to {to_email} after {retry_attempts + 1} attempts.")
                 await send_telegram_alert(f"Failed to send email to {to_email} after retries. Last Error: {e}")
                 return False # Failed after all retries
        except Exception as e: # Catch unexpected errors
            logger.error(f"Unexpected error sending email on attempt {current_attempt} to {to_email}: {e}", exc_info=True)
            last_exception = e
            # Don't retry unexpected errors immediately, log and fail
            await send_telegram_alert(f"Unexpected error sending email to {to_email}: {e}")
            return False
        finally:
            if server:
                try:
                    server.quit()
                    logger.debug("SMTP connection closed.")
                except Exception:
                    logger.warning("Exception during SMTP quit.", exc_info=True)

    # Should only reach here if all retries failed due to SMTPException
    logger.error(f"Final failure sending email to {to_email}. Last exception: {last_exception}")
    return False