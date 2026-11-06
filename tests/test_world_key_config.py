"""World client signing key: WORLD_CLIENT_KEY (inline PEM) or WORLD_CLIENT_KEY_PATH, with errors that name the problem."""
import os
import stat

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from publication.config import ConfigError, world_config


def pem(key) -> str:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


RSA_PEM = pem(rsa.generate_private_key(public_exponent=65537, key_size=2048))


@pytest.fixture(autouse=True)
def base(monkeypatch):
    monkeypatch.setenv('WORLD_ISSUER', 'https://auth.world.org')
    monkeypatch.setenv('WORLD_CLIENT_ID', 'client-1')
    for k in ('WORLD_CLIENT_KEY', 'WORLD_CLIENT_KEY_PATH'):
        monkeypatch.delenv(k, raising=False)


def test_inline_key_multiline_and_escaped(monkeypatch):
    monkeypatch.setenv('WORLD_CLIENT_KEY', RSA_PEM)
    assert world_config().private_key_pem == RSA_PEM.strip().encode()
    monkeypatch.setenv('WORLD_CLIENT_KEY', RSA_PEM.strip().replace('\n', '\\n'))   # single-line host setting
    assert world_config().private_key_pem == RSA_PEM.strip().encode()


def test_inline_key_wins_over_a_broken_path(monkeypatch):
    monkeypatch.setenv('WORLD_CLIENT_KEY', RSA_PEM)
    monkeypatch.setenv('WORLD_CLIENT_KEY_PATH', '/nonexistent/key.pem')
    assert world_config().private_key_pem.startswith(b'-----BEGIN')


def test_key_file(monkeypatch, tmp_path):
    f = tmp_path / 'k.pem'
    f.write_bytes(RSA_PEM.encode())
    monkeypatch.setenv('WORLD_CLIENT_KEY_PATH', str(f))
    assert world_config().private_key_pem == RSA_PEM.encode()


def test_missing_key_settings_and_file(monkeypatch):
    with pytest.raises(ConfigError, match='set WORLD_CLIENT_KEY'):
        world_config()
    monkeypatch.setenv('WORLD_CLIENT_KEY_PATH', '/nonexistent/key.pem')
    with pytest.raises(ConfigError, match='no file at /nonexistent/key.pem'):
        world_config()


@pytest.mark.skipif(getattr(os, 'geteuid', lambda: 0)() == 0, reason='root can read any file')
def test_unreadable_file_is_reported_as_permissions(monkeypatch, tmp_path):
    f = tmp_path / 'k.pem'
    f.write_bytes(RSA_PEM.encode())
    f.chmod(0)
    monkeypatch.setenv('WORLD_CLIENT_KEY_PATH', str(f))
    try:
        with pytest.raises(ConfigError, match='cannot read it'):
            world_config()
    finally:
        f.chmod(stat.S_IRUSR | stat.S_IWUSR)


@pytest.mark.parametrize('value', ['not a key', pem(ec.generate_private_key(ec.SECP256R1()))])
def test_invalid_or_non_rsa_key_never_echoes_material(monkeypatch, value):
    monkeypatch.setenv('WORLD_CLIENT_KEY', value)
    with pytest.raises(ConfigError) as e:
        world_config()
    assert 'WORLD_CLIENT_KEY' in str(e.value) and 'BEGIN' not in str(e.value) and 'not a key' not in str(e.value)

