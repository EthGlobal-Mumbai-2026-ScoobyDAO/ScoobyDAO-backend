"""Local-Anvil-only coherent V2 buy/approve/sell experiment; never a gate verdict.

Requires a dedicated, already-running fork. It does not create a fork, connect
to an upstream RPC, select candidates, or publish findings. Upstream archive
traffic initiated by the fork must be budgeted and controlled separately.
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ADDRESS = re.compile(r'^0x[0-9a-f]{40}$')
HASH = re.compile(r'^0x[0-9a-f]{64}$')
WETH = {1: '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2',
        8453: '0x4200000000000000000000000000000000000006'}
MAX_CALLS = 120
MAX_RESPONSE = 4_000_000
ALLOWED = {'web3_clientVersion', 'anvil_metadata', 'eth_chainId', 'eth_getBlockByNumber',
           'eth_getCode', 'eth_getBalance', 'eth_call', 'evm_snapshot', 'evm_revert',
           'anvil_setBalance', 'anvil_impersonateAccount', 'anvil_stopImpersonatingAccount',
           'eth_sendTransaction', 'eth_getTransactionReceipt', 'debug_traceTransaction'}


def local_endpoint(value):
    u = urllib.parse.urlsplit(value)
    if (u.scheme != 'http' or u.hostname not in ('127.0.0.1', '::1') or not u.port
        or u.username or u.password or u.query or u.fragment or u.path not in ('', '/')):
        raise ValueError('only a numeric loopback HTTP endpoint without credentials or paths is allowed')
    return value


def word(n):
    if type(n) is not int or not 0 <= n < 2**256:
        raise ValueError('invalid uint256')
    return format(n, '064x')


def addr_word(address):
    if not isinstance(address, str) or not ADDRESS.fullmatch(address):
        raise ValueError('invalid lowercase address')
    return address[2:].rjust(64, '0')


def abi_address(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', value) or int(value, 16) >= 2**160:
        raise ValueError('invalid ABI address response')
    return '0x' + value[-40:].lower()


def abi_uint(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', value):
        raise ValueError('invalid ABI uint response')
    return int(value, 16)


def block_matches(value, number, expected_hash):
    if not isinstance(value, dict) or not isinstance(value.get('hash'), str) or not isinstance(value.get('number'), str):
        return False
    try:
        return value['hash'].lower() == expected_hash and int(value['number'], 16) == number
    except ValueError:
        return False


def positive_decimal(value, name, zero=False):
    if not isinstance(value, str) or not re.fullmatch(r'0|[1-9][0-9]*', value):
        raise ValueError(name + ' must be a base-unit decimal string')
    number = int(value)
    if number >= 2**256 or (not zero and number == 0):
        raise ValueError('invalid ' + name)
    return number


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get('profile') != 'scooby.g02-fork-plan/0':
        raise ValueError('unknown execution plan')
    if set(plan) != {'profile', 'candidate_id', 'pool', 'router', 'block', 'amount_in',
                     'minimum_buy_out', 'minimum_sell_out', 'native_funding', 'deadline', 'gas_limit', 'max_rpc_calls'}:
        raise ValueError('execution plan has missing or unsupported fields')
    identity = plan['candidate_id']
    if not isinstance(identity, str) or not re.fullmatch(r'(1|8453):0x[0-9a-f]{40}', identity):
        raise ValueError('invalid candidate identity')
    chain, token = identity.split(':'); chain = int(chain)
    for key in ('pool', 'router'):
        if not isinstance(plan[key], str) or not ADDRESS.fullmatch(plan[key]):
            raise ValueError('invalid ' + key)
    if len({token, plan['pool'], plan['router'], WETH[chain]}) != 4:
        raise ValueError('token, WETH, pool and router must be distinct')
    block = plan['block']
    if (not isinstance(block, dict) or set(block) != {'number', 'hash'} or type(block['number']) is not int
        or block['number'] <= 0 or not isinstance(block['hash'], str) or not HASH.fullmatch(block['hash'])):
        raise ValueError('invalid block anchor')
    amount = positive_decimal(plan['amount_in'], 'amount_in')
    positive_decimal(plan['minimum_buy_out'], 'minimum_buy_out', zero=True)
    positive_decimal(plan['minimum_sell_out'], 'minimum_sell_out', zero=True)
    funding = positive_decimal(plan['native_funding'], 'native_funding')
    if funding <= amount:
        raise ValueError('native funding must cover WETH input and gas')
    if type(plan['deadline']) is not int or plan['deadline'] <= 0:
        raise ValueError('invalid explicit deadline')
    if type(plan['gas_limit']) is not int or not 21000 <= plan['gas_limit'] <= 30_000_000:
        raise ValueError('invalid explicit gas limit')
    if type(plan['max_rpc_calls']) is not int or not 35 <= plan['max_rpc_calls'] <= MAX_CALLS:
        raise ValueError('max_rpc_calls must be 35-120 including cleanup')
    return chain, token


def swap_data(amount_in, minimum_out, path, actor, deadline):
    # swapExactTokensForTokensSupportingFeeOnTransferTokens(uint,uint,address[],address,uint)
    return ('0x5c11d795' + word(amount_in) + word(minimum_out) + word(160) + addr_word(actor)
            + word(deadline) + word(2) + addr_word(path[0]) + addr_word(path[1]))


class RPCError(Exception):
    pass


class LocalRPC:
    def __init__(self, endpoint, root, budget):
        self.endpoint = local_endpoint(endpoint)
        self.root, self.budget, self.calls = root, budget, 0
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def _send(self, body):
        req = urllib.request.Request(self.endpoint, data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
        with self.opener.open(req, timeout=30) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise RPCError('response too large')
        return json.loads(raw)

    def call(self, method, params, cleanup=False):
        if method not in ALLOWED:
            raise ValueError('RPC method not allowed')
        # Reserve three calls for the anchor recheck and both cleanup operations.
        if self.calls >= self.budget - (0 if cleanup else 3):
            raise RPCError('local RPC budget exhausted')
        self.calls += 1
        body = {'jsonrpc': '2.0', 'id': self.calls, 'method': method, 'params': params}
        event = {'request': body, 'attempted_at': dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            response = self._send(body)
            if not isinstance(response, dict) or response.get('id') != body['id']:
                raise RPCError('invalid RPC response')
            if 'error' in response or 'result' not in response:
                error = response.get('error')
                code = error.get('code') if isinstance(error, dict) else None
                event.update(status='rpc_error', error_code=code if type(code) is int else None)
                raise RPCError('local RPC returned an error')
            result = response['result']
            # anvil_metadata may contain an archive URL/API key. Never persist it.
            event.update(status='ok', result='[redacted]' if method == 'anvil_metadata' else result)
            return result
        except (OSError, ValueError, TypeError, urllib.error.URLError, RPCError) as exc:
            event.setdefault('status', 'transport_or_format_error')
            raise RPCError(type(exc).__name__ + ': local RPC operation failed') from None
        finally:
            with (self.root / 'rpc.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + '\n')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def execute(plan, endpoint, output):
    chain, token = validate_plan(plan)
    local_endpoint(endpoint)  # Reject remote URLs before creating any artifact.
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    rpc = LocalRPC(endpoint, root, plan['max_rpc_calls'])
    result = {'profile': 'scooby.g02-fork-execution/0', 'candidate_id': plan['candidate_id'],
              'block': plan['block'], 'pool': plan['pool'], 'router': plan['router'], 'weth': WETH[chain],
              'started_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'plan': plan,
              'status': 'incomplete', 'steps': [], 'local_overrides': [], 'gate_status': 'unknown',
              'gate_votes': 0, 'live_verdict': 'not_determined', 'cleanup_succeeded': None,
        'limitations': ['Local fork experiment only; execution/revert is not semantic proof of a token restriction.',
                              'Trace/source/controller attribution, independent review and an accepted profile remain required.',
                              'The fork can make upstream archive calls; this tool does not enforce that external budget.']}
    snapshot, impersonating = None, False
    actor = '0x' + secrets.token_hex(20)
    if int(actor, 16) <= 0xffff or actor in (token, plan['pool'], plan['router'], WETH[chain]):
        raise ValueError('generated actor is not an eligible local test address')
    result['actor'] = actor
    def call_eth(to, data):
        return rpc.call('eth_call', [{'to': to, 'data': data}, 'latest'])
    def balance(contract):
        return abi_uint(call_eth(contract, '0x70a08231' + addr_word(actor)))
    def allowance(contract):
        return abi_uint(call_eth(contract, '0xdd62ed3e' + addr_word(actor) + addr_word(plan['router'])))
    def transact(stage, to, data, value=0):
        tx = {'from': actor, 'to': to, 'data': data, 'value': hex(value), 'gas': hex(plan['gas_limit'])}
        step = {'stage': stage, 'transaction': tx, 'status': 'attempted'}
        result['steps'].append(step)
        try:
            txhash = rpc.call('eth_sendTransaction', [tx])
            if not isinstance(txhash, str) or not HASH.fullmatch(txhash.lower()):
                raise RPCError('invalid transaction hash')
            step['transaction_hash'] = txhash
            receipt = rpc.call('eth_getTransactionReceipt', [txhash])
            if (not isinstance(receipt, dict) or not isinstance(receipt.get('transactionHash'), str)
                or receipt['transactionHash'].lower() != txhash.lower()
                or not isinstance(receipt.get('blockHash'), str) or not HASH.fullmatch(receipt['blockHash'].lower())
                or not isinstance(receipt.get('blockNumber'), str) or not re.fullmatch(r'0x[0-9a-fA-F]+', receipt['blockNumber'])
                or int(receipt['blockNumber'], 16) <= plan['block']['number']):
                raise RPCError('receipt unavailable')
            step['receipt'] = receipt
            if receipt.get('status') != '0x1':
                step['status'] = 'reverted_or_unknown'
                try:
                    step['trace'] = rpc.call('debug_traceTransaction', [txhash, {}])
                except RPCError:
                    step['trace'] = None
                return False
            step['status'] = 'success'
            if stage in ('buy', 'sell'):
                try:
                    step['trace'] = rpc.call('debug_traceTransaction', [txhash, {'tracer': 'callTracer'}])
                except RPCError:
                    step['trace'] = None
            return True
        except RPCError:
            step['status'] = 'rpc_or_execution_unavailable'
            return False
    try:
        version = rpc.call('web3_clientVersion', [])
        if not isinstance(version, str) or not version.lower().startswith('anvil/'):
            raise ValueError('dedicated Anvil engine required')
        metadata = rpc.call('anvil_metadata', [])
        fork = metadata.get('forkedNetwork') if isinstance(metadata, dict) else None
        if (not isinstance(fork, dict) or fork.get('chainId') != chain
            or fork.get('forkBlockNumber') != plan['block']['number']
            or str(fork.get('forkBlockHash', '')).lower() != plan['block']['hash']):
            raise ValueError('Anvil fork metadata does not match the plan')
        if int(rpc.call('eth_chainId', []), 16) != chain:
            raise ValueError('fork chain mismatch')
        anchor = rpc.call('eth_getBlockByNumber', [hex(plan['block']['number']), False])
        latest = rpc.call('eth_getBlockByNumber', ['latest', False])
        if (not block_matches(anchor, plan['block']['number'], plan['block']['hash'])
            or not block_matches(latest, plan['block']['number'], plan['block']['hash'])):
            raise ValueError('fork anchor or clean head mismatch')
        anchor_timestamp = int(anchor['timestamp'], 16)
        result['block_time_utc'] = dt.datetime.fromtimestamp(anchor_timestamp, dt.timezone.utc).isoformat()
        if plan['deadline'] <= anchor_timestamp:
            raise ValueError('deadline must be after the anchor timestamp')
        result['engine'] = {'name': 'anvil', 'version': version, 'fork_chain_id': chain,
                            'fork_block_number': fork['forkBlockNumber'], 'fork_block_hash': plan['block']['hash']}
        for name, address in [('token', token), ('weth', WETH[chain]), ('pool', plan['pool']), ('router', plan['router'])]:
            code = rpc.call('eth_getCode', [address, 'latest'])
            if not isinstance(code, str) or not re.fullmatch(r'0x(?:[0-9a-fA-F]{2})+', code):
                raise ValueError(name + ' code unavailable')
            result.setdefault('code_sha256', {})[name] = hashlib.sha256(bytes.fromhex(code[2:])).hexdigest()
        if rpc.call('eth_getCode', [actor, 'latest']) != '0x':
            raise ValueError('generated actor unexpectedly has code')
        result['actor_native_before_override_wei'] = str(int(rpc.call('eth_getBalance', [actor, 'latest']), 16))
        token0 = abi_address(call_eth(plan['pool'], '0x0dfe1681'))
        token1 = abi_address(call_eth(plan['pool'], '0xd21220a7'))
        if {token0, token1} != {token, WETH[chain]}:
            raise ValueError('pool tokens do not match the declared path')
        reserves = call_eth(plan['pool'], '0x0902f1ac')
        if not isinstance(reserves, str) or not re.fullmatch(r'0x[0-9a-fA-F]{192}', reserves):
            raise ValueError('pool reserves unavailable')
        r0, r1, updated = (int(reserves[2 + i:2 + i + 64], 16) for i in (0, 64, 128))
        if not (0 < r0 < 2**112 and 0 < r1 < 2**112 and 0 <= updated < 2**32):
            raise ValueError('invalid or empty pool reserves')
        result['pool_state'] = {'token0': token0, 'token1': token1, 'reserve0_base_units': str(r0),
                                'reserve1_base_units': str(r1), 'block_timestamp_last_uint32': updated}
        pool_factory = abi_address(call_eth(plan['pool'], '0xc45a0155'))
        router_factory = abi_address(call_eth(plan['router'], '0xc45a0155'))
        if pool_factory != router_factory:
            raise ValueError('router and pool factories do not match')
        pair = '0xe6a43905' + addr_word(token) + addr_word(WETH[chain])
        if abi_address(call_eth(pool_factory, pair)) != plan['pool']:
            raise ValueError('factory does not recognize pool')
        snapshot = rpc.call('evm_snapshot', [])
        if not isinstance(snapshot, str) or not snapshot.startswith('0x'):
            raise ValueError('snapshot unavailable')
        impersonating = True  # Clean up even if a successful RPC response is lost.
        rpc.call('anvil_impersonateAccount', [actor])
        result['local_overrides'].append({'kind': 'account_impersonation', 'address': actor})
        rpc.call('anvil_setBalance', [actor, hex(int(plan['native_funding']))])
        result['local_overrides'].append({'kind': 'native_balance', 'address': actor, 'amount_wei': plan['native_funding']})
        if int(rpc.call('eth_getBalance', [actor, 'latest']), 16) != int(plan['native_funding']):
            raise ValueError('native funding override did not take effect')
        token_before, weth_before = balance(token), balance(WETH[chain])
        if token_before or weth_before:
            raise ValueError('generated actor must begin with zero token and WETH balances')
        amount = int(plan['amount_in'])
        if not transact('wrap_native', WETH[chain], '0xd0e30db0', amount):
            result['status'] = 'setup_incomplete'; return result
        if balance(WETH[chain]) != amount:
            raise ValueError('unexpected WETH deposit result')
        if not transact('approve_weth', WETH[chain], '0x095ea7b3' + addr_word(plan['router']) + word(amount)):
            result['status'] = 'setup_incomplete'; return result
        if allowance(WETH[chain]) < amount:
            raise ValueError('insufficient WETH allowance')
        before_buy = balance(WETH[chain])
        buy = swap_data(amount, int(plan['minimum_buy_out']), [WETH[chain], token], actor, plan['deadline'])
        if not transact('buy', plan['router'], buy):
            result['status'] = 'buy_incomplete'; return result
        bought = balance(token)
        weth_after_buy = balance(WETH[chain])
        if weth_after_buy > before_buy:
            raise ValueError('WETH balance increased during buy')
        result['buy_spent_weth_base_units'] = str(before_buy - weth_after_buy)
        if before_buy - weth_after_buy != amount:
            raise ValueError('buy did not spend the declared WETH amount')
        result['buy_received_token_base_units'] = str(bought)
        if bought <= 0:
            result['status'] = 'buy_zero_received'; return result
        if not transact('approve_token', token, '0x095ea7b3' + addr_word(plan['router']) + word(bought)):
            result['status'] = 'token_approval_incomplete'; return result
        if allowance(token) < bought:
            raise ValueError('insufficient token allowance')
        before_sell = balance(WETH[chain])
        sell = swap_data(bought, int(plan['minimum_sell_out']), [token, WETH[chain]], actor, plan['deadline'])
        if not transact('sell', plan['router'], sell):
            result['status'] = 'sell_incomplete'; return result
        after_sell = balance(WETH[chain])
        tokens_after_sell = balance(token)
        if after_sell < before_sell:
            raise ValueError('WETH balance decreased during sell')
        if tokens_after_sell > bought:
            raise ValueError('token balance increased during sell')
        result['sell_received_weth_base_units'] = str(after_sell - before_sell)
        result['sell_spent_token_base_units'] = str(bought - tokens_after_sell)
        result['token_balance_after_sell'] = str(tokens_after_sell)
        result['actor_native_after_sell_wei'] = str(int(rpc.call('eth_getBalance', [actor, 'latest']), 16))
        result['status'] = ('sell_zero_received' if after_sell == before_sell else
                            'sell_zero_tokens_spent' if tokens_after_sell == bought else
                            'sell_partial' if tokens_after_sell else 'completed')
        return result
    except (ValueError, KeyError, TypeError, OverflowError, RPCError) as exc:
        result['status'] = 'incomplete'
        result['error_type'] = type(exc).__name__
        return result
    finally:
        cleanup = True
        result['cleanup_attempted'] = {'anchor_recheck': snapshot is not None,
                                       'stop_impersonation': impersonating,
                                       'snapshot_revert': snapshot is not None}
        if snapshot is not None:
            try:
                last_anchor = rpc.call('eth_getBlockByNumber', [hex(plan['block']['number']), False], cleanup=True)
                result['anchor_postcheck'] = block_matches(last_anchor, plan['block']['number'], plan['block']['hash'])
            except (RPCError, ValueError, TypeError, OSError):
                result['anchor_postcheck'] = False
            if not result['anchor_postcheck']:
                result['observed_status'] = result['status']
                result['status'] = 'incomplete'
                result['error_type'] = 'anchor_postcheck_failed'
        if impersonating:
            try: rpc.call('anvil_stopImpersonatingAccount', [actor], cleanup=True)
            except (RPCError, ValueError, OSError, TypeError): cleanup = False
        if snapshot is not None:
            try: cleanup = rpc.call('evm_revert', [snapshot], cleanup=True) is True and cleanup
            except (RPCError, ValueError, OSError, TypeError): cleanup = False
        result['cleanup_succeeded'] = cleanup
        if not cleanup:
            result['observed_status'] = result['status']
            result['status'] = 'cleanup_failed'
        result['local_rpc_attempts'] = rpc.calls
        result['finished_at_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        log = root / 'rpc.jsonl'
        if log.is_file():
            result['rpc_capture'] = {'path': 'rpc.jsonl', 'sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
        (root / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--endpoint', required=True, help='numeric loopback HTTP URL of a dedicated local Anvil fork')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    outcome = execute(json.loads(args.plan.read_text(encoding='utf-8')), args.endpoint, args.output)
    print(json.dumps({'status': outcome['status'], 'gate_status': outcome['gate_status'],
                      'cleanup_succeeded': outcome['cleanup_succeeded'], 'local_rpc_attempts': outcome['local_rpc_attempts']}))
    raise SystemExit(0 if outcome['status'] == 'completed' and outcome['cleanup_succeeded'] else 1)
