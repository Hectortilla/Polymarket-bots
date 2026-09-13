"""Private host transport files provisioned by Ansible."""

from enum import StrEnum


class HostTransportFile(StrEnum):
    SFTP_KEY = "sftp_key"
    SFTP_KNOWN_HOSTS = "sftp_known_hosts"
    AGE_RECIPIENTS = "age-recipients.txt"
    RCLONE_CONFIG = "rclone.conf"
    SMTP_CONFIG = "msmtprc"
