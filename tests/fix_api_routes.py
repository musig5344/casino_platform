#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
API 경로 일관성 문제 해결 스크립트

이 스크립트는 다음을 수행합니다:
1. 기존 API 경로 테스트
2. 메인 라우터 분석 및 수정 제안
3. API 경로 일관성 확인
"""

import os
import re
import sys
import logging
from datetime import datetime
import argparse
import requests

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("API_ROUTE_FIX")

# API 설정
BASE_URL = "http://localhost:8000"
ADMIN_HEADERS = {"X-Admin": "true", "Content-Type": "application/json"}

class APIRouteFixer:
    def __init__(self):
        """초기화"""
        self.api_endpoints = {
            "/": None,
            "/aml/alerts": None,
            "/api/aml/alerts": None,
            "/aml/analyze-transaction/123": None,
            "/api/aml/analyze-transaction/123": None,
            "/aml/player/test_player_1/risk-profile": None,
            "/api/aml/player/test_player_1/risk-profile": None
        }
        logger.info("API 경로 문제 해결 도구 초기화 완료")

    def backup_file(self, filepath):
        """파일 백업"""
        if os.path.exists(filepath):
            backup_path = f"{filepath}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
            try:
                with open(filepath, 'r', encoding='utf-8') as src, open(backup_path, 'w', encoding='utf-8') as dst:
                    dst.write(src.read())
                logger.info(f"파일 백업 완료: {backup_path}")
                return True
            except Exception as e:
                logger.error(f"파일 백업 중 오류: {str(e)}")
                return False
        else:
            logger.error(f"파일이 존재하지 않음: {filepath}")
            return False

    def test_api_endpoints(self):
        """API 엔드포인트 경로 테스트"""
        logger.info("API 엔드포인트 경로 테스트 시작...")
        
        for endpoint in self.api_endpoints.keys():
            try:
                if "transaction" in endpoint and endpoint.endswith("/123"):
                    # POST 요청이 필요한 엔드포인트
                    response = requests.post(
                        f"{BASE_URL}{endpoint}",
                        headers=ADMIN_HEADERS
                    )
                else:
                    # GET 요청이 필요한 엔드포인트
                    response = requests.get(
                        f"{BASE_URL}{endpoint}",
                        headers=ADMIN_HEADERS
                    )
                
                self.api_endpoints[endpoint] = response.status_code
                logger.info(f"엔드포인트 {endpoint}: 상태 코드 {response.status_code}")
                
                # 404가 아닌 경우는 엔드포인트가 존재하는 것 (401, 403 등은 인증 문제일 수 있음)
                if response.status_code != 404:
                    logger.info(f"엔드포인트 {endpoint}가 존재합니다. 상태 코드: {response.status_code}")
                else:
                    logger.warning(f"엔드포인트 {endpoint}가 존재하지 않습니다.")
            except Exception as e:
                logger.error(f"엔드포인트 {endpoint} 테스트 중 오류: {str(e)}")
                self.api_endpoints[endpoint] = "오류"
                
        logger.info("API 엔드포인트 테스트 완료")
        return self.api_endpoints

    def analyze_main_router(self, main_file_path):
        """메인 라우터 파일 분석"""
        logger.info(f"메인 라우터 파일 분석 시작: {main_file_path}")
        
        if not os.path.exists(main_file_path):
            logger.error(f"파일이 존재하지 않음: {main_file_path}")
            return None
        
        router_config = {
            "routers": [],
            "prefixes": {},
            "issues": []
        }
        
        try:
            with open(main_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 라우터 등록 부분 확인
            router_includes = re.findall(r'app\.include_router\(([^)]+)\)', content)
            for router in router_includes:
                router_name = router.strip()
                router_config["routers"].append(router_name)
                logger.info(f"라우터 등록 발견: {router_name}")
            
            # API 경로 접두사 확인 문제
            if 'aml.router' in content:
                logger.info("AML 라우터 등록 발견")
                if '/api/aml' in content:
                    logger.warning("잘못된 라우터 접두사 '/api/aml'가 발견됨")
                    router_config["issues"].append("AML 라우터 접두사 불일치 문제")
            
            return router_config
        except Exception as e:
            logger.error(f"메인 라우터 분석 중 오류: {str(e)}")
            return None

    def analyze_aml_router(self, aml_file_path):
        """AML 라우터 파일 분석"""
        logger.info(f"AML 라우터 파일 분석 시작: {aml_file_path}")
        
        if not os.path.exists(aml_file_path):
            logger.error(f"파일이 존재하지 않음: {aml_file_path}")
            return None
        
        router_config = {
            "prefix": None,
            "endpoints": [],
            "issues": []
        }
        
        try:
            with open(aml_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 라우터 접두사 확인
            prefix_match = re.search(r'router\s*=\s*APIRouter\(prefix="([^"]+)"', content)
            if prefix_match:
                router_config["prefix"] = prefix_match.group(1)
                logger.info(f"AML 라우터 접두사: {router_config['prefix']}")
            
            # 엔드포인트 확인
            endpoints = re.findall(r'@router\.(get|post|put|delete)\("([^"]+)"', content)
            for method, path in endpoints:
                router_config["endpoints"].append({
                    "method": method.upper(),
                    "path": path
                })
                logger.info(f"AML 엔드포인트 발견: {method.upper()} {path}")
            
            # 문제점 검사
            if router_config["prefix"] != "/aml":
                logger.warning(f"AML 라우터 접두사가 '/aml'이 아닙니다: {router_config['prefix']}")
                router_config["issues"].append("AML 라우터 접두사 불일치")
            
            for endpoint in router_config["endpoints"]:
                if endpoint["path"].startswith("/api/"):
                    logger.warning(f"잘못된 엔드포인트 경로: {endpoint['path']}")
                    router_config["issues"].append(f"잘못된 엔드포인트 경로: {endpoint['path']}")
            
            return router_config
        except Exception as e:
            logger.error(f"AML 라우터 분석 중 오류: {str(e)}")
            return None

    def fix_main_router(self, main_file_path):
        """메인 라우터 파일 수정"""
        logger.info(f"메인 라우터 파일 수정 시작: {main_file_path}")
        
        if not self.backup_file(main_file_path):
            logger.error("파일 백업 실패. 수정을 중단합니다.")
            return False
        
        try:
            with open(main_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 수정 1: 라우터 등록 부분 확인
            modified_content = content
            
            # 수정사항이 있는 경우에만 파일 업데이트
            if modified_content != content:
                with open(main_file_path, 'w', encoding='utf-8') as f:
                    f.write(modified_content)
                logger.info(f"{main_file_path} 파일이 수정되었습니다.")
                return True
            else:
                logger.info(f"{main_file_path} 파일에 수정이 필요하지 않습니다.")
                return False
        except Exception as e:
            logger.error(f"메인 라우터 수정 중 오류: {str(e)}")
            return False

    def fix_aml_router(self, aml_file_path):
        """AML 라우터 파일 수정"""
        logger.info(f"AML 라우터 파일 수정 시작: {aml_file_path}")
        
        if not self.backup_file(aml_file_path):
            logger.error("파일 백업 실패. 수정을 중단합니다.")
            return False
        
        try:
            with open(aml_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 수정 1: 라우터 접두사 확인 및 수정
            prefix_pattern = r'router\s*=\s*APIRouter\(prefix="([^"]+)"'
            prefix_match = re.search(prefix_pattern, content)
            
            modified_content = content
            if prefix_match and prefix_match.group(1) != "/aml":
                modified_content = re.sub(
                    prefix_pattern,
                    'router = APIRouter(prefix="/aml"',
                    modified_content
                )
                logger.info("AML 라우터 접두사를 '/aml'로 수정했습니다.")
            
            # 수정 2: 엔드포인트 경로 수정
            endpoints_pattern = r'@router\.(get|post|put|delete)\("(/api/[^"]+)"'
            endpoints_match = re.findall(endpoints_pattern, modified_content)
            
            for method, path in endpoints_match:
                corrected_path = path.replace("/api", "")
                modified_content = modified_content.replace(
                    f'@router.{method}("{path}"',
                    f'@router.{method}("{corrected_path}"'
                )
                logger.info(f"엔드포인트 경로 수정: {path} -> {corrected_path}")
            
            # 수정사항이 있는 경우에만 파일 업데이트
            if modified_content != content:
                with open(aml_file_path, 'w', encoding='utf-8') as f:
                    f.write(modified_content)
                logger.info(f"{aml_file_path} 파일이 수정되었습니다.")
                return True
            else:
                logger.info(f"{aml_file_path} 파일에 수정이 필요하지 않습니다.")
                return False
        except Exception as e:
            logger.error(f"AML 라우터 수정 중 오류: {str(e)}")
            return False

    def generate_report(self):
        """API 경로 분석 보고서 생성"""
        logger.info("API 경로 분석 보고서 생성 중...")
        
        report = "# API 경로 분석 보고서\n\n"
        report += f"생성 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        report += "## 엔드포인트 테스트 결과\n\n"
        report += "| 엔드포인트 | 상태 코드 | 상태 |\n"
        report += "| --- | --- | --- |\n"
        
        for endpoint, status_code in self.api_endpoints.items():
            status = "✅ 정상" if status_code and status_code != 404 else "❌ 오류"
            report += f"| {endpoint} | {status_code} | {status} |\n"
        
        report += "\n## 문제점 및 해결 방안\n\n"
        
        # 문제점 분석
        prefix_issues = []
        missing_routes = []
        
        for endpoint, status_code in self.api_endpoints.items():
            if endpoint.startswith("/api/aml") and status_code == 404:
                prefix_issues.append(endpoint)
            elif endpoint.startswith("/aml") and status_code == 404 and "transaction" in endpoint:
                missing_routes.append(endpoint)
        
        if prefix_issues:
            report += "### 1. 라우터 접두사 불일치 문제\n\n"
            report += "다음 엔드포인트에 접두사 불일치 문제가 있습니다:\n\n"
            for endpoint in prefix_issues:
                report += f"- {endpoint}\n"
            
            report += "\n**해결 방안:**\n\n"
            report += "1. 라우터 접두사를 '/aml'로 통일\n"
            report += "2. main.py에서 라우터 등록 방식 확인\n\n"
        
        if missing_routes:
            report += "### 2. 트랜잭션 분석 엔드포인트 문제\n\n"
            report += "다음 트랜잭션 분석 엔드포인트에 접근할 수 없습니다:\n\n"
            for endpoint in missing_routes:
                report += f"- {endpoint}\n"
            
            report += "\n**해결 방안:**\n\n"
            report += "1. 트랜잭션 ID 조회 로직 개선\n"
            report += "2. 오류 처리 및 로깅 강화\n\n"
        
        report += "## 향후 개선 사항\n\n"
        report += "1. 경로 자동 유효성 검사 도구 개발\n"
        report += "2. API 경로 문서화 자동화\n"
        report += "3. API 경로 일관성을 위한 미들웨어 추가\n"
        
        logger.info("API 경로 분석 보고서 생성 완료")
        
        # 보고서 저장
        report_file = "api_route_analysis_report.md"
        try:
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"보고서가 {report_file}에 저장되었습니다.")
        except Exception as e:
            logger.error(f"보고서 저장 중 오류: {str(e)}")
        
        return report

def main():
    parser = argparse.ArgumentParser(description="API 경로 일관성 문제 해결 도구")
    parser.add_argument("--main-file", default="backend/main.py", help="메인 라우터 파일 경로")
    parser.add_argument("--aml-file", default="backend/api/aml.py", help="AML 라우터 파일 경로")
    parser.add_argument("--fix", action="store_true", help="파일 자동 수정 활성화")
    args = parser.parse_args()
    
    logger.info("API 경로 일관성 문제 해결 시작...")
    fixer = APIRouteFixer()
    
    # 1. API 엔드포인트 테스트
    endpoints = fixer.test_api_endpoints()
    
    # 2. 라우터 분석
    main_router = fixer.analyze_main_router(args.main_file)
    aml_router = fixer.analyze_aml_router(args.aml_file)
    
    # 3. 라우터 수정 (--fix 옵션이 있는 경우에만)
    if args.fix:
        if main_router and "issues" in main_router and main_router["issues"]:
            logger.info("메인 라우터 수정 시작...")
            fixer.fix_main_router(args.main_file)
        
        if aml_router and "issues" in aml_router and aml_router["issues"]:
            logger.info("AML 라우터 수정 시작...")
            fixer.fix_aml_router(args.aml_file)
    
    # 4. 보고서 생성
    report = fixer.generate_report()
    
    logger.info("API 경로 일관성 문제 해결 종료")

if __name__ == "__main__":
    main() 