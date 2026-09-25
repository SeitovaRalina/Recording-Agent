import uuid


def test_locked_review_query_is_valid_for_postgres_for_update() -> None:
    from sqlalchemy.dialects import postgresql

    from app.services.reviews import locked_review_statement

    sql = str(locked_review_statement(uuid.uuid4()).compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE" in sql
    assert "LEFT OUTER JOIN" not in sql
