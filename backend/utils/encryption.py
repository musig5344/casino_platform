from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import os
import json
from typing import Dict, Any, Union, Optional
from backend.config.settings import get_settings

class EncryptionManager:
    """
    데이터 암호화 및 복호화를 처리하는 클래스
    특히 KYC 및 AML 관련 민감한 정보를 보호하기 위해 사용
    """
    
    def __init__(self, encryption_key: Optional[str] = None):
        """
        암호화 관리자 초기화
        
        Args:
            encryption_key: 선택적 암호화 키, 제공되지 않으면 환경 변수에서 가져옴
        """
        # 설정에서 암호화 키 가져오기
        settings = get_settings()
        self.encryption_key = encryption_key or settings.ENCRYPTION_KEY
        
        try:
            # 키가 유효한 base64 인코딩인지 확인
            try:
                key_bytes = base64.urlsafe_b64decode(self.encryption_key)
                if len(key_bytes) != 32:  # Fernet 키는 32바이트여야 함
                    raise ValueError("암호화 키의 형식이 올바르지 않습니다.")
            except Exception:
                # 키가 유효하지 않으면 새 키 생성
                print("유효하지 않은 암호화 키, 새 키 생성 중...")
                self.encryption_key = Fernet.generate_key().decode()
                
            # Fernet 암호화 객체 생성
            if isinstance(self.encryption_key, str):
                # 문자열이면 바이트로 변환 (이미 base64 인코딩된 경우)
                self.cipher_suite = Fernet(self.encryption_key.encode())
            else:
                # 이미 바이트면 그대로 사용
                self.cipher_suite = Fernet(self.encryption_key)
        except Exception as e:
            raise ValueError(f"암호화 키 초기화 오류: {str(e)}")
    
    @classmethod
    def generate_key(cls) -> str:
        """
        새로운 Fernet 암호화 키 생성
        
        Returns:
            str: base64로 인코딩된 암호화 키
        """
        return base64.urlsafe_b64encode(Fernet.generate_key()).decode()
    
    @classmethod
    def derive_key_from_password(cls, password: str, salt: Optional[bytes] = None) -> Dict[str, str]:
        """
        암호와 솔트에서 키 유도
        
        Args:
            password: 암호
            salt: 선택적 솔트, 제공되지 않으면 자동 생성
            
        Returns:
            Dict[str, str]: 키와 솔트를 포함하는 딕셔너리
        """
        if not salt:
            salt = os.urandom(16)
            
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return {
            "key": key.decode(),
            "salt": base64.b64encode(salt).decode()
        }
    
    def encrypt(self, data: Union[str, bytes, Dict[str, Any]]) -> str:
        """
        데이터 암호화
        
        Args:
            data: 암호화할 데이터 (문자열, 바이트 또는 딕셔너리)
            
        Returns:
            str: 암호화된 데이터 (base64로 인코딩)
        """
        try:
            # 딕셔너리를 JSON 문자열로 변환
            if isinstance(data, dict):
                data = json.dumps(data)
                
            # 문자열을 바이트로 변환
            if isinstance(data, str):
                data = data.encode()
                
            # 데이터 암호화
            encrypted_data = self.cipher_suite.encrypt(data)
            
            # base64로 인코딩하여 반환
            return base64.urlsafe_b64encode(encrypted_data).decode()
        except Exception as e:
            raise RuntimeError(f"데이터 암호화 오류: {str(e)}")
    
    def decrypt(self, encrypted_data: str, as_json: bool = False) -> Union[str, Dict[str, Any]]:
        """
        암호화된 데이터 복호화
        
        Args:
            encrypted_data: 복호화할 암호화된 데이터 (base64로 인코딩)
            as_json: 결과를 JSON으로 파싱할지 여부
            
        Returns:
            Union[str, Dict[str, Any]]: 복호화된 데이터
        """
        try:
            # base64에서 디코딩
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_data)
            
            # 데이터 복호화
            decrypted_data = self.cipher_suite.decrypt(encrypted_bytes).decode()
            
            # JSON으로 파싱
            if as_json:
                return json.loads(decrypted_data)
                
            return decrypted_data
        except Exception as e:
            raise RuntimeError(f"데이터 복호화 오류: {str(e)}")
    
    def encrypt_document_data(self, document_data: Dict[str, Any]) -> str:
        """
        신분증 데이터 암호화 (KYC에서 사용)
        
        Args:
            document_data: 암호화할 문서 데이터
            
        Returns:
            str: 암호화된 문서 데이터
        """
        return self.encrypt(document_data)
    
    def decrypt_document_data(self, encrypted_data: str) -> Dict[str, Any]:
        """
        암호화된 신분증 데이터 복호화 (KYC에서 사용)
        
        Args:
            encrypted_data: 복호화할 암호화된 문서 데이터
            
        Returns:
            Dict[str, Any]: 복호화된 문서 데이터
        """
        return self.decrypt(encrypted_data, as_json=True)
    
    def encrypt_pii(self, pii_data: Dict[str, Any]) -> str:
        """
        개인 식별 정보(PII) 암호화
        
        Args:
            pii_data: 암호화할 PII 데이터
            
        Returns:
            str: 암호화된 PII 데이터
        """
        return self.encrypt(pii_data)
    
    def decrypt_pii(self, encrypted_data: str) -> Dict[str, Any]:
        """
        암호화된 개인 식별 정보(PII) 복호화
        
        Args:
            encrypted_data: 복호화할 암호화된 PII 데이터
            
        Returns:
            Dict[str, Any]: 복호화된 PII 데이터
        """
        return self.decrypt(encrypted_data, as_json=True)
    
    def hash_sensitive_data(self, data: str) -> str:
        """
        민감한 데이터의 해시 생성 (단방향)
        
        Args:
            data: 해시할 데이터
            
        Returns:
            str: 해시된 데이터
        """
        digest = hashes.Hash(hashes.SHA256())
        digest.update(data.encode())
        return base64.b64encode(digest.finalize()).decode()
    
    def anonymize_data(self, data: str, keep_start: int = 0, keep_end: int = 0) -> str:
        """
        데이터 일부를 익명화 (예: 신용카드 번호의 일부만 표시)
        
        Args:
            data: 익명화할 데이터
            keep_start: 시작 부분에서 유지할 문자 수
            keep_end: 끝 부분에서 유지할 문자 수
            
        Returns:
            str: 익명화된 데이터
        """
        if not data:
            return ""
            
        data_length = len(data)
        if keep_start + keep_end >= data_length:
            # 유지할 문자가 전체 길이보다 크면 모든 문자 마스킹
            return "*" * data_length
            
        start = data[:keep_start] if keep_start > 0 else ""
        end = data[-keep_end:] if keep_end > 0 else ""
        middle = "*" * (data_length - keep_start - keep_end)
        
        return f"{start}{middle}{end}"

# 싱글톤 인스턴스 생성
encryption_manager = EncryptionManager() 