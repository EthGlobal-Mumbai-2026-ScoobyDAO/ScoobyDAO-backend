import os
import tempfile
os.environ['SCOOBY_DATA'] = tempfile.mkdtemp(prefix='scooby-tests-')
os.environ.setdefault('SCOOBY_WEB_ORIGIN', 'http://localhost:5173')

def pytest_configure(config):
    config.addinivalue_line('markers', 'anvil: needs Foundry (anvil + forge); skipped when unavailable')
