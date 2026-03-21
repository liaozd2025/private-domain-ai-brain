# Lessons

## 2026-03-20

- 当数据库 schema 变更需要兼容“已有库”时，不能只更新 `scripts/init_db.sql` 或依赖运行时自建 schema；必须同时提供单独的增量迁移 SQL。
- 用户指出交付物缺口后，要把缺口转成回归测试，避免再次出现“功能实现了，但运维落地件缺失”的问题。
- 新增“自动选择器”这类基础能力时，要优先做启发式短路和懒加载依赖，避免每个请求都初始化真实 LLM 客户端，尤其在测试和受限环境里。
- 当同一产品同时提供一方 API 和 OpenAI 兼容层时，涉及“转人工 / 客服 / 会话接管”这类用户可见能力，不能只在一方 API 接线；兼容层也要做等价分流或明确拒绝，并用回归测试锁住。
- 新增与 agent、skill、planning、memory、handoff、tool orchestration 相关的能力时，先核对 Deep Agents 官方是否已有标准实现；默认优先采用官方机制，只有明确不满足需求时才允许自定义，并在计划里写清差距与原因。
- 使用 Deep Agents 官方 `skills=[...]` 时，不能依赖 `FilesystemBackend` 默认配置；必须显式评估 backend 根目录和 `virtual_mode`，否则文件工具可能暴露超出预期的路径范围。
- 当官方 skill 机制无法直接覆盖现有非 deepagents 子智能体时，不要继续维护平行的硬编码 prompt；应复用同一份 `src/skills` 资产作为单一事实源，并用共享 loader 保持行为一致。
- 删除"死代码守卫"（如 `AgentExecutor = None`）时，必须同步更新对应测试中的 `patch` 调用；否则测试会因 `AttributeError: module has no attribute` 而崩溃，即使测试本身并不依赖该守卫路径。
- 在 Python 文件中间位置放置 `import` 语句（模块级别的 asyncio.Lock 初始化）会触发 E402；应在文件顶部统一 import，在模块末尾使用已导入的名称初始化单例锁。
- 外部输入触发的 HTTP 响应不应携带 `str(e)` 异常详情；应在 logger 记录完整错误，对客户端只返回通用提示，防止内部调用栈和数据库路径泄漏。
