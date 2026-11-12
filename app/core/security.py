import secrets
from fastapi import Security, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

security_scheme = HTTPBearer()

def verify_admin_token(credentials: HTTPAuthorizationCredentials = Security(security_scheme)) -> str:
    if not secrets.compare_digest(credentials.credentials, settings.ADMIN_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing ADMIN_TOKEN.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials
