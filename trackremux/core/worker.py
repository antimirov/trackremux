import threading
import time
import logging
from typing import Optional

from .queue import QueueManager, QueuedTask
from .converter import MediaConverter
from .models import OutputMode
from ..tui.progress import resolve_output_path, resolve_staging_path, atomic_finalize

logger = logging.getLogger(__name__)

class QueueWorker:
    """Background worker that processes pending tasks in the queue."""
    def __init__(self, queue_manager: QueueManager):
        self.qm = queue_manager
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.current_task: Optional[QueuedTask] = None
        self.current_process = None
        self.on_task_completed = None  # Callback for successful completion
        
        # Real-time progress state
        self.percent = 0
        self.status_line = ""
        self.total_frames = 0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self.qm.clean_stale_tasks()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        
    def stop(self):
        self._stop_event.set()
        p = self.current_process
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
            
            # Wait up to 1.5 seconds for it to exit gracefully
            start_time = time.time()
            while p.poll() is None and (time.time() - start_time) < 1.5:
                time.sleep(0.05)
                
            # If it's still running, send SIGKILL forcefully
            if p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass
                try:
                    p.wait(timeout=0.5)
                except Exception:
                    pass

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self):
        while not self._stop_event.is_set():
            task = self.qm.get_next_pending()
            if not task:
                time.sleep(1.0)
                continue
                
            self._process_task(task)

    def _process_task(self, task: QueuedTask):
        self.current_task = task
        self.percent = 0
        self.status_line = "Starting..."
        self.qm.update_task_status(task.id, "running")
        
        try:
            media_file = task.get_media_file()
            output_mode = task.get_output_mode()
            
            # Reconstruct total frames for progress
            self.total_frames = 0
            for track in media_file.tracks:
                if track.codec_type == "video" and getattr(track, "nb_frames", 0):
                    self.total_frames = max(self.total_frames, track.nb_frames)

            output_path = resolve_output_path(media_file, output_mode)
            staging_output = resolve_staging_path(output_path)
            
            from .config import AppConfig
            config = AppConfig.load()
            
            self.current_process = MediaConverter.convert(
                media_file, staging_output, task.convert_audio
            )
            task.ffmpeg_pid = self.current_process.pid
            self.qm.save()
            
            estimated_size_mb = MediaConverter.estimate_output_size(media_file, task.convert_audio) / 1024 / 1024
            
            for line in self.current_process.stdout:
                if self._stop_event.is_set():
                    break
                self._update_progress(line.strip(), media_file.duration, estimated_size_mb)
                
            if self._stop_event.is_set():
                self.qm.update_task_status(task.id, "pending")
                return
                
            self.current_process.wait()
            if self.current_process.returncode == 0:
                atomic_finalize(staging_output, output_path, output_mode)
                self.qm.update_task_status(task.id, "completed")
                if self.on_task_completed:
                    self.on_task_completed(task)
            else:
                self.qm.update_task_status(task.id, "failed", f"Process exited with code {self.current_process.returncode}")
                
        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}")
            self.qm.update_task_status(task.id, "failed", str(e))
        finally:
            self.current_task = None
            self.current_process = None

    def _update_progress(self, line: str, duration: float, estimated_size_mb: float = 0.0):
        if not line:
            return
            
        if "=" in line:
            parts = line.split("=", 1)
            if len(parts) == 2:
                key, value = [p.strip() for p in parts]
                if key == "frame" and value.isdigit() and self.total_frames > 0:
                    self.percent = min(98, int((int(value) / self.total_frames) * 100))
                elif key in ("out_time_ms", "out_time_us") and duration > 0:
                    try:
                        current_seconds = float(value) / 1_000_000.0
                        if current_seconds >= 0:
                            time_pct = int((current_seconds / duration) * 100)
                            if time_pct > self.percent:
                                self.percent = min(99, time_pct)
                    except Exception:
                        pass
                elif key == "total_size" and value.isdigit() and estimated_size_mb > 0:
                    actual_size_mb = int(value) / 1024 / 1024
                    size_pct = int((actual_size_mb / estimated_size_mb) * 100)
                    if size_pct > self.percent:
                        self.percent = min(99, size_pct)
                elif key == "progress" and value == "end":
                    self.percent = 100
        elif line.startswith("frame="):
            self.status_line = line
            if duration > 0 and "time=" in line:
                try:
                    time_str = line.split("time=")[1].split()[0]
                    if time_str != "N/A":
                        h, m, s = time_str.split(":")
                        current_seconds = float(h) * 3600 + float(m) * 60 + float(s)
                        time_pct = int((current_seconds / duration) * 100)
                        if time_pct > self.percent:
                            self.percent = min(99, time_pct)
                except Exception:
                    pass
