from pydantic import BaseModel, Field
from typing import List

class TestCaseStep(BaseModel):
    action: str = Field(..., description="The concrete action the tester must take.")
    expected_system_behavior: str = Field(..., description="How the medical device should respond.")

class QATestCase(BaseModel):
    title: str = Field(..., description="Short, descriptive title for the test case.")
    node_id_reference: str = Field(..., description="The specific Node ID this test is verifying.")
    prerequisites: List[str] = Field(default=[], description="Any setup required before testing.")
    steps: List[TestCaseStep] = Field(..., description="Sequential steps to execute the test.")
    pass_criteria: str = Field(..., description="The definitive condition that means the test passed.")

class QAGenerationResult(BaseModel):
    test_cases: List[QATestCase] = Field(
        ..., 
        min_length=3, 
        max_length=5, 
        description="Exactly 3 to 5 test cases based on the provided text."
    )