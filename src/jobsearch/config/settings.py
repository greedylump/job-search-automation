import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./jobsearch.db"
    log_level: str = "INFO"
    data_dir: Path = Path("data")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("JOBSEARCH_DATABASE_URL", "sqlite:///./jobsearch.db"),
            log_level=os.getenv("JOBSEARCH_LOG_LEVEL", "INFO"),
            data_dir=Path(os.getenv("JOBSEARCH_DATA_DIR", "data")),
        )


settings = Settings.from_env()


def get_settings() -> Settings:
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    return Settings.from_env()
