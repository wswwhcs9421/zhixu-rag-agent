# 配置与使用手册

面向共享知识库的中文网页应用：DeepSeek 负责工具调用和回答，bge-m3 负责生成文档与问题的 1024 维稠密向量。支持管理员 / 只读成员、文档与知识片段增删改、解析与向量统计、混合检索、引用追溯和个人会话。

## 1. 快速启动（Windows / PowerShell）

需要 Python 3.11 或 3.12。当前开发环境使用 Python 3.12。所有命令在项目根目录执行，以下路径以你自己的下载位置为准。

```powershell
cd zhixu-rag-agent  # 进入下载或克隆后的项目根目录
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

打开 <http://127.0.0.1:8000>。首次创建数据库时，系统自动生成随机管理员密码，写入 `data/bootstrap-admin.txt`。登录后，通过左下角的账号入口修改密码；修改后初始凭据文件自动移除。也可以在首次启动前通过 `.env` 的 `RAG_ADMIN_PASSWORD` 指定至少 12 个字符的密码。

`start.ps1` 会创建虚拟环境、安装基础依赖并在不存在时从 `.env.example` 复制 `.env`。手动启动方式：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env  # 仅首次执行；不要覆盖已有配置
.\.venv\Scripts\python.exe run.py
```

修改 `.env` 后需要重启服务。服务默认只监听 `127.0.0.1`。

### Linux / macOS 手动启动

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-local-model.txt
cp .env.example .env  # 仅首次执行，不要覆盖已有配置
# 编辑 .env，填写自己的 API Key，核对模型 ID
.venv/bin/python run.py
```

使用远程 Embedding API 时改装 `requirements.txt`，并配置 `BGE_MODE=api`。Linux / macOS 的后续 Python 命令使用 `.venv/bin/python` 替换 Windows 的 `.venv\Scripts\python.exe`。本次本地验收环境是 Windows，跨系统测试由 GitHub Actions 在推送后执行。

## 2. 配置 DeepSeek V4

编辑 `.env`：

```dotenv
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=填写你自己的密钥
DEEPSEEK_MODEL=deepseek-flash
```

模型名称、可用性和接口地址以你实际使用的服务商为准。本项目不假定 `deepseek-v4` 一定是有效 ID，也不会静默切换到其他模型。API 需要兼容 `/chat/completions`，并支持函数工具调用（包括 `tool_choice`）。第三方服务商的 URL 可带 `/v1`；程序会直接在配置地址后追加 `/chat/completions`。

本项目配置示例使用 `deepseek-flash`，这是开发时使用的官方 API 模型 ID；模型命名和可用性可能调整，请以当前账号及服务商的模型列表为准。`https://platform.deepseek.com/api_keys` 是密钥管理页面，不能用作 API Base URL。

官方 V4 Flash 默认开启思考模式，而该模式不支持本应用首次检索所用的 `tool_choice=required`。本应用在调用官方 `api.deepseek.com` 时显式使用非思考模式，保证先执行知识检索；第三方地址不会自动附加此专有参数。参考[官方工具调用文档](https://api-docs.deepseek.com/guides/tool_calls)和[模型说明](https://api-docs.deepseek.com/)。

密钥只在服务端读取，不发送给网页。未配置模型或调用失败时，页面显示真实错误，不生成占位答案。

**使用云端生成模型时，问题、相关会话文本和检索出的文档片段会发送到配置的服务商。** 若资料要求完全留在内网，可将地址改为内网提供的兼容模型服务，并使用该服务实际支持的模型 ID。

## 3. 配置 bge-m3

### 方式 A：本机运行

安装本地推理依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-local-model.txt
```

`.env` 使用：

```dotenv
BGE_MODE=local
BGE_MODEL=BAAI/bge-m3
BGE_DEVICE=cpu
```

首次在管理页点击「建立向量」会从 Hugging Face 下载模型到 `data/models/`；需要联网和数 GB 磁盘空间。模型下载或 CPU 推理可能较慢，状态会保持处理中，失败会显示具体操作建议。这里只使用 bge-m3 的稠密向量能力，不包含其稀疏向量或多向量检索模式。

若首次下载超时，可以先运行项目提供的下载脚本：

```powershell
.\.venv\Scripts\python.exe scripts\download_bge_m3.py
```

脚本固定官方模型版本，从官方接口读取文件哈希；大权重通过 `hf-mirror.com` 下载，并校验与官方 SHA256 一致，支持中断后重新运行。约需下载 2.3 GB，下载和组装时建议预留至少 5 GB 空间。完成后，将 `.env` 的 `BGE_MODEL` 设为本地模型目录，例如：

```dotenv
BGE_MODE=local
BGE_MODEL=./data/models/bge-m3
BGE_DEVICE=cpu
```

重启服务后，从本地文件加载模型，不再通过 Hugging Face 查询或下载。不要删除 `data/models/bge-m3`：这是运行所需模型文件。更改 `BGE_MODEL` 后应重新建立文档向量。

Windows + AMD 显卡环境默认选择 CPU。本初版没有实现 AMD GPU 加速，避免把 CUDA 配置误用于 AMD 显卡。

### 方式 B：调用已有 Embedding API

```dotenv
BGE_MODE=api
BGE_MODEL=填写该服务实际注册的bge-m3模型ID
BGE_BASE_URL=http://127.0.0.1:8001/v1
BGE_API_KEY=服务需要认证时填写
```

API 应支持 `POST /embeddings`，接收 `model` 和 `input: string[]`，返回带 `index` 和 `embedding` 的 `data` 数组，每个向量 1024 维。程序会验证维度、行数、索引和非零有限数值，并统一归一化。

切换模型、运行模式或 Embedding API 地址后，原配置生成的向量不会混入新检索，管理页会提示重新建立向量。

## 4. 管理员的第一次使用

1. 登录后在「成员与权限」创建只读成员或其他管理员。初版没有开放注册。
2. 在「文档知识库」上传 PDF、TXT、MD 或 Markdown，支持多文件选择，默认单个文件不超过 20 MB。
3. 等待解析完成。查看主题、片段数，点击「查看片段」检查内容。主题优先取 Markdown 一级标题，否则用文件名；管理员可以修改主题。这里没有自动生成 LLM 主题摘要。
4. 点击「建立向量」。完成后状态为「可检索」，向量数应与片段数一致。解析和向量化是两个独立动作，不会在上传时悄悄下载大模型。
5. 先用「检索测试」确认正确原文能被召回；该功能只调用 bge-m3，不调用 DeepSeek。
6. 在「知识问答」提问，可选择全部共享文档或单个文档。正文来源按首次引用顺序连续编号为 `[S1]`、`[S2]`；下方标注文件名与真实片段序号，例如 `S1 · D10_信息系统.md · 片段 7`。点击引用查看原文快照；展开检索过程可看见工具名称、查询、召回数量和耗时。

支持文本型 PDF；扫描 PDF 需要先做 OCR。加密 PDF、空文档和超出限制的文件会明确报错。暂不支持 Word、Excel、图片和网页抓取。

### 文档切分规则

按文档中的实际结构逐块识别，同一份文档可以混用多种规则，无需先为每个行业修改提示词。切分由代码执行，不调用 LLM。

| 原文结构 | 处理方式 |
| --- | --- |
| 第几章、节、条 | 短条款完整保留；条内小标题、条件和例外随正文保留 |
| 一、（一）、1.0、1.1、2.A 等层级编号 | 根据层级划分；纯文本数字编号需同组编号佐证，减少误认日期、金额、版本号 |
| Markdown、加粗、Setext 标题 | 按标题层级划分；识别部分常见纯文本栏目，如适用范围、职责、审批流程 |
| 问答、Q/A、问/答、独立问题标题 | 问题与回答一起保留；长回答细分时重复问题上下文 |
| 操作流程、步骤和条件清单 | 短流程/清单整体保留；过长时优先在完整步骤/条目之间切分，延续条件引导语 |
| Markdown 表格、制表符文本表格 | 过长时按行分组并重复表头、简短备注；超长单行降级为带行标识和列名的单元格片段 |
| 代码围栏 | 内部内容不识别为章节；长代码按行拆分并保留围栏 |
| 普通叙述 | 优先段落、句子，最后才按长度兜底 |

`RAG_CHUNK_SIZE`（默认 1000 字符）是长度上限，按字符数而非 token 数计算；`RAG_CHUNK_OVERLAP`（默认 120 字符）是同一长段内部的最大重叠范围，结构块之间不机械重叠。续片段会在空间允许时复用原文标题、问题或清单引导语，因此长度预算会扣除这部分上下文。

知识库列表显示文档序号；筛选列表保留完整列表中的序号。该序号随列表排序变化，不等同于文件名中的 `D01` 等业务编号。

章节字段保存“制度名称 / 章节 / 小节”等路径。PDF 连续内容可以跨页，`page` 记录起始页。规则采用文本结构判断，不包含扫描件 OCR、合并单元格和图片流程图识别、复杂 PDF 表格重建或 LLM 语义判断；异常长的表头/备注无法安全按行分组时保留文本并降级切分，需要人工检查。

公开企业案例、来源和离线回归材料位于 `evaluation/chunking_examples/`，参见其中的 `README.md`。这些研究资料未自动导入知识库，不能与实际公司制度混用。

重新解析会替换片段并使旧向量失效，之后必须重新建立向量；管理员手动改过的片段应先保存，再决定是否重新解析。

## 5. 权限与数据操作

| 操作 | 管理员 | 只读成员 |
| --- | --- | --- |
| 浏览共享文档主题与片段、查看统计 | 可以 | 可以 |
| 检索测试、知识问答 | 可以 | 可以 |
| 查看自己的会话 | 可以 | 可以 |
| 查看其他成员的会话 | 不可以 | 不可以 |
| 上传 / 删除 / 重新解析文档，修改主题 | 可以 | 不可以 |
| 增加 / 修改 / 删除知识片段，建立向量 | 可以 | 不可以 |
| 创建 / 停用 / 删除成员、重置密码、分配角色 | 可以 | 不可以 |
| 查看操作记录 | 可以 | 不可以 |
| 修改自己的密码 | 可以 | 可以 |

所有写操作在后端校验身份和角色，隐藏前端按钮只是呈现方式。权限修改、账号停用或密码重置会撤销该账号的登录状态。不能通过成员管理删除自己或修改自己的角色，必须保留可用管理员。

管理员通过应用接口修改 SQLite 中的知识内容，不提供网页任意 SQL 执行功能。

**数据一致性：**

- 编辑片段后，其旧向量立即删除；重新向量化前该片段不会作为向量候选参与检索。
- 新增片段后，现有片段向量可继续使用，新增内容需重新建立向量。
- 删除片段会同时删除对应向量；删除文档会级联删除片段、向量和原始上传文件。
- 重新解析覆盖手工修改的片段并清空原有向量，网页会先要求确认。
- 历史回答保留回答当时的引用快照。删除知识库中的文档不会改写历史对话；删除成员会删除其个人会话。
- 单个文档处理期间不能修改或删除，避免读写竞争；服务重启后的中断任务可以手动重试。

初版为**一个共享知识库**，没有实现部门、文档级 ACL 或多租户隔离。

## 6. RAG Agent 的执行方式

```text
提问 + 当前用户自己的历史消息
  → DeepSeek 选择工具和检索问题
  → search_knowledge：bge-m3 稠密检索 + 中文双字词 / 英文词 BM25 + RRF 排名融合
  → 需要时改写问题再检索，或 read_document_section 读取相邻片段
  → DeepSeek 根据本轮证据生成带来源编号的回答
  → 后端校验来源编号存在，保存回答、快照和工具调用记录
```

默认最多 3 轮工具选择、共 6 次工具调用，最后一次要求模型给出答案，总问答超时 180 秒。重复查询会被拦截。文档文本被当作证据，不应被当作系统指令。

这里的 RRF 是基于名次的融合，不是独立的学习型 Reranker。引用校验保证编号来自本次真实检索，**不等于逐条验证语义支持关系或保证事实正确**，重要结论仍需核对原文。

## 7. 数据位置与维护

```text
rag_agent/                 Python 后端、权限、解析、检索和 Agent
web/                       无构建步骤的 HTML / CSS / JavaScript 网页
tests/                     后端权限与数据一致性测试
.env                       本机配置与 API 密钥（忽略提交）
data/rag.sqlite3           用户、会话、文档、片段、向量及操作记录
data/uploads/              原始上传文件
data/models/               本地模型下载目录
data/bootstrap-admin.txt   首次生成的管理员凭据
```

`data/` 是业务数据与模型存储，不应当作缓存清理。备份时停止服务，复制整个 `data/` 及安全保存的 `.env`；SQLite WAL 模式下不要只复制运行中的单个主数据库文件。程序不依赖外部向量数据库或 Docker。

初版把向量保存在 SQLite 并用 NumPy 做内存余弦检索，适合验证小规模知识库。数据量增大时，应更换 Qdrant / pgvector 等检索后端，而不是把该实现直接用于大规模并发。

启动服务：`.venv\Scripts\python.exe run.py`。在前台运行时按 `Ctrl+C` 停止；若使用进程管理器，应由对应进程管理器停止。

## 8. 验证

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
node --check web/app.js
node --test tests/chat-format.test.cjs
```

后端测试使用**明确隔离的测试模型替身**，覆盖权限绕过、文档 / 向量生命周期、会话隔离、来源快照、错误模型配置、过期向量和引用编号校验。替身不会进入真实应用，也不代表真实 DeepSeek / bge-m3 的效果验收。

可选浏览器验收（需要 Microsoft Edge）：

```powershell
.\.venv\Scripts\python.exe -m pip install "playwright>=1.52,<2"
.\.venv\Scripts\python.exe -m tests.browser_smoke
```

浏览器验收使用独立的临时数据库，覆盖登录、上传、解析、编辑片段、成员创建、只读权限、缺少模型时的真实错误，以及桌面 / 手机布局；不会向正式知识库添加示例数据。截图输出到 `test-results/`。

真实模型验收需要完成模型配置后，上传你自己的文档，用已知答案的问题检查召回、引用准确性、资料不足时的行为和实际响应时间。
