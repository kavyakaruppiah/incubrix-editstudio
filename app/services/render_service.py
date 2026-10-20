import json
import threading
from pathlib import Path
from typing import Dict, Optional
from app.config import settings
from app.jobs.job_manager import job_manager
from app.models.render import RenderManifest
from app.rendering.ffmpeg_renderer import render_timeline
from app.services.media_service import media_service
from app.services.timeline_service import timeline_service


class RenderService:
    def start_render_job(self, media_id: str, options: Optional[Dict[str, object]] = None) -> str:
        timeline = timeline_service.get_timeline(media_id)
        if not timeline:
            raise ValueError(f"No timeline found for media ID '{media_id}'")

        manifest = media_service.get_media_manifest(media_id)
        if not manifest:
            raise ValueError(f"No media manifest found for media ID '{media_id}'")

        cancel_event = threading.Event()

        def _do_render():
            rendered_manifest = render_timeline(
                timeline=timeline,
                media_source_path=manifest.storage_path,
                output_dir=settings.RENDER_OUTPUT_DIR,
                **(options or {}),
                cancel_event=cancel_event,
            )
            # Save manifest JSON to disk alongside output
            manifest_file = Path(rendered_manifest.output_path).with_suffix(".manifest.json")
            with open(manifest_file, "w", encoding="utf-8") as f:
                f.write(rendered_manifest.model_dump_json(indent=2))
            return rendered_manifest.model_dump()

        job_id = job_manager.submit_job("render", _do_render)
        job_manager.register_cancel_callback(job_id, cancel_event.set)
        return job_id

    def get_render_manifest_by_filename(self, filename: str) -> Optional[RenderManifest]:
        target = Path(settings.RENDER_OUTPUT_DIR) / filename
        if not target.is_file():
            return None
        manifest_file = target.with_suffix(".manifest.json")
        if manifest_file.is_file():
            with open(manifest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return RenderManifest.model_validate(data)
        return None


render_service = RenderService()
