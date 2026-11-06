# Source checks — 6 November 2026

These checks support engineering choices, not token verdicts. User-provided case anecdotes are inputs to the separate historical reference catalog; exact contract/event/mechanism claims require their own evidence ledger.

| Claim | Primary source | Implication / limit |
|---|---|---|
| Eligible approved free Reddit Data API clients have a 100-QPM OAuth quota; OAuth and descriptive client identity are required | [Data API Wiki](https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki) | Quota is not permission for a new app; implement limits and unavailable states |
| New public API access requests stopped 31 October 2026; remaining public access is scheduled to end March 2027 | [Reddit migration announcement](https://www.reddit.com/r/redditdev/comments/1wubcvf/moving_data_api_apps_to_the_developer_platform/), [developer app registration](https://developers.reddit.com/app-registration) | Do not promise a newly issued free key or build an irreplaceable legacy provider |
| Access requires approval; the current policy covers apps and agents | [Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy) | No approval assumptions, unapproved scraping fallback or automatic account request |
| Commercial use is permission/contract dependent | [Developer access FAQ](https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data) | No spending or universal free-price claim |
| Reddit source retention must account for deleted content and user information | [Data API Wiki](https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki) | Keep minimum data, deletion/retraction handling and source-availability semantics; do not permanently embed raw social content in immutable public reports by default |
| AgentKit distinguishes agents backed by verified humans; the current guide resolves AgentBook on World Chain and illustrates x402 payment flows | [World integration guide](https://docs.world.org/agents/agent-kit/integrate) | This is identity/backing infrastructure, not Scooby risk qualification or consent. No automatic payment side effects |
| AgentKit's repository describes agent registration, signed challenge verification and access policy, with a different relay-network default in its README | [Official AgentKit README](https://github.com/worldcoin/agentkit/blob/main/README.md), [SDK integration notes](https://github.com/worldcoin/agentkit/blob/main/x402/DOCS.md) | Pin SDK/version/deployment and resolve documentation drift; do not mix network defaults |

No SDK installation, AgentBook registration, API-account request, private communication, paid request, live proof or transaction was performed for these checks.
