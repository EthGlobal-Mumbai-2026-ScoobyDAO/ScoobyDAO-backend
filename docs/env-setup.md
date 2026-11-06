# Local environment and credential setup

The current [.env.example](../.env.example) lists supported runtime variables without real credentials. The application reads process environment variables; copying that example to `.env` alone does not load them. Configure the API and worker shells, plus the frontend shell before its dev server/build. Match one web origin exactly.

## Provider credential audit

| Variable | Purpose and observed use |
|---|---|
| `SEARCHAPI_API_KEY` | Selected Reddit search provider. Used for the successful live smoke and bounded context searches. Backend only; sent as Bearer authorization. |
| `PUBLICNODE_TOKEN` | Optional authenticated Ethereum PublicNode historical RPC collector. Public/read-only sources elsewhere need no key; this is not a general token research verdict. |
| `OPENAI_API_KEY` | GPT-6.1 Terra Chat Completions transport. Configured locally, but no live model completion was made in this checkpoint; call budget defaults to zero. |
| `WORLD_CLIENT_ID`, `WORLD_CLIENT_KEY_PATH`, `WORLD_CLIENT_KEY_ID`, `WORLD_ISSUER` | World device-grant client configuration, including a signing-key file. This is not one generic World API key. Actual app registration/key provisioning and reviewer/delegation setup are separate. |
| `SCOOBY_OPERATOR_TOKEN` | Private operator bearer token, generated locally by the setup helper if absent. Not a third-party API key and never frontend config. |
| `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID` | Optional public frontend WalletConnect project identifier. Not a backend secret. |

The current DEX Screener, GeckoTerminal, GoPlus and Sourcify adapters use public endpoints without an API key in this implementation. The old direct-Reddit OAuth variables are optional legacy configuration and are not required for SearchApi. Do not copy old ASI configuration. There is no supported `OPENAI_MODEL` or global social-budget env toggle; the current model is selected in code and social lookback/request bounds are producer arguments.

Publication wallet keys (`SCOOBY_PUBLISHER_KEY`, `SCOOBY_ATTESTOR_KEY`) are separate optional transaction secrets, not required for the ordinary scout/research setup. This helper does not request them or enable publication. World configuration alone does not prove the complete candidate-authorization workflow is operational.

## PowerShell setup

From the backend repository root, use masked prompts for provider secrets and persist to the current Windows user's environment:

```powershell
. .\scripts\setup-local-env.ps1 -PersistUser
```

Enter each person's own SearchApi/PublicNode/OpenAI credential. Blank input keeps an existing configured value or skips an absent optional credential. Values are not printed, written to `.env`, committed or sent to a provider. User-level environment variables remain local to that Windows account.

For World client setup as well, with an already registered app and private signing-key file:

```powershell
. .\scripts\setup-local-env.ps1 -PersistUser -IncludeWorld
```

In each additional API/worker/frontend shell, reload the values without prompts:

```powershell
. .\scripts\setup-local-env.ps1 -LoadOnly -IncludeWorld
```

Dot-sourcing keeps settings in the current shell. Existing running services must be restarted; a user-level change cannot retroactively modify their environment. The helper explicitly sets local API bases to `http://127.0.0.1:8000` and web origin to `http://127.0.0.1:3000`, leaves fixtures off, and keeps model calls, discovery auto-sync and publication off. Configure actual existing discovery DB/evidence paths and authorized source/model budgets separately. Frontend public settings are URLs/feature flags only; no provider key goes in `NEXT_PUBLIC_*`.

Run the web at `http://127.0.0.1:3000` to match CORS, or deliberately update both sides to the chosen exact origin. All authored reports and runtime data still require the separate [asset transfer](report-assets.md) procedure on a fresh machine. Configuration is not a data migration or proof that every producer/verifier is integrated.

Case investigation model policy is `SCOOBY_CASE_MODEL_MAX_CALLS=0` by default. A server operator may explicitly set it to `1` for new decisions after budget authorization; it is bound into the decision policy and does not widen existing decisions. The API and worker must use the same value. The separate `SCOOBY_MODEL_CALL_BUDGET` controls a legacy reasoning route and does not enable case research.
