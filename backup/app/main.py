from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
from dotenv import load_dotenv

from app.core.config import settings
from app.core.cache import redis_client

# 환경 변수 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# FastAPI 애플리케이션 생성
app = FastAPI(
    title="카지노 플랫폼 API",
    description="Memurai(Windows용 Redis 호환 캐시) 연결 테스트 API",
    version="0.1.0",
)

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 실행되는 이벤트 핸들러"""
    logger.info("애플리케이션 시작 중...")
    
    # Memurai/Redis 연결 확인
    if redis_client.is_connected():
        logger.info("Memurai/Redis 연결 성공")
    else:
        logger.warning("Memurai/Redis 연결 실패")
    
    logger.info("애플리케이션이 성공적으로 시작되었습니다.")

@app.get("/api/health")
async def health_check():
    """API 상태 확인 엔드포인트"""
    cache_status = "연결됨" if redis_client.is_connected() else "연결 안됨"
    
    return {
        "status": "정상",
        "version": app.version,
        "environment": os.getenv("ENVIRONMENT", "개발"),
        "cache_status": cache_status
    }

@app.get("/api/cache/info")
async def cache_info():
    """캐시 정보 확인 엔드포인트"""
    return redis_client.get_client_info()

@app.post("/api/cache/set")
async def set_cache_item(key: str, value: str, ttl: int = None):
    """캐시에 아이템 저장"""
    success = redis_client.set(key, value, ttl)
    return {
        "success": success,
        "key": key,
        "operation": "set"
    }

@app.get("/api/cache/get/{key}")
async def get_cache_item(key: str):
    """캐시에서 아이템 조회"""
    value = redis_client.get(key)
    return {
        "success": value is not None,
        "key": key,
        "value": value,
        "operation": "get"
    }

@app.delete("/api/cache/delete/{key}")
async def delete_cache_item(key: str):
    """캐시에서 아이템 삭제"""
    success = redis_client.delete(key)
    return {
        "success": success,
        "key": key,
        "operation": "delete"
    }

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0", 
        port=8000,
        reload=True,
    ) 