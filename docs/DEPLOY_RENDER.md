# Deploy IncuBrix EditStudio on Render

The app is a single Docker web service: FastAPI serves both the API and the bundled HTML/CSS/JavaScript frontend. The Docker entrypoint uses Render's `PORT` value when present and falls back to port 8000 for local Docker Compose.

## 1. Push the project to GitHub

Render deploys this project from a Git repository. Push the project to a private or public GitHub repository. Keep `.env`, uploaded media, databases, renders, virtual environments, and local model files out of Git; the repository `.gitignore` excludes these local files.

## 2. Create the Render web service

1. In Render, choose **New → Web Service** and connect the GitHub repository.
2. Select the repository root as the root directory. Render should detect the root `Dockerfile`; use the Docker runtime.
3. Set the health check path to `/api/v1/health`.
4. Choose a plan with enough CPU and RAM for FFmpeg and Faster-Whisper. Start with at least 1 CPU / 2 GB RAM for small demo videos; larger uploads and transcription can require more.
5. Attach a persistent disk mounted at `/app/data`. Choose enough space for uploaded originals, temporary render files, and exported videos; 10 GB is only a small demo starting point.
6. Create the service and wait for the Docker build and health check to finish.

Render supplies `PORT` for the web service. Do not hard-code a different public port.

## 3. Configure environment variables

Add these in the service's **Environment** page:

```text
APP_ENV=production
APP_HOST=0.0.0.0
DATABASE_URL=sqlite:////app/data/app.db
LOCAL_STORAGE_DIR=/app/data/storage
RENDER_OUTPUT_DIR=/app/data/renders
TEMP_DIR=/app/data/temp
MAX_UPLOAD_SIZE_MB=500
WHISPER_MODEL_SIZE=tiny
WHISPER_DEVICE=cpu
INSTRUCTION_PROVIDER=auto
```

Do not set `PORT` yourself; Render manages it. The container does not include a local Ollama server, so `OLLAMA_BASE_URL=http://127.0.0.1:11434` will not work in Render. To use Ollama Cloud, create an Ollama Cloud API key and add these environment variables in Render: `INSTRUCTION_PROVIDER=ollama`, `OLLAMA_BASE_URL=https://ollama.com`, `OLLAMA_MODEL` set to a cloud model available to your Ollama account, and `OLLAMA_API_KEY` set to the key as a secret. The app calls Ollama Cloud's authenticated `/api/chat` endpoint. Never commit the key to GitHub. Alternatively, use hosted Gemini by setting `INSTRUCTION_PROVIDER=gemini` and adding `GEMINI_API_KEY`; provider requests may incur charges.

The Dockerfile installs FFmpeg and fonts. The Faster-Whisper package is installed by `requirements.txt`; its tiny model may need to download on first transcription. The Ollama model used on the development machine is not packaged into the Render container.

## 4. Verify the deployed app

When Render reports the deploy is live, open the service's `onrender.com` URL. Then check:

- `/api/v1/health`
- `/api/v1/ready`
- `/docs`

Upload a short test MP4, apply an edit, and render it before uploading large media. Check Render logs if readiness reports a missing binary/model or if the instance runs out of memory or disk space.

## Storage and plan limitations

Render's default filesystem is ephemeral, so uploads, SQLite data, and renders are lost across restarts/redeploys unless they are on persistent storage. Render persistent disks are available only to paid services, and a service with a disk is limited to one instance. Free services also spin down after inactivity and do not support persistent disks. Do not use a free instance for valuable project data.

This app currently uses SQLite and local media storage. A single disk-backed instance is the simplest deployment for a demo; a multi-instance production deployment needs shared object storage and a server database instead of local SQLite.
