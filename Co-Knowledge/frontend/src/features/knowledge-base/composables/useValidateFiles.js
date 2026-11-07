export function useValidateFiles (proxy) {
  function readFileChunk (file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(true);
      reader.onerror = () => reject(new Error(proxy.$t('public.readCurrentFileFailure')));
      reader.readAsArrayBuffer(file.slice(0, 1)); // 尝试读取文件的前一个字节
    });
  }

  function validateFiles (files) {
    const promises = files.map(file => {
      return readFileChunk(file.raw).then(
        () => ({ file, result: true }), // 文件可访问
        () => ({ file, result: false }) // 文件读取失败
      );
    });

    // 使用 Promise.all 来等待所有文件的验证结果
    return Promise.all(promises).then(results => {
      // 筛选出所有验证失败的结果
      const failedResults = results.filter(result => !result.result);
      if (failedResults.length > 0) {
        // 如果有文件验证失败，抛出错误信息
        const errorMessage = proxy.$t('public.readFilesFailure', {
          fileName: failedResults.map(fr => fr.file.name).join(`${proxy.$t('public.comma')}`)
        });
        throw new Error(errorMessage);
      }
      // 所有文件验证通过
      return true;
    });
  }

  function getFileSuffix (file) {
    const fileSuffix = file.name.substring(file.name.lastIndexOf('.') + 1).toLowerCase();
    return fileSuffix;
  }

  return {
    readFileChunk,
    validateFiles,
    getFileSuffix
  }
}
