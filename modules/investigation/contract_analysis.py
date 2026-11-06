"""Conservative, evidence-addressed static analysis of supplied EVM contract sources.

This is a lexical navigation aid, not a Solidity parser, compiler, audit or sell simulation.
The caller must capture and independently validate source and RPC provenance.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

_ADDRESS = re.compile(r'^0x[0-9a-fA-F]{40}$')
_HEX = re.compile(r'^0x(?:[0-9a-fA-F]{2})*$')
_FUNCTION = re.compile(r'\b(function\s+([A-Za-z_$][\w$]*)|constructor|fallback|receive)\s*\(')
_CATEGORIES = {
    'transfer_sell_restrictions': re.compile(r'\b(?:require|revert|assert|tradingEnabled|tradingOpen|cooldown|maxTxAmount|maxTransactionAmount|maxWallet|isPair|automatedMarketMakerPairs)\b', re.I),
    'blacklist_controls': re.compile(r'\b(?:blacklist(?:ed)?|isBlacklisted|blocklist(?:ed)?|denylist|bots)\b', re.I),
    'tax_fee_controls': re.compile(r'\b(?:tax|taxFee|buyTax|sellTax|fee|fees|marketingFee|liquidityFee)\b', re.I),
    'admin_authority': re.compile(r'\b(?:onlyOwner|onlyRole|owner|admin|administrator|hasRole|grantRole|revokeRole)\b', re.I),
    'upgrade_proxy_controls': re.compile(r'\b(?:upgradeTo|upgradeToAndCall|implementation|delegatecall|_authorizeUpgrade|changeAdmin)\b', re.I),
    'mint_controls': re.compile(r'\b(?:mint|_mint|increaseSupply)\b', re.I),
    'external_transfer_dependency': re.compile(r'\b(?:call|staticcall|delegatecall|xor)\s*\(', re.I),
}
_TRANSFER = re.compile(r'^(?:transfer|transferFrom|_transfer|_update|_beforeTokenTransfer|_afterTokenTransfer)$', re.I)
_CALL = re.compile(r'\b([A-Za-z_$][\w$]*)\s*\(')


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _code(value: str) -> str:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise ValueError('runtime bytecode must be even-length hex')
    return value.lower()


def _mask(source: str) -> str:
    """Blank comments/strings while preserving offsets and line numbers."""
    pattern = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
    return pattern.sub(lambda m: ''.join('\n' if c == '\n' else ' ' for c in m.group()), source)


def _functions(text: str):
    masked = _mask(text)
    for match in _FUNCTION.finditer(masked):
        opening = masked.find('{', match.end())
        semicolon = masked.find(';', match.end())
        if opening < 0 or (0 <= semicolon < opening):
            continue
        depth = 1; end = opening + 1
        while depth and end < len(masked):
            depth += (masked[end] == '{') - (masked[end] == '}')
            end += 1
        if depth:
            continue
        name = match.group(2) or match.group(1)
        yield name, match.start(), end, masked[match.start():end]


IMPLEMENTATION_SLOT = '0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc'


def rpc_plan(candidate: dict, block: dict, implementation_address: str | None = None) -> dict:
    """Plan for pinned_rpc_capture.capture; caller supplies authorization and budget."""
    chain, address = candidate.get('chain_id'), candidate.get('address', '')
    if isinstance(chain, bool) or not isinstance(chain, int) or chain <= 0 or not _ADDRESS.fullmatch(address):
        raise ValueError('positive chain id and EVM token address required')
    if not isinstance(block.get('number'), int) or block['number'] < 0 or not re.fullmatch(r'0x[0-9a-fA-F]{64}', str(block.get('hash', ''))):
        raise ValueError('pinned block number and hash required')
    tag = hex(block['number'])
    ops = [{'method': 'eth_getCode', 'params': [address.lower(), tag]},
           {'method': 'eth_getStorageAt', 'params': [address.lower(), IMPLEMENTATION_SLOT, tag]}]
    if implementation_address:
        if not _ADDRESS.fullmatch(implementation_address):
            raise ValueError('invalid implementation address')
        ops.append({'method': 'eth_getCode', 'params': [implementation_address.lower(), tag]})
    return {'candidate_id': f'{chain}:{address.lower()}', 'block': block, 'operations': ops}


def from_pinned_capture(folder: str | Path) -> dict:
    """Recheck persisted pinned RPC evidence bytes and turn them into analysis input."""
    root = Path(folder)
    manifest = json.loads((root / 'capture.json').read_text(encoding='utf-8'))
    if manifest.get('profile') != 'scooby.pinned-rpc-capture/1':
        raise ValueError('unsupported pinned capture')
    chain_text, address = manifest['candidate_id'].split(':', 1)
    chain = int(chain_text); block = manifest['block']; plan = rpc_plan({'chain_id': chain, 'address': address}, block)
    records = manifest['records']
    if not 5 <= len(records) <= 6 or manifest.get('attempts') != len(records):
        raise ValueError('unexpected capture size')
    responses = []
    for index, rec in enumerate(records, 1):
        req_name, resp_name = rec.get('request_path'), rec.get('response_path')
        if req_name != f'{index:03}-request.json' or resp_name != f'{index:03}-response.json' or rec.get('status') != 'received':
            raise ValueError('incomplete or unsafe pinned record')
        raw = (root / resp_name).read_bytes()
        if _sha(raw) != rec.get('sha256'):
            raise ValueError('pinned response digest mismatch')
        request = json.loads((root / req_name).read_bytes()); response = json.loads(raw)
        if request.get('id') != index or response.get('id') != index or request.get('method') != rec.get('method') or 'error' in response or 'result' not in response:
            raise ValueError('invalid pinned request/response')
        responses.append((request, response['result']))
    if responses[0][0]['method'] != 'eth_chainId' or int(responses[0][1], 16) != chain:
        raise ValueError('RPC chain mismatch')
    tag = hex(block['number'])
    for idx in (1, len(responses)-1):
        req, header = responses[idx]
        if req.get('method') != 'eth_getBlockByNumber' or req.get('params') != [tag, False] or int(header['number'], 16) != block['number'] or header['hash'].lower() != block['hash'].lower():
            raise ValueError('pinned header mismatch')
    for idx, op in enumerate(plan['operations'], 2):
        request = responses[idx][0]
        if (request.get('method'), request.get('params')) != (op['method'], op['params']):
            raise ValueError('pinned operation mismatch')
    runtime = _code(responses[2][1]); slot = responses[3][1]
    if not re.fullmatch(r'0x[0-9a-fA-F]{64}', str(slot)) or int(slot[2:26], 16):
        raise ValueError('invalid implementation slot value')
    implementation = '0x' + slot[-40:].lower() if int(slot[2:], 16) else None
    out = {'chain_id': chain, 'address': address, 'block': block, 'runtime_hex': runtime,
           'proxy': {'implementation_address': implementation, 'evidence_url': None},
           'capture_records': [{'path': r['response_path'], 'sha256': r['sha256']} for r in records]}
    if len(responses) == 6:
        req, impl_code = responses[4]
        if not implementation or req.get('method') != 'eth_getCode' or req.get('params') != [implementation, tag]:
            raise ValueError('implementation code does not match pinned slot')
        out['proxy']['implementation_capture'] = {'chain_id': chain, 'address': implementation,
                                                  'block': block, 'runtime_hex': _code(impl_code)}
    return out


def source_from_sourcify(candidate: dict, raw: bytes, expected_sha256: str, source_url: str) -> dict:
    """Translate an already-captured Sourcify v2 response; do not fetch or trust silently."""
    url = urlsplit(source_url)
    expected_path = f"/server/v2/contract/{candidate['chain_id']}/{candidate['address']}".lower()
    if (_sha(raw) != expected_sha256 or url.scheme != 'https' or url.netloc != 'sourcify.dev'
            or url.path.lower() != expected_path or url.fragment):
        raise ValueError('source capture hash or origin mismatch')
    doc = json.loads(raw)
    if str(doc.get('address', '')).lower() != candidate['address'].lower() or str(doc.get('chainId')) != str(candidate['chain_id']):
        raise ValueError('source chain/address mismatch')
    files = doc.get('sources')
    if not isinstance(files, dict):
        raise ValueError('Sourcify sources missing')
    contents = {path: item.get('content') for path, item in files.items() if isinstance(item, dict) and isinstance(item.get('content'), str)}
    if not contents:
        raise ValueError('Sourcify returned no source contents')
    return {'address': candidate['address'].lower(), 'source_url': source_url, 'provider_sha256': expected_sha256,
            'provider_runtime_match': doc.get('runtimeMatch'),
            'provider_onchain_runtime_hex': doc['runtimeBytecode']['onchainBytecode'],
            'compiled_runtime_hex': doc['runtimeBytecode']['recompiledBytecode'], 'files': contents}


def analyze(candidate: dict, capture: dict) -> dict:
    """Analyze bounded caller-supplied pinned RPC and source records, with no network.

    capture: chain_id, address, block {number, hash}, runtime_hex, optional source
    {address, compiled_runtime_hex, files, source_url}, proxy {implementation_address,
    evidence_url, implementation_capture}. Compiled runtime/source pairing is a caller
    provenance assertion; byte equality alone does not reproduce the compilation.
    """
    chain, address = candidate.get('chain_id'), candidate.get('address', '')
    if isinstance(chain, bool) or not isinstance(chain, int) or chain <= 0 or not _ADDRESS.fullmatch(address):
        raise ValueError('positive chain id and EVM token address required')
    if capture.get('chain_id') != chain or str(capture.get('address', '')).lower() != address.lower():
        raise ValueError('captured chain/address mismatch')
    block = capture.get('block', {})
    if not isinstance(block.get('number'), int) or block['number'] < 0 or not re.fullmatch(r'0x[0-9a-fA-F]{64}', str(block.get('hash', ''))):
        raise ValueError('pinned block number and hash required')
    runtime = _code(capture.get('runtime_hex', ''))
    if runtime == '0x':
        raise ValueError('no deployed contract runtime at captured block')
    result: dict[str, Any] = {'profile': 'scooby.contract-analysis/1',
        'candidate_id': f'{chain}:{address.lower()}', 'block': block,
        'status': 'partial', 'runtime_sha256': _sha(bytes.fromhex(runtime[2:])),
        'source_match': 'unavailable', 'findings': [], 'mechanism_hypotheses': [], 'unknowns': [], 'counterevidence': [],
        'proxy': {'status': 'unknown', 'implementation_address': None},
        'live_verdict': 'not_determined',
        'limitations': ['Input captures and compiler provenance require independent verification.',
                        'Lexical evidence can miss inherited, assembly, dynamically dispatched or obfuscated code.',
                        'Function and control matches are potential mechanisms, not proof of reachability, authority, state, or a blocked sell.',
                        'Source and bytecode equality does not establish that the supplied compiler output was built from the supplied source.']}
    if 'capture_records' in capture:
        result['rpc_evidence'] = capture['capture_records']
    source = capture.get('source')
    if source:
        if str(source.get('address', '')).lower() != address.lower():
            raise ValueError('source address mismatch')
        compiled = _code(source.get('compiled_runtime_hex', ''))
        result['source_match'] = 'runtime_bytes_equal_build_provenance_unverified' if runtime == compiled else 'runtime_mismatch'
        result['source_url'] = source.get('source_url')
        if source.get('provider_onchain_runtime_hex'):
            result['provider_verification'] = {'reported_runtime_match': source.get('provider_runtime_match'),
                'provider_onchain_equals_captured_runtime': _code(source['provider_onchain_runtime_hex']) == runtime,
                'provider_response_sha256': source.get('provider_sha256'),
                'interpretation': 'Provider assertion; any bytecode transformations and build must be independently reviewed.'}
        files = source.get('files', {})
        if not isinstance(files, dict) or len(files) > 100 or sum(len(x) for x in files.values() if isinstance(x, str)) > 2_000_000:
            raise ValueError('invalid or overlarge source bundle')
        if not files or any(not isinstance(k, str) or not isinstance(v, str) for k, v in files.items()):
            raise ValueError('source files must be a nonempty mapping of strings')
        funcs = []
        for path, text in sorted(files.items()):
            for name, start, end, masked in _functions(text):
                funcs.append({'name': name, 'path': path, 'text': text, 'start': start, 'end': end, 'masked': masked})
        transfer_names = {f['name'] for f in funcs if _TRANSFER.fullmatch(f['name'])}
        # Report direct transfer functions and one level of visible internal calls separately.
        transfer_calls = {m.group(1) for f in funcs if f['name'] in transfer_names for m in _CALL.finditer(f['masked'])}
        for f in funcs:
            scope = 'transfer_entry_or_hook' if f['name'] in transfer_names else ('called_by_transfer_name_match' if f['name'] in transfer_calls else 'other_function')
            for category, regex in _CATEGORIES.items():
                distinct = set()
                for match in regex.finditer(f['masked']):
                    token = match.group().lower()
                    if token in distinct:
                        continue
                    distinct.add(token)
                    if len(distinct) > 8:
                        break
                    absolute = f['start'] + match.start()
                    line = f['text'].count('\n', 0, absolute) + 1
                    code_line = f['text'].splitlines()[line - 1].strip()[:240]
                    result['findings'].append({'category': category, 'function': f['name'], 'scope': scope,
                        'path': f['path'], 'line': line, 'source_sha256': _sha(f['text'].encode('utf-8')),
                        'matched_token': match.group(), 'code_excerpt': code_line,
                        'evidence_interpretation': 'lexical indicator; requires manual semantic and runtime review'})
            if (scope != 'other_function' and re.search(r'\b(?:call|staticcall|delegatecall)\s*\(', f['masked'], re.I)
                    and re.search(r'\b(?:revert|require|assert)\s*\(', f['masked'], re.I)):
                linked = [x for x in result['findings'] if x['path'] == f['path'] and x['function'] == f['name']
                          and x['category'] in ('external_transfer_dependency', 'transfer_sell_restrictions')]
                result['mechanism_hypotheses'].append({
                    'kind': 'possible_external_transfer_gate', 'function': f['name'], 'scope': scope,
                    'rationale': 'A transfer-related function contains external-call and revert/require indicators; review whether a failed call can block transfer.',
                    'evidence_locations': [{'path': x['path'], 'line': x['line'], 'source_sha256': x['source_sha256']} for x in linked],
                    'status': 'requires_semantic_and_runtime_review'})
        if not transfer_names:
            result['unknowns'].append('No transfer entry or hook identified; inherited or external code may be missing.')
        if result['source_match'] == 'runtime_mismatch':
            result['unknowns'].append('Recompiled and captured bytecodes differ; review provider transformations and provenance before attributing source findings to deployed runtime.')
        if not result['findings']:
            result['counterevidence'].append('No configured control indicators found in supplied function bodies; this is not evidence of their absence.')
    else:
        result['unknowns'].append('No source and compiler runtime supplied; source controls cannot be reviewed.')
    proxy = capture.get('proxy')
    if proxy is None:
        result['unknowns'].append('Proxy and implementation resolution not supplied; proxy status is unknown.')
    else:
        implementation = proxy.get('implementation_address')
        if implementation is None:
            result['proxy'] = {'status': 'no_implementation_observed_in_supplied_slot', 'implementation_address': None,
                               'evidence_url': proxy.get('evidence_url')}
            result['unknowns'].append('A null inspected slot does not rule out a beacon, clone, diamond, or other proxy.')
        elif not _ADDRESS.fullmatch(str(implementation)):
            raise ValueError('invalid proxy implementation address')
        else:
            result['proxy'] = {'status': 'implementation_address_supplied', 'implementation_address': implementation.lower(),
                               'evidence_url': proxy.get('evidence_url')}
            impl = proxy.get('implementation_capture')
            if impl:
                # Nested implementation data is analyzed as its own deployment, not blindly inherited.
                if impl.get('block') != block:
                    raise ValueError('implementation block differs from proxy block')
                nested = dict(impl); nested.pop('proxy', None)
                result['proxy']['implementation_analysis'] = analyze({'chain_id': chain, 'address': implementation}, nested)
            else:
                result['unknowns'].append('Implementation source and runtime were not supplied; proxy controls are incomplete.')
    result['unknowns'].extend(['Admin, implementation, blacklist and tax state are not established by source text alone.',
                              'Current executable buy/sell behavior and ordinary-seller counterexamples were not tested.'])
    return result
