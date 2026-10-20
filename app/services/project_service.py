import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from app.models.db import ProjectRecord, SessionLocal
from app.services.timeline_service import timeline_service
from app.services.media_service import media_service


class ProjectService:
    def create_project(self, name: str, media_id: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
        proj_id = f"proj_{uuid.uuid4().hex[:8]}"
        clean_name = (name or "Untitled Project").strip()
        db = SessionLocal()
        try:
            rec = ProjectRecord(
                project_id=proj_id,
                name=clean_name,
                media_id=media_id,
                description=description,
            )
            db.add(rec)
            db.commit()
            return {
                "project_id": proj_id,
                "name": clean_name,
                "media_id": media_id,
                "description": description,
                "created_at": rec.created_at.isoformat() if rec.created_at else datetime.now(timezone.utc).isoformat(),
            }
        finally:
            db.close()

    def list_projects(self) -> List[Dict[str, Any]]:
        db = SessionLocal()
        try:
            recs = db.query(ProjectRecord).order_by(ProjectRecord.created_at.desc()).limit(20).all()
            result = []
            for r in recs:
                # enrich with duration and segment count if media_id exists
                duration = 0.0
                revision = 0
                if r.media_id:
                    tl = timeline_service.get_timeline(r.media_id)
                    if tl:
                        duration = round(tl.total_output_duration, 2)
                        revision = tl.revision
                result.append({
                    "project_id": r.project_id,
                    "name": r.name,
                    "media_id": r.media_id,
                    "description": r.description,
                    "duration": duration,
                    "revision": revision,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                })
            return result
        finally:
            db.close()

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        db = SessionLocal()
        try:
            r = db.query(ProjectRecord).filter(ProjectRecord.project_id == project_id).first()
            if not r:
                return None
            data = {
                "project_id": r.project_id,
                "name": r.name,
                "media_id": r.media_id,
                "description": r.description,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            if r.media_id:
                manifest = media_service.get_media_manifest(r.media_id)
                tl = timeline_service.get_timeline(r.media_id)
                data["media"] = manifest.model_dump() if manifest else None
                data["timeline"] = tl.model_dump() if tl else None
            return data
        finally:
            db.close()

    def update_project_media(self, project_id: str, media_id: str) -> bool:
        return self.update_project(project_id, {"media_id": media_id}) is not None

    def update_project(self, project_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        db = SessionLocal()
        try:
            r = db.query(ProjectRecord).filter(ProjectRecord.project_id == project_id).first()
            if not r:
                return None
            if "name" in updates:
                r.name = updates["name"]
            if "media_id" in updates:
                r.media_id = updates["media_id"]
            if "description" in updates:
                r.description = updates["description"]
            r.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(r)
            return {
                "project_id": r.project_id,
                "name": r.name,
                "media_id": r.media_id,
                "description": r.description,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
        finally:
            db.close()

    def delete_project(self, project_id: str) -> bool:
        """Delete project metadata only; referenced source media remains untouched."""
        db = SessionLocal()
        try:
            record = db.query(ProjectRecord).filter(ProjectRecord.project_id == project_id).first()
            if not record:
                return False
            db.delete(record)
            db.commit()
            return True
        finally:
            db.close()

    def duplicate_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        db = SessionLocal()
        try:
            source = db.query(ProjectRecord).filter(ProjectRecord.project_id == project_id).first()
            if not source:
                return None
            name = source.name
            media_id = source.media_id
            description = source.description
        finally:
            db.close()
        return self.create_project(
            name=f"{name} copy",
            media_id=media_id,
            description=description,
        )


project_service = ProjectService()
