"""
Pydantic schemas for PDF processing.
"""

from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ResponseCitation(BaseModel):
    """
    Schema for a citation in the paper.
    This is used to represent a single citation with its text and context.
    """

    text: str = Field(
        description="The raw text of the citation as it appears in the paper. Ensure that this is a direct quote or paraphrase from the paper."
    )
    index: int = Field(
        description="The index of the citation in the paper's reference list. This is used to identify the citation in discussions or findings."
    )


class HighlightType(str, Enum):
    TOPIC = "topic"
    MOTIVATION = "motivation"
    METHOD = "method"
    EVIDENCE = "evidence"
    RESULT = "result"
    IMPACT = "impact"


class AIHighlight(BaseModel):
    """
    Schema for a highlight in the paper.
    This is used to represent a single highlight with its text and context.
    """

    text: str = Field(
        description="The raw text of the highlight as it appears in the paper. Ensure that this is a direct quote or paraphrase from the paper."
    )
    annotation: str = Field(
        description="The context or annotation for the highlight, explaining its significance or relevance to the paper's content. Less than 350 characters."
    )

    type: HighlightType = Field(
        description="The type of highlight. This can be one of the following: topic, motivation, method, evidence, result, impact. This helps categorize the highlight based on its content and significance."
    )


class TitleAuthorsAbstract(BaseModel):
    """Schema for title, authors, and abstract extraction."""

    title: str = Field(description="Title of the paper **in normal case**")
    authors: List[str] = Field(default=[], description="List of authors")
    abstract: str = Field(default="", description="Abstract of the paper")
    publish_date: Optional[str] = Field(
        default="", description="Publishing date of the paper in YYYY-MM-DD format"
    )


class InstitutionsKeywords(BaseModel):
    """Schema for institutions and keywords extraction."""

    institutions: List[str] = Field(
        default=[], description="List of institutions involved in the publication."
    )
    keywords: List[str] = Field(
        default=[],
        description=(
            "3-8 concise topical keywords describing the paper's subject. "
            "Write each in title case (e.g. 'Machine Learning', 'Protein Folding'), "
            "NOT normal case or ALL CAPS; capitalize only proper nouns and acronyms "
            "(e.g. 'CRISPR', 'BERT', 'Alzheimer's Disease'). Prefer established field "
            "or topic terms, keep each to a short phrase (not a sentence), and do not "
            "repeat near-duplicates."
        ),
    )


class SummaryAndCitations(BaseModel):
    """Schema for summary and citations extraction."""

    summary_citations: List[ResponseCitation] = Field(
        description="List of citations supporting the summary. Include direct quotes or paraphrases with the citation index. The index should match the inline citations used in the summary. Only include citations that are directly relevant to the summary content. Use sequential numbering starting from 1."
    )
    summary: str = Field(
        description="""
                Write a simple, easy-to-read summary of this research paper (< 200 words).
                Your reader is a 1st-year Master's student who:
                - Rarely reads research papers
                - Is NOT a native English speaker
                - Has basic knowledge of the field but not deep expertise

                ## Language rules (very important):
                - Use SHORT sentences. One idea per sentence.
                - Use SIMPLE everyday English words
                - If you must use a technical term, explain it briefly in simple words
                - Avoid: jargon, complex academic language, long sentences
                - Imagine explaining this paper to a smart friend who knows nothing about this topic

                ## Structure:
                Write 1-2 short sentences for each:
                1. **Background**: What problem did the researchers try to solve?
                2. **Method**: What did they do? (simple explanation)
                3. **Findings**: What did they find? (use simple numbers if available)

                ## Citations:
                - Use inline citations [^1], [^2] to support important claims
                - Match the citation index to the `summary_citations` field

                The goal: someone who has NEVER read a paper before should understand this summary easily.
                        """,
    )


class Highlights(BaseModel):
    """Schema for highlights extraction."""

    highlights: List[AIHighlight] = Field(
        default=[],
        description="""
Extract 3-5 highlights that capture the most interesting parts of this paper.

Your reader is a 1st-year Master's student who:
- Rarely reads papers
- Is NOT a native English speaker
- Wants to understand WHY each highlight matters, in simple words

Requirements:
- Each highlight should be a direct quote from the paper
- Each must include a SHORT annotation (1-2 simple sentences) explaining:
  * What this means in simple words
  * Why it is important or interesting
  * How a beginner should understand it

Selection criteria:
Pick highlights that are:
- Interesting or surprising findings
- Important results (use simple numbers when possible)
- Useful methods or approaches a beginner should know about

Writing style:
- Simple words, short sentences
- Explain any technical term in parentheses
- Focus on what a new reader NEEDS to know
- Avoid academic jargon
""",
    )


class PaperMetadataExtraction(BaseModel):
    """Extracted metadata from a paper"""

    title: str = Field(description="Title of the paper in normal case")
    authors: List[str] = Field(default=[], description="List of authors")
    abstract: str = Field(default="", description="Abstract of the paper")
    institutions: List[str] = Field(
        default=[], description="List of institutions involved in the publication."
    )
    keywords: List[str] = Field(
        default=[],
        description=(
            "3-8 concise topical keywords describing the paper's subject. "
            "Write each in title case (e.g. 'Machine Learning', 'Protein Folding'), "
            "NOT normal case or ALL CAPS; capitalize only proper nouns and acronyms "
            "(e.g. 'CRISPR', 'BERT', 'Alzheimer's Disease'). Prefer established field "
            "or topic terms, keep each to a short phrase (not a sentence), and do not "
            "repeat near-duplicates."
        ),
    )
    summary: str = Field(
        default="",
        description="""
A concise, well-structured summary of the paper in markdown format. Include:
1. Key findings and contributions
2. Research methodology
3. Results and implications
4. Potential applications or impact

Format guidelines:
- Optional opening title (under 10 words)
- First paragraph: 2-4 sentence overview of the paper
- Use clear headings, bullet points, and tables for organization
- Include relevant data points and metrics when available
- Use plain language while preserving technical accuracy
- Include inline citations to support claims that refer to the paper's content. This is especially important for claims about the findings, methodology, and results.

Citation guidelines:
- Use [^1], [^2], [^6, ^7] etc. for citations in the summary
- Always increase the index of the citation sequentially, starting from 1
- You will separately provide a list of citations in the `summary_citations` field with the raw text and index

The summary should be accessible to readers with basic domain knowledge while maintaining scientific integrity.
                         """,
    )
    summary_citations: List[ResponseCitation] = Field(
        default=[],
        description="List of citations that are relevant to the summary. These should be direct quotes or paraphrases from the paper that support the summary provided. Remember to include the citation index (e.g., [^1], [^2]) in the summary.",
    )
    publish_date: Optional[str] = Field(
        default=None, description="Publishing date of the paper in YYYY-MM-DD format"
    )
    highlights: List[AIHighlight] = Field(
        default=[],
        description="List of key highlights from the paper. These should be significant quotes that are must-reads of the paper's findings and contributions. Each highlight should include the text of the highlight and an annotation explaining its significance or relevance to the paper's content. Particularly drill into interesting, novel findings, methodologies, or implications that are worth noting. Pay special attention to tables, figures, and diagrams that may contain important information.",
    )


class PDFProcessingResult(BaseModel):
    """Result of PDF processing"""

    success: bool
    job_id: str
    raw_content: Optional[str] = None
    page_offset_map: Optional[dict[int, list[int]]] = None
    metadata: Optional[PaperMetadataExtraction] = None
    s3_object_key: Optional[str] = None
    file_url: Optional[str] = None
    preview_url: Optional[str] = None
    preview_object_key: Optional[str] = None
    error: Optional[str] = None
    duration: Optional[float] = None  # Duration in seconds


class DocumentMapping(BaseModel):
    title: str
    s3_object_key: str
    id: str


class DataTableSchema(BaseModel):
    """Extraction request from the server. Contains primitive (extractable)
    columns only — derived columns are computed server-side after this
    service returns the extracted dataset."""

    columns: List[str] = Field(description="List of column names in the data table.")
    papers: List[DocumentMapping] = Field(
        description="List of papers included in the data table."
    )
    list_columns: List[str] = Field(
        default=[],
        description="Subset of columns whose value is a per-paper collection: one entry per instance found in the paper, each individually cited.",
    )


class CellEntry(BaseModel):
    """One element of a list-valued cell, individually cited."""

    value: str
    key: Optional[str] = None
    citations: List[ResponseCitation] = []


class DataTableCellValue(BaseModel):
    """Value for a single cell in the data table with supporting citations."""

    value: str = Field(description="The extracted value for this column")
    citations: List[ResponseCitation] = Field(
        default=[],
        description="List of citations that support this specific value. These should be direct quotes or paraphrases from the paper.",
    )
    entries: Optional[List[CellEntry]] = Field(
        default=None,
        description="Present only on list-valued cells: the individual elements, each with its own citations. `value` holds their joined display form.",
    )


class DataTableRow(BaseModel):
    paper_id: str
    values: dict[str, DataTableCellValue]  # column_name -> cell value with citations


class DataTableResult(BaseModel):
    success: bool
    columns: List[str] = Field(description="List of column names in the data table.")
    rows: List[DataTableRow] = Field(default=[], description="Row data per paper")
    row_failures: List[str] = Field(
        default=[], description="List of paper_ids that failed to process"
    )
