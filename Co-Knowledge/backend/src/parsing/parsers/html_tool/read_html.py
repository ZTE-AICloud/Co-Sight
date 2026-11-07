import os

from parsing.parsers.html_tool import html_md_tool


class HtmlContentParser:
    def __init__(self):
        pass

    def read_html(self, file_path):
        """HTML → ``(content, blocks)``。

        ``content`` 仍是「句子 → 整段正文」的字典（既有契约）；``blocks`` 是
        markdown 结构块序列，供 ``BlockChunkSplitter`` 使用 —— 以前标题只存在于
        content 的 key 上，重组正文时被丢掉，切片不知道自己在哪一章。
        """
        file_name = os.path.basename(file_path)
        doc_name = os.path.splitext(file_name)[0]
        md_path = html_md_tool.write_md_for_html(file_path, doc_name, 'html')
        content = html_md_tool.save_standard_txt('html', md_path)
        blocks = html_md_tool.collect_blocks('html', md_path)
        return content, blocks
