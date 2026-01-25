import collections
import threading
import time
import os
from .probe import MediaProbe

class GlobalScanner:
    def __init__(self):
        self.priority_queue = collections.deque()
        self.background_queue = collections.deque()
        self.processed_files = set()  # To avoid re-scanning identical files if needed, currently loose
        self.queue_lock = threading.Lock()
        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def add_priority_items(self, items, clear_priority=False, force=False):
        """
        Add items to the FRONT of the priority queue. 
        items: list of tuples (file_path, callback)
        clear_priority: If True, remove all pending priority tasks first (good for view switching).
        force: If True, re-scan even if already processed.
        """
        with self.queue_lock:
            if clear_priority:
                self.priority_queue.clear()
            
            if force:
                for path, _ in items:
                    self.processed_files.discard(path)
                
            # We reverse to keep the order within the added batch correct when pushing to front
            # e.g. [A, B, C] -> push C, then B, then A -> Queue: [A, B, C, ...]
            for item in reversed(items):
                # Optionally check if already in queue to move it up? 
                # For simplicity, we just add. If duplicates exist, they get processed (maybe redundant but safe)
                self.priority_queue.appendleft(item)

    def add_background_items(self, items, force=False):
        """
        Add items to the BACK of the queue.
        items: list of tuples (file_path, callback)
        force: If True, re-scan even if already processed.
        """
        with self.queue_lock:
            if force:
                for path, _ in items:
                    self.processed_files.discard(path)

            for item in items:
                self.background_queue.append(item)

    def stop(self):
        self.running = False
        if self.thread.is_alive():
            self.thread.join(timeout=1.0)

    def _worker(self):
        while self.running:
            task = None
            is_priority = False
            
            with self.queue_lock:
                if self.priority_queue:
                    task = self.priority_queue.popleft()
                    is_priority = True
                elif self.background_queue:
                    task = self.background_queue.popleft()
            
            if not task:
                time.sleep(0.1)
                continue

            file_path, callback = task
            
            # Check if already processed to avoid re-work
            # This allows safe re-submission for prioritization
            # BUT: If it's a priority task, we might want to force check or just rely on processed_files?
            # If user scrolls back to already processed file, we shouldn't re-scan.
            if file_path in self.processed_files:
                continue
            
            if not os.path.exists(file_path):
                continue

            try:
                # Probe the file
                # This is blocking and can be slow
                media = MediaProbe.probe(file_path)
                
                # Signal completion
                if callback:
                    callback(file_path, media)
                
                self.processed_files.add(file_path)
            except Exception:
                # pass or log
                pass
