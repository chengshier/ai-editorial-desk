# M5-D Visual Batch A QA

> 验收日期：2026-08-12。范围为 Design Foundation、Overview、Daily Candidates、Event Workbench 与 Operations Console 的视觉基础；不扩展到 Functional Batch B。

## 已验证

| 项目 | 证据 | 结果 |
| --- | --- | --- |
| 统一 Design Tokens | `apps/web/src/visual-fidelity.css` | Sidebar 236px、Topbar 72px、内容最大宽度 1760px、正文 14px、控件 40px、按钮 38px。 |
| 宽屏约束 | `.page-inner` 和 Workbench/Candidates Grid | 内容不会在 1920/2048 宽屏无限拉伸；Workbench 为 70/30，Candidates 为 68/32。 |
| 响应式 | 浏览器只读检查 | 1440px：236px Sidebar；1280px：220px Sidebar、Candidates Rail 保持 sticky；1024px：204px Sidebar、Candidates/Workbench Rail 下移。 |
| Operations 密度 | `visual-fidelity.css` 的 field width 与 SchemaForm 规则 | Form 控件 40px，语义字段宽度与表格 48–52px 行密度已统一。 |
| 空态与错误态 | Overview 只读浏览器截图 | 未授权时显示统一错误 Banner 与 Retry，不使用伪数据填充页面。 |

## 明确 Deferred / Not Tested

| 项目 | 原因 | 结论 |
| --- | --- | --- |
| Overview 填充态 Hero / Stat Strip / Priority Queue | 浏览器会话没有管理员 Token；不将本地 Token 写入浏览器 sessionStorage。 | DEFERRED |
| Candidates Ranking List / Sticky Decision Rail 填充态 | 当前无法在浏览器会话读取真实 Candidate 数据；禁止生产代码假数据。 | DEFERRED |
| Event Workbench Header / Tabs / Main + Right Rail 填充态 | 当前浏览器会话无凭据，不能打开真实 Event。 | DEFERRED |
| Connector 动态 SchemaForm 完整视觉 | Connector Definition 未在浏览器会话加载。 | DEFERRED |

## 结论

静态样式、宽度策略与 1440/1280/1024 响应式基线已完成；真实数据视觉验收没有被伪造为通过。恢复浏览器的只读 Admin 凭据后，应在不执行写操作的前提下补采 Overview、Candidates、Workbench 与 Connector Instance 的填充态截图，再作最终视觉确认。
