"""Mocked local RPC controls; these tests do not execute a real EVM."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import g02_fork_executor as executor

TOKEN = '0x' + 'a' * 40
POOL = '0x' + 'b' * 40
ROUTER = '0x' + 'c' * 40
FACTORY = '0x' + 'd' * 40
ACTOR = '0x' + 'e' * 40
BLOCK_HASH = '0x' + 'f' * 64
SECRET = 'synthetic-archive-secret-never-log'


def plan():
    return {'profile': 'scooby.g02-fork-plan/0', 'candidate_id': '1:' + TOKEN,
            'pool': POOL, 'router': ROUTER, 'block': {'number': 123, 'hash': BLOCK_HASH},
            'amount_in': '100', 'minimum_buy_out': '1', 'minimum_sell_out': '1',
            'native_funding': '1000000000000000000', 'deadline': 1700001000,
            'gas_limit': 3000000, 'max_rpc_calls': 80}


def encoded(n):
    return '0x' + format(n, '064x')


class MockNode:
    """State machine for transport/sequence controls, not bytecode execution."""
    def __init__(self, fail_stage=None, metadata_chain=1, cleanup_fails=False, bad_post_anchor=False, partial_sell=False, lost_impersonation_reply=False, empty_pool=False):
        self.fail_stage, self.metadata_chain, self.cleanup_fails = fail_stage, metadata_chain, cleanup_fails
        self.bad_post_anchor, self.partial_sell, self.lost_impersonation_reply = bad_post_anchor, partial_sell, lost_impersonation_reply
        self.empty_pool = empty_pool
        self.calls, self.sent, self.receipts = [], [], {}
        self.weth, self.token, self.weth_allowance, self.token_allowance = 0, 0, 0, 0
        self.native = 0
        self.impersonating = False
        self.reverted = False

    def send(self, body):
        self.calls.append(copy.deepcopy(body))
        method, params = body['method'], body['params']
        block = {'number': hex(123), 'hash': BLOCK_HASH, 'timestamp': hex(1700000000)}
        if method == 'web3_clientVersion': result = 'anvil/fixture-only'
        elif method == 'anvil_metadata': result = {'forkedNetwork': {'chainId': self.metadata_chain, 'forkBlockNumber': 123, 'forkBlockHash': BLOCK_HASH, 'forkUrl': 'https://example.invalid/' + SECRET}}
        elif method == 'eth_chainId': result = '0x1'
        elif method == 'eth_getBlockByNumber':
            result = {'number': '0x7b', 'hash': None} if self.bad_post_anchor and sum(x['method'] == method for x in self.calls) == 3 else block
        elif method == 'eth_getCode': result = '0x' if params[0] == ACTOR else '0x6000'
        elif method == 'eth_getBalance': result = hex(self.native)
        elif method == 'eth_call':
            target, data = params[0]['to'], params[0]['data']
            if data == '0x0dfe1681': result = encoded(int(TOKEN, 16))
            elif data == '0xd21220a7': result = encoded(int(executor.WETH[1], 16))
            elif data == '0x0902f1ac': result = '0x' + ''.join(format(x, '064x') for x in (0 if self.empty_pool else 10000, 20000, 1700000000))
            elif data == '0xc45a0155': result = encoded(int(FACTORY, 16))
            elif data.startswith('0xe6a43905'): result = encoded(int(POOL, 16))
            elif data.startswith('0x70a08231'): result = encoded(self.weth if target == executor.WETH[1] else self.token)
            elif data.startswith('0xdd62ed3e'): result = encoded(self.weth_allowance if target == executor.WETH[1] else self.token_allowance)
            else: raise AssertionError(data)
        elif method == 'evm_snapshot': result = '0x1'
        elif method == 'evm_revert':
            self.reverted = True
            self.weth = self.token = self.weth_allowance = self.token_allowance = 0
            result = True
        elif method == 'anvil_impersonateAccount':
            self.impersonating = True
            if self.lost_impersonation_reply:
                return {'id': body['id'], 'error': {'code': -1, 'message': SECRET}}
            result = None
        elif method == 'anvil_stopImpersonatingAccount':
            if self.cleanup_fails:
                return {'id': body['id'], 'error': {'code': -1, 'message': SECRET}}
            self.impersonating = False; result = None
        elif method == 'anvil_setBalance': self.native = int(params[1], 16); result = None
        elif method == 'eth_sendTransaction':
            tx = params[0]; self.sent.append(tx)
            data, target = tx['data'], tx['to']
            if data == '0xd0e30db0': stage = 'wrap_native'
            elif data.startswith('0x095ea7b3'): stage = 'approve_weth' if target == executor.WETH[1] else 'approve_token'
            elif data.startswith('0x5c11d795'):
                path0 = '0x' + data[10 + 6 * 64 + 24:10 + 7 * 64]
                stage = 'buy' if path0 == executor.WETH[1] else 'sell'
            else: raise AssertionError(data)
            ok = stage != self.fail_stage
            if ok:
                if stage == 'wrap_native': self.weth += int(tx['value'], 16)
                elif stage == 'approve_weth': self.weth_allowance = int(data[-64:], 16)
                elif stage == 'approve_token': self.token_allowance = int(data[-64:], 16)
                elif stage == 'buy': self.weth -= 100; self.token += 1000
                elif stage == 'sell': self.token -= 500 if self.partial_sell else 1000; self.weth += 80
            result = '0x' + format(len(self.sent), '064x')
            self.receipts[result] = {'transactionHash': result, 'status': '0x1' if ok else '0x0', 'gasUsed': '0x5208', 'blockHash': BLOCK_HASH, 'blockNumber': '0x7c'}
        elif method == 'eth_getTransactionReceipt': result = self.receipts[params[0]]
        elif method == 'debug_traceTransaction': result = {'synthetic': True, 'failed': True}
        else: raise AssertionError(method)
        return {'jsonrpc': '2.0', 'id': body['id'], 'result': result}


class ForkExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_fake(self, fake, value=None):
        with patch.object(executor.LocalRPC, '_send', lambda _, body: fake.send(body)), patch.object(executor.secrets, 'token_hex', return_value='e' * 40):
            result = executor.execute(value or plan(), 'http://127.0.0.1:8545', self.root / 'run')
        saved = json.loads((self.root / 'run' / 'result.json').read_text(encoding='utf-8'))
        self.assertEqual(result, saved)
        return result

    def test_coherent_sequence_and_cleanup_no_gate_vote(self):
        fake = MockNode()
        result = self.run_fake(fake)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['buy_received_token_base_units'], '1000')
        self.assertEqual(result['sell_received_weth_base_units'], '80')
        self.assertEqual(result['sell_spent_token_base_units'], '1000')
        self.assertTrue(result['anchor_postcheck'])
        self.assertEqual(result['pool_state']['reserve0_base_units'], '10000')
        self.assertEqual([s['stage'] for s in result['steps']], ['wrap_native', 'approve_weth', 'buy', 'approve_token', 'sell'])
        self.assertTrue(result['cleanup_succeeded'])
        self.assertTrue(fake.reverted)
        self.assertFalse(fake.impersonating)
        self.assertEqual(result['gate_status'], 'unknown')
        self.assertEqual(result['gate_votes'], 0)
        self.assertEqual(result['rpc_capture']['sha256'], hashlib.sha256((self.root / 'run' / 'rpc.jsonl').read_bytes()).hexdigest())
        self.assertNotIn(SECRET, (self.root / 'run' / 'rpc.jsonl').read_text(encoding='utf-8'))

    def test_sell_revert_is_observation_not_restriction(self):
        fake = MockNode(fail_stage='sell')
        result = self.run_fake(fake)
        self.assertEqual(result['status'], 'sell_incomplete')
        self.assertEqual(result['steps'][-1]['status'], 'reverted_or_unknown')
        self.assertTrue(result['steps'][-1]['trace']['synthetic'])
        self.assertEqual(result['gate_votes'], 0)
        self.assertTrue(result['cleanup_succeeded'])

    def test_bad_fork_metadata_stops_before_mutation(self):
        fake = MockNode(metadata_chain=8453)
        result = self.run_fake(fake)
        self.assertEqual(result['status'], 'incomplete')
        self.assertFalse(fake.sent)
        self.assertNotIn('anvil_setBalance', [x['method'] for x in fake.calls])

    def test_cleanup_failure_is_reported_and_snapshot_reverted(self):
        fake = MockNode(cleanup_fails=True)
        result = self.run_fake(fake)
        self.assertFalse(result['cleanup_succeeded'])
        self.assertEqual(result['status'], 'cleanup_failed')
        self.assertTrue(fake.reverted)
        self.assertNotIn(SECRET, (self.root / 'run' / 'rpc.jsonl').read_text(encoding='utf-8'))

    def test_remote_or_credential_endpoint_rejected_before_output(self):
        for endpoint in ('https://example.com', 'http://localhost:8545', 'http://127.0.0.1:8545/path', 'http://key@127.0.0.1:8545'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                executor.execute(plan(), endpoint, self.root / 'never')
        self.assertFalse((self.root / 'never').exists())

    def test_plan_rejects_implicit_actor_and_unknown_fields(self):
        bad = plan(); bad['actor'] = ACTOR
        with self.assertRaisesRegex(ValueError, 'unsupported fields'):
            executor.execute(bad, 'http://127.0.0.1:8545', self.root / 'never')

    def test_partial_sell_is_not_a_complete_round_trip(self):
        result = self.run_fake(MockNode(partial_sell=True))
        self.assertEqual(result['status'], 'sell_partial')
        self.assertEqual(result['token_balance_after_sell'], '500')
        self.assertEqual(result['gate_votes'], 0)

    def test_bad_post_anchor_fails_closed_and_still_cleans_up(self):
        fake = MockNode(bad_post_anchor=True)
        result = self.run_fake(fake)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['error_type'], 'anchor_postcheck_failed')
        self.assertTrue(result['cleanup_succeeded'])
        self.assertTrue(fake.reverted)

    def test_lost_impersonation_reply_still_attempts_cleanup(self):
        fake = MockNode(lost_impersonation_reply=True)
        result = self.run_fake(fake)
        self.assertEqual(result['status'], 'incomplete')
        self.assertTrue(result['cleanup_succeeded'])
        self.assertFalse(fake.impersonating)
        self.assertTrue(fake.reverted)

    def test_buy_failure_does_not_attempt_token_approval_or_sell(self):
        fake = MockNode(fail_stage='buy')
        result = self.run_fake(fake)
        self.assertEqual(result['status'], 'buy_incomplete')
        self.assertEqual([s['stage'] for s in result['steps']], ['wrap_native', 'approve_weth', 'buy'])
        self.assertEqual(result['gate_votes'], 0)
        self.assertTrue(result['cleanup_succeeded'])

    def test_budget_exhaustion_reserves_cleanup_calls(self):
        fake = MockNode()
        bounded = plan(); bounded['max_rpc_calls'] = 35
        result = self.run_fake(fake, bounded)
        self.assertNotEqual(result['status'], 'completed')
        self.assertLessEqual(result['local_rpc_attempts'], 35)
        self.assertTrue(result['cleanup_succeeded'])
        self.assertTrue(fake.reverted)

    def test_empty_pool_is_unavailable_before_any_mutation(self):
        fake = MockNode(empty_pool=True)
        result = self.run_fake(fake)
        self.assertEqual(result['status'], 'incomplete')
        self.assertFalse(fake.sent)
        self.assertNotIn('evm_snapshot', [x['method'] for x in fake.calls])


if __name__ == '__main__':
    unittest.main()
