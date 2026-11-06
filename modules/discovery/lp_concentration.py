"""G07 experimental V2 LP-address concentration, bound to finalized RPC calls."""
import hashlib
import json
import re
from decimal import Decimal, localcontext

import discovery
import market_activity as market

FORMAT = 'G07_V2_LP_V1'
EXCLUDED = {'0x' + '0' * 40, '0x' + '0' * 36 + 'dead'}


def usable_holder(address, pool):
    return (isinstance(address, str) and re.fullmatch(r'0x[0-9a-f]{40}', address)
            and address not in EXCLUDED and address != pool and int(address, 16) > 0xffff)


def verify(record, root, as_of):
    token = record['identity']['address'].lower()
    if record['identity']['chain_id'] != 1 or record['candidate_id'] != discovery.identity(1, token):
        raise ValueError('G07 supports Ethereum V2 candidates only')
    evidence = [e for e in record['evidence'] if FORMAT in e.get('limitations', [])]
    if not evidence:
        raise ValueError('no LP concentration evidence')
    e = max(evidence, key=lambda x: x.get('fetched_at') or '')
    if not re.fullmatch(r'snapshots/[0-9a-f]{64}\.json', e.get('source', '')):
        raise ValueError('invalid LP evidence path')
    path = root / e['source']
    if path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('unsafe LP snapshot')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != e.get('sha256') or e.get('id') != e.get('sha256') or path.name != e.get('sha256', '') + '.json':
        raise ValueError('LP snapshot digest mismatch')
    doc = json.loads(raw)
    if (doc.get('format') != FORMAT or doc.get('candidate_id') != record['candidate_id']
        or doc.get('chain_id') != 1 or doc.get('rpc_url') != 'https://ethereum-rpc.publicnode.com'):
        raise ValueError('LP snapshot provenance mismatch')
    pool = doc.get('pool', '').lower()
    if not re.fullmatch(r'0x[0-9a-f]{40}', pool):
        raise ValueError('invalid pool address')
    point = doc['point']
    tag = point['block_tag']
    if point.get('finality') != 'finalized' or not re.fullmatch(r'0x[0-9a-fA-F]{64}', point.get('block_hash', '')):
        raise ValueError('missing finalized block provenance')
    if (e.get('block_number') != market.integer(tag)
        or discovery.stamp(e['observed_at']).timestamp() != point['block_timestamp']):
        raise ValueError('LP evidence block/time mismatch')
    trace = doc.get('rpc_trace')
    if not isinstance(trace, list) or not trace:
        raise ValueError('missing LP RPC transcript')

    def match(method, params):
        results = []
        for entry in trace:
            if not isinstance(entry, dict) or not isinstance(entry.get('request'), dict) or not isinstance(entry.get('response'), dict):
                raise ValueError('invalid LP RPC transcript')
            request, response = entry['request'], entry['response']
            if request.get('method') == method and request.get('params') == params:
                if request.get('id') != response.get('id') or 'error' in response or 'result' not in response:
                    raise ValueError('invalid LP RPC response')
                results.append(response['result'])
        if not results or any(value != results[0] for value in results):
            raise ValueError('missing or conflicting LP RPC response')
        return results[0]

    if match('eth_chainId', []) != '0x1':
        raise ValueError('LP chain mismatch')
    block = match('eth_getBlockByNumber', ['finalized', False])
    if (not isinstance(block, dict) or block.get('number') != tag or block.get('hash') != point['block_hash']
        or market.integer(block.get('timestamp')) != point['block_timestamp']):
        raise ValueError('LP block mismatch')

    def checked(name, target, selector):
        value = market.response(point, name, target, selector)
        if match('eth_call', [{'to': target, 'data': selector}, tag]) != value:
            raise ValueError('LP call transcript mismatch')
        if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', value):
            raise ValueError('invalid LP ABI word')
        return value

    token0 = market.address_word(checked('token0', pool, '0x0dfe1681'))
    token1 = market.address_word(checked('token1', pool, '0xd21220a7'))
    if {token0, token1} != {token, market.WETH}:
        raise ValueError('LP pool token mismatch')
    if market.address_word(checked('factory', pool, '0xc45a0155')) != market.FACTORY:
        raise ValueError('LP pool factory mismatch')
    pair = '0xe6a43905' + token[2:].rjust(64, '0') + market.WETH[2:].rjust(64, '0')
    if market.address_word(checked('factory_pair', market.FACTORY, pair)) != pool:
        raise ValueError('LP factory pair mismatch')
    supply = market.integer(checked('total_supply', pool, '0x18160ddd'))
    if supply <= 0:
        raise ValueError('LP supply unavailable')
    holders = doc.get('holders')
    if not isinstance(holders, list) or not 1 <= len(holders) <= 10:
        raise ValueError('LP holder sample unavailable')
    seen = set()
    largest, largest_address, sampled_total = 0, None, 0
    for item in holders:
        address = item['address']
        if not usable_holder(address, pool) or address in seen:
            raise ValueError('invalid LP holder sample')
        seen.add(address)
        selector = '0x70a08231' + address[2:].rjust(64, '0')
        name = 'balance:' + address
        balance = market.integer(checked(name, pool, selector))
        if balance > supply:
            raise ValueError('LP balance exceeds supply')
        sampled_total += balance
        if balance > largest:
            largest, largest_address = balance, address
    if sampled_total > supply:
        raise ValueError('sampled LP balances exceed supply')
    if largest == 0:
        raise ValueError('no sampled address holds pool LP tokens')
    with localcontext() as ctx:
        ctx.prec = 60
        percentage = Decimal(largest) * 100 / Decimal(supply)
    return {'triggered': True if largest * 100 > supply * 15 else None,
            'detail': 'Largest sampled direct LP-address balance as a share of total supply in one canonical V2/WETH pool. Addresses can represent pooled custody; sample is incomplete. Below 15% remains unknown.',
            'measurements': [{'label': 'Largest sampled LP balance', 'value': str(round(percentage, 4)), 'unit': '% of pool LP supply'},
                             {'label': 'LP address', 'value': largest_address, 'unit': ''},
                             {'label': 'Addresses sampled', 'value': len(holders), 'unit': ''}],
            'evidence_ids': [e['id']]}
