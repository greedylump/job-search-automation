"""ORM model declarations for the initial job-search automation schema."""

from .job import Job
from .job_evaluation import JobEvaluation
from .application import Application
from .processing_run import ProcessingRun

__all__ = [
    "Job",
    "JobEvaluation",
    "Application",
    "ProcessingRun",
]
