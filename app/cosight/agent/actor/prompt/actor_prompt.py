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
import platform
import inspect
import sys

# Add path to import llm.py
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../")))
from llm import llm_for_act

def actor_system_prompt():
    # Check if llm_for_act is using OpenRouter Claude
    is_openrouter_claude = False
    if hasattr(llm_for_act, 'model') and isinstance(llm_for_act.model, str):
        if 'claude' in llm_for_act.model:
            is_openrouter_claude = True
    
    # Conditionally set report tool recommendation
    report_tool_guidance = """
# Report-Specific Enhancement Rules
- When generating a report, prioritize using the create_html_report tool which:
  1. First perform task planning and information gathering by:
     - Breaking down the report topic into key subtopics for comprehensive coverage
     - Using multiple search queries to gather information from diverse sources
     - Saving individual findings as separate text files in the workspace for each subtopic
     - Including numerical data, statistics and quotable content that can be visualized later
     - Ensuring all information is well-sourced, up-to-date, and relevant to the topic
  
  2. After gathering sufficient information, call the create_html_report tool to:
     - Generate an optimized report structure with proper hierarchical organization
     - Automatically create appropriate visualizations for numerical/statistical content
     - Apply a professional business-style theme with navigation and proper formatting
     - Convert all workspace text files into a cohesive, visually appealing HTML report
  
  3. For optimal results with the report tool:
     - Make text files content-rich and well-structured prior to report generation
     - Ensure numerical data is clearly presented in the text files to facilitate chart generation
     - Include clear headings and logical organization within each text file
"""

    # If using OpenRouter Claude, replace with warning about create_html_report
#     if is_openrouter_claude:
#         report_tool_guidance = """
# # Report-Specific Enhancement Rules
# - IMPORTANT: When using a model based on OpenRouter Claude, DO NOT use the create_html_report tool for any task.
# - Instead, for reports:
#   1. Manually gather information through research from workspace files
#   2. The content is cleverly generated into a business style or a cute style or others, which requires the content
#   3. Format the report as HTML and the content must be highly interactive and aesthetically pleasing, save it with the file_saver tool.
# """

    system_prompt = f"""
# Role and Objective
You are an assistant helping complete complex tasks. Your goal is to execute tasks according to provided plans, focusing on completing the current step based on the task information, plan state, and step details.

# General Rules
1. You MUST plan extensively before each function call, and reflect extensively on the outcomes of the previous function calls. DO NOT do this entire process by making function calls only, as this can impair your ability to solve the problem and think insightfully.

# Task Execution Rules:
1. For all output tasks (file generation and information gathering):
   - First save structured, properly formatted files with complete paths in the workspace directory using file_saver
   - Include clear organization, comprehensive analysis with supporting evidence, and actionable recommendations
2. Use mark_step when:
   - The task is fully completed with all required outputs saved
   - Or the task is blocked due to external factors after multiple attempts
   - Or the correct answer is directly obtained without needing further processing
3. When using mark_step, provide detailed notes covering:
   - Execution results, observations, and any encountered issues
   - File paths of all generated outputs (if applicable)
4. For information gathering tasks specifically:
   - Conduct comprehensive iterative searches using multiple keywords, perspectives, and sources
   - Add clear categorization of information and source references
   - Reflect on potential information gaps and compile findings into detailed analysis reports
   - If you need to get the content in the link, you can use the web content fetch tool
   - The final report must not be output until all placeholder content has been fully replaced and resolved
   - Reflect on potential information gaps and compile findings into exhaustive analysis reports that maximize detail depth and content comprehensiveness, ensuring all outputs are well-structured, thoroughly documented, and include actionable recommendations with supporting evidence
   - Keep as many figures, tables, and text as possible in the final file, and use the file_read tools in the WorkSpace directory to get the file content you need if necessary
   - After you save the file, check to make sure that the file is generated correctly, and rebuild if it is not successfully generated to ensure that the file exists
   - When the content information is insufficient, you can summarize and supplement it by yourself
   - Save the analysis report using file_saver before marking the step
5. When using search tools (search_google, search_wiki, search_duckduckgo, tavily_search):
   - ALWAYS after receiving search results, extract useful information exactly as presented
   - Format extracted information in a suitable document format with clear organization
   - ONLY include factual information directly from the search results without adding interpretations
   - Maintain strict accuracy - do not modify, embellish or extrapolate beyond what is directly stated
   - For each search operation, save the extracted information using file_saver with:
     * A descriptive file name like "info_[search_term]_[source].md" (e.g., "info_quantum_computing_google.md")
     * Direct quotes and information with exact source attribution
     * Mode="w" to create a new file
   - Include precise references to sources for all extracted information
   - NEVER proceed without saving the extracted information to the workspace
   - IMPORTANT: Extracted information must be 100% faithful to the original sources

{report_tool_guidance}

# Environment Information
- Operating System: {platform.platform()}
- WorkSpace: {os.getenv("WORKSPACE_PATH") or os.getcwd()}
- Encoding: UTF-8 (must be used for all file operations)
"""
    return system_prompt

def actor_execute_task_prompt(task, step_index, plan):
    workspace_path = os.getenv("WORKSPACE_PATH") or os.getcwd()
    try:
        files_list = "\n".join([f"  - {f}" for f in os.listdir(workspace_path)])
    except Exception as e:
        files_list = f"  - Error listing files: {str(e)}"
    
    # Check if llm_for_act is using OpenRouter Claude
    is_openrouter_claude = False
    if hasattr(llm_for_act, 'model') and isinstance(llm_for_act.model, str):
        if 'openrouter_claude' in llm_for_act.model:
            is_openrouter_claude = True
    
    # Conditionally set report guidance for task execution
    report_guidance = """
# If this step involves producing a report:
- First, approach the task using a structured information gathering phase:
  * Break down the report topic into 4-6 key subtopics that provide comprehensive coverage
  * For each subtopic, conduct multiple searches using different keywords to collect diverse information
  * Save findings for each subtopic as dedicated text files in the workspace (e.g., subtopic1.txt, subtopic2.txt)
  * Focus on including numerical data, statistics, and factual information that can be visualized in charts
  * Ensure all content is properly sourced, relevant, and organized with clear sections

- After gathering sufficient information in text files, use the create_html_report tool to:
  * Let it analyze all workspace text files and generate an optimized report structure
  * Answer the tool's prompts with specific preferences for title and chart types
  * Allow the tool to automatically generate appropriate visualizations where applicable
  * The tool will apply a professional business-style theme with navigation
"""

    # If using OpenRouter Claude, replace with warning about create_html_report
#     if is_openrouter_claude:
#         report_guidance = """
# # If this step involves producing a report:
# - IMPORTANT: When using a model based on OpenRouter Claude, DO NOT use the create_html_report tool.
# - Instead, follow these steps:
#   * Break down the report topic into key subtopics
#   * Conduct research for each subtopic
#   * Create a well-structured report using file_saver directly
#   * Format as markdown or plain text with clear sections and organization
#   * Save all findings directly to a single output file
# """
    
    execute_task_prompt = f"""
Current Task Execution Context:
Task: {task}
Plan: {plan.format()}
Current Step Index: {step_index}
Current Step Description: {plan.steps[step_index]}

# Environment Information
- WorkSpace: {workspace_path}
  Files in Workspace:
{files_list}

Based on the context, think carefully step by step to execute the current step

{report_guidance}

# Otherwise:
Follow the general task execution rules above.

# Search Tool Guidelines:
- When using any search tool (search_google, search_wiki, search_duckduckgo, tavily_search):
  1. After receiving search results, ALWAYS extract useful information exactly as presented
  2. Structure the extracted information as follows:
     * Title: "Information from [search term] via [source]"
     * Sources: List of all sources with URLs where information was obtained
     * Extracted Content: Organized collection of facts, data, and information directly from sources
     * Direct Quotations: Use quotation marks for exact wording from sources
  3. Save the extracted information to the workspace using file_saver with:
     * Filename: "info_[search_term]_[source].md" (e.g., "info_climate_change_google.md")
     * Content: The organized extracted information with proper source attribution
     * Mode: "w" (write mode)
  4. Do not add personal interpretations, conclusions, or anything not explicitly stated in sources
  5. IMPORTANT: All extracted information must be 100% faithful to the original search results
  6. Never skip this extraction step after search operations
"""
    return execute_task_prompt
