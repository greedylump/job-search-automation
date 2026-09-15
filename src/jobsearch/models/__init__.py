"""ORM model declarations for the initial job-search automation schema."""

from .applicant import Applicant
from .job import Job
from .job_evaluation import JobEvaluation
from .application import Application
from .processing_run import ProcessingRun
from .job_source import JobSource

__all__ = [
    "Applicant",
    "Job",
    "JobEvaluation",
    "Application",
    "ProcessingRun",
    "JobSource",
]
