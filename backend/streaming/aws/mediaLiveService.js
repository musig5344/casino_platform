/**
 * AWS MediaLive 서비스
 * AI 딜러 송출에 AWS MediaLive를 사용하기 위한 서비스
 */

const AWS = require('aws-sdk');
const config = require('../mediasoup/config');

class MediaLiveService {
  /**
   * MediaLive 서비스 초기화
   */
  constructor() {
    const { region } = config.aiDealerStream.mediaLive;
    
    this.mediaLive = new AWS.MediaLive({
      region,
      apiVersion: '2017-10-14'
    });
    
    this.channelId = config.aiDealerStream.mediaLive.channelId;
    this.inputId = config.aiDealerStream.mediaLive.inputId;
    this.startTimeout = config.aiDealerStream.mediaLive.startTimeout * 1000; // ms로 변환
    this.pollingInterval = config.aiDealerStream.mediaLive.pollingInterval;
  }

  /**
   * 채널 상태 확인
   * @returns {Promise<string>} 채널 상태
   */
  async getChannelState() {
    try {
      const params = {
        ChannelId: this.channelId
      };
      
      const response = await this.mediaLive.describeChannel(params).promise();
      return response.State;
      
    } catch (error) {
      console.error('MediaLive 채널 상태 확인 실패:', error);
      throw error;
    }
  }

  /**
   * 채널 시작
   * @returns {Promise<boolean>} 시작 성공 여부
   */
  async startChannel() {
    try {
      const state = await this.getChannelState();
      
      if (state === 'RUNNING') {
        console.log('채널이 이미 실행 중입니다');
        return true;
      }
      
      if (state === 'STARTING') {
        console.log('채널이 이미 시작 중입니다');
        return await this.waitForChannelState('RUNNING');
      }
      
      console.log(`MediaLive 채널 시작: ${this.channelId}`);
      
      const params = {
        ChannelId: this.channelId
      };
      
      await this.mediaLive.startChannel(params).promise();
      
      // 채널이 실행될 때까지 대기
      return await this.waitForChannelState('RUNNING');
      
    } catch (error) {
      console.error('MediaLive 채널 시작 실패:', error);
      throw error;
    }
  }

  /**
   * 채널 중지
   * @returns {Promise<boolean>} 중지 성공 여부
   */
  async stopChannel() {
    try {
      const state = await this.getChannelState();
      
      if (state === 'IDLE') {
        console.log('채널이 이미 중지되었습니다');
        return true;
      }
      
      if (state === 'STOPPING') {
        console.log('채널이 이미 중지 중입니다');
        return await this.waitForChannelState('IDLE');
      }
      
      console.log(`MediaLive 채널 중지: ${this.channelId}`);
      
      const params = {
        ChannelId: this.channelId
      };
      
      await this.mediaLive.stopChannel(params).promise();
      
      // 채널이 중지될 때까지 대기
      return await this.waitForChannelState('IDLE');
      
    } catch (error) {
      console.error('MediaLive 채널 중지 실패:', error);
      throw error;
    }
  }

  /**
   * 채널 상태 대기
   * @param {string} targetState - 대기할 상태
   * @returns {Promise<boolean>} 성공 여부
   */
  async waitForChannelState(targetState) {
    return new Promise((resolve, reject) => {
      const startTime = Date.now();
      
      const checkState = async () => {
        try {
          const currentState = await this.getChannelState();
          console.log(`현재 채널 상태: ${currentState}`);
          
          if (currentState === targetState) {
            console.log(`채널이 ${targetState} 상태가 되었습니다`);
            resolve(true);
            return;
          }
          
          // 타임아웃 확인
          if (Date.now() - startTime > this.startTimeout) {
            console.error(`채널 상태 변경 타임아웃: ${targetState}`);
            reject(new Error(`채널 상태 변경 타임아웃: ${currentState} -> ${targetState}`));
            return;
          }
          
          // 상태 계속 확인
          setTimeout(checkState, this.pollingInterval);
          
        } catch (error) {
          reject(error);
        }
      };
      
      checkState();
    });
  }

  /**
   * 입력 스위치
   * @param {string} inputAttachmentName - 입력 첨부 이름
   * @returns {Promise<boolean>} 스위치 성공 여부
   */
  async switchInput(inputAttachmentName) {
    try {
      console.log(`MediaLive 입력 전환: ${inputAttachmentName}`);
      
      const params = {
        ChannelId: this.channelId,
        InputAttachmentName: inputAttachmentName
      };
      
      await this.mediaLive.batchUpdateChannel(params).promise();
      return true;
      
    } catch (error) {
      console.error('MediaLive 입력 전환 실패:', error);
      throw error;
    }
  }

  /**
   * 입력 준비
   * @param {string} url - 입력 URL
   * @returns {Promise<Object>} 입력 정보
   */
  async prepareInput(url) {
    try {
      console.log(`MediaLive 입력 준비: ${url}`);
      
      // 입력 URL 업데이트
      const params = {
        InputId: this.inputId,
        Sources: [
          {
            Url: url
          }
        ]
      };
      
      const response = await this.mediaLive.updateInput(params).promise();
      return response;
      
    } catch (error) {
      console.error('MediaLive 입력 준비 실패:', error);
      throw error;
    }
  }
}

module.exports = MediaLiveService; 