import os

from parsing.common.special_filter import SpecialFilter
from parsing.common.logutil import log


class LCDocument:
    def __init__(self, page_content, metadata, doc_id=None, blocks=None):
        self.page_content = page_content
        self.metadata = metadata
        self.id = doc_id
        #: 结构块序列（``parsing.block_splitter``）。只有带结构的解析器（docx）
        #: 会填；不进 metadata —— 它不该出现在切片元数据里。
        self.blocks = blocks


def create_doc(content, doc_name: list, space_id, is_qa=False):
    docs = []
    # 同一段正文会被复制到很多个 key 上（每句一个 key），它们是**同一个字符串
    # 对象**；不缓存的话要对整段正文跑 → 次正则，段落一多就是 O(n²)。
    # 3000 段的文档这一步 6.9s，占解析总时长一半。
    filtered = {}
    for key, value in content.items():
        if value:
            source = get_source(value, doc_name, space_id)
            text = value['text']
            slot = id(text)
            if slot not in filtered:
                filtered[slot] = (text, SpecialFilter().replace_content_char(text))
            metadata = {'source': source,
                        'content_expand': filtered[slot][1]}
            set_is_qa(is_qa, metadata)
            page_content = SpecialFilter().replace_char(key)
            document = LCDocument(page_content=page_content, metadata=metadata,
                                  blocks=value.get('blocks'))
            docs.append(document)
    return docs


def get_source(value, doc_name, space_id):
    if 'source' in value.keys():
        source = create_source([value['source']], space_id)
    else:
        source = create_source(doc_name, space_id)
    return source


def create_source(doc_name, space_id):
    source = '/'.join(doc_name)
    if space_id:
        source = f'{source}/{space_id}'
    return source


def create_doc_by_content(docs, page_content, content_expend, source, is_qa=False):
    metadata = {'source': source,
                'content_expand': content_expend}
    set_is_qa(is_qa, metadata)
    document = LCDocument(page_content=page_content, metadata=metadata)
    docs.append(document)


def set_is_qa(is_qa, metadata):
    if is_qa:
        metadata['type'] = 1


def write_txt(docs, txt_save_path):
    log.info(f'write txt {txt_save_path}')
    create_dir(txt_save_path)
    with open(txt_save_path, 'w',
              encoding='utf-8') as fout:
        for doc in docs:
            fout.write(str(doc))
            fout.write('\n')
        fout.close()


def create_dir(txt_save_path):
    parent_dir = os.path.dirname(txt_save_path)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir)
