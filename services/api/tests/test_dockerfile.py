"""Smoke tests for Phase 03 Docker / nginx / deploy configuration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Workspace root — `tests/` is at grab-dashboard/services/api/tests/
# parents[0]=tests, [1]=api, [2]=services, [3]=grab-dashboard, [4]=grab
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
API_DIR = WORKSPACE_ROOT / "services" / "api"
DOCKER_COMPOSE_PATH = WORKSPACE_ROOT / "docker-compose.yml"
NGINX_CONF_PATH = API_DIR / "deploy" / "nginx.conf"


class TestDockerfile:
    """Verify the API Dockerfile exists and contains required directives."""

    @pytest.fixture
    def dockerfile_content(self) -> str:
        path = API_DIR / "Dockerfile"
        assert path.exists(), f"Dockerfile not found at {path}"
        return path.read_text(encoding="utf-8")

    def test_expose_8000(self, dockerfile_content: str) -> None:
        assert "EXPOSE 8000" in dockerfile_content

    def test_uvicorn_cmd(self, dockerfile_content: str) -> None:
        assert "uvicorn" in dockerfile_content
        assert "app.main:app" in dockerfile_content

    def test_multistage_builder(self, dockerfile_content: str) -> None:
        assert "AS builder" in dockerfile_content
        assert "AS runtime" in dockerfile_content

    def test_venv_in_path(self, dockerfile_content: str) -> None:
        assert ".venv" in dockerfile_content


class TestDockerCompose:
    """Verify docker-compose.yml at workspace root has all three services."""

    @pytest.fixture
    def compose_content(self) -> str:
        assert DOCKER_COMPOSE_PATH.exists(), (
            f"docker-compose.yml not found at {DOCKER_COMPOSE_PATH}"
        )
        return DOCKER_COMPOSE_PATH.read_text(encoding="utf-8")

    def test_api_service(self, compose_content: str) -> None:
        assert "api:" in compose_content
        assert "./services/api" in compose_content

    def test_web_service(self, compose_content: str) -> None:
        assert "web:" in compose_content
        assert "./apps/web" in compose_content

    def test_nginx_service(self, compose_content: str) -> None:
        assert "nginx:" in compose_content
        assert "nginx:alpine" in compose_content

    def test_nginx_ssl_port_443(self, compose_content: str) -> None:
        assert '"127.0.0.1:443:443"' in compose_content or "127.0.0.1:443:443" in compose_content

    def test_nginx_certs_volume(self, compose_content: str) -> None:
        assert "deploy/certs" in compose_content


class TestNginxConf:
    """Verify nginx.conf has upstream api and /api/ location."""

    @pytest.fixture
    def nginx_content(self) -> str:
        assert NGINX_CONF_PATH.exists(), (
            f"nginx.conf not found at {NGINX_CONF_PATH}"
        )
        return NGINX_CONF_PATH.read_text(encoding="utf-8")

    def test_upstream_api(self, nginx_content: str) -> None:
        assert "upstream api" in nginx_content
        assert "server api:8000" in nginx_content

    def test_location_api(self, nginx_content: str) -> None:
        assert "location /api/" in nginx_content
        assert "proxy_pass" in nginx_content

    def test_ssl_certificate(self, nginx_content: str) -> None:
        assert "ssl_certificate" in nginx_content
        assert "fullchain.pem" in nginx_content

    def test_listen_443_ssl(self, nginx_content: str) -> None:
        assert "listen 443 ssl" in nginx_content
