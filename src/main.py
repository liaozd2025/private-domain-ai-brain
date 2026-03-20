"""FastAPI 入口 - 私域运营专家 AI 智脑助手"""
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import settings

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 - 启动初始化 + 关闭清理"""
    # 启动
    logger.info("启动 AI 智脑助手", env=settings.app_env)

    # 确保上传目录存在
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)

    # 初始化数据库连接池
    from src.memory.checkpointer import init_checkpointer
    await init_checkpointer()

    # 初始化嵌入模型 (懒加载，首次请求时初始化)
    logger.info("服务启动完成", port=settings.api_port)

    yield

    # 关闭
    logger.info("正在关闭服务...")
    from src.memory.checkpointer import close_checkpointer
    await close_checkpointer()
    logger.info("服务已关闭")


def create_app() -> FastAPI:
    app = FastAPI(
        title="私域运营专家 AI 智脑",
        description="多角色私域运营 AI 助手 - 支持知识查询、内容生成、数据分析",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    from src.api.openai_compat import router as openai_compat_router
    from src.api.routes import router as api_router
    from src.api.streaming import router as ws_router
    from src.api.webhooks import router as webhook_router

    app.include_router(openai_compat_router, prefix="/v1")
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(ws_router, prefix="/api/v1")
    app.include_router(webhook_router, prefix="/api/v1/webhooks")

    # 全局异常处理
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        logger.error("未处理异常", error=str(exc), path=str(request.url))
        return JSONResponse(
            status_code=500,
            content={
                "error": "内部服务错误",
                "detail": str(exc) if not settings.is_production else "请联系管理员",
            },
        )

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=not settings.is_production,
        log_level=settings.log_level.lower(),
    )
