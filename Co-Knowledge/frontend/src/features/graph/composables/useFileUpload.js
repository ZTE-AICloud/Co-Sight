import { ref, computed } from 'vue'
import message from '@/shared/lib/message'
import { getKbaseFileLimitApi, getKnowledgeGraphFileListApi } from '@/features/graph/api/knowledgeGraph'

export function useFileUpload () {
  // 文件上传相关状态
  const uploadedFiles = ref([])
  const existingFiles = ref([])
  const fileLimit = ref(null)
  const deletedFiles = ref([])
  const remainingFiles = ref([])
  // 文件数量超限提示标志位，记录当前批次开始时的文件数量
  // 用于避免在同一次批量选择中重复提示
  const fileSelectionBatchCount = ref(null)
  // 上次文件选择的时间戳，用于判断是否是新的批次
  let lastFileSelectionTime = 0

  // 合并的文件列表
  const allFiles = computed(() => {
    const uploaded = uploadedFiles.value.map(file => ({
      ...file,
      isUploaded: true,
      fileFrom: '1' // 新上传的文件默认为本地文件
    }))
    const existing = existingFiles.value.map(file => ({
      ...file,
      isUploaded: false
    }))
    return [...uploaded, ...existing]
  })

  // 计算接受的文件类型（排除 zedx）
  const acceptAttr = computed(() => {
    const maxSizeMap = fileLimit.value?.maxSizeMap || {}
    // 过滤掉 zedx 文件
    const filteredKeys = Object.keys(maxSizeMap).filter(ext => ext.toLowerCase() !== 'zedx')
    if (filteredKeys.length === 0) {
      return '.pdf,.doc,.docx,.txt,.md,.xlsx,.xls,.csv'
    }
    return filteredKeys.map(ext => `.${ext}`).join(',')
  })

  // 加载文件上传限制
  async function loadFileLimit () {
    try {
      const limitRes = await getKbaseFileLimitApi(10)
      const data = limitRes || {}
      if (data.maxSizeMap && data.number) {
        fileLimit.value = { maxSizeMap: data.maxSizeMap, number: data.number }
      } else {
        fileLimit.value = null
      }
    } catch (e) {
      console.error('获取文件限制失败:', e)
      fileLimit.value = null
    }
  }

  // 加载已存在的文件列表
  // isCurrent：连续切换图谱时用来丢弃过期响应，避免把上一个图谱的文件写进当前页。
  async function loadExistingFiles (knowledgeGraphId, isCurrent = () => true) {
    try {
      const res = await getKnowledgeGraphFileListApi(knowledgeGraphId, {
        kbaseId: knowledgeGraphId,
        currentPage: 1,
        pageSize: 50,
        keyword: ''
      })
      if (!isCurrent()) {
        return
      }

      const fileRows = Array.isArray(res?.items) ? res.items : []
      if (fileRows.length) {
        existingFiles.value = fileRows.map((file) => ({
          id: file.id,
          title: file.title,
          fileSize: file.fileSize,
          fileFrom: file.fileFrom,
          isUploaded: false
        }))

        // 初始化剩余文件列表（所有已存在文件的ID）
        remainingFiles.value = existingFiles.value.map((file) => file.id)
      } else {
        // 空图谱也要清空：否则复用组件时会继续显示上一个图谱的来源文件。
        existingFiles.value = []
        remainingFiles.value = []
        if (res && !Array.isArray(res.items)) {
          console.warn('API响应数据格式不正确:', {
            res: !!res,
            data: res?.data,
            isArray: Array.isArray(res?.items)
          })
        }
      }
    } catch (error) {
      console.error('加载已存在文件失败:', error)
    }
  }

  // 处理文件选择
  function handleFileChange (file, proxy) {

    // 判断是否是新的文件选择批次
    // 如果距离上次文件选择超过500ms，认为是新的批次
    const now = Date.now()
    const isNewBatch = now - lastFileSelectionTime > 500
    lastFileSelectionTime = now

    const numberLimit = fileLimit.value?.number || 50
    const currentFileCount = allFiles.value.length

    // 如果是新的批次，重置批次记录
    // 这样可以确保每次新的文件选择都能重新判断是否需要提示
    if (isNewBatch) {
      fileSelectionBatchCount.value = null
    }

    // 记录批次开始时的文件数量（在检查超限之前）
    // 如果是新的一批文件选择（从未记录过），记录当前文件数量
    if (fileSelectionBatchCount.value === null) {
      fileSelectionBatchCount.value = currentFileCount
    }

    // 检查文件格式是否被屏蔽（zedx 文件不允许导入）
    const fileExt = file.name.split('.').pop()?.toLowerCase() || ''
    if (fileExt === 'zedx') {
      message.error(proxy.$t('knowledge.import.valid1', {
        fileName: file.name,
        type: Object.keys(fileLimit.value?.maxSizeMap || {}).filter(ext => ext.toLowerCase() !== 'zedx').join(', ')
      }))
      return
    }

    // 来自接口的限制，单位MB，需要转换为字节
    const limitMap = fileLimit.value?.maxSizeMap || {}
    const maxSizeMb = limitMap[fileExt]
    const maxSize = typeof maxSizeMb === 'number' ? maxSizeMb * 1024 * 1024 : undefined

    if (typeof maxSize === 'number' && file.size > maxSize) {
      message.error(proxy.$t('modules.kb.fileSizeExceeded', { fileName: file.name, fileExt, maxSize: maxSizeMb }))
      return
    }

    // 检查文件数量限制（使用上面已获取的numberLimit）
    if (currentFileCount >= numberLimit) {
      // 检查当前批次是否已经提示过
      // 如果批次开始时的文件数量 < 限制，说明是当前批次导致的超限，需要提示
      // 如果批次开始时的文件数量 >= 限制，且是新的批次（刚刚重置过），说明是在已有超限的基础上继续选择，也应该提示
      // 如果批次开始时的文件数量 >= 限制，但不是新批次，说明是同一批次中的后续文件，已在之前提示过，不重复提示
      const shouldShowError = (fileSelectionBatchCount.value !== null && fileSelectionBatchCount.value < numberLimit) ||
                              (isNewBatch && fileSelectionBatchCount.value >= numberLimit)

      if (shouldShowError) {
        message.error(proxy.$t('modules.kb.fileCountExceeded', { limit: numberLimit }))
        // 标记当前批次已经提示过（通过将批次数量设为限制值）
        fileSelectionBatchCount.value = numberLimit
      }
      return
    }

    // 添加到文件列表
    uploadedFiles.value.push({
      title: file.name,
      fileSize: file.size,
      raw: file.raw,
      isUploaded: true
    })
  }

  // 删除文件
  function removeFile (index) {
    const file = allFiles.value[index]
    if (file.isUploaded) {
      // 删除新上传的文件
      const uploadedIndex = uploadedFiles.value.findIndex(f => f.title === file.title)
      if (uploadedIndex > -1) {
        uploadedFiles.value.splice(uploadedIndex, 1)
      }
    } else {
      // 删除已存在的文件 - 添加到删除列表
      const existingIndex = existingFiles.value.findIndex(f => f.id === file.id)
      if (existingIndex > -1) {
        const deletedFile = existingFiles.value[existingIndex]
        existingFiles.value.splice(existingIndex, 1)

        // 添加到删除文件列表
        if (!deletedFiles.value.includes(deletedFile.id)) {
          deletedFiles.value.push(deletedFile.id)
        }

        // 从剩余文件列表中移除
        const remainingIndex = remainingFiles.value.indexOf(deletedFile.id)
        if (remainingIndex > -1) {
          remainingFiles.value.splice(remainingIndex, 1)
        }
      }
    }
    // 删除文件后，重置批次记录，允许下次选择时重新记录批次
    // 这样可以确保在删除文件后再次选择时，如果超限会重新提示
    fileSelectionBatchCount.value = null
  }

  /**
   * 恢复一个已移除的已有文件（「恢复已移除的 N 个文件」）。
   * 只操作本地三份列表：existingFiles / remainingFiles / deletedFiles。
   */
  function restoreFile (file) {
    if (!file || existingFiles.value.some(item => item.id === file.id)) {
      return
    }
    existingFiles.value.push(file)
    deletedFiles.value = deletedFiles.value.filter(id => id !== file.id)
    if (!remainingFiles.value.includes(file.id)) {
      remainingFiles.value.push(file.id)
    }
    fileSelectionBatchCount.value = null
  }

  // 格式化文件大小
  function formatFileSize (bytes) {
    if (bytes === 0) {
      return '0 MB'
    }
    const mb = bytes / (1024 * 1024)
    return mb.toFixed(2)
  }

  return {
    uploadedFiles,
    existingFiles,
    fileLimit,
    deletedFiles,
    remainingFiles,
    allFiles,
    acceptAttr,
    loadFileLimit,
    loadExistingFiles,
    handleFileChange,
    removeFile,
    restoreFile,
    formatFileSize
  }
}