"""FastAPI dependency injection for authentication and authorization.

Python 服务不再直连 MySQL：鉴权只做无状态 JWT 校验，用户数据归属 Java 侧。
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from backend.auth.jwt import decode_token

# Bearer token scheme (from Authorization header)
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(credentials=Depends(bearer_scheme)) -> dict:
    """Extract and validate the current user from JWT.

    单一 token 模型：只认 Authorization: Bearer 头（与 Java 端一致），不使用 Cookie。
    只做登录态校验，不区分角色——注册即可使用全部功能。

    Returns payload dict with "sub" (user_id) and "role".
    Raises 401 if no valid token found.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录已过期",
        )

    try:
        payload = decode_token(credentials.credentials)
        return {"sub": payload.get("sub"), "role": payload.get("role")}
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期，请重新登录",
        )
