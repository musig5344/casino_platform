#!/usr/bin/env python
"""
카지노 플랫폼 통합 테스트 실행 스크립트
다양한 테스트 옵션을 제공하며, 테스트 보고서를 생성합니다.
"""
import os
import sys
import argparse
import subprocess
import time
import datetime
import json
import logging
from pathlib import Path

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("test_runner.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 결과 디렉토리
RESULTS_DIR = "test_results"
Path(RESULTS_DIR).mkdir(exist_ok=True)

def run_cmd(cmd, capture_output=True):
    """
    주어진 명령을 실행하고 결과를 반환합니다.
    """
    logger.info(f"실행: {' '.join(cmd)}")
    start_time = time.time()
    
    if capture_output:
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        # 실시간 출력 캡처
        output = []
        for line in iter(process.stdout.readline, ''):
            print(line, end='')
            output.append(line)
            if process.poll() is not None:
                break
        
        process.wait()
        elapsed_time = time.time() - start_time
        logger.info(f"명령 실행 완료 (소요 시간: {elapsed_time:.2f}초)")
        return process.returncode, ''.join(output)
    else:
        # 직접 표준 출력으로 출력 (실시간 보기)
        process = subprocess.run(cmd)
        elapsed_time = time.time() - start_time
        logger.info(f"명령 실행 완료 (소요 시간: {elapsed_time:.2f}초)")
        return process.returncode, ""

def generate_test_report(results_file, output_content):
    """
    테스트 결과를 기반으로 요약 레포트를 생성합니다.
    """
    # 결과 파일에서 JSON 데이터 추출 시도
    try:
        with open(results_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            json_line = next((line for line in lines if line.strip().startswith('{')), None)
            if json_line:
                data = json.loads(json_line)
                
                summary = {
                    "테스트 총 개수": data.get("summary", {}).get("total", 0),
                    "통과": data.get("summary", {}).get("passed", 0),
                    "실패": data.get("summary", {}).get("failed", 0),
                    "에러": data.get("summary", {}).get("errors", 0),
                    "스킵": data.get("summary", {}).get("skipped", 0),
                    "마커별 결과": {}
                }
                
                # 마커별 결과 수집
                for test in data.get("tests", []):
                    for marker in test.get("keywords", []):
                        if marker.startswith("test_"):
                            continue
                        if marker not in summary["마커별 결과"]:
                            summary["마커별 결과"][marker] = {"total": 0, "passed": 0, "failed": 0}
                        
                        summary["마커별 결과"][marker]["total"] += 1
                        if test.get("outcome") == "passed":
                            summary["마커별 결과"][marker]["passed"] += 1
                        else:
                            summary["마커별 결과"][marker]["failed"] += 1
                
                # 요약 파일 생성
                summary_file = os.path.join(RESULTS_DIR, f"summary_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
                with open(summary_file, 'w', encoding='utf-8') as f:
                    json.dump(summary, f, ensure_ascii=False, indent=2)
                
                logger.info(f"테스트 요약 생성: {summary_file}")
                return summary
    except Exception as e:
        logger.error(f"테스트 결과 분석 중 오류 발생: {e}")
    
    return None

def main():
    parser = argparse.ArgumentParser(description='카지노 플랫폼 통합 테스트 실행')
    
    # 일반 옵션
    parser.add_argument('--all', action='store_true', help='모든 테스트 실행')
    parser.add_argument('--unit', action='store_true', help='단위 테스트만 실행')
    parser.add_argument('--integration', action='store_true', help='통합 테스트만 실행')
    parser.add_argument('--load', action='store_true', help='부하 테스트만 실행')
    
    # 기술/기능별 테스트
    parser.add_argument('--auth', action='store_true', help='인증 관련 테스트만 실행')
    parser.add_argument('--cache', action='store_true', help='캐시 관련 테스트만 실행')
    parser.add_argument('--transaction', action='store_true', help='트랜잭션 관련 테스트만 실행')
    parser.add_argument('--error', action='store_true', help='오류 처리 테스트만 실행')
    
    # 테스트 파일/모듈 지정
    parser.add_argument('--files', nargs='+', help='특정 테스트 파일만 실행')
    parser.add_argument('--module', help='특정 테스트 모듈만 실행 (예: tests.test_wallet)')
    
    # 테스트 실행 옵션
    parser.add_argument('--parallel', '-p', action='store_true', help='병렬 테스트 실행')
    parser.add_argument('--verbose', '-v', action='store_true', help='자세한 출력')
    parser.add_argument('--quiet', '-q', action='store_true', help='간략한 출력')
    parser.add_argument('--skip-slow', action='store_true', help='느린 테스트 건너뛰기')
    
    # 보고서 옵션
    parser.add_argument('--html', action='store_true', help='HTML 보고서 생성')
    parser.add_argument('--json', action='store_true', help='JSON 보고서 생성')
    
    args = parser.parse_args()
    
    # 타임스탬프
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # 기본 pytest 명령 구성
    python_cmd = [sys.executable]
    pytest_cmd = ['-m', 'pytest']
    
    # 출력 상세도 설정
    if args.verbose:
        pytest_cmd.append('-v')
    if args.quiet:
        pytest_cmd.append('-q')
    
    # 마커 설정
    markers = []
    if args.unit:
        markers.append("not integration and not load")
    if args.integration:
        markers.append("integration")
    if args.load:
        markers.append("load")
    if args.auth:
        markers.append("auth")
    if args.cache:
        markers.append("cache")
    if args.transaction:
        markers.append("transaction")
    if args.error:
        markers.append("error")
    if args.skip_slow:
        markers.append("not slow")
    
    # 마커 조합
    if markers:
        marker_expr = " and ".join(f"({m})" for m in markers)
        pytest_cmd.extend(['-m', marker_expr])
    
    # 병렬 처리
    if args.parallel:
        pytest_cmd.extend(['-xvs', '-n', 'auto'])
    
    # 보고서 형식
    report_files = []
    if args.html:
        html_report = os.path.join(RESULTS_DIR, f'report_{timestamp}.html')
        pytest_cmd.extend(['--html', html_report, '--self-contained-html'])
        report_files.append(html_report)
    
    if args.json:
        json_report = os.path.join(RESULTS_DIR, f'report_{timestamp}.json')
        pytest_cmd.extend(['--json', json_report])
        report_files.append(json_report)
    
    # 모든 테스트 로그를 캡처할 출력 파일
    output_file = os.path.join(RESULTS_DIR, f'output_{timestamp}.txt')
    
    # 특정 파일 또는 모듈 지정
    if args.files:
        pytest_cmd.extend(args.files)
    elif args.module:
        pytest_cmd.append(args.module)
    else:
        # 기본 테스트 디렉토리
        pytest_cmd.append("tests/")
    
    # 명령 실행
    cmd = python_cmd + pytest_cmd
    return_code, output = run_cmd(cmd)
    
    # 결과 저장
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(output)
    
    # 보고서 생성 (JSON이 지정된 경우)
    summary = None
    if args.json and os.path.exists(json_report):
        summary = generate_test_report(json_report, output)
    
    # 결과 출력
    print("\n" + "="*50)
    print(f"테스트 실행 완료 | 반환 코드: {return_code}")
    
    if summary:
        print(f"\n테스트 요약:")
        print(f"총 테스트: {summary['테스트 총 개수']}")
        print(f"통과: {summary['통과']}")
        print(f"실패: {summary['실패']}")
        print(f"에러: {summary['에러']}")
        print(f"스킵: {summary['스킵']}")
        
        # 마커별 결과 요약
        if summary["마커별 결과"]:
            print("\n마커별 결과:")
            for marker, result in summary["마커별 결과"].items():
                print(f"{marker}: {result['passed']}/{result['total']} 통과 ({result['passed']/result['total']*100:.1f}%)")
    
    print("\n생성된 파일:")
    print(f"- 출력 로그: {output_file}")
    for report in report_files:
        print(f"- 보고서: {report}")
    print("="*50)
    
    return return_code

if __name__ == '__main__':
    sys.exit(main()) 