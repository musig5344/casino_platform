import asyncio
import logging
import json
import boto3
from typing import Dict, Any, Optional, List, Tuple
from botocore.exceptions import ClientError

from .AIDealer import AIDealer

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AIWebRTCBridge:
    """
    AI 딜러와 WebRTC 간의 브릿지
    AWS MediaLive와 클라이언트 간의 WebRTC 연결 관리
    """
    
    def __init__(self):
        # 활성 AI 딜러 관리
        self.ai_dealers = {}          # dealer_id -> AIDealer
        self.client_connections = {}  # client_id -> {"dealer_id": dealer_id, "status": status}
        
        # AWS 클라이언트 초기화
        self.medialive_client = boto3.client('medialive')
        self.medialiveconnect_client = boto3.client('medialiveconnect')
        
        # STUN/TURN 서버 설정
        self.ice_config = {
            "iceServers": [
                {"urls": ["stun:stun.l.google.com:19302"]},
                # 비용 효율적인 TURN 서버 설정은 앱 운영 시 추가
            ]
        }
        
        logger.info("AI WebRTC 브릿지 초기화됨")
    
    async def register_ai_dealer(self, ai_dealer: AIDealer) -> bool:
        """
        AI 딜러 등록
        
        Args:
            ai_dealer: AI 딜러 인스턴스
            
        Returns:
            성공 여부
        """
        dealer_id = ai_dealer.dealer_id
        
        if dealer_id in self.ai_dealers:
            logger.warning(f"딜러 ID {dealer_id}는 이미 등록되어 있습니다")
            # 기존 딜러 교체
            old_dealer = self.ai_dealers[dealer_id]
            await old_dealer.stop()
        
        # 새 딜러 등록
        self.ai_dealers[dealer_id] = ai_dealer
        
        # 딜러 시작
        if not ai_dealer.is_running:
            await ai_dealer.start()
        
        logger.info(f"AI 딜러 등록됨: {dealer_id}")
        return True
    
    async def unregister_ai_dealer(self, dealer_id: str) -> bool:
        """
        AI 딜러 등록 해제
        
        Args:
            dealer_id: AI 딜러 ID
            
        Returns:
            성공 여부
        """
        if dealer_id not in self.ai_dealers:
            logger.warning(f"딜러 ID {dealer_id}를 찾을 수 없습니다")
            return False
        
        # 딜러 가져오기
        ai_dealer = self.ai_dealers[dealer_id]
        
        # 연결된 모든 클라이언트 연결 종료
        for client_id, connection in list(self.client_connections.items()):
            if connection.get("dealer_id") == dealer_id:
                await self._close_client_connection(client_id)
        
        # 딜러 중지
        await ai_dealer.stop()
        
        # 등록 해제
        del self.ai_dealers[dealer_id]
        
        logger.info(f"AI 딜러 등록 해제됨: {dealer_id}")
        return True
    
    async def create_webrtc_session(self, dealer_id: str, client_id: str) -> Dict[str, Any]:
        """
        WebRTC 세션 생성
        
        Args:
            dealer_id: AI 딜러 ID
            client_id: 클라이언트 ID
            
        Returns:
            WebRTC 세션 정보
        """
        if dealer_id not in self.ai_dealers:
            raise ValueError(f"딜러 ID {dealer_id}를 찾을 수 없습니다")
        
        try:
            # AWS MediaLive 채널 정보 조회
            ai_dealer = self.ai_dealers[dealer_id]
            media_live_channel_id = ai_dealer.media_live_channel_id
            
            if not media_live_channel_id:
                raise ValueError("MediaLive 채널이 구성되지 않았습니다")
            
            # MediaLiveConnect를 통한 WebRTC 세션 생성
            # 실제 구현 시에는 AWS MediaLive 서비스의 WebRTC 기능 활용
            # 여기서는 예시 코드만 제공
            
            # 클라이언트 연결 정보 저장
            self.client_connections[client_id] = {
                "dealer_id": dealer_id,
                "status": "creating",
                "created_at": asyncio.get_event_loop().time()
            }
            
            # ICE 설정 반환 (실제로는 AWS 서비스에서 제공하는 WebRTC 설정)
            session_info = {
                "client_id": client_id,
                "ice_config": self.ice_config,
                "dealer_id": dealer_id,
                "hls_fallback_urls": ai_dealer.get_hls_endpoints(),
                "status": "ready"
            }
            
            # 연결 상태 업데이트
            self.client_connections[client_id]["status"] = "ready"
            
            logger.info(f"WebRTC 세션 생성됨: 클라이언트 {client_id}, 딜러 {dealer_id}")
            
            return session_info
            
        except ClientError as e:
            logger.error(f"AWS MediaLive WebRTC 세션 생성 오류: {str(e)}")
            raise ValueError(f"WebRTC 세션 생성 실패: {str(e)}")
        except Exception as e:
            logger.error(f"WebRTC 세션 생성 오류: {str(e)}")
            raise ValueError(f"WebRTC 세션 생성 실패: {str(e)}")
    
    async def close_webrtc_session(self, client_id: str) -> bool:
        """
        WebRTC 세션 종료
        
        Args:
            client_id: 클라이언트 ID
            
        Returns:
            성공 여부
        """
        if client_id not in self.client_connections:
            logger.warning(f"클라이언트 ID {client_id}를 찾을 수 없습니다")
            return False
        
        await self._close_client_connection(client_id)
        return True
    
    async def _close_client_connection(self, client_id: str) -> None:
        """
        클라이언트 연결 종료
        
        Args:
            client_id: 클라이언트 ID
        """
        if client_id in self.client_connections:
            # 연결 상태 업데이트
            self.client_connections[client_id]["status"] = "closed"
            
            # 실제 WebRTC 세션 종료 로직 (AWS MediaLive 연동)
            # 여기서는 예시 코드만 제공
            
            # 클라이언트 연결 정보 삭제
            del self.client_connections[client_id]
            
            logger.info(f"클라이언트 연결 종료됨: {client_id}")
    
    async def close_all_connections(self) -> None:
        """
        모든 연결 종료
        """
        # 모든 클라이언트 연결 종료
        for client_id in list(self.client_connections.keys()):
            await self._close_client_connection(client_id)
        
        # 모든 AI 딜러 중지
        for dealer_id, ai_dealer in list(self.ai_dealers.items()):
            await ai_dealer.stop()
            del self.ai_dealers[dealer_id]
        
        logger.info("모든 연결 종료됨")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        시스템 상태 통계 정보 반환
        
        Returns:
            통계 정보
        """
        return {
            "ai_dealers": {
                dealer_id: dealer.get_stream_info()
                for dealer_id, dealer in self.ai_dealers.items()
            },
            "client_connections": {
                client_id: connection
                for client_id, connection in self.client_connections.items()
            },
            "total_dealers": len(self.ai_dealers),
            "total_connections": len(self.client_connections)
        }
    
    async def get_hls_fallback_urls(self, dealer_id: str) -> List[str]:
        """
        HLS 폴백 URL 목록 반환 (WebRTC 연결 실패 시 대체 스트림)
        
        Args:
            dealer_id: AI 딜러 ID
            
        Returns:
            HLS URL 목록
        """
        if dealer_id not in self.ai_dealers:
            logger.warning(f"딜러 ID {dealer_id}를 찾을 수 없습니다")
            return []
        
        ai_dealer = self.ai_dealers[dealer_id]
        return ai_dealer.get_hls_endpoints() 