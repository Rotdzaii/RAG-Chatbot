from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings


engine = create_engine(settings.database_url, pool_pre_ping=True)


class Base(DeclarativeBase):
    pass
