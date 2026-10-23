# UZI Market Relay — current status (2026-10-23)

**Historical data fallback is live as code, but must pass the first real download.**
GitHub-hosted Binance futures REST returned HTTP 451; the fast REST publisher is manual-only until an authorized provider is connected.
Use `Publish delayed SOXLUSDT 1D and 4H Binance Vision archive` for officially published *delayed* Klines, scheduled once daily. Its output is `data/SOXLUSDT-historical.json` (NOT real-time and no funding/OI/mark price).
Do not use an archived candle as a current entry signal. For live data, first verify third-party coverage and licensing for the exact Binance SOXLUSDT pair.

---

# UZI Market Relay — SOXLUSDT read-only GitHub snapshot

## 核心方案

```
Binance USD-M 公共 REST（无密钥）
  -> 允许合法访问的 Codex/服务器/GitHub Actions 执行环境
  -> data/SOXLUSDT.json (GitHub repository)
  -> ChatGPT GitHub connector -> UZI 合约分析 Skill
```

**这是近实时快照，不是交易毫秒级实时报价。** 公开数据不含密钥、账户、持仓或交易历史。接收端必须重新核验快照年龄。SOXL ETF 实盘、美股期权 Max Pain 不在此包的输出中。

## 步骤 1：把这个包放进你自己的 GitHub 仓库

1. 新建一个仅用于行情的 GitHub 仓库，例如 `uzi-market-data`（推荐单独建仓，避免改上游 `wbh604/UZI-Skill`）。公开仓库最容易读取；如果是私有仓库，确保 ChatGPT 的 GitHub 连接器对它有读取权限。
2. 把本包解压后的 `scripts/`、`tests/`、`data/`、`.github/workflows/publish.yml`、`README.md` 上传到该仓库根目录。
3. 在 GitHub 仓库 `Settings -> Actions -> General -> Workflow permissions` 设置允许本仓库 GitHub Actions 写入内容（只用于 `data/SOXLUSDT.json`）。工作流 YAML 有 `permissions: contents: write`。如组织安全策略禁止自动写入，请使用组织批准的部署方式。
4. 点击 `Actions -> Publish SOXLUSDT public-market snapshot -> Run workflow` 手动测试一次。
5. 成功时，访问仓库中的 `data/SOXLUSDT.json`，核对 `schema`、`generated_at_utc`、`required_quote_times`、`status_at_publication`、`analysis.technical.1d` 和 `analysis.technical.4h`。

旧实时 REST 工作流已停止每5分钟的定时请求；历史归档工作流每日尝试更新，但 GitHub可能延迟或跳过计划任务；**绝不能把定时计划等同实时成交行情**。读快照时，如果关键价位源时间已超过15分钟，请显示过期并拒绝当前精确交易信号。

**重要：Github-hosted runner 不保证能访问币安**。若诊断报 HTTP 451/403、DNS 或地区拒绝，停止该采集方案，不得通过代理/其他地区主机规避合规限制。改用在适用地区获授权的数据供应商，或在符合所在地及服务条款的网络使用官方接口。

## 步骤 2：在允许访问 Binance USD-M 的工作环境本地测试

```bash
python3 scripts/analyze_futures.py --diagnose
python3 scripts/publish_snapshot.py --symbol SOXLUSDT --output data/SOXLUSDT.json
python3 -m unittest discover -s tests -v
```

脚本仅调用 `https://fapi.binance.com` 的以下公开接口：
`/fapi/v1/ticker/24hr`、`/fapi/v1/premiumIndex`、`/fapi/v1/openInterest`、`/fapi/v1/ticker/bookTicker`、`/fapi/v1/klines`（1d/4h）、`/futures/data/openInterestHist`（1d/4h）、`/fapi/v1/fundingRate`。从不调用交易类 POST/DELETE 接口。

## 步骤 3：在 ChatGPT 的 UZI SKILL 项目内配置

在项目指令中加一句（把 `<你的GitHub用户名>` 换成你的用户名）：

```
分析 SOXLUSDT 时，优先通过 GitHub 连接器读取
仓库 <你的GitHub用户名>/uzi-market-data 的 data/SOXLUSDT.json。
仅把它当作只读币安市场快照，先核对 source、symbol、
required_quote_times、generated_at_utc、status_at_publication，
以当前 UTC 分别计算最新成交价与标记价的数据年龄。
任意关键行情超过15分钟、字段缺失、来源不一致时明确标记过期，
不得输出实时入场信号。1d 趋势优先、4h 波段次之。
无法读取仓库时再使用已经配置好的 UZI 合约分析降级流程。
```

然后输入 `分析 SOXLUSDT`，ChatGPT 可通过 GitHub 已连接的 API 读取 JSON，不需要在本地 Python 容器里直连币安，也不需要公开 HTTPS 服务器地址。

## 备用运行方式：不用 GitHub Actions

如果 GitHub Actions 运行环境不适用，而**你的固定工作机器经合规校验可访问币安官方市场数据**，可以用操作系统定时器运行上面的 `publish_snapshot.py` 并将 `data/SOXLUSDT.json` 推送到同一 GitHub 仓库。需保证机器持续在线，并通过 git credential manager 或 GitHub CLI 安全存储 GitHub 授权，不要把 GitHub Token 写进脚本或聊天内容。

## 时效与质量边界

- `realtime_at_publication` 只证明**生成当时**的交易所数据时效，不代表 ChatGPT 读取时仍然新鲜。
- GitHub 文件提交时间不是交易所行情时间；不根据 commit timestamp 推断行情。
- 1d/4h 趋势只采用已收盘K线；当日线与4h分歧时，标明反弹/回调而不是机械改变主趋势。
- OI 历史或特别费率缺失则留空；股息特别费用不会算作常规 funding。
- 不传账户信息，不需要模拟盘 API，也不提供下单功能。
- 该方案并不绕过任何交易所所在地政策；若 Binance 接口在某处不可合法访问，应使用当地合法获许可的数据提供方。
