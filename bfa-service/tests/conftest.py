import sys
import os
import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

import analyzer_service


@pytest.fixture(autouse=True)
def bypass_jwt(mocker):
    mocker.patch(
        "analyzer_service.jwt.decode",
        return_value={
            "sub": "test-user",
            "aud": "build-failure-analyzer",
        }
    )


@pytest.fixture
def client():
    return TestClient(analyzer_service.app)


@pytest.fixture
def auth_header():
    return {"Authorization": "Bearer test-token"}