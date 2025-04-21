import boto3
import json
import logging
import time
from typing import Dict, Any, Optional, List, Union
from botocore.exceptions import ClientError, NoCredentialsError
from functools import wraps
from concurrent.futures import ThreadPoolExecutor

# 로깅 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 보안 자격 증명 환경변수에서 로드
# AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION 환경변수 사용

def retry_aws_operation(max_retries=3, delay=2):
    """AWS 작업 재시도 데코레이터"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (ClientError, NoCredentialsError) as e:
                    last_exception = e
                    # Throttling 오류인 경우 더 긴 대기 시간 적용
                    if hasattr(e, 'response') and e.response.get('Error', {}).get('Code') in ['Throttling', 'ThrottlingException']:
                        wait_time = delay * (2 ** attempt)  # 지수 백오프
                    else:
                        wait_time = delay
                    logger.warning(f"AWS 작업 실패, {wait_time}초 후 재시도 ({attempt+1}/{max_retries}): {str(e)}")
                    time.sleep(wait_time)
            raise last_exception
        return wrapper
    return decorator

class AWSMediaLiveManager:
    """AWS MediaLive 서비스와 통합하여 AI 딜러 스트림을 관리하는 클래스"""
    
    def __init__(self, region: str = "ap-northeast-2", max_workers: int = 10):
        """
        AWS MediaLive 클라이언트 초기화
        
        Args:
            region: AWS 리전 이름
            max_workers: 병렬 작업을 위한 최대 워커 수
        """
        # AWS 서비스 클라이언트 초기화
        self.region = region
        self.medialive_client = boto3.client('medialive', region_name=region)
        self.mediapackage_client = boto3.client('mediapackage', region_name=region)
        self.cloudwatch_client = boto3.client('cloudwatch', region_name=region)
        
        # 병렬 작업 관리
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
        # 캐시 및 세션 관리
        self.channel_cache = {}
        self.input_cache = {}
        self.endpoint_cache = {}
        
        logger.info(f"AWS MediaLive 매니저 초기화 완료 (리전: {region})")
        
    @retry_aws_operation(max_retries=3, delay=2)
    def create_input(self, name: str, input_type: str, sources: List[Dict[str, str]]) -> str:
        """
        MediaLive 입력 생성
        
        Args:
            name: 입력 이름
            input_type: 입력 타입 (URL_PULL, RTMP_PUSH 등)
            sources: 입력 소스 목록
            
        Returns:
            생성된 입력의 ID
        """
        try:
            # 이미 존재하는 동일 이름의 입력 확인
            existing_inputs = self.list_inputs_by_name(name)
            if existing_inputs:
                input_id = existing_inputs[0]['Id']
                logger.info(f"기존 MediaLive 입력 사용: {input_id}")
                return input_id
            
            # 입력 정보 초기화
            input_request = {
                'Name': name,
                'Type': input_type,
                'Sources': sources
            }
            
            # 입력 타입에 따른 추가 설정
            if input_type == 'RTMP_PUSH':
                input_request['Destinations'] = [
                    {'StreamName': f"{name}_primary"},
                    {'StreamName': f"{name}_secondary"}
                ]
            
            # 입력 보안 그룹 설정
            input_request['InputSecurityGroups'] = []
            
            # 입력 생성 요청
            response = self.medialive_client.create_input(**input_request)
            input_id = response['Input']['Id']
            
            # 입력 정보 캐싱
            self.input_cache[input_id] = response['Input']
            
            # CloudWatch에 메트릭 전송
            self._put_custom_metric('InputCreated', 1, 'Count')
            
            logger.info(f"MediaLive 입력 생성 완료: {input_id} (타입: {input_type})")
            return input_id
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ConflictException':
                logger.warning(f"동일한 이름의 입력이 이미 존재함: {name}")
                existing_inputs = self.list_inputs_by_name(name)
                if existing_inputs:
                    return existing_inputs[0]['Id']
            logger.error(f"MediaLive 입력 생성 실패: {str(e)}")
            raise
    
    @retry_aws_operation()
    def list_inputs_by_name(self, name: str) -> List[Dict[str, Any]]:
        """
        이름으로 MediaLive 입력 검색
        
        Args:
            name: 입력 이름
            
        Returns:
            입력 목록
        """
        response = self.medialive_client.list_inputs()
        return [inp for inp in response['Inputs'] if inp['Name'] == name]
    
    @retry_aws_operation()
    def create_mediapackage_channel(self, channel_id: str) -> Dict[str, Any]:
        """
        MediaPackage 채널 생성
        
        Args:
            channel_id: 채널 ID
            
        Returns:
            생성된 채널 정보 및 엔드포인트 정보
        """
        try:
            # 기존 채널 확인
            try:
                existing_channel = self.mediapackage_client.describe_channel(Id=channel_id)
                logger.info(f"기존 MediaPackage 채널 사용: {channel_id}")
                
                # 기존 엔드포인트 확인
                endpoints = self.mediapackage_client.list_origin_endpoints(ChannelId=channel_id)
                if endpoints['OriginEndpoints']:
                    hls_endpoint = next((endpoint for endpoint in endpoints['OriginEndpoints'] 
                                         if endpoint['Id'] == f"{channel_id}-hls"), None)
                    if hls_endpoint:
                        return {
                            "channel": existing_channel['Channel'],
                            "hls_endpoint": hls_endpoint['Url']
                        }
            except ClientError:
                pass
            
            # 새 채널 생성
            response = self.mediapackage_client.create_channel(
                Id=channel_id, 
                Description=f"AI Dealer Channel {channel_id}"
            )
            
            # HLS 엔드포인트 설정
            hls_package = {
                "SegmentDurationSeconds": 2,
                "PlaylistWindowSeconds": 60,
                "PlaylistType": "EVENT",
                "AdMarkers": "NONE",
                "IncludeIframeOnlyStream": False,
                "UseAudioRenditionGroup": False,
                # 저지연 설정 추가
                "StreamSelection": {
                    "MinVideoBitsPerSecond": 0,
                    "MaxVideoBitsPerSecond": 2147483647,
                    "StreamOrder": "ORIGINAL"
                }
            }
            
            # CMAF 엔드포인트 생성
            cmaf_response = self.mediapackage_client.create_origin_endpoint(
                ChannelId=channel_id,
                Id=f"{channel_id}-cmaf",
                ManifestName="index",
                CmafPackage={
                    "SegmentDurationSeconds": 2,
                    "SegmentPrefix": f"{channel_id}-cmaf",
                    "HlsManifests": [{
                        "Id": "HLS",
                        "ManifestName": "index",
                        "AdMarkers": "NONE"
                    }]
                }
            )
            
            # HLS 엔드포인트 생성
            endpoint_response = self.mediapackage_client.create_origin_endpoint(
                ChannelId=channel_id,
                Id=f"{channel_id}-hls",
                ManifestName="index",
                StreamSelection={
                    "MinVideoBitsPerSecond": 0, 
                    "MaxVideoBitsPerSecond": 2147483647,
                    "StreamOrder": "ORIGINAL"
                },
                HlsPackage=hls_package
            )
            
            # DASH 엔드포인트 생성
            dash_response = self.mediapackage_client.create_origin_endpoint(
                ChannelId=channel_id,
                Id=f"{channel_id}-dash",
                ManifestName="index",
                DashPackage={
                    "SegmentDurationSeconds": 2,
                    "ManifestWindowSeconds": 60,
                    "Profile": "NONE"
                }
            )
            
            # 응답 조합
            channel_info = {
                "channel": response["Channel"],
                "hls_endpoint": endpoint_response["Url"],
                "cmaf_endpoint": cmaf_response["Url"],
                "dash_endpoint": dash_response["Url"]
            }
            
            # 채널 정보 캐싱
            self.endpoint_cache[channel_id] = {
                "hls": endpoint_response["Url"],
                "cmaf": cmaf_response["Url"],
                "dash": dash_response["Url"]
            }
            
            # CloudWatch에 메트릭 전송
            self._put_custom_metric('MediaPackageChannelCreated', 1, 'Count')
            
            logger.info(f"MediaPackage 채널 및 엔드포인트 생성 완료: {channel_id}")
            return channel_info
        except ClientError as e:
            logger.error(f"MediaPackage 채널 생성 실패: {str(e)}")
            raise
    
    @retry_aws_operation()
    def create_channel(self, 
                      channel_name: str, 
                      input_id: str, 
                      destination_urls: List[str],
                      output_group_settings: Dict[str, Any]) -> str:
        """
        MediaLive 채널 생성
        
        Args:
            channel_name: 채널 이름
            input_id: 입력 ID
            destination_urls: 출력 대상 URL 목록
            output_group_settings: 출력 그룹 설정
            
        Returns:
            생성된 채널의 ID
        """
        try:
            # 기존 채널 확인
            existing_channels = self.list_channels_by_name(channel_name)
            if existing_channels:
                channel_id = existing_channels[0]['Id']
                logger.info(f"기존 MediaLive 채널 사용: {channel_id}")
                return channel_id
            
            # 대상 설정
            destinations = []
            for i, url in enumerate(destination_urls):
                destinations.append({
                    'Id': f'destination_{i}',
                    'Settings': [{'Url': url}]
                })
            
            # 고품질 및 저품질 비디오 설정
            video_descriptions = [
                # 고품질 (HD)
                {
                    'Name': 'video_1080p',
                    'ResolutionName': 'HD',
                    'Width': 1920,
                    'Height': 1080,
                    'CodecSettings': {
                        'H264Settings': {
                            'Profile': 'HIGH',
                            'RateControlMode': 'CBR',
                            'Bitrate': 5000000,
                            'FramerateDenominator': 1,
                            'FramerateNumerator': 30,
                            'GopSize': 60,
                            'GopClosedCadence': 1,
                            'AdaptiveQuantization': 'HIGH',
                            'EntropyEncoding': 'CABAC',
                            'FixedAfd': 'AFD_16_9',
                            'FlickerAq': 'ENABLED',
                            'ForceFieldPictures': 'DISABLED',
                            'GopBReference': 'ENABLED',
                            'LookAheadRateControl': 'HIGH',
                            'NumRefFrames': 3,
                            'ParControl': 'INITIALIZE_FROM_SOURCE',
                            'QualityLevel': 'ENHANCED_QUALITY',
                            'ScanType': 'PROGRESSIVE',
                            'SceneChangeDetect': 'ENABLED',
                            'TemporalAq': 'ENABLED',
                            'TimecodeInsertion': 'DISABLED'
                        }
                    }
                },
                # 중간 품질 (SD)
                {
                    'Name': 'video_720p',
                    'ResolutionName': 'SD',
                    'Width': 1280,
                    'Height': 720,
                    'CodecSettings': {
                        'H264Settings': {
                            'Profile': 'MAIN',
                            'RateControlMode': 'CBR',
                            'Bitrate': 2500000,
                            'FramerateDenominator': 1,
                            'FramerateNumerator': 30,
                            'GopSize': 60,
                            'AdaptiveQuantization': 'HIGH',
                            'GopBReference': 'ENABLED',
                            'LookAheadRateControl': 'HIGH',
                            'ScanType': 'PROGRESSIVE',
                            'SceneChangeDetect': 'ENABLED',
                            'TemporalAq': 'ENABLED'
                        }
                    }
                },
                # 저품질 (모바일)
                {
                    'Name': 'video_480p',
                    'ResolutionName': 'SD',
                    'Width': 854,
                    'Height': 480,
                    'CodecSettings': {
                        'H264Settings': {
                            'Profile': 'MAIN',
                            'RateControlMode': 'CBR',
                            'Bitrate': 1200000,
                            'FramerateDenominator': 1,
                            'FramerateNumerator': 30,
                            'GopSize': 60,
                            'AdaptiveQuantization': 'HIGH',
                            'ScanType': 'PROGRESSIVE'
                        }
                    }
                }
            ]
            
            # 오디오 설정
            audio_descriptions = [
                {
                    'Name': 'audio_aac',
                    'CodecSettings': {
                        'AacSettings': {
                            'Profile': 'LC',
                            'RateControlMode': 'CBR',
                            'Bitrate': 192000,
                            'SampleRate': 48000,
                            'InputType': 'NORMAL'
                        }
                    }
                }
            ]
            
            # 인코더 설정 통합
            encoder_settings = {
                'VideoDescriptions': video_descriptions,
                'AudioDescriptions': audio_descriptions,
                'OutputGroups': [output_group_settings]
            }
            
            # 채널 생성 요청
            response = self.medialive_client.create_channel(
                Name=channel_name,
                RoleArn='arn:aws:iam::123456789012:role/MediaLiveAccessRole',  # 실제 사용 시 올바른 IAM 역할 ARN으로 변경 필요
                InputAttachments=[{'InputId': input_id}],
                Destinations=destinations,
                EncoderSettings=encoder_settings,
                InputSpecification={
                    'Codec': 'AVC',
                    'Resolution': 'HD',
                    'MaximumBitrate': 'MAX_20_MBPS'
                },
                LogLevel='INFO'
            )
            
            channel_id = response['Channel']['Id']
            
            # 채널 정보 캐싱
            self.channel_cache[channel_id] = response['Channel']
            
            # CloudWatch에 메트릭 전송
            self._put_custom_metric('MediaLiveChannelCreated', 1, 'Count')
            
            logger.info(f"MediaLive 채널 생성 완료: {channel_id}")
            return channel_id
        except ClientError as e:
            logger.error(f"MediaLive 채널 생성 실패: {str(e)}")
            raise
    
    @retry_aws_operation()
    def list_channels_by_name(self, channel_name: str) -> List[Dict[str, Any]]:
        """
        이름으로 MediaLive 채널 검색
        
        Args:
            channel_name: 채널 이름
            
        Returns:
            채널 목록
        """
        response = self.medialive_client.list_channels()
        return [channel for channel in response['Channels'] if channel['Name'] == channel_name]
    
    @retry_aws_operation()
    def start_channel(self, channel_id: str) -> None:
        """
        MediaLive 채널 시작
        
        Args:
            channel_id: 채널 ID
        """
        try:
            # 채널 상태 확인
            channel_info = self.describe_channel(channel_id)
            current_state = channel_info['State']
            
            if current_state == 'RUNNING':
                logger.info(f"MediaLive 채널 이미 실행 중: {channel_id}")
                return
            
            if current_state == 'STARTING':
                logger.info(f"MediaLive 채널 시작 진행 중: {channel_id}")
                return
            
            # 채널 시작
            self.medialive_client.start_channel(ChannelId=channel_id)
            
            # CloudWatch에 메트릭 전송
            self._put_custom_metric('MediaLiveChannelStarted', 1, 'Count')
            
            logger.info(f"MediaLive 채널 시작 요청 완료: {channel_id}")
            
            # 최대 5분 동안 채널 상태 확인
            start_time = time.time()
            while time.time() - start_time < 300:  # 5분 타임아웃
                time.sleep(10)  # 10초 간격으로 확인
                channel_info = self.describe_channel(channel_id)
                if channel_info['State'] == 'RUNNING':
                    logger.info(f"MediaLive 채널 시작됨: {channel_id}")
                    return
                elif channel_info['State'] == 'ERROR':
                    error_message = "채널이 에러 상태입니다"
                    logger.error(f"MediaLive 채널 시작 실패: {channel_id} - {error_message}")
                    raise Exception(error_message)
            
            logger.warning(f"MediaLive 채널 시작 타임아웃: {channel_id}")
        except ClientError as e:
            logger.error(f"MediaLive 채널 시작 실패: {str(e)}")
            raise
    
    @retry_aws_operation()
    def stop_channel(self, channel_id: str) -> None:
        """
        MediaLive 채널 정지
        
        Args:
            channel_id: 채널 ID
        """
        try:
            # 채널 상태 확인
            try:
                channel_info = self.describe_channel(channel_id)
                current_state = channel_info['State']
                
                if current_state in ['IDLE', 'STOPPED']:
                    logger.info(f"MediaLive 채널 이미 정지됨: {channel_id}")
                    return
                
                if current_state == 'STOPPING':
                    logger.info(f"MediaLive 채널 정지 진행 중: {channel_id}")
                    return
            except ClientError as e:
                if e.response['Error']['Code'] == 'NotFoundException':
                    logger.warning(f"MediaLive 채널을 찾을 수 없음: {channel_id}")
                    return
                raise
            
            # 채널 정지
            self.medialive_client.stop_channel(ChannelId=channel_id)
            
            # CloudWatch에 메트릭 전송
            self._put_custom_metric('MediaLiveChannelStopped', 1, 'Count')
            
            logger.info(f"MediaLive 채널 정지 요청 완료: {channel_id}")
        except ClientError as e:
            logger.error(f"MediaLive 채널 정지 실패: {str(e)}")
            raise
    
    def get_hls_stream_url(self, mediapackage_endpoint: str) -> str:
        """
        MediaPackage 엔드포인트에서 HLS 스트림 URL 가져오기
        
        Args:
            mediapackage_endpoint: MediaPackage 엔드포인트 URL
            
        Returns:
            HLS 스트림 URL
        """
        # CloudFront 도메인이 있으면 CloudFront URL 반환
        # CDN 사용 시 성능 개선을 위해 CloudFront 도메인 활용 권장
        if 'mediapackage.' in mediapackage_endpoint and hasattr(self, 'cloudfront_domain') and self.cloudfront_domain:
            # MediaPackage 도메인을 CloudFront 도메인으로 대체
            path = mediapackage_endpoint.split('.com')[1]
            return f"https://{self.cloudfront_domain}{path}/index.m3u8"
        
        return f"{mediapackage_endpoint}/index.m3u8"
    
    @retry_aws_operation()
    def describe_channel(self, channel_id: str) -> Dict[str, Any]:
        """
        MediaLive 채널 정보 조회
        
        Args:
            channel_id: 채널 ID
            
        Returns:
            채널 정보
        """
        try:
            # 캐시에서 확인
            if channel_id in self.channel_cache:
                # 캐시 데이터가 10분 이내인 경우 재사용
                cache_time = self.channel_cache.get('_timestamp', 0)
                if time.time() - cache_time < 600:  # 10분
                    return self.channel_cache[channel_id]
            
            # API 호출
            response = self.medialive_client.describe_channel(ChannelId=channel_id)
            
            # 채널 정보 캐싱
            self.channel_cache[channel_id] = response['Channel']
            self.channel_cache['_timestamp'] = time.time()
            
            return response['Channel']
        except ClientError as e:
            logger.error(f"MediaLive 채널 정보 조회 실패: {str(e)}")
            raise
    
    @retry_aws_operation()
    def _put_custom_metric(self, metric_name: str, value: float, unit: str) -> None:
        """
        CloudWatch에 사용자 정의 메트릭 전송
        
        Args:
            metric_name: 메트릭 이름
            value: 메트릭 값
            unit: 단위 (Count, Bytes, Seconds 등)
        """
        try:
            self.cloudwatch_client.put_metric_data(
                Namespace='Casino/MediaLive',
                MetricData=[{
                    'MetricName': metric_name,
                    'Value': value,
                    'Unit': unit
                }]
            )
        except Exception as e:
            logger.warning(f"CloudWatch 메트릭 전송 실패: {str(e)}")
    
    def get_all_channels(self) -> List[Dict[str, Any]]:
        """모든 MediaLive 채널 목록 조회"""
        try:
            response = self.medialive_client.list_channels()
            return response['Channels']
        except ClientError as e:
            logger.error(f"MediaLive 채널 목록 조회 실패: {str(e)}")
            raise
    
    def close(self) -> None:
        """리소스 정리"""
        self.executor.shutdown(wait=True)
        logger.info("AWS MediaLive 매니저 종료") 