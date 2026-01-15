"""
Configuration management for Artillery.

Loads and validates configuration from environment variables with sensible defaults.
All directory paths are validated for existence and write permissions at startup.
"""

import os
import sys
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _validate_directory(env_var: str, default: str) -> Path:
    """
    Validate and return directory path from environment variable or default.
    
    Creates the directory if it doesn't exist. Raises SystemExit if:
    - Path exists but is not a directory
    - Path is not writable
    
    Args:
        env_var: Environment variable name to check
        default: Default path if env var not set
        
    Returns:
        Validated Path object
        
    Raises:
        SystemExit: On validation failure
    """
    path_str = os.environ.get(env_var, default)
    
    try:
        path = Path(path_str).expanduser().resolve()
        
        # Create directory if it doesn't exist
        if not path.exists():
            logger.info(f"Creating directory: {path}")
            path.mkdir(parents=True, exist_ok=True)
        
        # Verify it's actually a directory
        if not path.is_dir():
            logger.critical(
                f"Configuration error: {path} exists but is not a directory "
                f"(set via {env_var}={path_str})"
            )
            sys.exit(1)
        
        # Verify write permissions
        if not os.access(path, os.W_OK):
            logger.critical(
                f"Permission error: {path} is not writable "
                f"(check filesystem permissions for {env_var})"
            )
            sys.exit(1)
        
        return path
        
    except Exception as exc:
        logger.critical(
            f"Failed to validate {env_var}={path_str}: {exc}"
        )
        sys.exit(1)


def _validate_int(env_var: str, default: int, min_val: Optional[int] = None,
                  max_val: Optional[int] = None) -> int:
    """
    Validate and return integer from environment variable or default.
    
    Args:
        env_var: Environment variable name
        default: Default value if env var not set
        min_val: Minimum allowed value (inclusive)
        max_val: Maximum allowed value (inclusive)
        
    Returns:
        Validated integer value
        
    Raises:
        SystemExit: If value is not a valid integer or outside bounds
    """
    value_str = os.environ.get(env_var, str(default))
    
    try:
        value = int(value_str)
    except ValueError:
        logger.critical(
            f"Configuration error: {env_var}={value_str} is not a valid integer"
        )
        sys.exit(1)
    
    if min_val is not None and value < min_val:
        logger.critical(
            f"Configuration error: {env_var}={value} is below minimum {min_val}"
        )
        sys.exit(1)
    
    if max_val is not None and value > max_val:
        logger.critical(
            f"Configuration error: {env_var}={value} exceeds maximum {max_val}"
        )
        sys.exit(1)
    
    return value


def _validate_bool(env_var: str, default: bool) -> bool:
    """
    Validate and return boolean from environment variable or default.
    
    Accepts: "1", "true", "yes", "on" (case-insensitive) for True
    Accepts: "0", "false", "no", "off" (case-insensitive) for False
    
    Args:
        env_var: Environment variable name
        default: Default value if env var not set
        
    Returns:
        Validated boolean value
        
    Raises:
        SystemExit: If value is not recognized as boolean
    """
    value_str = os.environ.get(env_var)
    if value_str is None:
        return default
    
    value_lower = value_str.lower().strip()
    if value_lower in ("1", "true", "yes", "on"):
        return True
    elif value_lower in ("0", "false", "no", "off"):
        return False
    else:
        logger.critical(
            f"Configuration error: {env_var}={value_str} is not a valid boolean "
            f"(use: 1/0, true/false, yes/no, or on/off)"
        )
        sys.exit(1)


@dataclass
class Config:
    """Application configuration loaded from environment variables."""
    
    # Data directories (required with validation)
    tasks_dir: Path
    config_dir: Path
    downloads_dir: Path
    
    # Flask security
    secret_key: str
    
    # Logging
    log_level: str
    debug_requests: bool
    debug_fs: bool
    hang_dump_seconds: int
    
    # Login/authentication
    login_required: bool
    login_username: str
    login_password: str
    
    # Media wall
    media_wall_enabled: bool
    media_wall_items_per_page: int
    media_wall_cache_videos: bool
    media_wall_copy_limit: int
    media_wall_auto_ingest_on_task_end: bool
    media_wall_auto_refresh_on_task_end: bool
    media_wall_min_refresh_seconds: int
    
    # Gallery-dl config
    default_config_url: str
    
    @classmethod
    def from_env(cls) -> "Config":
        """
        Load and validate configuration from environment variables.
        
        Validates all paths exist and are writable.
        Validates all numeric values are within acceptable ranges.
        Exits with error code 1 if any validation fails.
        
        Returns:
            Validated Config instance
        """
        logger.info("Loading configuration from environment variables...")
        
        # Validate directories (creates them if they don't exist)
        tasks_dir = _validate_directory("TASKS_DIR", "/tasks")
        config_dir = _validate_directory("CONFIG_DIR", "/config")
        downloads_dir = _validate_directory("DOWNLOADS_DIR", "/downloads")
        
        logger.info(f"  TASKS_DIR: {tasks_dir}")
        logger.info(f"  CONFIG_DIR: {config_dir}")
        logger.info(f"  DOWNLOADS_DIR: {downloads_dir}")
        
        # Logging configuration
        log_level = os.environ.get("ARTILLERY_LOG_LEVEL", "INFO").upper()
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if log_level not in valid_levels:
            logger.warning(
                f"Invalid log level: {log_level}, using INFO"
            )
            log_level = "INFO"
        
        # Numeric validation
        media_wall_items = _validate_int(
            "MEDIA_WALL_ITEMS", 45, min_val=1, max_val=500
        )
        media_wall_copy_limit = _validate_int(
            "MEDIA_WALL_COPY_LIMIT", 100, min_val=1, max_val=1000
        )
        media_wall_min_refresh = _validate_int(
            "MEDIA_WALL_MIN_REFRESH_SECONDS", 300, min_val=0, max_val=86400
        )
        hang_dump_seconds = _validate_int(
            "ARTILLERY_HANG_DUMP_SECONDS", 0, min_val=0
        )
        
        config = cls(
            tasks_dir=tasks_dir,
            config_dir=config_dir,
            downloads_dir=downloads_dir,
            secret_key=os.environ.get("SECRET_KEY", "dev-secret-key"),
            log_level=log_level,
            debug_requests=_validate_bool("ARTILLERY_DEBUG_REQUESTS", False),
            debug_fs=_validate_bool("ARTILLERY_DEBUG_FS", False),
            hang_dump_seconds=hang_dump_seconds,
            login_required=_validate_bool("ARTILLERY_LOGIN_REQUIRED", False),
            login_username=os.environ.get("ARTILLERY_USERNAME", "admin"),
            login_password=os.environ.get("ARTILLERY_PASSWORD", "artillery"),
            media_wall_enabled=_validate_bool("MEDIA_WALL_ENABLED", True),
            media_wall_items_per_page=media_wall_items,
            media_wall_cache_videos=_validate_bool("MEDIA_WALL_CACHE_VIDEOS", False),
            media_wall_copy_limit=media_wall_copy_limit,
            media_wall_auto_ingest_on_task_end=_validate_bool(
                "MEDIA_WALL_AUTO_INGEST_ON_TASK_END", True
            ),
            media_wall_auto_refresh_on_task_end=_validate_bool(
                "MEDIA_WALL_AUTO_REFRESH_ON_TASK_END", True
            ),
            media_wall_min_refresh_seconds=media_wall_min_refresh,
            default_config_url=os.environ.get(
                "GALLERYDL_DEFAULT_CONFIG_URL",
                "https://raw.githubusercontent.com/mikf/gallery-dl/master/docs/gallery-dl.conf",
            ),
        )
        
        logger.info("Configuration loaded and validated successfully")
        return config
