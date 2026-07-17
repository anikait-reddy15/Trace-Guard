import os
from typing import List, Dict, Any
import instructor
from openai import AsyncOpenAI
from pydantic import ValidationError

from app.config import settings
from app.schemas.qa_schemas import QAGenerationResult
from app.schemas.document_schemas import NodeBase

class LLMGenerationError(Exception):
    """Custom exception for when the LLM repeatedly fails to follow instructions."""
    pass

class QAEngine:
    def __init__(self):
        # We use the OpenAI client pointed at Google's Gemini endpoint.
        # This provides the most stable Instructor/Structured Output experience for Gemini.
        api_key = settings.llm_api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("LLM API key is missing. Set it in .env")

        self.client = instructor.from_openai(
            AsyncOpenAI(
                api_key=api_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
            ),
            mode=instructor.Mode.JSON
        )
        self.model = "gemini-3.5-flash" # Fast, cheap, and excellent at structured data

    def _build_context_prompt(self, nodes: List[Dict[str, Any]]) -> str:
        """Formats the selected nodes into a readable context for the LLM."""
        context = "DOCUMENT SELECTION EXTRACT:\n\n"
        for node in nodes:
            context += f"--- NODE ID: {node['node_id']} ---\n"
            context += f"HEADING: {node['node']['heading']}\n"
            context += f"TEXT: {node['node']['body_text']}\n\n"
        return context

    async def generate_test_cases(self, nodes: List[Dict[str, Any]]) -> QAGenerationResult:
        """
        Generates 3-5 QA test cases from the provided text.
        Includes a strict retry loop to handle hallucinations.
        """
        context = self._build_context_prompt(nodes)
        
        try:
            # Instructor patches the client to return our Pydantic model directly
            generation: QAGenerationResult = await self.client.chat.completions.create(
                model=self.model,
                response_model=QAGenerationResult,
                max_retries=3, # If validation fails, it asks the LLM to fix its own JSON
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a Senior Quality Assurance Engineer for regulated medical devices. "
                            "Your job is to read extracts from a device manual and write concrete, repeatable "
                            "test cases. Every test must be traceable to a specific NODE ID. "
                            "You must return EXACTLY 3 to 5 test cases. Do not assume hardware features "
                            "that are not mentioned in the text."
                        )
                    },
                    {
                        "role": "user",
                        "content": context
                    }
                ]
            )
            return generation
            
        except ValidationError as e:
            # This triggers if the LLM completely fails after 3 retries.
            # Design Choice: We do not fail silently. We raise a specific error that the API 
            # will catch and log as a "FAILED" generation attempt in the database.
            raise LLMGenerationError(f"LLM failed to adhere to schema after 3 retries: {str(e)}")
        except Exception as e:
            # Catch rate limits, network drops, or API key errors
            raise LLMGenerationError(f"LLM API failure: {str(e)}")