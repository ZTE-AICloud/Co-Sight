import { ref } from 'vue';

export function useNode (props:any) {
  function inputUpHandle (index: number) {
    let preIndex = index - 1;
    [props.nodeInfo.inputVariables[preIndex], props.nodeInfo.inputVariables[index]] = [props.nodeInfo.inputVariables[index], props.nodeInfo.inputVariables[preIndex]];
    props.nodeInfo.inputVariables = ref(props.nodeInfo.inputVariables)
  }
  function inputDownHandle (index: number) {
    let nextIndex = index + 1;
    [props.nodeInfo.inputVariables[nextIndex], props.nodeInfo.inputVariables[index]] = [props.nodeInfo.inputVariables[index], props.nodeInfo.inputVariables[nextIndex]];
    props.nodeInfo.inputVariables = ref(props.nodeInfo.inputVariables)
  }
  return {
    inputUpHandle, inputDownHandle

  }
}
