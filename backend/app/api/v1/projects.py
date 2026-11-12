"""User-owned project endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import CurrentUser, SessionDependency
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectPublic

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectPublic, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    user: CurrentUser,
    session: SessionDependency,
) -> Project:
    """Create a project owned by the authenticated account."""

    project = Project(
        owner_id=user.id,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


@router.get("", response_model=list[ProjectPublic])
async def list_projects(user: CurrentUser, session: SessionDependency) -> list[Project]:
    """List only projects owned by the authenticated account."""

    result = await session.scalars(
        select(Project)
        .where(Project.owner_id == user.id)
        .order_by(Project.created_at.desc(), Project.id)
    )
    return list(result.all())


@router.get("/{project_id}", response_model=ProjectPublic)
async def read_project(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDependency,
) -> Project:
    """Retrieve a project only when it belongs to the authenticated account."""

    project = await session.scalar(
        select(Project).where(Project.id == project_id, Project.owner_id == user.id)
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project
