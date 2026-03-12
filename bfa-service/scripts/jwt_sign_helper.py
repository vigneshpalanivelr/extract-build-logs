#!/home/build-failure-analyzer/build-failure-analyzer/.venv/bin/python3

"""
Small utility for CI agents to generate short-lived JWTs for the Analyzer.
This should run inside your corporate network and keep the private key secure.
"""
import jwt
import time
import os

from dotenv import load_dotenv

load_dotenv()

PRIVATE_KEY_PATH = os.getenv("JWT_PRIVATE_KEY_PATH", "/mount/keys/private.pem")
ISSUER = os.getenv("JWT_ISS", "corp-ci-system")
AUD = os.getenv("JWT_AUD", "build-failure-analyzer")


def generate_token(subject: str, ttl_seconds: int = 60):
    with open(PRIVATE_KEY_PATH, "r") as f:
        private = f.read()
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "aud": AUD,
        "sub": subject,
        "iat": now,
        "exp": now + ttl_seconds
    }
    token = jwt.encode(payload, private, algorithm="RS256")
    return token


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--subject", default="jenkins-runner-1")
    p.add_argument("--ttl", type=int, default=60)
    args = p.parse_args()
    print(generate_token(args.subject, args.ttl))
