"""SCOOBY_PUBLIC_GATE: deny-by-default route allowlist for a public host (Render)."""
import os
import tempfile

os.environ.setdefault('SCOOBY_DATA', tempfile.mkdtemp(prefix='scooby-test-'))
import pytest
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)
TOKEN = 'test-operator-token'
OPERATOR_ROUTES = ['/status', '/candidates', '/schemas', '/docs', '/openapi.json', '/readiness/honeypot']


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.setenv('SCOOBY_PUBLIC_GATE', 'true')
    monkeypatch.setenv('SCOOBY_OPERATOR_TOKEN', TOKEN)


def test_gate_off_by_default(monkeypatch):
    monkeypatch.delenv('SCOOBY_PUBLIC_GATE', raising=False)
    assert client.get('/status').status_code == 200


def test_public_paths_open(gate):
    assert client.get('/health').status_code == 200
    assert client.get('/web/v1/health').status_code == 200
    assert client.get('/reports').status_code == 200            # public library list (release policy applies)
    assert client.post('/reports/import', json={}).status_code == 404   # library writes stay private


@pytest.mark.parametrize('path', OPERATOR_ROUTES)
def test_operator_routes_hidden_without_token(gate, path):
    assert client.get(path).status_code == 404
    assert client.get(path, headers={'Authorization': 'Bearer wrong'}).status_code == 404


def test_operator_writes_hidden(gate):
    assert client.post('/candidates', json={'payload': {}}).status_code == 404
    assert client.post('/reports/import', json={'run_id': 'x', 'bundle_path': '/etc'}).status_code == 404


@pytest.mark.parametrize('path', OPERATOR_ROUTES)
def test_operator_routes_open_with_token(gate, path):
    assert client.get(path, headers={'Authorization': f'Bearer {TOKEN}'}).status_code == 200


def test_closed_when_no_token_configured(monkeypatch):
    monkeypatch.setenv('SCOOBY_PUBLIC_GATE', 'true')
    monkeypatch.delenv('SCOOBY_OPERATOR_TOKEN', raising=False)
    assert client.get('/status', headers={'Authorization': 'Bearer '}).status_code == 404


@pytest.mark.parametrize('path', ['/web/v1/../status', '/web/v1/%2e%2e/status', '/web/v1//../candidates', '/health/', '/healthz'])
def test_prefix_bypass_denied(gate, path):
    assert client.get(path).status_code == 404
