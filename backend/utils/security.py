"""
암호화 및 보안 관련 유틸리티 모듈
"""
from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad, unpad
from Cryptodome.Random import get_random_bytes
import base64
from backend.config.database import settings
import logging
import hashlib

logger = logging.getLogger(__name__)

class CryptoUtils:
    """민감한 데이터 암호화/복호화를 위한 유틸리티 클래스"""
    
    @staticmethod
    def generate_key():
        """
        AES-256 암호화에 사용할 32바이트 키를 생성합니다.
        이 함수는 새 키가 필요할 때만 사용하세요.
        """
        key = get_random_bytes(32)  # AES-256은 32바이트 키 사용
        return base64.b64encode(key).decode('utf-8')
    
    @staticmethod
    def get_key():
        """
        환경 변수에서 암호화 키를 가져옵니다.
        키가 설정되지 않았으면 에러 로그를 남깁니다.
        """
        if not settings.ENCRYPTION_KEY:
            logger.error("암호화 키가 설정되지 않았습니다. ENCRYPTION_KEY 환경 변수를 설정하세요.")
            return None
        
        # Base64 인코딩된 키를 디코딩합니다.
        try:
            raw_key = base64.b64decode(settings.ENCRYPTION_KEY)
            if len(raw_key) != 32:
                logger.error(f"암호화 키 길이가 잘못되었습니다. 32바이트여야 하는데 {len(raw_key)}바이트입니다.")
                return None
            return raw_key
        except Exception as e:
            logger.error(f"암호화 키 디코딩 오류: {e}")
            return None
    
    @staticmethod
    def encrypt(plaintext):
        """
        AES-256을 사용하여 문자열을 암호화합니다.
        
        Args:
            plaintext (str): 암호화할 평문
            
        Returns:
            str: Base64로 인코딩된 암호문
        """
        if not plaintext:
            return plaintext
        
        key = CryptoUtils.get_key()
        if not key:
            logger.error("암호화 키를 가져올 수 없어 암호화를 건너뜁니다.")
            return plaintext
        
        try:
            # iv(Initialization Vector)를 생성합니다.
            iv = get_random_bytes(16)
            
            # AES 객체를 생성합니다.
            cipher = AES.new(key, AES.MODE_CBC, iv)
            
            # 평문을 바이트로 변환하고 패딩합니다.
            padded_plaintext = pad(plaintext.encode('utf-8'), AES.block_size)
            
            # 암호화합니다.
            ciphertext = cipher.encrypt(padded_plaintext)
            
            # iv와 암호문을 결합하고 Base64로 인코딩합니다.
            encrypted = base64.b64encode(iv + ciphertext).decode('utf-8')
            
            return encrypted
        except Exception as e:
            logger.error(f"암호화 오류: {e}")
            return plaintext
    
    @staticmethod
    def decrypt(encrypted_text):
        """
        AES-256을 사용하여 암호화된 문자열을 복호화합니다.
        
        Args:
            encrypted_text (str): Base64로 인코딩된 암호문
            
        Returns:
            str: 복호화된 평문
        """
        if not encrypted_text:
            return encrypted_text
        
        key = CryptoUtils.get_key()
        if not key:
            logger.error("암호화 키를 가져올 수 없어 복호화를 건너뜁니다.")
            return encrypted_text
        
        try:
            # Base64로 디코딩합니다.
            encrypted_bytes = base64.b64decode(encrypted_text)
            
            # iv를 추출합니다 (처음 16바이트).
            iv = encrypted_bytes[:16]
            
            # 암호문을 추출합니다 (나머지 바이트).
            ciphertext = encrypted_bytes[16:]
            
            # AES 객체를 생성합니다.
            cipher = AES.new(key, AES.MODE_CBC, iv)
            
            # 복호화하고 패딩을 제거합니다.
            plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)
            
            return plaintext.decode('utf-8')
        except Exception as e:
            logger.error(f"복호화 오류: {e}")
            return encrypted_text
    
    @staticmethod
    def hash_password(password):
        """
        비밀번호를 SHA-256으로 해싱합니다.
        
        실제 운영 환경에서는 더 강력한 알고리즘(bcrypt, Argon2 등)을 사용하는 것이 좋습니다.
        
        Args:
            password (str): 해싱할 비밀번호
            
        Returns:
            str: 해싱된 비밀번호
        """
        return hashlib.sha256(password.encode('utf-8')).hexdigest() 