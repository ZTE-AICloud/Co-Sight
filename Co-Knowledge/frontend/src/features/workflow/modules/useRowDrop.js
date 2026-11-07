import Sortable from 'sortablejs';
export function useRowDrop (tableData) {
  function rowDrop () {
    const tbody = document.querySelector('.el-table__body-wrapper tbody');

    Sortable.create(tbody, {
      animation: 500,
      handle: '.btn-drag',
      // 指定父元素下可被拖拽的子元素
      draggable: '.el-table__row',
      onEnd: ({ newIndex, oldIndex }) => {

        const currRow = tableData.splice(oldIndex, 1)[0];
        tableData.splice(newIndex, 0, currRow);
      }
    });
  }

  return {
    rowDrop
  }
}
