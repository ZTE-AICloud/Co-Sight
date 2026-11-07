export interface AgentKey {
  keyPrefix: string
  name: string
  scopes: string[]
  kbIds: string[]
  rateLimitPerMin: number
  enabled: boolean
  expiresAt: string | null
  expired: boolean
  lastUsedAt: string | null
  createdAt: string | null
  createdBy: string
  /** 仅前端使用：启停请求在飞时禁用开关 */
  toggling?: boolean
}

export interface AgentKeyStatus {
  adminEnabled: boolean
  apiEnabled: boolean
  restEnabled: boolean
  mcpEnabled: boolean
  answerEnabled: boolean
  pepperConfigured: boolean
  keyStoreAvailable: boolean
  authMode: string
  restBasePath: string
  mcpPath: string
  publicBase: string
  scopes: string[]
  defaultScopes: string[]
  defaultRateLimitPerMin: number
  maxKbs: number
  maxKbIds: number
}

export interface KbOption {
  id: string
  name: string
}

export interface KeyCreateResult {
  key: AgentKey
  plaintextKey: string
}
