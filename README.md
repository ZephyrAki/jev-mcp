# jev-mcp

English | [简体中文](README.zh-CN.md)

Use TypeSafe Jev for focused semantic judgments: evidence-based yes/no, finite-choice selection and relevance scoring. Batch independent questions sharing the same state.

## Tools

| Tool | Arguments | Behavior |
|---|---|---|
| `jev_evaluate` | `state, questions` | Batch Noul, Choice and Score judgments; consumes TypeSafe quota |
| `get_mcp_status` | `—` | Read local status and usage snapshots |

## Install and configure

Requires Python 3.12–3.14; Linux is recommended.

```sh
git clone https://github.com/ZephyrAki/jev-mcp.git
cd jev-mcp
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
cp .env.example .env
chmod 600 .env
```

Fill in `.env` before starting; placeholders are not usable credentials. `ZEPHYR_DATA_DIR` must be a writable private directory, separate for each service. All tools enforce GitHub OAuth and a numeric user-ID allowlist. Create a GitHub OAuth App with callback `https://your-domain/auth/callback`; set `MCP_PUBLIC_BASE_URL` to the same root URL without `/mcp`.

Generate independent keys locally (Jev needs only the first two) and save the outputs in your private environment file, never on GitHub:

```sh
.venv/bin/python -c "import secrets; print(secrets.token_hex(32))" # FASTMCP_JWT_SIGNING_KEY
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" # OAUTH_STORAGE_FERNET_KEY
```

```sh
set -a
. ./.env
set +a
.venv/bin/jev-mcp
```

The process binds to `127.0.0.1:8765`. Put the entire application behind an HTTPS reverse proxy, including OAuth routes. Connect your MCP client to `https://your-domain/mcp`. This server uses HTTP MCP transport, not stdio. Forwarded proxy headers must agree with the public URL.

## Workflow and limits

Example tool arguments (JSON):

```json
{"state":"用户明确要求修复当前登录问题", "questions":{"needs_action":{"type":"noul","instructions":"用户是否要求执行操作？"}}}
```

See `tests/test_typesafe.py` for accepted Noul, Choice and Score shapes. Batch independent questions with the same state; submit again when new evidence is needed. SQLite stores usage metadata, not states, questions or answers. Defaults: 1 MiB request size, four concurrent requests and 30-second timeout. The monthly input-token warning is informational, not a hard free-quota stop. States and questions are sent to TypeSafe API.

## Development checks

```sh
PYTHONPATH=src .venv/bin/pytest -q
.venv/bin/python -m pip check
```

Tests use mocks and synthetic data, without accessing real accounts or consuming cloud quota. Real platform access and TypeSafe requests still require validation in your deployment. Required common code is included locally; neither sibling repository is required.

## License

Original code is [MIT](LICENSE). Upstream licenses and attribution are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
