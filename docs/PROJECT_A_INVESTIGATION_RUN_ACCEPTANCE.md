# 调查提交持久化与刷新恢复：脱敏验收摘要

记录日期：2026-10-22。基线 `d908fc7` 之后的改动，尚未提交。本摘要不包含账号、凭据、Token、完整报告或原始请求日志。

| 能力 | 验证条件与结果 | 范围边界 |
| --- | --- | --- |
| 提交占位、幂等、终态、授权读取 | 用户在普通 PowerShell 运行隔离 PostgreSQL 专项：单方法 1 项、1.796 秒、OK；完整专项 6 项、11.847 秒、OK。测试使用 `ragforge_day6_test` 的临时 schema，包含同键并发、异参冲突、独立会话读取、权限撤销、受控 Provider 的 Graph 报告保存、失败/截止/未保存结果及清理检查。 | 结果由用户提供；PowerShell 最终数值退出码未单独存档。不是业务数据库迁移或真实聊天模型验收。 |
| 完成后刷新恢复 | 第一轮本地受控页面：用户确认刷新后恢复已保存报告；状态接口返回 `provider_calls=2`、`run_count=1`、`saved_reports=1`、`statuses=["succeeded"]`。 | 真实 JWT/API＋隔离 PG，聊天决策由受控 Provider 替代；第一轮未在运行中刷新。 |
| 运行中刷新恢复 | 第二轮独立受控页面：用户确认运行中刷新后自动找回“运行中”；该轮状态接口同样返回 `provider_calls=2`、`run_count=1`、`saved_reports=1`、`statuses=["succeeded"]`。 | 同样不是实时聊天模型验收；两轮各自计数，不能合并为稳定率。 |

代码与复现入口：[迁移](../backend/alembic/versions/0009_investigation_runs.py)、[Service](../backend/app/services/investigation_run_service.py)、[认证 API](../backend/app/api/v1/endpoints/investigations.py)、[页面](<../frontend/src/app/(dashboard)/investigations/page.tsx>)、[隔离 PG 专项](../backend/tests/commerce/test_investigation_runs_postgres.py)、[受控 Provider](../scripts/investigation_refresh_controlled.py)、[启动脚本](../scripts/start_investigation_allocation_demo.ps1)。原始账号状态与运行日志仅本地保留，未纳入仓库。

受控案件是启动时确认不存在的合成案件，因此报告为已校验的 `not_found`；它只验证提交记录、报告持久化、去重和页面刷新恢复，不验证库存分配归因。现有执行仍限单 API worker；服务重启把遗留 `running` 记为 `interrupted`，不提供 Graph 断点续跑。真实模型调查沿用此前独立证据，不能把本次受控验收计为新的真实模型或完整业务页面 E2E。
