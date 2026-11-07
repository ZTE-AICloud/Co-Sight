<template>
  <span class="ai-table-icon-root">
    <el-tooltip
      placement="top"
      :trigger="tips ? 'hover' : 'manual'"
      :content="tips"
      popper-class="ai-popper--table"
      :effect="effect"
    >
      <el-icon
        v-if="$slots.elIcon" :class="[
          'ai-button-icon',
          iconClass,
          {'ai-button-icon--disabled': disabled}
        ]"
        @click="clickIcon"
      >
        <slot name="elIcon" />
      </el-icon>
      <slot>
        <i
          v-if="!$slots.elIcon"
          :class="[
            'ai-button-icon',
            iconClass,
            {'ai-button-icon--disabled': disabled}
          ]"
          @click="clickIcon"
        />
      </slot>
    </el-tooltip>
  </span>
</template>

<script>
export default {
  // components: {
  //   Popover
  // },
  props: {
    iconClass: {},
    tips: {},
    disabled: {
      type: Boolean,
      default: false
    },
    effect: {
      type: String,
      default: 'dark'
    }
  },
  emits: ['click'],
  data () {
    return {};
  },
  created () {},
  mounted () {},
  methods: {
    clickIcon (e) {
      if (this.disabled) {
        return;
      }
      this.$emit('click', e);
    }
  }
};
</script>

<style scoped lang="less">
.ai-table-icon-root {
  line-height: 1;
}
.disabled {
  color: var(--el-color-info-light-5);
  cursor: not-allowed;
}
.option-icon {
  cursor: pointer;
}
</style>
