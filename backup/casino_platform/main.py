import logging
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import redis.asyncio as aioredis

from casino_platform.api import auth, users, games, wallet
from casino_platform.config import settings
from casino_platform.database import init_db
from casino_platform.middleware import LocalizationMiddleware, RateLimitMiddleware

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="카지노 플랫폼 API",
    description="온라인 카지노 게임 플랫폼을 위한 API",
    version="0.1.0",
)

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 전역 예외 처리기
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"message": "서버 내부 오류가 발생했습니다"},
    )

# API 라우터 등록
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(games.router)
app.include_router(wallet.router)

@app.on_event("startup")
async def startup_event():
    logger.info("애플리케이션 시작")
    
    # Redis 연결 설정
    app.state.redis = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True
    )
    logger.info(f"Redis 연결 설정: {settings.REDIS_URL}")
    
    # 데이터베이스 초기화
    await init_db()
    
    # 캐시 통계 로깅 (옵션)
    try:
        info = await app.state.redis.info()
        logger.info(f"Redis 서버 정보: 버전={info.get('redis_version', 'unknown')}, 메모리={info.get('used_memory_human', 'unknown')}")
    except Exception as e:
        logger.warning(f"Redis 정보 조회 실패: {str(e)}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("애플리케이션 종료")
    
    # Redis 연결 해제
    if hasattr(app.state, "redis"):
        await app.state.redis.close()
        logger.info("Redis 연결 해제됨")

# 국제화 미들웨어 설정
app.add_middleware(
    LocalizationMiddleware,
    default_language="ko",
    default_timezone="Asia/Seoul",
    translations_dir="translations"
)

# 비율 제한 미들웨어 설정 (API 남용 방지)
@app.on_event("startup")
async def setup_rate_limiter():
    # 기본 설정: 분당 100개 요청, 금융 API는 더 엄격하게 제한
    app.add_middleware(
        RateLimitMiddleware,
        redis_client=app.state.redis,
        rate_limit_seconds=60,
        max_requests=100,
        whitelist_ips=settings.RATE_LIMIT_WHITELIST_IPS,
        block_on_exceed=settings.BLOCK_ON_RATE_LIMIT_EXCEED
    )
    logger.info("비율 제한 미들웨어 설정됨")

@app.get("/", tags=["상태"])
async def root():
    return {"message": "카지노 플랫폼 API가 실행 중입니다"}

@app.get("/health", tags=["상태"])
async def health_check():
    # Redis 연결 확인
    redis_status = "ok"
    try:
        await app.state.redis.ping()
    except Exception:
        redis_status = "error"
    
    # DB 연결 확인 (구현 필요)
    db_status = "ok"
    
    return {
        "status": "ok" if redis_status == "ok" and db_status == "ok" else "error",
        "services": {
            "api": "ok",
            "redis": redis_status,
            "database": db_status
        }
    }

if __name__ == "__main__":
    uvicorn.run("casino_platform.main:app", host="0.0.0.0", port=8000, reload=True) 