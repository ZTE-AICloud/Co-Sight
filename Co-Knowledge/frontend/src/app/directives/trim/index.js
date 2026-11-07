export default {
  install (app) {
    app.directive('trim', {
      mounted (el, binding, vnode) {
        // 获取 input 或 textarea 元素
        const input = el.querySelector('input') || el.querySelector('textarea');
        if (!input) {
          return;
        }

        // 定义一个失焦事件处理函数
        const handleBlur = function (e) {
          vnode.ctx.emit('update:modelValue', (vnode.ctx.ctx?.modelValue || e.target.value).trim())
        };

        // 给 input 元素添加失焦事件监听
        input.addEventListener('blur', handleBlur);

        // 保存事件处理函数的引用，以便在 unmounted 钩子中移除
        el._handleBlur = handleBlur;
      },
      unmounted (el) {
        // 获取 input 或 textarea 元素
        const input = el.querySelector('input') || el.querySelector('textarea');
        if (!input) {
          return;
        }

        // 获取之前保存的事件处理函数的引用
        const handleBlur = el._handleBlur;

        // 移除 input 元素的失焦事件监听
        input.removeEventListener('blur', handleBlur);

        // 删除保存的事件处理函数引用
        el._handleBlur = null;
      }
    });
  }
};
