import { computed } from 'vue'

export function useKnowledgeGraphBuild (formData, step2Form, operatorNotFound, templateNotFound, allFiles, operatorArgs, dynamicParams) {
  // 计算属性：是否可以构建
  const canBuild = computed(() => {

    // 如果算子不存在，不允许构建
    if (operatorNotFound.value) {
      return false
    }

    // 如果模版不存在，不允许构建
    if (templateNotFound.value) {
      return false
    }

    // 基础信息必填字段检查
    if (!formData.name || !formData.name.trim()) {
      return false
    }
    if (!formData.embeddingModel) {
      return false
    }

    // 必须已选择并上传至少一个文件
    if (allFiles.value.length === 0) {
      return false
    }

    // 必须已选择算子
    if (!step2Form.config.operator) {
      return false
    }

    // 根据所选算子的 args 判定是否填完必填参数
    const args = operatorArgs.value || []

    if (!args.length) {
      return true
    }

    // 检查每个必填参数
    return args.every((arg) => {
      const val = dynamicParams[arg.argName]
      return val !== undefined && val !== null && String(val).trim() !== ''
    })
  })

  return {
    canBuild
  }
}