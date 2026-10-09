# jev-mcp

[English](README.md) | 简体中文

用TypeSafe Jev执行窄范围语义判断：依据证据判断是/否、从有限候选中选择、相关性评分。同一state下的独立问题可合并提交。

## 工具

| 工具 | 参数 | 行为 |
|---|---|---|
| `jev_evaluate` | `state, questions` | 批量执行Noul、Choice、Score语义判断；消耗TypeSafe额度 |
| `get_mcp_status` | `—` | 读取本地状态与用量快照 |

## 安装与配置

需要Python 3.12–3.14，推荐Linux。

```sh
git clone https://github.com/ZephyrAki/jev-mcp.git
cd jev-mcp
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
cp .env.example .env
chmod 600 .env
```

填写`.env`后再启动；示例值不可直接使用。`ZEPHYR_DATA_DIR`是可写的私密目录，不同服务使用不同目录。所有工具都经过GitHub OAuth与数字用户ID白名单校验。创建GitHub OAuth App，将回调URL设为`https://你的域名/auth/callback`，`MCP_PUBLIC_BASE_URL`填写同一个域名根地址，不附加`/mcp`。

本地生成三个独立密钥（Jev只需要前两个），将输出分别保存到环境文件，不要上传GitHub：

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

进程默认只监听`127.0.0.1:8765`。用HTTPS反向代理转发整个应用，包含OAuth路由；客户端添加`https://你的域名/mcp`。服务使用HTTP MCP传输，不提供stdio启动模式。代理转发头和公开URL必须一致。

## 使用与边界

示例调用（JSON）：

```json
{"state":"用户明确要求修复当前登录问题", "questions":{"needs_action":{"type":"noul","instructions":"用户是否要求执行操作？"}}}
```

支持的question结构请以`tests/test_typesafe.py`的Noul、Choice、Score示例为准。相同state的独立问题尽量合并；需要新的证据才能判断的问题再另行提交。服务只保存用量元数据，不在SQLite保存state、问题或答案。默认最大请求1MiB、并发4、超时30秒；月输入token告警阈值只用于提醒，不是免费额度硬性停止保护。state和问题会发送到TypeSafe API。

## 开发验证

```sh
PYTHONPATH=src .venv/bin/pytest -q
.venv/bin/python -m pip check
```

测试使用替身与合成数据，不访问你的真实账号或消费云额度。部署后的TypeSafe请求仍需在实际环境验收。仓库包含所需共用工具副本，不依赖另外两个功能仓库。

## 许可

原创代码采用[MIT](LICENSE)。第三方原许可与出处见[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
