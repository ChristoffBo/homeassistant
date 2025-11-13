#!/usr/bin/env python3
"""
LLM Worker Process - Isolated from main Jarvis
If this crashes, only this process dies - Jarvis stays alive
Communicates with worker_manager.py via JSON-RPC on stdin/stdout
"""
import os
import sys
import json
import time
import traceback
from typing import Optional, Dict, Any

# Disable buffering for immediate IPC
sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)
sys.stderr = os.fdopen(sys.stderr.fileno(), 'w', buffering=1)

LLM = None
LLM_MODE = "none"
LOADED_MODEL_PATH = None

def log(msg: str):
    """Log to stderr so it doesn't interfere with JSON-RPC on stdout"""
    print(f"[llm_worker] {msg}", file=sys.stderr, flush=True)

def load_model(model_path: str, ctx_tokens: int, threads: int) -> Dict[str, Any]:
    """Load llama.cpp model"""
    global LLM, LLM_MODE, LOADED_MODEL_PATH
    
    try:
        # Don't reload if already loaded
        if LOADED_MODEL_PATH == model_path and LLM is not None:
            log(f"Model already loaded: {model_path}")
            return {"success": True, "message": "Model already loaded"}
        
        import llama_cpp
        
        log(f"Loading model: {model_path}")
        log(f"Context: {ctx_tokens}, Threads: {threads}")
        
        # Set environment for optimal threading
        os.environ["OMP_NUM_THREADS"] = str(threads)
        os.environ["OMP_DYNAMIC"] = "FALSE"
        os.environ["OMP_PROC_BIND"] = "TRUE"
        os.environ["OMP_PLACES"] = "cores"
        os.environ["GGML_NUM_THREADS"] = str(threads)
        
        # Load model
        LLM = llama_cpp.Llama(
            model_path=model_path,
            n_ctx=ctx_tokens,
            n_threads=threads,
            n_threads_batch=threads,
            n_batch=128,
            n_ubatch=128,
            verbose=False
        )
        
        LOADED_MODEL_PATH = model_path
        LLM_MODE = "llama"
        
        log(f"Model loaded successfully")
        return {"success": True, "message": "Model loaded"}
        
    except Exception as e:
        log(f"Model load failed: {e}")
        log(f"Traceback: {traceback.format_exc()}")
        return {"success": False, "error": str(e)}

def generate(prompt: str, max_tokens: int, temperature: float, stops: list) -> Dict[str, Any]:
    """Generate text with loaded model"""
    global LLM, LLM_MODE
    
    if LLM_MODE != "llama" or LLM is None:
        return {"success": False, "error": "Model not loaded"}
    
    try:
        log(f"Generating ({max_tokens} tokens)")
        
        result = LLM(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=0.9,
            repeat_penalty=1.10,
            stop=stops or []
        )
        
        text = result.get("choices", [{}])[0].get("text", "")
        log(f"Generated {len(text)} chars")
        
        return {"success": True, "text": text.strip()}
        
    except Exception as e:
        log(f"Generation failed: {e}")
        log(f"Traceback: {traceback.format_exc()}")
        return {"success": False, "error": str(e)}

def unload_model() -> Dict[str, Any]:
    """Unload model to free memory"""
    global LLM, LLM_MODE, LOADED_MODEL_PATH
    
    LLM = None
    LLM_MODE = "none"
    LOADED_MODEL_PATH = None
    
    log("Model unloaded")
    return {"success": True, "message": "Model unloaded"}

def handle_request(req: Dict[str, Any]) -> Dict[str, Any]:
    """Handle a single JSON-RPC request"""
    method = req.get("method")
    params = req.get("params", {})
    
    if method == "load":
        return load_model(
            params.get("model_path"),
            params.get("ctx_tokens", 4096),
            params.get("threads", 4)
        )
    
    elif method == "generate":
        return generate(
            params.get("prompt"),
            params.get("max_tokens", 128),
            params.get("temperature", 0.7),
            params.get("stops", [])
        )
    
    elif method == "unload":
        return unload_model()
    
    elif method == "ping":
        return {"success": True, "message": "pong"}
    
    else:
        return {"success": False, "error": f"Unknown method: {method}"}

def main():
    """Main worker loop - reads JSON requests from stdin, writes responses to stdout"""
    log("="*60)
    log("LLM Worker Process Starting")
    log(f"PID: {os.getpid()}")
    log("Process isolated - crashes won't affect main Jarvis")
    log("="*60)
    
    while True:
        try:
            # Read request from stdin
            line = sys.stdin.readline()
            if not line:
                log("EOF on stdin - parent died, exiting")
                break
            
            req = json.loads(line.strip())
            
            # Handle request
            response = handle_request(req)
            
            # Write response to stdout
            print(json.dumps(response), flush=True)
            
        except json.JSONDecodeError as e:
            log(f"JSON decode error: {e}")
            print(json.dumps({"success": False, "error": "Invalid JSON"}), flush=True)
            
        except KeyboardInterrupt:
            log("Interrupted - exiting")
            break
            
        except Exception as e:
            log(f"Unexpected error: {e}")
            log(f"Traceback: {traceback.format_exc()}")
            print(json.dumps({"success": False, "error": str(e)}), flush=True)
    
    log("LLM Worker Process Exiting")

if __name__ == "__main__":
    main()
