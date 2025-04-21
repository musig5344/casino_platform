import json
import os
from fastapi import Request, Depends
from typing import Dict, Any, Optional
import logging
import re

logger = logging.getLogger(__name__)

# 기본 설정
LOCALES_DIR = os.path.join(os.path.dirname(__file__), 'locales')
DEFAULT_LOCALE = 'en'
# locales 디렉토리가 존재하고 실제 디렉토리인 경우에만 목록을 가져옴
SUPPORTED_LOCALES = [d for d in os.listdir(LOCALES_DIR) if os.path.isdir(os.path.join(LOCALES_DIR, d))] if os.path.exists(LOCALES_DIR) and os.path.isdir(LOCALES_DIR) else [DEFAULT_LOCALE]


# 번역 데이터 캐시
translations: Dict[str, Dict[str, Any]] = {}

def load_translations():
    """모든 지원 언어의 번역 파일을 로드합니다."""
    global translations
    translations = {}
    if not os.path.exists(LOCALES_DIR) or not os.path.isdir(LOCALES_DIR):
        logger.warning(f"Locales directory not found or not a directory: {LOCALES_DIR}")
        # 기본 로케일 데이터라도 생성 (오류 방지)
        translations[DEFAULT_LOCALE] = {}
        return

    logger.info(f"지원 언어 로딩 시작: {SUPPORTED_LOCALES}")
    for locale in SUPPORTED_LOCALES:
        locale_path = os.path.join(LOCALES_DIR, locale)
        if os.path.isdir(locale_path):
            translations[locale] = {}
            try:
                for filename in os.listdir(locale_path):
                    if filename.endswith(".json"):
                        filepath = os.path.join(locale_path, filename)
                        namespace = filename[:-5] # 확장자 제외한 파일 이름 (예: common)
                        try:
                            with open(filepath, 'r', encoding='utf-8') as f:
                                translations[locale][namespace] = json.load(f)
                        except json.JSONDecodeError:
                            logger.error(f"번역 파일 파싱 오류: {filepath}")
                        except Exception as e:
                            logger.error(f"번역 파일 로드 오류 ({filepath}): {e}")
                logger.info(f"'{locale}' 언어 번역 로드 완료.")
            except FileNotFoundError:
                 logger.warning(f"언어 디렉토리를 찾을 수 없음: {locale_path}")
            except Exception as e:
                 logger.error(f"언어 디렉토리 처리 중 오류 ({locale_path}): {e}")
        else:
            logger.warning(f"언어 디렉토리가 아님: {locale_path}")

    if not translations:
        logger.warning("로드된 번역 데이터가 없습니다. 기본 언어({DEFAULT_LOCALE})만 사용됩니다.")
        # 기본 로케일 데이터라도 생성 (오류 방지)
        translations[DEFAULT_LOCALE] = {}


# 애플리케이션 시작 시 번역 로드
load_translations()

def get_best_match_locale(accept_language_header: Optional[str]) -> str:
    """Accept-Language 헤더를 분석하여 가장 적합한 지원 언어를 반환합니다."""
    if not accept_language_header:
        return DEFAULT_LOCALE

    # q-factor 파싱 (예: "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7")
    languages = []
    for lang_part in accept_language_header.split(','):
        parts = lang_part.strip().split(';')
        locale_code = parts[0]
        q = 1.0
        if len(parts) > 1 and parts[1].startswith('q='):
            try:
                q = float(parts[1][2:])
            except ValueError:
                pass # q-factor 파싱 실패 시 기본값 사용
        languages.append((locale_code, q))

    # q-factor 기준으로 정렬 (내림차순)
    languages.sort(key=lambda x: x[1], reverse=True)

    # 지원하는 언어와 매칭 시도
    for lang, _ in languages:
        # 기본 로케일 코드 추출 (예: 'ko-KR' -> 'ko')
        primary_locale = lang.split('-')[0].lower()
        if primary_locale in SUPPORTED_LOCALES:
            return primary_locale
        # 전체 로케일 코드 매칭 시도 (예: 'en-us')
        if lang.lower() in SUPPORTED_LOCALES:
             return lang.lower()

    # 매칭되는 언어가 없으면 기본 언어 반환
    return DEFAULT_LOCALE

class Translator:
    def __init__(self, locale: str):
        self.locale = locale if locale in translations else DEFAULT_LOCALE
        # 요청된 언어의 번역 데이터가 없으면 기본 언어 데이터 사용
        self.locale_data = translations.get(self.locale, translations.get(DEFAULT_LOCALE, {}))
        if not self.locale_data and self.locale != DEFAULT_LOCALE:
             logger.warning(f"'{self.locale}' 언어 번역 데이터 없음, 기본 언어({DEFAULT_LOCALE}) 사용.")
             self.locale_data = translations.get(DEFAULT_LOCALE, {})


    def get_translation(self, key: str, **kwargs) -> str:
        """주어진 키에 해당하는 번역 문자열을 반환하고, kwargs로 플레이스홀더를 채웁니다."""
        # 키 형식: "namespace.key.subkey"
        keys = key.split('.')
        namespace = keys[0] if len(keys) > 1 else 'common' # 키가 점 포함 안하면 common 네임스페이스로 가정
        lookup_key = '.'.join(keys[1:]) if len(keys) > 1 else key

        # 네임스페이스 내에서 키 찾기
        translation_string = self.locale_data.get(namespace, {}).get(lookup_key, key) # 번역 없으면 키 자체 반환

        # 기본 언어에서도 찾아보기 (Fallback)
        if translation_string == key and self.locale != DEFAULT_LOCALE:
            default_data = translations.get(DEFAULT_LOCALE, {})
            translation_string = default_data.get(namespace, {}).get(lookup_key, key)
            if translation_string != key:
                 logger.debug(f"키 '{key}'에 대한 '{self.locale}' 번역 없음, 기본 언어({DEFAULT_LOCALE}) 사용.")

        # 플레이스홀더 치환 (예: "Hello {name}")
        try:
             # f-string 방식 플레이스홀더 ({variable})
             if isinstance(translation_string, str) and '{' in translation_string and '}' in translation_string:
                  # 정규식으로 플레이스홀더 추출 및 치환
                  placeholders = re.findall(r'\{([^}]+)\}', translation_string)
                  temp_string = translation_string
                  all_kwargs_found = True
                  for ph in placeholders:
                       if ph in kwargs:
                           temp_string = temp_string.replace(f'{{{ph}}}', str(kwargs[ph]))
                       else:
                           all_kwargs_found = False
                           logger.warning(f"번역 키 '{key}'의 플레이스홀더 '{ph}'에 대한 값이 제공되지 않음.")
                  # 모든 플레이스홀더 값이 제공되었거나 플레이스홀더가 없는 경우에만 치환
                  if all_kwargs_found or not placeholders:
                      translation_string = temp_string
                  # 플레이스홀더 값이 부족하면 원본 문자열 일부 유지될 수 있음

        except Exception as e:
            logger.error(f"번역 문자열 포맷팅 오류 (키: {key}): {e}")
            translation_string = key # 포맷팅 실패 시 키 반환

        return translation_string

    # 호출 가능 객체로 만들기 ( _('key') 형태로 사용 가능)
    def __call__(self, key: str, **kwargs) -> str:
        return self.get_translation(key, **kwargs)

# FastAPI 의존성 함수
async def get_translator(request: Request) -> Translator:
    """요청 헤더를 기반으로 적절한 Translator 객체를 반환하는 의존성 함수"""
    # 주의: 실제 프로덕션에서는 로깅 레벨 조정 필요
    accept_language = request.headers.get('accept-language')
    locale = get_best_match_locale(accept_language)
    # logger.debug(f"Request language: {accept_language}, Selected locale: {locale}")
    return Translator(locale)

# 애플리케이션 재시작 없이 번역 리로드 (개발용)
def reload_translations():
    logger.info("번역 리로딩 중...")
    load_translations()
    logger.info("번역 리로딩 완료.") 