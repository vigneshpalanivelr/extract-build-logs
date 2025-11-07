"""
Token Manager Module

Provides JWT token generation for API authentication.
Tokens are generated dynamically based on subject (gitlab|jenkins_repo_pipeline)
and can be used for authenticated API posting instead of static tokens.

Token Format:
  subject: <source>_<repository>_<pipeline_id>
  Examples:
    - gitlab_myproject_12345
    - jenkins_build-service_456

Token Claims:
  - sub: Subject identifier
  - iat: Issued at timestamp
  - exp: Expiration timestamp (default: 1 hour)
  - jti: JWT ID (unique token identifier)
"""

import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional
import jwt


class TokenManager:
    """
    Manages JWT token generation and validation for API authentication.
    """

    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        """
        Initialize token manager.

        Args:
            secret_key: Secret key for JWT signing
            algorithm: JWT algorithm (default: HS256)
        """
        self.secret_key = secret_key
        self.algorithm = algorithm

    def generate_token(
        self,
        subject: str,
        expires_in_minutes: int = 60,
        additional_claims: Optional[Dict] = None
    ) -> str:
        """
        Generate a JWT token for the given subject.

        Args:
            subject: Subject identifier (format: <source>_<repo>_<pipeline>)
            expires_in_minutes: Token expiration time in minutes (default: 60)
            additional_claims: Additional JWT claims to include

        Returns:
            JWT token string

        Raises:
            ValueError: If subject is invalid
        """
        # Validate subject format
        if not subject or not isinstance(subject, str):
            raise ValueError("Subject must be a non-empty string")

        parts = subject.split('_')
        if len(parts) < 3:
            raise ValueError(
                "Subject must be in format: <source>_<repo>_<pipeline> "
                f"(e.g., 'gitlab_myproject_12345'), got: {subject}"
            )

        source = parts[0].lower()
        if source not in ['gitlab', 'jenkins']:
            raise ValueError(
                f"Source must be 'gitlab' or 'jenkins', got: {source}"
            )

        # Create JWT payload
        now = datetime.utcnow()
        payload = {
            'sub': subject,  # Subject
            'iat': now,  # Issued at
            'exp': now + timedelta(minutes=expires_in_minutes),  # Expiration
            'jti': str(uuid.uuid4())  # JWT ID (unique token identifier)
        }

        # Add additional claims if provided
        if additional_claims:
            payload.update(additional_claims)

        # Generate and return JWT token
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return token

    def validate_token(self, token: str) -> Dict:
        """
        Validate and decode a JWT token.

        Args:
            token: JWT token string

        Returns:
            Decoded token payload

        Raises:
            jwt.InvalidTokenError: If token is invalid or expired
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise jwt.InvalidTokenError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise jwt.InvalidTokenError(f"Invalid token: {str(e)}")

    def decode_token_unsafe(self, token: str) -> Dict:
        """
        Decode token without validation (for debugging).

        Args:
            token: JWT token string

        Returns:
            Decoded token payload (unverified)
        """
        return jwt.decode(token, options={"verify_signature": False})
