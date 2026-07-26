"""JWT token verification using PyJWT (not python-jose).

Python 服务不发 token（token 由 Java 端登录/注册签发），这里只做校验，
与 Java 端单一 token 模型（无 access/refresh 区分）保持一致。
"""
import jwt

from config import JWT_SECRET, JWT_ALGORITHM


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token. Returns the payload dict.

    Raises jwt.PyJWTError on invalid/expired tokens.
    """
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
