import {
  absoluteUrl,
  buildAnswerCurl,
  buildClaudeCommand,
  buildListCurl,
  buildMcpCurl,
  buildMcpJson,
  buildPatchPayload,
  buildSearchCurl,
  buildStdioCommand,
  formatCount,
  formatDateUTC,
  formatDateTime,
  isExpired,
  normalizeScopes,
  scopeLabelKey,
  SCOPE_LABEL_KEYS
} from '@/features/agent/lib/helpers'

describe('remoteAccess helpers', () => {
  describe('absoluteUrl', () => {
    it('拼接相对路径', () => {
      expect(absoluteUrl('/api/co-knowledge/v1/mcp', 'http://host:8080'))
        .toBe('http://host:8080/api/co-knowledge/v1/mcp')
    })

    it('绝对 URL 原样返回', () => {
      expect(absoluteUrl('https://rag.example/api/co-knowledge/v1/mcp', 'http://host'))
        .toBe('https://rag.example/api/co-knowledge/v1/mcp')
    })

    it('空值返回空串', () => {
      expect(absoluteUrl('', 'http://host')).toBe('')
    })
  })

  describe('MCP snippets', () => {
    const url = 'http://host/api/co-knowledge/v1/mcp'

    it('Claude Code 命令包含 transport 与 header', () => {
      const command = buildClaudeCommand(url)
      expect(command).toContain('claude mcp add --transport http co-knowledge')
      expect(command).toContain(url)
      expect(command).toContain('Authorization: Bearer <YOUR_API_KEY>')
    })

    it('.mcp.json 是合法 JSON 且带认证头', () => {
      const config = JSON.parse(buildMcpJson(url))
      expect(config.mcpServers['co-knowledge'].type).toBe('http')
      expect(config.mcpServers['co-knowledge'].url).toBe(url)
      expect(config.mcpServers['co-knowledge'].headers.Authorization)
        .toBe('Bearer <YOUR_API_KEY>')
    })

    it('stdio 兜底命令使用 mcp-remote', () => {
      expect(buildStdioCommand(url)).toContain('npx -y mcp-remote')
    })

    it('curl initialize 带 Accept 与 SSE 兼容头', () => {
      const curl = buildMcpCurl(url)
      expect(curl).toContain('"method":"initialize"')
      expect(curl).toContain('Accept: application/json, text/event-stream')
    })
  })

  describe('REST snippets', () => {
    const base = 'http://host/api/co-knowledge/v1/agent'

    it('列库 / 检索 / 问答分别指向正确端点', () => {
      expect(buildListCurl(base)).toContain(`${base}/knowledge-bases`)
      expect(buildSearchCurl(base)).toContain(`${base}/search`)
      expect(buildAnswerCurl(base)).toContain(`${base}/answer`)
    })
  })

  describe('scopes', () => {
    it('scopeLabelKey 命中固定映射，未知值回落', () => {
      expect(scopeLabelKey('kb:list')).toBe(SCOPE_LABEL_KEYS['kb:list'])
      expect(scopeLabelKey('workflow:run')).toBe(SCOPE_LABEL_KEYS['workflow:run'])
      expect(scopeLabelKey('nope')).toBe('modules.remoteAccess.scopeUnknown')
    })

    it('normalizeScopes 去重并按固定顺序排列', () => {
      expect(normalizeScopes(['kb:answer', 'kb:list', 'kb:list']))
        .toEqual(['kb:list', 'kb:answer'])
      expect(normalizeScopes(['workflow:run', 'kb:list', 'workflow:run']))
        .toEqual(['kb:list', 'workflow:run'])
      expect(normalizeScopes(null)).toEqual([])
    })
  })

  describe('buildPatchPayload', () => {
    const original = {
      name: 'demo',
      scopes: ['kb:list', 'kb:search'],
      kbIds: ['kb-1'],
      rateLimitPerMin: 60,
      expiresAt: '2030-01-02T23:59:59+00:00'
    }

    it('没有变化时返回空对象', () => {
      expect(buildPatchPayload(original, {
        name: 'demo',
        scopes: ['kb:search', 'kb:list'],
        kbIds: ['kb-1'],
        rateLimitPerMin: 60,
        expiresAt: '2030-01-02'
      })).toEqual({})
    })

    it('只返回变化的字段', () => {
      expect(buildPatchPayload(original, {
        name: 'renamed',
        scopes: ['kb:list'],
        kbIds: ['kb-1', 'kb-2'],
        rateLimitPerMin: 10,
        expiresAt: '2030-01-02'
      })).toEqual({
        name: 'renamed',
        scopes: ['kb:list'],
        kbIds: ['kb-1', 'kb-2'],
        rateLimitPerMin: 10
      })
    })

    it('用途说明变化时发送 description，清空发送空串', () => {
      const withDescription = { ...original, description: '旧用途' }
      expect(buildPatchPayload(withDescription, {
        name: 'demo',
        description: '新用途',
        scopes: ['kb:list', 'kb:search'],
        kbIds: ['kb-1'],
        rateLimitPerMin: 60,
        expiresAt: '2030-01-02'
      })).toEqual({ description: '新用途' })
      expect(buildPatchPayload(withDescription, {
        name: 'demo',
        description: '',
        scopes: ['kb:list', 'kb:search'],
        kbIds: ['kb-1'],
        rateLimitPerMin: 60,
        expiresAt: '2030-01-02'
      })).toEqual({ description: '' })
    })

    it('清空过期时间发送 null', () => {
      expect(buildPatchPayload(original, {
        name: 'demo',
        scopes: ['kb:list', 'kb:search'],
        kbIds: ['kb-1'],
        rateLimitPerMin: 60,
        expiresAt: ''
      })).toEqual({ expiresAt: null })
    })

    it('已过期的旧日期不原样回传（否则后端会拒绝保存）', () => {
      const expired = { ...original, expiresAt: '2000-01-01T00:00:00+00:00' }
      expect(buildPatchPayload(expired, {
        name: 'demo',
        scopes: ['kb:list', 'kb:search'],
        kbIds: ['kb-1'],
        rateLimitPerMin: 60,
        expiresAt: '2000-01-01'
      })).toEqual({})
    })
  })

  describe('时间', () => {
    it('formatDateTime 空值返回空串', () => {
      expect(formatDateTime(null)).toBe('')
      expect(formatDateTime('')).toBe('')
    })

    it('formatDateUTC 按 UTC 取日，东八区不跳到第二天', () => {
      expect(formatDateUTC('2026-10-28T23:59:59Z')).toBe('2026-10-28')
      expect(formatDateUTC('2026-10-29T07:59:59+08:00')).toBe('2026-10-28')
      expect(formatDateUTC(null)).toBe('')
    })

    it('formatDateTime 输出 YYYY-MM-DD HH:mm', () => {
      expect(formatDateTime('2030-01-02T03:04:05+00:00'))
        .toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
    })

    it('isExpired 以传入的 now 为准', () => {
      const now = new Date('2030-01-02T00:00:00Z').getTime()
      expect(isExpired('2030-01-01T00:00:00Z', now)).toBe(true)
      expect(isExpired('2030-01-03T00:00:00Z', now)).toBe(false)
      expect(isExpired(null, now)).toBe(false)
    })
  })

  describe('formatCount', () => {
    it('调用量带千分位', () => {
      expect(formatCount(12430)).toBe('12,430')
      expect(formatCount(0)).toBe('0')
      expect(formatCount('3290')).toBe('3,290')
    })

    it('空值 / 非数字回落占位符', () => {
      expect(formatCount(null)).toBe('—')
      expect(formatCount(undefined)).toBe('—')
      expect(formatCount('')).toBe('—')
      expect(formatCount('not-a-number')).toBe('—')
    })
  })
})
