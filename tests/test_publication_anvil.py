"""Optional chain tests against ../SmartContracts/src/ReportRegistry.sol on a local anvil.
Skipped unless anvil and forge are installed. No public network is touched."""
import json
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

FOUNDRY_BIN = Path.home() / '.foundry' / 'bin'
ANVIL = shutil.which('anvil') or (str(FOUNDRY_BIN / 'anvil') if (FOUNDRY_BIN / 'anvil').exists() else None)
FORGE = shutil.which('forge') or (str(FOUNDRY_BIN / 'forge') if (FOUNDRY_BIN / 'forge').exists() else None)
CONTRACTS = Path(__file__).resolve().parents[2] / 'SmartContracts' / 'src'
pytestmark = [pytest.mark.anvil, pytest.mark.skipif(not (ANVIL and FORGE and (CONTRACTS / 'ReportRegistry.sol').exists()),
                                                    reason='anvil/forge or ../SmartContracts not available')]

from publication import chain  # noqa: E402

KEYS = [
    '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80',  # publisher
    '0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d',  # attestor / reviewer
    '0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a',  # stranger
]


def _free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope='module')
def deployed(tmp_path_factory):
    from web3 import Web3
    root = tmp_path_factory.mktemp('registry')
    (root / 'src').mkdir()
    for f in ('ReportRegistry.sol', 'Utils.sol'):
        shutil.copy(CONTRACTS / f, root / 'src' / f)
    (root / 'foundry.toml').write_text('[profile.default]\nsrc = "src"\nout = "out"\nsolc_version = "0.8.26"\noptimizer = true\n')
    subprocess.run([FORGE, 'build', '--root', str(root)], check=True, capture_output=True, timeout=600)
    art = json.loads((root / 'out' / 'ReportRegistry.sol' / 'ReportRegistry.json').read_text())
    port = _free_port()
    proc = subprocess.Popen([ANVIL, '--port', str(port), '--silent'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rpc = f'http://127.0.0.1:{port}'
    w3 = Web3(Web3.HTTPProvider(rpc))
    for _ in range(100):
        if w3.is_connected():
            break
        time.sleep(0.1)
    pub = w3.eth.account.from_key(KEYS[0])
    C = w3.eth.contract(abi=art['abi'], bytecode=art['bytecode']['object'])
    tx = C.constructor(pub.address).build_transaction({'from': pub.address, 'nonce': w3.eth.get_transaction_count(pub.address), 'chainId': 31337})
    rcpt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(pub.sign_transaction(tx).raw_transaction))
    yield {'w3': w3, 'rpc': rpc, 'address': rcpt['contractAddress'], 'abi': art['abi']}
    proc.terminate()
    proc.wait(timeout=10)


def _target(registry):
    t = int(time.time())
    return {'reportSha256': 'aa' * 32, 'claimHash': 'bb' * 32, 'chainId': 31337, 'registry': registry,
            'resolver': '0x70997970C51812dc3A010C7d01b50e0d17dc79C8', 'adjudicator': '0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC',
            'lockTime': t + 7200, 'crossChainCutoff': t + 3600, 'resultDeadline': t + 7200 + 31 * 86400, 'challengePeriod': 86400}


def test_approval_digest_matches_contract(deployed):
    reg = deployed['w3'].eth.contract(address=deployed['address'], abi=deployed['abi'])
    reviewer = chain.address_of(KEYS[1])
    report = chain.report_tuple(_target(deployed['address']), reviewer)
    nonce, expiry = chain.new_nonce(), int(time.time()) + 900
    onchain = reg.functions.approvalDigest(report, nonce, expiry).call()
    assert bytes(onchain) == chain.approval_digest(31337, deployed['address'], report, nonce, expiry)


def test_real_publish_then_replay_wrong_signer_wrong_sender(deployed):
    from web3.exceptions import ContractLogicError
    w3 = deployed['w3']
    reg = w3.eth.contract(address=deployed['address'], abi=deployed['abi'])
    sender = chain.Web3Sender(deployed['rpc'], 31337, deployed['address'], KEYS[0])
    sender.preflight()
    reviewer = chain.address_of(KEYS[1])
    target = _target(deployed['address'])
    report = chain.report_tuple(target, reviewer)
    nonce, expiry = chain.new_nonce(), int(time.time()) + 900
    sig = chain.sign_approval(KEYS[1], 31337, deployed['address'], report, nonce, expiry)
    assert not sender.nonce_used(reviewer, nonce)
    tx_hash, raw = sender.build_signed(target, reviewer, nonce, expiry, sig)
    assert sender.broadcast(raw) == tx_hash
    rec = sender.wait(tx_hash)
    assert rec.status == 1 and rec.onchain_report_id == '1'
    assert sender.nonce_used(reviewer, nonce) and sender.find_published(tx_hash) == '1'
    pub = chain.address_of(KEYS[0])
    sigb = bytes.fromhex(sig[2:])
    with pytest.raises(ContractLogicError, match='APPROVAL_EXPIRED_OR_USED'):
        reg.functions.publish(report, nonce, expiry, sigb).call({'from': pub})
    n2 = chain.new_nonce()
    bad = chain.sign_approval(KEYS[2], 31337, deployed['address'], report, n2, expiry)
    with pytest.raises(ContractLogicError, match='REVIEWER'):
        reg.functions.publish(report, n2, expiry, bytes.fromhex(bad[2:])).call({'from': pub})
    good = chain.sign_approval(KEYS[1], 31337, deployed['address'], report, n2, expiry)
    with pytest.raises(ContractLogicError, match='PUBLISHER'):
        reg.functions.publish(report, n2, expiry, bytes.fromhex(good[2:])).call({'from': chain.address_of(KEYS[2])})


def test_preflight_rejects_wrong_publisher_key(deployed):
    with pytest.raises(chain.ChainError, match='publisher'):
        chain.Web3Sender(deployed['rpc'], 31337, deployed['address'], KEYS[2]).preflight()
    with pytest.raises(chain.ChainError, match='chain id'):
        chain.Web3Sender(deployed['rpc'], 11155111, deployed['address'], KEYS[0]).preflight()
