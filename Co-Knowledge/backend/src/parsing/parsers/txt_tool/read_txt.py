from parsing.common.decode_tool import detect_encoding
from parsing.common.sentence_add_validator import SentenceValidator
from parsing.common.special_filter import SpecialFilter
from parsing.common.logutil import log


class TxtContentParser:
    def __init__(self):
        pass

    def read_txt(self, file_path):
        content = self.read_txt_content(file_path)
        return self.create_doc_from_txt(content)

    def read_txt_content(self, file_path):
        log.info(f'read txt {file_path}')
        encoding = detect_encoding(file_path)
        log.info(f'encoding {encoding}')
        with open(file_path, newline='', encoding=encoding) as file:
            content = file.read()
        return content

    def create_doc_from_txt(self, content):
        result = {}
        paragraphs = content.split("\n")
        for paragraph in paragraphs:
            sentences = paragraph.split("。")
            for sentence in sentences:
                sentence = SpecialFilter().replace_pic_and_serial(sentence)
                if SentenceValidator().is_add_sentence_key(sentence):
                    result[sentence] = {'text': paragraph}
        return result
