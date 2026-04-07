# AgentMatrix Research Core 升级记录

**日期**: 2026-04-07  
**范围**: `agentmatrix-research-core` 首次拆分落地与第二阶段结构重组  
**当前版本基线**: `0911a14` (`refactor: establish research core package structure`)

## 1. 本次升级目的

本次升级的目标是把原先混合在 `agentmatrix-web` 仓库中的研究相关能力，独立沉淀到新的 `agentmatrix-research-core` 仓库中，降低前台网站代码、支付登录逻辑、营销页面对研究系统的语义干扰，提升研究协作效率、Agent 解析准确率和后续模块化演进能力。

## 2. 已完成事项

### 2.1 新仓库建立与远程同步

- 新建 GitHub 仓库：`https://github.com/AgentMatrixLab/agentmatrix-research-core`
- 本地仓库已初始化并连接远程 `origin`
- 主分支统一为 `main`
- 已完成首批迁移提交：`60b8843` `chore: bootstrap research core repository`
- 已完成第二阶段结构重组提交：`0911a14` `refactor: establish research core package structure`

### 2.2 首批迁移进入新仓的模块

#### Document Normalizer / Research Copilot

- 文档标准化 API
- 文档标准化服务
- MinerU 运行时与烟雾测试
- 文档标准化接口测试脚本

#### Data Loader

- `fetch_csi300.py`
- `fetch_csi300_simple.py`
- `check_ak.py`
- `check_ak_recent.py`
- `analyze_fund.py`

#### Strategy Engine

- `etf_agent_engine.py`
- `stock_agent_engine.py`
- `mean_revert_engine.py`
- `grid_master_engine.py`
- `index_sniper_engine.py`
- `etf_rotation_agent.py`
- `reproducibility_agent.py`

#### Test Assets

- `test_docs/` 中的首批测试素材
- `sample_report.pdf`

## 3. 当前目录结构

当前仓库已经建立与新架构图相匹配的基础骨架：

```text
agentmatrix-research-core/
  common/
  deerflow/
    research_copilot/
      document_normalizer/
  research_core/
    data_loader/
    dataset_builder/
    strategy_engine/
    risk_rule_engine/
    backtest_adapter/
    attribution_engine/
  registry/
    factor_registry/
    strategy_registry/
    run_registry/
  contracts/
  data_layer/
    serving_repositories/
  runtime/
  data/
```

## 4. 本次关键重构内容

### 4.1 路径与运行目录解耦

已新增统一路径模块：`common/paths.py`

本次改造的重点是把研究内核从旧网站仓的硬编码路径中解耦出来：

- 不再依赖 `product/website/data`
- 不再把输出默认写回旧的 `agentmatrixlab` 路径
- 文档标准化运行目录从旧的 `backend_runtime` 收敛到新仓自己的 `runtime/document_normalizer`
- 新仓的数据输出统一收敛到 `data/`

### 4.2 Document Normalizer 去前台耦合

`document_normalizer` 已从“网站附属页面能力”开始向“研究内核服务能力”转变：

- 去掉了对 `config.js` 的直接依赖回退逻辑
- 首页响应改为服务状态 JSON，而不是依赖旧前台页面文件
- 静态文件直出逻辑已收缩，避免继续把 research-core 当成 web 容器使用

### 4.3 研究模块重新归位

首批文件已经按职责复制进入新结构：

- DeerFlow 侧：`deerflow/research_copilot/document_normalizer/`
- 研究内核侧：`research_core/data_loader/` 与 `research_core/strategy_engine/`
- 治理层：`registry/`、`contracts/`、`data_layer/` 已建立骨架，等待下一阶段实体化

## 5. 当前仍保留的过渡层

为了避免一次性切断研究员当前工作流，仓库里仍保留了旧目录：

- `backend/`
- `scripts/`

这两个目录目前属于**迁移过渡层**，短期内用于兼容旧路径和降低切换成本。

后续原则：

- 新开发优先放入新结构目录
- 旧目录只做过渡，不再作为长期主结构扩展

## 6. 验证情况

本次重构完成后，已执行语法级校验：

```bash
python -m py_compile common\paths.py deerflow\research_copilot\document_normalizer\api.py deerflow\research_copilot\document_normalizer\service.py deerflow\research_copilot\document_normalizer\mineru_runtime.py deerflow\research_copilot\document_normalizer\smoketest.py deerflow\research_copilot\document_normalizer\api_test.py research_core\data_loader\analyze_fund.py research_core\data_loader\check_ak.py research_core\data_loader\check_ak_recent.py research_core\data_loader\fetch_csi300.py research_core\data_loader\fetch_csi300_simple.py research_core\strategy_engine\etf_agent_engine.py research_core\strategy_engine\etf_rotation_agent.py research_core\strategy_engine\grid_master_engine.py research_core\strategy_engine\index_sniper_engine.py research_core\strategy_engine\mean_revert_engine.py research_core\strategy_engine\reproducibility_agent.py research_core\strategy_engine\stock_agent_engine.py
```

校验结果：通过。

## 7. 对当前线上网站的影响

本次升级**不影响当前网站访问**。

原因：

- 本次所有结构化改造都发生在 `agentmatrix-research-core`
- 当前 `agentmatrix-web` 仓库的站点入口、页面、部署逻辑未被改动
- 现有线上网站继续以当前 web 仓为准运行

## 8. 后续建议动作

### 优先级 P1

- 将新开发任务优先切换到 `research_core/` 与 `deerflow/` 新结构
- 两位研究员后续 PR 以新仓为主，不再继续把研究主逻辑堆回 web 仓
- 明确 `backend/`、`scripts/` 为过渡层

### 优先级 P2

- 抽出 `run_registry` 第一版实体结构
- 抽出 `contracts` 中的 run / artifact / dataset 定义
- 将 `etf_agent_engine` 中的输出契约与运行元数据继续解耦

### 优先级 P3

- 逐步清理新仓中的旧路径兼容副本
- 评估哪些历史数据产物应迁到对象存储或数据库，而不是长期留在 Git
- 在稳定后再考虑从 `agentmatrix-web` 中移除重复 research 文件

## 9. 团队协作建议

- `agentmatrix-web` 继续承接线上网站和前台产品迭代
- `agentmatrix-research-core` 继续承接研究编排、数据处理、策略引擎和研究服务能力
- 与研究内核直接相关的新增代码，默认进入新仓
- 对外页面、登录、支付、展示、运营后台默认留在 web 仓

## 10. 给同事的快速同步结论

一句话总结：

> `agentmatrix-research-core` 已经从“新建空仓”升级成“可开始承接研究开发的独立仓库”，并完成了首批研究模块迁移与结构骨架搭建；当前网站不受影响，后续研究开发应优先在新仓推进。
