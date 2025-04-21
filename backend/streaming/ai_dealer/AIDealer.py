import os
import json
import logging
import boto3
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from botocore.exceptions import ClientError

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AIDealer:
    """
    AI 딜러 관리 클래스
    AWS MediaLive로 스트리밍을 처리하고 G4dn 인스턴스에서 생성된 AI 딜러 비주얼 활용
    """
    
    def __init__(self, 
                dealer_id: str, 
                game_type: str,
                media_live_channel_id: Optional[str] = None,
                fps: int = 30,
                resolution: Tuple[int, int] = (1280, 720)):
        """
        AI 딜러 초기화
        
        Args:
            dealer_id: AI 딜러 고유 ID
            game_type: 게임 유형 (blackjack, roulette, baccarat 등)
            media_live_channel_id: AWS MediaLive 채널 ID (없으면 새로 생성)
            fps: 초당 프레임 수
            resolution: 비디오 해상도 (width, height)
        """
        self.dealer_id = dealer_id
        self.game_type = game_type
        self.media_live_channel_id = media_live_channel_id
        self.fps = fps
        self.resolution = resolution
        self.is_running = False
        self.start_time = None
        
        # AWS 클라이언트 초기화
        self.medialive_client = boto3.client('medialive')
        self.s3_client = boto3.client('s3')
        
        # 게임 상태 정보
        self.game_state = {
            "dealer_id": dealer_id,
            "game_type": game_type,
            "status": "initializing",
            "current_hand": None,
            "cards_dealt": [],
            "last_updated": datetime.now().isoformat()
        }
        
        # Redis 캐시 설정 (게임 상태 캐싱)
        self.redis_key = f"ai_dealer:{dealer_id}:state"
        
        logger.info(f"AI 딜러 초기화: {dealer_id} (게임: {game_type})")
    
    async def start(self) -> bool:
        """
        AI 딜러 스트리밍 시작 (AWS MediaLive 채널 시작)
        
        Returns:
            성공 여부
        """
        if self.is_running:
            logger.warning(f"AI 딜러 {self.dealer_id}는 이미 실행 중입니다")
            return True
        
        try:
            # MediaLive 채널 시작
            if self.media_live_channel_id:
                response = self.medialive_client.start_channel(
                    ChannelId=self.media_live_channel_id
                )
                logger.info(f"MediaLive 채널 시작: {self.media_live_channel_id}")
            else:
                # 새 채널 생성 필요 (실제 구현에서는 채널 생성 로직 추가)
                logger.warning("MediaLive 채널 ID가 없습니다. 채널을 먼저 생성해야 합니다.")
                return False
            
            self.is_running = True
            self.start_time = datetime.now()
            self.game_state["status"] = "running"
            self.game_state["last_updated"] = datetime.now().isoformat()
            
            # Redis에 게임 상태 저장
            await self._cache_game_state()
            
            logger.info(f"AI 딜러 {self.dealer_id} 시작됨")
            return True
            
        except ClientError as e:
            logger.error(f"AWS MediaLive 채널 시작 오류: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"AI 딜러 시작 오류: {str(e)}")
            return False
    
    async def stop(self) -> bool:
        """
        AI 딜러 스트리밍 중지 (AWS MediaLive 채널 중지)
        
        Returns:
            성공 여부
        """
        if not self.is_running:
            logger.warning(f"AI 딜러 {self.dealer_id}는 이미 중지되었습니다")
            return True
        
        try:
            # MediaLive 채널 중지
            if self.media_live_channel_id:
                response = self.medialive_client.stop_channel(
                    ChannelId=self.media_live_channel_id
                )
                logger.info(f"MediaLive 채널 중지: {self.media_live_channel_id}")
            
            self.is_running = False
            self.game_state["status"] = "stopped"
            self.game_state["last_updated"] = datetime.now().isoformat()
            
            # Redis에 게임 상태 저장
            await self._cache_game_state()
            
            logger.info(f"AI 딜러 {self.dealer_id} 중지됨")
            return True
            
        except ClientError as e:
            logger.error(f"AWS MediaLive 채널 중지 오류: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"AI 딜러 중지 오류: {str(e)}")
            return False
    
    async def _cache_game_state(self):
        """
        Redis에 게임 상태 캐싱 (비동기 작업)
        """
        try:
            # 실제 구현에서는 Redis 클라이언트로 상태 캐싱
            # 이 코드는 백엔드 서비스에 Redis 클라이언트가 구현되어 있다고 가정
            from ..cache_service import cache_client
            
            await cache_client.set(
                self.redis_key, 
                json.dumps(self.game_state), 
                expire=3600  # 1시간 캐시
            )
            logger.debug(f"게임 상태 캐싱됨: {self.redis_key}")
        except Exception as e:
            logger.error(f"게임 상태 캐싱 오류: {str(e)}")
    
    def get_media_live_info(self) -> Dict[str, Any]:
        """
        MediaLive 채널 정보 조회
        
        Returns:
            채널 정보
        """
        if not self.media_live_channel_id:
            return {"error": "MediaLive 채널이 구성되지 않았습니다"}
        
        try:
            response = self.medialive_client.describe_channel(
                ChannelId=self.media_live_channel_id
            )
            
            # 필요한 정보만 추출
            channel_info = {
                "channel_id": response.get("Id"),
                "name": response.get("Name"),
                "state": response.get("State"),
                "input_attachments": [
                    {
                        "input_id": input_attach.get("InputId"),
                        "input_name": input_attach.get("InputAttachmentName")
                    }
                    for input_attach in response.get("InputAttachments", [])
                ],
                "destinations": response.get("Destinations", [])
            }
            
            return channel_info
            
        except ClientError as e:
            logger.error(f"MediaLive 채널 정보 조회 오류: {str(e)}")
            return {"error": str(e)}
    
    def get_hls_endpoints(self) -> List[str]:
        """
        MediaLive 채널의 HLS 엔드포인트 목록 반환
        
        Returns:
            HLS 엔드포인트 URL 목록
        """
        try:
            channel_info = self.get_media_live_info()
            
            if "error" in channel_info:
                return []
            
            hls_endpoints = []
            for dest in channel_info.get("destinations", []):
                for output in dest.get("Settings", []):
                    url = output.get("Url")
                    if url and "m3u8" in url:
                        hls_endpoints.append(url)
            
            return hls_endpoints
            
        except Exception as e:
            logger.error(f"HLS 엔드포인트 조회 오류: {str(e)}")
            return []
    
    def update_game_state(self, state_update: Dict[str, Any]) -> Dict[str, Any]:
        """
        게임 상태 업데이트
        
        Args:
            state_update: 업데이트할 게임 상태 정보
            
        Returns:
            업데이트된 전체 게임 상태
        """
        # 게임 상태 업데이트
        self.game_state.update(state_update)
        self.game_state["last_updated"] = datetime.now().isoformat()
        
        # 비동기 태스크로 Redis 캐싱 실행
        asyncio.create_task(self._cache_game_state())
        
        logger.info(f"게임 상태 업데이트: {json.dumps(state_update)}")
        return self.game_state
    
    def get_game_state(self) -> Dict[str, Any]:
        """
        현재 게임 상태 반환
        
        Returns:
            현재 게임 상태
        """
        return self.game_state
    
    def get_stream_info(self) -> Dict[str, Any]:
        """
        스트림 정보 반환
        
        Returns:
            스트림 정보
        """
        return {
            "dealer_id": self.dealer_id,
            "game_type": self.game_type,
            "is_running": self.is_running,
            "resolution": self.resolution,
            "fps": self.fps,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "media_live_channel_id": self.media_live_channel_id,
            "hls_endpoints": self.get_hls_endpoints()
        }
    
    async def generate_audio_chunk(self) -> bytes:
        """
        오디오 청크 생성 (무음)
        
        Returns:
            오디오 데이터
        """
        # 실제 구현에서는 AWS Polly 또는 다른 AWS 서비스를 사용하여 오디오 생성
        # 예시로 무음 데이터 생성 (16비트, 48kHz, 모노)
        import numpy as np
        duration_ms = 20  # 20ms 청크
        sample_rate = 48000
        num_samples = int(sample_rate * duration_ms / 1000)
        silence = np.zeros(num_samples, dtype=np.int16)
        return silence.tobytes() 