import subprocess
import re
import threading
import time
import os
import sys

# Global reference to the tunnel process and URL
_tunnel_process = None
_tunnel_url = None
_tunnel_thread = None
_tunnel_error = None

def get_tunnel_url():
    """Returns the active tunnel URL, or None if not started."""
    global _tunnel_url
    return _tunnel_url

def set_tunnel_url(url):
    """Sets the active tunnel URL manually (e.g. from sniffer headers)."""
    global _tunnel_url
    _tunnel_url = url


def get_tunnel_error():
    """Returns any startup or runtime errors occurred, or None."""
    global _tunnel_error
    return _tunnel_error

def start_tunnel(port=8501):
    """Starts the Cloudflare tunnel in a background thread if it isn't already running."""
    global _tunnel_process, _tunnel_url, _tunnel_thread, _tunnel_error

    if _tunnel_process is not None:
        # Tunnel is already running or attempting to run
        return _tunnel_url

    def run():
        global _tunnel_process, _tunnel_url, _tunnel_error
        # Determine command: we try to run pycloudflared CLI directly
        # On some systems, the python executable might need to run it as a module: -m pycloudflared
        cmd = [sys.executable, "-m", "pycloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"]
        
        try:
            _tunnel_error = None
            _tunnel_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
            
            for line in _tunnel_process.stdout:
                # Capture rate limit or proxy/handshake errors from stdout/stderr stream
                if "429" in line or "1015" in line or "Too Many Requests" in line:
                    _tunnel_error = "Rate limit reached (429 Too Many Requests). Please wait a few minutes or change your IP (VPN)."
                elif "failed to unmarshal" in line:
                    _tunnel_error = "Rate limit reached. Try again in a few minutes or connect via VPN."
                
                match = url_pattern.search(line)
                if match:
                    _tunnel_url = match.group(0)
                    _tunnel_error = None
                    print(f"[TUNNEL] Cloudflare Tunnel successfully started: {_tunnel_url}")
                    
            _tunnel_process.wait()
            if _tunnel_process.returncode != 0 and not _tunnel_error:
                _tunnel_error = f"Tunnel exited with code {_tunnel_process.returncode}."
        except Exception as e:
            _tunnel_error = str(e)
            print(f"[TUNNEL] Error running Cloudflare Tunnel: {e}")
        finally:
            _tunnel_process = None
            _tunnel_url = None

    _tunnel_thread = threading.Thread(target=run, daemon=True)
    _tunnel_thread.start()

    # Wait up to 10 seconds for the URL to be generated
    for _ in range(20):
        if _tunnel_url or _tunnel_error:
            break
        time.sleep(0.5)

    return _tunnel_url

def stop_tunnel():
    """Stops the active Cloudflare tunnel if running."""
    global _tunnel_process, _tunnel_url, _tunnel_error
    if _tunnel_process:
        try:
            _tunnel_process.terminate()
            _tunnel_process.wait(timeout=2)
        except Exception:
            try:
                _tunnel_process.kill()
            except Exception:
                pass
        _tunnel_process = None
        _tunnel_url = None
        _tunnel_error = None
        print("[TUNNEL] Tunnel stopped.")
