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

# ========= Copyright 2023-2024 @ CAMEL-AI.org. All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2023-2024 @ CAMEL-AI.org. All Rights Reserved. =========

from typing import Dict, Generator, List, Optional
from arxiv2text import arxiv_to_text
import os

from app.manus.gate.format_gate import format_check


class ArxivToolkit:
    r"""A toolkit for interacting with the arXiv API to search and download
    academic papers.
    """

    def __init__(self, timeout: Optional[float] = None) -> None:
        r"""Initializes the ArxivToolkit and sets up the arXiv client."""
        self.timeout = timeout
        import arxiv
        self.client = arxiv.Client()

    def _get_search_results(
            self,
            query: str,
            paper_ids: Optional[List[str]] = None,
            max_results: Optional[int] = 5,
    ) -> Generator:
        r"""Retrieves search results from the arXiv API based on the provided
        query and optional paper IDs.

        Args:
            query (str): The search query string used to search for papers on
                arXiv.
            paper_ids (List[str], optional): A list of specific arXiv paper
                IDs to search for. (default: :obj: `None`)
            max_results (int, optional): The maximum number of search results
                to retrieve. (default: :obj: `5`)

        Returns:
            Generator: A generator that yields results from the arXiv search
                query, which includes metadata about each paper matching the
                query.
        """
        import arxiv

        paper_ids = paper_ids or []
        search_query = arxiv.Search(
            query=query,
            id_list=paper_ids,
            max_results=max_results,
        )
        return self.client.results(search_query)

    @format_check()
    def search_papers(
            self,
            query: str,
            paper_ids: Optional[List[str]] = None,
            max_results: Optional[int] = 5,
    ) -> List[Dict[str, str]]:
        r"""Searches for academic papers on arXiv using a query string and
        optional paper IDs.

        Args:
            query (str): The search query string.
            paper_ids (List[str], optional): A list of specific arXiv paper
                IDs to search for. (default: :obj: `None`)
            max_results (int, optional): The maximum number of search results
                to return. (default: :obj: `5`)

        Returns:
            List[Dict[str, str]]: A list of dictionaries, each containing
                information about a paper, including title, published date,
                authors, entry ID, summary, and extracted text from the paper.
        """
        try:
            os.environ['HTTP_PROXY'] = "http://proxy.zte.com.cn:80"
            os.environ['HTTPS_PROXY'] = "http://proxy.zte.com.cn:80"
            search_results = self._get_search_results(
                query, paper_ids, 5
            )
            papers_data = []

            for paper in search_results:
                paper_info = {
                    "title": paper.title,
                    "published_date": paper.updated.date().isoformat(),
                    "authors": [author.name for author in paper.authors],
                    "entry_id": paper.entry_id,
                    "summary": paper.summary,
                    "pdf_url": paper.pdf_url,
                }
                # Extract text from the paper
                try:
                    # TODO: Use chunkr instead of atxiv_to_text for better
                    # performance and reliability
                    text = arxiv_to_text(paper_info["pdf_url"])
                except Exception as e:
                    text = f"Failed to extract text content from the PDF at the specified URL. URL: {paper_info.get('pdf_url', 'Unknown')} | Error: {e}"

                paper_info['paper_text'] = text[:2000]

                papers_data.append(paper_info)
            return papers_data
        finally:
            os.environ['HTTP_PROXY'] = "http://proxyhk.zte.com.cn:80"
            os.environ['HTTPS_PROXY'] = "http://proxyhk.zte.com.cn:80"

    @format_check()
    def download_papers(
            self,
            query: str,
            paper_ids: Optional[List[str]] = None,
            max_results: Optional[int] = 5,
            output_dir: Optional[str] = "./",
    ) -> str:
        r"""Downloads PDFs of academic papers from arXiv based on the provided
        query.

        Args:
            query (str): The search query string.
            paper_ids (List[str], optional): A list of specific arXiv paper
                IDs to download. (default: :obj: `None`)
            max_results (int, optional): The maximum number of search results
                to download. (default: :obj: `5`)
            output_dir (str, optional): The directory to save the downloaded
                PDFs. Defaults to the current directory.

        Returns:
            str: Status message indicating success or failure.
        """
        try:
            os.environ['HTTP_PROXY'] = "http://proxy.zte.com.cn:80"
            os.environ['HTTPS_PROXY'] = "http://proxy.zte.com.cn:80"
            print(f"query:{query}, paper_id:{paper_ids},max_results:{max_results}")
            search_results = self._get_search_results(
                query, paper_ids, max_results
            )
            # Convert generator to list to see the actual results
            search_results_list = list(search_results)
            print(f"search_result： {search_results_list}")
            for paper in search_results_list:
                print(f"Paper details: {paper.title} by {[author.name for author in paper.authors]}")
                paper.download_pdf(
                    dirpath=output_dir, filename=f"{paper.title}" + ".pdf"
                )
            return "papers downloaded successfully"
        except Exception as e:
            return f"An error occurred: {e}"
        finally:
            os.environ['HTTP_PROXY'] = "http://proxyhk.zte.com.cn:80"
            os.environ['HTTPS_PROXY'] = "http://proxyhk.zte.com.cn:80"


def main():
    # Initialize the toolkit
    arxiv_toolkit = ArxivToolkit()

    # Search for papers about "large language models"
    search_query = """In Emily Midkiff's June 2014 article in a journal named for the one of Hreidmar's sons that guarded his house, what word was quoted from two different authors in distaste for the nature of dragon depictions?"""

    papers = arxiv_toolkit.search_papers(search_query, max_results=5)

    # Print search results
    print("Search Results:")
    for i, paper in enumerate(papers):
        print(f"\nPaper {i + 1}:")
        print(f"Title: {paper['title']}")
        print(f"Authors: {', '.join(paper['authors'])}")
        print(f"Published Date: {paper['published_date']}")
        print(f"Summary: {paper['summary'][:200]}...")  # Print first 200 chars of summary

    # Download the papers
    paper_ids = [paper['entry_id'].split('/')[-1] for paper in papers]  # Extract paper IDs
    print(f"paper_ids:{paper_ids}")
    download_status = arxiv_toolkit.download_papers(
        query=search_query,
        paper_ids=paper_ids,
        output_dir=os.getenv("WORKSPACE_PATH") or os.getcwd()
    )
    print(f"\nDownload Status: {download_status}")


if __name__ == "__main__":
    os.environ['HTTP_PROXY'] = "http://proxy.zte.com.cn:80"
    os.environ['HTTPS_PROXY'] = "http://proxy.zte.com.cn:80"
    # main()
    arxiv_toolkit = ArxivToolkit()
    test_paper_id = "2303.18223"  # A known arXiv paper ID
    result = arxiv_toolkit.download_papers(
        query="In Emily Midkiff's June 2014 article in a journal named for the one of Hreidmar's sons that guarded his house, what word was quoted from two different authors in distaste for the nature of dragon depictions?",
        paper_ids=[test_paper_id]
    )
