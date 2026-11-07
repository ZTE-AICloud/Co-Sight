/**
 * 通用 UI：components/、utils/、lib/、api/、constants/、service/、views/
 *
 * 同一个 key 必须在 zh/ 与 en/ 两侧同时存在（tests/unit/i18n.consistency.spec.js 会断言）。
 *
 * ⚠️ 写值时的两个坑（都是**静默**的，测试不红但用户看到的是残缺文案）：
 *   1. `|` 是 vue-i18n 的「复数分隔符」，值里要写竖线必须写成 `{'|'}`；
 *   2. `{name}` 是插值占位符，字面量花括号同样要包进 `{'...'}`。
 */
export default {
  // 文件预览（src/components/FilePreview.vue）

  // 名称校验器（src/utils/nameValidator.js）**没传 `t` 时**的内置兜底文案。
  // 措辞与 en.js 的 `agent.agentNameLimit*` / en/agentApp.js 的 `xxxNameLimit*`
  // 刻意不同：那是「传了 t」时用的键，本组是内置原文的英文版。

  // 知识图谱接口层（src/api/knowledgeGraph.js）的兜底文案。
  // '上传失败' 不在这里：复用 modules.kb.uploadFailed（同一个词的唯一 key）。
  knowledgeGraphApi: {
    networkFailed: 'Network connection failed. Check your network and try again',
    timeout: 'Request timed out. Please try again later',
    /** 带错误码的形态：{code} 是后端业务码 */
  },

  // 常量（src/constants/index.js）里会被当文案渲染的值
  constants: {
    /** 数值展示单位 */
    percentageCh: 'Percentage',
    /** 平台名（APPNAME，注释说是调 prompt 外部接口用的） */
    appName: 'AI Application Development Platform',
    /** ZHMAP.DOC：资源类型「文档」 */
    doc: 'Document'
  },

  // 对话流（src/views/Chat.vue、src/composables/chat/、src/utils/chat/）
  chat: {
    /** 流式请求没进流式时的状态后缀，拼在原 fallback 文案之后：`{fallback} (HTTP 502)` */
    httpStatusSuffix: ' (HTTP {status})'
  }
}
