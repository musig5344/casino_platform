import json
import logging
from typing import Dict, Any, Optional
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)

class KafkaProducerMock:
    """Kafka 프로듀서 모의 구현 (실제 Kafka 연결 없이 테스트용)"""
    
    def __init__(self):
        self.messages = []
        logger.info("Kafka 프로듀서 모의 객체가 초기화되었습니다.")
    
    def send(self, topic: str, value: bytes, key: Optional[bytes] = None) -> None:
        """메시지 전송 (모의)"""
        try:
            # 바이트를 문자열로 디코딩하여 로깅
            value_str = value.decode('utf-8') if isinstance(value, bytes) else str(value)
            key_str = key.decode('utf-8') if key and isinstance(key, bytes) else str(key)
            
            message = {
                "topic": topic, 
                "key": key_str if key else None, 
                "value": value_str,
                "timestamp": datetime.now().isoformat()
            }
            
            self.messages.append(message)
            logger.info(f"Kafka 메시지가 전송되었습니다 (모의): 토픽={topic}, 키={key_str if key else 'None'}")
            logger.debug(f"메시지 내용: {value_str}")
            
            return {"offset": len(self.messages) - 1, "topic": topic}
        except Exception as e:
            logger.error(f"Kafka 메시지 전송 중 오류 (모의): {e}")
            return None
    
    def flush(self) -> None:
        """버퍼링된 메시지 전송 (모의)"""
        logger.info(f"Kafka 프로듀서 플러시 (모의): {len(self.messages)}개 메시지")
    
    def close(self) -> None:
        """프로듀서 종료 (모의)"""
        logger.info("Kafka 프로듀서가 종료되었습니다 (모의).")
        self.messages = []
    
    def get_messages(self) -> list:
        """저장된 메시지 목록 반환 (모의 전용)"""
        return self.messages

# 싱글톤 프로듀서 인스턴스
_producer = None

def get_kafka_producer():
    """Kafka 프로듀서 인스턴스 반환 (싱글톤)"""
    global _producer
    if _producer is None:
        try:
            # 실제 Kafka 프로듀서 구현을 사용할 수 있으면 사용
            # from kafka import KafkaProducer
            # _producer = KafkaProducer(bootstrap_servers=['localhost:9092'])
            
            # 모의 프로듀서 사용
            _producer = KafkaProducerMock()
            logger.info("Kafka 프로듀서 모의 객체가 생성되었습니다.")
        except Exception as e:
            logger.error(f"Kafka 프로듀서 생성 중 오류: {e}")
            _producer = KafkaProducerMock()
            logger.warning("오류로 인해 Kafka 프로듀서 모의 객체로 대체되었습니다.")
    
    return _producer

async def send_kafka_message(topic: str, message: Dict[str, Any], key: Optional[str] = None) -> bool:
    """
    Kafka 토픽에 메시지를 비동기적으로 전송합니다.
    
    Args:
        topic: Kafka 토픽 이름
        message: 전송할 메시지 (딕셔너리)
        key: 메시지 키 (선택 사항)
        
    Returns:
        bool: 전송 성공 여부
    """
    try:
        producer = get_kafka_producer()
        
        # 메시지를 JSON 문자열로 직렬화
        value_bytes = json.dumps(message).encode('utf-8')
        key_bytes = key.encode('utf-8') if key else None
        
        # 메시지 전송
        future = producer.send(topic, value=value_bytes, key=key_bytes)
        
        # 비동기 환경에서 작업 실행을 위해 짧은 대기 추가
        await asyncio.sleep(0)
        
        logger.info(f"Kafka 메시지가 토픽 '{topic}'에 전송되었습니다")
        return True
    except Exception as e:
        logger.error(f"Kafka 메시지 전송 중 오류: {e}")
        return False

# 동기 버전의 함수 (비동기 환경이 아닌 곳에서 사용)
def send_kafka_message_sync(topic: str, message: Dict[str, Any], key: Optional[str] = None) -> bool:
    """
    Kafka 토픽에 메시지를 동기적으로 전송합니다.
    
    Args:
        topic: Kafka 토픽 이름
        message: 전송할 메시지 (딕셔너리)
        key: 메시지 키 (선택 사항)
        
    Returns:
        bool: 전송 성공 여부
    """
    try:
        producer = get_kafka_producer()
        
        # 메시지를 JSON 문자열로 직렬화
        value_bytes = json.dumps(message).encode('utf-8')
        key_bytes = key.encode('utf-8') if key else None
        
        # 메시지 전송
        future = producer.send(topic, value=value_bytes, key=key_bytes)
        producer.flush()  # 메시지 즉시 전송 보장
        
        logger.info(f"Kafka 메시지가 토픽 '{topic}'에 전송되었습니다 (동기)")
        return True
    except Exception as e:
        logger.error(f"Kafka 메시지 전송 중 오류 (동기): {e}")
        return False 