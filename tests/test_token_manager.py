"""
Unit tests for token_manager.py

Comprehensive test coverage for JWT token management including:
- Token manager initialization
- Token generation with valid subjects
- Subject format validation
- Source validation (gitlab/jenkins)
- Token expiration
- Additional claims
- Token validation and decoding
- Expired token handling
- Invalid token handling
- Unsafe token decoding
"""

import unittest
import time
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.token_manager import TokenManager
import jwt


class TestTokenManager(unittest.TestCase):
    """Test cases for TokenManager class."""

    def setUp(self):
        """Set up test fixtures."""
        self.secret_key = "test-secret-key-12345"
        self.manager = TokenManager(secret_key=self.secret_key)

    def test_initialization_default_algorithm(self):
        """Test TokenManager initialization with default algorithm."""
        manager = TokenManager(secret_key="secret")

        self.assertEqual(manager.secret_key, "secret")
        self.assertEqual(manager.algorithm, "HS256")

    def test_initialization_custom_algorithm(self):
        """Test TokenManager initialization with custom algorithm."""
        manager = TokenManager(secret_key="secret", algorithm="HS512")

        self.assertEqual(manager.secret_key, "secret")
        self.assertEqual(manager.algorithm, "HS512")

    def test_generate_token_gitlab_valid_subject(self):
        """Test token generation with valid GitLab subject."""
        subject = "gitlab_myproject_12345"

        token = self.manager.generate_token(subject)

        self.assertIsInstance(token, str)
        self.assertTrue(len(token) > 0)

        # Decode and verify payload
        payload = self.manager.validate_token(token)
        self.assertEqual(payload['sub'], subject)
        self.assertIn('iat', payload)
        self.assertIn('exp', payload)
        self.assertIn('jti', payload)

    def test_generate_token_jenkins_valid_subject(self):
        """Test token generation with valid Jenkins subject."""
        subject = "jenkins_buildservice_456"

        token = self.manager.generate_token(subject)

        payload = self.manager.validate_token(token)
        self.assertEqual(payload['sub'], subject)

    def test_generate_token_subject_with_underscores(self):
        """Test token generation with subject containing multiple underscores."""
        subject = "gitlab_my_complex_project_name_12345"

        token = self.manager.generate_token(subject)

        payload = self.manager.validate_token(token)
        self.assertEqual(payload['sub'], subject)

    def test_generate_token_empty_subject_raises_error(self):
        """Test that empty subject raises ValueError."""
        with self.assertRaises(ValueError) as context:
            self.manager.generate_token("")

        self.assertIn("non-empty string", str(context.exception))

    def test_generate_token_none_subject_raises_error(self):
        """Test that None subject raises ValueError."""
        with self.assertRaises(ValueError) as context:
            self.manager.generate_token(None)

        self.assertIn("non-empty string", str(context.exception))

    def test_generate_token_invalid_format_too_few_parts(self):
        """Test that subject with too few parts raises ValueError."""
        with self.assertRaises(ValueError) as context:
            self.manager.generate_token("gitlab_project")

        self.assertIn("format: <source>_<repo>_<pipeline>", str(context.exception))

    def test_generate_token_invalid_source(self):
        """Test that invalid source raises ValueError."""
        with self.assertRaises(ValueError) as context:
            self.manager.generate_token("bitbucket_project_123")

        self.assertIn("gitlab", str(context.exception))
        self.assertIn("jenkins", str(context.exception))

    def test_generate_token_custom_expiration(self):
        """Test token generation with custom expiration time."""
        subject = "gitlab_test_123"
        expires_in_minutes = 120

        token = self.manager.generate_token(subject, expires_in_minutes=expires_in_minutes)

        payload = self.manager.validate_token(token)

        # Check expiration is approximately correct (within 60 seconds)
        expected_exp = datetime.utcnow() + timedelta(minutes=expires_in_minutes)
        actual_exp = datetime.utcfromtimestamp(payload['exp'])
        time_diff = abs((expected_exp - actual_exp).total_seconds())
        self.assertLess(time_diff, 60)

    def test_generate_token_with_additional_claims(self):
        """Test token generation with additional claims."""
        subject = "gitlab_project_789"
        additional_claims = {
            'user': 'test-user',
            'role': 'admin',
            'custom_field': 'value'
        }

        token = self.manager.generate_token(subject, additional_claims=additional_claims)

        payload = self.manager.validate_token(token)
        self.assertEqual(payload['user'], 'test-user')
        self.assertEqual(payload['role'], 'admin')
        self.assertEqual(payload['custom_field'], 'value')

    def test_generate_token_unique_jti(self):
        """Test that each token has a unique JWT ID."""
        subject = "gitlab_project_123"

        token1 = self.manager.generate_token(subject)
        token2 = self.manager.generate_token(subject)

        payload1 = self.manager.validate_token(token1)
        payload2 = self.manager.validate_token(token2)

        # JTI should be different for each token
        self.assertNotEqual(payload1['jti'], payload2['jti'])

    def test_validate_token_valid(self):
        """Test validation of a valid token."""
        subject = "gitlab_project_456"
        token = self.manager.generate_token(subject)

        payload = self.manager.validate_token(token)

        self.assertEqual(payload['sub'], subject)
        self.assertIsInstance(payload['iat'], int)
        self.assertIsInstance(payload['exp'], int)

    def test_validate_token_expired(self):
        """Test validation of an expired token."""
        subject = "gitlab_project_789"
        # Generate token with 0 minutes expiration (immediately expired)
        # Need to manually create an expired token
        now = datetime.utcnow()
        payload = {
            'sub': subject,
            'iat': now - timedelta(minutes=2),
            'exp': now - timedelta(minutes=1),  # Expired 1 minute ago
            'jti': 'test-jti'
        }
        expired_token = jwt.encode(payload, self.secret_key, algorithm="HS256")

        with self.assertRaises(jwt.InvalidTokenError) as context:
            self.manager.validate_token(expired_token)

        self.assertIn("expired", str(context.exception).lower())

    def test_validate_token_invalid_signature(self):
        """Test validation of token with invalid signature."""
        subject = "gitlab_project_999"
        # Generate token with different secret
        other_manager = TokenManager(secret_key="different-secret")
        token = other_manager.generate_token(subject)

        with self.assertRaises(jwt.InvalidTokenError) as context:
            self.manager.validate_token(token)

        self.assertIn("Invalid token", str(context.exception))

    def test_validate_token_malformed(self):
        """Test validation of malformed token."""
        malformed_token = "not.a.valid.jwt.token"

        with self.assertRaises(jwt.InvalidTokenError):
            self.manager.validate_token(malformed_token)

    def test_validate_token_empty_string(self):
        """Test validation of empty token string."""
        with self.assertRaises(jwt.InvalidTokenError):
            self.manager.validate_token("")

    def test_decode_token_unsafe_valid_token(self):
        """Test unsafe decoding of a valid token."""
        subject = "gitlab_project_111"
        token = self.manager.generate_token(subject)

        payload = self.manager.decode_token_unsafe(token)

        self.assertEqual(payload['sub'], subject)
        self.assertIn('iat', payload)
        self.assertIn('exp', payload)
        self.assertIn('jti', payload)

    def test_decode_token_unsafe_expired_token(self):
        """Test unsafe decoding of expired token (should succeed)."""
        # Create expired token
        now = datetime.utcnow()
        payload = {
            'sub': 'gitlab_test_999',
            'iat': now - timedelta(minutes=2),
            'exp': now - timedelta(minutes=1),  # Expired
            'jti': 'test-jti'
        }
        expired_token = jwt.encode(payload, self.secret_key, algorithm="HS256")

        # Unsafe decode should succeed even for expired tokens
        decoded = self.manager.decode_token_unsafe(expired_token)

        self.assertEqual(decoded['sub'], 'gitlab_test_999')
        self.assertEqual(decoded['jti'], 'test-jti')

    def test_decode_token_unsafe_invalid_signature(self):
        """Test unsafe decoding with invalid signature (should succeed)."""
        # Generate token with different secret
        other_manager = TokenManager(secret_key="different-secret")
        token = other_manager.generate_token("gitlab_test_222")

        # Unsafe decode should succeed even with invalid signature
        decoded = self.manager.decode_token_unsafe(token)

        self.assertEqual(decoded['sub'], 'gitlab_test_222')

    def test_token_default_expiration(self):
        """Test that default token expiration is 60 minutes."""
        subject = "gitlab_project_333"

        token = self.manager.generate_token(subject)

        payload = self.manager.validate_token(token)

        # Calculate expected expiration (60 minutes from now)
        expected_exp = datetime.utcnow() + timedelta(minutes=60)
        actual_exp = datetime.utcfromtimestamp(payload['exp'])

        # Should be within 60 seconds of expected
        time_diff = abs((expected_exp - actual_exp).total_seconds())
        self.assertLess(time_diff, 60)

    def test_source_case_insensitive(self):
        """Test that source validation is case-insensitive."""
        # Should accept uppercase
        token1 = self.manager.generate_token("GITLAB_project_123")
        payload1 = self.manager.validate_token(token1)
        self.assertEqual(payload1['sub'], "GITLAB_project_123")

        # Should accept mixed case
        token2 = self.manager.generate_token("Jenkins_project_456")
        payload2 = self.manager.validate_token(token2)
        self.assertEqual(payload2['sub'], "Jenkins_project_456")

    def test_different_algorithms(self):
        """Test token generation with different algorithms."""
        for algorithm in ['HS256', 'HS384', 'HS512']:
            manager = TokenManager(secret_key=self.secret_key, algorithm=algorithm)
            token = manager.generate_token("gitlab_test_111")
            payload = manager.validate_token(token)

            self.assertEqual(payload['sub'], 'gitlab_test_111')

    def test_token_issued_at_timestamp(self):
        """Test that issued at timestamp is approximately correct."""
        subject = "gitlab_project_444"

        before = datetime.utcnow()
        token = self.manager.generate_token(subject)
        after = datetime.utcnow()

        payload = self.manager.validate_token(token)
        issued_at = datetime.utcfromtimestamp(payload['iat'])

        # Issued at should be between before and after
        self.assertGreaterEqual(issued_at, before - timedelta(seconds=1))
        self.assertLessEqual(issued_at, after + timedelta(seconds=1))

    def test_subject_with_numeric_pipeline_id(self):
        """Test subject with numeric pipeline ID."""
        subject = "gitlab_myproject_123456789"

        token = self.manager.generate_token(subject)
        payload = self.manager.validate_token(token)

        self.assertEqual(payload['sub'], subject)

    def test_subject_with_alphanumeric_pipeline_id(self):
        """Test subject with alphanumeric pipeline ID."""
        subject = "jenkins_build_abc123def"

        token = self.manager.generate_token(subject)
        payload = self.manager.validate_token(token)

        self.assertEqual(payload['sub'], subject)

    def test_token_roundtrip(self):
        """Test complete token generation, validation, and decoding cycle."""
        subject = "gitlab_integration_test_555"
        additional_claims = {'test': 'data'}

        # Generate token
        token = self.manager.generate_token(
            subject,
            expires_in_minutes=30,
            additional_claims=additional_claims
        )

        # Validate token
        validated_payload = self.manager.validate_token(token)

        # Unsafe decode token
        unsafe_payload = self.manager.decode_token_unsafe(token)

        # Both should have same content
        self.assertEqual(validated_payload['sub'], subject)
        self.assertEqual(unsafe_payload['sub'], subject)
        self.assertEqual(validated_payload['test'], 'data')
        self.assertEqual(unsafe_payload['test'], 'data')


if __name__ == '__main__':
    unittest.main()
