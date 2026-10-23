from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
import yt_dlp
import imageio_ffmpeg
import os
import subprocess
import uuid
import urllib.parse

app = FastAPI()
FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Media Downloader</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
        .card { background: #1e293b; padding: 2rem; border-radius: 1rem; width: 100%; max-width: 400px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
        h1 { font-size: 1.5rem; margin-bottom: 1.5rem; text-align: center; color: #3b82f6; }
        .input-group { margin-bottom: 1rem; }
        input[type="text"] { width: 100%; padding: 0.75rem; background: #334155; border: none; border-radius: 0.5rem; color: white; outline: none; box-sizing: border-box; }
        input[type="text"]:focus { border: 2px solid #3b82f6; }
        .radio-group { display: flex; gap: 1rem; margin-bottom: 1.5rem; }
        .radio-group label { display: flex; align-items: center; gap: 0.5rem; cursor: pointer; font-size: 0.9rem; }
        button { width: 100%; padding: 0.75rem; background: #3b82f6; color: white; border: none; border-radius: 0.5rem; font-weight: 600; cursor: pointer; transition: 0.2s; }
        button:hover { background: #2563eb; }
        button:disabled { background: #475569; cursor: not-allowed; }
        .status { margin-top: 1rem; text-align: center; font-size: 0.875rem; color: #94a3b8; }
        .spinner { display: none; margin: 0 auto 1rem; width: 2rem; height: 2rem; border: 3px solid #334155; border-top-color: #3b82f6; border-radius: 50%; animation: spin 1s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .error { color: #ef4444; margin-top: 1rem; text-align: center; font-size: 0.875rem; }
    </style>
</head>
<body>
    <div class="card">
        <h1>Fetch Media</h1>
        <div class="input-group">
            <input type="text" id="url" placeholder="Dán link YouTube / TikTok...">
        </div>
        <div class="radio-group">
            <label><input type="radio" name="format" value="mp4" checked> MP4 (Video)</label>
            <label><input type="radio" name="format" value="mp3"> MP3 (Audio)</label>
        </div>
        <button id="btn" onclick="download()">Tải Xuống</button>
        <div class="spinner" id="spinner"></div>
        <div class="status" id="status"></div>
        <div class="error" id="error"></div>
    </div>

    <script>
        async function download() {
            const url = document.getElementById('url').value.trim();
            const format = document.querySelector('input[name="format"]:checked').value;
            const btn = document.getElementById('btn');
            const spinner = document.getElementById('spinner');
            const status = document.getElementById('status');
            const error = document.getElementById('error');

            if (!url) {
                error.textContent = "Vui lòng nhập URL.";
                return;
            }

            btn.disabled = true;
            spinner.style.display = 'block';
            status.textContent = "Đang xử lý... Quá trình này có thể mất vài phút.";
            error.textContent = "";

            try {
                const res = await fetch('/api/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url, format })
                });

                if (!res.ok) {
                    const errData = await res.json();
                    throw new Error(errData.detail || 'Tải thất bại');
                }

                const blob = await res.blob();
                
                const disposition = res.headers.get('Content-Disposition');
                let filename = 'download.' + (format === 'mp3' ? 'mp3' : 'mp4');
                if (disposition && disposition.includes("filename*=UTF-8''")) {
                    filename = decodeURIComponent(disposition.split("filename*=UTF-8''")[1]);
                }

                const downloadUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = downloadUrl;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                a.remove();
                
                status.textContent = "Hoàn tất! Kiểm tra thư mục tải xuống của bạn.";
            } catch (err) {
                error.textContent = err.message;
                status.textContent = "";
            } finally {
                btn.disabled = false;
                spinner.style.display = 'none';
            }
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_CONTENT

def cleanup_files(*paths):
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

@app.post("/api/download")
async def download(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        url = data.get("url")
        fmt = data.get("format", "mp4")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not url:
        raise HTTPException(status_code=400, detail="Missing URL")

    # Thư mục /tmp là thư mục duy nhất được phép ghi trên Render Web Service
    out_dir = "/tmp"
    unique_id = str(uuid.uuid4())[:8]
    
    ydl_opts = {
        "outtmpl": f"{out_dir}/{unique_id}_%(title).50B.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "ffmpeg_location": FFMPEG_PATH,
        "noplaylist": True,
        "restrictfilenames": True,
        # --- THÊM 2 DÒNG NÀY ---
        "impersonate": "chrome", # Vượt Cloudflare TLS check
        "extractor_args": {
            "tiktok": {
                "api_hostname": ["api16-normal-c-useast1a.tiktokv.com"]
            }
        }
        # ------------------------
    }
    
    if fmt == "mp3":
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    else:
        ydl_opts["format"] = "bestvideo[vcodec^=avc1]+bestaudio/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
        ydl_opts["merge_output_format"] = "mp4"
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if fmt == "mp3":
                filename = os.path.splitext(filename)[0] + ".mp3"
            else:
                filename = os.path.splitext(filename)[0] + ".mp4"
                if not os.path.exists(filename):
                    base = os.path.splitext(filename)[0]
                    for ext in [".mkv", ".webm"]:
                        if os.path.exists(base + ext):
                            filename = base + ext
                            break

            if not os.path.exists(filename):
                raise Exception("File not found after download")

            # Xử lý transcode H264 nếu là video
            if fmt == "mp4":
                base = os.path.splitext(filename)[0]
                out_h264 = base + "_h264.mp4"
                cmd = [
                    FFMPEG_PATH, "-y", "-i", filename,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "128k", "-ac", "2",
                    "-movflags", "+faststart", "-pix_fmt", "yuv420p",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    out_h264
                ]
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if os.path.exists(filename) and filename != out_h264:
                    os.remove(filename)
                filename = out_h264

            ext = os.path.splitext(filename)[1]
            raw_title = info.get("title", "download")
            safe_title = "".join(c for c in raw_title if c.isalnum() or c in " ._-").strip()
            if not safe_title:
                safe_title = "download"
            download_name = safe_title + ext
            encoded_name = urllib.parse.quote(download_name)

            # Xoá file sau khi response đã gửi xong
            background_tasks.add_task(cleanup_files, filename)

            return FileResponse(
                filename,
                media_type="application/octet-stream",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"}
            )

    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"Download failed: {str(e)}")
    except subprocess.CalledProcessError:
        raise HTTPException(status_code=500, detail="FFmpeg transcode failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
