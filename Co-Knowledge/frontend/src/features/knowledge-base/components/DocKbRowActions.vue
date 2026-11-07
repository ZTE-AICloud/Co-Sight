<!--
  文档知识库列表「操作」列的单元格：详情按钮 + 「更多」下拉。

  为什么这块可以独立成组件（边界）：
  - **props 进（`row`）、events 出**：`@detail(row)` 与 `@command(command, row)`。
    真正的动作（路由跳转 / 打开编辑弹窗 / 删除确认）全在父组件的
    `kbaseMoreDropdown` 分发表里；本组件不 import `@/api/*`、不碰列表取数，
    不读父组件的任何响应式变量。
  - 「修改 / 删除」的可用性闸门在本组件内判定：行级鉴权标记
    （父组件里的 `kbAuth`，这里提成 `isRowLocked` computed，取值语义不变）
    与 `lib/list-status` 的 `isDocKbModifyEnabled` —— 它们都是 `row.action` / `row.status`
    的纯函数，没有别的输入。
  - per-row 的 `:key`（`kbase-button-<id>`）放在**父组件的标签上**：
    它在插槽内容列表里才有意义，搬进组件内部会变成不生效的死绑定。

  留在父组件（不属于本组件职责）：
  - `moreHandleCommand` / `kbaseMoreDropdown`（命令 → 具体动作）；
  - 行点击跳转、删除确认弹窗；
  - 表格取数 `getTableDataApi` 与列表刷新回环 —— 那部分拆进子组件会变成
    "props 十几个回调"的假组件。

  注意「自优化任务」菜单项在父组件里是注释状态（闸门 `isAISEnvironment` 在父组件）。
  这里按原样保留注释与位置；真要恢复时**以 prop 把闸门传进来**，别直接引用未定义的变量
  （模板里对未定义变量的判断不吃构建期报错，只会静默变成"恒显示"）。
-->
<template>
  <!-- 操作列只有一个「更多」按钮；详情入口收进菜单，
       不在行尾占一个文字按钮（否则 75px 的操作列会被挤出表外）。 -->
  <div class="flex-box--align-center">
    <el-dropdown trigger="click">
      <button class="ux-icon-button" :aria-label="$t('app.more')">
        <MoreFilled class="more-icon" />
      </button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item class="more-buttons-dropdown-item--mini" @click="handleDetail">
            <View />
            {{ $t('knowledge.detail') }}
          </el-dropdown-item>
          <el-dropdown-item :disabled="isRowLocked || !isDocKbModifyEnabled(statusNum)" class="more-buttons-dropdown-item--mini" @click="handleCommand('modifyKbase')">
            <Edit />
            {{ $t('public.modify') }}
          </el-dropdown-item>
          <!-- 不提供「发布」菜单项：发布接口（POST /asset/publish/{id}）在后端没有路由、
               恒返回 404（死入口）。发布闸门 isDocKbPublishEnabled 在 lib/list-status
               里保留并被单测钉住。 -->
          <el-dropdown-item divided :disabled="isRowLocked" class="more-buttons-dropdown-item--mini" @click="handleCommand('deleteKbase')">
            <Delete />
            {{ $t('public.delete') }}
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<script lang="ts" setup>
import { computed } from 'vue';
import { Delete, Edit, MoreFilled, View } from '@element-plus/icons-vue';
// 文档知识库的状态闸门：与知识图谱列表页共用同一份实现（允许集合在 lib 里逐条注明）
import { toNum, isDocKbModifyEnabled } from '@/features/knowledge-base/lib/list-status';

const props = defineProps({
  /** 表格行（列表 `#table-operation` 插槽给的 `tableOptionData`） */
  row: { type: Object, default: () => ({}) }
});

// 具名元组写法（与 views/flow/DrawerFrame.vue 一致）：调用签名写法 `(e: 'x', p: any): void`
// 会被 eslint 的 no-unused-vars 当成未使用的形参报 5 条 error
const emit = defineEmits<{
  /** 点了「详情」 */
  detail: [row: any];
  /** 「更多」菜单里选了某条命令（第二参是行；命令字面量与父组件 kbaseMoreDropdown 的键一致） */
  command: [command: string, row: any];
}>();

/**
 * 行级鉴权标记（原样搬自父组件的 `kbAuth`）：`action === 'c'` 时整行的更多操作都禁用。
 *
 * ⚠️ 为什么保留 `data.action &&` 这一截、而不是简化成 `action === 'c'`：
 * `action === ''` 时本计算值返回**空串**，而 ElDropdownItem 的 `disabled` 是「只声明
 * Boolean」的 prop —— Vue 会把空串转成 `true`，于是删除项被禁用。这是既有行为
 * （tests/unit/DocKbRowActions.spec.js 有用例钉住），改动前请先确认线上
 * 行数据的 action 取值；改成纯布尔比较会**静默改变**空串行的删除闸门。
 */
const isRowLocked = computed(() => {
  const data: any = props.row;
  return data.action && data.action === 'c';
});

/** 原模板每支都调一次 toNum(row.status)，同一个值，这里只算一次 */
const statusNum = computed(() => toNum((props.row as any).status));

function handleDetail () {
  emit('detail', props.row);
}

function handleCommand (command: string) {
  emit('command', command, props.row);
}
</script>
