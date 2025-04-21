import React, { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import styled from 'styled-components';
import Hls from 'hls.js';
import ReactPlayer from 'react-player';
import { io } from 'socket.io-client';
import { Device } from 'mediasoup-client';
import { useAuth } from '../../contexts/AuthContext';

// 스타일 컴포넌트
const PlayerContainer = styled.div`
  position: relative;
  width: 100%;
  height: 0;
  padding-bottom: 56.25%; /* 16:9 비율 */
  background-color: #000;
  overflow: hidden;
  border-radius: 8px;
`;

const VideoElement = styled.video`
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
`;

const ControlsOverlay = styled.div`
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.7));
  padding: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  opacity: 0;
  transition: opacity 0.3s ease;
  
  ${PlayerContainer}:hover & {
    opacity: 1;
  }
`;

const Button = styled.button`
  background-color: rgba(255, 255, 255, 0.2);
  color: white;
  border: none;
  border-radius: 4px;
  padding: 8px 16px;
  margin: 0 4px;
  cursor: pointer;
  transition: background-color 0.3s ease;
  
  &:hover {
    background-color: rgba(255, 255, 255, 0.3);
  }
  
  &:disabled {
    background-color: rgba(255, 255, 255, 0.1);
    cursor: not-allowed;
  }
`;

const StatusIndicator = styled.div`
  position: absolute;
  top: 16px;
  right: 16px;
  padding: 4px 8px;
  border-radius: 4px;
  background-color: ${props => props.isLive ? 'red' : 'gray'};
  color: white;
  font-size: 12px;
  font-weight: bold;
`;

const LoadingOverlay = styled.div`
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  justify-content: center;
  align-items: center;
  background-color: rgba(0, 0, 0, 0.5);
  color: white;
  font-size: 18px;
`;

/**
 * 스트리밍 플레이어 컴포넌트
 * HLS와 WebRTC 스트리밍 재생 지원
 */
const StreamingPlayer = ({ 
  roomId, 
  streamUrl, 
  streamType = 'hls',
  muted = false,
  autoPlay = true,
  controls = true,
  onLoad,
  onError
}) => {
  // 상태
  const [isPlaying, setIsPlaying] = useState(autoPlay);
  const [isLoading, setIsLoading] = useState(true);
  const [isLive, setIsLive] = useState(false);
  const [error, setError] = useState(null);
  const [device, setDevice] = useState(null);
  const [rtpCapabilities, setRtpCapabilities] = useState(null);
  const [producers, setProducers] = useState([]);
  
  // 참조
  const videoRef = useRef(null);
  const hlsRef = useRef(null);
  const socketRef = useRef(null);
  const consumersRef = useRef(new Map());
  
  // 인증 컨텍스트
  const { user, getToken } = useAuth();
  
  /**
   * HLS 플레이어 초기화
   */
  const initHlsPlayer = () => {
    if (!streamUrl || streamType !== 'hls') return;
    
    if (Hls.isSupported()) {
      // HLS.js 지원되는 경우
      if (hlsRef.current) {
        hlsRef.current.destroy();
      }
      
      const hls = new Hls({
        enableWorker: true,
        lowLatencyMode: true,
        backBufferLength: 90
      });
      
      hls.attachMedia(videoRef.current);
      hls.on(Hls.Events.MEDIA_ATTACHED, () => {
        hls.loadSource(streamUrl);
      });
      
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        setIsLoading(false);
        setIsLive(true);
        if (autoPlay) {
          videoRef.current.play()
            .catch(err => console.error('자동 재생 실패:', err));
        }
        if (onLoad) onLoad();
      });
      
      hls.on(Hls.Events.ERROR, (event, data) => {
        console.error('HLS 오류:', data);
        if (data.fatal) {
          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              // 네트워크 오류, 재시도
              hls.startLoad();
              break;
            case Hls.ErrorTypes.MEDIA_ERROR:
              // 미디어 오류, 복구 시도
              hls.recoverMediaError();
              break;
            default:
              // 치명적 오류, 플레이어 소멸
              hls.destroy();
              setError('스트림 로드 중 오류가 발생했습니다');
              if (onError) onError(data);
              break;
          }
        }
      });
      
      hlsRef.current = hls;
    } else if (videoRef.current.canPlayType('application/vnd.apple.mpegurl')) {
      // 네이티브 HLS 지원 (iOS Safari)
      videoRef.current.src = streamUrl;
      videoRef.current.addEventListener('loadedmetadata', () => {
        setIsLoading(false);
        setIsLive(true);
        if (autoPlay) {
          videoRef.current.play()
            .catch(err => console.error('자동 재생 실패:', err));
        }
        if (onLoad) onLoad();
      });
      
      videoRef.current.addEventListener('error', (err) => {
        console.error('비디오 오류:', err);
        setError('스트림 로드 중 오류가 발생했습니다');
        if (onError) onError(err);
      });
    } else {
      // HLS 지원되지 않음
      setError('이 브라우저는 HLS 스트리밍을 지원하지 않습니다');
      if (onError) onError(new Error('HLS not supported'));
    }
  };
  
  /**
   * WebRTC 초기화
   */
  const initWebRTC = async () => {
    if (!roomId || streamType !== 'webrtc') return;
    
    try {
      // 토큰 가져오기
      const token = await getToken();
      
      if (!token) {
        throw new Error('인증 토큰을 가져올 수 없습니다');
      }
      
      // Socket.IO 연결
      const socketUrl = process.env.REACT_APP_STREAMING_SERVER || 'http://localhost:4000';
      const socket = io(socketUrl, {
        transports: ['websocket'],
        query: { token }
      });
      
      socketRef.current = socket;
      
      // 연결 이벤트
      socket.on('connect', async () => {
        console.log('스트리밍 서버에 연결됨');
        
        // 룸 입장
        socket.emit('joinRoom', {
          roomId,
          userId: user.id,
          token
        }, async (response) => {
          if (!response.success) {
            setError('룸 입장 실패: ' + response.error);
            return;
          }
          
          console.log('룸 입장 성공:', response.data);
          
          // 기존 프로듀서 저장
          setProducers(response.data.producers);
          
          // RTP 기능 가져오기
          socket.emit('getRouterRtpCapabilities', {}, async (response) => {
            if (!response.success) {
              setError('RTP 기능 가져오기 실패: ' + response.error);
              return;
            }
            
            setRtpCapabilities(response.data.rtpCapabilities);
            
            // Device 생성
            try {
              const newDevice = new Device();
              
              // Device 로드
              await newDevice.load({ routerRtpCapabilities: response.data.rtpCapabilities });
              
              setDevice(newDevice);
              
              // 이제 준비 완료
              setIsLoading(false);
              setIsLive(true);
              
              // 기존 프로듀서 소비
              for (const producer of response.data.producers) {
                await consumeProducer(producer.id, newDevice);
              }
              
              if (onLoad) onLoad();
            } catch (error) {
              console.error('Device 초기화 실패:', error);
              setError('WebRTC 초기화 실패');
              if (onError) onError(error);
            }
          });
        });
      });
      
      // 연결 오류 이벤트
      socket.on('connect_error', (err) => {
        console.error('연결 오류:', err);
        setError('스트리밍 서버에 연결할 수 없습니다');
        if (onError) onError(err);
      });
      
      // 새 프로듀서 알림 이벤트
      socket.on('newProducer', async (data) => {
        console.log('새 프로듀서:', data);
        
        if (device && device.loaded) {
          await consumeProducer(data.producerId, device);
        }
      });
      
      // HLS 스트림 시작 알림
      socket.on('hlsStreamStarted', (data) => {
        console.log('HLS 스트림 시작됨:', data);
      });
      
      // 사용자 입장 알림
      socket.on('userJoined', (data) => {
        console.log('사용자 입장:', data);
      });
      
      // 사용자 퇴장 알림
      socket.on('userLeft', (data) => {
        console.log('사용자 퇴장:', data);
      });
      
    } catch (error) {
      console.error('WebRTC 초기화 실패:', error);
      setError('WebRTC 초기화 중 오류가 발생했습니다');
      if (onError) onError(error);
    }
  };
  
  /**
   * 프로듀서 소비 함수
   * @param {string} producerId - 프로듀서 ID
   * @param {Device} deviceObj - mediasoup Device 객체
   */
  const consumeProducer = async (producerId, deviceObj) => {
    try {
      if (!socketRef.current || !deviceObj || !deviceObj.loaded) {
        console.error('소비 초기화 실패: 소켓 또는 디바이스가 준비되지 않음');
        return;
      }
      
      // 컨슈머 트랜스포트가 없으면 생성
      if (!deviceObj.canConsume) {
        // 전송 생성
        socketRef.current.emit('createWebRtcTransport', {}, async (response) => {
          if (!response.success) {
            console.error('트랜스포트 생성 실패:', response.error);
            return;
          }
          
          const transport = deviceObj.createRecvTransport(response.data);
          
          // 트랜스포트 연결 이벤트
          transport.on('connect', ({ dtlsParameters }, callback, errback) => {
            socketRef.current.emit('connectWebRtcTransport', {
              transportId: transport.id,
              dtlsParameters
            }, (response) => {
              if (response.success) {
                callback();
              } else {
                errback(new Error(response.error));
              }
            });
          });
          
          // 트랜스포트로 소비 시작
          await consumeWithTransport(transport, producerId);
        });
      } else {
        // 기존 트랜스포트로 소비
        const transport = deviceObj.getRecvTransports()[0];
        await consumeWithTransport(transport, producerId);
      }
    } catch (error) {
      console.error('프로듀서 소비 실패:', error);
    }
  };
  
  /**
   * 트랜스포트로 소비 함수
   * @param {Transport} transport - mediasoup 트랜스포트
   * @param {string} producerId - 프로듀서 ID
   */
  const consumeWithTransport = async (transport, producerId) => {
    socketRef.current.emit('consume', {
      transportId: transport.id,
      producerId,
      rtpCapabilities: device.rtpCapabilities
    }, async (response) => {
      if (!response.success) {
        console.error('소비 실패:', response.error);
        return;
      }
      
      const { id, kind, rtpParameters, producerId, producerPaused } = response.data;
      
      // 컨슈머 생성
      const consumer = await transport.consume({
        id,
        producerId,
        kind,
        rtpParameters
      });
      
      // 컨슈머 저장
      consumersRef.current.set(id, consumer);
      
      // 비디오 또는 오디오 트랙 처리
      if (kind === 'video') {
        const stream = new MediaStream([consumer.track]);
        videoRef.current.srcObject = stream;
        
        if (autoPlay) {
          videoRef.current.play()
            .catch(err => console.error('자동 재생 실패:', err));
        }
      } else if (kind === 'audio') {
        // 기존 비디오 스트림이 있으면 오디오 트랙 추가
        if (videoRef.current.srcObject) {
          videoRef.current.srcObject.addTrack(consumer.track);
        } else {
          const stream = new MediaStream([consumer.track]);
          videoRef.current.srcObject = stream;
          
          if (autoPlay) {
            videoRef.current.play()
              .catch(err => console.error('자동 재생 실패:', err));
          }
        }
      }
      
      // 컨슈머 재개
      socketRef.current.emit('resumeConsumer', { consumerId: id });
    });
  };
  
  /**
   * 직접 HLS 변환 요청 함수
   */
  const requestHlsConversion = async (producerId) => {
    if (!socketRef.current) return;
    
    socketRef.current.emit('startHlsStream', {
      producerId
    }, (response) => {
      if (!response.success) {
        console.error('HLS 변환 요청 실패:', response.error);
        return;
      }
      
      console.log('HLS 변환 시작됨:', response.data.hlsUrl);
    });
  };
  
  /**
   * 비디오 재생/일시정지 토글 함수
   */
  const togglePlay = () => {
    if (isPlaying) {
      videoRef.current.pause();
    } else {
      videoRef.current.play()
        .catch(err => console.error('재생 실패:', err));
    }
    
    setIsPlaying(!isPlaying);
  };
  
  /**
   * 음소거 토글 함수
   */
  const toggleMute = () => {
    videoRef.current.muted = !videoRef.current.muted;
  };
  
  /**
   * 전체화면 토글 함수
   */
  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      videoRef.current.requestFullscreen()
        .catch(err => console.error('전체화면 진입 실패:', err));
    } else {
      document.exitFullscreen();
    }
  };
  
  // 컴포넌트 마운트/업데이트 시 스트리밍 초기화
  useEffect(() => {
    if (streamType === 'hls') {
      initHlsPlayer();
    } else if (streamType === 'webrtc') {
      initWebRTC();
    }
    
    return () => {
      // 정리
      if (hlsRef.current) {
        hlsRef.current.destroy();
      }
      
      if (socketRef.current) {
        socketRef.current.disconnect();
      }
      
      // 컨슈머 정리
      consumersRef.current.forEach((consumer) => {
        consumer.close();
      });
      consumersRef.current.clear();
    };
  }, [streamUrl, roomId, streamType]);
  
  return (
    <PlayerContainer>
      <VideoElement 
        ref={videoRef}
        playsInline
        muted={muted}
        controls={controls}
      />
      
      {isLive && <StatusIndicator isLive={isLive}>LIVE</StatusIndicator>}
      
      {!controls && (
        <ControlsOverlay>
          <Button onClick={togglePlay}>
            {isPlaying ? '일시정지' : '재생'}
          </Button>
          
          <div>
            <Button onClick={toggleMute}>
              {videoRef.current?.muted ? '음소거 해제' : '음소거'}
            </Button>
            
            <Button onClick={toggleFullscreen}>
              전체화면
            </Button>
          </div>
        </ControlsOverlay>
      )}
      
      {isLoading && (
        <LoadingOverlay>
          스트림 로딩 중...
        </LoadingOverlay>
      )}
      
      {error && (
        <LoadingOverlay>
          {error}
        </LoadingOverlay>
      )}
    </PlayerContainer>
  );
};

StreamingPlayer.propTypes = {
  roomId: PropTypes.string,
  streamUrl: PropTypes.string,
  streamType: PropTypes.oneOf(['hls', 'webrtc']),
  muted: PropTypes.bool,
  autoPlay: PropTypes.bool,
  controls: PropTypes.bool,
  onLoad: PropTypes.func,
  onError: PropTypes.func
};

export default StreamingPlayer; 