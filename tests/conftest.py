def pytest_configure(config):
    config.addinivalue_line('markers', 'anvil: needs Foundry (anvil + forge); skipped when unavailable')
