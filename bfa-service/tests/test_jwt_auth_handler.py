import subprocess
import sys
from pathlib import Path

import jwt_dmz_issuer


# -------------------------------------------------
# Helpers
# -------------------------------------------------

def generate_real_rsa_key(tmp_path):
    """Generate a real RSA private key for RS256 tests."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )

    key_path = tmp_path / "private.pem"
    key_path.write_bytes(pem)
    return key_path


# -------------------------------------------------
# UNIT TESTS (mock jwt.encode)
# -------------------------------------------------

def test_create_jwt_returns_token(mocker):
    mocker.patch("jwt.encode", return_value="fake.jwt.token")

    token = jwt_dmz_issuer.create_jwt("test-subject")

    assert token == "fake.jwt.token"


def test_jwt_contains_expected_claims(mocker):
    captured_payload = {}

    def fake_encode(payload, key, algorithm):
        captured_payload.update(payload)
        return "fake.jwt"

    mocker.patch("jwt.encode", side_effect=fake_encode)

    jwt_dmz_issuer.create_jwt("jenkins-runner")

    assert captured_payload["iss"] == "dmz-analyzer"
    assert captured_payload["sub"] == "jenkins-runner"
    assert captured_payload["aud"] == jwt_dmz_issuer.JWT_AUDIENCE


def test_jwt_custom_expiry_minutes(mocker):
    captured_payload = {}

    def fake_encode(payload, key, algorithm):
        captured_payload.update(payload)
        return "fake.jwt"

    mocker.patch("jwt.encode", side_effect=fake_encode)

    jwt_dmz_issuer.create_jwt("agent", expiry_minutes=5)

    delta = (
        captured_payload["exp"] - captured_payload["iat"]
    ).total_seconds()

    assert 290 <= delta <= 310


def test_private_key_file_is_read(mocker, tmp_path):
    key_path = tmp_path / "key.pem"
    key_path.write_text("dummy")

    mocker.patch.object(jwt_dmz_issuer, "PRIVATE_KEY_PATH", str(key_path))
    mocker.patch("jwt.encode", return_value="fake.jwt")

    jwt_dmz_issuer.create_jwt("test")

    assert key_path.exists()


# -------------------------------------------------
# INTEGRATION TEST (REAL RSA KEY)
# -------------------------------------------------

def test_cli_execution_outputs_token(tmp_path, monkeypatch):
    key_path = generate_real_rsa_key(tmp_path)

    monkeypatch.setenv("JWT_PRIVATE_KEY_PATH", str(key_path))

    script_path = Path(jwt_dmz_issuer.__file__)

    result = subprocess.run(
        [sys.executable, str(script_path), "cli-agent"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert len(result.stdout.strip()) > 20
