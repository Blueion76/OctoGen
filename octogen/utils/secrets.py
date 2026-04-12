"""Docker secrets support for secure configuration"""

import os
from pathlib import Path
from typing import Optional


def load_secret(secret_name: str, default: Optional[str] = None) -> Optional[str]:
    """Load a secret from Docker secrets or environment variable.
    
    Checks in order:
    1. /run/secrets/{secret_name}
    2. Environment variable {secret_name}
    3. Default value
    
    Args:
        secret_name: Name of the secret/environment variable
        default: Default value if secret not found
        
    Returns:
        Secret value or default
    """
    # Try Docker secrets first
    secret_path = Path(f"/run/secrets/{secret_name.lower()}")
    if secret_path.exists():
        try:
            value = secret_path.read_text().strip()
            if value:
                return value
        except Exception:
            pass
    
    # Fall back to environment variable
    value = os.getenv(secret_name, default)
    return value if value else default
