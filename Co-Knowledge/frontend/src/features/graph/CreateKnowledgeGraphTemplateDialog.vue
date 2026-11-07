<template>
  <el-dialog
    v-model="dialogVisible"
    :title="$t('modules.kb.createKnowledgeGraphTemplate')"
    width="600px"
    :before-close="beforeCloseHandle"
    :close-on-click-modal="false"
  >
    <el-form
      v-if="dialogVisible"
      ref="formRef"
      :model="formData"
      :rules="formRules"
      :label-width="$globalZh ? '120px' : '130px'"
    >
      <el-form-item :label="$t('modules.kb.knowledgeGraphTemplateName')" prop="name">
        <el-input
          v-model="formData.name"
          v-trim
          :placeholder="$t('modules.kb.inputKnowledgeGraphTemplateName')"
          maxlength="99"
          show-word-limit
          class="form-item-content--400"
        />
      </el-form-item>
      <el-form-item :label="$t('modules.kb.knowledgeGraphTemplateDescription')" prop="description" required>
        <el-input
          v-model="formData.description"
          :placeholder="$t('modules.kb.inputKnowledgeGraphTemplateDescription')"
          maxlength="1000"
          show-word-limit
          type="textarea"
          :rows="4"
          class="form-item-content--400 textarea-with-limit"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <div class="dialog-footer-center">
        <el-button
          :loading="loading"
          :disabled="loading"
          type="primary"
          @click="submitHandle"
        >
          {{ $t('modules.kb.create') }}
        </el-button>
        <el-button plain @click="closeHandle">
          {{ $t("public.cancel") }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, getCurrentInstance } from 'vue'
import appState from '@/app/state'

const { proxy } = getCurrentInstance() as any

// 获取子组件的引用
const formRef = ref()


// 获取初始化表单数据
function getInitFormData() {
  // 生成默认名称：用户名+时间戳
  const userName = appState.user.personName || appState.user.userName || 'user'
  const timestamp = Date.now()
  const defaultName = `${userName}_${timestamp}`

  return {
    name: defaultName,
    description: ''
  }
}

// 表单数据
const formData = ref(getInitFormData())

// 统一的名称字段验证函数（与后端校验规则保持一致）
const validateName = (_rule: any, value: string, callback: any) => {
  if (!value) {
    return callback(new Error(proxy.$t('modules.kb.inputKnowledgeGraphTemplateName')))
  }

  // 1. 长度检查：必须在1-99之间
  const length = value.length
  if (length < 1 || length > 99) {
    return callback(new Error(proxy.$t('modules.kb.templateNameLengthError')))
  }

  return callback()
}

// 统一的描述字段验证函数（与后端校验规则保持一致）
const validateDesc = (_rule: any, value: string, callback: any) => {
  if (!value) {
    return callback(new Error(proxy.$t('modules.kb.inputKnowledgeGraphTemplateDescription')))
  }

  // 1. 长度检查：使用原始长度（不是trim后的长度），必须在1-1000之间
  const length = value.length
  if (length < 1 || length > 1000) {
    return callback(new Error(proxy.$t('modules.kb.descLengthInvalid', { length })))
  }

  // 2. 检查是否为全空格或空白字符
  if (value.trim() === '') {
    return callback(new Error(proxy.$t('modules.kb.descCannotBeWhitespace')))
  }

  return callback()
}

// 表单验证规则
const formRules = ref({
  name: [{
    validator: validateName,
    trigger: ['blur', 'change']
  }, {
    // \u4e0e\u540e\u7aef SCHEMA_NAME_PATTERN\uff08`^[a-zA-Z0-9_\u4e00-\u9fa5]+$`\uff09\u5bf9\u9f50\u3002
    // \u53ea\u5141\u8bb8\u5b57\u6bcd\u3001\u6570\u5b57\u3001\u4e0b\u5212\u7ebf\u4e0e\u4e2d\u6587\uff1b`.` \u548c `-` \u4f1a\u8ba9\u300cTEST-regress-tpl\u300d\u8fd9\u7c7b\u540d\u5b57
    // \u901a\u8fc7\u524d\u7aef\u6821\u9a8c\u3001\u5230\u4fdd\u5b58\u65f6\u624d\u88ab\u540e\u7aef\u62d2\u7edd\u3002\u524d\u7aef\u63d0\u524d\u62e6\u4f4f\uff0c\u63d0\u793a\u843d\u5728\u540d\u79f0\u8f93\u5165\u6846\u4e0a\u3002
    pattern: /^[\w\u4e00-\u9fa5]+$/,
    message: proxy.$t('modules.kb.templateNameCharsError'),
    trigger: ['blur', 'change']
  }],
  description: [{
    required: true,
    validator: validateDesc,
    trigger: ['blur', 'change']
  }]
})

// 对话框是否显示
const dialogVisible = ref(false)

// 加载状态
const loading = ref(false)

/**
 * 打开对话框
 */
function openDialog() {
  loading.value = false
  dialogVisible.value = true
  formData.value = getInitFormData()
}

/**
 * 关闭对话框
 */
function closeHandle() {
  dialogVisible.value = false
  formData.value = getInitFormData()
}

/**
 * 提交表单
 */
async function submitHandle() {
  formRef.value.validate(async (valid: any) => {
    if (valid) {
      loading.value = true

      try {
        // 先保存表单数据，避免被 closeHandle 清空
        const templateName = formData.value.name
        const templateDescription = formData.value.description

        // 关闭对话框
        closeHandle()

        // 跳转到图谱模板设计器页面，传递模板名称和描述
        proxy.$router.push({
          name: 'graph-template',
          params: {
            templateId: 'new'
          },
          query: {
            templateName: templateName,
            templateDescription: templateDescription
          }
        })

      } catch (error) {
        // 冒号在 public.createFail 词条值里（zh '：'/ en ': '），此处不再拼「：」
        proxy.$message.error(`${proxy.$t('public.createFail')}${error.message || proxy.$t('public.noData')}`)
      } finally {
        loading.value = false
      }
    }
  })
}

/**
 * 关闭前处理
 * @param done 回调函数
 */
function beforeCloseHandle(done: Function) {
  closeHandle()
  done()
}

// 定义组件对外暴露的方法
defineExpose({
  openDialog
})
</script>

<style lang="less" scoped>
:deep(.el-dialog__body) {
  padding: 20px;
  text-align: left;
}

:deep(.el-form) {
  width: 100%;
  margin-left: -20px;
}

.form-item-content--400 {
  width: 400px;
}

// 修改 textarea 字符计数显示位置，使其显示在输入框下方，避免与内容重叠
:deep(.el-form-item) {
  // 确保表单项容器允许溢出显示
  overflow: visible !important;

  // 为包含 textarea 的表单项添加底部间距
  .vn-textarea,
  .el-textarea {
    position: relative !important;
    margin-bottom: 20px !important; // 为字符计数预留空间
    overflow: visible !important; // 确保字符计数可以显示在容器外

    // 确保 textarea 内部有足够的底部 padding，避免内容与字符计数重叠
    .el-textarea__inner {
      padding-bottom: 25px !important;
    }

    // 字符计数样式 - 使用多种选择器确保覆盖
    .vn-input__count,
    .el-input__count {
      background: var(--vn-fill-color-blank, var(--el-fill-color-blank, var(--rs-bg-card))) !important;
      color: var(--vn-input-count-color, var(--el-text-color-placeholder, var(--rs-text-3))) !important;
      font-size: 12px !important;
      line-height: 14px !important;
      position: absolute !important;
      right: 8px !important;
      bottom: -19px !important;
      z-index: 10 !important;
    }
  }

  // 确保 el-input__wrapper 也允许溢出
  .vn-textarea .el-input__wrapper,
  .el-textarea .el-input__wrapper {
    overflow: visible !important;
  }
}

// 全局覆盖 Element Plus 的默认样式（针对 textarea）
:deep(.vn-textarea .vn-input__count),
:deep(.vn-textarea .el-input__count),
:deep(.el-textarea .vn-input__count),
:deep(.el-textarea .el-input__count),
:deep(.el-form-item .el-textarea .el-input__count),
:deep(.el-form-item .vn-textarea .el-input__count) {
  bottom: -19px !important;
  right: 8px !important;
  position: absolute !important;
  background: var(--vn-fill-color-blank, var(--el-fill-color-blank, var(--rs-bg-card))) !important;
  color: var(--vn-input-count-color, var(--el-text-color-placeholder, var(--rs-text-3))) !important;
  font-size: 12px !important;
  line-height: 14px !important;
  z-index: 10 !important;
}

// 针对 el-form-item__content 容器
:deep(.el-form-item__content) {
  overflow: visible !important;

  .vn-textarea,
  .el-textarea {
    overflow: visible !important;
  }
}

// 按钮区域居中样式
.dialog-footer-center {
  display: flex;
  justify-content: center;
  gap: 12px;
}
</style>
