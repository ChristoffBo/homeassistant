#!/usr/bin/env python3
"""
Singleton Worker Manager - shared across all llm_client imports
Ensures only ONE worker process exists regardless of how many times module is imported
"""
import os
import sys
import json
import time
import subprocess
import threading
import select
from typing import Optional, Dict, Any

class WorkerManager:
    """Singleton that manages the LLM worker process"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self.process: Optional[subprocess.Popen] = None
        self.model_path: Optional[str] = None
        self.loading = False
        self.crashed = False
        self.pid = None
        
        print(f"[WorkerManager] Singleton initialized (id: {id(self)})", file=sys.stderr)
    
    def is_alive(self) -> bool:
        """Check if worker is alive"""
        if self.process is None:
            return False
        return self.process.poll() is None
    
    def start(self, model_path: str, ctx_tokens: int, threads: int) -> bool:
        """Start worker if not already running"""
        with self._lock:
            # Already running?
            if self.is_alive() and self.model_path == model_path:
                print(f"[WorkerManager] Worker already running (PID: {self.pid})", file=sys.stderr)
                return True
            
            # Another thread loading?
            if self.loading:
                print("[WorkerManager] Another thread is loading, waiting...", file=sys.stderr)
                time.sleep(0.3)
                return self.is_alive()
            
            self.loading = True
            try:
                return self._start_worker(model_path, ctx_tokens, threads)
            finally:
                self.loading = False
    
    def _start_worker(self, model_path: str, ctx_tokens: int, threads: int) -> bool:
        """Actually start the worker process"""
        worker_path = "/app/llm_worker.py"
        if not os.path.exists(worker_path):
            print(f"[WorkerManager] Worker not found: {worker_path}", file=sys.stderr)
            return False
        
        try:
            print(f"[WorkerManager] Starting worker process", file=sys.stderr)
            self.process = subprocess.Popen(
                [sys.executable, worker_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=sys.stderr,
                bufsize=1,
                universal_newlines=True
            )
            self.pid = self.process.pid
            
            print(f"[WorkerManager] Worker started (PID: {self.pid})", file=sys.stderr)
            
            # Ping test
            response = self.call("ping", {}, timeout=5.0)
            if not response or not response.get("success"):
                print("[WorkerManager] Worker ping failed", file=sys.stderr)
                self.stop()
                return False
            
            # Load model
            print(f"[WorkerManager] Loading model in worker", file=sys.stderr)
            response = self.call("load", {
                "model_path": model_path,
                "ctx_tokens": ctx_tokens,
                "threads": threads
            }, timeout=60.0)
            
            if not response or not response.get("success"):
                print(f"[WorkerManager] Model load failed", file=sys.stderr)
                self.stop()
                return False
            
            self.model_path = model_path
            print(f"[WorkerManager] Model loaded successfully", file=sys.stderr)
            return True
            
        except Exception as e:
            print(f"[WorkerManager] Error starting worker: {e}", file=sys.stderr)
            self.stop()
            return False
    
    def call(self, method: str, params: Dict[str, Any], timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """Call worker with JSON-RPC"""
        if not self.is_alive():
            return None
        
        try:
            request = json.dumps({"method": method, "params": params})
            self.process.stdin.write(request + "\n")
            self.process.stdin.flush()
            
            start = time.time()
            while time.time() - start < timeout:
                if not self.is_alive():
                    return None
                
                ready, _, _ = select.select([self.process.stdout], [], [], 0.1)
                if ready:
                    line = self.process.stdout.readline()
                    if line:
                        return json.loads(line.strip())
            
            print(f"[WorkerManager] Call timeout: {method}", file=sys.stderr)
            return None
            
        except Exception as e:
            print(f"[WorkerManager] Call failed: {e}", file=sys.stderr)
            return None
    
    def stop(self):
        """Stop worker process"""
        if self.process is None:
            return
        
        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass
        
        print(f"[WorkerManager] Worker stopped (PID: {self.pid})", file=sys.stderr)
        self.process = None
        self.model_path = None
        self.pid = None

# Global singleton instance
_worker_manager = WorkerManager()

def get_worker() -> WorkerManager:
    """Get the singleton worker manager"""
    return _worker_manager
