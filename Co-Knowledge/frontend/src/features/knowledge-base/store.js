export default {
  namespaced: true, // 命名空间，用于区分不同模块的状态、getters、mutations和actions
  state: {
    folderInfo: {}, // 存储文件夹信息的状态
    faqCategoryInfo: {}, // 存储高频问答分类树的状态
    kBaseName: ''
  },
  getters: {
    // 获取器，用于从状态中派生出新的状态
  },
  mutations: {
    updateFolderInfo (state, value) {
      // 更新文件夹信息的mutation
      state.folderInfo = value; // 将传入的值赋给状态中的folderInfo
    },
    updateFaqCategoryInfo (state, value) {
      state.faqCategoryInfo = value;
    },
    updatekBaseName (state, value) {
      // 更新文件夹信息的mutation
      state.kBaseName = value;
    }
  },
  actions: {
    // 异步操作，可以包含多个mutation的调用
  }
};
