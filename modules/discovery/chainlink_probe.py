"""Resolve Chainlink ETH/USD through its documented ENS resolver and read at a finalized Ethereum block."""
import argparse,datetime as dt,json
from pathlib import Path
from Crypto.Hash import keccak
import rpc_snapshot
RESOLVER='0x122eb74f9d0F1a5ed587F43D120C1c2BbDb9360B'
URL=rpc_snapshot.RPC[1]
def kh(data): return keccak.new(digest_bits=256,data=data).digest()
def namehash(name):
 node=bytes(32)
 for label in reversed(name.split('.')):node=kh(node+kh(label.encode('ascii')))
 return node.hex()
def require(result):
 if result.get('status')!='ok':raise ValueError('RPC call failed: '+str(result.get('error')))
 return result['result']
def ethcall(address,data,block):return require(rpc_snapshot.call(URL,'eth_call',[{'to':address,'data':data},block]))
def words(encoded):
 h=encoded[2:] if encoded.startswith('0x') else encoded
 if len(h)%64:raise ValueError('invalid ABI words')
 return [int(h[i:i+64],16) for i in range(0,len(h),64)]
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if require(rpc_snapshot.call(URL,'eth_chainId',[]))!='0x1':raise ValueError('wrong chain')
 block=require(rpc_snapshot.call(URL,'eth_getBlockByNumber',['finalized',False]));tag=block['number'];node=namehash('eth-usd.data.eth')
 address_word=words(ethcall(RESOLVER,'0x3b3b57de'+node,tag))
 if len(address_word)!=1 or address_word[0]==0 or address_word[0]>=2**160:raise ValueError('invalid ENS feed address')
 feed='0x'+format(address_word[0],'040x')
 raw_desc=ethcall(feed,'0x7284e416',tag);hex_desc=bytes.fromhex(raw_desc[2:]);offset=int.from_bytes(hex_desc[:32],'big');n=int.from_bytes(hex_desc[offset:offset+32],'big');description=hex_desc[offset+32:offset+32+n].decode('utf-8')
 if description.strip().upper()!='ETH / USD':raise ValueError('resolved feed description did not match ETH / USD: '+description)
 decimals=words(ethcall(feed,'0x313ce567',tag));round_data=words(ethcall(feed,'0xfeaf968c',tag))
 if len(decimals)!=1 or decimals[0]>36 or len(round_data)!=5:raise ValueError('malformed feed response')
 round_id,answer,started,updated,answered=round_data
 if answer>=2**255:answer-=2**256
 block_time=int(block['timestamp'],16); fetched_time=dt.datetime.now(dt.timezone.utc)
 if answer<=0 or updated<=0 or updated>block_time:raise ValueError('invalid feed answer or timestamp')
 result={'network':'ethereum','chain_id':1,'ens':'eth-usd.data.eth','ens_resolver':RESOLVER,'feed_proxy':feed,'description':description,'block_number':int(tag,16),'block_hash':block.get('hash'),'block_time':dt.datetime.fromtimestamp(block_time,dt.timezone.utc).isoformat(),'fetched_at':fetched_time.isoformat(),'round_id':str(round_id),'answer_integer':str(answer),'decimals':decimals[0],'updated_at':dt.datetime.fromtimestamp(updated,dt.timezone.utc).isoformat(),'age_seconds_at_block':block_time-updated,'age_seconds_at_fetch':round(fetched_time.timestamp()-updated),'provider_url':URL,'method':'on-chain finalized-block eth_call; feed resolved using Chainlink documented ENS resolver','limits':['Feed answers are reference prices and may be stale; feed heartbeat/deviation and current implementation must be checked against use requirements.','No pool or token screening gate is evaluated.']}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2),encoding='utf-8'); print(json.dumps(result,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
