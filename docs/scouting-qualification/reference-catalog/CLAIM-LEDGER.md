# Claim ledger

Confidence is claim-specific and measures support in this bounded source review, not a finding of guilt or a current risk assessment.

### C01 — squid-bsc-2021

**Claim:** SQUID proxy and sell restrictions  
**Type:** source_attributed_historical_claim; **confidence:** moderate  
**Sources:** [S1](https://sharkteam.org/report/analysis/20211112001A_en.pdf), [S2](https://medium.com/@BeeNBee/how-squid-tokens-rug-pull-worked-4d547aa12229)  
**Limit:** Security investigator + independent analyst; exact contract implementation and sell rules not replayed.

### C02 — anubis-ethereum-2021

**Claim:** Bootstrap pool creator held and redeemed LP position  
**Type:** source_attributed_historical_claim; **confidence:** moderate  
**Sources:** [S3](https://www.lawsociety.org.sg/wp-content/uploads/2022/10/Crypto-Crime-Report-2022.pdf), [S4](https://smartcontractshacking.com/hacks/anubisdao-hack-2021)  
**Limit:** Chainalysis interpretation; independent explorer decoding blocked; intent disputed.

### C03 — lunayield-solana-2021

**Claim:** Solana project and apparent exit  
**Type:** source_attributed_historical_claim; **confidence:** moderate  
**Sources:** [S5](https://www.investing.com/analysis/luna-yield-executes-first-major-rug-pull-on-solana-200599584), [S6](https://smartcontractshacking.com/hacks/luna-yield-hack-2021), [S17](https://zhiqlin.github.io/file/RAID24.pdf)  
**Limit:** Original investigators cited; scope of recoveries not resolved.

### C04 — meerkat-bsc-2021

**Claim:** Proxy upgrades and subsequent vault withdrawal  
**Type:** source_attributed_historical_claim; **confidence:** moderate  
**Sources:** [S7](https://onchainattack.org/document/examples/2021-03-meerkat-finance/), [S8](https://smartcontractshacking.com/hacks/meerkat-finance-hack-2021), [S9](https://www.theblock.co/news/defi/2021-03-04-rug-pull-defi-meerkat-31-million-97082)  
**Limit:** Downstream case studies rely in part on common incident analysis; key compromise remains possible.

### C05 — bald-base-2023

**Claim:** Base BALD identity and liquidity removal  
**Type:** source_attributed_historical_claim; **confidence:** moderate  
**Sources:** [S10](https://cointelegraph.com/news/bald-token-developer-denies-rug-pull-price-falls-post-launch), [S11](https://www.theblock.co/news/ecosystems/2023-07-31-bald-memecoin-developer-liquidity-pull-242225), [S12](https://www.sharkteam.org/report/analysis/20231020001A_en.pdf)  
**Limit:** Linked chain transaction unavailable to reader; amounts represent different possible windows.

### C06 — bald-base-2023

**Claim:** Developer denied market sales and acknowledged two-sided liquidity activity  
**Type:** source_attributed_historical_claim; **confidence:** moderate  
**Sources:** [S10](https://cointelegraph.com/news/bald-token-developer-denies-rug-pull-price-falls-post-launch)  
**Limit:** Reported contemporaneous statement; source link to original social post not separately reviewed.

### C07 — magnate-base-2023

**Claim:** Base oracle change and lending-asset withdrawal  
**Type:** source_attributed_historical_claim; **confidence:** moderate  
**Sources:** [S12](https://www.sharkteam.org/report/analysis/20231020001A_en.pdf), [S13](https://www.quillaudits.com/blog/hack-analysis/magnate-finance-rug-pull)  
**Limit:** Quill attributes oracle mechanism; separate report describes drain; no RPC replay.

### C08 — bald-base-2023

**Claim:** Best token-oriented Base replay candidate for this bounded comparison  
**Type:** selection_inference; **confidence:** moderate  
**Sources:** [S10](https://cointelegraph.com/news/bald-token-developer-denies-rug-pull-price-falls-post-launch), [S11](https://www.theblock.co/news/ecosystems/2023-07-31-bald-memecoin-developer-liquidity-pull-242225), [S12](https://www.sharkteam.org/report/analysis/20231020001A_en.pdf)  
**Limit:** Selection inference, not admission to discovery or proof of a sell trap.

## Source quality and unresolved conflicts

- Some Meerkat sources repeat the same Rekt investigation; repetition does not establish independent corroboration. The project reported a hack and the reviewed case studies do not conclusively rule out key compromise.
- BALD withdrawal figures vary in scope and timing. The July De.Fi summary includes Ethereum explorer links under its BALD section that also appear under an unrelated incident, so those links are not used as proof of Base-chain transactions. The directly linked Base transaction in S10 was blocked when opened.
- Luna Yield loss and recovery figures vary, and compensation to IDO buyers cannot be equated to total losses recovered. No loss or recovery total is asserted in the catalog.
- Chainalysis and the Anubis incident index support a pool drain; the actor identity, intent and exact historical token/pool relationship remain unresolved.
- All present-day statuses remain unknown. The source-reported 2026 SQUID proxy state is dated, is not an independent read, and is not substituted for historical state.
