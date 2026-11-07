// 回归守卫：画布节点抽屉不能被当成「零引用死代码」整组删掉，
// 否则点击检索器齿轮报 `Cannot find module './retriever/Drawer'` —— 所有节点都编辑不了。
//
// 根因不是抽屉本身，而是 `FlowDetail.vue` 用**动态 require** 拼路径：
//
//     require(`./modules/${shapeAndPortIdMap[componentType]}/Drawer`)
//
// 静态扫描看不到这种引用，于是 48b442d「清理死代码」把 4 个 Drawer.vue 全删了。
// 这里钉住两件事，防止同一类清理再来一次：
//   1) 画布里注册的每种节点类型，都有对应的 Drawer.vue 文件；
//   2) 每个抽屉都导出 `sendOperatorListData` 与 `validate`（父组件提交时依赖这两个）。
//
// 只读源码、不挂组件：与 serialColumn.consistency.spec.js 同一手法（抽屉要登录态与
// 接口才渲染得出来，源码形状是单测里唯一稳定可判的）。
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  isExternalModelReranker
} from '../../src/features/workflow/lib/externalModelReranker.js'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const FLOW_VUE = path.join(ROOT, 'src/pages/workflow/WorkflowEditorPage.vue')
const MODULES_DIR = path.join(ROOT, 'src/features/workflow/modules')

/**
 * 节点类型 → 抽屉目录。
 *
 * 与 `FlowDetail.vue` 的 `shapeAndPortIdMap` 保持一致；改映射时两边一起改。
 * 这里写死而不是解析源码，是为了让「映射改了但目录没建」也能在测试里直接暴露。
 */
const NODE_DRAWERS = {
  PRE_RETRIEVER: 'preretriever',
  RETRIEVER: 'retriever',
  POST_RETRIEVER: 'postretriever',
  RESPONSE_SYNTHESIZER: 'responsesynthesizer'
}

describe('画布节点抽屉', () => {
  it('画布仍通过动态 require 加载抽屉', () => {
    const source = fs.readFileSync(FLOW_VUE, 'utf8')
    expect(source).toMatch(/require\(`[^`]*modules\/\$\{[^}]+\}\/Drawer`\)/)
  })

  it('每种画布节点都有对应的 Drawer.vue', () => {
    for (const [nodeType, dir] of Object.entries(NODE_DRAWERS)) {
      const file = path.join(MODULES_DIR, dir, 'Drawer.vue')
      const exists = fs.existsSync(file)
      // 用断言带出具体节点类型，失败信息比单纯「文件不存在」更容易定位
      expect(exists, `${nodeType} 的抽屉缺失：${path.relative(ROOT, file)}`).toBe(true)
    }
  })

  it('图谱检索抽屉暴露 include_edge_facts 开关', () => {
    const source = fs.readFileSync(
      path.join(MODULES_DIR, 'retriever/Drawer.vue'), 'utf8')
    expect(source).toContain('include_edge_facts')
    expect(source).toContain("modules.workflow.includeEdgeFacts")
  })


  it('每个抽屉都暴露父组件要求的 sendOperatorListData / validate', () => {
    for (const dir of Object.values(NODE_DRAWERS)) {
      const source = fs.readFileSync(path.join(MODULES_DIR, dir, 'Drawer.vue'), 'utf8')
      expect(source, `${dir}/Drawer.vue 缺少 sendOperatorListData`).toContain('function sendOperatorListData')
      expect(source, `${dir}/Drawer.vue 缺少 validate`).toContain('function validate')
      expect(source, `${dir}/Drawer.vue 没有 defineExpose 导出`).toMatch(/defineExpose\(\{[\s\S]*sendOperatorListData[\s\S]*validate[\s\S]*\}\)/)
    }
  })
})

describe('后检索抽屉的重排模型选择', () => {
  const source = fs.readFileSync(
    path.join(MODULES_DIR, 'postretriever/Drawer.vue'), 'utf8')

  it('模型清单来自 /system/rerank-models（与运行期解析同源）', () => {
    expect(source).toContain('getRerankModels')
  })

  it('ExternalModelReranker 的模型写在 kwargs.model（空值 = 跟随部署默认）', () => {
    expect(source).toMatch(/v-model="operator\.kwargs\.model"/)
    expect(source).toContain('EXTERNAL_MODEL_RERANKER_OPERATOR')
    expect(source).toContain('rerankModelFollowDefault')
  })

  it('只认 ExternalModelReranker 这一个逻辑 ID', () => {
    expect(isExternalModelReranker({ operator: 'ExternalModelReranker' })).toBe(true)
    expect(isExternalModelReranker({ operator: 'BgeLargeReranker' })).toBe(false)
    expect(isExternalModelReranker({})).toBe(false)
  })

  it('新节点默认带 model 键，缺失时补成空串', () => {
    const defaults = fs.readFileSync(
      path.join(MODULES_DIR, 'flowNodeDefaults.js'), 'utf8')
    expect(defaults).toContain('EXTERNAL_MODEL_RERANKER_OPERATOR')
    expect(defaults).toMatch(/top_n: 4/)
    expect(source).toContain('item.kwargs.model = \'\'')
  })
})
