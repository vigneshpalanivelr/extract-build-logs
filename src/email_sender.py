"""
Email Sender Module

Handles sending email notifications for API response processing.
Sends success emails to pipeline users with error analysis and fixes,
and failure emails to DevOps team for API errors.

Module Dependencies:
    - smtplib: For SMTP email sending
    - email: For email message construction
    - logging: For operation logging
    - typing: For type hints
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, List
from datetime import datetime

# Configure module logger
logger = logging.getLogger(__name__)


class EmailSender:
    """
    Handles email notifications for API response processing.

    This class sends two types of emails:
    1. Success emails: Sent to pipeline user with error analysis and fixes
    2. Failure emails: Sent to DevOps team when API posting fails
    """

    def __init__(self, config):
        """
        Initialize email sender.

        Args:
            config: Configuration object with SMTP settings
        """
        self.config = config
        self.smtp_host = config.smtp_host
        self.smtp_port = config.smtp_port
        self.from_email = config.smtp_from_email
        self.devops_email = config.devops_email

        logger.debug(f"EmailSender initialized: {self.smtp_host}:{self.smtp_port}")

    def send_success_email(
        self,
        pipeline_info: Dict[str, Any],
        api_response: Dict[str, Any]
    ) -> bool:
        """
        Send success email to pipeline user with error analysis and fixes.

        Args:
            pipeline_info: Pipeline information from webhook
            api_response: API response with status "ok" and results array

        Returns:
            bool: True if email sent successfully, False otherwise

        Example api_response:
            {
                "status": "ok",
                "results": [
                    {
                        "error_hash": "...",
                        "source": "slack_posted",
                        "step_name": "unit-test",
                        "error_text": "semi colon missing",
                        "fix": "## Fix: Semi colon missing..."
                    }
                ]
            }
        """
        try:
            # Extract user email from pipeline info
            user_email = pipeline_info.get('user', {}).get('email')
            if not user_email:
                logger.warning("No user email found in pipeline info, cannot send success email")
                return False

            # Extract pipeline details
            project_name = pipeline_info.get('project_name', 'Unknown Project')
            ref = pipeline_info.get('ref', 'unknown-branch')
            pipeline_id = pipeline_info.get('pipeline_id', 'unknown')
            project_path = pipeline_info.get('project_path', project_name)

            # Extract results
            results = api_response.get('results', [])
            if not results:
                logger.info(f"No error results to send for pipeline {pipeline_id}")
                return False

            # Build email
            subject = f"Build Analysis Complete: {project_path} - {ref}"
            body_html = self._build_success_email_html(
                project_name=project_name,
                project_path=project_path,
                ref=ref,
                pipeline_id=pipeline_id,
                results=results
            )

            # Send email
            success = self._send_email(
                to_email=user_email,
                subject=subject,
                body_html=body_html
            )

            if success:
                logger.info(
                    f"Success email sent to {user_email} for pipeline {pipeline_id} "
                    f"with {len(results)} error(s) analyzed"
                )
            else:
                logger.error(f"Failed to send success email to {user_email} for pipeline {pipeline_id}")

            return success

        except Exception as e:
            logger.error(f"Error sending success email: {str(e)}", exc_info=True)
            return False

    def send_failure_email(
        self,
        pipeline_info: Dict[str, Any],
        status_code: int,
        error_message: str
    ) -> bool:
        """
        Send failure email to DevOps team when API posting fails.

        Args:
            pipeline_info: Pipeline information from webhook
            status_code: HTTP status code from API response
            error_message: Error message or response body

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            if not self.devops_email:
                logger.warning("DEVOPS_EMAIL not configured, cannot send failure email")
                return False

            # Extract pipeline details
            project_name = pipeline_info.get('project_name', 'Unknown Project')
            project_path = pipeline_info.get('project_path', project_name)
            ref = pipeline_info.get('ref', 'unknown-branch')
            pipeline_id = pipeline_info.get('pipeline_id', 'unknown')
            pipeline_status = pipeline_info.get('status', 'unknown')

            # Build email
            subject = f"BFA API Failure: Pipeline {pipeline_id} - {project_path}"
            body_html = self._build_failure_email_html(
                project_name=project_name,
                project_path=project_path,
                ref=ref,
                pipeline_id=pipeline_id,
                pipeline_status=pipeline_status,
                status_code=status_code,
                error_message=error_message,
                bfa_host=self.config.bfa_host or "Not configured"
            )

            # Send email
            success = self._send_email(
                to_email=self.devops_email,
                subject=subject,
                body_html=body_html
            )

            if success:
                logger.info(
                    f"Failure alert sent to {self.devops_email} for pipeline {pipeline_id} "
                    f"(status code: {status_code})"
                )
            else:
                logger.error(f"Failed to send failure alert to {self.devops_email} for pipeline {pipeline_id}")

            return success

        except Exception as e:
            logger.error(f"Error sending failure email: {str(e)}", exc_info=True)
            return False

    def _build_success_email_html(
        self,
        project_name: str,
        project_path: str,
        ref: str,
        pipeline_id: int,
        results: List[Dict[str, Any]]
    ) -> str:
        """
        Build HTML email body for success notification.

        Args:
            project_name: Project name
            project_path: Full project path
            ref: Branch or tag name
            pipeline_id: Pipeline ID
            results: List of error analysis results

        Returns:
            str: HTML email body
        """
        # Build results sections
        results_html = ""
        for idx, result in enumerate(results, 1):
            step_name = result.get('step_name', 'Unknown Step')
            error_text = result.get('error_text', 'No error text provided')
            fix = result.get('fix', 'No fix provided')
            source = result.get('source', 'unknown')

            # Convert markdown to basic HTML (simple conversion)
            fix_html = self._markdown_to_html(fix)

            results_html += f"""
            <div style="margin-bottom: 30px; padding: 20px; background-color: #f8f9fa; border-left: 4px solid #007bff; border-radius: 4px;">
                <h3 style="margin-top: 0; color: #007bff;">Error #{idx}: {step_name}</h3>
                <p><strong>Source:</strong> {source}</p>
                <p><strong>Error:</strong></p>
                <pre style="background-color: #fff; padding: 10px; border: 1px solid #ddd; border-radius: 4px; overflow-x: auto;">{error_text}</pre>
                <div style="margin-top: 15px;">
                    {fix_html}
                </div>
            </div>
            """

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #28a745; color: white; padding: 20px; border-radius: 4px; }}
                .content {{ padding: 20px; }}
                pre {{ background-color: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; }}
                code {{ background-color: #f5f5f5; padding: 2px 4px; border-radius: 2px; font-family: monospace; }}
                .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0;">Build Analysis Complete</h1>
                    <p style="margin: 10px 0 0 0;">{len(results)} error(s) analyzed and fixes provided</p>
                </div>

                <div class="content">
                    <h2>Pipeline Information</h2>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Project:</strong></td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{project_path}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Branch/Tag:</strong></td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{ref}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Pipeline ID:</strong></td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{pipeline_id}</td>
                        </tr>
                    </table>

                    <h2 style="margin-top: 30px;">Error Analysis & Fixes</h2>
                    {results_html}
                </div>

                <div class="footer">
                    <p>This email was automatically generated by the GitLab Pipeline Log Extraction System.</p>
                    <p>Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
                </div>
            </div>
        </body>
        </html>
        """
        return html

    def _build_failure_email_html(
        self,
        project_name: str,
        project_path: str,
        ref: str,
        pipeline_id: int,
        pipeline_status: str,
        status_code: int,
        error_message: str,
        bfa_host: str
    ) -> str:
        """
        Build HTML email body for failure notification.

        Args:
            project_name: Project name
            project_path: Full project path
            ref: Branch or tag name
            pipeline_id: Pipeline ID
            pipeline_status: Pipeline status (failed, success, etc.)
            status_code: HTTP status code from API
            error_message: Error message or response body
            bfa_host: BFA server hostname

        Returns:
            str: HTML email body
        """
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #dc3545; color: white; padding: 20px; border-radius: 4px; }}
                .content {{ padding: 20px; }}
                .alert {{ background-color: #fff3cd; border: 1px solid #ffc107; padding: 15px; border-radius: 4px; margin: 20px 0; }}
                pre {{ background-color: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; }}
                .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0;">BFA API Failure Alert</h1>
                    <p style="margin: 10px 0 0 0;">Build Failure Analysis API request failed</p>
                </div>

                <div class="content">
                    <div class="alert">
                        <strong>⚠️ Action Required:</strong> The API request to the BFA server failed.
                        Please investigate and resolve the issue.
                    </div>

                    <h2>Pipeline Information</h2>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Project:</strong></td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{project_path}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Branch/Tag:</strong></td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{ref}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Pipeline ID:</strong></td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{pipeline_id}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Pipeline Status:</strong></td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{pipeline_status}</td>
                        </tr>
                    </table>

                    <h2 style="margin-top: 30px;">API Error Details</h2>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>BFA Host:</strong></td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;">{bfa_host}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>HTTP Status Code:</strong></td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong style="color: #dc3545;">{status_code}</strong></td>
                        </tr>
                    </table>

                    <h3>Error Message</h3>
                    <pre>{error_message}</pre>

                    <h2 style="margin-top: 30px;">Troubleshooting Steps</h2>
                    <ol>
                        <li>Verify BFA server is running: <code>curl http://{bfa_host}:8000/health</code></li>
                        <li>Check BFA server logs for errors</li>
                        <li>Verify network connectivity between log extractor and BFA server</li>
                        <li>Check BFA_SECRET_KEY is correctly configured on both sides</li>
                        <li>Review API request logs: <code>logs/api-requests.log</code></li>
                    </ol>
                </div>

                <div class="footer">
                    <p>This email was automatically generated by the GitLab Pipeline Log Extraction System.</p>
                    <p>Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
                </div>
            </div>
        </body>
        </html>
        """
        return html

    def _markdown_to_html(self, markdown_text: str) -> str:
        """
        Convert basic markdown to HTML (simple conversion).

        Handles:
        - Headers (##, ###)
        - Code blocks (```)
        - Inline code (`)
        - Bold (**text**)
        - Lists (-, *)

        Args:
            markdown_text: Markdown text to convert

        Returns:
            str: HTML representation
        """
        if not markdown_text:
            return ""

        lines = markdown_text.split('\n')
        html_lines = []
        in_code_block = False

        for line in lines:
            # Code block
            if line.strip().startswith('```'):
                if in_code_block:
                    html_lines.append('</pre>')
                    in_code_block = False
                else:
                    html_lines.append('<pre style="background-color: #f5f5f5; padding: 10px; border: 1px solid #ddd; border-radius: 4px; overflow-x: auto;">')
                    in_code_block = True
                continue

            if in_code_block:
                html_lines.append(line)
                continue

            # Headers
            if line.startswith('### '):
                html_lines.append(f'<h4>{line[4:]}</h4>')
            elif line.startswith('## '):
                html_lines.append(f'<h3>{line[3:]}</h3>')
            elif line.startswith('# '):
                html_lines.append(f'<h2>{line[2:]}</h2>')
            # Lists
            elif line.strip().startswith(('- ', '* ')):
                item = line.strip()[2:]
                if not html_lines or not html_lines[-1].startswith('<ul>'):
                    html_lines.append('<ul>')
                html_lines.append(f'<li>{item}</li>')
            else:
                # Close list if needed
                if html_lines and html_lines[-1].startswith('<li>'):
                    html_lines.append('</ul>')

                # Regular paragraph
                if line.strip():
                    # Inline code
                    line = line.replace('`', '<code>').replace('</code>', '`')
                    # Bold
                    import re
                    line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
                    html_lines.append(f'<p>{line}</p>')
                else:
                    html_lines.append('<br>')

        # Close any open lists
        if html_lines and html_lines[-1].startswith('<li>'):
            html_lines.append('</ul>')

        return '\n'.join(html_lines)

    def _send_email(
        self,
        to_email: str,
        subject: str,
        body_html: str
    ) -> bool:
        """
        Send email via SMTP or fallback to system mail command.

        Args:
            to_email: Recipient email address
            subject: Email subject
            body_html: HTML email body

        Returns:
            bool: True if sent successfully, False otherwise
        """
        # Try SMTP first
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = to_email

            # Attach HTML body
            html_part = MIMEText(body_html, 'html')
            msg.attach(html_part)

            # Connect to SMTP server and send
            logger.debug(f"Connecting to SMTP server: {self.smtp_host}:{self.smtp_port}")

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                # Note: No authentication needed for local SMTP relay
                # server.starttls()  # Uncomment if TLS is required
                # server.login(user, password)  # Uncomment if auth is required

                server.send_message(msg)
                logger.info(f"Email sent successfully via SMTP to {to_email}")
                return True

        except (smtplib.SMTPException, OSError, ConnectionError) as e:
            logger.warning(f"SMTP failed ({type(e).__name__}: {str(e)}), trying system mail command")

            # Fallback to system mail command
            try:
                import subprocess
                import html

                # Strip HTML tags for plain text email (mail command doesn't support HTML)
                import re
                plain_body = re.sub(r'<[^>]+>', '', body_html)
                plain_body = html.unescape(plain_body)

                # Use system mail command
                logger.debug(f"Sending email via system mail command to {to_email}")

                process = subprocess.Popen(
                    ['mail', '-s', subject, to_email],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )

                stdout, stderr = process.communicate(input=plain_body, timeout=30)

                if process.returncode == 0:
                    logger.info(f"Email sent successfully via mail command to {to_email}")
                    return True
                else:
                    logger.error(f"Mail command failed with return code {process.returncode}: {stderr}")
                    return False

            except FileNotFoundError:
                logger.error("'mail' command not found on system. Install mailutils package.")
                return False
            except subprocess.TimeoutExpired:
                logger.error("Mail command timed out after 30 seconds")
                return False
            except Exception as mail_err:
                logger.error(f"System mail command failed: {str(mail_err)}", exc_info=True)
                return False

        except Exception as e:
            logger.error(f"Unexpected error sending email to {to_email}: {str(e)}", exc_info=True)
            return False
