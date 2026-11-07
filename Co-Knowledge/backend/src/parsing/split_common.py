import ast
import os
import re
import shutil
import uuid

from parsing import corpus

from parsing.common.logutil import log
from parsing.common.pathutil import get_workdir
from parsing.sensitive import SensitiveWordChecker


class LCDocument:
    def __init__(self, page_content, metadata, doc_id=None):
        self.page_content = page_content
        self.metadata = metadata
        self.id = doc_id


def file_split_common(input_path: str, chunk_size: int = 1024, chunk_overlap: int = 200, is_chunk_split: bool = False, custom_work_dir: str = None):
    # 如果传入了自定义work_dir，使用它；否则使用默认的
    if custom_work_dir:
        current_work_dir = custom_work_dir
    else:
        current_work_dir = get_workdir()
    base_filename = os.path.basename(input_path)
    _, extension = os.path.splitext(base_filename)
    extension_path = extension.lstrip('.')
    # 目录按**每次调用**的 uuid 命名：worker 线程池会并发切不同文件，同名文件
    # （不同目录下的「报告.docx」）会落到同一个临时目录，互相删目录/串内容。
    work_id = uuid.uuid4().hex
    corpus_split_path = f'{current_work_dir}/temp/corpus_split/{work_id}/{extension_path}'
    corpus.load_corpus_file(input_path, corpus_split_path, chunk_size, chunk_overlap, sensitive_checker=SensitiveWordChecker())
    temp_txt_file_name = f'{corpus_split_path}/output/corpus_file.txt'
    docs = []
    with open(temp_txt_file_name, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        for line in lines:
            try:
                if line.startswith("filepath="):
                    continue
                else:
                    # corpus_file.txt 是本模块自己写出的 repr 文本；用 literal_eval
                    # 而不是 eval —— 该文件位于可写临时目录，eval 会执行任意代码。
                    page_content = ast.literal_eval(line.split('metadata=')[0].split('page_content=')[1].strip())
                    metadata = ast.literal_eval(line.split('metadata=')[1])
                    docs.append(LCDocument(page_content=page_content, metadata=metadata))
            except Exception as e:
                # 不静默：坏行要被记录（不要 print 到 stdout，容器里等于丢失）
                log.warning(f'parse corpus_file line failed: {e}')
    filter_invalid_char(docs)
    if os.path.exists(corpus_split_path):
        shutil.rmtree(corpus_split_path)
    return docs


def filter_invalid_char(nodes):
    for document in nodes:
        page_content = document.page_content
        cleaned_invalid_content = re.sub(r'[\uD800-\uDBFF](?![\uDC00-\uDFFF])', '', page_content)
        document.page_content = cleaned_invalid_content.replace('\x00', '')
        metadata = document.metadata
        content_expand = metadata['content_expand']
        if content_expand:
            cleaned_invalid_content_expend = re.sub(r'[\uD800-\uDBFF](?![\uDC00-\uDFFF])', '', content_expand)
            metadata['content_expand'] = cleaned_invalid_content_expend.replace('\x00', '')


if __name__ == '__main__':
    import json

    result = file_split_common(
        "logfile.txt")
    # for res in result:
    #     print(res.metadata)
    with open("output_test.json", "w", encoding="utf-8") as file:
        for res in result:
            file.write(json.dumps(res.page_content, ensure_ascii=False, indent=4) + "\n")
            file.write(json.dumps(res.metadata, ensure_ascii=False, indent=4) + "\n")
