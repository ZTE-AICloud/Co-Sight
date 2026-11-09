/**
 * 配置解析与跨源基准的归一化。
 *
 * hostOrigin 的归一化值得单独测：它被拿去和 `new URL(...).origin` 做**全等比较**，
 * 一旦留了路径或尾斜杠，比较恒不相等，模块的跨源校验就会静默失效——不报错、
 * 不崩溃，只是不再起作用。这种失效必须在测试里钉住。
 */

import { describe, expect, it } from 'vitest';

import { ConfigError, DEFAULT_PORT, loadConfig } from '../src/config/env';

describe('loadConfig', () => {
  it('缺省时用默认端口与所有网卡地址', () => {
    const config = loadConfig({});
    expect(config.port).toBe(DEFAULT_PORT);
    expect(config.host).toBe('0.0.0.0');
  });

  it('端口越界时启动即失败，而不是运行期出问题', () => {
    expect(() => loadConfig({ COSIGHT_PORT: '0' })).toThrow(ConfigError);
    expect(() => loadConfig({ COSIGHT_PORT: '65536' })).toThrow(ConfigError);
    expect(() => loadConfig({ COSIGHT_PORT: 'abc' })).toThrow(ConfigError);
  });

  it('日志级别只接受白名单值', () => {
    expect(() => loadConfig({ COSIGHT_LOG_LEVEL: 'verbose' })).toThrow(ConfigError);
    expect(loadConfig({ COSIGHT_LOG_LEVEL: 'debug' }).logLevel).toBe('debug');
  });

  it('hostOrigin 去掉路径、查询串与尾斜杠', () => {
    const config = loadConfig({ COSIGHT_HOST_ORIGIN: 'http://localhost:4310/app?x=1' });
    expect(config.hostOrigin).toBe('http://localhost:4310');
  });

  it('hostOrigin 非法时报错', () => {
    expect(() => loadConfig({ COSIGHT_HOST_ORIGIN: 'not a url' })).toThrow(ConfigError);
  });

  it('未配置 hostOrigin 时回退到 API 自身的源', () => {
    const config = loadConfig({ COSIGHT_HOST: '127.0.0.1', COSIGHT_PORT: '4300' });
    expect(config.hostOrigin).toBe('http://127.0.0.1:4300');
  });

  it('绑定 0.0.0.0 时 hostOrigin 回退到回环地址，避免生成无法比较的源', () => {
    const config = loadConfig({ COSIGHT_HOST: '0.0.0.0', COSIGHT_PORT: '4300' });
    expect(config.hostOrigin).toBe('http://127.0.0.1:4300');
  });

  it('CORS 源按逗号切分并去掉空项', () => {
    const config = loadConfig({ COSIGHT_CORS_ORIGINS: 'http://a.test, ,http://b.test' });
    expect(config.corsOrigins).toEqual(['http://a.test', 'http://b.test']);
  });

  it('开发态不设前端产物目录（交给 Vite）', () => {
    expect(loadConfig({ NODE_ENV: 'development' }).webDistDir).toBeNull();
  });

  it('生产态默认从包内 public 目录托管前端', () => {
    const config = loadConfig({ NODE_ENV: 'production', COSIGHT_WEB_DIST: '/srv/web' });
    expect(config.webDistDir).toBe('/srv/web');
  });

  it('知识库 API Key 默认值：没设或只有空白都算未配置', () => {
    expect(loadConfig({}).ragKnowledgeApiKey).toBeNull();
    // `CO_KNOWLEDGE_API_KEY=` 是"留空"，不能当成一枚空密钥。
    expect(loadConfig({ CO_KNOWLEDGE_API_KEY: '   ' }).ragKnowledgeApiKey).toBeNull();
    expect(loadConfig({ CO_KNOWLEDGE_API_KEY: 'ragk_module' }).ragKnowledgeApiKey).toBe(
      'ragk_module',
    );
  });

  it('框架命名空间优先；它显式留空时仍落到模块同名变量', () => {
    const both = loadConfig({
      COSIGHT_KNOWLEDGE_API_KEY: 'ragk_framework',
      CO_KNOWLEDGE_API_KEY: 'ragk_module',
    });
    expect(both.ragKnowledgeApiKey).toBe('ragk_framework');

    /*
     * `??` 会停在空串上、把模块那一枚挡掉——同一份 cosight.env 里既有框架的
     * 空占位、又有模块的真实 Key 时，模块面会突然拿不到 Key，且没有任何报错。
     */
    const emptyFramework = loadConfig({
      COSIGHT_KNOWLEDGE_API_KEY: '',
      CO_KNOWLEDGE_API_KEY: 'ragk_module',
    });
    expect(emptyFramework.ragKnowledgeApiKey).toBe('ragk_module');
  });
});
