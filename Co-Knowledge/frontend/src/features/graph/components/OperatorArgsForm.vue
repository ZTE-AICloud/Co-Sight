<template>
  <!-- 联动参数区域：根据所选算子的 args 渲染 -->
  <template v-for="arg in operatorArgs" :key="arg.argName">
    <!-- schemaId → 模版下拉，必填 -->
    <el-form-item v-if="arg.argName === 'schemaId'" :label="$t('modules.kb.graphTemplate')" required>
      <el-select
        :model-value="dynamicParams.schemaId"
        :placeholder="templateNotFound ? $t('modules.kb.templateNotFoundPlaceholder') : $t('modules.kb.selectGraphTemplate')"
        filterable
        style="width: 100%"
        :disabled="currentOperator && (schemaInfo || templateNotFound)"
        @update:model-value="handleSchemaIdChange"
      >
        <!-- 如果schemaInfo存在，添加当前模版选项 -->
        <el-option
          v-if="schemaInfo && schemaInfo.schema_name"
          :key="schemaInfo.schema_id"
          :label="schemaInfo.schema_name"
          :value="schemaInfo.schema_id"
        />
        <!-- 其他模版选项 -->
        <el-option v-for="tpl in templateList" :key="tpl.schemaId || tpl.id" :label="tpl.schemaName || tpl.name" :value="tpl.schemaId || tpl.id" />
      </el-select>
    </el-form-item>

    <!-- llm → 大模型下拉，必填 -->
    <el-form-item v-else-if="arg.argName === 'llm'" :label="$t('modules.kb.llmModel')" required>
      <el-select 
        :model-value="dynamicParams.llm" 
        :placeholder="$t('modules.kb.selectLlmModel')" 
        filterable 
        style="width: 100%"
        :disabled="false"
        @update:model-value="handleLlmChange"
      >
        <el-option v-for="m in llmModelList" :key="m.value || m.id" :label="m.label || m.name || m.value" :value="m.value || m.id" />
      </el-select>
    </el-form-item>

    <!-- extractionProfile → 通用 / 通用+属性（同一次 LLM 调用，仅追加 prompt） -->
    <el-form-item v-else-if="arg.argName === 'extractionProfile'" :label="arg.description || $t('modules.kb.graphArgExtractionProfile')">
      <el-select
        :model-value="dynamicParams.extractionProfile || 'general'"
        style="width: 100%"
        @update:model-value="handleTextInput('extractionProfile', $event)"
      >
        <el-option :label="$t('modules.kb.extractionProfileGeneral')" value="general" />
        <el-option :label="$t('modules.kb.extractionProfileAttributes')" value="general_attributes" />
      </el-select>
    </el-form-item>

    <!-- overlap → 数字输入框，最小值0，最大值5120 -->
    <!-- 标签：优先用算子声明的 description（与下面两个通用分支同款数据驱动），
         没有才回落到本地化文案。不要硬写 `arg.argName`：界面上会直接显示英文键名。 -->
    <el-form-item v-else-if="arg.argName === 'overlap'" :label="arg.description || $t('modules.kb.graphArgOverlap')" required>
      <el-input-number
        :model-value="Number(dynamicParams.overlap) || 0"
        :min="0"
        :max="5120"
        :placeholder="arg.defaultValue || '0'"
        style="width: 100%"
        @update:model-value="handleNumberInput('overlap', $event)"
      />
    </el-form-item>

    <!-- chunkSize → 数字输入框，最小值512，最大值10240 -->
    <el-form-item v-else-if="arg.argName === 'chunkSize'" :label="arg.description || $t('modules.kb.graphArgChunkSize')" required>
      <el-input-number
        :model-value="Number(dynamicParams.chunkSize) || 512"
        :min="512"
        :max="10240"
        :placeholder="arg.defaultValue || '512'"
        style="width: 100%"
        @update:model-value="handleNumberInput('chunkSize', $event)"
      />
    </el-form-item>

    <!-- 数字类型参数 → 数字输入框 -->
    <el-form-item v-else-if="arg.type === 'number' || arg.argName.includes('Size') || arg.argName.includes('Overlap') || arg.argName.includes('Chars')" :label="arg.description || arg.argName" required>
      <el-input-number 
        :model-value="Number(dynamicParams[arg.argName]) || 0" 
        :placeholder="arg.defaultValue || ''"
        :min="0"
        :max="10000"
        :step="1"
        style="width: 100%"
        @update:model-value="handleNumberInput(arg.argName, $event)"
      />
    </el-form-item>

    <!-- 其他参数 → 普通输入框 -->
    <el-form-item v-else :label="arg.description || arg.argName" required>
      <el-input 
        :model-value="dynamicParams[arg.argName]" 
        :placeholder="arg.defaultValue || ''"
        :disabled="false"
        :readonly="false"
        style="width: 100%"
        @update:model-value="handleTextInput(arg.argName, $event)"
      />
    </el-form-item>
  </template>
</template>

<script setup>
const props = defineProps({
  operatorArgs: Array,
  dynamicParams: Object,
  schemaInfo: Object,
  templateNotFound: Boolean,
  currentOperator: Object,
  templateList: Array,
  llmModelList: Array
})

const emit = defineEmits(['update:dynamicParams'])

function handleSchemaIdChange (value) {
  emit('update:dynamicParams', { ...props.dynamicParams, schemaId: value })
}

function handleLlmChange (value) {
  emit('update:dynamicParams', { ...props.dynamicParams, llm: value })
}

function handleNumberInput (paramName, value) {
  emit('update:dynamicParams', { ...props.dynamicParams, [paramName]: value })
}

function handleTextInput (paramName, value) {
  emit('update:dynamicParams', { ...props.dynamicParams, [paramName]: value })
}
</script>

