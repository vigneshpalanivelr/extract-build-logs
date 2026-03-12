#!/home/build-failure-analyzer/build-failure-analyzer/.venv/bin/python3

"""
DMZ-side JWT issuer for CI/CD agents.
Signs tokens locally using RSA private key (kept in DMZ).
Later, this can be swapped for corp-signed approach without changing analyzer_service.py logic.
"""

import os
import jwt
import datetime
from dotenv import load_dotenv

load_dotenv()

PRIVATE_KEY_PATH = os.getenv("JWT_PRIVATE_KEY_PATH", "/home/build-failure-analyzer/private.pem")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "build-failure-analyzer")
JWT_ISSUER = os.getenv("JWT_ISSUER", "dmz-analyzer")
JWT_EXPIRY_MINUTES = int(os.getenv("JWT_EXPIRY_MINUTES", "60"))


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
