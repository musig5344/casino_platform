import json
import os
import logging
import pytz
from datetime import datetime
from typing import Dict, Any, Callable, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from casino_platform.schemas.wallet import Language, TimeZone

logger = logging.getLogger(__name__)

class LocalizationMiddleware(BaseHTTPMiddleware):
    """
    국제화 및 현지화를 위한 미들웨어
    
    - Accept-Language 헤더를 기반으로 언어 감지
    - 사용자 프로필의 선호 언어 및 시간대 처리
    - 응답의 날짜/시간 값을 사용자 시간대로 변환
    """
    
    def __init__(
        self, 
        app,
        default_language: str = "ko",
        default_timezone: str = "UTC",
        translations_dir: str = "translations"
    ):
        super().__init__(app)
        self.default_language = default_language
        self.default_timezone = default_timezone
        self.translations_dir = translations_dir
        self.translations = self._load_translations()
        
        logger.info(f"현지화 미들웨어 초기화: 기본 언어={default_language}, 기본 시간대={default_timezone}")
    
    def _load_translations(self) -> Dict[str, Dict[str, str]]:
        """
        번역 파일들을 로드합니다.
        
        Returns:
            Dict[str, Dict[str, str]]: 언어별 메시지 딕셔너리
        """
        translations = {}
        
        try:
            # translations 디렉토리가 없으면 생성
            if not os.path.exists(self.translations_dir):
                os.makedirs(self.translations_dir)
                logger.warning(f"번역 디렉토리 생성됨: {self.translations_dir}")
                
                # 기본 번역 파일 생성 (예시)
                self._create_default_translation_files()
            
            # 각 언어 파일 로드
            for lang_code in [lang.value for lang in Language]:
                lang_file = os.path.join(self.translations_dir, f"{lang_code}.json")
                
                if os.path.exists(lang_file):
                    with open(lang_file, "r", encoding="utf-8") as f:
                        translations[lang_code] = json.load(f)
                        logger.info(f"언어 파일 로드됨: {lang_code} ({len(translations[lang_code])} 항목)")
                else:
                    logger.warning(f"언어 파일 없음: {lang_file}")
                    translations[lang_code] = {}
            
            return translations
            
        except Exception as e:
            logger.error(f"번역 파일 로드 중 오류: {str(e)}")
            return {}
    
    def _create_default_translation_files(self):
        """기본 번역 파일을 생성합니다."""
        try:
            # 한국어(ko) 메시지
            ko_messages = {
                "insufficient_funds": "잔액이 부족합니다",
                "transaction_successful": "거래가 성공적으로 처리되었습니다",
                "wallet_not_found": "지갑을 찾을 수 없습니다",
                "invalid_amount": "금액이 올바르지 않습니다",
                "amount_must_be_positive": "금액은 0보다 커야 합니다",
                "internal_error": "내부 서버 오류가 발생했습니다"
            }
            
            # 영어(en) 메시지
            en_messages = {
                "insufficient_funds": "Insufficient funds",
                "transaction_successful": "Transaction processed successfully",
                "wallet_not_found": "Wallet not found",
                "invalid_amount": "Invalid amount",
                "amount_must_be_positive": "Amount must be greater than 0",
                "internal_error": "Internal server error occurred"
            }
            
            # 일본어(ja) 메시지
            ja_messages = {
                "insufficient_funds": "残高不足です",
                "transaction_successful": "トランザクションが正常に処理されました",
                "wallet_not_found": "ウォレットが見つかりません",
                "invalid_amount": "金額が無効です",
                "amount_must_be_positive": "金額は0より大きくなければなりません",
                "internal_error": "内部サーバーエラーが発生しました"
            }
            
            # 파일로 저장
            with open(os.path.join(self.translations_dir, "ko.json"), "w", encoding="utf-8") as f:
                json.dump(ko_messages, f, ensure_ascii=False, indent=2)
                
            with open(os.path.join(self.translations_dir, "en.json"), "w", encoding="utf-8") as f:
                json.dump(en_messages, f, ensure_ascii=False, indent=2)
                
            with open(os.path.join(self.translations_dir, "ja.json"), "w", encoding="utf-8") as f:
                json.dump(ja_messages, f, ensure_ascii=False, indent=2)
                
            logger.info("기본 번역 파일 생성 완료")
            
        except Exception as e:
            logger.error(f"기본 번역 파일 생성 중 오류: {str(e)}")
    
    def _get_language(self, request: Request) -> str:
        """
        요청에서 선호 언어를 추출합니다.
        
        Args:
            request: FastAPI 요청 객체
            
        Returns:
            str: 언어 코드
        """
        # 1. 쿠키에서 언어 설정 확인
        lang_cookie = request.cookies.get("language")
        if lang_cookie and lang_cookie in [lang.value for lang in Language]:
            return lang_cookie
            
        # 2. Accept-Language 헤더 확인
        accept_language = request.headers.get("accept-language", "")
        if accept_language:
            # 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7' 형식 파싱
            for lang_item in accept_language.split(","):
                lang_parts = lang_item.strip().split(";")[0].split("-")
                lang_code = lang_parts[0].lower()
                
                if lang_code in [lang.value for lang in Language]:
                    return lang_code
        
        # 3. 기본 언어 반환
        return self.default_language
    
    def _get_timezone(self, request: Request) -> str:
        """
        요청에서 선호 시간대를 추출합니다.
        
        Args:
            request: FastAPI 요청 객체
            
        Returns:
            str: 시간대 (pytz 형식)
        """
        # 1. 쿠키에서 시간대 설정 확인
        tz_cookie = request.cookies.get("timezone")
        if tz_cookie and tz_cookie in pytz.all_timezones:
            return tz_cookie
        
        # 2. 기본 시간대 반환
        return self.default_timezone
    
    def translate(self, key: str, language: str) -> str:
        """
        주어진 키에 대한 번역을 반환합니다.
        
        Args:
            key: 메시지 키
            language: 언어 코드
            
        Returns:
            str: 번역된 메시지
        """
        try:
            # 언어가 지원되지 않으면 기본 언어 사용
            if language not in self.translations:
                language = self.default_language
                
            # 키가 있으면 번역 반환, 없으면 키 그대로 반환
            return self.translations.get(language, {}).get(key, key)
            
        except Exception as e:
            logger.error(f"번역 중 오류: {str(e)}")
            return key
    
    def _convert_datetime_to_timezone(self, dt_str: str, timezone: str) -> str:
        """
        ISO 형식의 UTC 날짜/시간 문자열을 지정된 시간대로 변환합니다.
        
        Args:
            dt_str: ISO 형식의 날짜/시간 문자열
            timezone: 변환할 시간대
            
        Returns:
            str: 변환된 ISO 형식의 날짜/시간 문자열
        """
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            target_tz = pytz.timezone(timezone)
            
            # UTC 시간을 대상 시간대로 변환
            localized_dt = dt.astimezone(target_tz)
            
            return localized_dt.isoformat()
            
        except (ValueError, pytz.exceptions.UnknownTimeZoneError) as e:
            logger.error(f"시간대 변환 중 오류: {str(e)}")
            return dt_str
    
    def _localize_json_response(self, data: Any, timezone: str) -> Any:
        """
        JSON 응답 데이터의 날짜/시간 값을 현지화합니다.
        
        Args:
            data: JSON 응답 데이터
            timezone: 변환할 시간대
            
        Returns:
            Any: 현지화된 데이터
        """
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                # created_at, updated_at, timestamp 등의 필드 변환
                if key.endswith("_at") or key.endswith("_time") or key == "timestamp":
                    if isinstance(value, str) and "T" in value:
                        result[key] = self._convert_datetime_to_timezone(value, timezone)
                    else:
                        result[key] = value
                elif isinstance(value, (dict, list)):
                    result[key] = self._localize_json_response(value, timezone)
                else:
                    result[key] = value
            return result
        elif isinstance(data, list):
            return [self._localize_json_response(item, timezone) for item in data]
        else:
            return data
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        미들웨어 처리 로직
        
        Args:
            request: FastAPI 요청 객체
            call_next: 다음 미들웨어 호출 함수
            
        Returns:
            Response: 응답 객체
        """
        # 언어 및 시간대 결정
        language = self._get_language(request)
        timezone = self._get_timezone(request)
        
        # 요청 확장 속성에 언어 및 시간대 설정
        request.state.language = language
        request.state.timezone = timezone
        request.state.translate = lambda key: self.translate(key, language)
        
        # 요청 처리
        response = await call_next(request)
        
        # JSON 응답인 경우 날짜/시간 현지화
        if response.headers.get("content-type") == "application/json":
            try:
                body = await response.body()
                text = body.decode("utf-8")
                
                data = json.loads(text)
                localized_data = self._localize_json_response(data, timezone)
                
                # 새 응답 생성
                new_body = json.dumps(localized_data, ensure_ascii=False).encode("utf-8")
                
                # 응답 헤더 복사 및 콘텐츠 길이 수정
                headers = dict(response.headers)
                headers["content-length"] = str(len(new_body))
                
                # 언어 관련 헤더 추가
                headers["Content-Language"] = language
                
                # 새 응답 반환
                return Response(
                    content=new_body,
                    status_code=response.status_code,
                    headers=headers,
                    media_type="application/json"
                )
                
            except json.JSONDecodeError:
                # JSON이 아닌 경우 원본 응답 반환
                pass
        
        # 언어 관련 헤더 추가
        response.headers["Content-Language"] = language
        
        return response


async def get_translator(request: Request) -> Callable[[str], str]:
    """
    번역 함수를 반환하는 의존성
    
    Args:
        request: FastAPI 요청 객체
        
    Returns:
        Callable[[str], str]: 번역 함수
    """
    # request.state.translate가 설정되어 있는지 확인
    if hasattr(request.state, "translate"):
        return request.state.translate
    
    # 미들웨어가 설정되지 않은 경우 기본 함수 반환
    return lambda x: x 