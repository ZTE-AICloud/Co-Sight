// 设置cookie
export function setCookie (name: string, value: string, days: number) {
  const d = new Date();
  d.setTime(d.getTime() + (days * 24 * 60 * 60 * 1000));
  const expires = `expires=${d.toUTCString()}`;
  document.cookie = `${name}=${value};${expires};path=/`;
}

// 获取cookie
export function getCookie (name: string): string | null|undefined {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) {
    return parts.pop()?.split(';')
      .shift();
  }
  return null;
}

// 定义一个函数，用于停止事件冒泡
export function stopEventBubble (e: Event) {
  // 检查事件对象中是否存在stopPropagation方法
  if (e.stopPropagation) {
    e.stopPropagation(); // 如果存在，则调用W3C的方法来停止冒泡
  } else {
    // 如果不存在，则使用IE的方式设置cancelBubble属性为true来停止冒泡
    e.cancelBubble = true;
  }
};

// 下载用户本地上传的附件

export function encodeHeaderValue (src: string) {
  if (src === '') {
    return '';
  }

  const result = [];
  const encoder = new TextEncoder();

  for (const c of src) {
    const codePoint = c.codePointAt(0)!;
    const isDigit = /\d/.test(c);

    // 检查UTF-8编码的每个字节是否均为ASCII字母
    const bytes = encoder.encode(c);
    let isAlpha = bytes.every(b => (b >= 0x41 && b <= 0x5A) || // A-Z
          (b >= 0x61 && b <= 0x7A) // a-z
    );

    if (!isDigit && !isAlpha) {
      if (codePoint < 256) {
        const hex = codePoint.toString(16).padStart(2, '0');
        result.push(`%${hex}`);
      } else {
        const hex = codePoint.toString(16);
        result.push(`%u${hex}`);
      }
    } else {
      result.push(c);
    }
  }

  return result.join('');
}
