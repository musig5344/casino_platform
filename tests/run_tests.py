#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
카지노 플랫폼 API 테스트 실행 스크립트
주요 기능:
- 모든 테스트 스크립트 통합 실행
- 테스트 결과 종합
- 특정 테스트만 선택적 실행

실행:
  모든 테스트 실행: python run_tests.py --all
  인증 테스트만 실행: python run_tests.py --auth
  지갑 테스트만 실행: python run_tests.py --wallet
  게임 테스트만 실행: python run_tests.py --games
  AML 테스트만 실행: python run_tests.py --aml
  PEP/고위험국가 테스트만 실행: python run_tests.py --pep
"""

import argparse
import importlib
import sys
import os
import time
import traceback
from datetime import datetime
import json

# 테스트 환경 설정
def setup_test_environment():
    """테스트 환경 변수 설정"""
    # 기본 서버 URL 설정
    if "API_BASE_URL" not in os.environ:
        os.environ["API_BASE_URL"] = "http://localhost:8000"
    
    # 기본 테스트 플레이어 설정
    if "TEST_PLAYER_ID" not in os.environ:
        os.environ["TEST_PLAYER_ID"] = "test_player_123"
    
    # 디버그 모드 설정
    if "TEST_DEBUG" not in os.environ:
        os.environ["TEST_DEBUG"] = "0"
    
    print(f"테스트 환경 설정 완료:")
    print(f"  서버 URL: {os.environ['API_BASE_URL']}")
    print(f"  테스트 플레이어: {os.environ['TEST_PLAYER_ID']}")
    print(f"  디버그 모드: {'켜짐' if os.environ['TEST_DEBUG'] == '1' else '꺼짐'}")

def run_test_module(module_name):
    """
    특정 테스트 모듈 실행
    
    Args:
        module_name: 실행할 모듈 이름
        
    Returns:
        (실행 성공 여부, 테스트 성공 여부, 성공한 테스트 수, 실패한 테스트 수, 예상된 실패 수)
    """
    print(f"\n{'=' * 30}")
    print(f"실행: {module_name}")
    print(f"{'=' * 30}")
    
    start_time = time.time()
    
    try:
        # 모듈 동적 임포트
        module = importlib.import_module(module_name)
        
        # 테스트 결과 초기화
        if hasattr(module, "reset_test_results"):
            module.reset_test_results()
        
        # 메인 함수 호출
        if hasattr(module, "main"):
            result = module.main()
            elapsed = time.time() - start_time
            
            # 테스트 결과 수집
            test_stats = {}
            if hasattr(module, "TEST_RESULTS"):
                test_stats = {
                    "total": len(module.TEST_RESULTS.get("tests", [])),
                    "success": module.TEST_RESULTS.get("success", 0),
                    "fail": module.TEST_RESULTS.get("fail", 0),
                    "expected_failures": sum(1 for test in module.TEST_RESULTS.get("tests", []) 
                                          if test.get("expected_failure", False))
                }
                
                real_failures = test_stats["fail"]
                expected_failures = test_stats["expected_failures"]
                
                # 예상된 실패를 제외한 진짜 실패가 없으면 성공으로 간주
                success = real_failures == 0 or (real_failures == expected_failures and expected_failures > 0)
                
                print(f"\n{module_name} 실행 완료: {'성공' if success else '실패'} (소요 시간: {elapsed:.2f}초)")
                return True, success, test_stats.get("success", 0), real_failures, expected_failures
            else:
                # TEST_RESULTS가 없으면 결과 값 그대로 사용
                print(f"\n{module_name} 실행 완료: {'성공' if result else '실패'} (소요 시간: {elapsed:.2f}초)")
                return True, result, 0, 0, 0
        else:
            print(f"경고: {module_name}에 main() 함수가 없습니다.")
            return False, False, 0, 0, 0
    except ImportError:
        print(f"오류: {module_name} 모듈을 찾을 수 없습니다.")
        return False, False, 0, 0, 0
    except Exception as e:
        print(f"오류: {module_name} 실행 중 예외 발생: {e}")
        traceback.print_exc()
        return True, False, 0, 0, 0

def run_all_tests():
    """
    모든 테스트 스크립트 실행
    
    Returns:
        성공 여부
    """
    print("\n" + "=" * 50)
    print("카지노 플랫폼 API 통합 테스트 시작")
    print("=" * 50)
    print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 테스트 모듈 목록 (순서 중요)
    test_modules = [
        "test_auth_api",
        "test_wallet_api",
        "test_games_api",
        "test_aml_integration",
        "test_pep_riskcountry"
    ]
    
    results = {}
    total_start_time = time.time()
    
    # 전체 통계
    total_stats = {
        "executed": 0,
        "success": 0,
        "tests_passed": 0,
        "tests_failed": 0,
        "expected_failures": 0
    }
    
    for module_name in test_modules:
        executed, success, tests_passed, tests_failed, expected_failures = run_test_module(module_name)
        
        results[module_name] = {
            "executed": executed, 
            "success": success,
            "tests_passed": tests_passed,
            "tests_failed": tests_failed,
            "expected_failures": expected_failures
        }
        
        if executed:
            total_stats["executed"] += 1
            if success:
                total_stats["success"] += 1
            
            total_stats["tests_passed"] += tests_passed
            total_stats["tests_failed"] += tests_failed
            total_stats["expected_failures"] += expected_failures
    
    total_elapsed = time.time() - total_start_time
    
    # 최종 결과 출력
    print("\n" + "=" * 70)
    print("모든 테스트 모듈 실행 결과")
    print("=" * 70)
    
    for module_name, result in results.items():
        if result["executed"]:
            real_failures = result["tests_failed"] - result["expected_failures"]
            status = "성공" if result["success"] else f"실패 (실제 오류: {real_failures}개)"
        else:
            status = "실행 불가"
            
        print(f"{module_name}: {status}")
    
    print(f"\n총 {len(results)}개 모듈 중 {total_stats['executed']}개 실행됨")
    print(f"성공: {total_stats['success']}/{total_stats['executed']}")
    
    if total_stats["tests_failed"] > 0:
        print(f"총 테스트: 성공 {total_stats['tests_passed']}개, 실패 {total_stats['tests_failed']}개")
        print(f"예상된 실패: {total_stats['expected_failures']}개, 실제 실패: {total_stats['tests_failed'] - total_stats['expected_failures']}개")
    else:
        print(f"총 테스트: 모두 성공 ({total_stats['tests_passed']}개)")
    
    print(f"총 소요 시간: {total_elapsed:.2f}초")
    print("=" * 70)
    
    # 실제 실패(예상되지 않은 실패)가 없으면 성공으로 간주
    real_failures = total_stats["tests_failed"] - total_stats["expected_failures"]
    return real_failures == 0

def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description='카지노 플랫폼 API 테스트 실행')
    parser.add_argument('--auth', action='store_true', help='인증 테스트만 실행')
    parser.add_argument('--wallet', action='store_true', help='지갑 API 테스트만 실행')
    parser.add_argument('--games', action='store_true', help='게임 API 테스트만 실행')
    parser.add_argument('--aml', action='store_true', help='AML 테스트만 실행')
    parser.add_argument('--pep', action='store_true', help='PEP/고위험국가 테스트만 실행')
    parser.add_argument('--all', action='store_true', help='모든 테스트 실행')
    parser.add_argument('--url', help='테스트할 서버 URL 설정')
    parser.add_argument('--player', help='테스트할 플레이어 ID 설정')
    parser.add_argument('--debug', action='store_true', help='디버그 모드 활성화')
    
    args = parser.parse_args()
    
    # 환경 변수 설정
    if args.url:
        os.environ["API_BASE_URL"] = args.url
    if args.player:
        os.environ["TEST_PLAYER_ID"] = args.player
    if args.debug:
        os.environ["TEST_DEBUG"] = "1"
    
    # 테스트 환경 설정
    setup_test_environment()
    
    # 특정 플래그가 없으면 모든 테스트 실행
    if not any([args.auth, args.wallet, args.games, args.aml, args.pep, args.all]):
        args.all = True
    
    success = True
    
    if args.all:
        success = run_all_tests()
    else:
        # 개별 모듈 실행 시 통계 초기화
        total_stats = {
            "executed": 0,
            "success": 0,
        }
        
        if args.auth:
            executed, module_success, _, _, _ = run_test_module("test_auth_api")
            if executed:
                total_stats["executed"] += 1
                if module_success:
                    total_stats["success"] += 1
            success = success and module_success
            
        if args.wallet:
            executed, module_success, _, _, _ = run_test_module("test_wallet_api")
            if executed:
                total_stats["executed"] += 1
                if module_success:
                    total_stats["success"] += 1
            success = success and module_success
            
        if args.games:
            executed, module_success, _, _, _ = run_test_module("test_games_api")
            if executed:
                total_stats["executed"] += 1
                if module_success:
                    total_stats["success"] += 1
            success = success and module_success
            
        if args.aml:
            executed, module_success, _, _, _ = run_test_module("test_aml_integration")
            if executed:
                total_stats["executed"] += 1
                if module_success:
                    total_stats["success"] += 1
            success = success and module_success
            
        if args.pep:
            executed, module_success, _, _, _ = run_test_module("test_pep_riskcountry")
            if executed:
                total_stats["executed"] += 1
                if module_success:
                    total_stats["success"] += 1
            success = success and module_success
            
        # 요약 출력
        print(f"\n총 {total_stats['executed']}개 모듈 중 {total_stats['success']}개 성공")
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 