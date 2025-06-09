# Copyright 2025 ZTE Corporation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
import traceback
import re
from pathlib import Path

from app.common.logger_util import logger

default_encoding: str = "utf-8"
DEFAULT_FORMAT: str = ".md"  # Default format for files without extension


class FileToolkit:
    def __init__(self, work_space_path: str = None):
        self.work_space_path = work_space_path if work_space_path else os.environ.get("WORKSPACE_PATH") or os.getcwd()

    def file_saver(self, content: str | bytes, file_path: str, mode: str = "a", binary: bool = False) -> str:
        r"""Save content to a file at the specified path. Supports both text and binary files. Default mode is append to preserve existing content.

        Args:
            content (str | bytes): The content to save to the file.
            file_path (str): Absolute path of the file to save. The file will be placed in workspace.
            mode (str, optional): The file opening mode. Default is 'a' for append. Use 'w' for write.
            binary (bool, optional): Whether to open file in binary mode. Default is False.

        Returns:
            str: A message indicating the result of the operation.
        """
        try:
            # Explicit validation for content parameter
            if content is None or (isinstance(content, str) and content.strip() == ''):
                error_msg = "ERROR: Missing required 'content' parameter. You must provide the actual text content to save to the file."
                logger.error(error_msg)
                return error_msg

            logger.info(f"Saving content to file: {file_path}")
            logger.info(f"Content length: {len(str(content)) if content else 0} characters")

            # Use the input path if it exists, otherwise use workspace path
            if os.path.exists(file_path):
                absolute_path = file_path
            else:
                absolute_path = os.path.join(self.work_space_path, os.path.basename(file_path))
                # If file doesn't exist and mode is append, change to write mode
                if mode == 'a':
                    mode = 'w'

            # Ensure the directory exists
            directory = os.path.dirname(absolute_path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)
            logger.info(f"saved file to absolute_path {absolute_path}")

            # Add 'b' to mode if binary
            file_mode = mode + 'b' if binary else mode
            with open(absolute_path, file_mode, encoding=None if binary else "utf-8") as file:
                file.write(content)

            return f"Content successfully saved to {absolute_path}"
        except TypeError as e:
            error_msg = f"ERROR: Invalid content parameter. Make sure you provide the 'content' parameter with the text to save: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return error_msg
        except Exception as e:
            logger.error(f"failed to save file: {str(e)}", exc_info=True)
            return f"Error saving file: {str(e)}"

    def file_read(self, file: str, start_line: int = None, end_line: int = None, sudo: bool = False,
                  binary: bool = False) -> str | bytes:
        r"""Read file content. Supports both text and binary files.

        Args:
            file (str): Absolute path of the file to read. The file must be in workspace.
            start_line (int, optional): Starting line to read from, 0-based (text files only)
            end_line (int, optional): Ending line number (exclusive, text files only)
            sudo (bool, optional): Whether to use sudo privileges
            binary (bool, optional): Whether to read file in binary mode

        Returns:
            str | bytes: The file content or error message
        """
        try:
            logger.info(f"reading content to file: {file}")
            # Use the input path if it exists, otherwise use workspace path
            if os.path.exists(file):
                absolute_path = file
            else:
                absolute_path = os.path.join(self.work_space_path, os.path.basename(file))

            # Verify file exists
            if not os.path.exists(absolute_path):
                return f"Error: File not found at {absolute_path}"

            # Read file content
            with open(absolute_path, 'rb' if binary else 'r', encoding=None if binary else 'utf-8') as f:
                if binary:
                    return f.read()
                else:
                    lines = f.readlines()

            # Handle line range for text files
            if start_line is not None or end_line is not None:
                start = start_line if start_line is not None else 0
                end = end_line if end_line is not None else len(lines)
                lines = lines[start:end]

            return ''.join(lines)
        except PermissionError as e:
            logger.error(f"Error: Permission denied. Try with sudo=True if appropriate: {str(e)}",exc_info=True)
            return "Error: Permission denied. Try with sudo=True if appropriate"
        except Exception as e:
            logger.error(f"Error reading file: {str(e)}", exc_info=True)
            return f"Error reading file: {str(e)}"

    def file_str_replace(self, file: str, old_str: str, new_str: str, sudo: bool = False) -> str:
        r"""Replace specified string in a text file. Supports text-based formats like txt, markdown, etc.

        Args:
            file (str): Absolute path of the text file to perform replacement on. The file must be in workspace.
            old_str (str): Original string to be replaced
            new_str (str): New string to replace with
            sudo (bool, optional): Whether to use sudo privileges

        Returns:
            str: Success message or error message
        """
        try:
            # Use the input path if it exists, otherwise use workspace path
            if os.path.exists(file):
                absolute_path = file
            else:
                absolute_path = os.path.join(self.work_space_path, os.path.basename(file))

            # Verify file exists
            if not os.path.exists(absolute_path):
                return f"Error: File not found at {absolute_path}"

            # Read file content
            with open(absolute_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Perform replacement
            new_content = content.replace(old_str, new_str)

            # Write updated content
            with open(absolute_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            return f"Successfully replaced '{old_str}' with '{new_str}' in {absolute_path}"
        except PermissionError as e:
            logger.error(f"Error: Permission denied. Try with sudo=True if appropriate: {str(e)}", exc_info=True)
            return "Error: Permission denied. Try with sudo=True if appropriate"
        except Exception as e:
            logger.error(f"Error replacing string in file: {str(e)}", exc_info=True)
            return f"Error replacing string in file: {str(e)}"

    def file_find_in_content(self, file: str, regex: str, sudo: bool = False) -> str:
        r"""Search for matching text within text file content. Supports text-based formats like txt, markdown, etc.

        Args:
            file (str): Absolute path of the text file to search within. The file must be in workspace.
            regex (str): Regular expression pattern to match
            sudo (bool, optional): Whether to use sudo privileges

        Returns:
            str: Matching results or error message
        """
        try:
            logger.info(f"finding content in file: {file}")
            import re

            # Use the input path if it exists, otherwise use workspace path
            if os.path.exists(file):
                absolute_path = file
            else:
                absolute_path = os.path.join(self.work_space_path, os.path.basename(file))

            # Verify file exists
            if not os.path.exists(absolute_path):
                return f"Error: File not found at {absolute_path}"

            # Read file content
            with open(absolute_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Find matches
            matches = re.findall(regex, content)

            if not matches:
                return f"No matches found for pattern '{regex}' in {absolute_path}"

            return f"Matches found in {absolute_path}:\n" + "\n".join(matches)
        except re.error as e:
            logger.error(f"Error: Invalid regular expression pattern: {str(e)}", exc_info=True)
            return "Error: Invalid regular expression pattern"
        except PermissionError as e:
            logger.error(f"Error: Permission denied. Try with sudo=True if appropriate: {str(e)}", exc_info=True)
            return "Error: Permission denied. Try with sudo=True if appropriate"
        except Exception as e:
            logger.error(f"Error searching file content: {str(e)}", exc_info=True)
            return f"Error searching file content: {str(e)}"

    def _write_text_file(
            self,
            file_path: Path,
            content: str,
            encoding: str = "utf-8",
            binary: bool = False,
            file_mode: str = "w"
    ) -> None:
        r"""Write text content to a plaintext file.

        Args:
            file_path (Path): The target file path.
            content (str): The text content to write.
            encoding (str): Character encoding to use. (default: :obj: `utf-8`)
        """
        with file_path.open(file_mode, encoding=None if binary else encoding) as f:
            f.write(content)
        logger.info(f"Wrote text to {file_path} with {encoding} encoding")

    def _write_docx_file(self, file_path: Path, content: str) -> None:
        r"""Write text content to a DOCX file with default formatting.

        Args:
            file_path (Path): The target file path.
            content (str): The text content to write.
        """
        import docx

        # Use default formatting values
        font_name = 'Calibri'
        font_size = 11
        line_spacing = 1.0

        document = docx.Document()
        style = document.styles['Normal']
        style.font.name = font_name
        style.font.size = docx.shared.Pt(font_size)
        style.paragraph_format.line_spacing = line_spacing

        # Split content into paragraphs and add them
        for para_text in content.split('\n'):
            para = document.add_paragraph(para_text)
            para.style = style

        document.save(str(file_path))
        logger.info(f"Wrote DOCX to {file_path} with default formatting")

    def _write_pdf_file(self, file_path: Path, content: str, **kwargs) -> None:
        r"""Write text content to a PDF file with default formatting.

        Args:
            file_path (Path): The target file path.
            content (str): The text content to write.

        Raises:
            RuntimeError: If the 'fpdf' library is not installed.
        """
        from fpdf import FPDF

        # Use default formatting values
        font_family = 'Arial'
        font_size = 12
        font_style = ''
        line_height = 10
        margin = 10

        pdf = FPDF()
        pdf.set_margins(margin, margin, margin)

        pdf.add_page()
        pdf.set_font(font_family, style=font_style, size=font_size)

        # Split content into paragraphs and add them
        for para in content.split('\n'):
            if para.strip():  # Skip empty paragraphs
                pdf.multi_cell(0, line_height, para)
            else:
                pdf.ln(line_height)  # Add empty line

        pdf.output(str(file_path))
        logger.info(f"Wrote PDF to {file_path} with custom formatting")

    def _write_csv_file(
            self,
            file_path: Path,
            content: str,
            encoding: str = "utf-8",
    ) -> None:
        r"""Write CSV content to a file.

        Args:
            file_path (Path): The target file path.
            content (str): The CSV content as a string or
                list of lists.
            encoding (str): Character encoding to use. (default: :obj: `utf-8`)
        """
        import csv

        with file_path.open("w", encoding=encoding, newline='') as f:
            if isinstance(content, str):
                f.write(content)
            else:
                writer = csv.writer(f)
                writer.writerows(content)
        logger.info(f"Wrote CSV to {file_path} with {encoding} encoding")

    def _write_json_file(
            self,
            file_path: Path,
            content: str,
            encoding: str = "utf-8",
    ) -> None:
        r"""Write JSON content to a file.

        Args:
            file_path (Path): The target file path.
            content (str): The JSON content as a string.
            encoding (str): Character encoding to use. (default: :obj: `utf-8`)
        """
        import json

        with file_path.open("w", encoding=encoding) as f:
            if isinstance(content, str):
                try:
                    # Try parsing as JSON string first
                    data = json.loads(content)
                    json.dump(data, f, ensure_ascii=False)
                except json.JSONDecodeError:
                    # If not valid JSON string, write as is
                    f.write(content)
            else:
                # If not string, dump as JSON
                json.dump(content, f, ensure_ascii=False)
        logger.info(f"Wrote JSON to {file_path} with {encoding} encoding")

    def _write_yaml_file(
            self,
            file_path: Path,
            content: str,
            encoding: str = "utf-8",
            binary: bool = False,
            file_mode: str = "w"
    ) -> None:
        r"""Write YAML content to a file.

        Args:
            file_path (Path): The target file path.
            content (str): The YAML content as a string.
            encoding (str): Character encoding to use. (default: :obj: `utf-8`)
        """
        with file_path.open(file_mode, encoding=None if binary else encoding) as f:
            f.write(content)
        logger.info(f"Wrote YAML to {file_path} with {encoding} encoding")

    def _write_html_file(
            self, file_path: Path, content: str, encoding: str = "utf-8", binary: bool = False, file_mode: str = "w"
    ) -> None:
        r"""Write text content to an HTML file.

        Args:
            file_path (Path): The target file path.
            content (str): The HTML content to write.
            encoding (str): Character encoding to use. (default: :obj: `utf-8`)
        """
        with file_path.open(file_mode, encoding=None if binary else encoding) as f:
            f.write(content)
        logger.info(f"Wrote HTML to {file_path} with {encoding} encoding")

    def _write_markdown_file(
            self, file_path: Path, content: str, encoding: str = "utf-8", binary: bool = False, file_mode: str = "w"
    ) -> None:
        r"""Write text content to a Markdown file.

        Args:
            file_path (Path): The target file path.
            content (str): The Markdown content to write.
            encoding (str): Character encoding to use. (default: :obj: `utf-8`)
        """
        with file_path.open(file_mode, encoding=None if binary else encoding) as f:
            f.write(content)
        logger.info(f"Wrote Markdown to {file_path} with {encoding} encoding")

    def _sanitize_filename(self, filename: str) -> str:
        r"""Sanitize a filename by replacing any character that is not
        alphanumeric, a dot (.), hyphen (-), or underscore (_) with an
        underscore (_).

        Args:
            filename (str): The original filename which may contain spaces or
                special characters.

        Returns:
            str: The sanitized filename with disallowed characters replaced by
                underscores.
        """
        safe = re.sub(r'[^\w\-.]', '_', filename)
        return safe

    def write_to_file(
            self, content: str | bytes, file_path: str, mode: str = "a", binary: bool = False
    ) -> str:
        r"""Write the given content to a file.

        If the file exists, it will be overwritten. Supports multiple formats:
        Markdown (.md, .markdown, default), Plaintext (.txt), CSV (.csv),
        DOC/DOCX (.doc, .docx), PDF (.pdf), JSON (.json), YAML (.yml, .yaml),
        and HTML (.html, .htm).

        Returns:
            str: A message indicating success or error details.
        """
        # Explicit validation for content parameter
        if content is None or (isinstance(content, str) and content.strip() == ''):
            error_msg = "ERROR: Missing required 'content' parameter. You must provide the actual text content to save to the file."
            logger.error(error_msg)
            return error_msg

        logger.info(f"Saving content to file: {file_path}")
        logger.info(f"Content length: {len(str(content)) if content else 0} characters")

        # Use the input path if it exists, otherwise use workspace path
        if os.path.exists(file_path):
            absolute_path = file_path
        else:
            absolute_path = os.path.join(self.work_space_path, os.path.basename(file_path))
            # If file doesn't exist and mode is append, change to write mode
            if mode == 'a':
                mode = 'w'

        # Ensure the directory exists
        directory = os.path.dirname(absolute_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        logger.info(f"saved file to absolute_path {absolute_path}")

        # Add 'b' to mode if binary
        file_mode = mode + 'b' if binary else mode

        # Use absolute_path for Path object, not the original file_path
        path_obj = Path(absolute_path)
        extension = path_obj.suffix.lower()

        # If no extension is provided, use the default format
        if extension == "":
            path_obj = path_obj.with_suffix(DEFAULT_FORMAT)
            extension = DEFAULT_FORMAT

        try:
            # Get encoding or use default
            file_encoding = default_encoding
            if extension in [".doc", ".docx"]:
                self._write_docx_file(path_obj, str(content))
            elif extension == ".pdf":
                self._write_pdf_file(path_obj, str(content))
            elif extension == ".csv":
                self._write_csv_file(
                    path_obj, content, encoding=file_encoding
                )
            elif extension == ".json":
                self._write_json_file(
                    path_obj,
                    content,  # type: ignore[arg-type]
                    encoding=file_encoding,
                )
            elif extension in [".yml", ".yaml"]:
                self._write_yaml_file(
                    path_obj, str(content), encoding=file_encoding, binary=binary, file_mode=mode
                )
            elif extension in [".html", ".htm"]:
                self._write_html_file(
                    path_obj, str(content), encoding=file_encoding, binary=binary, file_mode=mode
                )
            elif extension in [".md", ".markdown"]:
                self._write_markdown_file(
                    path_obj, str(content), encoding=file_encoding, binary=binary, file_mode=mode
                )
            else:
                # Fallback to simple text writing for unknown or .txt
                # extensions
                self._write_text_file(
                    path_obj, str(content), encoding=file_encoding, binary=binary, file_mode=mode
                )

            msg = f"Content successfully written to file: {absolute_path}"
            logger.info(msg)
            return msg
        except TypeError as e:
            error_msg = f"ERROR: Invalid content parameter. Make sure you provide the 'content' parameter with the text to save: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return error_msg
        except Exception as e:
            error_msg = (
                f"Error occurred while writing to file {absolute_path}: {str(e)}"
            )
            logger.error(error_msg, exc_info=True)
            return error_msg
