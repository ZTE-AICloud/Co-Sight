<template>
  <div class="controls-wrapper">
    <div class="controls-panel">
      <div class="controls-main">
        <div class="controls-row">
          <div class="controls-left">
            <!-- 实体搜索：输入后交给详情页的 handleSearchInput，
                 由 GraphVisualization 在客户端过滤当前画布。 -->
            <el-input
              :model-value="props.searchKeyword"
              class="control-search"
              :placeholder="t('modules.kb.searchEntityPlaceholder')"
              :prefix-icon="Search"
              clearable
              @input="$emit('search-input', $event)"
              @clear="$emit('search-clear')"
            />
            <el-select
              :model-value="entityTypeFilter"
              class="control-type"
              :placeholder="t('modules.kb.allEntityTypes')"
              clearable
              @change="handleEntityTypeFilter"
            >
              <el-option
                v-for="type in entityTypes"
                :key="type"
                :label="type"
                :value="type"
              />
            </el-select>
            <div class="control-item control-item--stat">
              <span class="label">{{ t('modules.kb.totalNodes') }}</span>
              <span class="value">{{ props.totalNodes }}</span>
            </div>
            <div class="control-item control-item--stat">
              <span class="label">{{ t('modules.kb.totalEdges') }}</span>
              <span class="value">{{ props.totalEdges }}</span>
            </div>
            <div class="control-item control-item--stat">
              <span class="label">{{ t('modules.kb.zoomLevel') }}</span>
              <span class="value">{{ props.zoomLevel }}%</span>
            </div>

          </div>
          <div class="controls-right" :key="queryType">
            <el-tooltip :content="queryButtonTooltip" placement="top" :disabled="!isQueryButtonDisabled">
              <span>
                <el-button
                  type="primary"
                  class="control-button"
                  :disabled="isQueryButtonDisabled"
                  @click="handleExecuteQuery"
                >
                  <Search />{{ t('modules.kb.query') }}
                </el-button>
              </span>
            </el-tooltip>
            <el-button class="control-button" :class="{ 'is-active': advancedOpen }" @click="advancedOpen = !advancedOpen">
              <Filter />{{ t('modules.kb.advancedQuery') }}
            </el-button>
          </div>
          <div class="controls-right graph-data-actions">
            <TableRefreshButton
              :label="t('modules.kb.refreshGraph')"
              :refresh="handleRefreshGraph"
              :inline-feedback="!floating"
            />
          </div>
        </div>
      </div>

      <el-drawer
        v-model="advancedOpen"
        direction="rtl"
        size="min(480px, 100vw)"
        append-to-body
        class="graph-advanced-drawer"
      >
        <template #header>
          <h2 class="workspace-panel-title text-section-title">{{ t('modules.kb.advancedQuery') }}</h2>
        </template>
        <p class="advanced-drawer-intro text-secondary">{{ t('modules.kb.advancedQueryIntro') }}</p>
        <div class="controls-body controls-drawer-body" :key="`controls-body-${queryType}`">
          <el-form label-position="top" class="advanced-query-form" @submit.prevent>
          <el-form-item :label="t('modules.kb.graphLimitLabel')" class="query-limit-field">
            <el-input-number
              :model-value="props.limitValue"
              :min="1"
              :max="1000"
              :controls="true"
              @change="handleLimitChange"
              @blur="handleLimitBlur"
            />
            <p class="query-limit-help text-caption">
              {{ t('modules.kb.graphLimitHelp', { default: DEFAULT_LIMIT_VALUE, max: 1000 }) }}
            </p>
          </el-form-item>
          <el-form-item :label="t('modules.kb.queryType')" class="advanced-query-type">
            <el-select v-model="queryType" size="default" class="query-type-select" @change="handleQueryTypeChange">
              <el-option
                v-for="option in queryTypeOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>
          <!-- 复杂条件收在「高级查询」里，深度 / 方向也一并放进来。 -->
          <div v-if="queryType === 'subgraph'" class="advanced-param-row">
            <el-form-item :label="t('modules.kb.depth')" class="advanced-param-item">
              <el-input-number
                :model-value="props.depthValue"
                :min="1"
                :max="100"
                :controls="true"
                @change="handleDepthChange"
              />
            </el-form-item>
            <el-form-item :label="t('modules.kb.direction')" class="advanced-param-item">
              <el-select
                v-model="subgraphDirection"
                size="default"
                clearable
              >
                <el-option
                  v-for="option in directionOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
            </el-form-item>
          </div>
          <el-form-item :label="t('modules.kb.conditionCombine')" class="condition-combine">
            <el-radio-group v-model="conditionCombine">
              <el-radio-button value="and">{{ t('modules.kb.conditionMatchAll') }}</el-radio-button>
              <el-radio-button value="or">{{ t('modules.kb.conditionMatchAny') }}</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <div v-if="queryType !== 'subgraph'">
            <div
              v-for="(group, groupIndex) in activeGroups"
              :key="group.id"
              class="query-condition entity-group"
            >
              <div class="condition-label text-secondary">
                <span>{{ t('modules.kb.conditionIndex', { index: groupIndex + 1 }) }}</span>
                <el-tooltip :content="t('modules.kb.atLeastOneQueryCondition')" placement="top" :disabled="!isOnlyActiveGroup">
                  <button
                    type="button"
                    class="icon-button danger-icon"
                    :aria-label="t('modules.kb.removeConditionIndex', { index: groupIndex + 1 })"
                    :disabled="isOnlyActiveGroup"
                    @click="removeActiveGroup(groupIndex)"
                  >
                    <Delete />
                  </button>
                </el-tooltip>
              </div>
              <div class="condition-fields entity-group-row">
                <div class="entity-editor">
                  <label class="entity-editor-label">
                    {{ queryType === 'relation' ? t('modules.kb.edgeType') : t('modules.kb.entityType') }}
                  </label>
                  <el-select
                    v-model="group.type"
                    clearable
                    size="default"
                    class="entity-select"
                    :placeholder="activeTypePlaceholder"
                    @change="handleActiveGroupTypeChange(groupIndex)"
                  >
                    <el-option
                      v-for="type in activeTypes"
                      :key="type"
                      :label="type"
                      :value="type"
                    />
                  </el-select>
                </div>

                <div class="property-editor">
                  <div
                    v-for="(row, rowIndex) in group.conditions"
                    :key="row.id"
                    class="condition-row"
                  >
                    <div class="col col-prop">
                    <el-select
                      v-model="row.prop"
                      clearable
                      class="condition-select"
                      :disabled="!group.type"
                      :placeholder="group.type ? t('modules.kb.selectProperty') : t('modules.kb.selectTypeFirst')"
                      @change="handlePropChange(groupIndex, rowIndex)"
                    >
                      <el-option
                          v-for="option in getPropertyOptions(group.type, queryType)"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                    </div>
                    <div class="col col-operator">
                      <el-select
                        v-model="row.operator"
                        class="condition-select"
                        clearable
                        @change="handleOperatorChange(row)"
                      >
                        <el-option
                          v-for="option in getOperatorOptions(group.type, row.prop, queryType)"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                    </div>
                    <div class="col col-value">
                      <div class="value-input-wrapper">
                        <el-input
                          v-model="row.value"
                          :disabled="!row.prop"
                          :placeholder="getValuePlaceholder(group.type, row.prop, row.operator, queryType)"
                          @input="handleValueInput(row)"
                        />
                        <div v-if="row.error" class="error-msg">{{ row.error }}</div>
                      </div>
                    </div>
                    <div class="col col-actions">
                      <button
                        type="button"
                        class="icon-btn-circle icon-btn-circle--dark"
                        :disabled="!group.type"
                        @click="addCondition(groupIndex, rowIndex)"
                      >
                        <img :src="AddIcon" alt="add">
                      </button>
                      <el-tooltip :content="t('modules.kb.atLeastOneQueryCondition')" placement="top" :disabled="!isOnlyCondition(group)">
                        <button
                          type="button"
                          class="icon-btn-circle icon-btn-circle--dark"
                          :disabled="isOnlyCondition(group)"
                          @click="removeCondition(groupIndex, rowIndex)"
                        >
                          <Delete class="danger-icon" />
                        </button>
                      </el-tooltip>
                    </div>
                  </div>

                  <div class="condition-footer">
                    <button
                      type="button"
                      class="add-condition-row"
                      :disabled="!group.type"
                      @click="addCondition(groupIndex, group.conditions.length - 1, true)"
                    >
                      <el-icon><Plus /></el-icon>
                      <span>{{ t('modules.kb.addAttributeCondition') }}</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
            <el-button class="add-condition-card" @click="addActiveGroup">
              <Plus />{{ t('modules.kb.addCondition') }}
            </el-button>
          </div>
          <div v-else>
            <div class="entity-group">
              <div class="entity-group-row">
                <div class="entity-editor">
                  <div class="entity-editor-row">
                    <label class="entity-editor-label">{{ t('modules.kb.startEntityType') }}</label>
                    <el-select
                      v-model="subgraphStartGroup.type"
                      clearable
                      size="default"
                      class="entity-select"
                      :placeholder="t('modules.kb.selectStartEntityType')"
                      @change="handleSubgraphStartTypeChange"
                    >
                      <el-option
                        v-for="type in entityTypes"
                        :key="type"
                        :label="type"
                        :value="type"
                      />
                    </el-select>
                  </div>
                </div>
                <div class="property-editor">
                  <div class="condition-header">
                    <span class="col col-actions" />
                    <span class="col col-logic">{{ t('modules.kb.logicToggle') }}</span>
                    <span class="col col-prop">{{ t('modules.kb.property') }}</span>
                    <span class="col col-operator">{{ t('modules.kb.operator') }}</span>
                    <span class="col col-value">{{ t('modules.kb.value') }}</span>
                  </div>
                  <div
                    v-for="(row, rowIndex) in subgraphStartGroup.conditions"
                    :key="row.id"
                    class="condition-row"
                  >
                    <div class="col col-actions">
                      <button
                        type="button"
                        class="icon-btn-circle icon-btn-circle--dark"
                        :disabled="!subgraphStartGroup.type"
                        @click="addSubgraphStartCondition(rowIndex)"
                      >
                        <img :src="AddIcon" alt="add">
                      </button>
                      <el-tooltip :content="t('modules.kb.atLeastOneQueryCondition')" placement="top" :disabled="subgraphStartGroup.conditions.length > 1">
                        <button
                          type="button"
                          class="icon-btn-circle icon-btn-circle--dark"
                          :disabled="subgraphStartGroup.conditions.length <= 1"
                          @click="removeSubgraphStartCondition(rowIndex)"
                        >
                          <Delete class="danger-icon" />
                        </button>
                      </el-tooltip>
                    </div>
                    <div class="col col-logic logic-cell">
                      <el-select
                        v-if="rowIndex === 0 && subgraphStartGroup.conditions.length > 1"
                        v-model="subgraphStartGroup.logicOperator"
                        size="small"
                        class="condition-select condition-select--logic"
                      >
                        <el-option
                          v-for="option in logicOptions"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                      <span v-else class="logic-placeholder">
                        {{ rowIndex === 0 ? '' : getLogicLabel(subgraphStartGroup.logicOperator) }}
                      </span>
                    </div>
                    <div class="col col-prop">
                    <el-select
                      v-model="row.prop"
                      clearable
                      size="small"
                      class="condition-select"
                      :disabled="!subgraphStartGroup.type"
                      :placeholder="subgraphStartGroup.type ? t('modules.kb.selectProperty') : t('modules.kb.selectTypeFirst')"
                      @change="handleSubgraphStartPropChange(rowIndex)"
                    >
                      <el-option
                          v-for="option in getPropertyOptions(subgraphStartGroup.type, 'entity')"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                    </div>
                    <div class="col col-operator">
                      <el-select
                        v-model="row.operator"
                        size="small"
                        class="condition-select"
                        clearable
                        @change="handleOperatorChange(row)"
                      >
                        <el-option
                          v-for="option in getOperatorOptions(subgraphStartGroup.type, row.prop, 'entity')"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                    </div>
                    <div class="col col-value">
                      <div class="value-input-wrapper">
                        <el-input
                          v-model="row.value"
                          size="small"
                          :disabled="!row.prop"
                          :placeholder="getValuePlaceholder(subgraphStartGroup.type, row.prop, row.operator, 'entity')"
                          @input="handleValueInput(row)"
                        />
                        <div v-if="row.error" class="error-msg">{{ row.error }}</div>
                      </div>
                    </div>
                  </div>
                  <div class="condition-footer">
                    <button
                      type="button"
                      class="icon-btn-circle icon-btn-circle--primary"
                      :disabled="!subgraphStartGroup.type"
                      @click="addSubgraphStartCondition(subgraphStartGroup.conditions.length - 1, true)"
                    >
                      <el-icon><Plus /></el-icon>
                      <span>{{ t('modules.kb.addAttributeCondition') }}</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
            <div class="entity-group" v-for="(group, groupIndex) in subgraphEntityGroups" :key="group.id">
              <div class="entity-group-row">
                <div class="entity-editor">
                  <div class="entity-editor-row">
                    <label class="entity-editor-label">{{ t('modules.kb.pathEntityType') }}</label>
                    <el-select
                      v-model="group.type"
                      size="default"
                      class="entity-select"
                      :placeholder="t('modules.kb.selectPathEntityType')"
                      clearable
                      @change="handleSubgraphEntityTypeChange(groupIndex)"
                    >
                      <el-option
                        v-for="type in entityTypes"
                        :key="type"
                        :label="type"
                        :value="type"
                      />
                    </el-select>
                    <div class="entity-editor-actions">
                      <button type="button" class="icon-btn-circle icon-btn-circle--primary" @click="addSubgraphEntityGroup">
                        <img :src="AddIcon" alt="add">
                      </button>
                      <el-tooltip :content="t('modules.kb.atLeastOneQueryCondition')" placement="top" :disabled="subgraphEntityGroups.length > 1">
                        <button
                          type="button"
                          class="icon-btn-circle icon-btn-circle--primary"
                          :disabled="subgraphEntityGroups.length <= 1"
                          @click="removeSubgraphEntityGroup(groupIndex)"
                        >
                          <Delete class="danger-icon" />
                        </button>
                      </el-tooltip>
                    </div>
                  </div>
                </div>
                <div class="property-editor">
                  <div class="condition-header">
                    <span class="col col-actions" />
                    <span class="col col-logic">{{ t('modules.kb.logicToggle') }}</span>
                    <span class="col col-prop">{{ t('modules.kb.property') }}</span>
                    <span class="col col-operator">{{ t('modules.kb.operator') }}</span>
                    <span class="col col-value">{{ t('modules.kb.value') }}</span>
                  </div>
                  <div
                    v-for="(row, rowIndex) in group.conditions"
                    :key="row.id"
                    class="condition-row"
                  >
                    <div class="col col-actions">
                      <button
                        type="button"
                        class="icon-btn-circle icon-btn-circle--dark"
                        :disabled="!group.type"
                        @click="addSubgraphEntityCondition(groupIndex, rowIndex)"
                      >
                        <img :src="AddIcon" alt="add">
                      </button>
                      <el-tooltip :content="t('modules.kb.atLeastOneQueryCondition')" placement="top" :disabled="group.conditions.length > 1">
                        <button
                          type="button"
                          class="icon-btn-circle icon-btn-circle--dark"
                          :disabled="group.conditions.length <= 1"
                          @click="removeSubgraphEntityCondition(groupIndex, rowIndex)"
                        >
                          <Delete class="danger-icon" />
                        </button>
                      </el-tooltip>
                    </div>
                    <div class="col col-logic logic-cell">
                      <el-select
                        v-if="rowIndex === 0 && group.conditions.length > 1"
                        v-model="group.logicOperator"
                        size="small"
                        class="condition-select condition-select--logic"
                      >
                        <el-option
                          v-for="option in logicOptions"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                      <span v-else class="logic-placeholder">
                        {{ rowIndex === 0 ? '' : getLogicLabel(group.logicOperator) }}
                      </span>
                    </div>
                    <div class="col col-prop">
                    <el-select
                      v-model="row.prop"
                      size="small"
                      class="condition-select"
                      :disabled="!group.type"
                      :placeholder="group.type ? t('modules.kb.selectProperty') : t('modules.kb.selectTypeFirst')"
                      @change="handleSubgraphEntityPropChange(groupIndex, rowIndex)"
                      clearable
                    >
                        <el-option
                          v-for="option in getPropertyOptions(group.type, 'entity')"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                    </div>
                    <div class="col col-operator">
                      <el-select
                        v-model="row.operator"
                        size="small"
                        class="condition-select"
                        clearable
                        @change="handleOperatorChange(row)"
                      >
                        <el-option
                          v-for="option in getOperatorOptions(group.type, row.prop, 'entity')"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                    </div>
                    <div class="col col-value">
                      <div class="value-input-wrapper">
                        <el-input
                          v-model="row.value"
                          size="small"
                          :disabled="!row.prop"
                          :placeholder="getValuePlaceholder(group.type, row.prop, row.operator, 'entity')"
                          @input="handleValueInput(row)"
                        />
                        <div v-if="row.error" class="error-msg">{{ row.error }}</div>
                      </div>
                    </div>
                  </div>
                  <div class="condition-footer">
                    <button
                      type="button"
                      class="icon-btn-circle icon-btn-circle--primary"
                      :disabled="!group.type"
                      @click="addSubgraphEntityCondition(groupIndex, group.conditions.length - 1, true)"
                    >
                      <el-icon><Plus /></el-icon>
                      <span>{{ t('modules.kb.addAttributeCondition') }}</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
            <div class="entity-group" v-for="(group, groupIndex) in subgraphEdgeGroups" :key="group.id">
              <div class="entity-group-row">
                <div class="entity-editor">
                  <div class="entity-editor-row">
                    <label class="entity-editor-label">{{ t('modules.kb.pathEdgeType') }}</label>
                    <el-select
                      v-model="group.type"
                      size="default"
                      class="entity-select"
                      :placeholder="t('modules.kb.selectPathEdgeType')"
                      clearable
                      @change="handleSubgraphEdgeTypeChange(groupIndex)"
                    >
                      <el-option
                        v-for="type in edgeTypes"
                        :key="type"
                        :label="type"
                        :value="type"
                      />
                    </el-select>
                    <div class="entity-editor-actions">
                      <button type="button" class="icon-btn-circle icon-btn-circle--primary" @click="addSubgraphEdgeGroup">
                        <img :src="AddIcon" alt="add">
                      </button>
                      <el-tooltip :content="t('modules.kb.atLeastOneQueryCondition')" placement="top" :disabled="subgraphEdgeGroups.length > 1">
                        <button
                          type="button"
                          class="icon-btn-circle icon-btn-circle--primary"
                          :disabled="subgraphEdgeGroups.length <= 1"
                          @click="removeSubgraphEdgeGroup(groupIndex)"
                        >
                          <Delete class="danger-icon" />
                        </button>
                      </el-tooltip>
                    </div>
                  </div>
                </div>
                <div class="property-editor">
                  <div class="condition-header">
                    <span class="col col-actions" />
                    <span class="col col-logic">{{ t('modules.kb.logicToggle') }}</span>
                    <span class="col col-prop">{{ t('modules.kb.property') }}</span>
                    <span class="col col-operator">{{ t('modules.kb.operator') }}</span>
                    <span class="col col-value">{{ t('modules.kb.value') }}</span>
                  </div>
                  <div
                    v-for="(row, rowIndex) in group.conditions"
                    :key="row.id"
                    class="condition-row"
                  >
                    <div class="col col-actions">
                      <button
                        type="button"
                        class="icon-btn-circle icon-btn-circle--dark"
                        :disabled="!group.type"
                        @click="addSubgraphEdgeCondition(groupIndex, rowIndex)"
                      >
                        <img :src="AddIcon" alt="add">
                      </button>
                      <el-tooltip :content="t('modules.kb.atLeastOneQueryCondition')" placement="top" :disabled="group.conditions.length > 1">
                        <button
                          type="button"
                          class="icon-btn-circle icon-btn-circle--dark"
                          :disabled="group.conditions.length <= 1"
                          @click="removeSubgraphEdgeCondition(groupIndex, rowIndex)"
                        >
                          <Delete class="danger-icon" />
                        </button>
                      </el-tooltip>
                    </div>
                    <div class="col col-logic logic-cell">
                      <el-select
                        v-if="rowIndex === 0 && group.conditions.length > 1"
                        v-model="group.logicOperator"
                        size="small"
                        class="condition-select condition-select--logic"
                      >
                        <el-option
                          v-for="option in logicOptions"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                      <span v-else class="logic-placeholder">
                        {{ rowIndex === 0 ? '' : getLogicLabel(group.logicOperator) }}
                      </span>
                    </div>
                    <div class="col col-prop">
                    <el-select
                      v-model="row.prop"
                      size="small"
                      class="condition-select"
                      :disabled="!group.type"
                      :placeholder="group.type ? t('modules.kb.selectProperty') : t('modules.kb.selectTypeFirst')"
                      @change="handleSubgraphEdgePropChange(groupIndex, rowIndex)"
                      clearable
                    >
                        <el-option
                          v-for="option in getPropertyOptions(group.type, 'relation')"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                    </div>
                    <div class="col col-operator">
                      <el-select
                        v-model="row.operator"
                        size="small"
                        class="condition-select"
                        clearable
                        @change="handleOperatorChange(row)"
                      >
                        <el-option
                          v-for="option in getOperatorOptions(group.type, row.prop, 'relation')"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                    </div>
                    <div class="col col-value">
                      <div class="value-input-wrapper">
                        <el-input
                          v-model="row.value"
                          size="small"
                          :disabled="!row.prop"
                          :placeholder="getValuePlaceholder(group.type, row.prop, row.operator, 'relation')"
                          @input="handleValueInput(row)"
                        />
                        <div v-if="row.error" class="error-msg">{{ row.error }}</div>
                      </div>
                    </div>
                  </div>
                  <div class="condition-footer">
                    <button
                      type="button"
                      class="icon-btn-circle icon-btn-circle--primary"
                      :disabled="!group.type"
                      @click="addSubgraphEdgeCondition(groupIndex, group.conditions.length - 1, true)"
                    >
                      <el-icon><Plus /></el-icon>
                      <span>{{ t('modules.kb.addAttributeCondition') }}</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
          </el-form>
        </div>
        <template #footer>
          <div class="controls-drawer-footer">
            <el-button @click="handleResetAdvanced">{{ t('modules.kb.resetAdvancedQuery') }}</el-button>
            <el-tooltip :content="queryButtonTooltip" placement="top" :disabled="!isQueryButtonDisabled">
              <span>
                <el-button
                  type="primary"
                  :disabled="isQueryButtonDisabled"
                  class="control-button"
                  @click="handleExecuteQuery"
                >
                  {{ t('modules.kb.applyQuery') }}
                </el-button>
              </span>
            </el-tooltip>
          </div>
        </template>
      </el-drawer>
    </div>
  </div>
</template>

<script setup>
import { ref, defineEmits, defineProps, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import message from '@/shared/lib/message'
import { Delete, Filter, Plus, Search } from '@element-plus/icons-vue'
import AddIcon from '@/assets/fonts/add-16.svg'
import TableRefreshButton from '@/shared/ui/TableRefreshButton.vue'
import { createGroup, createConditionRow, resetGroupConditions, isOnlyCondition, normalizePropertyOption } from '../lib/control-forms'

const { t } = useI18n()
const props = defineProps({
  entityTypes: {
    type: Array,
    default: () => []
  },
  edgeTypes: {
    type: Array,
    default: () => []
  },
  selectedEntityTypes: {
    type: Array,
    default: () => []
  },
  selectedEdgeTypes: {
    type: Array,
    default: () => []
  },
  limitValue: {
    type: Number,
    default: 100
  },
  depthValue: {
    type: Number,
    default: 10
  },
  searchKeyword: {
    type: String,
    default: ''
  },
  totalNodes: {
    type: Number,
    default: 0
  },
  totalEdges: {
    type: Number,
    default: 0
  },
  zoomLevel: {
    type: Number,
    default: 100
  },
  entityTypeProperties: {
    type: Object,
    default: () => ({})
  },
  edgeTypeProperties: {
    type: Object,
    default: () => ({})
  },
  resetToken: {
    type: Number,
    default: 0
  },
  /** 「刷新知识图谱」由详情页提供；未注入时退回请求父组件刷新。 */
  refreshGraph: {
    type: Function,
    default: null
  },
  /** 全屏「查询与操作」浮层内使用紧凑刷新反馈（不撑开浮层）。 */
  floating: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits([
  'entity-type-change',
  'edge-type-change',
  'limit-change',
  'depth-change',
  'export',
  'search-input',
  'search-clear',
  'execute-query',
  'query-type-change',
  'advanced-open',
  'refresh-graph'
])

function handleRefreshGraph () {
  if (typeof props.refreshGraph === 'function') {
    return props.refreshGraph()
  }
  emit('refresh-graph')
  return Promise.resolve()
}

const entityTypes = computed(() => props.entityTypes || [])

const entityTypeFilter = computed(() => (
  props.selectedEntityTypes && props.selectedEntityTypes.length === 1
    ? props.selectedEntityTypes[0]
    : ''
))

function handleEntityTypeFilter (value) {
  emit('entity-type-change', value ? [value] : [])
}
const edgeTypes = computed(() => props.edgeTypes || [])

const queryType = ref('entity')
/** 条件编辑器默认收起（复杂条件收在「高级查询」里）。 */
const advancedOpen = ref(false)
const queryTypeOptions = [
  { label: t('modules.kb.entityQuery'), value: 'entity' },
  { label: t('modules.kb.relationQuery'), value: 'relation' },
  { label: t('modules.kb.subgraphPathQuery'), value: 'subgraph' }
]
const logicOptions = [
  { label: t('modules.kb.logicAnd'), value: 'and' },
  { label: t('modules.kb.logicOr'), value: 'or' }
]
const directionOptions = [
  { label: t('modules.kb.directionIn'), value: 'in' },
  { label: t('modules.kb.directionOut'), value: 'out' },
  { label: t('modules.kb.directionBoth'), value: 'both' }
]

function getLogicLabel (value) {
  const option = logicOptions.find((item) => item.value === value)
  return option ? option.label : ''
}
const entityGroups = ref([createGroup()])
const relationGroups = ref([createGroup()])

const showConditionEditor = computed(() => ['entity', 'relation', 'subgraph'].includes(queryType.value))
const activeGroups = computed(() => (queryType.value === 'relation' ? relationGroups.value : entityGroups.value))
const activeTypes = computed(() => (queryType.value === 'relation' ? edgeTypes.value : entityTypes.value))
const activeTypePlaceholder = computed(() => (queryType.value === 'relation'
  ? t('modules.kb.selectEdgeType')
  : t('modules.kb.selectEntityType')))

// 判断是否只有一个活动组
const isOnlyActiveGroup = computed(() => {
  if (queryType.value === 'subgraph') {
    return false // 子图查询模式需要单独处理
  }
  const groups = queryType.value === 'relation' ? relationGroups.value : entityGroups.value
  return groups.length <= 1
})

// 验证查询条件是否完整
function validateQueryConditions () {
  if (queryType.value === 'entity' || queryType.value === 'relation') {
    const groups = queryType.value === 'relation' ? relationGroups.value : entityGroups.value
    for (const group of groups) {
      // 检查是否有属性校验错误
      for (const condition of group.conditions) {
        if (condition.error) {
          return false
        }
      }
    }
  } else if (queryType.value === 'subgraph') {
    // 检查起始实体属性校验错误
    for (const condition of subgraphStartGroup.value.conditions) {
      if (condition.error) {
        return false
      }
    }
    // 检查途径实体校验错误
    for (const group of subgraphEntityGroups.value) {
      for (const condition of group.conditions) {
        if (condition.error) {
          return false
        }
      }
    }
    // 检查途径关系校验错误
    for (const group of subgraphEdgeGroups.value) {
      for (const condition of group.conditions) {
        if (condition.error) {
          return false
        }
      }
    }
  }
  return true
}

// 查询按钮是否禁用
const isQueryButtonDisabled = computed(() => {
  if (!showConditionEditor.value) {
    return false
  }
  return !validateQueryConditions()
})

// 查询按钮提示
const queryButtonTooltip = computed(() => {
  if (isQueryButtonDisabled.value) {
    // 区分是未选类型还是校验错误
    if (queryType.value === 'entity' || queryType.value === 'relation') {
      const groups = queryType.value === 'relation' ? relationGroups.value : entityGroups.value
      if (groups.some(g => g.conditions.some(c => c.error))) {
        return t('modules.kb.schemaValidationFailed')
      }
    } else if (queryType.value === 'subgraph') {
      if (subgraphStartGroup.value.conditions.some(c => c.error) ||
          subgraphEntityGroups.value.some(g => g.conditions.some(c => c.error)) ||
          subgraphEdgeGroups.value.some(g => g.conditions.some(c => c.error))) {
        return t('modules.kb.schemaValidationFailed')
      }
    }
    return t('modules.kb.queryConditionValueEmpty')
  }
  return ''
})
const subgraphDirection = ref('both')
const subgraphStartGroup = ref(createGroup())
const subgraphEntityGroups = ref([createGroup()])
const subgraphEdgeGroups = ref([createGroup()])
/** 页面缺省 Limit（KnowledgeGraphDetail 的初始值；与 handleLimitBlur 的兜底同源）。 */
const DEFAULT_LIMIT_VALUE = 50

/**
 * 「条件组合」：满足全部 = and，满足任意 = or。
 * 只有一个全局开关；这里同步写入当前查询类型下所有条件组，
 * 保留按组存 logicOperator 的数据结构。
 */
const conditionCombine = computed({
  get: () => {
    let groups
    if (queryType.value === 'subgraph') {
      groups = [subgraphStartGroup.value, ...subgraphEntityGroups.value, ...subgraphEdgeGroups.value]
    } else if (queryType.value === 'relation') {
      groups = relationGroups.value
    } else {
      groups = entityGroups.value
    }
    const first = groups.find(group => group)
    return first && first.logicOperator === 'or' ? 'or' : 'and'
  },
  set: (value) => {
    const logic = value === 'or' ? 'or' : 'and'
    ;[...entityGroups.value, ...relationGroups.value, subgraphStartGroup.value,
      ...subgraphEntityGroups.value, ...subgraphEdgeGroups.value]
      .filter(Boolean)
      .forEach((group) => {
        group.logicOperator = logic
      })
  }
})

function handleActiveGroupTypeChange (groupIndex) {
  const groups = queryType.value === 'relation' ? relationGroups.value : entityGroups.value
  const group = groups[groupIndex]
  resetGroupConditions(group)
  notifyActiveTypeChange()
}

function handleSubgraphStartTypeChange () {
  resetGroupConditions(subgraphStartGroup.value)
}

function handleSubgraphEntityTypeChange (groupIndex) {
  const group = subgraphEntityGroups.value[groupIndex]
  resetGroupConditions(group)
}

function handleSubgraphEdgeTypeChange (groupIndex) {
  const group = subgraphEdgeGroups.value[groupIndex]
  resetGroupConditions(group)
}

function resetAllConditions () {
  entityGroups.value = [createGroup()]
  relationGroups.value = [createGroup()]
  subgraphStartGroup.value = createGroup()
  subgraphEntityGroups.value = [createGroup()]
  subgraphEdgeGroups.value = [createGroup()]
  subgraphDirection.value = 'both'
  emit('entity-type-change', [])
  emit('edge-type-change', [])
}

watch(() => props.resetToken, (newValue, oldValue) => {
  if (newValue === oldValue) {
    return
  }
  resetAllConditions()
})

// 属性类型分类
const BASIC_TYPES = ['BOOLEAN', 'BYTE', 'SHORT', 'INTEGER', 'LONG', 'FLOAT', 'DOUBLE', 'DATE', 'DATETIME', 'STRING']
const NUMERIC_TYPES = ['BYTE', 'SHORT', 'INTEGER', 'LONG', 'FLOAT', 'DOUBLE']
const STRING_TYPES = ['STRING']
const COLLECTION_TYPES = ['EMBEDDEDLIST', 'EMBEDDEDSET', 'LINKLIST', 'LINKSET']

// 校验函数
// 校验函数
//
// ⚠️【签名与调用不一致，勿"顺手修"】本函数只声明 1 个形参 `row`，但有 4 处调用按 3 个实参传：
//   handlePropChange / handleSubgraphStartPropChange / handleSubgraphEntityPropChange /
//   handleSubgraphEdgePropChange → `validateConditionRow(row, group.type, mode)`。
//   JS 静默忽略多余实参，**校验结果只由 row 决定**。
// 那 3 个实参恰好是 getOperatorOptions / getPropertyType 需要的 `(typeName, mode)` 元组，
// 类型相关的约束实际落在"运算符下拉选项"这一层（getOperatorOptions 按属性类型裁剪选项、
// handlePropChange 再把已不允许的 operator 清掉），不在这条**格式**校验里。
// 不要改签名、不要删实参。
// 钉住它的用例：tests/unit/GraphControls.spec.js → describe('validateConditionRow 的"签名漂移"…')
function validateConditionRow (row) {
  if (!row.prop) {
    row.error = ''
    return
  }

  const value = String(row.value ?? '')
  const trimmedValue = value.trim()

  // 当已选择属性和运算符时，值不能为空（也不能是全空格）
  if (row.operator && !trimmedValue) {
    row.error = t('modules.kb.validationNotEmpty')
    return
  }

  // 1. 长度校验 - 统一长度不能超过1000个字符
  if (value.length > 1000) {
    row.error = t('modules.kb.validationMaxLength')
    return
  }

  // 2. 运算符特定校验
  switch (row.operator) {
    case 'like':
      // 字符串类型，不能为空，且必须包含 %
      if (!value) {
        row.error = t('modules.kb.validationLikeFormat')
      } else if (!value.includes('%')) {
        row.error = t('modules.kb.validationLikeFormat')
      } else {
        row.error = ''
      }
      break
    case 'in':
      // 字符串类型，不能为空，且符合 json 列表格式
      if (!value) {
        row.error = t('modules.kb.validationNotEmpty')
      } else {
        const trimmed = value.trim()
        if (!trimmed.startsWith('[') || !trimmed.endsWith(']')) {
          row.error = t('modules.kb.validationInFormat')
        } else {
          try {
            const parsed = JSON.parse(trimmed)
            if (!Array.isArray(parsed)) {
              row.error = t('modules.kb.validationInFormat')
            } else {
              row.error = ''
            }
          } catch (e) {
            row.error = t('modules.kb.validationInFormat')
          }
        }
      }
      break
    case 'between':
      // 数字类型，不能为空，且符合 json 列表格式（2个数字）
      if (!value) {
        row.error = t('modules.kb.validationNotEmpty')
      } else {
        const trimmed = value.trim()
        if (!trimmed.startsWith('[') || !trimmed.endsWith(']')) {
          row.error = t('modules.kb.validationBetweenFormat')
        } else {
          try {
            const parsed = JSON.parse(trimmed)
            if (!Array.isArray(parsed) || parsed.length !== 2 || Number.isNaN(Number(parsed[0])) || Number.isNaN(Number(parsed[1]))) {
              row.error = t('modules.kb.validationBetweenFormat')
            } else {
              row.error = ''
            }
          } catch (e) {
            row.error = t('modules.kb.validationBetweenFormat')
          }
        }
      }
      break
    case 'contains_all':
    case 'contains_any':
      // 集合类型，不能为空，且符合 json 列表格式
      if (!value) {
        row.error = t('modules.kb.validationNotEmpty')
      } else {
        const trimmed = value.trim()
        if (!trimmed.startsWith('[') || !trimmed.endsWith(']')) {
          row.error = t('modules.kb.validationInFormat')
        } else {
          try {
            const parsed = JSON.parse(trimmed)
            if (!Array.isArray(parsed)) {
              row.error = t('modules.kb.validationInFormat')
            } else {
              row.error = ''
            }
          } catch (e) {
            row.error = t('modules.kb.validationInFormat')
          }
        }
      }
      break
    case 'contains':
      // 集合类型，不能为空，json 转换校验
      if (!value) {
        row.error = t('modules.kb.validationNotEmpty')
      } else {
        row.error = '' // 转换失败不报错，按输入下发
      }
      break
    case 'gt':
    case 'gte':
    case 'lt':
    case 'lte':
      // 数字类型，输入内容进行类型转换校验
      if (value !== '' && Number.isNaN(Number(value))) {
        row.error = t('modules.kb.validationNumberFormat')
      } else {
        row.error = ''
      }
      break
    default:
      row.error = ''
      break
  }
}

function handleQueryTypeChange () {
  if (!showConditionEditor.value) {
    return
  }
  // 通知父组件查询类型已改变
  emit('query-type-change', queryType.value)
}

function addActiveGroup () {
  if (queryType.value === 'relation') {
    relationGroups.value = [...relationGroups.value, createGroup()]
    return
  }
  entityGroups.value = [...entityGroups.value, createGroup()]
}

function removeActiveGroup (index) {
  const groups = queryType.value === 'relation' ? relationGroups.value : entityGroups.value
  if (groups.length <= 1) {
    return
  }
  groups.splice(index, 1)
  if (queryType.value === 'relation') {
    relationGroups.value = [...groups]
    return
  }
  entityGroups.value = [...groups]
}

function addCondition (groupIndex, rowIndex, appendToEnd = false) {
  const groups = queryType.value === 'relation' ? relationGroups.value : entityGroups.value
  const group = groups[groupIndex]
  if (!group) {
    return
  }

  // 校验行数限制：不能超过当前已选实体或关系的可选属性总数的两倍
  //
  // ⚠️【已知行为，勿"修"】属性表为空（propOptionsCount === 0）时
  // `1 >= 0` 恒真 ⇒ 第一行之外永远加不了行，而且弹的是"行数上限"（指错了原因：真实原因是
  // 该类型没有任何可用属性，不是行数到顶）。按钮本身没被禁用（只由 `!group.type` 控制），
  // 所以用户点得动、只得到一条误导性的 warning。
  // 何时真的发生：类型列表来自 schemaInfo.entities，属性表来自 schemaMapping.entity_meta
  // （utils/schemaMapper.js 就是 `entity.properties || []`）——schema 里声明了类型却没写
  // properties、或 properties 形状不被 normalizePropertyOption 认（value 为空被滤掉）时，
  // 这里就是 0，而该类型照样出现在类型下拉里。
  // 钉住它的用例：tests/unit/GraphControls.spec.js → describe('行数上限守卫…')
  const propOptionsCount = getPropertyOptions(group.type, queryType.value).length
  if (group.conditions.length >= propOptionsCount * 2) {
    message.warning(t('modules.kb.validationRowLimit'))
    return
  }

  const insertIndex = appendToEnd ? group.conditions.length : rowIndex + 1
  group.conditions.splice(insertIndex, 0, createConditionRow())
  if (queryType.value === 'relation') {
    relationGroups.value = [...groups]
    return
  }
  entityGroups.value = [...groups]
}

function removeCondition (groupIndex, rowIndex) {
  const groups = queryType.value === 'relation' ? relationGroups.value : entityGroups.value
  const group = groups[groupIndex]
  if (!group || group.conditions.length <= 1) {
    return
  }
  group.conditions.splice(rowIndex, 1)
  if (queryType.value === 'relation') {
    relationGroups.value = [...groups]
    return
  }
  entityGroups.value = [...groups]
}

function handleValueInput (row) {
  validateConditionRow(row)
}

function handleOperatorChange (row) {
  if (!row) {
    return
  }
  if (!row.operator) {
    row.error = ''
    return
  }
  validateConditionRow(row)
}

function getPropertyOptions (typeName, mode) {
  if (!typeName) {
    return []
  }
  const properties = mode === 'relation'
    ? (props.edgeTypeProperties?.[typeName] || [])
    : (props.entityTypeProperties?.[typeName] || [])
  return properties
    .map(normalizePropertyOption)
    .filter(option => option.value)
}

function getPropertyType (typeName, propName, mode) {
  if (!typeName || !propName) {
    return ''
  }
  const properties = getPropertyOptions(typeName, mode)
  const match = properties.find(option => option.value === propName)
  return match?.type || ''
}

function getOperatorOptions (typeName, propName, mode) {
  if (!propName) {
    return []
  }
  const propType = (getPropertyType(typeName, propName, mode) || '').toUpperCase()
  const options = []

  // eq, ne 适用于基础类型
  if (BASIC_TYPES.includes(propType)) {
    options.push({ label: '=', value: 'eq' })
    options.push({ label: '!=', value: 'ne' })
  }

  // gt, gte, lt, lte, between 适用于数字类型
  if (NUMERIC_TYPES.includes(propType)) {
    options.push({ label: '>', value: 'gt' })
    options.push({ label: '>=', value: 'gte' })
    options.push({ label: '<', value: 'lt' })
    options.push({ label: '<=', value: 'lte' })
    options.push({ label: 'between', value: 'between' })
  }

  // like, in 适用于字符串类型
  if (STRING_TYPES.includes(propType)) {
    options.push({ label: 'like', value: 'like' })
    options.push({ label: 'in', value: 'in' })
  }

  // contains 相关适用于集合类型
  if (COLLECTION_TYPES.includes(propType)) {
    options.push({ label: 'contains', value: 'contains' })
    options.push({ label: 'contains all', value: 'contains_all' })
    options.push({ label: 'contains any', value: 'contains_any' })
  }

  return options
}

function handlePropChange (groupIndex, rowIndex) {
  const groups = queryType.value === 'relation' ? relationGroups.value : entityGroups.value
  const group = groups[groupIndex]
  if (!group) {
    return
  }
  const row = group.conditions[rowIndex]
  if (!row) {
    return
  }

  const allowed = getOperatorOptions(group.type, row.prop, queryType.value)
  if (!allowed.find(option => option.value === row.operator)) {
    row.operator = allowed[0]?.value || ''
  }

  validateConditionRow(row, group.type, queryType.value)

  if (queryType.value === 'relation') {
    relationGroups.value = [...groups]
    return
  }
  entityGroups.value = [...groups]
}

function addSubgraphStartCondition (rowIndex, appendToEnd = false) {
  const group = subgraphStartGroup.value
  if (!group) {
    return
  }

  // 校验行数限制（propOptionsCount 为 0 时恒真、点"+"只弹 warning，
  // 见 addCondition 上的说明）
  const propOptionsCount = getPropertyOptions(group.type, 'entity').length
  if (group.conditions.length >= propOptionsCount * 2) {
    message.warning(t('modules.kb.validationRowLimit'))
    return
  }

  const insertIndex = appendToEnd ? group.conditions.length : rowIndex + 1
  const updatedConditions = [...group.conditions]
  updatedConditions.splice(insertIndex, 0, createConditionRow())

  // Update group indices
  const updatedConditionGroups = (group.conditionGroups || []).map((g) => {
    const newG = { ...g }
    if (newG.start >= insertIndex) {
      newG.start++
    }
    if (newG.end >= insertIndex) {
      newG.end++
    }
    return newG
  })

  subgraphStartGroup.value = { ...group, conditions: updatedConditions, conditionGroups: updatedConditionGroups }
}

function removeSubgraphStartCondition (rowIndex) {
  const group = subgraphStartGroup.value
  if (!group) {
    return
  }
  if (group.conditions.length <= 1) {
    return
  }
  const updatedConditions = [...group.conditions]
  updatedConditions.splice(rowIndex, 1)

  const updatedConditionGroups = (group.conditionGroups || [])
    .map((g) => {
      const newG = { ...g }
      if (rowIndex < newG.start) {
        newG.start--
        newG.end--
      } else if (rowIndex >= newG.start && rowIndex <= newG.end) {
        newG.end--
      }
      return newG
    })
    .filter((g) => g.end - g.start + 1 >= 2)

  const updatedGroup = { ...group, conditions: updatedConditions, conditionGroups: updatedConditionGroups }
  subgraphStartGroup.value = updatedGroup
}

function handleSubgraphStartPropChange (rowIndex) {
  const group = subgraphStartGroup.value
  if (!group) {
    return
  }
  const updatedConditions = [...group.conditions]
  const row = updatedConditions[rowIndex]
  if (!row) {
    return
  }
  const allowed = getOperatorOptions(group.type, row.prop, 'entity')
  if (!allowed.find(option => option.value === row.operator)) {
    row.operator = allowed[0]?.value || ''
  }

  validateConditionRow(row, group.type, 'entity')

  subgraphStartGroup.value = { ...group, conditions: updatedConditions }
}

function addSubgraphEntityCondition (groupIndex, rowIndex, appendToEnd = false) {
  const group = subgraphEntityGroups.value[groupIndex]
  if (!group) {
    return
  }

  // 校验行数限制（同 addSubgraphStartCondition：0 属性时恒真，见 addCondition 上的说明）
  const propOptionsCount = getPropertyOptions(group.type, 'entity').length
  if (group.conditions.length >= propOptionsCount * 2) {
    message.warning(t('modules.kb.validationRowLimit'))
    return
  }

  const insertIndex = appendToEnd ? group.conditions.length : rowIndex + 1
  const updatedConditions = [...group.conditions]
  updatedConditions.splice(insertIndex, 0, createConditionRow())
  const updatedGroups = [...subgraphEntityGroups.value]
  updatedGroups[groupIndex] = { ...group, conditions: updatedConditions }
  subgraphEntityGroups.value = updatedGroups
}

function removeSubgraphEntityCondition (groupIndex, rowIndex) {
  const group = subgraphEntityGroups.value[groupIndex]
  if (!group) {
    return
  }
  if (group.conditions.length <= 1) {
    return
  }
  const updatedConditions = [...group.conditions]
  updatedConditions.splice(rowIndex, 1)
  const updatedGroups = [...subgraphEntityGroups.value]
  updatedGroups[groupIndex] = { ...group, conditions: updatedConditions }
  subgraphEntityGroups.value = updatedGroups
}

function handleSubgraphEntityPropChange (groupIndex, rowIndex) {
  const group = subgraphEntityGroups.value[groupIndex]
  if (!group) {
    return
  }
  const updatedConditions = [...group.conditions]
  const row = updatedConditions[rowIndex]
  if (!row) {
    return
  }
  const allowed = getOperatorOptions(group.type, row.prop, 'entity')
  if (!allowed.find(option => option.value === row.operator)) {
    row.operator = allowed[0]?.value || ''
  }

  validateConditionRow(row, group.type, 'entity')

  const updatedGroups = [...subgraphEntityGroups.value]
  updatedGroups[groupIndex] = { ...group, conditions: updatedConditions }
  subgraphEntityGroups.value = updatedGroups
}

function addSubgraphEdgeCondition (groupIndex, rowIndex, appendToEnd = false) {
  const group = subgraphEdgeGroups.value[groupIndex]
  if (!group) {
    return
  }

  // 校验行数限制（同 addSubgraphStartCondition：0 属性时恒真，见 addCondition 上的说明）
  const propOptionsCount = getPropertyOptions(group.type, 'relation').length
  if (group.conditions.length >= propOptionsCount * 2) {
    message.warning(t('modules.kb.validationRowLimit'))
    return
  }

  const insertIndex = appendToEnd ? group.conditions.length : rowIndex + 1
  const updatedConditions = [...group.conditions]
  updatedConditions.splice(insertIndex, 0, createConditionRow())
  const updatedGroups = [...subgraphEdgeGroups.value]
  updatedGroups[groupIndex] = { ...group, conditions: updatedConditions }
  subgraphEdgeGroups.value = updatedGroups
}

function removeSubgraphEdgeCondition (groupIndex, rowIndex) {
  const group = subgraphEdgeGroups.value[groupIndex]
  if (!group) {
    return
  }
  if (group.conditions.length <= 1) {
    return
  }
  const updatedConditions = [...group.conditions]
  updatedConditions.splice(rowIndex, 1)
  const updatedGroups = [...subgraphEdgeGroups.value]
  updatedGroups[groupIndex] = { ...group, conditions: updatedConditions }
  subgraphEdgeGroups.value = updatedGroups
}

function handleSubgraphEdgePropChange (groupIndex, rowIndex) {
  const group = subgraphEdgeGroups.value[groupIndex]
  if (!group) {
    return
  }
  const updatedConditions = [...group.conditions]
  const row = updatedConditions[rowIndex]
  if (!row) {
    return
  }
  const allowed = getOperatorOptions(group.type, row.prop, 'relation')
  if (!allowed.find(option => option.value === row.operator)) {
    row.operator = allowed[0]?.value || ''
  }

  validateConditionRow(row, group.type, 'relation')

  const updatedGroups = [...subgraphEdgeGroups.value]
  updatedGroups[groupIndex] = { ...group, conditions: updatedConditions }
  subgraphEdgeGroups.value = updatedGroups
}

function addSubgraphEntityGroup () {
  subgraphEntityGroups.value = [...subgraphEntityGroups.value, createGroup()]
}

function removeSubgraphEntityGroup (groupIndex) {
  if (subgraphEntityGroups.value.length <= 1) {
    return
  }
  if (groupIndex < 0 || groupIndex >= subgraphEntityGroups.value.length) {
    return
  }
  const updatedGroups = [...subgraphEntityGroups.value]
  updatedGroups.splice(groupIndex, 1)
  subgraphEntityGroups.value = updatedGroups
}

function addSubgraphEdgeGroup () {
  subgraphEdgeGroups.value = [...subgraphEdgeGroups.value, createGroup()]
}

function removeSubgraphEdgeGroup (groupIndex) {
  if (subgraphEdgeGroups.value.length <= 1) {
    return
  }
  if (groupIndex < 0 || groupIndex >= subgraphEdgeGroups.value.length) {
    return
  }
  const updatedGroups = [...subgraphEdgeGroups.value]
  updatedGroups.splice(groupIndex, 1)
  subgraphEdgeGroups.value = updatedGroups
}

function getValuePlaceholder (typeName, propName, operator, mode) {
  const propType = getPropertyType(typeName, propName, mode)
  const normalizedType = String(propType || '').toUpperCase()
  switch (operator) {
    case 'like':
      return t('modules.kb.valuePlaceholderLike')
    case 'in':
      return t('modules.kb.valuePlaceholderIn')
    case 'between':
      return t('modules.kb.valuePlaceholderBetween')
    case 'contains':
      return t('modules.kb.valuePlaceholderContains')
    case 'contains_all':
    case 'contains_any':
      return t('modules.kb.valuePlaceholderContainsAny')
    default:
      break
  }

  if (normalizedType === 'BOOLEAN') {
    return t('modules.kb.valuePlaceholderBoolean')
  }
  if (['BYTE', 'SHORT', 'INTEGER', 'LONG', 'FLOAT', 'DOUBLE'].includes(normalizedType)) {
    return t('modules.kb.valuePlaceholderNumber')
  }
  if (normalizedType === 'DATE') {
    return t('modules.kb.valuePlaceholderDate')
  }
  if (normalizedType === 'DATETIME') {
    return t('modules.kb.valuePlaceholderDatetime')
  }
  if (normalizedType === 'STRING') {
    return t('modules.kb.valuePlaceholderString')
  }
  return t('modules.kb.valuePlaceholderDefault')
}

function buildFilters (groups, typeKey, propKey, mode) {
  return groups
    .map(group => {
      const activeConditions = group.conditions
        .filter(row => row.enabled && row.prop && String(row.value ?? '').trim() !== '' && !row.error)
        .map(row => {
          let finalValue = row.value
          const propType = (getPropertyType(group.type, row.prop, mode) || '').toUpperCase()

          // 根据运算符和类型进行转换
          if (['gt', 'gte', 'lt', 'lte'].includes(row.operator) || NUMERIC_TYPES.includes(propType)) {
            if (!Number.isNaN(Number(row.value))) {
              finalValue = Number(row.value)
            }
          }

          if (['in', 'between', 'contains_all', 'contains_any'].includes(row.operator)) {
            try {
              finalValue = JSON.parse(row.value)
            } catch (e) {
              // 如果解析失败，保持原样（虽然校验应该已经拦截了）
            }
          }

          if (row.operator === 'contains') {
            try {
              finalValue = JSON.parse(row.value)
            } catch (e) {
              // contains 转换失败不报错，按字符串下发
            }
          }

          return {
            property: row.prop,
            op: row.operator,
            value: finalValue
          }
        })

      const properties = {}
      if (activeConditions.length > 1) {
        properties.complex_filter = {
          op: (group.logicOperator || 'and').toLowerCase(),
          value: activeConditions
        }
      } else if (activeConditions.length === 1) {
        const [single] = activeConditions
        properties[single.property] = {
          op: single.op,
          value: single.value
        }
      }

      return {
        [typeKey]: group.type ? [group.type] : [],
        [propKey]: properties
      }
    })
}

function handleLimitChange (value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return
  }
  const validValue = Math.max(1, Math.min(1000, Number(value)))
  emit('limit-change', validValue)
}

// ⚠️【兜底值与组件默认值不一致，勿"对齐"】无效值兜底发 50，而 props.limitValue
// 的默认值是 100（模板里 el-input-number 的 min/max 是 1/1000）。50 是调用方页面的
// 初始值（KnowledgeGraphDetail.vue `const limitValue = ref(50)`）。
// 只有父组件显式传 null / NaN 才走这条分支（传 undefined 会被 prop 默认值 100 顶掉，
// 见 Vue `resolvePropValue` 的 `hasDefault && value === undefined`），而该调用链上的
// handleLimitChange 会先挡掉非法值 —— 正常路径跑不到这条兜底，它是防御性代码。
// 钉住它的用例：tests/unit/GraphControls.spec.js → describe('limit 输入的 blur 兜底…')
function handleLimitBlur () {
  const currentValue = props.limitValue
  if (currentValue === null || currentValue === undefined || Number.isNaN(currentValue)) {
    emit('limit-change', 50)
    return
  }
  const validValue = Math.max(1, Math.min(1000, Number(currentValue)))
  if (validValue !== currentValue) {
    emit('limit-change', validValue)
  }
}

function notifyActiveTypeChange () {
  if (queryType.value === 'relation') {
    const types = relationGroups.value.map((g) => g.type).filter(Boolean)
    emit('edge-type-change', types)
    return
  }
  const types = entityGroups.value.map((g) => g.type).filter(Boolean)
  emit('entity-type-change', types)
}

function handleDepthChange (value) {
  emit('depth-change', value)
}

/** 摘要行的「显示上限」入口：打开同一个高级查询抽屉。 */
function openAdvanced () {
  advancedOpen.value = true
}

// 抽屉打开时收起「查询与操作」浮层（避免两层叠在一起）。
watch(advancedOpen, (value) => {
  if (value) {
    emit('advanced-open')
  }
})

/** 重置高级条件并把 Limit 恢复到页面缺省值（不自动发起查询）。 */
function handleResetAdvanced () {
  resetAllConditions()
  if (Number(props.limitValue) !== DEFAULT_LIMIT_VALUE) {
    emit('limit-change', DEFAULT_LIMIT_VALUE)
  }
}

function handleExecuteQuery () {
  let filters = []
  if (queryType.value === 'relation') {
    filters = buildFilters(relationGroups.value, 'edge_type', 'properties', 'relation')
  } else if (queryType.value === 'subgraph') {
    const startFilters = buildFilters([subgraphStartGroup.value], 'start_entity_type', 'start_entity_properties', 'entity')
    filters = [
      ...startFilters,
      ...buildFilters(subgraphEntityGroups.value, 'path_entity_type', 'path_entity_properties', 'entity'),
      ...buildFilters(subgraphEdgeGroups.value, 'path_edge_type', 'path_edge_properties', 'relation')
    ]
  } else {
    filters = buildFilters(entityGroups.value, 'entity_type', 'properties', 'entity')
    // 工具条上的「全部实体类型」快速筛选也要参与查询：handleExecuteQuery 不读它，
    // 若不合并，选中类型后点查询，请求体里 entity_type 永远是 []，
    // 用户看到的就是「选了类型没生效」。
    // 高级条件里已经覆盖的类型不重复下发（两者共用 selectedEntityTypes 回显）。
    const coveredTypes = new Set(filters.flatMap(f => f.entity_type || []))
    const quickTypes = (props.selectedEntityTypes || [])
      .filter(type => type && !coveredTypes.has(type))
    if (quickTypes.length) {
      filters = [{ entity_type: quickTypes, properties: {} }, ...filters]
    }
  }
  advancedOpen.value = false
  emit('execute-query', {
    queryType: queryType.value,
    filters,
    direction: queryType.value === 'subgraph' ? subgraphDirection.value : undefined
  })
}

defineExpose({ openAdvanced })
</script>

<style lang="less" scoped>
.controls-wrapper {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  // 控制面板高度随内容；不要被画布的 flex:1 挤扁
  flex: 0 0 auto;
  min-width: 0;
}

.controls-panel {
  position: relative;
  background: var(--rs-bg-card);
  border-radius: 8px;
  // 跟随详情页内容区宽度（97.5vw 未扣左栏与内边距，会把查询按钮顶出视口）
  width: 100%;
  min-width: 0;
  padding: 12px 0px 0; // 底部padding设为0，由wrapper承担
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.controls-main {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 8px;
}

.controls-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.controls-left {
  display: flex;
  align-items: center;
  gap: 32px;
  padding-left: 16px;
}

.controls-right {
  display: flex;
  align-items: center;
  gap: 32px;
  z-index: 1000;
  padding-right: 16px;
}

.control-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  justify-content: flex-start;

  label,
  .label {
    font-size: 12px;
    color: var(--rs-text-2);
    white-space: nowrap;
  }

  .value {
    font-weight: 600;
    color: var(--rs-primary);
  }
}

.control-item--stat {
  justify-content: center;
}

.control-select {
  width:200px;
}

.control-select--wide {
  width: 180px;
}

.control-button {
  min-width: 72px;
}

// 数字框宽度固定 180px：这是设计口径，不是 EP 默认的 150px。
// 不要改成 100px，否则数字框被压窄，连带整条 `.controls-left` 变窄。
.control-item :deep(.el-input-number) {
  width: 180px;
}

.controls-body {
  min-width: 0;
}

/* 高级查询抽屉（对齐 workspace-panel-* / query-condition 口径）。 */
.advanced-drawer-intro {
  margin: 0 0 24px;
  color: var(--rs-text-2, #536383);
  font-size: 13px;
  line-height: 1.6;
}

.advanced-query-form :deep(.el-form-item) {
  margin-bottom: 20px;
}

.advanced-query-form :deep(.el-form-item__label) {
  margin-bottom: 6px;
  color: var(--rs-text-2, #536383);
  font-size: 13px;
  line-height: 1.4;
}

.query-limit-field :deep(.el-form-item__content) {
  display: block;
}

.query-limit-field :deep(.el-input-number) {
  width: 150px;
}

.query-limit-help {
  margin: 10px 0 0;
  color: var(--rs-text-3, #8794ae);
  line-height: 1.6;
}

.advanced-query-type :deep(.el-select) {
  width: 200px;
}

.advanced-query-type :deep(.el-select__wrapper) {
  min-height: var(--el-component-size);
}

.advanced-param-row {
  display: flex;
  gap: 12px;
}

.advanced-param-item {
  flex: 1;
  min-width: 0;
}

.advanced-param-item :deep(.el-input-number),
.advanced-param-item :deep(.el-select) {
  width: 100%;
}

.condition-combine :deep(.el-radio-button__inner) {
  min-width: 76px;
}

.controls-drawer-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  width: 100%;
}

/* 条件卡片：对应 .query-condition / .condition-label / .condition-fields。 */
.controls-drawer-body {
  overflow-x: hidden;

  .query-condition,
  .entity-group {
    padding: 16px;
    margin-bottom: 16px;
    border: 1px solid var(--rs-border, var(--rs-border));
    border-radius: 8px;
  }

  .entity-group + .entity-group {
    border-top: 1px solid var(--rs-border, var(--rs-border));
  }

  .condition-label {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
    font-size: 13px;
  }

  .condition-fields,
  .entity-group-row {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .entity-editor {
    flex: 0 0 auto;
    width: 100%;
    min-width: 0;
    padding-left: 0;
  }

  .entity-editor-row {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
  }

  .entity-editor-label {
    display: block;
    margin-bottom: 6px;
    color: var(--rs-text-2, #536383);
    font-size: 13px;
  }

  .entity-editor-row .entity-editor-label {
    margin-bottom: 0;
  }

  .entity-select {
    width: 100%;
    max-width: none;
  }

  .entity-editor-actions {
    justify-content: flex-end;
  }

  .property-editor {
    width: 100%;
    min-width: 0;
    max-width: none;
    padding-right: 0;
  }

  .condition-header {
    display: none;
  }

  .condition-row {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    grid-template-areas:
      'prop operator'
      'value value'
      'actions actions';
    gap: 10px;
    padding: 0 0 10px;
  }

  .condition-row .col-prop { grid-area: prop; }
  .condition-row .col-operator { grid-area: operator; }
  .condition-row .col-value { grid-area: value; }
  .condition-row .col-actions {
    grid-area: actions;
    justify-self: end;
    visibility: hidden;
  }
  .entity-group:has(.condition-row + .condition-row) .condition-row .col-actions {
    visibility: visible;
  }
  .condition-row .col-logic { display: none; }
}

.add-condition-card {
  margin-top: 4px;
}

.add-condition-row {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--rs-border, var(--rs-border));
  border-radius: 6px;
  background: transparent;
  color: var(--rs-text-2, #536383);
  cursor: pointer;
}

.add-condition-row:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.entity-group {
  padding: 12px 0;
}

.entity-group + .entity-group {
  border-top: 1px dashed var(--rs-border);
}

.entity-group-row {
  display: flex;
  flex-direction: row;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.entity-editor {
  // 400px 是宽屏下的理想宽度；窄屏允许收缩，避免把右侧条件表格挤出容器
  flex: 0 1 400px;
  min-width: 260px;
  padding-left: 6px;
}

.entity-editor-title {
  font-size: 13px;
  color: var(--rs-text-2);
  margin-bottom: 8px;
}

.entity-editor-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.entity-editor-label {
  font-size: 12px;
  color: var(--rs-text-2);
  white-space: nowrap;
}

.entity-select {
  flex: 1;
  min-width: 0;
  max-width: 250px;
}

.entity-editor-actions {
  display: flex;
}

.property-editor {
  flex: 0 1 auto;
  // 下限与下方栅格的最小宽度对齐（100+120+120+80+120+4×8 = 572）：
  // 600 会在 1280~1440 这类常见笔记本宽度上把表格顶出容器，出现不必要的横向滚动条。
  min-width: 572px;
  max-width: 1250px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding-right: 16px;
}

.condition-header,
.condition-row {
  display: grid;
  // 宽屏保持原列宽上限（属性 240 / 运算符 140 / 值 500），窄屏按最小值收缩。
  // width:100% 必须写：父级 align-items:flex-start 会让行按 max-content 撑开，
  // 即使父容器已收窄，行仍保持 1132px → 内容区横向滚动条。
  width: 100%;
  grid-template-columns: 100px 120px minmax(120px, 240px) minmax(80px, 140px) minmax(120px, 500px);
  gap: 8px;
  align-items: center;
}

.condition-header {
  padding-bottom: 4px;
  font-size: 13px;
  color: var(--rs-text-2);
}

.condition-row {
  padding: 8px 0;
}

.condition-select {
  width: 100%;
}

.condition-select--logic {
  width: 100%;
}

.value-input-wrapper {
  position: relative;
  width: 100%;
}

.error-msg {
  position: absolute;
  left: 0;
  top: 100%;
  max-width: 100%;
  font-size: 12px;
  color: var(--rs-danger);
  line-height: 1.2;
  padding-top: 2px;
  white-space: normal;
  word-break: break-word;
  overflow-wrap: anywhere;
  z-index: 1;
}

.logic-placeholder {
  color: var(--rs-text-3);
}

.condition-footer {
  display: flex;
  justify-content: flex-start;
  padding-top: 6px;
  width: 100%;
}

.icon-btn-circle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 20px;
  padding: 0 4px;
  border: none;
  background: transparent;
  cursor: pointer;
  gap: 6px;
}

.icon-btn-circle img {
  width: 16px;
  height: 16px;
}

.icon-btn-circle--primary {
  color: var(--rs-primary);
}

.icon-btn-circle--dark {
  color: var(--rs-text-2);
}

.icon-btn-circle--dark img {
  filter: invert(49%) sepia(0%) saturate(121%) hue-rotate(159deg) brightness(91%) contrast(89%);
}

.icon-btn-circle--primary img {
  filter: brightness(0) saturate(100%) invert(54%) sepia(88%) saturate(1755%) hue-rotate(190deg) brightness(101%) contrast(101%);
}

.icon-btn-circle:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

/* ── 工具栏 ──────────────────────────────────────────────────────
   查询区不是独立白卡：搜索 + 类型 + 查询 + 高级查询直接排在画布上方。 */
.controls-panel {
  background: transparent;
  overflow: visible;
  padding: 0;
}

.controls-main {
  padding: 0;
  margin-bottom: 0;
}

.controls-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.controls-left,
.controls-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

/* 节点/关系/缩放统计在画布上以「显示 13 个实体 · 16 条关系」呈现，
   工具栏这里不重复占位。 */
.control-item.control-item--stat {
  display: none;
}

.control-search {
  width: 270px;
}

.advanced-control-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.control-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.control-item > label {
  font-size: 13px;
  color: var(--rs-text-2, #536383);
  white-space: nowrap;
}

.control-button {
  height: 40px;
  padding: 8px 16px;
}

.control-button.is-active {
  color: var(--rs-primary, #1677ff);
  border-color: var(--rs-primary, #1677ff);
}

@media (max-width: 1100px) {
  .control-search {
    width: 220px;
  }
}

/* 查询行：搜索 270×40 + 实体类型 150×32 + 查询 78×32 + 高级 104×32，
   从内容左缘起排、间距 10；查询类型放在「高级查询」面板内，功能不变。

   高度**不混用 40/32**：同一行右侧的「刷新 / 新增实体」用的是全局
   `.el-button`（40px），搜索框也是全局输入高度（`--el-component-size` = 40px），
   只把类型下拉与两个查询按钮压到 32px 会让行内四种控件三种基线（截图可见）。
   这里统一取 `--el-component-size`。 */
.controls-left,
.controls-right {
  padding-left: 0;
  padding-right: 0;
}

.controls-row {
  gap: 10px;
  justify-content: flex-start;
}

.controls-left {
  gap: 10px;
}

.controls-right {
  gap: 10px;
}

.control-search {
  width: 270px;
  height: var(--el-component-size);
}

.control-search :deep(.el-input__wrapper) {
  min-height: var(--el-component-size);
  height: var(--el-component-size);
}

.control-type {
  width: 150px;
}

/* EP 的 el-select 不读 --el-component-size（其 wrapper 自带 min-height:32px），
   要按面补 min-height，别去改 token。 */
.control-type :deep(.el-select__wrapper) {
  min-height: var(--el-component-size);
  height: var(--el-component-size);
}

.control-button {
  height: var(--el-component-size);
  padding: 10px 18px;
  font-size: 14px;
}

.control-button :deep(.el-icon + span) {
  margin-left: 8px;
}

/* 刷新与「新增实体」靠右成组；整组换行后 margin-left:auto 仍把它推到右缘。 */
.graph-data-actions {
  margin-left: auto;
  justify-content: flex-end;
  min-width: 0;
  max-width: 100%;
}
</style>
