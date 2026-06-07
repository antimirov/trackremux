import json
import os
import threading
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
    owner_pid: Optional[int] = None
    ffmpeg_pid: Optional[int] = None
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
        self.lock = threading.RLock()
        with self.lock:
            if not queue_file_path:
                config_dir = os.path.expanduser("~/.config/trackremux")
                os.makedirs(config_dir, exist_ok=True)
                self.queue_file_path = os.path.join(config_dir, "queue.json")
            else:
                self.queue_file_path = queue_file_path
                
            self._tasks: List[QueuedTask] = []
            self.load()
            self.clean_stale_tasks()


    def load(self):
        """Load the queue from disk."""
        with self.lock:
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
        """Save the current queue to disk atomically."""
        with self.lock:
            try:
                temp_path = self.queue_file_path + ".tmp"
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump([t.to_dict() for t in self._tasks], f, indent=2)
                os.replace(temp_path, self.queue_file_path)
            except Exception as e:
                logger.error(f"Failed to save queue file: {e}")

    def add_task(self, media_file: MediaFile, output_mode: OutputMode, convert_audio: bool) -> QueuedTask:
        """Add a new task to the queue."""
        with self.lock:
            task = QueuedTask.create(media_file, output_mode, convert_audio)
            task.owner_pid = os.getpid()
            self._tasks.append(task)
            self.save()
            return task

    def get_tasks(self, status: Optional[str] = None) -> List[QueuedTask]:
        """Get tasks, optionally filtered by status."""
        with self.lock:
            if status:
                return [t for t in self._tasks if t.status == status]
            return list(self._tasks)

    def has_pending_task(self, path: str) -> bool:
        """Check if a file is already in the queue (pending or running)."""
        with self.lock:
            for t in self._tasks:
                if t.media_file_dict.get('path') == path and t.status in ("pending", "running"):
                    return True
            return False

    def get_next_pending(self) -> Optional[QueuedTask]:
        """Get the next pending task, if any, that belongs to this instance or is abandoned."""
        with self.lock:
            my_pid = os.getpid()
            for t in self._tasks:
                if t.status in ("pending", "running"):
                    # If it's a running task but the owner process is dead, 
                    # we must have crashed or been force-quit. 
                    # Before adopting, kill the orphaned ffmpeg process if it exists.
                    if t.status == "running" and t.owner_pid is not None and not self._is_owner_alive(t.owner_pid):
                        if t.ffmpeg_pid is not None and self._is_pid_running(t.ffmpeg_pid):
                            try:
                                logger.info(f"Killing orphaned ffmpeg process {t.ffmpeg_pid} for task {t.id}")
                                os.kill(t.ffmpeg_pid, 9) # SIGKILL
                            except OSError:
                                pass
                        
                        t.status = "pending"
                        t.owner_pid = my_pid
                        t.ffmpeg_pid = None
                        self.save()
                        return t
                        
                    if t.status == "pending":
                        # Take task if:
                        # 1. We own it
                        # 2. It has no owner (legacy)
                        # 3. The owner is dead
                        if t.owner_pid is None or t.owner_pid == my_pid or not self._is_owner_alive(t.owner_pid):
                            # If it's abandoned, we take ownership
                            if t.owner_pid != my_pid:
                                t.owner_pid = my_pid
                                self.save()
                            return t
            return None

    def _is_pid_running(self, pid: int) -> bool:
        """Check if a process is still running."""
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _is_owner_alive(self, pid: int) -> bool:
        """Check if the owner process is still alive and is a Python/trackremux process."""
        if pid == os.getpid():
            return True
        import subprocess
        try:
            cmd = ["ps", "-p", str(pid), "-o", "command="]
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
            output_lower = output.lower()
            return "python" in output_lower or "trackremux" in output_lower
        except Exception:
            # Fallback to standard process check
            return self._is_pid_running(pid)

    def clean_stale_tasks(self):
        """Reset any tasks marked as running that belong to dead or non-trackremux processes,
        or that belong to our own PID from a previous launch on startup."""
        with self.lock:
            my_pid = os.getpid()
            changed = False
            for t in self._tasks:
                if t.status == "running":
                    # On startup, we are not running any tasks, so if it has our PID, it's stale.
                    # If it belongs to another PID, check if that PID is alive and is a trackremux process.
                    if t.owner_pid is None or t.owner_pid == my_pid or not self._is_owner_alive(t.owner_pid):
                        if t.ffmpeg_pid is not None and self._is_pid_running(t.ffmpeg_pid):
                            try:
                                logger.info(f"Killing orphaned ffmpeg process {t.ffmpeg_pid} for task {t.id}")
                                os.kill(t.ffmpeg_pid, 9)
                            except OSError:
                                pass
                        logger.info(f"Resetting stale running task {t.id} to pending")
                        t.status = "pending"
                        t.owner_pid = None
                        t.ffmpeg_pid = None
                        changed = True
            if changed:
                self.save()


    def update_task_status(self, task_id: str, status: str, error_message: Optional[str] = None):
        """Update a task's status and optionally its error message."""
        with self.lock:
            for t in self._tasks:
                if t.id == task_id:
                    t.status = status
                    if error_message is not None:
                        t.error_message = error_message
                    if status in ("completed", "failed"):
                        t.ffmpeg_pid = None
                        t.owner_pid = None
                    elif status == "pending":
                        t.ffmpeg_pid = None
                    self.save()
                    return
                    
    def remove_task(self, task_id: str):
        """Remove a task from the queue."""
        with self.lock:
            self._tasks = [t for t in self._tasks if t.id != task_id]
            self.save()
            
    def clear_completed(self):
        """Remove all completed and failed tasks."""
        with self.lock:
            self._tasks = [t for t in self._tasks if t.status in ("pending", "running")]
            self.save()
