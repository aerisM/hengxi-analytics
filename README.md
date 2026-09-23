# 衡析 · 企业经营分析工作台

衡析是面向企业经营数据查询与分析场景的智能问数与分析应用。业务人员可以用自然语言查询示例数据库，查看表格、SQL、结果说明，并基于已有结果生成图表或分析报告。

> 当前版本使用仓库中的合成演示数据和固定演示账号，尚未部署为生产系统。

## 能做什么

- **自然语言查数**：将销售、客户等经营问题路由到数据库查询流程，生成并执行只读 SQL。
- **字段级 Schema 检索**：结合 BM25、向量召回、RRF 融合与重排序，为 SQL 生成提供相关表、字段和关联关系。
- **必要时澄清口径**：当排名指标等关键信息不明确时暂停查询，用户补充后继续；明确的问题可直接执行。
- **安全与失败处理**：执行前检查单语句、只读、`SELECT *`、表名及访问范围；对可修正的 SQL 语法或引用错误最多尝试一次模型修正，不对权限或数据源故障盲目重试。
- **结果复用**：查看、保存、导出查询结果，并基于已有结果进行问答、图表展示和报告生成。

查询主链路：

```text
用户问题 → 请求预处理与路由 → Schema 检索/建图 → 必要时澄清
        → SQL 生成 → MCP 数据库工具 → 安全校验与执行
        → 可修正错误的一次重试 → 表格与结果说明
```

后端使用 Python、FastAPI、LangGraph、DuckDB、SQLGlot 和进程内 MCP 工具；前端使用 Vue 3、TypeScript 和 Vite。模型接口默认配置为阿里云百炼兼容接口，并使用 Qwen、`text-embedding-v4` 与 `qwen3-rerank`。代码中的 `askdata` 标识保留为内部模块、API 和数据集名称；“衡析”是当前界面品牌。

## 快速开始

环境：Python 3.11、Node.js 20.19+、npm，以及可用的聊天、Embedding 和 Rerank 模型额度。以下命令均从仓库根目录开始。

1. 安装后端依赖并创建配置。macOS/Linux：

   ```bash
   cd backend
   python3.11 -m venv .venv
   ./.venv/bin/python -m pip install -r requirements.txt
   cp .env.example .env
   ```

   Windows PowerShell：

   ```powershell
   cd backend
   py -3.11 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

2. 在 `backend/.env` 中填入自己的 `LLM_API_KEY`，并检查模型名及接口地址。中国站百炼的默认地址已经写在 `.env.example` 中；不同账号可用模型可能不同，请以自己的控制台为准。**不要提交 `.env` 或将 API Key 填入前端。**

3. 在一个终端启动后端：

   ```bash
   cd backend
   ./.venv/bin/python run.py
   ```

   Windows 使用 `.\.venv\Scripts\python.exe run.py`。

4. 在另一个终端启动前端：

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

5. 打开 `http://127.0.0.1:5173`。后端 API 文档位于 `http://127.0.0.1:8000/docs`，健康检查位于 `http://127.0.0.1:8000/api/health`。

首次查询可能需要建立 Schema 向量索引，会调用 Embedding 接口并产生一定费用与等待时间。之后若 Schema 和模型配置未变化，会复用本地索引。

## 演示账号与问题

| 账号 | 密码 | 可访问的演示数据 |
| --- | --- | --- |
| `admin` | `admin123` | 全部演示数据 |
| `sales` | `sales123` | `ecommerce_ops` 电商运营数据 |
| `mock` | `mock123` | `askdata_mock` 基础销售数据 |

这些账号是进程内的固定演示账号，不具备生产级认证能力。服务重启后登录令牌会失效。

可先使用基础销售数据提问：

- `按地区统计2026年8月销售额`
- `按客户等级统计2026年8月销售额`
- `对比2026年8月各地区销售额与销售目标`

查询后可查看 SQL、保存结果、导出 Excel。右上角的“高级分析设置”是可选功能，可手动指定查询字段或加入已保存的结果表；普通查询无需预先设置。

## 验证

后端测试（`pytest` 为开发测试依赖）：

```bash
cd backend
./.venv/bin/python -m pip install pytest
./.venv/bin/python -m pytest -q
```

Windows 将上面的 Python 路径替换为 `.\.venv\Scripts\python.exe`。前端构建检查：

```bash
cd frontend
npm run build
```

测试覆盖了 SQL 权限和只读校验、字段/表引用错误后的有界重试、澄清后续跑、Schema 检索与示例数据查询。另曾在合成销售数据上进行一次受控真实 Qwen 验证：人为注入不存在的金额字段后，模型根据 DuckDB 错误改用正确字段并执行成功。**这只是单个案例，不代表总体 SQL 修复率。**

## 当前边界

- 数据集为合成演示数据；未验证真实企业数据接入、并发负载或生产部署。
- 排名等问题的业务语义仍可能与生成的 SQL 不完全一致，重要结论应检查 SQL、时间范围和指标定义。
- SQL 自动修正只针对部分可修正的执行错误，最多重试一次；安全规则拒绝、权限不足和数据源故障不会通过改写 SQL 绕过。
- 检索召回和查询正确性尚无针对当前版本的系统性公开评测，不应将历史版本的指标当作当前版本结果。

## 目录

```text
backend/app/         FastAPI、工作流、Schema 检索、SQL 执行与 MCP 工具
backend/data/        合成演示数据
backend/tests/       后端回归测试
frontend/src/        Vue 页面、图表与结果组件
```
