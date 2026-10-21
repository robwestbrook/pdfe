from sqlalchemy import Engine, ForeignKey, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class FileRecord(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]


class Revision(Base):
    __tablename__ = "revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id"))
    number: Mapped[int]


def make_engine(url: str) -> Engine:
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine
