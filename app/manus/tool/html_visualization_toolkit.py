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
import json
import traceback
from typing import Dict, List, Optional, Union, Any
import re
import uuid
from app.manus import WORKSPACE_PATH


class HTMLVisualizationToolkit:
    """A toolkit for generating HTML visualizations including charts, graphs, and data displays."""
    
    def __init__(self):
        # Map chart types to their generation methods
        self.chart_generators = {
            'bar': self._generate_bar_chart_options,
            'line': self._generate_line_chart_options,
            'pie': self._generate_pie_chart_options,
            'scatter': self._generate_scatter_plot_options,
            'heatmap': self._generate_heatmap_options,
            'histogram': self._generate_histogram_options,
            'boxplot': self._generate_boxplot_options,
            'treemap': self._generate_treemap_options,
            'sankey': self._generate_sankey_options,
        }
        
        # Default data templates for different chart types
        self.default_data_templates = {
            'pie': lambda msg: [{"name": msg, "value": 100}],
            'table': lambda msg: [{msg: "This is a placeholder. Please collect actual data based on your analysis requirements."}],
            'histogram': lambda msg: [0],  # Empty histogram data
            'boxplot': lambda msg: [{"name": msg, "values": [0]}],
            'treemap': lambda msg: [{"name": msg, "value": 100}],
            'sankey': lambda msg: {"nodes": [{"name": msg}], "links": []},
            # Default for bar, line, scatter, heatmap, etc.
            'default': lambda msg: [{"x": msg, "y": 0}]
        }
        
        # HTML templates and CSS themes
        self.themes = {
            'default': self._get_default_theme_css,
            'dark': self._get_dark_theme_css,
            'professional': self._get_professional_theme_css
        }
        
    def create_visualization(self, 
                            chart_type: str,
                            data: str,
                            title: str = "Visualization",
                            width: int = 800,
                            height: int = 500,
                            options: str = "{}",
                            file_path: Optional[str] = None) -> str:
        r"""Create an HTML visualization based on the specified chart type and data.
        
        Args:
            chart_type (str): Type of chart to create. Options: "bar", "line", "pie", "scatter", "heatmap", "table"
            data (str): JSON string of data for the chart. Format depends on chart type.
            title (str, optional): Chart title. Default is "Visualization".
            width (int, optional): Width of the chart in pixels. Default is 800.
            height (int, optional): Height of the chart in pixels. Default is 500.
            options (str, optional): JSON string of additional chart options. Default is an empty object.
            file_path (str, optional): Absolute path (using the WORKSPACE_PATH environment variable) to save the generated HTML. If None, HTML is returned as string.
                
        Returns:
            str: Path to the saved HTML file or HTML content if file_path is None.
        """
        try:
            # Parse data
            parsed_data = self._parse_chart_data(data, chart_type, title)
            
            # Check if data collection is required
            if self._requires_data_collection(parsed_data):
                return self._handle_data_collection_required(chart_type, title, width, height, file_path)
            
            # Parse options
            options_dict = self._parse_options(options)
                
            # Generate HTML template
            html_content = self._generate_html_template(chart_type, parsed_data, title, width, height, options_dict)
            
            # Save to file or return HTML content
            if file_path:
                return self._save_html_to_file(html_content, file_path, title)
            else:
                return html_content
                
        except Exception as e:
            error_msg = f"Error generating visualization: {str(e)}"
            print(error_msg, traceback.format_exc())
            return error_msg
            
    def create_report(self,
                     title: str = "Interactive Report",
                     content: str = "",
                     visualizations: str = "[]",
                     css_theme: str = "default",
                     file_path: Optional[str] = None,
                     html_files: str = "[]",
                     presentation_mode: bool = False) -> str:
        r"""Create a complete HTML report with multiple visualizations and formatted text content.
        
        Args:
            title (str, optional): Report title. Default is "Interactive Report".
            content (str, optional): HTML/Markdown content for the report body.
            visualizations (str, optional): JSON string array of visualization objects.
            css_theme (str, optional): Theme for styling the report. Options: "default", "light", "dark", "professional".
            file_path (str, optional): Path to save the generated HTML. If None, HTML is returned as string.
            html_files (str, optional): JSON string array of visualization HTML file paths to include.
            presentation_mode (bool, optional): If True, generates a navigable presentation-style HTML instead of a scrolling document.
                
        Returns:
            str: Path to the saved HTML file or HTML content if file_path is None.
        """
        try:
            # Process visualizations and HTML files
            all_visualizations = self._process_visualizations_and_files(visualizations, html_files)
            
            # Generate the report HTML based on mode
            if presentation_mode:
                html_content = self._generate_presentation_template(title, content, all_visualizations, css_theme)
            else:
                html_content = self._generate_report_template(title, content, all_visualizations, css_theme)
            
            # Save to file or return HTML content
            if file_path:
                return self._save_html_to_file(html_content, file_path, title)
            else:
                return html_content
                
        except Exception as e:
            error_msg = f"Failed to create report: {str(e)}"
            print(error_msg, traceback.format_exc())
            return error_msg

    # Helper methods for parsing and processing data
    def _parse_chart_data(self, data: str, chart_type: str, title: str) -> Any:
        """Parse chart data from various formats into the internal format."""
        if isinstance(data, str):
            try:
                parsed_json = json.loads(data)
                
                # Handle charts.js format
                if isinstance(parsed_json, dict) and "labels" in parsed_json and "datasets" in parsed_json:
                    return self._convert_chartjs_format(parsed_json, chart_type)
                elif isinstance(parsed_json, list):
                    return parsed_json
                else:
                    print(f"Warning: Data format not recognized for chart type '{chart_type}'. Data collection is required.")
                    return self._generate_default_data(chart_type, title)
            except json.JSONDecodeError:
                print(f"Warning: Invalid JSON in data parameter for chart type '{chart_type}'. Data collection is required.")
                return self._generate_default_data(chart_type, title)
        else:
            return data
            
    def _convert_chartjs_format(self, chartjs_data: Dict, chart_type: str) -> List:
        """Convert Charts.js format to our internal format."""
        parsed_data = []
        labels = chartjs_data.get("labels", [])
        datasets = chartjs_data.get("datasets", [])
        
        if len(datasets) > 0 and "data" in datasets[0]:
            dataset = datasets[0]  # Use the first dataset
            data_values = dataset.get("data", [])
            
            for i, label in enumerate(labels):
                if i < len(data_values):
                    if chart_type == 'pie':
                        parsed_data.append({"name": label, "value": data_values[i]})
                    else:
                        parsed_data.append({"x": label, "y": data_values[i]})
        
        return parsed_data
        
    def _requires_data_collection(self, data: Any) -> bool:
        """Check if data collection is required based on the parsed data."""
        if not data:
            return True
            
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            if ("x" in data[0] and data[0]["x"] == "DATA_COLLECTION_REQUIRED") or \
               ("name" in data[0] and data[0]["name"] == "DATA_COLLECTION_REQUIRED"):
                return True
                
        return False
        
    def _handle_data_collection_required(self, chart_type: str, title: str, width: int, height: int, file_path: Optional[str]) -> str:
        """Handle the case when data collection is required."""
        # Create a placeholder visualization message
        placeholder_message = f"""
        <div style="width: {width}px; height: {height}px; border: 2px dashed #ccc; margin: 20px auto; text-align: center; padding: 20px; font-family: Arial, sans-serif;">
            <h2 style="color: #555;">Data Collection Required</h2>
            <p style="color: #777; font-size: 16px;">
                This {chart_type} chart requires actual data to be collected and analyzed.
                <br><br>
                Please gather relevant data from your analysis to create this visualization.
            </p>
        </div>
        """
        
        # If file_path is provided, save the placeholder
        if file_path:
            basic_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{title} - Data Required</title>
</head>
<body>
    <h1 style="text-align: center;">{title}</h1>
    {placeholder_message}
</body>
</html>"""
            
            return self._save_html_to_file(basic_html, file_path, f"{title} - Data Required")
        else:
            return placeholder_message
            
    def _parse_options(self, options: Union[str, Dict]) -> Dict:
        """Parse options string or dict into a dictionary."""
        try:
            if isinstance(options, str):
                return json.loads(options)
            else:
                return options
        except json.JSONDecodeError:
            print("Warning: Invalid JSON in options parameter. Using empty options.")
            return {}
            
    def _save_html_to_file(self, html_content: str, file_path: str, title: str) -> str:
        """Save HTML content to a file and return a success message."""
        try:
            print(f"Saving HTML content to file: {file_path}")
            
            # If input is just a filename (no directory), use workspace path
            if not os.path.dirname(file_path):
                workspace_path = os.getenv("WORKSPACE_PATH") or os.getcwd()
                absolute_path = os.path.join(workspace_path, file_path)
            # If input is a relative path, resolve it to absolute path
            elif not os.path.isabs(file_path):
                workspace_path = os.getenv("WORKSPACE_PATH") or os.getcwd()
                absolute_path = os.path.join(workspace_path, file_path)
            # If input is an absolute path, use it directly
            else:
                absolute_path = file_path
            
            # If file doesn't exist, ensure we're in write mode
            mode = 'w' if not os.path.exists(absolute_path) else 'a'

            # Ensure the directory exists
            directory = os.path.dirname(absolute_path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)
            print(f"Saved HTML file to absolute_path: {absolute_path}")

            # Write HTML content
            with open(absolute_path, mode, encoding="utf-8") as file:
                file.write(html_content)

            return f"HTML content successfully saved to {absolute_path}"
        except Exception as e:
            print(f"Failed to save HTML file: {e}", traceback.format_exc())
            return f"Error saving HTML file: {str(e)}"
        
    def _process_visualizations_and_files(self, visualizations: str, html_files: str) -> List[Dict]:
        """Process visualization specifications and HTML files into a unified list."""
        all_visualizations = []
        
        # Process explicitly provided visualizations
        try:
            viz_list = json.loads(visualizations) if visualizations else []
            for viz in viz_list:
                # Format data properly if it's a string
                if isinstance(viz.get('data'), str):
                    try:
                        viz['data'] = json.loads(viz['data'])
                    except json.JSONDecodeError:
                        viz['data'] = self._generate_default_data(viz.get('chart_type', 'bar'), viz.get('title', ''))
                
                all_visualizations.append(viz)
        except json.JSONDecodeError:
            print("Warning: Invalid JSON format for visualizations parameter. Ignoring.")
        
        # Process HTML files
        try:
            file_list = self._parse_html_files_param(html_files)
            for html_file in file_list:
                try:
                    # Resolve file path
                    workspace_path = os.getenv("WORKSPACE_PATH") or os.getcwd()
                    full_path =  html_file
                    
                    if not os.path.isfile(full_path):
                        print(f"Warning: File does not exist: {full_path}. Skipping.")
                        continue
                    
                    # Read file content
                    with open(full_path, 'r', encoding='utf-8') as f:
                        html_content = f.read()
                    
                    # Extract visualization or fix chart placeholders
                    viz = self._process_html_file_content(html_content, html_file)
                    if viz:
                        all_visualizations.append(viz)
                except Exception as e:
                    print(f"Error processing file {html_file}: {str(e)}")
        except Exception as e:
            print(f"Error processing HTML files: {str(e)}")
            
        return all_visualizations
    
    def _parse_html_files_param(self, html_files: Union[str, List]) -> List[str]:
        """Parse the html_files parameter into a list of file paths."""
        file_list = []
        if html_files:
            if isinstance(html_files, str):
                try:
                    parsed = json.loads(html_files)
                    file_list = parsed if isinstance(parsed, list) else [parsed]
                except json.JSONDecodeError:
                    if html_files.strip():
                        file_list = [html_files.strip()]
            elif isinstance(html_files, list):
                file_list = html_files
        return file_list
    
    def _process_html_file_content(self, html_content: str, file_name: str) -> Optional[Dict]:
        """Process HTML file content to extract visualization or fix chart placeholders."""
        # Extract title
        title_match = re.search(r'<title>(.*?)</title>', html_content)
        chart_title = title_match.group(1) if title_match else os.path.basename(file_name)
        
        # Check for chart placeholders
        if '{CHART_OPTIONS}' in html_content:
            # Determine chart type from content or filename
            chart_type = "bar"  # Default
            if "line" in file_name.lower() or "trend" in chart_title.lower():
                chart_type = "line"
            elif "pie" in file_name.lower() or "distribution" in chart_title.lower():
                chart_type = "pie"
            elif "scatter" in file_name.lower():
                chart_type = "scatter"
            
            # Generate default data
            default_data = self._generate_default_data(chart_type, chart_title)
            
            return {
                'chart_type': chart_type,
                'data': default_data,
                'title': chart_title,
                'options': {}
            }
        
        # Try to extract visualization from complete HTML file
        viz = self._extract_visualization_from_html(html_content, chart_title)
        return viz
    
    def _generate_default_data(self, chart_type: str, title: str = "") -> List:
        """Generate default data for a specific chart type."""
        message = "DATA_COLLECTION_REQUIRED"
        
        # Use template if available, otherwise default to generic format
        template = self.default_data_templates.get(chart_type, self.default_data_templates['default'])
        return template(message)
    
    def _extract_visualization_from_html(self, html_content: str, chart_title: str) -> Optional[Dict]:
        """Extract visualization data from HTML content."""
        try:
            # Extract options object
            options_pattern = r'var\s+option\s*=\s*({.*?});'
            chart_options_match = re.search(options_pattern, html_content, re.DOTALL)
            
            if not chart_options_match:
                return None
            
            # Extract and parse chart options
            try:
                chart_options_str = chart_options_match.group(1)
                
                # Clean up the JS object to make it valid JSON
                chart_options_str = re.sub(r'([{,])\s*(\w+):', r'\1"\2":', chart_options_str)
                chart_options_str = re.sub(r'\'([^\']+)\'', r'"\1"', chart_options_str)
                
                chart_options = json.loads(chart_options_str)
                
                # Determine chart type from options
                chart_type = "bar"  # Default
                if "series" in chart_options and isinstance(chart_options["series"], list) and len(chart_options["series"]) > 0:
                    if "type" in chart_options["series"][0]:
                        chart_type = chart_options["series"][0]["type"]
                
                # Extract data based on chart type
                data = self._extract_data_from_chart_options(chart_options, chart_type)
                
                if not data:
                    data = self._generate_default_data(chart_type, chart_title)
                
                return {
                    'chart_type': chart_type,
                    'data': data,
                    'title': chart_title,
                    'options': {}
                }
            except Exception as e:
                print(f"Error parsing chart options: {str(e)}. Using default data.")
                return None
        except Exception as e:
            print(f"Error extracting visualization from HTML: {str(e)}")
            return None

    def _extract_data_from_chart_options(self, chart_options: Dict, chart_type: str) -> List:
        """Extract data from chart options based on chart type."""
        data = []
        
        if chart_type in ["bar", "line"]:
            # Extract x-axis categories and y values
            x_values = chart_options.get("xAxis", {}).get("data", [])
            y_values = []
            
            if "series" in chart_options and len(chart_options["series"]) > 0:
                y_values = chart_options["series"][0].get("data", [])
            
            # Create data array with x and y values
            for i in range(min(len(x_values), len(y_values))):
                data.append({"x": x_values[i], "y": y_values[i]})
        
        elif chart_type == "pie":
            # Extract name and value pairs
            if "series" in chart_options and len(chart_options["series"]) > 0:
                pie_data = chart_options["series"][0].get("data", [])
                for item in pie_data:
                    if isinstance(item, dict) and "name" in item and "value" in item:
                        data.append({"name": item["name"], "value": item["value"]})
        
        return data 


    def _generate_html_template(
        self,
        chart_type: str,
        data: Any,
        title: str,
        width: int,
        height: int,
        options: Dict
    ) -> str:
        """Generate HTML template for a visualization.

        支持两种模式：
        1. 完整文档模式（默认）：返回 <html>…</html> 的整页字符串
        2. 内嵌模式（embed=True）：只返回 <style> + <div id=…>（可选）+ <script> 的片段
            并可通过 options['container_id'] 指定已有容器的 ID
        """
        try:
            # 先处理表格，逻辑不变
            if chart_type == 'table':
                table_html = self._generate_table_html(data, title, width, height, options)
                # 表格只做完整文档模式
                return f"""<!DOCTYPE html>
    <html>
    <head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        /* 你的全局表格样式 */
        {self._get_table_css(options)}
    </style>
    </head>
    <body>
    <h1 style="text-align:center">{title}</h1>
    <div class="content-container" style="max-width:{width}px;margin:0 auto">
        {table_html}
    </div>
    </body>
    </html>"""

            # 检查是否内嵌模式
            embed = bool(options.pop('embed', False))
            # 如果用户指定了 container_id，就用它，否则在 embed 模式下也自动生成
            container_id = options.pop('container_id', None)
            if embed and not container_id:
                container_id = f"chart-{uuid.uuid4().hex}"

            # 调用对应的 chart generator 得到 ECharts 配置
            generator = self.chart_generators.get(chart_type, self.chart_generators['bar'])
            chart_options = generator(data, title, options)

            # --- 内嵌模式：仅返回片段 ---
            if embed:
                # 1) 可选：如果用户没有先在内容里写 <div id="…"></div>，我们顺便输出一个
                div_html = (
                    f'<div id="{container_id}" '
                    f'style="width:{width}px;height:{height}px;'
                    'background-color:var(--card-bg);'
                    'border-radius:var(--border-radius);'
                    'box-shadow:var(--shadow);'
                    'margin:2rem auto;overflow:hidden;"></div>'
                )

                # 2) 样式复用：把你原来在 <head><style> 里的 CSS 片段塞进来
                style_block = f"""<style>
    :root {{
    --primary-color: #4361ee;
    --secondary-color: #3f37c9;
    --accent-color: #4895ef;
    --text-color: #2b2d42;
    --bg-color: #f8f9fa;
    --card-bg: #ffffff;
    --border-radius: 8px;
    --shadow: 0 4px 6px rgba(0,0,0,0.1),0 1px 3px rgba(0,0,0,0.08);
    --transition: all 0.3s ease;
    }}
    body {{
    font-family: 'Inter', sans-serif;
    background-color: var(--bg-color);
    color: var(--text-color);
    }}
    #{container_id} {{
    transition: var(--transition);
    }}
    #{container_id}:hover {{
    box-shadow: 0 10px 20px rgba(0,0,0,0.12),0 4px 8px rgba(0,0,0,0.06);
    transform: translateY(-5px);
    }}
    @media(max-width:900px) {{
    #{container_id} {{
        width:100% !important;
        height:400px !important;
    }}
    }}
    </style>"""

                # 3) 脚本初始化
                script_block = f"""<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <script>
    document.addEventListener('DOMContentLoaded', function() {{
    var dom = document.getElementById('{container_id}');
    var chart = echarts.init(dom);
    var opt = {chart_options};
    chart.setOption(opt);
    window.addEventListener('resize', function() {{ chart.resize(); }});
    }});
    </script>"""

                # 最终只输出 div+style+script
                return "\n".join([style_block, div_html, script_block])

            # --- 完整文档模式：行为与之前几乎一致，只是把 ID 动态化 ---
            html = f"""<!DOCTYPE html>
    <html>
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>{title}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        /* 全局样式 */
        body {{ margin:0;padding:0;background:var(--bg-color);color:var(--text-color);font-family:'Inter',sans-serif; }}
        h1 {{ text-align:center;color:var(--primary-color);margin:2rem 0;font-weight:700; }}
        .container {{ max-width:1200px;margin:0 auto;padding:2rem; }}
        /* 这里用动态 ID */
        #{container_id} {{
        width:{width}px;
        height:{height}px;
        margin:2rem auto;
        background-color:var(--card-bg);
        border-radius:var(--border-radius);
        box-shadow:var(--shadow);
        overflow:hidden;
        }}
        #{container_id}:hover {{
        box-shadow:0 10px 20px rgba(0,0,0,0.12),0 4px 8px rgba(0,0,0,0.06);
        transform:translateY(-5px);
        }}
        @media(max-width:900px) {{
        #{container_id} {{ width:100% !important; height:400px !important; }}
        }}
    </style>
    </head>
    <body>
    <div class="container">
        <h1>{title}</h1>
        <div id="{container_id}"></div>
    </div>
    <script>
        var dom = document.getElementById('{container_id}');
        var chart = echarts.init(dom);
        chart.setOption({chart_options});
        window.addEventListener('resize', function() {{ chart.resize(); }});
    </script>
    </body>
    </html>"""
            return html

        except Exception as e:
            print(f"Error generating HTML template: {e}")
            return f"""<!DOCTYPE html>
    <html><head><meta charset="UTF-8"><title>Error</title></head>
    <body><h1>Error Generating Chart</h1><p>{e}</p></body></html>"""


            
    def _generate_bar_chart_options(self, data: List[Dict], title: str, options: Dict) -> str:
        """Generate options for a bar chart."""
        try:
            # Extract data for bar chart
            x_data = []
            y_data = []
            
            for item in data:
                if "x" in item and "y" in item:
                    x_data.append(item["x"])
                    y_data.append(item["y"])
            
            bar_options = {
                "title": {"text": title},
                "tooltip": {},
                "xAxis": {
                    "type": "category",
                    "data": x_data,
                    "axisLabel": {
                        "rotate": options.get("rotateLabels", 0)
                    }
                },
                "yAxis": {
                    "type": "value"
                },
                "series": [{
                    "name": options.get("seriesName", "Value"),
                    "type": "bar",
                    "data": y_data,
                    "itemStyle": {
                        "color": options.get("barColor", "#5470c6")
                    }
                }]
            }
            
            # Apply custom options
            for key, value in options.items():
                if key not in ["rotateLabels", "seriesName", "barColor"]:
                    bar_options[key] = value
            
            return json.dumps(bar_options)
        except Exception as e:
            print(f"Error generating options for chart type 'bar': {e}")
            return json.dumps({"title": {"text": title}, "series": [{"type": "bar", "data": [10, 20]}]})
            
    def _generate_line_chart_options(self, data: List[Dict], title: str, options: Dict) -> str:
        """Generate options for a line chart."""
        try:
            # Extract data for line chart
            x_data = []
            y_data = []
            
            for item in data:
                if "x" in item and "y" in item:
                    x_data.append(item["x"])
                    y_data.append(item["y"])
            
            line_options = {
                "title": {"text": title},
                "tooltip": {
                    "trigger": "axis"
                },
                "xAxis": {
                    "type": "category",
                    "data": x_data,
                    "axisLabel": {
                        "rotate": options.get("rotateLabels", 0)
                    }
                },
                "yAxis": {
                    "type": "value"
                },
                "series": [{
                    "name": options.get("seriesName", "Value"),
                    "type": "line",
                    "data": y_data,
                    "smooth": options.get("smooth", False),
                    "lineStyle": {
                        "width": options.get("lineWidth", 2),
                        "type": options.get("lineType", "solid"),
                        "color": options.get("lineColor", "#5470c6")
                    },
                    "symbol": options.get("symbol", "circle"),
                    "symbolSize": options.get("symbolSize", 4)
                }]
            }
            
            # Apply custom options
            for key, value in options.items():
                if key not in ["rotateLabels", "seriesName", "smooth", "lineWidth", "lineType", "lineColor", "symbol", "symbolSize"]:
                    line_options[key] = value
            
            return json.dumps(line_options)
        except Exception as e:
            print(f"Error generating options for chart type 'line': {e}")
            return json.dumps({"title": {"text": title}, "series": [{"type": "line", "data": [10, 20]}]})
            
    def _generate_pie_chart_options(self, data: List[Dict], title: str, options: Dict) -> str:
        """Generate options for a pie chart."""
        try:
            # Extract data for pie chart
            pie_data = []
            
            # Handle different data formats
            for item in data:
                # Case 1: Standard pie chart format {"name": "X", "value": Y}
                if "name" in item and "value" in item:
                    pie_data.append({
                        "name": str(item["name"]),
                        "value": float(item["value"])
                    })
                # Case 2: Sector/Contribution format used in GDP data
                elif "Sector" in item and ("Contribution" in item or "Value" in item or "value" in item):
                    pie_data.append({
                        "name": str(item["Sector"]),
                        "value": float(item.get("Contribution") or item.get("Value") or item.get("value", 0))
                    })
                # Case 3: Any key/value pair (use first key as name, second as value)
                elif len(item) >= 2:
                    keys = list(item.keys())
                    pie_data.append({
                        "name": str(item[keys[0]]),
                        "value": float(item[keys[1]]) if isinstance(item[keys[1]], (int, float)) else 0
                    })
            
            # Generate pie chart options
            pie_options = {
                "title": {
                    "text": title,
                    "left": "center"
                },
                "tooltip": {
                    "trigger": "item",
                    "formatter": "{b}: {c} ({d}%)"
                },
                "legend": {
                    "orient": "vertical",
                    "left": options.get("legendPosition", "right") 
                },
                "series": [
                    {
                        "name": options.get("seriesName", "Category"),
                        "type": "pie",
                        "radius": options.get("radius", "50%"),
                        "center": options.get("center", ["50%", "50%"]),
                        "data": pie_data,
                        "emphasis": {
                            "itemStyle": {
                                "shadowBlur": 10,
                                "shadowOffsetX": 0,
                                "shadowColor": "rgba(0, 0, 0, 0.5)"
                            }
                        },
                        "label": {
                            "show": options.get("showLabels", True)
                        }
                    }
                ]
            }
            
            # Apply custom options
            for key, value in options.items():
                if key not in ["legendPosition", "seriesName", "radius", "center", "showLabels"]:
                    pie_options[key] = value
            
            return json.dumps(pie_options, ensure_ascii=False)
        except Exception as e:
            print(f"Error generating options for chart type 'pie': {e}")
            return json.dumps({
                "title": {"text": title},
                "series": [{
                    "type": "pie",
                    "data": [
                        {"name": "Category 1", "value": 60},
                        {"name": "Category 2", "value": 40}
                    ]
                }]
            })
            
    def _generate_scatter_plot_options(self, data: List[Dict], title: str, options: Dict) -> str:
        """Generate options for a scatter plot."""
        try:
            # Extract data for scatter plot
            scatter_data = []
            
            for item in data:
                if "x" in item and "y" in item:
                    scatter_data.append([item["x"], item["y"]])
            
            scatter_options = {
                "title": {"text": title},
                "tooltip": {
                    "trigger": "item",
                    "formatter": function_formatter if options.get("customFormatter", False) else "{c}"
                },
                "xAxis": {},
                "yAxis": {},
                "series": [{
                    "symbolSize": options.get("symbolSize", 10),
                    "type": "scatter",
                    "data": scatter_data,
                    "itemStyle": {
                        "color": options.get("markerColor", "#5470c6")
                    }
                }]
            }
            
            # Apply custom options
            for key, value in options.items():
                if key not in ["symbolSize", "customFormatter", "markerColor"]:
                    scatter_options[key] = value
            
            # Fix the formatter if it's custom
            function_formatter = "function(params) { return params[0] + ': ' + params[1]; }"
            scatter_options_json = json.dumps(scatter_options)
            if options.get("customFormatter", False):
                scatter_options_json = scatter_options_json.replace('"function_formatter"', function_formatter)
            
            return scatter_options_json
        except Exception as e:
            print(f"Error generating options for chart type 'scatter': {e}")
            return json.dumps({
                "title": {"text": title},
                "series": [{
                    "type": "scatter",
                    "data": [[10, 20], [30, 40]]
                }]
            })
            
    def _generate_heatmap_options(self, data: List[Dict], title: str, options: Dict) -> str:
        """Generate options for a heatmap."""
        try:
            # Extract data for heatmap
            x_categories = []
            y_categories = []
            heatmap_data = []
            
            # First, collect all unique x and y values
            for item in data:
                if "x" in item and "y" in item and "value" in item:
                    if item["x"] not in x_categories:
                        x_categories.append(item["x"])
                    if item["y"] not in y_categories:
                        y_categories.append(item["y"])
            
            # Sort categories if needed
            if options.get("sortXCategories", False):
                x_categories.sort()
            if options.get("sortYCategories", False):
                y_categories.sort()
            
            # Create data points in the format expected by ECharts
            for item in data:
                if "x" in item and "y" in item and "value" in item:
                    x_index = x_categories.index(item["x"])
                    y_index = y_categories.index(item["y"])
                    heatmap_data.append([x_index, y_index, item["value"]])
            
            heatmap_options = {
                "title": {"text": title},
                "tooltip": {
                    "position": 'top'
                },
                "grid": {
                    "top": '10%',
                    "height": '50%',
                    "y": '10%'
                },
                "xAxis": {
                    "type": 'category',
                    "data": x_categories,
                    "splitArea": {
                        "show": True
                    }
                },
                "yAxis": {
                    "type": 'category',
                    "data": y_categories,
                    "splitArea": {
                        "show": True
                    }
                },
                "visualMap": {
                    "min": options.get("min", 0),
                    "max": options.get("max", 100),
                    "calculable": True,
                    "orient": 'horizontal',
                    "left": 'center',
                    "bottom": '0%',
                    "inRange": {
                        "color": options.get("colorRange", ['#313695', '#4575b4', '#74add1', '#abd9e9', '#e0f3f8', '#ffffbf', '#fee090', '#fdae61', '#f46d43', '#d73027', '#a50026'])
                    }
                },
                "series": [{
                    "name": options.get("seriesName", "Heatmap"),
                    "type": 'heatmap',
                    "data": heatmap_data,
                    "label": {
                        "show": options.get("showLabels", False)
                    },
                    "emphasis": {
                        "itemStyle": {
                            "shadowBlur": 10,
                            "shadowColor": 'rgba(0, 0, 0, 0.5)'
                        }
                    }
                }]
            }
            
            # Apply custom options
            for key, value in options.items():
                if key not in ["sortXCategories", "sortYCategories", "min", "max", "colorRange", "seriesName", "showLabels"]:
                    heatmap_options[key] = value
            
            return json.dumps(heatmap_options)
        except Exception as e:
            print(f"Error generating options for chart type 'heatmap': {e}")
            return json.dumps({
                "title": {"text": title},
                "series": [{
                    "type": "heatmap",
                    "data": [[0, 0, 5], [0, 1, 10]]
                }]
            })
            
    def _generate_histogram_options(self, data: List, title: str, options: Dict) -> str:
        """Generate options for a histogram."""
        try:
            # Set default binning options
            bin_count = options.get("binCount", 10)
            
            # Ensure data is a flat list of values
            flat_data = []
            for item in data:
                if isinstance(item, dict) and "value" in item:
                    flat_data.append(item["value"])
                elif isinstance(item, (int, float)):
                    flat_data.append(item)
            
            if not flat_data:
                flat_data = [0]  # Default for empty data
            
            # Find min/max for binning
            min_val = min(flat_data)
            max_val = max(flat_data)
            bin_size = (max_val - min_val) / bin_count if max_val > min_val else 1
            
            # Create bins
            bins = []
            for i in range(bin_count):
                bin_start = min_val + i * bin_size
                bin_end = min_val + (i + 1) * bin_size
                bins.append([bin_start, 0])  # Initialize with zero count
            
            # Count values in each bin
            for val in flat_data:
                bin_index = min(bin_count - 1, max(0, int((val - min_val) / bin_size)))
                bins[bin_index][1] += 1
            
            # Extract bin positions and counts for chart
            bin_positions = [f"{round(bin[0], 2)}" for bin in bins]
            bin_counts = [bin[1] for bin in bins]
            
            histogram_options = {
                "title": {"text": title},
                "tooltip": {
                    "trigger": "axis",
                    "axisPointer": {
                        "type": "shadow"
                    }
                },
                "grid": {
                    "left": "3%",
                    "right": "4%",
                    "bottom": "3%",
                    "containLabel": True
                },
                "xAxis": {
                    "type": "category",
                    "data": bin_positions,
                    "name": options.get("xAxisName", "Value"),
                    "axisLabel": {
                        "rotate": options.get("rotateLabels", 0)
                    }
                },
                "yAxis": {
                    "type": "value",
                    "name": options.get("yAxisName", "Frequency")
                },
                "series": [{
                    "name": options.get("seriesName", "Frequency"),
                    "type": "bar",
                    "data": bin_counts,
                    "itemStyle": {
                        "color": options.get("barColor", "#5470c6")
                    }
                }]
            }
            
            # Apply custom options
            for key, value in options.items():
                if key not in ["binCount", "xAxisName", "yAxisName", "rotateLabels", "seriesName", "barColor"]:
                    histogram_options[key] = value
            
            return json.dumps(histogram_options)
        except Exception as e:
            print(f"Error generating options for chart type 'histogram': {e}")
            return json.dumps({
                "title": {"text": title},
                "series": [{
                    "type": "bar",
                    "data": [5, 10, 15, 8, 3]
                }]
            })
            
    def _generate_boxplot_options(self, data: List[Dict], title: str, options: Dict) -> str:
        """Generate options for a box plot."""
        try:
            # Organize data by categories
            categories = {}
            for item in data:
                category = item.get('category', 'Default')
                value = item.get('value', 0)
                if category not in categories:
                    categories[category] = []
                categories[category].append(value)
            
            # Prepare boxplot data format
            boxplot_data = []
            category_names = []
            
            for category, values in categories.items():
                category_names.append(category)
                # Sort values for percentile calculations
                values.sort()
                
                # Calculate quartiles and whiskers
                q1 = self._percentile(values, 25)
                median = self._percentile(values, 50)
                q3 = self._percentile(values, 75)
                iqr = q3 - q1
                lower_whisker = max(min(values), q1 - 1.5 * iqr)
                upper_whisker = min(max(values), q3 + 1.5 * iqr)
                
                # Box plot format: [lower whisker, Q1, median, Q3, upper whisker]
                boxplot_data.append([lower_whisker, q1, median, q3, upper_whisker])
            
            # Boxplot options
            boxplot_options = {
                'title': {'text': title},
                'tooltip': {
                    'trigger': 'item',
                    'formatter': '{b}: {c}'
                },
                'xAxis': {
                    'type': 'category',
                    'data': category_names,
                    'axisLabel': {'rotate': options.get('rotateLabels', 0)}
                },
                'yAxis': {'type': 'value'},
                'series': [{
                    'name': options.get('seriesName', 'Distribution'),
                    'type': 'boxplot',
                    'data': boxplot_data,
                    'itemStyle': {
                        'color': options.get('boxColor', '#5470c6'),
                        'borderColor': options.get('borderColor', '#000')
                    }
                }]
            }
            
            # Apply any additional custom options
            for key, value in options.items():
                if key not in ['rotateLabels', 'seriesName', 'boxColor', 'borderColor']:
                    boxplot_options[key] = value
            
            return json.dumps(boxplot_options)
        except Exception as e:
            print(f"Error generating options for chart type 'boxplot': {e}")
            return json.dumps({
                "title": {"text": title},
                "series": [{
                    "type": "boxplot",
                    "data": [[1, 3, 5, 7, 9]]
                }]
            })
            
    def _percentile(self, values: List[float], percentile: float) -> float:
        """Calculate the percentile of a list of values."""
        if not values:
            return 0
        
        index = (len(values) - 1) * percentile / 100
        if index.is_integer():
            return values[int(index)]
        else:
            lower_index = int(index)
            upper_index = lower_index + 1
            weight = index - lower_index
            return (1 - weight) * values[lower_index] + weight * values[upper_index]
    
    def _generate_treemap_options(self, data: List[Dict], title: str, options: Dict) -> str:
        """Generate options for a treemap."""
        try:
            treemap_options = {
                'title': {'text': title},
                'tooltip': {
                    'formatter': '{b}: {c}'
                },
                'series': [{
                    'name': options.get('seriesName', 'Treemap'),
                    'type': 'treemap',
                    'data': data,
                    'label': {
                        'show': options.get('showLabels', True)
                    },
                    'upperLabel': {
                        'show': options.get('showUpperLabels', False)
                    },
                    'itemStyle': {
                        'borderColor': options.get('borderColor', '#fff')
                    },
                    'levels': options.get('levels', [
                        {
                            'itemStyle': {
                                'borderColor': '#777',
                                'borderWidth': 3,
                                'gapWidth': 3
                            }
                        },
                        {
                            'itemStyle': {
                                'borderColor': '#555',
                                'borderWidth': 2,
                                'gapWidth': 2
                            }
                        },
                        {
                            'itemStyle': {
                                'borderColor': '#333',
                                'borderWidth': 1,
                                'gapWidth': 1
                            }
                        }
                    ])
                }]
            }
            
            # Apply custom options
            for key, value in options.items():
                if key not in ['seriesName', 'showLabels', 'showUpperLabels', 'borderColor', 'levels']:
                    treemap_options[key] = value
            
            return json.dumps(treemap_options)
        except Exception as e:
            print(f"Error generating options for chart type 'treemap': {e}")
            return json.dumps({
                "title": {"text": title},
                "series": [{
                    "type": "treemap",
                    "data": [
                        {"name": "Category 1", "value": 60},
                        {"name": "Category 2", "value": 40}
                    ]
                }]
            })
    
    def _generate_sankey_options(self, data: Dict, title: str, options: Dict) -> str:
        """Generate options for a Sankey diagram."""
        try:
            sankey_options = {
                'title': {'text': title},
                'tooltip': {
                    'trigger': 'item',
                    'triggerOn': 'mousemove'
                },
                'series': [{
                    'type': 'sankey',
                    'data': data.get('nodes', []),
                    'links': data.get('links', []),
                    'emphasis': {
                        'focus': 'adjacency'
                    },
                    'lineStyle': {
                        'color': 'gradient',
                        'curveness': options.get('curveness', 0.5)
                    },
                    'label': {
                        'position': options.get('labelPosition', 'right')
                    }
                }]
            }
            
            # Apply custom options
            for key, value in options.items():
                if key not in ['curveness', 'labelPosition']:
                    sankey_options[key] = value
            
            return json.dumps(sankey_options)
        except Exception as e:
            print(f"Error generating options for chart type 'sankey': {e}")
            return json.dumps({
                "title": {"text": title},
                "series": [{
                    "type": "sankey",
                    "data": [{"name": "Node 1"}, {"name": "Node 2"}],
                    "links": [{"source": "Node 1", "target": "Node 2", "value": 10}]
                }]
            })
            
    def _generate_table_html(self, data: List[Dict], title: str, width: int, height: int, options: Dict) -> str:
        """Generate HTML for a table visualization."""
        try:
            if not data or not isinstance(data, list):
                return '<div class="error">No valid data for table.</div>'
            
            # Extract column headers from the first data item
            columns = []
            if data and isinstance(data[0], dict):
                columns = list(data[0].keys())
            
            # Build table HTML
            table_html = '<div class="table-responsive">\n<table class="data-table">\n'
            
            # Add header row
            table_html += '<thead>\n<tr>\n'
            for col in columns:
                table_html += f'<th>{col}</th>\n'
            table_html += '</tr>\n</thead>\n'
            
            # Add data rows
            table_html += '<tbody>\n'
            for item in data:
                table_html += '<tr>\n'
                for col in columns:
                    cell_value = item.get(col, '')
                    table_html += f'<td>{cell_value}</td>\n'
                table_html += '</tr>\n'
            table_html += '</tbody>\n'
            
            table_html += '</table>\n</div>'
            return table_html
        except Exception as e:
            print(f"Error generating table HTML: {str(e)}")
            return f'<div class="error">Error generating table: {str(e)}</div>'
            
    def _get_table_css(self, options: Dict) -> str:
        """Get CSS for table styling."""
        table_css = """
        .table-responsive {
            overflow-x: auto;
            max-width: 100%;
            border-radius: var(--border-radius);
            box-shadow: var(--shadow);
            margin-bottom: 2rem;
        }
        .data-table {
            width: 100%;
            border-collapse: collapse;
            margin: 0;
            font-size: 0.9rem;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        .data-table thead tr {
            background-color: var(--primary-color);
            color: white;
            text-align: left;
            font-weight: 600;
        }
        .data-table th,
        .data-table td {
            padding: 1rem;
            border: 1px solid #eee;
        }
        .data-table th {
            position: relative;
        }
        .data-table th:after {
            content: '';
            position: absolute;
            left: 0;
            bottom: 0;
            width: 100%;
            height: 2px;
            background-color: rgba(255, 255, 255, 0.3);
        }
        .data-table tbody tr {
            border-bottom: 1px solid #eee;
            transition: var(--transition);
        }
        .data-table tbody tr:nth-of-type(even) {
            background-color: rgba(0, 0, 0, 0.02);
        }
        .data-table tbody tr:last-of-type {
            border-bottom: 2px solid var(--primary-color);
        }
        .data-table tbody tr:hover {
            background-color: rgba(67, 97, 238, 0.05);
            transform: translateY(-2px);
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
        }
        """
        
        # Apply custom styling from options
        border_color = options.get('borderColor', '#eee')
        header_bg = options.get('headerBackground', 'var(--primary-color)')
        row_hover = options.get('rowHoverColor', 'rgba(67, 97, 238, 0.05)')
        alternating_row = options.get('alternatingRowColor', 'rgba(0, 0, 0, 0.02)')
        
        # Replace default colors with custom colors
        table_css = table_css.replace('#eee', border_color)
        table_css = table_css.replace('var(--primary-color)', header_bg)
        table_css = table_css.replace('rgba(67, 97, 238, 0.05)', row_hover)
        table_css = table_css.replace('rgba(0, 0, 0, 0.02)', alternating_row)
        
        return table_css
    
    def _get_default_theme_css(self) -> str:
        """Get CSS for the default theme."""
        return """
            body {
                font-family: 'Arial', sans-serif;
                margin: 0;
                padding: 0;
                background-color: #f7f7f7;
                color: #333;
            }
            .report-container {
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
                background-color: white;
                box-shadow: 0 0 10px rgba(0,0,0,0.1);
            }
            header {
                background-color: #4a90e2;
                color: white;
                padding: 20px;
                margin-bottom: 20px;
                text-align: center;
            }
            h1 {
                margin: 0;
            }
            h2 {
                color: #4a90e2;
                border-bottom: 1px solid #eee;
                padding-bottom: 10px;
            }
            .content-section {
                margin-bottom: 30px;
                line-height: 1.6;
            }
            .visualization-section {
                margin-bottom: 40px;
                background-color: white;
                padding: 20px;
                border-radius: 5px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            }
            .chart-container {
                margin: 0 auto;
            }
            footer {
                text-align: center;
                margin-top: 50px;
                padding: 20px;
                color: #888;
                border-top: 1px solid #eee;
            }
            table {
                width: 100%;
                border-collapse: collapse;
            }
            th, td {
                border: 1px solid #ddd;
                padding: 8px;
                text-align: left;
            }
            th {
                background-color: #f2f2f2;
            }
            tr:nth-child(even) {
                background-color: #f9f9f9;
            }
            tr:hover {
                background-color: #f5f5f5;
            }
            .error {
                color: #d32f2f;
                padding: 20px;
                background-color: #ffeeee;
                border: 1px solid #ffcccc;
                border-radius: 4px;
            }
        """
        
    def _get_dark_theme_css(self) -> str:
        """Get CSS for the dark theme."""
        return """
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                margin: 0;
                padding: 0;
                background-color: #121212;
                color: #e0e0e0;
            }
            .report-container {
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
                background-color: #1e1e1e;
                box-shadow: 0 0 10px rgba(0,0,0,0.5);
            }
            header {
                background-color: #2d2d2d;
                color: #ffffff;
                padding: 20px;
                margin-bottom: 20px;
                text-align: center;
            }
            h1 {
                margin: 0;
            }
            h2 {
                color: #4a90e2;
                border-bottom: 1px solid #333;
                padding-bottom: 10px;
            }
            .content-section {
                margin-bottom: 30px;
                line-height: 1.6;
            }
            .visualization-section {
                margin-bottom: 40px;
                background-color: #2d2d2d;
                padding: 20px;
                border-radius: 5px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.3);
            }
            .chart-container {
                margin: 0 auto;
                background-color: #2d2d2d;
            }
            footer {
                text-align: center;
                margin-top: 50px;
                padding: 20px;
                color: #888;
                border-top: 1px solid #333;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                color: #e0e0e0;
            }
            th, td {
                border: 1px solid #444;
                padding: 8px;
                text-align: left;
            }
            th {
                background-color: #333;
            }
            tr:nth-child(even) {
                background-color: #2a2a2a;
            }
            tr:hover {
                background-color: #3a3a3a;
            }
            .error {
                color: #ff6b6b;
                padding: 20px;
                background-color: #3a1c1c;
                border: 1px solid #582626;
                border-radius: 4px;
            }
        """
        
    def _get_professional_theme_css(self) -> str:
        """Get CSS for the professional theme."""
        return """
            :root {
                --primary-color: #4361ee;
                --secondary-color: #3f37c9;
                --accent-color: #4895ef;
                --text-color: #2b2d42;
                --heading-color: #1a365d;
                --bg-color: #f8f9fa;
                --card-bg: #ffffff;
                --border-radius: 8px;
                --shadow: 0 4px 6px rgba(0, 0, 0, 0.1), 0 1px 3px rgba(0, 0, 0, 0.08);
                --transition: all 0.3s ease;
            }
            
            body {
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                margin: 0;
                padding: 0;
                background-color: var(--bg-color);
                color: var(--text-color);
                line-height: 1.6;
            }
            
            .report-container {
                max-width: 1200px;
                margin: 0 auto;
                padding: 2rem;
                background-color: var(--card-bg);
                box-shadow: var(--shadow);
                border-radius: var(--border-radius);
            }
            
            header {
                background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%);
                color: white;
                padding: 3rem 2rem;
                margin-bottom: 2rem;
                text-align: center;
                border-radius: var(--border-radius);
                box-shadow: var(--shadow);
            }
            
            h1 {
                margin: 0;
                font-weight: 700;
                letter-spacing: 0.5px;
                font-size: 2.5rem;
            }
            
            h2 {
                color: var(--heading-color);
                border-bottom: 2px solid rgba(0, 0, 0, 0.05);
                padding-bottom: 0.75rem;
                margin-top: 2.5rem;
                margin-bottom: 1.5rem;
                font-weight: 600;
            }
            
            .content-section {
                margin-bottom: 2.5rem;
                font-size: 1rem;
                background-color: var(--card-bg);
                padding: 1.5rem;
                border-radius: var(--border-radius);
                box-shadow: var(--shadow);
                transition: var(--transition);
            }
            
            .content-section:hover {
                box-shadow: 0 10px 20px rgba(0, 0, 0, 0.12), 0 4px 8px rgba(0, 0, 0, 0.06);
                transform: translateY(-5px);
            }
            
            .visualization-section {
                margin-bottom: 3rem;
                background-color: var(--card-bg);
                padding: 1.5rem;
                border-radius: var(--border-radius);
                box-shadow: var(--shadow);
                transition: var(--transition);
            }
            
            .visualization-section:hover {
                box-shadow: 0 10px 20px rgba(0, 0, 0, 0.12), 0 4px 8px rgba(0, 0, 0, 0.06);
                transform: translateY(-5px);
            }
            
            .visualization-section h2 {
                text-align: center;
                color: var(--heading-color);
                margin-top: 0;
                margin-bottom: 1.5rem;
                font-size: 1.5rem;
                border-bottom: none;
            }
            
            .chart-container {
                margin: 0 auto;
                height: 400px;
                background-color: var(--card-bg);
                border-radius: var(--border-radius);
                overflow: hidden;
            }
            
            footer {
                text-align: center;
                margin-top: 3rem;
                padding: 1.5rem;
                color: #777;
                border-top: 1px solid rgba(0, 0, 0, 0.05);
                font-size: 0.9rem;
            }
            
            table {
                width: 100%;
                border-collapse: collapse;
                margin: 1.5rem 0;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
                border-radius: var(--border-radius);
                overflow: hidden;
            }
            
            th, td {
                border: 1px solid #e7e7e7;
                padding: 0.75rem 1rem;
                text-align: left;
            }
            
            th {
                background-color: var(--primary-color);
                font-weight: 600;
                color: white;
                position: relative;
            }
            
            th:after {
                content: '';
                position: absolute;
                left: 0;
                bottom: 0;
                width: 100%;
                height: 2px;
                background-color: rgba(255, 255, 255, 0.3);
            }
            
            tr:nth-child(even) {
                background-color: rgba(0, 0, 0, 0.02);
            }
            
            tr:hover {
                background-color: rgba(67, 97, 238, 0.05);
            }
            
            .error {
                color: #d32f2f;
                padding: 1.5rem;
                background-color: #fdecea;
                border: 1px solid #f5c6cb;
                border-radius: var(--border-radius);
                margin: 1.5rem 0;
            }
            
            a {
                color: var(--primary-color);
                text-decoration: none;
                transition: var(--transition);
            }
            
            a:hover {
                color: var(--secondary-color);
                text-decoration: underline;
            }
            
            /* Responsive adjustments */
            @media (max-width: 768px) {
                .report-container {
                    padding: 1rem;
                }
                
                header {
                    padding: 2rem 1rem;
                }
                
                h1 {
                    font-size: 2rem;
                }
                
                .visualization-section, .content-section {
                    padding: 1rem;
                }
                
                .chart-container {
                    height: 300px;
                }
            }
        """
    
    def _get_theme_css(self, theme: str) -> str:
        """Get CSS for the specified theme."""
        theme_func = self.themes.get(theme.lower(), self.themes['default'])
        return theme_func() 

    def _generate_report_template(self, title: str, content: str, visualizations: List[Dict], theme: str) -> str:
        """Generate HTML template for a report."""
        try:
            # Process content to identify logical sections
            content_sections = self._process_content_sections(content)
            
            # Get CSS for the theme
            theme_css = self._get_theme_css(theme)
            
            # Build HTML start
            html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        {theme_css}
        /* Additional styles for visualizations */
        .chart-container {{
            min-height: 400px;
            width: 100%;
            margin: 30px auto;
            border: 1px solid #eaeaea;
            border-radius: 5px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }}
        .visualization-section {{
            margin-bottom: 40px;
            padding: 20px;
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 15px rgba(0,0,0,0.08);
        }}
        .visualization-section h2 {{
            text-align: center;
            color: #1a365d;
            margin-top: 0;
            margin-bottom: 20px;
            font-size: 1.5rem;
        }}
        .content-section {{
            line-height: 1.8;
            font-size: 16px;
            margin-bottom: 30px;
            padding: 20px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 15px rgba(0,0,0,0.05);
        }}
        header {{
            padding: 30px;
            margin-bottom: 40px;
        }}
        .data-collection-required {{
            background-color: #f9f9f9;
            border-radius: 5px;
            position: relative;
        }}
        .chart-error {{
            color: #d32f2f;
            padding: 20px;
            background-color: #ffeeee;
            border: 1px solid #ffcccc;
            border-radius: 4px;
        }}
    </style>
</head>
<body>
    <div class="report-container">
        <header>
            <h1>{title}</h1>
        </header>'''
            
            # Distribute visualizations across content sections
            html += self._distribute_visualizations(content_sections, visualizations)
            
            # Complete the HTML
            html += '''
    </div>
    
    <script>
        // Initialize charts when DOM is loaded
        document.addEventListener('DOMContentLoaded', function() {
            // Initialize all charts
            var charts = document.querySelectorAll('[id^="chart-"]');
            charts.forEach(function(chartContainer) {
                var chartId = chartContainer.id;
                var chartOptions = chartContainer.getAttribute('data-options');
                if (chartOptions) {
                    var myChart = echarts.init(chartContainer);
                    myChart.setOption(JSON.parse(chartOptions));
                }
            });
            
            // Force redraw after a delay
            setTimeout(function() {
                window.dispatchEvent(new Event('resize'));
            }, 100);
        });
    </script>
</body>
</html>'''
            
            return html
        except Exception as e:
            print(f"Error generating report template: {str(e)}")
            return f'''<!DOCTYPE html>
<html>
<head>
    <title>Error: {title}</title>
</head>
<body>
    <h1>Error Generating Report</h1>
    <p>An error occurred: {str(e)}</p>
</body>
</html>'''
            
    def _process_content_sections(self, content: str) -> List[Dict]:
        """Process content to identify logical sections."""
        content_sections = []
        
        if not content:
            return content_sections
            
        # Convert Markdown to HTML if it doesn't look like HTML
        content_html = content
        try:
            if "<" not in content[:100] and ">" not in content[:100]:
                try:
                    import markdown
                    # Use the 'extra' extension for better markdown support
                    content_html = markdown.markdown(content, extensions=['extra', 'nl2br'])
                except ImportError:
                    # Better markdown fallback if the module is not available
                    # Process headers
                    processed_content = re.sub(r'^\s*#{1}\s+(.+?)$', r'<h1>\1</h1>', content, flags=re.MULTILINE)
                    processed_content = re.sub(r'^\s*#{2}\s+(.+?)$', r'<h2>\1</h2>', processed_content, flags=re.MULTILINE)
                    processed_content = re.sub(r'^\s*#{3}\s+(.+?)$', r'<h3>\1</h3>', processed_content, flags=re.MULTILINE)
                    processed_content = re.sub(r'^\s*#{4}\s+(.+?)$', r'<h4>\1</h4>', processed_content, flags=re.MULTILINE)
                    processed_content = re.sub(r'^\s*#{5}\s+(.+?)$', r'<h5>\1</h5>', processed_content, flags=re.MULTILINE)
                    processed_content = re.sub(r'^\s*#{6}\s+(.+?)$', r'<h6>\1</h6>', processed_content, flags=re.MULTILINE)
                    
                    # Process bold and italic
                    processed_content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', processed_content)
                    processed_content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', processed_content)
                    
                    # Process lists
                    processed_content = re.sub(r'^\s*-\s+(.+?)$', r'<li>\1</li>', processed_content, flags=re.MULTILINE)
                    processed_content = re.sub(r'((?:<li>.*?</li>\s*)+)', r'<ul>\1</ul>', processed_content, flags=re.DOTALL)
                    
                    # Process paragraphs and line breaks
                    processed_content = re.sub(r'\n\s*\n', '</p><p>', processed_content)
                    processed_content = re.sub(r'\n', '<br>', processed_content)
                    
                    # Wrap in paragraph tags if not already wrapped
                    if not processed_content.startswith('<'):
                        processed_content = f"<p>{processed_content}</p>"
                    
                    content_html = processed_content
        except Exception as e:
            print(f"Error converting markdown to HTML: {str(e)}")
            # Fallback to simple HTML wrapping
            content_html = f"<p>{content}</p>"
            
        # Split content by headers to identify logical sections
        section_pattern = r'(<h[1-6][^>]*>.*?</h[1-6]>)'
        sections = re.split(section_pattern, content_html, flags=re.DOTALL)
        
        # Group header with its content
        i = 0
        while i < len(sections):
            if i + 1 < len(sections) and re.match(r'<h[1-6][^>]*>', sections[i], re.DOTALL):
                content_sections.append({
                    'header': sections[i], 
                    'content': sections[i+1] if i+1 < len(sections) else ''
                })
                i += 2
            else:
                if sections[i].strip():  # Only add non-empty sections
                    content_sections.append({'content': sections[i]})
                i += 1
        
        # If no sections were found, treat the entire content as one section
        if not content_sections and content_html:
            content_sections.append({'content': content_html})
            
        return content_sections
        
    def _distribute_visualizations(self, content_sections: List[Dict], visualizations: List[Dict]) -> str:
        """Distribute visualizations across content sections and return HTML."""
        html = ""
        
        if not content_sections:
            # If no content sections, just add all visualizations
            html += '<div class="content-section">'
            for i, viz in enumerate(visualizations):
                html += self._generate_visualization_html(viz, i)
            html += '</div>'
            return html
        
        # Create a copy of visualizations we can modify
        remaining_visualizations = visualizations.copy()
        
        # Process each content section
        for i, section in enumerate(content_sections):
            section_content = section.get('content', '')
            section_header = section.get('header', '')
            
            # Start the section HTML
            section_html = f'''
    <div class="content-section">
        {section_header}'''
            
            # Process content, looking for image references to replace with visualizations
            # Match patterns like ![title](chart_name.html) or similar references
            image_refs = re.findall(r'!\[(.*?)\]\((.*?)\)', section_content)
            
            # Replace any matching images with their visualizations
            for img_title, img_path in image_refs:
                viz_title_lower = img_title.lower() if img_title else ''
                viz_path_lower = img_path.lower() if img_path else ''
                
                # Look for a matching visualization
                matched_index = -1
                for j, viz in enumerate(remaining_visualizations):
                    viz_title = viz.get('title', '').lower()
                    viz_type = viz.get('chart_type', '').lower()
                    
                    # Match by title or type
                    if ((viz_title and viz_title in viz_title_lower) or 
                        (viz_type and viz_type in viz_title_lower) or
                        (viz_title and viz_title in viz_path_lower) or
                        (viz_type and viz_type in viz_path_lower)):
                        matched_index = j
                        break
                
                # If we found a match, replace the reference with the visualization
                if matched_index >= 0:
                    viz = remaining_visualizations.pop(matched_index)
                    viz_index = len(visualizations) - len(remaining_visualizations) - 1
                    # Replace the image reference with empty string (we'll add viz after content)
                    section_content = section_content.replace(f'![{img_title}]({img_path})', '')
            
            # Add the processed content
            section_html += section_content
            
            # Add placed visualizations after the content
            for img_title, img_path in image_refs:
                viz_title_lower = img_title.lower() if img_title else ''
                viz_path_lower = img_path.lower() if img_path else ''
                
                # For any matched visualization, add its HTML
                matched_index = -1
                for j, viz in enumerate(visualizations):
                    viz_title = viz.get('title', '').lower()
                    viz_type = viz.get('chart_type', '').lower()
                    
                    if ((viz_title and viz_title in viz_title_lower) or 
                        (viz_type and viz_type in viz_title_lower) or
                        (viz_title and viz_title in viz_path_lower) or
                        (viz_type and viz_type in viz_path_lower)):
                        if viz not in remaining_visualizations:  # Only if we removed it earlier
                            viz_index = visualizations.index(viz)
                            section_html += self._generate_visualization_html(viz, viz_index)
                            break
            
            # Close the section
            section_html += '</div>'
            html += section_html
        
        # Add any remaining visualizations at the end
        if remaining_visualizations:
            html += '<div class="content-section">'
            for i, viz in enumerate(remaining_visualizations):
                viz_index = visualizations.index(viz)
                html += self._generate_visualization_html(viz, viz_index)
            html += '</div>'
        
        return html
        
    def _generate_visualization_html(self, viz: Dict, index: int) -> str:
        """Generate HTML for a visualization in the report."""
        chart_div_id = f"chart-{index+1}"
        chart_type = viz.get('chart_type', 'bar')
        chart_title = viz.get('title', f'Chart {index+1}')
        chart_data = viz.get('data', [])
        chart_options = viz.get('options', {})
        
        # Check if data collection is required
        if self._requires_data_collection(chart_data):
            return f'''
<div class="visualization-section">
    <h2>{chart_title}</h2>
    <div id="{chart_div_id}" class="data-collection-required" style="height: 400px; border: 2px dashed #ccc; margin: 20px auto; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; padding: 20px;">
        <h3 style="color: #555; margin-bottom: 15px;">Data Collection Required</h3>
        <p style="color: #777; max-width: 80%;">
            This {chart_type} chart requires actual data to be collected and analyzed.
            <br><br>
            Please gather relevant data from your analysis to create this visualization.
        </p>
    </div>
</div>'''
        
        # Generate chart options
        generator = self.chart_generators.get(chart_type, self.chart_generators['bar'])
        chart_options_str = generator(chart_data, chart_title, chart_options)
        
        # For tables, generate differently
        if chart_type == 'table':
            table_html = self._generate_table_html(chart_data, chart_title, 800, 400, chart_options)
            return f'''
<div class="visualization-section">
    <h2>{chart_title}</h2>
    {table_html}
</div>'''
        
        # For charts using ECharts
        return f'''
<div class="visualization-section">
    <h2>{chart_title}</h2>
    <div id="{chart_div_id}" class="chart-container" style="height: 400px;" data-options='{chart_options_str}'></div>
</div>'''
        
    def _deep_update(self, target_dict: Dict, source_dict: Dict) -> None:
        """Deep update target dict with source dict."""
        for key, value in source_dict.items():
            if isinstance(value, dict) and key in target_dict and isinstance(target_dict[key], dict):
                self._deep_update(target_dict[key], value)
            else:
                target_dict[key] = value
                
    def _generate_presentation_template(self, title: str, content: str, visualizations: List[Dict], theme: str) -> str:
        """Generate HTML template for a presentation-style report with navigation controls."""
        try:
            # Process content to identify logical sections for slides
            content_sections = self._process_content_sections(content)
            
            # Get CSS for the theme and add presentation-specific CSS
            theme_css = self._get_theme_css(theme)
            presentation_css = self._get_presentation_css()
            
            # Build HTML start
            html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        {theme_css}
        {presentation_css}
    </style>
</head>
<body>
    <div class="presentation-container">
        <!-- Title Slide -->
        <section class="slide active" id="slide-0">
            <div class="slide-content title-slide">
                <h1>{title}</h1>
            </div>
        </section>'''
            
            # Create slides from content sections and visualizations
            slides_html = self._create_presentation_slides(content_sections, visualizations)
            html += slides_html
            
            # Add navigation controls
            html += '''
        <div class="slide-controls">
            <button id="prev-slide" class="nav-button">&lt; Previous</button>
            <span id="slide-counter">1 / 1</span>
            <button id="next-slide" class="nav-button">Next &gt;</button>
        </div>
    </div>
    
    <script>
    // Presentation navigation functionality
    document.addEventListener('DOMContentLoaded', function() {
        // Initialize all charts
        var charts = document.querySelectorAll('[id^="chart-"]');
        charts.forEach(function(chartContainer) {
            var chartId = chartContainer.id;
            var chartOptions = chartContainer.getAttribute('data-options');
            if (chartOptions) {
                var myChart = echarts.init(chartContainer);
                myChart.setOption(JSON.parse(chartOptions));
            }
        });
        
        // Set up slide navigation
        var slides = document.querySelectorAll('.slide');
        var currentSlide = 0;
        var slideCounter = document.getElementById('slide-counter');
        var prevButton = document.getElementById('prev-slide');
        var nextButton = document.getElementById('next-slide');
        
        // Update slide counter display
        function updateCounter() {
            slideCounter.textContent = (currentSlide + 1) + ' / ' + slides.length;
        }
        
        // Show current slide and hide others
        function showSlide(index) {
            slides.forEach(function(slide, i) {
                if (i === index) {
                    slide.classList.add('active');
                } else {
                    slide.classList.remove('active');
                }
            });
            
            // Disable prev button on first slide
            prevButton.disabled = index === 0;
            // Disable next button on last slide
            nextButton.disabled = index === slides.length - 1;
            
            // Trigger resize event to redraw charts correctly
            setTimeout(function() {
                window.dispatchEvent(new Event('resize'));
            }, 100);
        }
        
        // Initialize navigation
        updateCounter();
        showSlide(currentSlide);
        
        // Previous slide button
        prevButton.addEventListener('click', function() {
            if (currentSlide > 0) {
                currentSlide--;
                showSlide(currentSlide);
                updateCounter();
            }
        });
        
        // Next slide button
        nextButton.addEventListener('click', function() {
            if (currentSlide < slides.length - 1) {
                currentSlide++;
                showSlide(currentSlide);
                updateCounter();
            }
        });
        
        // Keyboard navigation
        document.addEventListener('keydown', function(e) {
            if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                if (currentSlide > 0) {
                    currentSlide--;
                    showSlide(currentSlide);
                    updateCounter();
                }
            } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === ' ') {
                if (currentSlide < slides.length - 1) {
                    currentSlide++;
                    showSlide(currentSlide);
                    updateCounter();
                }
            }
        });
    });
    </script>
</body>
</html>'''
            
            return html
        except Exception as e:
            print(f"Error generating presentation template: {str(e)}")
            return f'''<!DOCTYPE html>
<html>
<head>
    <title>Error: {title}</title>
</head>
<body>
    <h1>Error Generating Presentation</h1>
    <p>An error occurred: {str(e)}</p>
</body>
</html>'''
    
    def _get_presentation_css(self) -> str:
        """Get CSS for presentation mode."""
        return """
        /* Presentation-specific CSS */
        body, html {
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
            overflow: hidden;
        }
        .presentation-container {
            position: relative;
            width: 100%;
            height: 100vh;
            overflow: hidden;
        }
        .slide {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            display: none;
            opacity: 0;
            transition: opacity 0.6s ease;
            padding: 40px;
            box-sizing: border-box;
            overflow-y: auto;
        }
        .slide.active {
            display: block;
            opacity: 1;
            z-index: 10;
        }
        .slide-content {
            max-width: 90%;
            margin: 0 auto;
            height: 100%;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        .title-slide {
            text-align: center;
            justify-content: center;
            align-items: center;
        }
        .title-slide h1 {
            font-size: 3rem;
            margin-bottom: 2rem;
        }
        .slide-controls {
            position: fixed;
            bottom: 20px;
            width: 100%;
            display: flex;
            justify-content: center;
            z-index: 100;
        }
        .nav-button {
            background-color: rgba(0, 0, 0, 0.6);
            color: white;
            border: none;
            padding: 10px 20px;
            margin: 0 10px;
            border-radius: 5px;
            cursor: pointer;
            transition: background-color 0.3s;
        }
        .nav-button:hover {
            background-color: rgba(0, 0, 0, 0.8);
        }
        .nav-button:disabled {
            background-color: rgba(0, 0, 0, 0.3);
            cursor: not-allowed;
        }
        #slide-counter {
            background-color: rgba(0, 0, 0, 0.6);
            color: white;
            padding: 10px 15px;
            border-radius: 5px;
            font-size: 14px;
        }
        .chart-container {
            width: 100% !important;
            height: 70% !important;
            margin: 20px auto;
        }
        .visualization-section {
            height: 90%;
            margin-bottom: 0;
            display: flex;
            flex-direction: column;
        }
        .visualization-section h2 {
            margin-top: 0;
        }
        """
    
    def _create_presentation_slides(self, content_sections: List[Dict], visualizations: List[Dict]) -> str:
        """Create HTML for presentation slides from content sections and visualizations."""
        slides_html = ""
        slide_count = 1
        
        # Create a copy of visualizations we can modify
        remaining_visualizations = visualizations.copy()
        
        # Process each content section as a slide
        for i, section in enumerate(content_sections):
            section_content = section.get('content', '')
            section_header = section.get('header', '')
            
            # Create slide for this section
            slides_html += f'''
        <section class="slide" id="slide-{slide_count}">
            <div class="slide-content">
                {section_header}
                {section_content}
            </div>
        </section>'''
            slide_count += 1
            
            # Look for image references to place as separate slides
            image_refs = re.findall(r'!\[(.*?)\]\((.*?)\)', section_content)
            
            # For each image reference, try to match a visualization and create a slide
            for img_title, img_path in image_refs:
                viz_title_lower = img_title.lower() if img_title else ''
                viz_path_lower = img_path.lower() if img_path else ''
                
                # Look for a matching visualization
                matched_index = -1
                for j, viz in enumerate(remaining_visualizations):
                    viz_title = viz.get('title', '').lower()
                    viz_type = viz.get('chart_type', '').lower()
                    
                    # Match by title or type
                    if ((viz_title and viz_title in viz_title_lower) or 
                        (viz_type and viz_type in viz_title_lower) or
                        (viz_title and viz_title in viz_path_lower) or
                        (viz_type and viz_type in viz_path_lower)):
                        matched_index = j
                        break
                
                # If we found a match, create a slide for this visualization
                if matched_index >= 0:
                    viz = remaining_visualizations.pop(matched_index)
                    viz_html = self._generate_visualization_html(viz, j)
                    slides_html += f'''
        <section class="slide" id="slide-{slide_count}">
            <div class="slide-content">
                {viz_html}
            </div>
        </section>'''
                    slide_count += 1
        
        # Add remaining visualizations as separate slides
        for i, viz in enumerate(remaining_visualizations):
            viz_html = self._generate_visualization_html(viz, visualizations.index(viz))
            slides_html += f'''
        <section class="slide" id="slide-{slide_count}">
            <div class="slide-content">
                {viz_html}
            </div>
        </section>'''
            slide_count += 1
        
        return slides_html
                
if __name__ == '__main__':
    # Set up workspace path
    workspace = WORKSPACE_PATH
    os.environ['WORKSPACE_PATH'] = workspace
    
    # Initialize toolkit
    toolkit = HTMLVisualizationToolkit()
    
    # Test with bar chart
    bar_data = [
        {"x": "Category A", "y": 120},
        {"x": "Category B", "y": 200},
        {"x": "Category C", "y": 150},
        {"x": "Category D", "y": 80},
        {"x": "Category E", "y": 70}
    ]
    
    print("Testing bar chart:")
    print(toolkit.create_visualization(
        chart_type='bar',
        data=json.dumps(bar_data),
        title='Sample Bar Chart',
        file_path='sample_bar_chart.html'
    ))
    
    # Test with pie chart
    pie_data = [
        {"name": "Category A", "value": 120},
        {"name": "Category B", "value": 200},
        {"name": "Category C", "value": 150},
        {"name": "Category D", "value": 80},
        {"name": "Category E", "value": 70}
    ]
    
    print("Testing pie chart:")
    print(toolkit.create_visualization(
        chart_type='pie',
        data=json.dumps(pie_data),
        title='Sample Pie Chart',
        options=json.dumps({"radius": "70%"}),
        file_path='sample_pie_chart.html'
    )) 