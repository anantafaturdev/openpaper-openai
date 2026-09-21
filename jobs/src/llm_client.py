"""
OpenAI-compatible LLM client for metadata extraction.

Replaces the previous Gemini-specific implementation. Uses the same
OpenAI-compatible endpoint as the server (OPENAI_API_KEY + OPENAI_BASE_URL).
"""

import asyncio
import base64
import io
import json
import logging
import os
import random
import re

import httpx
from dotenv import load_dotenv

load_dotenv()

from src.observability import configure_langfuse

configure_langfuse()

from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

import pymupdf
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from openai import APIError as OpenAIAPIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from src.prompts import (
    EXTRACT_COLS_INSTRUCTION,
    EXTRACT_METADATA_PROMPT_TEMPLATE,
    SYSTEM_INSTRUCTIONS_CACHE,
)
from src.schemas import (
    CellEntry,
    DataTableCellValue,
    DataTableRow,
    Highlights,
    InstitutionsKeywords,
    PaperMetadataExtraction,
    ResponseCitation,
    SummaryAndCitations,
    TitleAuthorsAbstract,
)
from src.utils import retry_llm_operation, time_it

logger = logging.getLogger(__name__)


def _format_api_error(e: Exception) -> str:
    """Pull a concise error message for logging."""
    if isinstance(e, OpenAIAPIError):
        body = getattr(e, "body", None)
        if isinstance(body, dict):
            return str(body.get("error", body))
        return str(e)
    return str(e)


# HTTP status codes worth retrying. Everything else is deterministic.
RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


def _is_retryable(e: Exception) -> bool:
    """Whether re-sending the identical request could plausibly succeed."""
    if isinstance(e, (APITimeoutError, APIConnectionError)):
        return True
    if isinstance(e, RateLimitError):
        return True
    if isinstance(e, OpenAIAPIError):
        status = getattr(e, "status_code", None)
        return status in RETRYABLE_STATUS_CODES
    return False


# Constants
DEFAULT_CHAT_MODEL = "deepseek-v4-flash"
FAST_CHAT_MODEL = "deepseek-v4-pro"
CACHE_TTL_SECONDS = 3600
CACHE_MIN_CONTENT_CHARS = 5000

# Pydantic model type variable
T = TypeVar("T", bound=BaseModel)


class JSONParser:
    """Parse JSON from LLM responses"""

    @staticmethod
    def validate_and_extract_json(text: str) -> Any:
        """
        Extract and validate JSON from LLM response text.

        Handles:
        - JSON with markdown code fences (```json ... ```)
        - JSON with leading/trailing text
        - Invalid JSON (raises ValueError)

        Args:
            text: The raw text from LLM response

        Returns:
            Parsed JSON data
        """
        # Try to find JSON in code fences first
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # Try to find JSON object directly (from { to matching })
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            json_str = brace_match.group(0)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # Last resort: try parsing the whole text
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            logger.debug(f"Raw text (first 500 chars): {text[:500]}")
            raise ValueError(f"Could not extract valid JSON from response: {e}")


class AsyncLLMClient:
    """
    An async LLM client using OpenAI-compatible API for metadata extraction.
    """

    DEFAULT_TIMEOUT = 90_000  # 90s for text/cached operations
    PDF_TIMEOUT = 120_000  # 120s for PDF file operations
    MAX_PDF_CHARS = 500_000  # Max PDF text chars to send (truncated if larger)

    def __init__(
        self,
        api_key: str,
        base_url: str,
        default_model: Optional[str] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.default_model: str = default_model or DEFAULT_CHAT_MODEL

    def _create_client(self, timeout: int = DEFAULT_TIMEOUT) -> AsyncOpenAI:
        """Create a fresh client instance for thread-safe concurrent calls."""
        if not self.api_key:
            raise ValueError("API key is not set")
        return AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout / 1000.0,  # OpenAI client uses seconds
            max_retries=0,  # We handle retries ourselves
        )

    async def _close_client(self, client: AsyncOpenAI) -> None:
        """Close the async HTTP client."""
        try:
            await client.aclose()
        except Exception:
            pass

    async def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        """Rough token count estimate (no count_tokens endpoint on most providers)."""
        return len(text) // 4

    async def create_cache(
        self, cache_content: str, client: AsyncOpenAI, model: Optional[str] = None
    ) -> str:
        """Caching not supported with OpenAI-compatible endpoints. Returns empty string."""
        logger.warning("Content caching not supported; using inline content")
        return ""

    async def create_file_cache(
        self,
        file_path: str,
        client: AsyncOpenAI,
        system_instructions: Optional[str] = None,
    ) -> str:
        """File caching not supported with OpenAI-compatible endpoints. Returns empty string."""
        logger.warning("File caching not supported; using inline content")
        return ""

    def _extract_text_from_pdf(self, file_path: str) -> str:
        """Extract text from a PDF file using pymupdf."""
        doc = pymupdf.open(file_path)
        try:
            text = ""
            for page in doc:
                text += page.get_text()
            # Truncate if too large
            if len(text) > self.MAX_PDF_CHARS:
                text = text[: self.MAX_PDF_CHARS]
                logger.warning(
                    f"PDF text truncated to {self.MAX_PDF_CHARS} chars (was {len(text)} total)"
                )
            return text
        finally:
            doc.close()

    async def generate_content(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
        image_mime_type: Optional[str] = None,
        cache_key: Optional[str] = None,
        model: Optional[str] = None,
        schema: Optional[Type[BaseModel]] = None,
        file_path: Optional[str] = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        client: Optional[AsyncOpenAI] = None,
    ) -> str:
        """
        Generate content using the LLM with automatic retry and exponential backoff.

        Args:
            prompt: The prompt to send to the LLM
            image_bytes: Optional image bytes (sent as base64 data URL)
            model: Optional specific model to use
            max_retries: Maximum number of retry attempts (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 1.0)
            client: Optional client to use

        Returns:
            str: The generated content from the LLM
        """
        if not client:
            raise ValueError("Client is required for generate_content")

        if not model:
            model = self.default_model

        messages = [{"role": "user", "content": []}]
        content_list = messages[0]["content"]

        # Handle image input (e.g. for captioning)
        if image_bytes:
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            content_list.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image_mime_type or 'image/png'};base64,{b64}"
                    },
                }
            )

        # Handle PDF file input — extract text and include inline
        if file_path:
            pdf_text = self._extract_text_from_pdf(file_path)
            content_list.append(
                {"type": "text", "text": f"PDF Content:\n\n{pdf_text}\n\n"}
            )

        content_list.append({"type": "text", "text": prompt})

        # For structured output, add a system message asking for JSON
        kwargs: Dict[str, Any] = {}
        if schema:
            kwargs["response_format"] = {"type": "json_object"}
            system_msg = "You are a helpful assistant. Respond with valid JSON only."
            messages.insert(0, {"role": "system", "content": system_msg})

        last_exception: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    **kwargs,
                )

                text = response.choices[0].message.content
                if text:
                    return text

                raise ValueError("No content generated from LLM response")

            except (
                OpenAIAPIError,
                APITimeoutError,
                APIConnectionError,
                RateLimitError,
                httpx.TimeoutException,
            ) as e:
                last_exception = e
                if not _is_retryable(e):
                    logger.error(
                        f"Non-retryable LLM API error for generate_content: {_format_api_error(e)}"
                    )
                    break
                if attempt < max_retries:
                    backoff_time = (
                        base_delay * (2**attempt) * (0.5 + 0.5 * random.random())
                    )
                    logger.warning(
                        f"LLM API error (attempt {attempt + 1}/{max_retries + 1}): {_format_api_error(e)}. "
                        f"Retrying in {backoff_time:.2f}s"
                    )
                    await asyncio.sleep(backoff_time)
                else:
                    logger.error(
                        f"All {max_retries + 1} attempts failed for generate_content: {_format_api_error(e)}"
                    )

        raise last_exception or ValueError(
            "Failed to generate content after all retries"
        )

    async def generate_structured(
        self,
        prompt: str,
        schema: Type[T],
        client: AsyncOpenAI,
        model: Optional[str] = None,
        file_path: Optional[str] = None,
        cache_key: Optional[str] = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> T:
        """
        Generate content constrained to a Pydantic schema and return a validated instance.

        Uses response_format='json_object' and provides the schema in the system
        prompt. Retries on transport errors as well as parse/validation failures,
        adding a corrective instruction on retry.

        Args:
            prompt: The prompt describing what to extract
            schema: The Pydantic model class to parse the response into
            client: The OpenAI client to use
            model: Optional model override
            file_path: Optional path to a PDF file (text will be extracted and included)
            cache_key: Ignored (not supported with OpenAI-compatible endpoints)
            max_retries: Maximum retry attempts
            base_delay: Base delay for exponential backoff

        Returns:
            An instance of the provided Pydantic model
        """
        if not client:
            raise ValueError("Client is required for generate_structured")

        if not model:
            model = self.default_model

        # Build messages with schema definition included so the model knows which fields to output
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        system_prompt = (
            "You are a research paper metadata extraction assistant. "
            "Respond with ONLY a single JSON object matching this exact schema:\n\n"
            f"{schema_json}\n\n"
            "Do not include markdown code fences, explanations, or any text outside the JSON object. "
            "Every field listed in the schema is required unless marked as optional."
        )

        # Build user content
        user_parts = []

        if file_path:
            pdf_text = self._extract_text_from_pdf(file_path)
            user_parts.append(
                {"type": "text", "text": f"PDF Content:\n\n{pdf_text}\n\n"}
            )

        user_parts.append({"type": "text", "text": prompt})

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_parts},
        ]

        last_exception: Optional[Exception] = None
        last_raw: Optional[str] = None

        for attempt in range(max_retries + 1):
            current_messages = list(messages)

            # On retry after a parse failure, add a corrective instruction
            if attempt > 0 and last_raw is not None:
                current_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous response could not be parsed as valid JSON. "
                            "Respond with ONLY a single JSON object matching the schema — "
                            "no prose, no markdown code fences, and properly escape any quotes inside string values."
                        ),
                    }
                )

            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=current_messages,
                    response_format={"type": "json_object"},
                )

                text = response.choices[0].message.content
                last_raw = text

                if not text:
                    raise ValueError("No content generated from LLM response")

                response_json = JSONParser.validate_and_extract_json(text)
                return schema.model_validate(response_json)

            except (
                OpenAIAPIError,
                APITimeoutError,
                APIConnectionError,
                RateLimitError,
                httpx.TimeoutException,
            ) as e:
                last_exception = e
                if not _is_retryable(e):
                    logger.error(
                        f"Non-retryable LLM API error for generate_structured "
                        f"({schema.__name__}): {_format_api_error(e)}"
                    )
                    break
                if attempt < max_retries:
                    backoff_time = (
                        base_delay * (2**attempt) * (0.5 + 0.5 * random.random())
                    )
                    logger.warning(
                        f"LLM API failed (attempt {attempt + 1}/{max_retries + 1}): {_format_api_error(e)}. "
                        f"Retrying in {backoff_time:.2f}s"
                    )
                    await asyncio.sleep(backoff_time)
                else:
                    logger.error(
                        f"All {max_retries + 1} attempts failed for generate_structured: {_format_api_error(e)}"
                    )
            except (ValueError, ValidationError) as e:
                last_exception = e
                if attempt < max_retries:
                    backoff_time = (
                        base_delay * (2**attempt) * (0.5 + 0.5 * random.random())
                    )
                    logger.warning(
                        f"Structured parse failed for {schema.__name__} "
                        f"(attempt {attempt + 1}/{max_retries + 1}): {e}. Retrying in {backoff_time:.2f}s"
                    )
                    await asyncio.sleep(backoff_time)
                else:
                    logger.error(
                        f"All {max_retries + 1} attempts failed to parse structured response for "
                        f"{schema.__name__}. Raw response (first 1000 chars): {(last_raw or '')[:1000]!r}"
                    )

        raise last_exception or ValueError(
            "Failed to generate structured content after all retries"
        )


class PaperOperations(AsyncLLMClient):
    """
    LLM client for paper metadata extraction using an OpenAI-compatible endpoint.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        default_model: Optional[str] = None,
    ):
        """Initialize the LLM client for paper operations."""
        super().__init__(api_key, base_url, default_model=default_model)

    async def count_metadata_prompt_tokens(self, paper_content: str) -> int:
        """Rough token count estimate."""
        return await self.count_tokens(paper_content, model=FAST_CHAT_MODEL)

    async def _extract_single_metadata_field(
        self,
        model: Type[T],
        paper_content: str,
        schema: Type[BaseModel],
        status_callback: Callable[[str], None],
        client: AsyncOpenAI,
        cache_key: Optional[str] = None,
        llm_model: Optional[str] = None,
    ) -> T:
        """
        Helper function to extract a single metadata field.

        Args:
            model: The Pydantic model for the data to extract.
            paper_content: The paper content.
            status_callback: Optional function to update task status.
            client: The OpenAI client to use.
            llm_model: Optional LLM model override.

        Returns:
            An instance of the provided Pydantic model.
        """
        # Build a schema-specific extraction instruction so the model knows what fields to produce
        schema_name = model.__name__
        schema_fields = list(model.model_fields.keys())
        fields_str = ", ".join(f'"{f}"' for f in schema_fields)
        instruction = (
            f"Extract the following fields from this paper and return them as a JSON object: {fields_str}.\n"
            f'This extraction is for the "{schema_name}" schema.\n'
            f"Each field is described in the JSON schema above — match the field names and types exactly."
        )

        if paper_content and not cache_key:
            prompt = f"Paper Content:\n\n{paper_content}\n\n{instruction}"
        else:
            prompt = instruction

        instance = await self.generate_structured(
            prompt, schema=model, cache_key=cache_key, client=client, model=llm_model
        )

        if model == SummaryAndCitations:
            n_citations = len(getattr(instance, "summary_citations", []))
            status_callback(f"Compiled with {n_citations} citations")
        elif model == InstitutionsKeywords:
            keywords = getattr(instance, "keywords", [])
            institutions = getattr(instance, "institutions", [])
            first_keyword = keywords[0] if keywords else ""
            if first_keyword:
                status_callback(f"Building on {first_keyword} context")
            elif institutions:
                first_institution = institutions[0] if institutions else ""
                status_callback(f"Adding context from institution: {first_institution}")
            else:
                status_callback("Processing without keyword data")
        elif model == Highlights:
            highlights = getattr(instance, "highlights", [])
            if highlights:
                status_callback(f"Formulated {len(highlights)} annotations")
            else:
                status_callback("No annotations extracted")
        elif model == TitleAuthorsAbstract:
            title = getattr(instance, "title", "")
            status_callback(f"Reading {title if title else 'untitled paper'}")
        else:
            status_callback(f"Successfully extracted {model.__name__}")

        return instance

    @retry_llm_operation(max_retries=3, delay=1.0)
    async def extract_title_authors_abstract(
        self,
        paper_content: str,
        status_callback: Callable[[str], None],
        client: AsyncOpenAI,
        cache_key: Optional[str] = None,
        llm_model: Optional[str] = None,
    ) -> TitleAuthorsAbstract:
        result = await self._extract_single_metadata_field(
            model=TitleAuthorsAbstract,
            cache_key=cache_key,
            schema=TitleAuthorsAbstract,
            paper_content=paper_content,
            status_callback=status_callback,
            client=client,
            llm_model=llm_model,
        )
        return result

    @retry_llm_operation(max_retries=3, delay=1.0)
    async def extract_institutions_keywords(
        self,
        paper_content: str,
        status_callback: Callable[[str], None],
        client: AsyncOpenAI,
        cache_key: Optional[str] = None,
        llm_model: Optional[str] = None,
    ) -> InstitutionsKeywords:
        return await self._extract_single_metadata_field(
            model=InstitutionsKeywords,
            cache_key=cache_key,
            schema=InstitutionsKeywords,
            paper_content=paper_content,
            status_callback=status_callback,
            client=client,
            llm_model=llm_model,
        )

    @retry_llm_operation(max_retries=3, delay=1.0)
    async def extract_summary_and_citations(
        self,
        paper_content: str,
        status_callback: Callable[[str], None],
        client: AsyncOpenAI,
        cache_key: Optional[str] = None,
        llm_model: Optional[str] = None,
    ) -> SummaryAndCitations:
        result = await self._extract_single_metadata_field(
            model=SummaryAndCitations,
            cache_key=cache_key,
            schema=SummaryAndCitations,
            paper_content=paper_content,
            status_callback=status_callback,
            client=client,
            llm_model=llm_model,
        )
        return result

    @retry_llm_operation(max_retries=3, delay=1.0)
    async def extract_highlights(
        self,
        paper_content: str,
        status_callback: Callable[[str], None],
        client: AsyncOpenAI,
        cache_key: Optional[str] = None,
        llm_model: Optional[str] = None,
    ) -> Highlights:
        return await self._extract_single_metadata_field(
            model=Highlights,
            paper_content=paper_content,
            status_callback=status_callback,
            cache_key=cache_key,
            schema=Highlights,
            client=client,
            llm_model=llm_model,
        )

    async def extract_paper_metadata(
        self,
        paper_content: str,
        job_id: str,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> PaperMetadataExtraction:
        """
        Extract metadata from paper content using LLM.

        Args:
            paper_content: The extracted text content from the PDF
            job_id: Job ID for tracking
            status_callback: Optional function to update task status

        Returns:
            PaperMetadataExtraction: Extracted metadata
        """
        async with time_it("Extracting paper metadata from LLM", job_id=job_id):
            extraction_model = FAST_CHAT_MODEL

            # Create a fresh client for this operation
            client = self._create_client()

            try:
                # With OpenAI-compatible endpoints, we always send content inline
                # (caching is not supported, so skip it entirely).
                cache_key = None

                # Run all extraction tasks concurrently
                async with time_it(
                    "Running all metadata extraction tasks concurrently", job_id=job_id
                ):
                    tasks = [
                        asyncio.create_task(
                            time_it(
                                "Extracting title, authors, and abstract",
                                job_id=job_id,
                            )(self.extract_title_authors_abstract)(
                                paper_content=paper_content,
                                cache_key=cache_key,
                                status_callback=status_callback,
                                client=client,
                                llm_model=extraction_model,
                            )
                        ),
                        asyncio.create_task(
                            time_it(
                                "Extracting institutions and keywords", job_id=job_id
                            )(self.extract_institutions_keywords)(
                                paper_content=paper_content,
                                cache_key=cache_key,
                                status_callback=status_callback,
                                client=client,
                                llm_model=extraction_model,
                            )
                        ),
                        asyncio.create_task(
                            time_it("Extracting summary and citations", job_id=job_id)(
                                self.extract_summary_and_citations
                            )(
                                paper_content=paper_content,
                                cache_key=cache_key,
                                status_callback=status_callback,
                                client=client,
                                llm_model=extraction_model,
                            )
                        ),
                        asyncio.create_task(
                            time_it("Extracting highlights", job_id=job_id)(
                                self.extract_highlights
                            )(
                                paper_content=paper_content,
                                cache_key=cache_key,
                                status_callback=status_callback,
                                client=client,
                                llm_model=extraction_model,
                            )
                        ),
                    ]

                    # Use shield to prevent task cancellation during cleanup
                    shielded_tasks = [asyncio.shield(task) for task in tasks]
                    results = await asyncio.gather(
                        *shielded_tasks, return_exceptions=True
                    )

                # Process results and handle potential errors
                (
                    title_authors_abstract,
                    institutions_keywords,
                    summary_and_citations,
                    highlights,
                ) = results

                subtask_labels = (
                    "title_authors_abstract",
                    "institutions_keywords",
                    "summary_and_citations",
                    "highlights",
                )
                failed_subtasks = [
                    (label, result)
                    for label, result in zip(subtask_labels, results)
                    if isinstance(result, BaseException)
                ]
                if failed_subtasks:
                    non_printable = sum(
                        1
                        for c in paper_content
                        if not c.isprintable() and c not in "\n\r\t"
                    )
                    logger.error(
                        "Metadata extraction failed for job %s [%d/%d subtasks failed]: "
                        "model=%s, path=%s, paper_content_chars=%d, non_printable_chars=%d",
                        job_id,
                        len(failed_subtasks),
                        len(subtask_labels),
                        extraction_model or self.default_model,
                        "inline" if cache_key is None else "cached",
                        len(paper_content),
                        non_printable,
                    )
                for label, result in failed_subtasks:
                    logger.error(
                        f"Metadata subtask '{label}' failed for job {job_id}: {result}",
                        exc_info=result,
                    )

                if isinstance(title_authors_abstract, BaseException):
                    raise title_authors_abstract

                return PaperMetadataExtraction(
                    title=getattr(title_authors_abstract, "title", ""),
                    authors=getattr(title_authors_abstract, "authors", []),
                    abstract=getattr(title_authors_abstract, "abstract", ""),
                    institutions=getattr(institutions_keywords, "institutions", []),
                    keywords=getattr(institutions_keywords, "keywords", []),
                    summary=getattr(summary_and_citations, "summary", ""),
                    summary_citations=getattr(
                        summary_and_citations, "summary_citations", []
                    ),
                    highlights=getattr(highlights, "highlights", []),
                    publish_date=getattr(title_authors_abstract, "publish_date", None),
                )

            except Exception as e:
                logger.error(f"Error extracting metadata: {e}", exc_info=True)
                if status_callback:
                    status_callback(f"Error during metadata extraction: {e}")
                raise ValueError(f"Failed to extract metadata: {str(e)}")
            finally:
                await self._close_client(client)

    async def extract_data_table(
        self,
        columns: List[str],
        file_path: str,
        paper_id: str,
        list_columns: Optional[List[str]] = None,
    ) -> DataTableRow:
        """
        Extract structured data table from paper content.

        Args:
            columns: List of column names for the data table
            file_path: The file path to the PDF
            list_columns: Subset of columns extracted as collections

        Returns:
            DataTableRow with extracted values
        """
        # Create a fresh client with longer timeout since we're sending full PDFs
        client = self._create_client(timeout=self.PDF_TIMEOUT)
        list_column_set = set(list_columns or [])

        try:
            # Map each column to a safe field name
            aliases: Dict[str, str] = {f"col_{i}": col for i, col in enumerate(columns)}

            cols_str = "\n".join(
                f'- {alias}: "{col}"'
                + (
                    " [LIST: one keyed entry per instance found in the paper]"
                    if col in list_column_set
                    else ""
                )
                for alias, col in aliases.items()
            )
            prompt = EXTRACT_COLS_INSTRUCTION.format(
                cols_str=cols_str, n_cols=len(columns)
            )

            class ExtractedCell(BaseModel):
                value: str
                citations: List[ResponseCitation] = []

            class ExtractedEntry(BaseModel):
                key: str = Field(
                    description=(
                        "Label identifying which instance this entry belongs to "
                        "(model name, dataset, condition, etc.). Empty string if "
                        "the paper gives no such label."
                    )
                )
                value: str
                citations: List[ResponseCitation] = []

            field_definitions: Dict[str, Any] = {
                alias: (
                    (
                        List[ExtractedEntry],
                        Field(
                            description=f"One keyed entry per instance found for column: {col!r}"
                        ),
                    )
                    if col in list_column_set
                    else (
                        ExtractedCell,
                        Field(description=f"Value and citations for column: {col!r}"),
                    )
                )
                for alias, col in aliases.items()
            }

            ValuesModel = create_model(
                "ValuesModel",
                __config__=ConfigDict(),
                **field_definitions,
            )

            values_instance = await self.generate_structured(
                prompt,
                schema=ValuesModel,
                model=self.default_model,
                file_path=file_path,
                client=client,
            )

            # Map aliased fields back to the original column names
            values_dict: Dict[str, DataTableCellValue] = {}
            for alias, col in aliases.items():
                extracted = getattr(values_instance, alias)
                if col in list_column_set:
                    entries = [
                        CellEntry(
                            value=e.value,
                            key=e.key.strip() or None,
                            citations=e.citations,
                        )
                        for e in extracted
                        if e.value.strip() and e.value.strip().upper() != "N/A"
                    ]
                    values_dict[col] = DataTableCellValue(
                        value="; ".join(
                            f"{e.key}: {e.value}" if e.key else e.value for e in entries
                        )
                        if entries
                        else "N/A",
                        citations=[],
                        entries=entries,
                    )
                else:
                    values_dict[col] = DataTableCellValue(
                        value=extracted.value, citations=extracted.citations
                    )

            return DataTableRow(paper_id=paper_id, values=values_dict)

        except Exception as e:
            logger.error(f"Error extracting data table: {str(e)}", exc_info=True)
            raise ValueError(f"Failed to extract DT for paper {paper_id}: {str(e)}")
        finally:
            await self._close_client(client)


# Create instances for the application
api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_BASE_URL")

if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is not set")
if not base_url:
    raise ValueError("OPENAI_BASE_URL environment variable is not set")

llm_client = PaperOperations(
    api_key=api_key, base_url=base_url, default_model=DEFAULT_CHAT_MODEL
)
fast_llm_client = PaperOperations(
    api_key=api_key, base_url=base_url, default_model=FAST_CHAT_MODEL
)
