<template>
  <div class="captcha-input">
    <span class="captcha-code">{{ displayCode }}</span>
    <el-input
      :model-value="modelValue"
      class="captcha-field"
      :maxlength="displayCode.length || 6"
      @update:model-value="onInput"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

interface Props {
  customRandomCaptcha?: string
  showErrorTip?: boolean
  modelValue?: string
}

const props = withDefaults(defineProps<Props>(), {
  customRandomCaptcha: '',
  showErrorTip: true,
  modelValue: ''
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'input', value: string): void
}>()

const displayCode = ref(props.customRandomCaptcha || '')

watch(
  () => props.customRandomCaptcha,
  (value) => {
    if (value) {
      displayCode.value = value
    }
  }
)

function onInput (value: string) {
  emit('update:modelValue', value)
  emit('input', value)
}

function validate (): boolean {
  return (props.modelValue || '') === displayCode.value
}

defineExpose({
  validate,
  get captcha () {
    return displayCode.value
  }
})
</script>

<style scoped>
.captcha-input {
  display: flex;
  align-items: center;
  gap: 8px;
}

.captcha-code {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 64px;
  height: 32px;
  padding: 0 8px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 2px;
  color: var(--rs-primary);
  background-color: var(--rs-bg-selected);
  border: 1px solid var(--rs-primary-border);
  border-radius: 4px;
  user-select: none;
}

.captcha-field {
  width: 96px;
}

/* 全局 `style/common.less` 里有一条 `.el-input__inner{padding-right:30px!important}`，
   本意是给下拉箭头留位（那边还配了 `padding-left:0`），但它写成了不带限定条件的
   `.el-input__inner`，于是连验证码输入框也吃进去 30px —— 调用方把本组件压到 80px 宽
   （`.captcha-usage .captcha-field`），扣掉这 30px 只剩 26px 内容区，而 4 位数字要
   26.7px，末位被 `text-overflow:ellipsis` 截成 `48...`。
   验证码框没有箭头，这里只在本组件内把这段内边距收掉；宽度不归本组件管，布局不变。
   全局那条已经带 `!important`，所以这里也必须带；两边都带时比选择器特异性，
   本规则编译成 `.captcha-input[data-v-x] .el-input__inner`（0,3,0）胜出，删掉 `!important` 就会输。 */
.captcha-input :deep(.el-input__inner) {
  padding-right: 8px !important;
}
</style>
