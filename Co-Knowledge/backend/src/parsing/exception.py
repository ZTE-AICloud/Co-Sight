"""敏感信息异常类型（替代私有 corpus.common.exception.SensitiveMsgException）。

保持与私有包一致的构造签名与行为，映射到契约错误码 OPERATOR_SENSITIVE。
"""


class ParseEmptyError(Exception):
    """解析完成但正文为空（未被消化的既有失败模式，见 ``test_split.py`` 相关用例）。

以前这条路径是 ``process_single_file`` 里的**静默 return**：不产出 corpus_file.txt、
不抛错，于是上层去读那个文件报 ``FileNotFoundError``，被翻译成
``RetCode.operator.split.error``（"切分算子执行失败"）—— 真实原因（HTML 是 JS 渲染的
空壳、纯图片/扫描件、空白文件…）完全丢失。实测复现：GoAccess 的 report.html 与
空白 .txt 都走这条路径。

**``message`` 是文案键而不是给人看的句子**：tornado 的 ``pretty_error_response`` 会
把它当 i18n key 传给 ``gettext``，没有 catalog 时原样回填 —— 所以信封里的
``code.msg`` 就是键名本身，下游（RKB 的 ``SPLIT_ERROR_MESSAGES``）据此映射文案。
真实原因（文件名/格式/字符数）只进 ``logging`` 与 ``__str__``，不上**对外**信封。
"""

    code = '0001'
    bo = None
    message = 'RetCode.operator.split.empty'

    def __init__(self, file_path, source=None, detail=None):
        self.file_path = file_path
        self.source = source
        self.detail = detail
        super().__init__(file_path, source, detail)

    def __str__(self):
        return (f"ParseEmptyError(file_path={self.file_path!r}, source={self.source!r}, "
                f"detail={self.detail!r}, message={self.message})")


class UnsupportedFormatError(Exception):
    """该格式**没有可用的解析器**（OFD、压缩包等）。

    以前这类文件在 ``process_single_file`` 里是「不支持的格式，跳过」的静默 return，
    最终以 ``FileNotFoundError`` 冒到上层，被翻译成 ``RetCode.operator.split.error``
    （"切分算子执行失败，请检查算子是否存在问题"）—— 把「格式不支持」说成「算子坏了」，
    用户会去查算子，徒劳。

    与 :class:`ParseEmptyError` 同样的约定：``message`` 是**文案键**，细节只进日志。
    """

    code = '0001'
    bo = None
    message = 'RetCode.operator.split.unsupported'

    def __init__(self, file_path, source=None):
        self.file_path = file_path
        self.source = source
        super().__init__(file_path, source)

    def __str__(self):
        return (f"UnsupportedFormatError(file_path={self.file_path!r}, "
                f"source={self.source!r}, message={self.message})")


class ParseCorruptError(Exception):
    """文件本身损坏或不完整（截断的 docx/pptx/xlsx 等 OOXML ZIP 包）。

    现场：上传的 docx 只有 33.1 MB，开头是 ``PK\\x03\\x04``，但文件在
    ``word/media/image1.jpeg`` 中间就结束了，且没有 ZIP 中央目录 —— python-docx 抛
    ``PackageNotFoundError``，信封里只有一句 "Package not found at ..."，最终落到
    ``RetCode.operator.split.error``（"切分算子执行失败，请检查算子是否存在问题"），
    用户会去查算子，徒劳。

    与 :class:`ParseEmptyError` / :class:`UnsupportedFormatError` 同样的约定：
    ``message`` 是**文案键**，细节（文件路径、底层异常）只进日志与 ``__str__``。
    """

    code = '0001'
    bo = None
    message = 'RetCode.operator.split.corrupt'

    def __init__(self, file_path, source=None, detail=None):
        self.file_path = file_path
        self.source = source
        self.detail = detail
        super().__init__(file_path, source, detail)

    def __str__(self):
        return (f"ParseCorruptError(file_path={self.file_path!r}, source={self.source!r}, "
                f"detail={self.detail!r}, message={self.message})")


class SensitiveMsgException(Exception):
    def __init__(self, code, bo, message_dict=None):
        if message_dict is None:
            message_dict = {}
        self.code = code
        self.bo = bo
        self.message_dict = message_dict

    def get_code(self):
        return self.code

    def get_bo(self):
        return self.bo

    def get_i18n_message(self, lang_option):
        if 'zh_CN' == lang_option:
            return self.message_dict.get('zh_CN')
        else:
            return self.message_dict.get('en_US')

    def __str__(self):
        return f"SensitiveMsgException(code={self.code}, bo={self.bo}, message={self.message_dict})"
