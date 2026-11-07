import message from './message'

// 见 ``Crypto.AES.encrypt`` 的说明：非安全上下文（http 部署）下 subtle 不存在。
const hasWebCrypto = () => typeof crypto !== 'undefined' && !!crypto.subtle

let _warnedNoWebCrypto = false
function warnUnavailableOnce () {
  if (_warnedNoWebCrypto) {
    return
  }
  _warnedNoWebCrypto = true
  console.warn('[crypto] 当前非安全上下文（非 HTTPS/localhost），crypto.subtle 不可用，' +
    '已跳过请求签名（后端不校验该签名）。')
}

const Crypto = {
  AES: {
    format (date) {
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, '0'); // 月份从0开始
      const day = String(date.getDate()).padStart(2, '0');
      const hours = String(date.getHours()).padStart(2, '0'); // 小时
      const minutes = String(date.getMinutes()).padStart(2, '0'); // 分钟

      // 返回格式化的日期字符串，包括小时和分钟
      return `${year}${month}${day}${hours}${minutes}`;
    },
    /**
     * 使用 HMAC-SHA256 算法加密数据
     * @param {string} data - 要加密的数据
     * @param {string} secret - 密钥
     * @returns {Promise<string>} 返回十六进制格式的签名
     *
     * ⚠️ WebCrypto（``crypto.subtle``）**只在安全上下文存在**（HTTPS 或 localhost）。
     * 以 http://<host> 形态部署时 ``crypto.subtle`` 为 ``undefined``，
     * 直接调用会在 ``importKey`` 抛 ``TypeError``，把整条上传链路带崩
     * （症状：建库成功但文件一个都传不上去，且向导把异常吞了 → 用户零提示）。
     *
     * 签名头后端**不校验**，它只对「HTTPS 网关」这类部署有意义 ——
     * 而那种部署天然是安全上下文，签名照常工作。所以非安全上下文下**降级为不带签名**
     * 是安全的：不引入手写 crypto 实现（安全敏感、且当前零收益），只让链路能跑通。
     */
    async encrypt (data, secret) {
      if (!hasWebCrypto()) {
        warnUnavailableOnce();
        return '';
      }
      // 将字符串转换为 ArrayBuffer
      const encoder = new TextEncoder();
      const dataBuffer = encoder.encode(data);
      const secretBuffer = encoder.encode(secret);

      // 导入密钥
      const key = await crypto.subtle.importKey(
        'raw',
        secretBuffer,
        {
          name: 'HMAC',
          hash: 'SHA-256'
        },
        false,
        ['sign']
      );

      // 使用 HMAC-SHA256 签名
      const signature = await crypto.subtle.sign(
        'HMAC',
        key,
        dataBuffer
      );

      // 将 ArrayBuffer 转换为十六进制字符串
      const hashArray = Array.from(new Uint8Array(signature));
      return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    },
    /**
     * 生成签名和时间戳
     * @param {string} accessKey - 访问密钥
     * @param {string} accessSecret - 访问密钥的密钥
     * @returns {Promise<{Signature: string, Timestamp: number}>} 返回签名和时间戳
     */
    async doSignature (accessKey, accessSecret) {
      if (!accessKey || !accessSecret) {
        message.error({ message: 'Access Key or Access Secret is missing.' });
      }

      let sf = accessKey;
      const date = new Date();
      const timestampInSeconds = Math.floor(date.getTime() / 1000);
      const today = Crypto.AES.format(date);
      sf += `:${today}`;

      const signature = await Crypto.AES.encrypt(sf, accessSecret);
      return {
        Signature: signature,
        Timestamp: timestampInSeconds
      };
    }
  }
};

export default Crypto;
