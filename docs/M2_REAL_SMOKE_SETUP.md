# M2 Real Smoke 本地环境与人工验证指南

> 状态：**仅用于 M2-D 人工低量真实验证准备。当前仓库 CI/Fixture 不等于真实平台验证。**
>
> 本文不包含任何真实 Cookie、Token、账号密码、二维码、localStorage 或个人机器绝对路径。所有 `<...>` 都必须由本地操作员在自己的环境中填写，且不得提交 Git。

## 1. 适用范围与停止规则

首批平台：

- B站：低量 search engineering gate READY；REAL SMOKE 仍 NOT_TESTED。
- 知乎：低量 search engineering gate READY；REAL SMOKE 仍 NOT_TESTED。
- 微博：detail 工程入口存在，但 **LOW_VOLUME_SEARCH BLOCKED**；不得执行微博 search smoke。

本指南不进入 M3，不涉及 Event / Embedding / 聚类 / AI。

任何真实阶段出现以下任一信号，必须立即停止：

- HTTP 403 / 406 / 429；
- CAPTCHA / 人机验证；
- automation detected / AI-operation detection；
- login expired / repeated login invalidation；
- account abnormal / restricted / blocked；
- 平台明确的反自动化或账号异常提示。

停止后：不重试、不换账号、不换 Browser Profile、不换代理、不做 proxy rotation、不修改签名、不做验证码绕过或 stealth/fingerprint 处理。保留 Run / Checkpoint / RiskEvent 的安全证据，进入人工复核。

---

## 2. 软件要求

### 2.1 主系统

当前项目要求：

- Python：`>=3.11,<3.14`；推荐与 CI 一致使用 Python 3.11。
- Node.js：项目 README 使用 Node.js 22。
- PostgreSQL：项目 Docker Compose 使用 `pgvector/pgvector:pg16`。
- pgvector：由 `docker/postgres/init.sql` 创建 `vector` extension，同时创建 `pgcrypto`。
- Docker Desktop / Docker Engine + Compose。
- Chrome 或 Edge：用于人工登录和 existing-CDP 9222。

### 2.2 MediaCrawler runtime 必须与主系统 Python 环境隔离

主项目 FastAPI 约束为 `>=0.115,<1`，vendored MediaCrawler requirements 固定 `fastapi==0.110.2`，因此不要把两套依赖混装到同一个 venv。

Windows PowerShell 示例：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"

New-Item -ItemType Directory -Force .runtime | Out-Null
python -m venv .runtime\mediacrawler-venv
.\.runtime\mediacrawler-venv\Scripts\python.exe -m pip install --upgrade pip
.\.runtime\mediacrawler-venv\Scripts\python.exe -m pip install -r third_party\MediaCrawler\requirements.txt
```

`.runtime/` 已加入 `.gitignore`。

将 MediaCrawler interpreter 配置到本机 `.env` 或当前 shell；不要提交真实绝对路径：

```powershell
$McPython = (Resolve-Path ".runtime\mediacrawler-venv\Scripts\python.exe").Path
$env:MEDIACRAWLER_PYTHON = $McPython
```

如果写入 `.env`，使用本机解析后的 interpreter 路径；`.env` 已被 Git 忽略。

---

## 3. 初始化 `.env` 与 PostgreSQL / pgvector

复制模板：

```powershell
Copy-Item .env.example .env
```

至少填写本地值：

```text
POSTGRES_PASSWORD=<LOCAL_ONLY_PASSWORD>
DATABASE_URL=postgresql+asyncpg://ai_editorial:<LOCAL_ONLY_PASSWORD>@127.0.0.1:55432/ai_editorial
APP_SECRET_KEY=<LOCAL_RANDOM_STRING_AT_LEAST_32_CHARS>
APP_ADMIN_TOKEN=<LOCAL_ADMIN_TOKEN_AT_LEAST_24_CHARS>
MEDIACRAWLER_HOME=third_party/MediaCrawler
MEDIACRAWLER_PYTHON=<LOCAL_MEDIACRAWLER_PYTHON_ABSOLUTE_PATH>
MEDIACRAWLER_PROFILE_ROOT=.runtime/mediacrawler_profiles
```

不得把真实 secret 提交 Git。

启动数据库：

```powershell
docker compose up -d postgres
docker compose ps
```

Docker Compose 只把 PostgreSQL 暴露到 `127.0.0.1:${POSTGRES_PORT:-55432}`。

---

## 4. Migration 与 Definition sync

在主系统 venv 中：

```powershell
.\.venv\Scripts\Activate.ps1
alembic upgrade head
python -m scripts.sync_connector_definitions
python -m scripts.sync_connector_definitions
```

第二次 Definition sync 应保持幂等。当前工程基线总 Definition 数为 11，其中 MediaCrawler 为 7 个平台。

如需确认 pgvector：

```powershell
docker compose exec postgres psql -U ai_editorial -d ai_editorial -c "SELECT extname FROM pg_extension WHERE extname IN ('vector','pgcrypto') ORDER BY extname;"
```

---

## 5. 启动 API 与 Web

API：

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn apps.api.main:app --reload
```

默认地址为 `127.0.0.1:8000`。

Web 另开终端：

```powershell
cd apps\web
npm install
npm run dev
```

Scheduler 不是手工 Smoke 的必要条件；如需查看调度状态可单独启动：

```powershell
python -m apps.scheduler.main
```

内部 Admin API 前缀：

```text
/api/v1/admin
```

读取接口需要 `X-Admin-Token`；所有修改操作还必须提供 `X-Actor-ID`。

PowerShell 可先准备本地 Header：

```powershell
$Api = "http://127.0.0.1:8000/api/v1/admin"
$Headers = @{
  "X-Admin-Token" = $env:APP_ADMIN_TOKEN
  "X-Actor-ID" = "m2d-local-operator"
}
```

不要把 `APP_ADMIN_TOKEN` 打印、截图或提交到文档。

---

## 6. 创建专用低价值测试 Instance / Account / Source

### 6.1 原则

- 只使用专用、低价值测试账号，与个人账号/正式业务账号隔离。
- 不自动注册账号，不做批量账号、账号轮换。
- `credential_ref` 只能是秘密管理系统中的**不透明引用**；不得填 Cookie、Token、密码或 localStorage 内容。
- M2-D 当前以人工 Browser Profile 登录为主，允许 `credential_ref=null`。
- `browser_profile_ref` 只填写短 opaque ref，例如 `bili-smoke-01`；不得填写绝对路径、`..` 或带 `/`、`\` 的路径。
- Browser Profile 的真实目录由 `MEDIACRAWLER_PROFILE_ROOT/<browser_profile_ref>` 在本机解析，不写进 Git。

### 6.2 查询平台 Definition

以 B站为例：

```powershell
$Definition = Invoke-RestMethod `
  -Headers $Headers `
  -Uri "$Api/connector-definitions?connector_type=mediacrawler&platform=bilibili"
$Definition.items | Select-Object id, platform, implementation_version, is_enabled
```

B站/知乎/微博是 M2-D 首批 Definition；若目标 Definition 为 disabled，先在管理端确认原因，不通过数据库手工绕过 Gate。

### 6.3 创建 Connector Instance

使用上一步的 Definition ID。下面只展示结构，值均为本地测试占位：

```powershell
$Body = @{
  definition_id = "<DEFINITION_UUID>"
  name = "m2d-bilibili-smoke"
  config = @{
    modes = @("detail", "search", "comments")
    keyword = "m2d-smoke-placeholder"
    content_ids = @("<PUBLIC_CONTENT_ID_OR_URL_PLACEHOLDER>")
    include_comments = $false
    comment_limit = 0
    include_subcomments = $false
    timeout_seconds = 120
  }
  schedule_config = @{}
} | ConvertTo-Json -Depth 8

$Instance = Invoke-RestMethod -Method Post -Headers $Headers `
  -ContentType "application/json" -Body $Body `
  -Uri "$Api/connector-instances"

Invoke-RestMethod -Method Post -Headers $Headers `
  -Uri "$Api/connector-instances/$($Instance.id)/enable"
```

不要创建自动 Schedule；M2-D 使用 Test/Manual smoke。

### 6.4 创建低价值 Platform Account

```powershell
$AccountBody = @{
  connector_instance_id = $Instance.id
  platform = "bilibili"
  display_name = "M2-D Bilibili Low Value Test"
  account_identifier = "bili-smoke-test-01"
  credential_ref = $null
  browser_profile_ref = "bili-smoke-01"
} | ConvertTo-Json

$Account = Invoke-RestMethod -Method Post -Headers $Headers `
  -ContentType "application/json" -Body $AccountBody `
  -Uri "$Api/platform-accounts"
```

API 响应只应关注 `credential_configured` / `browser_profile_configured`，不要把真实秘密值放入请求体。

### 6.5 创建三个独立 Source

建议 Detail / Search / Comments 使用独立 Source，避免修改同一 Source 时误带评论参数。

Detail Source：

```powershell
$DetailSourceBody = @{
  connector_instance_id = $Instance.id
  name = "m2d-bili-detail"
  source_type = "mediacrawler"
  mode = "detail"
  scope_key = "m2d:bilibili:detail"
  external_ref = $null
  config = @{
    content_ids = @("<PUBLIC_BILIBILI_ID_OR_URL>")
    include_comments = $false
    comment_limit = 0
    include_subcomments = $false
    timeout_seconds = 120
  }
  enabled = $true
} | ConvertTo-Json -Depth 8
```

Search Source：

```powershell
$SearchSourceBody = @{
  connector_instance_id = $Instance.id
  name = "m2d-bili-search"
  source_type = "mediacrawler"
  mode = "search"
  scope_key = "m2d:bilibili:search"
  external_ref = $null
  config = @{
    keyword = "<LOW_RISK_TEST_KEYWORD>"
    include_comments = $false
    comment_limit = 0
    include_subcomments = $false
    timeout_seconds = 120
  }
  enabled = $true
} | ConvertTo-Json -Depth 8
```

Comments Source：

```powershell
$CommentsSourceBody = @{
  connector_instance_id = $Instance.id
  name = "m2d-bili-comments"
  source_type = "mediacrawler"
  mode = "comments"
  scope_key = "m2d:bilibili:comments"
  external_ref = $null
  config = @{
    content_ids = @("<PUBLIC_BILIBILI_ID_OR_URL>")
    include_comments = $true
    comment_limit = 5
    include_subcomments = $false
    timeout_seconds = 120
  }
  enabled = $true
} | ConvertTo-Json -Depth 8
```

创建命令：

```powershell
$DetailSource = Invoke-RestMethod -Method Post -Headers $Headers -ContentType "application/json" -Body $DetailSourceBody -Uri "$Api/sources"
$SearchSource = Invoke-RestMethod -Method Post -Headers $Headers -ContentType "application/json" -Body $SearchSourceBody -Uri "$Api/sources"
$CommentsSource = Invoke-RestMethod -Method Post -Headers $Headers -ContentType "application/json" -Body $CommentsSourceBody -Uri "$Api/sources"
```

在第一次真实 Detail 前，公开内容 ID/URL 必须由人工明确提供；禁止为了寻找测试内容而额外执行 search。

---

## 7. 创建极低 Account Budget

推荐直接给测试 Account 加一条 account-scope Budget：

```powershell
$BudgetBody = @{
  scope_type = "account"
  scope_key = "$($Account.id)"
  max_runs_per_day = 3
  max_items_per_run = 5
  max_items_per_day = 15
  max_comments_per_run = 5
  max_comments_per_day = 15
  max_concurrency = 1
  timezone = "Asia/Shanghai"
  enabled = $true
} | ConvertTo-Json

$Budget = Invoke-RestMethod -Method Post -Headers $Headers `
  -ContentType "application/json" -Body $BudgetBody `
  -Uri "$Api/collection-budgets"
```

`check_m2_smoke_environment` 不会自动创建 Budget：没有显式适用 Budget 会 BLOCKED；至少一条适用 Budget 必须满足上述 M2-D 安全上限。

---

## 8. Browser Profile root 与 Chrome/Edge CDP 9222

### 8.1 建立受控 Profile root

```powershell
New-Item -ItemType Directory -Force .runtime\mediacrawler_profiles | Out-Null
$ProfileRoot = (Resolve-Path ".runtime\mediacrawler_profiles").Path
$ProfileRef = "bili-smoke-01"
$ProfileDir = Join-Path $ProfileRoot $ProfileRef
New-Item -ItemType Directory -Force $ProfileDir | Out-Null
```

`BrowserProfileResolver` 要求该目录真实存在、位于 root 下、不是 symlink；ref 不能包含路径跳转。

### 8.2 按当前仓库 BrowserLauncher 的 Windows 检测范围找 Chrome/Edge

```powershell
$BrowserCandidates = @(
  "$env:PROGRAMFILES\Google\Chrome\Application\chrome.exe",
  "${env:PROGRAMFILES(X86)}\Google\Chrome\Application\chrome.exe",
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
  "$env:PROGRAMFILES\Microsoft\Edge\Application\msedge.exe",
  "${env:PROGRAMFILES(X86)}\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { $_ -and (Test-Path $_) }

$Browser = $BrowserCandidates | Select-Object -First 1
if (-not $Browser) { throw "Chrome/Edge not found in the project-supported stable paths" }
```

### 8.3 确认 9222 未占用，并启动独立可见浏览器

```powershell
$Existing = Get-NetTCPConnection -LocalPort 9222 -State Listen -ErrorAction SilentlyContinue
if ($Existing) { throw "Port 9222 is already in use; inspect it before continuing" }

Start-Process -FilePath $Browser -ArgumentList @(
  "--remote-debugging-port=9222",
  "--user-data-dir=$ProfileDir",
  "--no-first-run",
  "--no-default-browser-check",
  "--start-maximized"
)
```

本指南不增加 stealth、fingerprint、proxy、AutomationControlled、验证码或反风控参数。

确认本机端口：

```powershell
Test-NetConnection 127.0.0.1 -Port 9222
```

`TcpTestSucceeded` 应为 `True`。

可进一步只在本机确认监听进程是刚才启动的 Chrome/Edge：

```powershell
$Conn = Get-NetTCPConnection -LocalPort 9222 -State Listen | Select-Object -First 1
Get-CimInstance Win32_Process -Filter "ProcessId=$($Conn.OwningProcess)" |
  Select-Object Name, ExecutablePath, CommandLine
```

这些本机路径不要复制进 Git、Issue、PR 或 Validation evidence。

---

## 9. 零平台请求 Environment Preflight

在**尚未登录平台也可以执行**；它不会打开平台页面、不会读取 Cookie、不会创建 Run、不会运行 CollectorRuntime、不会写 Validation。

以 B站 Detail Source 为例：

```powershell
python -m scripts.check_m2_smoke_environment `
  --platform bilibili `
  --connector-instance-id $Instance.id `
  --source-id $DetailSource.id `
  --account-id $Account.id `
  --mode detail `
  --requested-limit 1 `
  --comment-limit 0
```

它只检查：

- `DATABASE_URL` 可连接；
- Alembic DB revision 等于本地 head；
- Definitions 为 11 个、MediaCrawler 为 7 个；
- pinned MediaCrawler commit 记录和 vendored entry files 存在；
- 目标 Definition / Instance / Source 状态；
- localhost:9222 TCP；
- Profile root 与 opaque profile ref 的本地解析；
- Account 是否 runnable；
- 显式低量 Budget；
- unresolved RiskEvent；
- proxy=false 安全边界；
- 目标平台当前 low-volume search engineering Gate；
- Validation 当前状态（只读）。

输出只包含 `READY` / `BLOCKED` 和安全原因，不输出 `credential_ref`、`browser_profile_ref`、Profile path、DATABASE_URL 或任何 Cookie。

微博 `--mode search` 必须保持 `BLOCKED`。

---

## 10. 人工登录与 login-only preflight

### 10.1 人工登录

只有在项目负责人明确进入某个平台人工登录 Gate 后才操作。

在第 8 节刚启动的**独立测试浏览器窗口**中，由人工打开目标平台并登录专用低价值账号。不要把密码、Cookie、Token、二维码或浏览器存储发送给项目代码或聊天记录。

登录后保持浏览器和 9222 开启。

### 10.2 login-only preflight

仓库提供：

```text
python -m scripts.check_m2_smoke_login
```

它会先重复第 9 节环境 Gate。全部 READY 后，仅连接 `127.0.0.1:9222` existing CDP，并从本地浏览器 cookie store **只判断预期登录标记名称是否存在**；不读取/输出 cookie value，不 `goto` 页面，不发 detail/search/comments，不创建 Run，不写 Validation。

B站 Detail 示例：

```powershell
python -m scripts.check_m2_smoke_login `
  --platform bilibili `
  --connector-instance-id $Instance.id `
  --source-id $DetailSource.id `
  --account-id $Account.id `
  --mode detail `
  --requested-limit 1 `
  --comment-limit 0 `
  --actor "m2d-local-operator" `
  --confirm M2D_LOGIN_PREFLIGHT
```

`READY + login_state=valid` 仅表示本地登录标记存在，**不是**真实内容接口已验证，也不能产生 PASSED Validation。

如果 `requires_interaction` / `unknown`：停止，不自动扫码、不自动填 Cookie、不重新登录循环。

---

## 11. 第一个真实 Detail Smoke：严格 1 条

必须在：

1. Environment Preflight READY；
2. 人工登录完成；
3. login-only preflight READY；
4. 再次取得明确人工确认；
5. 已由人工提供一个普通公开内容 ID/URL；

之后才能执行。

B站示例：

```powershell
python -m scripts.mediacrawler_smoke `
  --execute `
  --platform bilibili `
  --connector-instance-id $Instance.id `
  --source-id $DetailSource.id `
  --account-id $Account.id `
  --mode detail `
  --requested-limit 1 `
  --actor "m2d-local-operator" `
  --confirm M2D_REAL_SMOKE
```

Detail Source 必须：

- `include_comments=false`
- `comment_limit=0`
- `include_subcomments=false`

Smoke bridge 强制：concurrency=1、proxy=false、visible existing CDP、subcomments=false，并禁止自动登录和标准浏览器 fallback。

**Detail 完成后立即停下检查结果，不要自动继续 Search。**

---

## 12. Search <= 5

只有目标平台 search engineering Gate READY 且 Detail 已稳定通过、再次取得人工确认后执行。

B站 / 知乎：

```powershell
python -m scripts.mediacrawler_smoke `
  --execute `
  --platform bilibili `
  --connector-instance-id $Instance.id `
  --source-id $SearchSource.id `
  --account-id $Account.id `
  --mode search `
  --requested-limit 5 `
  --actor "m2d-local-operator" `
  --confirm M2D_REAL_SMOKE
```

- B站 compatibility patch：`requested_limit=1/3/5` 时 client `page_size=1/3/5`。
- 知乎 compatibility patch：`requested_limit=1/3/5` 时 client `page_size=1/3/5`，client 已正式把它映射到 `offset` / `limit`。
- 微博：当前 pinned client 没有已证实的 page_size/count/limit 参数，**禁止运行 search smoke**。

不得采用“请求 20/10 条后本地只保存 5 条”来冒充低量请求。

---

## 13. Comments <= 5

必须在对应主内容 Detail 稳定通过并再次取得人工确认后执行。

```powershell
python -m scripts.mediacrawler_smoke `
  --execute `
  --platform bilibili `
  --connector-instance-id $Instance.id `
  --source-id $CommentsSource.id `
  --account-id $Account.id `
  --mode comments `
  --requested-limit 1 `
  --actor "m2d-local-operator" `
  --confirm M2D_REAL_SMOKE
```

Comments Source：

- 一个主内容；
- `comment_limit <= 5`；
- `include_comments=true`；
- `include_subcomments=false`。

每个平台每天只做必要的 1–3 个低量 Test/Manual Run。

---

## 14. 检查 Run / Checkpoint / RiskEvent

### 14.1 Run

```powershell
Invoke-RestMethod -Headers $Headers `
  -Uri "$Api/connector-runs?platform_account_id=$($Account.id)&page_size=20"
```

单个 Run：

```powershell
Invoke-RestMethod -Headers $Headers -Uri "$Api/connector-runs/<RUN_UUID>"
```

真实 Validation 只能绑定 `SUCCEEDED` 且 trigger type 为 Test/Manual 的 Run。

### 14.2 Checkpoint

```powershell
Invoke-RestMethod -Headers $Headers `
  -Uri "$Api/checkpoints?connector_instance_id=$($Instance.id)&platform_account_id=$($Account.id)&page_size=20"
```

不要为了“让测试通过”手工 reset Checkpoint。Reset 是单独的审计操作。

### 14.3 RiskEvent

```powershell
Invoke-RestMethod -Headers $Headers `
  -Uri "$Api/platform-risk-events?platform=bilibili&platform_account_id=$($Account.id)&resolved=false&page_size=20"
```

只要有未解决 RiskEvent，后续 real smoke 应停止进入人工复核。

---

## 15. 创建真实 Validation record

Fixture / CI / Mock **永远不能**写真实 PASSED。

只有在某个平台已经完成约定的人工低量验证，并确认绑定的 Run：

- status=`SUCCEEDED`；
- trigger type=`TEST` 或 `MANUAL`；
- Run 属于当前平台 Definition；
- `implementation_version` 等于当前 Definition；

才能人工创建 PASSED Validation。

先从 Definition API 读取当前 `implementation_version`，不要手填旧版本。

示例：

```powershell
$ValidationBody = @{
  connector_type = "mediacrawler"
  platform = "bilibili"
  implementation_version = "<CURRENT_IMPLEMENTATION_VERSION_FROM_DEFINITION>"
  environment = "local"
  status = "passed"
  notes = "M2-D dedicated low-value account manual smoke"
  safe_evidence = @{
    run_id = "<REAL_SUCCEEDED_TEST_OR_MANUAL_RUN_UUID>"
  }
  real_smoke_test = $true
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Method Post -Headers $Headers `
  -ContentType "application/json" -Body $ValidationBody `
  -Uri "$Api/connector-validations"
```

服务端会拒绝：

- CI/Mock PASSED；
- `real_smoke_test=false`；
- 无 Run ID；
- 非 SUCCEEDED Run；
- 非 Test/Manual Run；
- Run 与 Definition 不匹配；
- implementation_version 不是当前版本。

不要直接向数据库伪造 Validation。

---

## 16. 停止与清理

真实 Smoke 结束后：

1. 停止后续命令，不自动继续下一模式/下一平台。
2. 保留 Run / Checkpoint / RiskEvent / Validation 的数据库证据。
3. 关闭专用测试 Chrome/Edge 窗口。
4. 确认 9222 不再监听：

```powershell
Test-NetConnection 127.0.0.1 -Port 9222
```

5. API / Web / Scheduler 使用各自终端 `Ctrl+C` 停止。
6. PostgreSQL 可停止但默认保留数据卷：

```powershell
docker compose stop postgres
```

不要在尚需验收证据时执行 `docker compose down -v`。

Browser Profile 位于 `.runtime/` 或本机自定义 root，均不得提交 Git。账号/Profile 的删除应在 M2-D 验收完成后由人工决定，不由脚本自动清理或轮换。

---

## 17. 当前三平台 Readiness 快照

| 平台 | Low-volume Detail | Low-volume Search | Login / Real Smoke | Validation |
|---|---|---|---|---|
| B站 | ENGINEERING READY | ENGINEERING READY | NOT_RUN | NOT_TESTED |
| 知乎 | ENGINEERING READY | ENGINEERING READY | NOT_RUN | NOT_TESTED |
| 微博 | ENGINEERING READY（入口存在，未实跑） | **BLOCKED**：pinned client 无已证实 page-size/count/limit | NOT_RUN | NOT_TESTED |

这张表只描述工程 readiness。**M2 不能因此标记完成。**
