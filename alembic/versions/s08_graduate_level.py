"""s08 (2026-11-01): a student can be a graduate or in college, stored as grade 13.

The owner's field test: a graduate preparing for UPSC typed "mai graduate hun" and was asked
for a class from 1 to 12 three times. Grade 13 means "past class 12"; teachers' grades stay 1-12
(the parser never gives a teacher 13).

Revision ID: s08_graduate_level
Revises: s10b_child_session_language
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "s08_graduate_level"
down_revision: str | Sequence[str] | None = "s10b_child_session_language"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_users_grade_range", "users", type_="check")
    op.create_check_constraint("ck_users_grade_range", "users", "grade BETWEEN 1 AND 13")


def downgrade() -> None:
    # A graduate becomes class 12 again: the closest grade the old check allows.
    op.execute("UPDATE users SET grade = 12 WHERE grade = 13")
    op.drop_constraint("ck_users_grade_range", "users", type_="check")
    op.create_check_constraint("ck_users_grade_range", "users", "grade BETWEEN 1 AND 12")
