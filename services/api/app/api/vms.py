from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Device, VirtualMachine
from app.schemas.schemas import VmCreate, VmOut
from app.services.execution import queue_command

router = APIRouter()

HYPERVISORS = {"hyper-v", "libvirt", "vmware", "qemu", "other"}

COMMANDS = {
    "hyper-v": {
        "start": lambda n: f"powershell -Command \"Start-VM -Name '{n}'\"",
        "stop": lambda n: f"powershell -Command \"Stop-VM -Name '{n}' -Force\"",
        "restart": lambda n: f"powershell -Command \"Restart-VM -Name '{n}' -Force\"",
        "scan": "powershell -Command \"Get-VM | Select-Object Name,State | ConvertTo-Json\"",
    },
    "libvirt": {
        "start": lambda n: f"virsh start {n}",
        "stop": lambda n: f"virsh shutdown {n}",
        "restart": lambda n: f"virsh reboot {n}",
        "scan": "virsh list --all --name",
    },
    "vmware": {
        "start": lambda n: f'vim-cmd vmsvc/power.on "{n}"',
        "stop": lambda n: f'vim-cmd vmsvc/power.off "{n}"',
        "restart": lambda n: f'vim-cmd vmsvc/power.reboot "{n}"',
        "scan": "vim-cmd vmsvc/getallvms",
    },
    "qemu": {
        "start": lambda n: f"virsh start {n}",
        "stop": lambda n: f"virsh shutdown {n}",
        "restart": lambda n: f"virsh reboot {n}",
        "scan": "virsh list --all --name",
    },
    "other": {
        "start": lambda n: f"echo start {n}",
        "stop": lambda n: f"echo stop {n}",
        "restart": lambda n: f"echo restart {n}",
        "scan": "echo no-scan",
    },
}


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="org scope mismatch")


def _require_admin(user) -> None:
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")


@router.get("", response_model=list[VmOut])
def list_vms(org_id: int, hypervisor: str | None = None, host_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    q = db.query(VirtualMachine).filter(VirtualMachine.org_id == org_id)
    if hypervisor:
        q = q.filter(VirtualMachine.hypervisor == hypervisor)
    if host_id:
        q = q.filter(VirtualMachine.host_id == host_id)
    return q.order_by(VirtualMachine.name.asc()).all()


@router.post("", response_model=VmOut, status_code=201)
def register_vm(payload: VmCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, payload.org_id)
    host = db.query(Device).filter(Device.id == payload.host_id, Device.org_id == payload.org_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="host device not found")
    if payload.hypervisor not in HYPERVISORS:
        raise HTTPException(status_code=400, detail=f"invalid hypervisor: {payload.hypervisor}")
    vm = VirtualMachine(org_id=payload.org_id, host_id=payload.host_id, name=payload.name, hypervisor=payload.hypervisor, state=payload.state, vcpu=payload.vcpu, memory_mb=payload.memory_mb, notes=payload.notes)
    db.add(vm)
    db.commit()
    db.refresh(vm)
    emit(db, "vm.registered", {"id": vm.id, "name": vm.name, "hypervisor": vm.hypervisor}, actor_of(user), {"org_id": payload.org_id}, {"reason": "VM inventory"})
    return vm


def _control(db: Session, user, vm_id: int, action: str) -> dict:
    vm = db.query(VirtualMachine).filter(VirtualMachine.id == vm_id).first()
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    _scope(user, vm.org_id)
    _require_admin(user)
    cmd = COMMANDS.get(vm.hypervisor, COMMANDS["other"]).get(action)
    if not cmd:
        raise HTTPException(status_code=400, detail="unsupported action")
    run = queue_command(db, vm.org_id, vm.host_id, cmd(vm.name), actor_of(user))
    emit(db, f"vm.{action}", {"vm_id": vm.id, "name": vm.name, "run_id": run.id}, actor_of(user), {"org_id": vm.org_id}, {"reason": "VM control"})
    return {"vm_id": vm.id, "action": action, "run_id": run.id, "command": cmd(vm.name)}


@router.post("/{vm_id}/start")
def start_vm(vm_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _control(db, user, vm_id, "start")


@router.post("/{vm_id}/stop")
def stop_vm(vm_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _control(db, user, vm_id, "stop")


@router.post("/{vm_id}/restart")
def restart_vm(vm_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _control(db, user, vm_id, "restart")


@router.post("/scan")
def scan_hosts(host_id: int, org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Queue a hypervisor VM enumeration command on the host (output appears in Scripts → run history)."""
    _scope(user, org_id)
    _require_admin(user)
    host = db.query(Device).filter(Device.id == host_id, Device.org_id == org_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="host device not found")
    # Use libvirt as a safe default enumeration; operator can adjust per host.
    run = queue_command(db, org_id, host_id, "virsh list --all --name 2>/dev/null || powershell -Command \"Get-VM | Select-Object Name,State\"", actor_of(user))
    emit(db, "vm.scan", {"host_id": host_id, "run_id": run.id}, actor_of(user), {"org_id": org_id}, {"reason": "VM enumeration"})
    return {"host_id": host_id, "run_id": run.id}
