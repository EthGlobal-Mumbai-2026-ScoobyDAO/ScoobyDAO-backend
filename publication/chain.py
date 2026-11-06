"""ReportRegistry encoding, attestor signing and the web3 transaction sender.

approval_digest reproduces, byte for byte,
    Sig.ethSigned(keccak256(abi.encode(block.chainid, address(this), report, nonce, expiry)))
from ../SmartContracts/src/ReportRegistry.sol, with the Report tuple in declaration order:
(reportHash, claimHash, reviewer, resolver, adjudicator, lockTime, crossChainCutoff,
 resultDeadline, challengePeriod). The anvil test compares it against the contract's own
approvalDigest view and proves recovery with Sig.recover.

Signing choice: Account.sign_message(encode_defunct(primitive=inner_hash)) on the *inner*
keccak, which applies the same "\\x19Ethereum Signed Message:\\n32" prefix as Sig.ethSigned
and yields a low-s, v in {27, 28} signature as Sig.recover requires.
"""
from __future__ import annotations
import secrets
from dataclasses import dataclass
from typing import Protocol

from eth_abi import encode as abi_encode
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak, to_checksum_address

REPORT_TUPLE = '(bytes32,bytes32,address,address,address,uint64,uint64,uint64,uint64)'
ETH_PREFIX = b'\x19Ethereum Signed Message:\n32'
LOCAL_CHAIN_IDS = (31337, 1337)

REGISTRY_ABI = [
    {'type': 'function', 'name': 'publisher', 'stateMutability': 'view', 'inputs': [], 'outputs': [{'type': 'address'}]},
    {'type': 'function', 'name': 'usedNonce', 'stateMutability': 'view',
     'inputs': [{'type': 'address'}, {'type': 'uint256'}], 'outputs': [{'type': 'bool'}]},
    {'type': 'function', 'name': 'reportCount', 'stateMutability': 'view', 'inputs': [], 'outputs': [{'type': 'uint256'}]},
    {'type': 'function', 'name': 'approvalDigest', 'stateMutability': 'view',
     'inputs': [{'name': 'report', 'type': 'tuple', 'components': [
         {'name': 'reportHash', 'type': 'bytes32'}, {'name': 'claimHash', 'type': 'bytes32'},
         {'name': 'reviewer', 'type': 'address'}, {'name': 'resolver', 'type': 'address'},
         {'name': 'adjudicator', 'type': 'address'}, {'name': 'lockTime', 'type': 'uint64'},
         {'name': 'crossChainCutoff', 'type': 'uint64'}, {'name': 'resultDeadline', 'type': 'uint64'},
         {'name': 'challengePeriod', 'type': 'uint64'}]},
         {'name': 'nonce', 'type': 'uint256'}, {'name': 'expiry', 'type': 'uint64'}],
     'outputs': [{'type': 'bytes32'}]},
    {'type': 'function', 'name': 'publish', 'stateMutability': 'nonpayable',
     'inputs': [{'name': 'report', 'type': 'tuple', 'components': [
         {'name': 'reportHash', 'type': 'bytes32'}, {'name': 'claimHash', 'type': 'bytes32'},
         {'name': 'reviewer', 'type': 'address'}, {'name': 'resolver', 'type': 'address'},
         {'name': 'adjudicator', 'type': 'address'}, {'name': 'lockTime', 'type': 'uint64'},
         {'name': 'crossChainCutoff', 'type': 'uint64'}, {'name': 'resultDeadline', 'type': 'uint64'},
         {'name': 'challengePeriod', 'type': 'uint64'}]},
         {'name': 'nonce', 'type': 'uint256'}, {'name': 'approvalExpiry', 'type': 'uint64'},
         {'name': 'approval', 'type': 'bytes'}],
     'outputs': [{'name': 'id', 'type': 'uint256'}]},
    {'type': 'event', 'name': 'Published', 'anonymous': False, 'inputs': [
        {'name': 'reportId', 'type': 'uint256', 'indexed': True},
        {'name': 'reportHash', 'type': 'bytes32', 'indexed': False},
        {'name': 'claimHash', 'type': 'bytes32', 'indexed': False},
        {'name': 'reviewer', 'type': 'address', 'indexed': False}]},
]
PUBLISHED_TOPIC = '0x' + keccak(text='Published(uint256,bytes32,bytes32,address)').hex().removeprefix('0x')


class ChainError(RuntimeError):
    """RPC or chain state problem; publishing fails closed."""


def report_tuple(target: dict, reviewer: str) -> tuple:
    """Report struct from a scooby.publication-target/1 record. reportHash = report.json SHA-256."""
    return (
        bytes.fromhex(target['reportSha256']),
        bytes.fromhex(target['claimHash']),
        to_checksum_address(reviewer),
        to_checksum_address(target['resolver']),
        to_checksum_address(target['adjudicator']),
        int(target['lockTime']),
        int(target['crossChainCutoff']),
        int(target['resultDeadline']),
        int(target['challengePeriod']),
    )


def inner_hash(chain_id: int, registry: str, report: tuple, nonce: int, expiry: int) -> bytes:
    return keccak(abi_encode(['uint256', 'address', REPORT_TUPLE, 'uint256', 'uint64'],
                             [chain_id, to_checksum_address(registry), report, nonce, expiry]))


def approval_digest(chain_id: int, registry: str, report: tuple, nonce: int, expiry: int) -> bytes:
    """Sig.ethSigned(inner) exactly as ReportRegistry.approvalDigest."""
    return keccak(ETH_PREFIX + inner_hash(chain_id, registry, report, nonce, expiry))


def sign_approval(attestor_key: str, chain_id: int, registry: str, report: tuple, nonce: int, expiry: int) -> str:
    msg = encode_defunct(primitive=inner_hash(chain_id, registry, report, nonce, expiry))
    sig = Account.sign_message(msg, private_key=attestor_key).signature
    return '0x' + bytes(sig).hex()


def recover_approval(signature: str, chain_id: int, registry: str, report: tuple, nonce: int, expiry: int) -> str:
    msg = encode_defunct(primitive=inner_hash(chain_id, registry, report, nonce, expiry))
    return Account.recover_message(msg, signature=bytes.fromhex(signature.removeprefix('0x')))


def new_nonce() -> int:
    """Random 256-bit nonce; checked unused onchain right before broadcast."""
    return secrets.randbits(256)


def address_of(key: str) -> str:
    return Account.from_key(key).address


# ---------------------------------------------------------------------------- sender interface
@dataclass(frozen=True)
class TxReceipt:
    status: int
    block_number: int
    onchain_report_id: str | None


class ChainSender(Protocol):
    def nonce_used(self, reviewer: str, nonce: int) -> bool: ...
    def build_signed(self, target: dict, reviewer: str, nonce: int, expiry: int, signature: str) -> tuple[str, str]: ...
    def broadcast(self, raw_tx: str) -> str: ...
    def wait(self, tx_hash: str) -> TxReceipt | None: ...
    def tx_known(self, tx_hash: str) -> bool: ...
    def find_published(self, tx_hash: str) -> str | None: ...


class Web3Sender:
    """Real sender. Signs locally with the publisher key; never uses a node-held key."""

    def __init__(self, rpc_url: str, chain_id: int, registry: str, publisher_key: str, confirmations: int = 1,
                 timeout: float = 180):
        from web3 import Web3
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 20}))
        self.chain_id = chain_id
        self.registry = self.w3.eth.contract(address=to_checksum_address(registry), abi=REGISTRY_ABI)
        self.account = Account.from_key(publisher_key)
        self.confirmations = confirmations
        self.timeout = timeout

    def preflight(self) -> None:
        """Startup check: RPC chain id and ReportRegistry.publisher() must match config."""
        try:
            got = self.w3.eth.chain_id
            onchain_publisher = self.registry.functions.publisher().call()
        except Exception as e:
            raise ChainError(f'preflight RPC failed ({type(e).__name__})') from None
        if got != self.chain_id:
            raise ChainError(f'RPC chain id {got} does not match SCOOBY_CHAIN_ID {self.chain_id}')
        if onchain_publisher.lower() != self.account.address.lower():
            raise ChainError('SCOOBY_PUBLISHER_KEY does not match ReportRegistry.publisher()')

    def nonce_used(self, reviewer: str, nonce: int) -> bool:
        return bool(self.registry.functions.usedNonce(to_checksum_address(reviewer), nonce).call())

    def build_signed(self, target: dict, reviewer: str, nonce: int, expiry: int, signature: str) -> tuple[str, str]:
        if self.w3.eth.chain_id != self.chain_id:
            raise ChainError('chain id changed under us')
        fn = self.registry.functions.publish(report_tuple(target, reviewer), nonce, expiry,
                                             bytes.fromhex(signature.removeprefix('0x')))
        base = self.w3.eth.get_block('latest').get('baseFeePerGas', 0)
        tip = self.w3.eth.max_priority_fee
        tx = fn.build_transaction({
            'from': self.account.address, 'chainId': self.chain_id, 'type': 2,
            'nonce': self.w3.eth.get_transaction_count(self.account.address, 'pending'),
            'maxPriorityFeePerGas': tip, 'maxFeePerGas': base * 2 + tip,
        })
        tx['gas'] = int(self.w3.eth.estimate_gas(tx) * 1.2)
        signed = self.account.sign_transaction(tx)
        raw = getattr(signed, 'raw_transaction', None) or signed.rawTransaction
        return '0x' + bytes(signed.hash).hex().removeprefix('0x'), '0x' + bytes(raw).hex()

    def broadcast(self, raw_tx: str) -> str:
        h = self.w3.eth.send_raw_transaction(bytes.fromhex(raw_tx.removeprefix('0x')))
        return '0x' + bytes(h).hex().removeprefix('0x')

    def wait(self, tx_hash: str) -> TxReceipt | None:
        from web3.exceptions import TimeExhausted
        try:
            r = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=self.timeout)
        except TimeExhausted:
            return None
        while self.w3.eth.block_number - r['blockNumber'] + 1 < self.confirmations:
            import time
            time.sleep(2)
        return TxReceipt(int(r['status']), int(r['blockNumber']), self._report_id(r))

    def tx_known(self, tx_hash: str) -> bool:
        try:
            self.w3.eth.get_transaction(tx_hash)
            return True
        except Exception:
            return False

    def find_published(self, tx_hash: str) -> str | None:
        try:
            r = self.w3.eth.get_transaction_receipt(tx_hash)
        except Exception:
            return None
        return self._report_id(r) if r and int(r['status']) == 1 else None

    def _report_id(self, receipt) -> str | None:
        for lg in receipt['logs']:
            if lg['address'].lower() == self.registry.address.lower() and lg['topics'] and \
                    ('0x' + bytes(lg['topics'][0]).hex().removeprefix('0x')) == PUBLISHED_TOPIC:
                return str(int.from_bytes(bytes(lg['topics'][1]), 'big'))
        return None
