// import Vue from 'vue';
import { createStore } from 'vuex'
import { SUPERADMIN, PLATFORMADMIN, APPCREATOR, KBASECREATOR, APPADMIN, KBASEADMIN, APPDEVELOPER, KBASEMEMBER } from '@/shared/constants/index.js'
import kbase from '@/features/knowledge-base/store';

const storeConfig = {
  state: {
    kb: {
      currentName: ''
    },
    authority: {
      noAnyAuthority: true,
      isSuperAdmin: false,
      isPlatformAdmin: false,
      isAppCreator: false,
      isKbaseCreator: false,
      isAppAdmin: false,
      isAppDeveloper: false,
      isKbaseAdmin: false,
      isKbaseMember: false,
    },
    flow: {
      userGuideVariables: {}
    },
    simple: {
      userGuideVariables: {}
    },
    showDetailLeft: true, // 是否展示应用子菜单侧边栏
    showAsideMenu: true, // 是否展示应用平台左侧侧边菜单栏 -- 目前服务于高级编排 编辑模式 隐藏侧边菜单
    isAdvancedFlowEditMode: false, // 高级编排是否处于编辑状态
    appName: '',
    appLatestSaveDate: '',
    ragWorkflowType: '',
    ragWorkflowIsStructKnowledge: false // 高级编排工作流是否实际使用结构化知识库（SQL检索算子）
  },
  getters: {
  },
  mutations: {
    updateCurrentName (state, value) {
      state.kb.currentName = value
    },
    // NOTE：updateCodeKbPermission / updateGlobalRoles / updateRoles
    // 全仓从未被 commit 调用（存活的 commit 点只有 kbase/* 与 ADD|UPDATE|REMOVE_NODE）；
    // updateGlobalRoles / updateRoles 还写的是不存在的 state.role（state 只有 authority），
    // 一旦被调用必抛 TypeError。为保持结构稳定，这里只标注、不删除。
    updateCodeKbPermission (state, value) {
      state.authority.isCodeKbaseCreator = value
    },
    updateGlobalRoles (state, value) {
      state.authority.isSuperAdmin = value.indexOf(SUPERADMIN) > -1
      state.authority.isPlatformAdmin = value.indexOf(PLATFORMADMIN) > -1
      state.authority.isAppCreator = value.indexOf(APPCREATOR) > -1
      state.authority.isKbaseCreator = value.indexOf(KBASECREATOR) > -1
      state.authority.noAnyAuthority = !(value.length > 0)
      state.role.globalRoles = value
    },
    updateRoles (state, value) {
      state.role.app_admin = value[APPADMIN]
      state.role.kbase_admin = value[KBASEADMIN]
      state.authority.isAppAdmin = !!value[APPADMIN].length
      state.authority.isAppDeveloper = !!value[APPDEVELOPER].length
      state.authority.isKbaseAdmin = !!value[KBASEADMIN].length
      state.authority.isKbaseMember = !!value[KBASEMEMBER].length
    },
    updateShowAsideMenu (state, value) {
      state.showAsideMenu = value
    },
    updateDetailLeft (state, value) {
      state.showDetailLeft = value
    },
    updateAppLatestSaveDate (state, value) {
      state.appLatestSaveDate = value;
    }
  },
  actions: {
  },
  modules: {
    kbase
  }
}

export default storeConfig

// Vue.use(Vuex)
export const store = createStore(storeConfig)
