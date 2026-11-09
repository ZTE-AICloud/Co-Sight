import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { TEST_WORKSPACE_BROKEN_ID, TEST_WORKSPACE_DEFAULT_ID, TEST_WORKSPACE_ID } from './agents.js';
import { startFrameworkStub, type FrameworkStub, type StubModel } from './framework-stub.js';
import type { TestEnv } from './test-db.js';

const TIMESTAMP = '2026-01-01T00:00:00.000Z';

/** 会话模型运行配置的夹具：一条自定义地址、一条官方地址、一条 OpenAI 协议、一条无密钥。 */
export const TEST_MODEL_ID = 'a7cf0154-020b-4f97-b2bc-5ab8eb3bf0b5';
export const TEST_MODEL_ALT_ID = '2168b0c5-6f3b-4f2f-9d6b-2f5b4f7f8a11';
export const TEST_MODEL_OPENAI_ID = '3d4e5f60-7182-4a3b-9c4d-5e6f708192a3';
export const TEST_MODEL_NO_KEY_ID = '4e5f6071-8293-4b4c-8d5e-6f708192a3b4';
export const TEST_MODEL_KEY = 'sk-test-model-key';
export const TEST_MODEL_ALT_KEY = 'sk-test-alt-key';
export const TEST_MODEL_BASE_URL = 'https://gateway.test/anthropic';

export const TEST_MODELS: StubModel[] = [
  {
    id: TEST_MODEL_ID,
    provider: 'anthropic',
    protocol: 'anthropic',
    label: '测试 Sonnet',
    modelName: 'test-sonnet',
    baseUrl: TEST_MODEL_BASE_URL,
    hasApiKey: true,
    isActive: true,
    apiKey: TEST_MODEL_KEY,
    temperature: 0.7,
    topP: 1,
    maxOutputTokens: null,
    contextWindow: null,
    timeoutSeconds: 120,
    createdAt: TIMESTAMP,
    updatedAt: TIMESTAMP,
  },
  {
    id: TEST_MODEL_ALT_ID,
    provider: 'anthropic',
    protocol: 'anthropic',
    label: '测试 Opus',
    modelName: 'test-opus',
    baseUrl: null,
    hasApiKey: true,
    isActive: false,
    apiKey: TEST_MODEL_ALT_KEY,
    temperature: 1,
    topP: 1,
    maxOutputTokens: null,
    contextWindow: null,
    timeoutSeconds: 120,
    createdAt: TIMESTAMP,
    updatedAt: TIMESTAMP,
  },
  {
    id: TEST_MODEL_OPENAI_ID,
    provider: 'openai-compatible',
    protocol: 'openai',
    label: '测试 OpenAI',
    modelName: 'test-gpt',
    baseUrl: null,
    hasApiKey: true,
    isActive: false,
    apiKey: 'sk-test-openai-key',
    temperature: 1,
    topP: 1,
    maxOutputTokens: null,
    contextWindow: null,
    timeoutSeconds: 120,
    createdAt: TIMESTAMP,
    updatedAt: TIMESTAMP,
  },
  {
    id: TEST_MODEL_NO_KEY_ID,
    provider: 'anthropic',
    protocol: 'anthropic',
    label: '测试无密钥',
    modelName: 'test-no-key',
    baseUrl: null,
    hasApiKey: false,
    isActive: false,
    apiKey: null,
    temperature: 1,
    topP: 1,
    maxOutputTokens: null,
    contextWindow: null,
    timeoutSeconds: 120,
    createdAt: TIMESTAMP,
    updatedAt: TIMESTAMP,
  },
];

/**
 * 起一个只服务测试工作区的框架桩，并把 `FRAMEWORK_BASE_URL` 指过去。
 *
 * 必须在 import 任何 src 模块之前调用 - `config` 在导入时读取该环境变量。
 * 令牌是 prepareTestEnv 写进临时目录的假值，不涉及真实凭据。
 */
export async function startWorkspaceStub(env: TestEnv): Promise<FrameworkStub> {
  const token = readFileSync(join(env.home, '.module-token'), 'utf8').trim();
  const stub = await startFrameworkStub({
    token,
    workspaces: [
      {
        id: TEST_WORKSPACE_ID,
        name: '测试工作区',
        directory: env.workspaceDir,
        defaultModelId: null,
        defaultAgentId: null,
        createdAt: '2026-01-01T00:00:00.000Z',
        updatedAt: '2026-01-01T00:00:00.000Z',
      },
      {
        id: TEST_WORKSPACE_DEFAULT_ID,
        name: '默认模型工作区',
        directory: env.workspaceDir,
        defaultModelId: TEST_MODEL_ALT_ID,
        defaultAgentId: null,
        createdAt: '2026-01-01T00:00:00.000Z',
        updatedAt: '2026-01-01T00:00:00.000Z',
      },
      {
        id: TEST_WORKSPACE_BROKEN_ID,
        name: '默认模型失效工作区',
        directory: env.workspaceDir,
        defaultModelId: '00000000-0000-4000-8000-000000000000',
        defaultAgentId: null,
        createdAt: '2026-01-01T00:00:00.000Z',
        updatedAt: '2026-01-01T00:00:00.000Z',
      },
    ],
    activeWorkspaceId: TEST_WORKSPACE_ID,
    activeModelId: TEST_MODEL_ID,
    models: TEST_MODELS,
  });
  process.env.FRAMEWORK_BASE_URL = stub.url;
  return stub;
}
