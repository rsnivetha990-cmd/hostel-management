"""
SMTP Configuration Diagnostics and Test Mailer

Usage:
    python test_smtp_connection.py
    python test_smtp_connection.py recipient@example.com
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

def test_smtp(to_email=None):
    smtp_server = os.environ.get("MAIL_SERVER", "").strip()
    smtp_port = int(os.environ.get("MAIL_PORT", 587))
    smtp_user = os.environ.get("MAIL_USERNAME", "").strip()
    smtp_pass = os.environ.get("MAIL_PASSWORD", "").strip()
    sender = os.environ.get("MAIL_DEFAULT_SENDER", smtp_user or "noreply@hostel.edu").strip()
    use_tls = os.environ.get("MAIL_USE_TLS", "true").lower() in ["true", "1"]

    print("=" * 65)
    print(" Smart Hostel Management System - SMTP Configuration Check")
    print("=" * 65)
    print(f"  MAIL_SERVER        : {smtp_server if smtp_server else '[NOT CONFIGURED]'}")
    print(f"  MAIL_PORT          : {smtp_port}")
    print(f"  MAIL_USE_TLS       : {use_tls}")
    print(f"  MAIL_USERNAME      : {smtp_user if smtp_user else '[NOT CONFIGURED]'}")
    print(f"  MAIL_PASSWORD      : {'*' * len(smtp_pass) if smtp_pass else '[NOT CONFIGURED]'}")
    print(f"  MAIL_DEFAULT_SENDER: {sender if sender else '[NOT CONFIGURED]'}")
    print("=" * 65)

    if not smtp_server or not smtp_user or not smtp_pass:
        print("\n[!] SMTP credentials are missing in .env.")
        print("To receive real emails in your inbox, add the following to your .env file:\n")
        print("  MAIL_SERVER=smtp.gmail.com")
        print("  MAIL_PORT=587")
        print("  MAIL_USE_TLS=true")
        print("  MAIL_USERNAME=your_email@gmail.com")
        print("  MAIL_PASSWORD=your_16_char_gmail_app_password")
        print("  MAIL_DEFAULT_SENDER=your_email@gmail.com\n")
        print("Tip for Gmail: Generate an App Password at: https://myaccount.google.com/apppasswords")
        return False

    recipient = to_email or smtp_user
    print(f"\nAttempting live connection and email delivery to: {recipient}...")

    try:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg.set_content(
            "Hello!\n\n"
            "This is a confirmation test email from your Smart Hostel Management System.\n"
            "If you received this message, your SMTP credentials in .env are working perfectly!\n\n"
            "Password reset links will now be delivered directly to your real inbox.\n\n"
            "Best regards,\n"
            "Smart Hostel Administration Team"
        )
        msg["Subject"] = "Smart Hostel System - SMTP Test Successful"
        msg["From"] = sender
        msg["To"] = recipient

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
                if use_tls:
                    server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)

        print(f"\n[SUCCESS] Test email successfully delivered to {recipient}!")
        print("Real emails are active and working.")
        return True
    except Exception as e:
        print(f"\n[ERROR] SMTP Transmission Failed: {e}")
        if "Username and Password not accepted" in str(e) or "BadCredentials" in str(e):
            print("\n>> GMAIL NOTICE: Google does not accept your normal Gmail password for SMTP.")
            print(">> You must generate a 16-character App Password at: https://myaccount.google.com/apppasswords")
        return False

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    test_smtp(target)
