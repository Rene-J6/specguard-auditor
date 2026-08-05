from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginRequest(StrictRequest):
    username: str
    password: str


class RegisterRequest(StrictRequest):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    full_name: str
    email: str
    phone_number: str = ""
    company_name: str = ""


class ProfileUpdateRequest(StrictRequest):
    full_name: str
    email: str
    phone_number: str = ""
    company_name: str = ""


class ChangePasswordRequest(StrictRequest):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class AnalysisRequest(StrictRequest):
    raw_text: str
    document_name: str = "Untitled Document"


class LockRequest(StrictRequest):
    document_id: str


class UnlockRequest(StrictRequest):
    document_id: str


class SingleRequirementReview(StrictRequest):
    id: int
    expert_evaluation: str
    expert_rewrite: str


class SubmitReviewRequest(StrictRequest):
    document_id: str
    reviews: List[SingleRequirementReview]
    is_approved: bool


class AdminCreateUserRequest(StrictRequest):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    full_name: str
    email: str
    role: Literal["User", "Expert", "Admin"]
    phone_number: str = ""
    company_name: str = ""


class AdminUpdateUserRequest(StrictRequest):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    company_name: Optional[str] = None
    role: Optional[Literal["User", "Expert", "Admin"]] = None
    is_active: Optional[bool] = None
