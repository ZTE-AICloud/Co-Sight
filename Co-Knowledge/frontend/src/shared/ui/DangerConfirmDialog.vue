<template>
  <el-dialog
    v-if="dialogVisible"
    v-model="dialogVisible"
    class="danger-confirm-dialog"
    :title="title"
    width="500"
    append-to-body
  >
    <div class="container">
      <div class="left">
        <el-icon><WarnTriangleFilled /></el-icon>
      </div>
      <div class="right">
        <div class="top">
          <div class="title">
            {{ message }}
          </div>
          <div v-if="description" class="desc">
            {{ description }}
          </div>
        </div>
        <div class="bottom-area">
          <span class="label">{{ $t('public.verificationCode') }}</span>
          <CaptchaInput
            ref="captchaRef"
            v-model="inputValue"
            :custom-random-captcha="captchaCode"
            :show-error-tip="false"
            class="captcha-usage"
            @input="handleInput"
          />
        </div>
        <p v-if="captchaError" class="captcha-error" role="alert">
          {{ captchaError }}
        </p>
      </div>
    </div>
    <template #footer>
      <div class="dialog-footer">
        <el-button
          :disabled="disabledBtn"
          :loading="loading"
          type="danger"
          @click="handleConfirm"
        >
          {{ confirmText }}
        </el-button>
        <el-button @click="handleCancel">
          {{ cancelText }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script lang="ts" setup>
import { computed, ref } from 'vue'
import CaptchaInput from '@/shared/ui/CaptchaInput.vue'
import { WarnTriangleFilled } from '@/shared/lib/icons'
import { generateNumericCaptcha } from '@/shared/lib/captcha'
import { $t } from '@/app/i18n/i18n.js'

// 定义组件属性
interface Props {
  title?: string
  confirmText?: string
  cancelText?: string
}

// 默认值与 i18n 里 public.delete / public.cancel 是同一句话 —— 复用公共键，不另立新词。
// ⚠️ withDefaults 的默认值会被编译器内联进 props 定义，在**模块加载时**求值；
// 语言只在构建/启动时定一次（VUE_APP_LANG → localStorage），不存在运行中切语言，
// 所以不会出现「切了语言但默认值没跟着变」的问题。
withDefaults(defineProps<Props>(), {
  title: $t('public.delete'),
  confirmText: $t('public.delete'),
  cancelText: $t('public.cancel')
})

// 定义组件对外暴露的事件
const emits = defineEmits(['confirm', 'cancel'])

const captchaRef = ref<InstanceType<typeof CaptchaInput> | null>(null)
const dialogVisible = ref(false)
const inputValue = ref('')
const captchaCode = ref(generateNumericCaptcha())
const captchaError = ref('')
const loading = ref(false)
const message = ref('')
const description = ref('')

// 输入满 4 位就允许提交：错误由 handleConfirm 明确提示，而不是把按钮一直置灰
// 让用户猜「为什么不能点」。
const disabledBtn = computed(() => {
  return !inputValue.value || inputValue.value.length !== captchaCode.value.length
})

/**
 * 打开确认对话框
 * @param options 对话框配置选项
 */
function openDialog (options: {
  message: string
  description?: string
}) {
  message.value = options.message
  description.value = options.description || ''
  inputValue.value = ''
  captchaCode.value = generateNumericCaptcha()
  captchaError.value = ''
  loading.value = false
  dialogVisible.value = true
}

/**
 * 处理确认操作
 */
const handleConfirm = () => {
  if (!captchaRef.value?.validate()) {
    // 明确的错误反馈 + 自动换一张验证码；否则用户只会看到一个点不动的删除按钮。
    captchaError.value = $t('public.captchaInvalid')
    captchaCode.value = generateNumericCaptcha()
    inputValue.value = ''
    return
  }
  captchaError.value = ''

  loading.value = true
  emits('confirm', {
    done: () => {
      dialogVisible.value = false
      loading.value = false
    },
    setLoading: (loadingState: boolean) => {
      loading.value = loadingState
    }
  })
}

/**
 * 处理取消操作
 */
const handleCancel = () => {
  dialogVisible.value = false
  emits('cancel')
}

/**
 * 处理验证码输入
 */
const handleInput = () => {
  captchaError.value = ''
}

// 定义组件对外暴露的方法
defineExpose({
  openDialog
})
</script>

<style scoped>
.container {
  display: flex;
  justify-content: center;
}

.container .left .el-icon {
  font-size: 50px;
  color: red;
}

.container .right {
  margin-left: 10px;
}

.container .right .top .title {
  font-size: 16px;
  color: var(--rs-text-primary);
  line-height: 24px;
  font-weight: 600;
  max-width: 460px;
  word-break: break-all;
  overflow-wrap: anywhere;
}

.container .right .top .desc {
  max-width: 460px;
  margin-bottom: 16px;
  font-size: 14px;
  color: var(--rs-text);
  line-height: 22px;
}

.container .right .bottom-area {
  display: flex;
  align-items: center;
  margin-top: 4px;
}

:deep(.captcha-usage .captcha-field) {
  width: 80px;
}

:deep(.captcha-usage .captcha-code) {
  width: 80px;
  white-space: nowrap;
}

.container .right .bottom-area .label {
  margin-right: 16px;
  font-size: 14px;
  color: var(--rs-text);
  line-height: 18px;
}

.container .right .captcha-error {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--rs-danger);
}
</style>
