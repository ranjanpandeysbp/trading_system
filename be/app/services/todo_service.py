"""Todos — simple per-user task list with status and search."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Todo

_STATUSES = {"pending", "done"}


class TodoService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_todos(
        self, user_id: int, *, search: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        stmt = select(Todo).where(Todo.user_id == user_id)
        if status:
            if status not in _STATUSES:
                raise ValueError(f"Unknown status: {status}")
            stmt = stmt.where(Todo.status == status)
        search = (search or "").strip()
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(Todo.title.ilike(like), Todo.notes.ilike(like)))
        stmt = stmt.order_by(Todo.created_at.desc())
        result = await self.db.execute(stmt)
        return [self._todo_dict(t) for t in result.scalars().all()]

    async def create_todo(self, user_id: int, *, title: str, notes: str | None = None) -> dict[str, Any]:
        title = (title or "").strip()
        if not title:
            raise ValueError("Title cannot be empty.")
        todo = Todo(user_id=user_id, title=title, notes=(notes or "").strip() or None, status="pending")
        self.db.add(todo)
        await self.db.commit()
        await self.db.refresh(todo)
        return self._todo_dict(todo)

    async def update_todo(
        self,
        user_id: int,
        todo_id: int,
        *,
        title: str | None = None,
        notes: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        todo = await self._get_owned(user_id, todo_id)
        if not todo:
            raise ValueError("Todo not found")
        if title is not None:
            title = title.strip()
            if not title:
                raise ValueError("Title cannot be empty.")
            todo.title = title
        if notes is not None:
            todo.notes = notes.strip() or None
        if status is not None:
            if status not in _STATUSES:
                raise ValueError(f"Unknown status: {status}")
            todo.status = status
        await self.db.commit()
        await self.db.refresh(todo)
        return self._todo_dict(todo)

    async def delete_todo(self, user_id: int, todo_id: int) -> bool:
        todo = await self._get_owned(user_id, todo_id)
        if not todo:
            return False
        await self.db.delete(todo)
        await self.db.commit()
        return True

    async def _get_owned(self, user_id: int, todo_id: int) -> Todo | None:
        todo = await self.db.get(Todo, todo_id)
        if todo is None or todo.user_id != user_id:
            return None
        return todo

    @staticmethod
    def _todo_dict(t: Todo) -> dict[str, Any]:
        return {
            "id": t.id,
            "title": t.title,
            "notes": t.notes,
            "status": t.status,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
