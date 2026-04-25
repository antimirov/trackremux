import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime
from uuid import uuid4
import logging

from .models import MediaFile, Track, OutputMode

logger = logging.getLogger(__name__)

@dataclass
class QueuedTask:
    """Represents a single remux operation in the queue."""
    id: str
    media_file_dict: Dict[str, Any]
    output_mode: str
    convert_audio: bool
    status: str = "pending"  # pending, running, completed, failed
    added_at: str = field(default_factory=lambda: datetime.now().isoformat())
    error_message: Optional[str] = None

    @classmethod
    def create(cls, media_file: MediaFile, output_mode: OutputMode, convert_audio: bool) -> "QueuedTask":
        return cls(
            id=str(uuid4()),
            media_file_dict=asdict(media_file),
            output_mode=output_mode.value,
            convert_audio=convert_audio
        )

    def get_media_file(self) -> MediaFile:
        """Reconstruct the MediaFile object from the dictionary."""
        tracks = []
        for track_dict in self.media_file_dict.get('tracks', []):
            tracks.append(Track(**track_dict))
            
        kwargs = self.media_file_dict.copy()
        kwargs['tracks'] = tracks
        return MediaFile(**kwargs)
        
    def get_output_mode(self) -> OutputMode:
        return OutputMode(self.output_mode)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QueuedTask":
        return cls(**data)


class QueueManager:
    """Manages the persistent task queue on disk."""
    def __init__(self, queue_file_path: Optional[str] = None):
        if not queue_file_path:
            config_dir = os.path.expanduser("~/.config/trackremux")
            os.makedirs(config_dir, exist_ok=True)
            self.queue_file_path = os.path.join(config_dir, "queue.json")
        else:
            self.queue_file_path = queue_file_path
            
        self._tasks: List[QueuedTask] = []
        self.load()

    def load(self):
        """Load the queue from disk."""
        if not os.path.exists(self.queue_file_path):
            self._tasks = []
            return

        try:
            with open(self.queue_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._tasks = [QueuedTask.from_dict(t) for t in data]
        except Exception as e:
            logger.error(f"Failed to load queue file: {e}")
            self._tasks = []

    def save(self):
        """Save the current queue to disk."""
        try:
            with open(self.queue_file_path, 'w', encoding='utf-8') as f:
                json.dump([t.to_dict() for t in self._tasks], f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save queue file: {e}")

    def add_task(self, media_file: MediaFile, output_mode: OutputMode, convert_audio: bool) -> QueuedTask:
        """Add a new task to the queue."""
        task = QueuedTask.create(media_file, output_mode, convert_audio)
        self._tasks.append(task)
        self.save()
        return task

    def get_tasks(self, status: Optional[str] = None) -> List[QueuedTask]:
        """Get tasks, optionally filtered by status."""
        if status:
            return [t for t in self._tasks if t.status == status]
        return list(self._tasks)

    def get_next_pending(self) -> Optional[QueuedTask]:
        """Get the next pending task, if any."""
        for t in self._tasks:
            if t.status == "pending":
                return t
        return None

    def update_task_status(self, task_id: str, status: str, error_message: Optional[str] = None):
        """Update a task's status and optionally its error message."""
        for t in self._tasks:
            if t.id == task_id:
                t.status = status
                if error_message is not None:
                    t.error_message = error_message
                self.save()
                return
                
    def remove_task(self, task_id: str):
        """Remove a task from the queue."""
        self._tasks = [t for t in self._tasks if t.id != task_id]
        self.save()
        
    def clear_completed(self):
        """Remove all completed and failed tasks."""
        self._tasks = [t for t in self._tasks if t.status in ("pending", "running")]
        self.save()
