import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from modules.investigation import contract_analysis as contract
from modules.investigation import pinned_rpc_capture
from modules.investigation import reddit_search as reddit

ADDR = '0x' + '12' * 20
IMPL = '0x' + '34' * 20
CANDIDATE = {'chain_id': 1, 'address': ADDR}
BLOCK = {'number': 100, 'hash': '0x' + 'aa' * 32}
WINDOW = {'start': '2020-01-01T00:00:00Z', 'end': '2020-02-01T00:00:00Z'}
STAMP = int(datetime(2020, 1, 5, tzinfo=timezone.utc).timestamp())


def test_no_approved_reddit_app_is_unavailable_and_makes_no_request():
    def never(_request):
        raise AssertionError('network must not be used')
    result = reddit.collect_reddit_oauth(CANDIDATE, WINDOW, reddit.RedditCredentials('id', 'secret', 'agent', False),
                            transport=httpx.MockTransport(never))
    assert result['status'] == 'unavailable' and result['coverage']['requests'] == 0
    assert result['observations'] == [] and result['interpretation'] is None
    assert reddit.summarize([])['counts'] is None


def test_bounded_reddit_search_paginates_attributes_redacts_and_counts():
    requests = []
    def send(request):
        requests.append(request)
        if request.url.host == 'www.reddit.com':
            assert request.method == 'POST'
            return httpx.Response(200, json={'access_token': 'secret-token'})
        assert request.headers['Authorization'] == 'Bearer secret-token'
        if request.url.path == '/search':
            if request.url.params.get('after'):
                return httpx.Response(200, json={'data': {'after': None, 'children': []}})
            post = {'name': 't3_abc', 'title': f'Warning for {ADDR}',
                    'selftext': 'email a@example.com and visit https://bad.invalid',
                    'created_utc': STAMP, 'permalink': '/r/example/comments/abc/title/'}
            unrelated = {'name': 't3_xyz', 'title': 'only ticker RAY', 'created_utc': STAMP,
                         'permalink': '/r/example/comments/xyz/title/'}
            return httpx.Response(200, json={'data': {'after': 't3_abc', 'children': [{'data': post}, {'data': unrelated}]}})
        assert request.url.path == '/comments/abc'
        comment = {'name': 't1_def', 'body': 'not a scam, actually promising', 'created_utc': STAMP,
                   'permalink': '/r/example/comments/abc/title/def/'}
        return httpx.Response(200, json=[{}, {'data': {'children': [{'kind': 't1', 'data': comment}]}}])
    result = reddit.collect_reddit_oauth(CANDIDATE, WINDOW, reddit.RedditCredentials('id', 'secret', 'test-agent', True),
                            max_requests=5, max_posts=10, max_comments=2, transport=httpx.MockTransport(send))
    assert result['status'] == 'partial' and len(requests) == 4
    assert [x['attribution'] for x in result['observations']] == ['address_mentioned', 'comment_on_attributed_post']
    assert 'a@example.com' not in str(result) and 'secret-token' not in str(result)
    assert result['interpretation']['counts']['concern'] == 1
    assert result['interpretation']['counts']['both'] == 1  # literal terms, not a stance classifier
    assert result['interpretation']['daily'][0]['date'] == '2020-01-05'
    assert result['coverage']['posts_examined'] == 2 and result['coverage']['comments_examined'] == 1


def test_reddit_failure_and_alias_rules_are_explicit():
    creds = reddit.RedditCredentials('id', 'secret', 'test-agent', True)
    def rate_limited(request):
        return httpx.Response(429)
    result = reddit.collect_reddit_oauth(CANDIDATE, WINDOW, creds, transport=httpx.MockTransport(rate_limited))
    assert result['status'] == 'unavailable' and result['coverage']['requests'] == 1
    with pytest.raises(ValueError):
        reddit.collect_reddit_oauth({**CANDIDATE, 'project_alias': 'RAY', 'alias_evidence_url': 'https://example.org'}, WINDOW, creds)
    with pytest.raises(ValueError):
        reddit.collect_reddit_oauth({**CANDIDATE, 'project_alias': 'Project Ray'}, WINDOW, creds)


def test_reddit_lead_search_keeps_unresolved_identifiers_and_zero_votes():
    requests = []
    def send(request):
        requests.append(request)
        if request.url.host == 'www.reddit.com':
            return httpx.Response(200, json={'access_token': 'private-token'})
        assert request.url.path == '/r/CryptoCurrency/search'
        assert request.url.params['restrict_sr'] == 'true'
        post = {'name': 't3_abc', 'title': f'Possible rug in {ADDR}', 'selftext': 'Do your own research',
                'created_utc': STAMP, 'permalink': '/r/CryptoCurrency/comments/abc/title/'}
        return httpx.Response(200, json={'data': {'after': None, 'children': [{'data': post}]}})
    result = reddit.search_leads_reddit_oauth('rugpull', ['CryptoCurrency'], WINDOW,
                                 reddit.RedditCredentials('id', 'secret', 'agent', True),
                                 transport=httpx.MockTransport(send))
    lead = result['observations'][0]
    assert result['status'] == 'partial' and len(requests) == 2
    assert lead['id'] == 't3_abc' and lead['subreddit'] == 'CryptoCurrency'
    assert lead['extracted_identifiers'] == [{'kind': 'evm_address', 'value': ADDR, 'chain_id': None}]
    assert lead['attribution'] == 'unresolved' and lead['verified_concern_votes'] == 0
    assert 'private-token' not in str(result) and lead['fetched_at'] and lead['content_sha256']
    missing = reddit.search_leads_reddit_oauth('honeypot', ['CryptoCurrency'], WINDOW, None, transport=httpx.MockTransport(send))
    assert missing['status'] == 'unavailable' and missing['coverage']['requests'] == 0


def test_reddit_rate_limit_stops_without_retries():
    calls = []
    def send(request):
        calls.append(request)
        return httpx.Response(200, json={'access_token': 'test'}, headers={'x-ratelimit-remaining': '0.0', 'x-ratelimit-reset': '45'})
    result = reddit.search_leads_reddit_oauth('honeypot', ['CryptoCurrency'], WINDOW,
                                 reddit.RedditCredentials('id', 'secret', 'agent', True),
                                 transport=httpx.MockTransport(send))
    assert result['status'] == 'unavailable' and len(calls) == 1
    assert result['coverage']['rate_limit_reset_seconds'] == 45


def test_shared_lead_example_is_explicitly_synthetic_and_unresolved():
    path = Path(__file__).parent / 'fixtures' / 'social-contract' / 'reddit-leads.example.json'
    example = json.loads(path.read_text(encoding='utf-8'))
    assert example['profile'] == 'scooby.reddit-leads/1'
    assert 'Synthetic fixture only' in example['limitations'][0]
    assert example['observations'][0]['extracted_identifiers'][0]['chain_id'] is None
    assert example['observations'][0]['verified_concern_votes'] == 0


@pytest.mark.parametrize('http_status', [401, 403, 429])
def test_reddit_authorization_failures_leave_scopes_unvisited(http_status):
    result = reddit.search_leads_reddit_oauth('honeypot', ['Example', 'ExampleTwo'], WINDOW,
        reddit.RedditCredentials('id', 'secret', 'agent', True),
        transport=httpx.MockTransport(lambda request: httpx.Response(http_status)))
    assert result['status'] == 'unavailable'
    assert [s['state'] for s in result['coverage']['scopes']] == ['not_started', 'not_started']
    assert result['observations'] == [] and result['coverage']['requests'] == 1


def test_reddit_cursor_loop_fails_closed_without_infinite_requests():
    calls = []
    def send(request):
        calls.append(request)
        if request.url.host == 'www.reddit.com':
            return httpx.Response(200, json={'access_token': 'test'})
        return httpx.Response(200, json={'data': {'after': 't3_same', 'children': []}})
    result = reddit.search_leads_reddit_oauth('honeypot', ['Example', 'ExampleTwo'], WINDOW,
        reddit.RedditCredentials('id', 'secret', 'agent', True), transport=httpx.MockTransport(send))
    assert result['status'] == 'unavailable' and len(calls) == 3
    assert [s['state'] for s in result['coverage']['scopes']] == ['failed', 'not_started']
    assert result['coverage']['scopes'][0]['next_cursor'] == 't3_same'


def source_capture(code):
    return {'chain_id': 1, 'address': ADDR, 'block': BLOCK, 'runtime_hex': '0x6001',
            'source': {'address': ADDR, 'compiled_runtime_hex': '0x6001',
                       'source_url': 'https://example.org/source', 'files': {'Token.sol': code}}}


def test_contract_finds_transfer_dependency_and_privileged_controls_without_comment_hits():
    code = '''contract Token {
       // function blacklist() external {} -- a comment is not executable
       function _update(address from, address to, uint value) internal { emitTransfer(from); }
       function emitTransfer(address from) internal { assembly { let x := xor(1, 2) let ok := call(gas(), x, 0, 0, 0, 0, 0) if iszero(ok) { revert(0, 0) } } }
       function setTaxFee(uint taxFee) external onlyOwner { fee = taxFee; }
       function mint(address a, uint n) external onlyOwner { _mint(a, n); }
    }'''
    result = contract.analyze(CANDIDATE, source_capture(code))
    assert result['source_match'] == 'runtime_bytes_equal_build_provenance_unverified'
    assert result['live_verdict'] == 'not_determined'
    found = result['findings']
    assert any(f['category'] == 'external_transfer_dependency' and f['function'] == 'emitTransfer' and f['scope'] == 'called_by_transfer_name_match' and f['matched_token'].startswith('call') for f in found)
    assert any(f['category'] == 'tax_fee_controls' and f['function'] == 'setTaxFee' for f in found)
    assert any(f['category'] == 'admin_authority' and f['function'] == 'mint' for f in found)
    assert result['mechanism_hypotheses'][0]['kind'] == 'possible_external_transfer_gate'
    assert result['mechanism_hypotheses'][0]['status'] == 'requires_semantic_and_runtime_review'
    assert not any(f['category'] == 'blacklist_controls' for f in found)
    assert all(len(f['source_sha256']) == 64 and f['line'] > 0 for f in found)


def test_contract_identity_mismatch_unverified_proxy_and_bytecode_mismatch():
    capture = source_capture('contract T { function transfer() public { require(true); } }')
    with pytest.raises(ValueError):
        contract.analyze({'chain_id': 8453, 'address': ADDR}, capture)
    capture['source']['compiled_runtime_hex'] = '0x6002'
    capture['proxy'] = {'implementation_address': IMPL}
    result = contract.analyze(CANDIDATE, capture)
    assert result['source_match'] == 'runtime_mismatch'
    assert result['proxy']['status'] == 'implementation_address_supplied'
    assert any('Implementation source' in x for x in result['unknowns'])


def test_pinned_rpc_capture_verifies_chain_block_slot_and_hash(tmp_path):
    plan = contract.rpc_plan(CANDIDATE, BLOCK, IMPL)
    selected = {'candidate_id': plan['candidate_id'], 'decision': 'selected', 'record_id': 'fixture'}
    def mock_rpc(req):
        method, params = req['method'], req['params']
        result = {'eth_chainId': '0x1', 'eth_getBlockByNumber': {'number': '0x64', 'hash': BLOCK['hash']},
                  'eth_getStorageAt': '0x' + '0' * 24 + IMPL[2:]}.get(method)
        if method == 'eth_getCode':
            result = '0x6001' if params[0] == ADDR else '0x6002'
        return json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'result': result}).encode()
    folder = tmp_path / 'capture'
    pinned_rpc_capture.capture(plan, selected, folder, mock_rpc, max_requests=6)
    output = contract.from_pinned_capture(folder)
    assert output['proxy']['implementation_address'] == IMPL
    assert output['proxy']['implementation_capture']['runtime_hex'] == '0x6002'
    assert len(output['capture_records']) == 6
    assert len(contract.analyze(CANDIDATE, output)['rpc_evidence']) == 6
    (folder / '003-response.json').write_text('{}')
    with pytest.raises(ValueError, match='digest'):
        contract.from_pinned_capture(folder)


def test_sourcify_identity_hash_and_provider_runtime_are_recorded():
    raw = json.dumps({'chainId': '1', 'address': ADDR, 'runtimeMatch': 'match',
                      'runtimeBytecode': {'onchainBytecode': '0x6001', 'recompiledBytecode': '0x6002'},
                      'sources': {'Token.sol': {'content': 'contract T {}'}}}).encode()
    source = contract.source_from_sourcify(CANDIDATE, raw, hashlib.sha256(raw).hexdigest(),
                                           f'https://sourcify.dev/server/v2/contract/1/{ADDR}?fields=all')
    result = contract.analyze(CANDIDATE, {**source_capture('contract T {}'), 'source': source})
    assert result['source_match'] == 'runtime_mismatch'
    assert result['provider_verification']['reported_runtime_match'] == 'match'
    assert result['provider_verification']['provider_onchain_equals_captured_runtime'] is True
    with pytest.raises(ValueError):
        contract.source_from_sourcify(CANDIDATE, raw, '0' * 64, 'https://sourcify.dev/test')
