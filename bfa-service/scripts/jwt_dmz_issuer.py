#!/home/build-failure-analyzer/build-failure-analyzer/.venv/bin/python3

"""
DMZ-side JWT issuer for CI/CD agents.
Signs tokens locally using RSA private key (kept in DMZ).
Later, this can be swapped for corp-signed approach without changing analyzer_service.py logic.
"""

import sys
import os
import jwt
import datetime

# Add src/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from logging_config import setup_logging, get_logger
from config_loader import config as cfg

setup_logging(log_dir=cfg.bfa_log_dir, log_level=cfg.bfa_log_level)
logger = get_logger("jwt_dmz_issuer")

PRIVATE_KEY_PATH = cfg.jwt_private_key_path
JWT_AUDIENCE = cfg.jwt_audience
JWT_ISSUER = cfg.jwt_issuer
JWT_EXPIRY_MINUTES = cfg.jwt_expiry_minutes


def create_jwt(subject: str, expiry_minutes: int = JWT_EXPIRY_MINUTES) -> str:
    """Generate JWT token signed using private key."""
    with open(PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()

    payload = {
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "sub": subject,
        "iat": datetime.datetime.utcnow(),
        "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=expiry_minutes)
    }

    token = jwt.encode(payload, private_key, algorithm="RS256")
    return token


# Optional CLI usage (so it can still be run manually)
if __name__ == "__main__":
    import sys
    subject = sys.argv[1] if len(sys.argv) > 1 else "jenkins-runner-01"
    print(create_jwt(subject))
