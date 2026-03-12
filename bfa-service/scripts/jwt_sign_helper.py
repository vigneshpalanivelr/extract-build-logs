#!/home/build-failure-analyzer/build-failure-analyzer/.venv/bin/python3

"""
Small utility for CI agents to generate short-lived JWTs for the Analyzer.
This should run inside your corporate network and keep the private key secure.
"""
import sys
import os
import jwt
import time

# Add src/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from logging_config import setup_logging, get_logger
from config_loader import config as cfg

setup_logging(log_dir=cfg.bfa_log_dir, log_level=cfg.bfa_log_level)
logger = get_logger("jwt_sign_helper")

PRIVATE_KEY_PATH = cfg.jwt_private_key_path
ISSUER = cfg.jwt_iss
AUD = cfg.jwt_audience


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
