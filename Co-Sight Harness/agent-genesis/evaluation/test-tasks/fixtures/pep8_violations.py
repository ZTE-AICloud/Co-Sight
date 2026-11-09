"""PEP 8 违规测试文件 — 含 6 个已知违规.

违规清单:
- E501: line too long (line 11)
- E302: expected 2 blank lines before function (line 11, 14)
- E305: expected 2 blank lines after function definition (line 17)
- W291: trailing whitespace (line 17)
- E703: statement ends with semicolon (line 19)
"""

def this_line_is_way_too_long_and_exceeds_the_79_character_limit_set_by_pep8_for_python_code_style_compliance():
    pass

def another_function():
    pass

x = 5+3  

y = 10;
