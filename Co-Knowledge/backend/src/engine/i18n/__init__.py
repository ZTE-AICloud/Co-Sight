from engine.i18n import rag_i18n


def get_i18n(language_option, error_tag, *args):
    error_infos = rag_i18n.i18n.get(error_tag)
    if error_infos:
        error_message = error_infos.get(language_option)
        return error_message.format(*args)
    return '内部错误，错误码缺失。' if language_option.startswith('zh') else 'Internal Error，error code missing.'


def _normalize_language(language_option):
    """i18n 表里的键只有 'zh'/'en'；其它写法（zh_CN、zh-Hans、空）一律归一到这两者。"""
    if not language_option:
        return 'zh'
    return 'zh' if str(language_option).lower().startswith('zh') else 'en'


def get_i18n_safe(language_option, error_tag, *args):
    """与 get_i18n 相同，但**绝不抛异常**。

    错误分支里不能再用一个会抛异常的取消息函数：一旦取不到（语言没归一 / 新增了错误码
    但漏了翻译），业务错误就会被 "Internal Server Error" 盖掉，现场只剩一个 500 —— 实测踩过。
    """
    try:
        return get_i18n(_normalize_language(language_option), error_tag, *args)
    except Exception:
        return f'{error_tag}{":" + str(args) if args else ""}'
