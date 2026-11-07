import Crypto from '@/shared/lib/crypto.js';
import { v4 as uuidv4 } from 'uuid';

export function useCrypto (secret) {
  function getNonce () {
    let uuid = uuidv4()
    uuid = uuid.replace(/-/g, '');
    return uuid
  };
  /**
   * 异步获取签名信息
   * @returns {Promise<{Signature: string, Timestamp: number, Nonce: string}>}
   */
  async function getSignature () {
    const nonce = getNonce();
    const { Signature, Timestamp } = await Crypto.AES.doSignature(nonce, secret)
    return {
      Signature,
      Timestamp,
      Nonce: nonce
    }
  }

  /**
   * 获取包含签名信息的请求配置（异步）
   * @returns {Promise<{headers: {Signature: string, Timestamp: number, Nonce: string}}>}
   */
  async function getConfig () {
    const headers = await getSignature();
    return { headers };
  }

  return {
    getConfig
  }
};
