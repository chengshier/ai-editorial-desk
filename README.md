# AI Editorial Desk

AI 编辑部系统：面向短视频创作者的多平台事件发现、资料整理、编辑判断与内容生产辅助系统。

项目当前处于 **M1：基础设施与项目骨架** 阶段。完整产品和分阶段路线见 [`docs/START_HERE.md`](docs/START_HERE.md)。

## 当前骨架

```text
apps/                          应用入口：API、Web、Worker、Scheduler
packages/connectors/           统一连接器 SDK 与 MediaCrawler Adapter
packages/risk_guard/           平台账号风险状态和错误分类
docker/postgres/               PostgreSQL 初始化脚本
docs/                          PRD、技术文档和综合实施规划
third_party/                   MediaCrawler 等第三方模块边界
```

## 本地启动

要求：Python 3.11 或 3.12、Docker Desktop。

```bash
# 1. 创建本地配置
cp .env.example .env

# 2. 启动 PostgreSQL + pgvector
docker compose up -d postgres

# 3. 安装项目与开发依赖
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

# 4. 启动 API
uvicorn apps.api.main:app --reload

# 5. 运行测试
pytest
```

健康检查：`GET http://127.0.0.1:8000/health`

## MediaCrawler

当前提交只建立集成边界，尚未复制上游源码。后续将其引入 `third_party/MediaCrawler`，并由 `packages/connectors/mediacrawler_adapter` 通过子进程调用。详见 [`third_party/README.md`](third_party/README.md)。

## 安全原则

- 不提交真实 API Key、Cookie、Token 或密码；
- 国内平台采集使用独立测试账号；
- 验证码、权限拒绝、403/406/429、账号受限等风险信号不得进入普通重试；
- 不实现验证码破解、指纹伪造、封禁后自动换号或其他绕过平台限制的机制。
