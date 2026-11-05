# 常见问题与故障排查

| 现象 | 排查与处理 |
| --- | --- |
| 首次启动不知道密码 | 默认用户名为 `admin`；查看本机 `data/bootstrap-admin.txt`。若已设置 `RAG_ADMIN_PASSWORD`，使用首次建库时的配置值 |
| 修改 `.env` 后密码没有变 | 管理员环境变量只在首次创建数据库时生效。已有账号通过网页账号菜单或另一管理员重置，不要删除数据库尝试重置 |
| 用户名或密码错误 / 已停用 | 确认当前运行目录和数据目录是否正确、账号是否停用；发布目录是全新实例，不继承原项目账号 |
| bge-m3 运行库未安装 | 用启动服务的同一个 Python 执行 `-m pip install -r requirements-local-model.txt` |
| bge-m3 加载失败 | 检查模型下载、可用磁盘和内存；可运行下载脚本后配置 `BGE_MODEL=./data/models/bge-m3`，使用 `BGE_DEVICE=cpu` 后重启 |
| 文档已解析但无法回答 | 解析与向量化分开执行，需要点击建立向量，等待状态变为可检索；再确认 DeepSeek 已配置 |
| 向量数小于片段数 | 部分内容被编辑、新增，或 Embedding 配置已变更；检查片段后重新建立向量 |
| DeepSeek 返回 401 / 402 / 404 | 检查 API Key、额度、API Base URL 和服务商实际模型 ID；不要把密钥管理网页填作接口地址 |
| 工具调用失败 | 确认模型支持函数调用和 `tool_choice`；兼容接口不一定完整支持工具协议 |
| 扫描 PDF 没有正文 | 当前没有 OCR；先在其他工具中进行 OCR，再上传有文本层的 PDF 或纯文本 |
| 端口 8000 已占用 | 检查是否已有实例。可在 `.env` 改成 `RAG_PORT=8002` 后重启，访问对应端口；不要停止归属不明的进程 |
| 外网访问不到 | 默认仅监听本机，这是当前启动配置。部署到其他主机时需明确配置监听、HTTPS 和访问管理 |
| 页面资源看起来没更新 | 先刷新页面，必要时使用 `Ctrl+F5`；后端改动需要重启服务 |

## Windows 常用命令

在项目根目录执行：

```powershell
# 查看端口占用，仅盘点，不停止进程
Get-NetTCPConnection -LocalPort 8000 -State Listen

# 重新启动（先在原服务终端按 Ctrl+C 停止）
.\.venv\Scripts\python.exe run.py

# 准备本地模型
.\.venv\Scripts\python.exe scripts/download_bge_m3.py
```

默认数据在项目根目录的 `data/`。原始上传文件、SQLite 与模型均是运行数据，不应当作缓存删除。备份方法见[使用手册](usage.md#7-数据位置与维护)。
