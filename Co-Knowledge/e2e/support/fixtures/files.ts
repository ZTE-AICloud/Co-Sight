/**
 * 测试文件/压缩包生成。
 *
 * 运行时生成而不是把二进制都塞进仓库：
 * - 危险算子、图谱导入包、超大文件、伪造扩展名都能按用例定制；
 * - 只把仓库本来就有的样本（deploy/init/seed）复制到 fixtures/docs 作为稳定输入。
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import JSZip from 'jszip'

export interface ZipEntries {
  [name: string]: string | Buffer
}

export async function createZip (entries: ZipEntries): Promise<Buffer> {
  const zip = new JSZip()
  for (const [name, content] of Object.entries(entries)) {
    zip.file(name, content)
  }
  return zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' })
}

/** 含 `os.system` 的算子包：code-check 必须拒绝。 */
export async function dangerousOperatorZip (): Promise<Buffer> {
  return createZip({
    'config.json': JSON.stringify({
      display_name: { zh: 'E2E危险算子', en: 'e2e_dangerous_splitter' },
      desc: { zh: 'E2E 危险算子', en: 'E2E dangerous operator' },
      module: 'text_split',
      version: '1.0.0',
      supportedFormat: ['md', 'txt'],
      is_published: 1,
      visibleRange: 'private',
      defaultArgs: []
    }, null, 2),
    'dangerous_split.py': [
      'import os',
      '',
      'def file_split(file_path: str, **args):',
      "    os.system('echo e2e-dangerous')",
      "    return [{'content': 'x', 'metadata': {'source': 'x'}}]",
      ''
    ].join('\n')
  })
}

/**
 * 官方 graph_extract 模板的扁平化版本。
 *
 * 模板 zip 里是 `graph_extract/` 子目录，而 `/operator/import` 要求 config.json 在根；
 * 这里解包后重新扁平打包。
 *
 * 同时补一个 `schemaId` 参数：算子签名里有 `schema`，但官方模板没有声明 `schemaId`，
 * 后端的 `operator_consumes_schema` 只认算子参数表里声明过 `schemaId` 的专业算子，
 * 不声明就永远不会把 schema 传进沙箱（会报 `graph_extract() missing 1 required
 * positional argument: 'schema'`）。UI 也靠同一个参数决定是否渲染「图谱模板」下拉。
 */
export async function graphExtractOperatorZip (suffix = ''): Promise<Buffer> {
  const templatePath = path.resolve(
    __dirname,
    '../../../backend/src/operators/templates/graph_extract.zip'
  )
  const template = fs.readFileSync(templatePath)
  const source = await JSZip.loadAsync(template)
  const configEntry = source.file('graph_extract/config.json')
  const codeEntry = source.file('graph_extract/graph_extract.py')
  if (!configEntry || !codeEntry) {
    throw new Error('graph_extract 模板结构与预期不符（缺 config.json 或 graph_extract.py）')
  }
  const config = JSON.parse(await configEntry.async('string'))
  // 算子名只允许汉字 / 英文 / 数字 / 下划线（导入接口 0005 校验），用例 ID 里的
  // 连字符必须归一化掉。
  const safeSuffix = suffix.replace(/[^A-Za-z0-9_一-龥]/g, '_')
  config.display_name = {
    zh: `E2E图谱抽取算子${safeSuffix ? `_${safeSuffix}` : ''}`,
    en: `e2e_graph_extract${safeSuffix ? `_${safeSuffix}` : ''}`
  }
  // 官方模板已声明 schemaId；只有旧模板才需要补（避免出现两个同名参数）。
  const args = Array.isArray(config.defaultArgs) ? config.defaultArgs : []
  if (!args.some((arg: { argName?: string }) => arg?.argName === 'schemaId')) {
    args.unshift({
      argName: 'schemaId',
      argType: 'str',
      defaultValue: '',
      description: '知识图谱模板',
      tips: { zh: '选择抽取时遵循的 schema', en: 'Schema used for extraction' }
    })
  }
  config.defaultArgs = args
  return createZip({
    'config.json': JSON.stringify(config, null, 2),
    'graph_extract.py': await codeEntry.async('nodebuffer')
  })
}

export const GRAPH_SCHEMA = {
  schema_id: 'schema-e2e-person',
  schema_name: 'E2E人物关系',
  schema_desc: 'E2E 图谱导入/抽取使用的固定 schema',
  entities: [
    {
      entity_type: 'Person',
      entity_desc: '人物',
      properties: [
        { name: 'name', type: 'STRING', desc: '姓名', is_primary: true, is_embedding: false, is_index: true },
        { name: 'age', type: 'INTEGER', desc: '年龄', is_primary: false, is_embedding: false, is_index: false }
      ]
    },
    {
      entity_type: 'Organization',
      entity_desc: '组织',
      properties: [
        { name: 'name', type: 'STRING', desc: '名称', is_primary: true, is_embedding: false, is_index: true }
      ]
    }
  ],
  edges: [
    {
      edge_type: 'Knows',
      edge_desc: '认识',
      direction: 'two-way',
      source_entity: 'Person',
      target_entity: 'Person',
      properties: [
        { name: 'since', type: 'DATE', desc: '认识日期', is_embedding: false, is_index: false }
      ]
    },
    {
      edge_type: 'WorksAt',
      edge_desc: '就职于',
      direction: 'one-way',
      source_entity: 'Person',
      target_entity: 'Organization',
      properties: [
        { name: 'role', type: 'STRING', desc: '角色', is_embedding: false, is_index: false }
      ]
    }
  ]
}

/** 图谱导入 zip：desc.json + schema.json + entities.jsonl + edges.jsonl。 */
export async function graphImportZip (name: string): Promise<Buffer> {
  const entities = [
    { entity_type: 'Person', entity_id: 'person_alice', properties: { name: 'Alice', age: 30 } },
    { entity_type: 'Person', entity_id: 'person_bob', properties: { name: 'Bob', age: 28 } },
    { entity_type: 'Organization', entity_id: 'org_acme', properties: { name: 'Acme' } }
  ]
  const edges = [
    {
      edge_type: 'Knows',
      edge_id: 'edge_knows_alice_bob',
      source_id: 'person_alice',
      target_id: 'person_bob',
      properties: { since: '2020-01-01' }
    },
    {
      edge_type: 'WorksAt',
      edge_id: 'edge_alice_acme',
      source_id: 'person_alice',
      target_id: 'org_acme',
      properties: { role: 'Engineer' }
    }
  ]
  return createZip({
    'desc.json': JSON.stringify({
      name,
      desc: 'E2E 图谱导入样本',
      embedding: 'e2e-embedding'
    }, null, 2),
    'schema.json': JSON.stringify(GRAPH_SCHEMA, null, 2),
    'entities.jsonl': entities.map(item => JSON.stringify(item)).join('\n') + '\n',
    'edges.jsonl': edges.map(item => JSON.stringify(item)).join('\n') + '\n'
  })
}

/** 写一个临时文件；调用方负责在 finally 里删除。 */
export function tempFile (name: string, content: string | Buffer): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ragstudio-e2e-'))
  const file = path.join(dir, name)
  fs.writeFileSync(file, content)
  return file
}

export function cleanupTempFile (file: string): void {
  try {
    fs.rmSync(path.dirname(file), { recursive: true, force: true })
  } catch {
    // best effort
  }
}

/** 生成一篇含 100+ 切片的 markdown（按 maxWordCount=512 切分时约 110 片）。 */
export function largeMarkdown (paragraphs = 260): string {
  const lines = ['# E2E 大文档', '']
  for (let index = 0; index < paragraphs; index += 1) {
    lines.push(`## 段落 ${index + 1}`)
    lines.push(`这是第 ${index + 1} 段测试文本，用于验证大文档的分页与切片列表。` + '内容填充'.repeat(60))
    lines.push('')
  }
  return lines.join('\n')
}
