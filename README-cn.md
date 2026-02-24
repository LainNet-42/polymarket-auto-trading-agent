# Polymarket Auto Trading Agent

<p align="center">
  <strong>基于 Claude Code 的全自动预测市场交易 Agent</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.11+-3776AB.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="https://docs.anthropic.com/en/docs/claude-code"><img src="https://img.shields.io/badge/Claude_Code-Anthropic-cc785c.svg?style=for-the-badge" alt="Claude Code"></a>
  <a href="https://polymarket.com"><img src="https://img.shields.io/badge/Polymarket-Polygon-7B3FE4.svg?style=for-the-badge" alt="Polymarket"></a>
</p>

[**English**](./README.md) | **中文简体**

[工作原理](#工作原理) | [快速开始](#快速开始) | [Dashboard](#dashboard可选) | [MCP 工具](#mcp-工具) | [策略](#默认策略) | [自定义](#自定义) | [架构](#架构) | [贡献](#贡献) | [FAQ](#常见问题)

---

## 架构

<p align="center">
  <img src="images/agent_arch.excalidraw.svg" alt="Architecture Diagram" width="800">
</p>

---

~~"耶稣基督会在 2027 年前回归吗？"~~ 这是 [Polymarket](https://polymarket.com) 上一个真实存在的市场。你可以买 YES 或 NO 的份额来押注现实世界的事件，押对了结算时每份 $1.00。这个市场有 [$3000 万的交易量](https://polymarket.com/event/will-jesus-christ-return-before-2027)。圣经没更新，梵蒂冈没发声明，耶稣也没来 -- 但 NO 仍然只卖 $0.96，不是 $1.00。白白四分钱摆在桌上没人捡。

这个 Agent 就是来捡这四分钱的。它专找那些结果已经板上钉钉的市场 -- 比赛打完了、选票点完了、神迹毫无悬念地没有发生 -- 然后用实时网搜验证结果，趁结算前买入吃价差。这套玩法有个正经说法叫 ["高确定性债券" 策略](https://www.panewslab.com/en/articles/c1772590-4a84-46c0-87e2-4e83bb5c8ad9)：每笔赚一点确定性的小钱。

Agent 在 session 之间维护**长期交易日志**，记住自己买了什么、为什么买、结果怎样。赔了会反思，会修正策略笔记，还会通过 D-mail 自己安排下一次唤醒时间。如果你有一台闲着的机器，这相当于把闲置算力变成 7x24 的预测市场 scalper。

开源之前我们让它自主跑了两周：**19 笔交易，18 笔盈利（94.7% 胜率）**，净赚，链上提现已验证。你的钱包、你的私钥，不需要 Polymarket 账号。

<p align="center">
  <img src="images/example_webui.png" alt="Dashboard Screenshot" width="900">
</p>

**在线查看**: [Dashboard](https://homosapiens.capital/#/live) | [钱包 on Polygonscan](https://polygonscan.com/address/0xFd0A48d7f4867446a5165AEaB35c42f8B529dBf0)

---

## 工作原理

本项目基于 **[Claude Agent SDK](https://docs.anthropic.com/en/docs/claude-code/sdk)**，通过编程方式启动 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) session。这**不是**简单的 API 调用 -- 每次调用都会起一个完整的 Claude Code 进程，能用 MCP 工具、网搜、读写文件、跑 bash。Scheduler 只管*什么时候*叫醒它，Claude 自己决定*干什么*。

```
Scheduler (agent/scheduler.py)
  |
  |  claude_agent_sdk.query()
  |  = 启动完整的 Claude Code session
  v
Claude Code session
  |-- MCP tools    -> find_opportunities, place_order, get_balance, ...
  |-- WebSearch    -> 下单前网搜验证结果
  |-- Read/Edit    -> 读账本，写交易日志
  |-- hibernate()  -> 设下次唤醒时间 + 留 D-mail
  v
Scheduler 睡到 wake_time，然后重复
```

### MCP 工具是什么？

[MCP (Model Context Protocol)](https://modelcontextprotocol.io/) 让你给 Claude 接自定义工具。本项目提供了一个 Polymarket MCP server，包含 `find_opportunities`、`place_order`、`get_balance` 等工具。Claude 自主调用这些工具完成交易。

### Hibernate / D-mail 是什么？

Hibernate 是 Agent 的自调度机制。开启后（`config/risk.py`），Agent 进入自主循环：扫描、交易、然后调 `hibernate(hours, d_mail)` 进入睡眠。D-mail 是留给未来自己的消息 -- 比如 *"UFC 赛事 22:00 UTC 结束，醒来看结果"*。Scheduler 读取 D-mail，到点唤醒 Agent。

不开 hibernate 的话，Scheduler 按固定间隔运行（`--interval`，默认 30 分钟）。

灵感来自 [Steins;Gate 的 D-mail](https://steins-gate.fandom.com/wiki/D-Mail)。

---

## 快速开始

### 前置条件

- Python 3.11+
- Node.js 18+（装 Claude Code CLI 用，Dashboard 也需要）

### 安装

```bash
npm install -g @anthropic-ai/claude-code  # 已装过就跳过
claude login

git clone https://github.com/LainNet-42/polymarket-auto-trading-agent.git
cd polymarket-auto-trading-agent
python setup.py
```

安装脚本一键搞定：虚拟环境、依赖、钱包生成（或导入已有私钥）、`.env`、MCP server 注册、hooks。Mac / Linux / Windows 通用。

装完之后，往钱包充 **POL**（gas 费）+ **USDC**（交易本金），走 **Polygon 网络**，然后：

```bash
python setup.py --approve          # 一次性钱包授权（约 6 笔交易）
python -m agent.scheduler          # 启动（持续运行）
python -m agent.scheduler --once   # 或跑一次就退出
```

> **充值提示:** 充约 5 POL（约 $0.50）做 gas + 任意金额 USDC。从交易所提现时**必须选 Polygon 网络**（不是以太坊）。Coinbase、Binance、Kraken、OKX 都支持。Agent 启动时会自动把 native USDC 换成 USDC.e。

### 提现

在 `.env` 里设好 `WITHDRAW_DESTINATION`，然后：

```bash
PYTHONPATH=. python scripts/withdraw.py status          # 查余额
PYTHONPATH=. python scripts/withdraw.py send --amount 50 # 提 $50 USDC.e
```

<details>
<summary><strong>手动安装（逐步）</strong></summary>

### 第 1 步：Clone 并安装

```bash
git clone https://github.com/LainNet-42/polymarket-auto-trading-agent.git
cd polymarket-auto-trading-agent

python3 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

pip install -e ".[trading]"
```

> **注意**: Mac/Linux 用 `python3`，Windows 或虚拟环境里直接 `python`。

### 第 2 步：创建钱包

你需要一个 Polygon 上的标准以太坊钱包（EOA）。**不需要注册 Polymarket 账号** -- Polymarket 是非托管的，资金始终在你钱包里。

**方法 A**: Python 生成：
```bash
python -c "from eth_account import Account; a=Account.create(); print(f'Address: {a.address}\nPrivate Key: {a.key.hex()}')"
```

**方法 B**: MetaMask 导出，Settings > Security 里找私钥。

### 第 3 步：充值

钱包需要 **Polygon** 网络上的两种代币：

| 代币 | 用途 | 数量 | 获取方式 |
|------|------|------|----------|
| **POL** | Gas 费（约 0.01-0.30 POL/笔） | 约 5 POL（约 $0.50） | 交易所购买，提现到 Polygon |
| **USDC** | 交易本金 | 任意金额 | 从交易所发 USDC 到你的 Polygon 地址 |

> **重要：提现时选对网络！**
> - 必须选 **Polygon 网络**
> - 不要选 "Ethereum (ERC-20)" -- 走以太坊主网的资金用不了
> - 不是所有交易所都支持 Polygon 提现。Coinbase、Binance、Kraken、OKX 支持。部分小所只支持以太坊
> - 如果你的交易所不支持 Polygon，需要走跨链桥（要 ETH gas）或换一家

**备注：**
- 可以充 **native USDC** 或 **USDC.e** -- Agent 每次启动时自动通过 Uniswap V3 把 native USDC 换成 USDC.e
- Polymarket CLOB 只接受 USDC.e（桥接 USDC）
- Gas 费因操作而异：普通转账约 0.02 POL，赎回约 0.07-0.30 POL
- `set_allowances.py`（第 7 步）发约 6 笔授权交易，共约 1-2 POL
- 5 POL 够用几百笔交易

### 第 4 步：配置 .env

```bash
cp .env.example .env
```

用第 2 步的私钥和地址填 `.env`：

```env
POLYGON_WALLET_PRIVATE_KEY=0x_your_private_key
EOA_ADDRESS=0x_your_address
```

API 凭证从私钥自动派生，不用手动填。

### 第 5 步：注册 MCP Server

```bash
claude mcp add polymarket -- python -m mcp_server.server
```

> **注意**: `--` 是分隔符，用来区分 Claude CLI 参数和 Python 命令。

这一步让 Claude 拿到 Polymarket 交易工具。

### 第 6 步：启用 Hooks

```bash
cp .claude/settings.local.json.example .claude/settings.local.json
```

Hooks 在每次 Agent session 中自动执行：
- **SessionStart**: 自动赎回收益、转换 USDC、同步持仓、检查止损、注入余额上下文
- **PostToolUse**: 记录所有 MCP 工具调用，用于审计

### 第 7 步：一次性钱包授权

```bash
PYTHONPATH=. python scripts/set_allowances.py
```

> **注意**: `PYTHONPATH=.` 必须加，不然 Python 找不到本地 `config` 模块。

这会发约 6 笔交易，授权 Polymarket 交易合约操作你的 USDC.e 和条件代币。每个钱包只需跑一次，约 1-2 POL gas 费。

### 第 8 步：运行

```bash
# 跑一次（扫描、有机会就交易、然后退出）
python -m agent.scheduler --once

# 持续运行（Agent 通过 hibernate 自我调度）
python -m agent.scheduler

# 或用 shell 脚本
./start_agent.sh
```

</details>

---

## Dashboard（可选）

实时监控面板：账户价值走势、实时持仓、D-mail 查看器、Agent 执行轨迹。

```bash
cd web-ui/frontend && npm install && npm run build && cd ../..
cd web-ui/backend-py && pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080
```

打开 http://localhost:8080

---

## MCP 工具

| 工具 | 功能 |
|------|------|
| `find_opportunities` | 扫描即将到期的高确定性二元市场 |
| `get_market_details` | 市场规则、CLOB 价格、token ID |
| `place_order` | 下单（内置风控：最高价格、仓位上限） |
| `get_balance` | USDC 余额 |
| `hibernate` | 睡 N 小时，留 D-mail 给下次唤醒 |
| `get_price_history` | 历史价格 |
| `analyze_opportunity` | 风险评估 |
| `detect_anomalies` | 异常价格波动检测 |
| `search_markets` | 关键词搜索 |

---

## 默认策略

| 规则 | 值 |
|------|------|
| 市场类型 | 仅二元 YES/NO |
| 最高买入价 | $0.99（绝不买更贵的） |
| 单市场仓位上限 | 组合的 20% |
| 止损 | 跌破入场价 20% 自动卖出 |
| 自动赎回 | 结算时自动将盈利仓位赎回为 USDC.e |

---

## 自定义

以下文件是专门留给你改的：

| 文件 | 能改什么 | 默认值 |
|------|---------|--------|
| `config/risk.py` | 最高买入价、仓位上限、止损线、hibernate 时间范围 | 0.99, 20%, 20%, 0.5-24h |
| `agent/prompts.py` | Agent 人设、交易策略、决策标准、记忆笔记 | 高确定性二元市场 |
| `.env` | 钱包密钥、工作目录、RPC 端点 | 见 `.env.example` |
| `web-ui/frontend/.env` | Dashboard API 地址、初始本金（算盈亏用） | localhost:8080, $100 |

---

## 项目结构

```
agent/           Claude Agent SDK 入口、调度器、提示词
mcp_server/      Polymarket MCP 工具（查找、交易、分析、hibernate）
hooks/           Claude Code hooks（自动赎回、审计日志）
polymarket/      Polymarket API 客户端库（Gamma + CLOB）
config/          风险参数、路径配置
scripts/         钱包设置、提现、独立扫描器
web-ui/          React + FastAPI 监控面板
```

---

## 贡献

### Roadmap

- [x] ~~**实盘验证** -- 开源前 Agent 自主跑了两周，净盈利。~~
- [ ] **多模型支持** -- 目前只支持 Claude。计划接入 Kimi、OpenAI、Gemini 或本地模型。核心 MCP 工具本身跟模型无关，耦合点在 `agent/scheduler.py` 和 `agent/prompts.py`。
- [ ] **Agent 框架集成** -- 本项目天然适合作为 [OpenClaw](https://github.com/openclaw/openclaw)、[Claude Code](https://docs.anthropic.com/en/docs/claude-code) 等 Agent 平台的 skill/plugin。思路：把核心 MCP 工具封装成独立脚本，打包成 **skill**，D-mail/hibernate 变成 **heartbeat**。这样能大幅简化 -- 不需要自定义调度器，不需要 Claude Agent SDK 依赖，就是一个任何 Agent 都能用的 skill。
- [ ] **策略库** -- 现在的到期收敛策略效果不错，但只是玩法之一。跨市场套利、波动率策略、事件驱动交易 -- 用现有 MCP 工具都能实现。

### 代码风格

- 文件路径统一用 `pathlib.Path`（跨平台）
- 不硬编码密钥、代理或机器相关路径
- 风险参数放 `config/risk.py`，MCP 工具放 `mcp_server/tools/`

---

## 常见问题

**Q: 我完全按步骤操作了，但交易失败 / API 返回 403**

> **A:** Polymarket 限制了部分地区的访问。去[官方地区限制页面](https://docs.polymarket.com/polymarket-learn/FAQ/geoblocking)看看你的国家是否在列。

**Q: "Transaction failed" 或 "nonce too low"**

> **A:** 一般是上一笔交易还没确认。等几秒重试就行，Agent 下次运行时会自动处理 nonce。

**Q: "insufficient funds for gas"**

> **A:** 钱包里没有 POL。Polygon 上交易需要 POL 做 gas，充约 5 POL（约 $0.50）就够了。单笔 gas 在 0.02（转账）到 0.30 POL（赎回）之间，5 POL 够用几百笔。

**Q: USDC 余额显示 0，但我明明充了**

> **A:** 检查是不是走了 **Polygon 网络**，不是以太坊主网。如果充的是 native USDC，下次 Agent 启动时会自动换成 USDC.e。

**Q: `set_allowances.py` 跑失败了**

> **A:** 确保钱包里至少有约 2 POL 的 gas（脚本要发约 6 笔授权交易）。每个钱包只需跑一次 -- 如果之前已授权过，部分交易 revert 是正常的。默认 RPC 太慢的话，在 `.env` 里设 `POLYGON_RPC_URL`。

**Q: Agent 扫不到机会**

> **A:** 正常。Agent 只做高确定性市场（90%+ 概率），且必须 48 小时内到期。没有满足条件的市场时，它会 hibernate 等下一轮。可以在 `config/risk.py` 调阈值，或在 `agent/prompts.py` 改策略。

**Q: Dashboard 报 "connection refused"**

> **A:** 确认后端在跑：在 `web-ui/backend-py/` 目录下执行 `uvicorn main:app --host 0.0.0.0 --port 8080`。检查 `web-ui/frontend/.env` 里的 `VITE_API_URL` 指向是否正确。如果用了代理，加 `NO_PROXY=localhost` 避免干扰。

**Q: 认证是怎么回事？**

> **A:** 只需要**私钥**。CLOB API 凭证通过 `py_clob_client` 从私钥自动派生。不需要 Polymarket 账号，不需要申请 API key，不需要 Builder API -- 一把私钥搞定。

**Q: 能在服务器 / VPS 上跑吗？**

> **A:** 能。Agent 不需要图形界面，任何装了 Python 3.11+ 和 Claude Code 的机器都行。用 `./start_agent.sh` 或 `python -m agent.scheduler` 放在 tmux/screen 里跑，或者配个 systemd service。

**Q: 私钥安全吗？**

> **A:** 私钥只存在本地 `.env` 文件里（已在 `.gitignore` 中排除），除了在 Polygon 链上签名交易外不会发给任何外部服务。Agent 完全在你的机器上运行。

---

## 免责声明

本软件仅供教育和研究用途。预测市场交易涉及真实的财务风险，使用风险自负。作者不对任何损失承担责任。

## 致谢

- Dashboard UI 灵感来自 [coke-nof1](https://github.com/cokepoppy/coke-nof1)

## License

[MIT](LICENSE)

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=LainNet-42/polymarket-auto-trading-agent&type=date&legend=top-left)](https://www.star-history.com/#LainNet-42/polymarket-auto-trading-agent&type=date&legend=top-left)
