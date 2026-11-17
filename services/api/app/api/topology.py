"""Service topology: declared and trace-observed dependencies with impact analysis."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Device, ServiceDependency, ServiceNode
from app.services import topology

router = APIRouter()


class ServiceIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    device_id: int | None = Field(default=None, gt=0)
    description: str = Field(default="", max_length=2000)


class DependencyIn(BaseModel):
    source_id: int = Field(gt=0)
    target_id: int = Field(gt=0)


def _writer(user) -> None:
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")


def _node(db: Session, user, node_id: int) -> ServiceNode:
    node = db.query(ServiceNode).filter(ServiceNode.id == node_id, ServiceNode.org_id == user.org_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="service not found in organization")
    return node


@router.get("")
def get_graph(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return topology.graph(db, user.org_id)


@router.post("/services", status_code=201)
def create_service(payload: ServiceIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    name = payload.name.strip()
    if db.query(ServiceNode).filter(ServiceNode.org_id == user.org_id, ServiceNode.name == name).first():
        raise HTTPException(status_code=409, detail="a service with this name already exists")
    if payload.device_id and not db.query(Device).filter(Device.id == payload.device_id, Device.org_id == user.org_id).first():
        raise HTTPException(status_code=404, detail="device not found in organization")
    node = ServiceNode(org_id=user.org_id, name=name, device_id=payload.device_id, description=payload.description)
    db.add(node)
    db.flush()
    node_id = node.id
    emit(db, "topology.service.created", {"service_id": node_id, "name": name, "device_id": payload.device_id},
        actor_of(user), {"org_id": user.org_id}, {"reason": "declare service"})
    return {"id": node_id, "name": name, "device_id": payload.device_id, "description": payload.description}


@router.patch("/services/{node_id}")
def update_service(node_id: int, payload: ServiceIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    node = _node(db, user, node_id)
    if payload.device_id and not db.query(Device).filter(Device.id == payload.device_id, Device.org_id == user.org_id).first():
        raise HTTPException(status_code=404, detail="device not found in organization")
    node.device_id = payload.device_id
    node.description = payload.description
    emit(db, "topology.service.updated", {"service_id": node_id, "device_id": payload.device_id},
        actor_of(user), {"org_id": user.org_id}, {"reason": "link service to endpoint"})
    return {"id": node_id, "device_id": payload.device_id, "description": payload.description}


@router.delete("/services/{node_id}")
def delete_service(node_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    node = _node(db, user, node_id)
    name = node.name
    db.query(ServiceDependency).filter(ServiceDependency.org_id == user.org_id,
        (ServiceDependency.source_id == node_id) | (ServiceDependency.target_id == node_id)).delete(synchronize_session=False)
    db.delete(node)
    emit(db, "topology.service.deleted", {"service_id": node_id, "name": name},
        actor_of(user), {"org_id": user.org_id}, {"reason": "remove service"})
    return {"ok": True}


@router.post("/dependencies", status_code=201)
def create_dependency(payload: DependencyIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    if payload.source_id == payload.target_id:
        raise HTTPException(status_code=422, detail="a service cannot depend on itself")
    source = _node(db, user, payload.source_id)
    target = _node(db, user, payload.target_id)
    if db.query(ServiceDependency).filter(ServiceDependency.org_id == user.org_id,
            ServiceDependency.source_id == source.id, ServiceDependency.target_id == target.id).first():
        raise HTTPException(status_code=409, detail="dependency already recorded")
    edge = ServiceDependency(org_id=user.org_id, source_id=source.id, target_id=target.id, origin="manual")
    db.add(edge)
    db.flush()
    edge_id = edge.id
    emit(db, "topology.dependency.created", {"dependency_id": edge_id, "source": source.name, "target": target.name, "origin": "manual"},
        actor_of(user), {"org_id": user.org_id}, {"reason": "declare dependency"})
    return {"id": edge_id, "source_id": payload.source_id, "target_id": payload.target_id, "origin": "manual"}


@router.delete("/dependencies/{edge_id}")
def delete_dependency(edge_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    edge = db.query(ServiceDependency).filter(ServiceDependency.id == edge_id, ServiceDependency.org_id == user.org_id).first()
    if not edge:
        raise HTTPException(status_code=404, detail="dependency not found in organization")
    db.delete(edge)
    emit(db, "topology.dependency.deleted", {"dependency_id": edge_id},
        actor_of(user), {"org_id": user.org_id}, {"reason": "remove dependency"})
    return {"ok": True}


@router.get("/impact/{node_id}")
def get_impact(node_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _node(db, user, node_id)
    return topology.impact(db, user.org_id, node_id)
