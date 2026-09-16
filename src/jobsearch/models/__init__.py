"""ORM model declarations for the initial job-search automation schema."""

from .applicant import Applicant
from .job import Job
from .job_evaluation import JobEvaluation
from .application import Application
from .processing_run import ProcessingRun
from .job_source import JobSource
from .request_attempt import RequestAttempt
from .request_budget import RequestBudget, RequestBudgetWindow
from .collection_control import CollectionControl

__all__ = [
    "Applicant",
    "Job",
    "JobEvaluation",
    "Application",
    "ProcessingRun",
    "JobSource",
    "RequestAttempt",
    "RequestBudget",
    "RequestBudgetWindow",
    "CollectionControl",
]
