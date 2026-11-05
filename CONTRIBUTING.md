# 开发与贡献

## 本地开发

使用 Python 3.11 或 3.12。在项目根目录建立虚拟环境并安装 `requirements-dev.txt`，然后从 `.env.example` 创建本机 `.env`。应用没有前端打包步骤，修改 `web/` 文件后刷新浏览器；修改后端后重启 `run.py`。

业务代码位于 `rag_agent/`，页面位于 `web/`。解析规则在 `documents.py`，检索在 `knowledge.py`，工具与回答约束在 `agent.py`，引用编号在 `citations.py`。不要用前端按钮隐藏代替后端权限检查。

## 提交前检查

```powershell
python -m pytest
python -m evaluation.enterprise_v1.evaluate validate
node --check web/app.js
node --check web/chat-format.js
node --test tests/chat-format.test.cjs
```

以上 `python` 应指向已安装开发依赖的虚拟环境；Windows 可明确写成 `.\.venv\Scripts\python.exe`。Node.js 建议使用 22 LTS，前端测试使用内置测试运行器，无需 npm 安装。

测试使用临时数据库与明确的模型替身，不下载 bge-m3、不请求 DeepSeek、不读取正式数据库。浏览器验收是可选步骤，需要安装 Playwright 和 Microsoft Edge，命令为 `python -m tests.browser_smoke`。

改动解析或检索时，保留来源、条件、例外和章节信息，并核对固定测试集。修改源码测试全部通过后，真实检索效果仍需使用实际模型单独验收，不能用单元测试数量代替回答正确率。

## 提交内容

提交必要源码、测试和使用说明。不要提交 `.env`、账号密码、会话、生产数据库、模型权重、私人资料、生成的评测结果或调试日志。新配置项同步更新 `.env.example` 和使用手册。修改公开测试材料时保留来源和版本记录，避免误当成本公司的制度。

Pull Request 请说明解决的问题、实际行为变化及验证命令。提交 Issue 时包含脱敏复现步骤、Python 版本与操作系统；不要粘贴 API Key 或完整敏感文档。
