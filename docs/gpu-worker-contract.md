# Self-hosted GPU worker contract

The FastAPI backend owns user authentication, scene/job persistence, reference
asset authorization, cancellation, retry policy, and generated-file storage.
The Next.js frontend only submits and polls backend jobs; it never calls the
GPU worker directly. The worker is an independently deployed HTTP service and
is optional. No paid provider is required.

## Configure the backend

Set these server-side environment variables:

- `GENERATION_WORKER_URL`: base URL for the private worker service.
- `GENERATION_WORKER_API_TOKEN`: optional bearer token for worker requests.
- `GENERATION_WORKER_TIMEOUT_SECONDS`: per-request HTTP timeout.
- `GENERATION_WORKER_MAX_OUTPUT_BYTES`: maximum MP4 download size.
- `PUBLIC_API_BASE_URL`: URL the GPU worker can use to fetch signed reference
  images from the backend.
- `GENERATION_MODEL_VERSION`: operator-reported default model version.
- `GENERATION_MODEL_NAME`, `GENERATION_MODEL_REPOSITORY`,
  `GENERATION_MODEL_LICENSE`, and `GENERATION_MODEL_COMMERCIAL_USE_PERMITTED`:
  metadata for the selected self-hosted model. Commercial use defaults to
  disabled and should only be enabled after verifying the model and weight
  licenses.
- `GENERATION_MODEL_GPU_REQUIREMENT`, `GENERATION_MODEL_SUPPORTED_LANGUAGES`,
  `GENERATION_MODEL_GENERATION_MODES`, and
  `GENERATION_MODEL_INSTALLATION_INSTRUCTIONS`: registry documentation for the
  manually installed model.

Keep the worker on a private network or use HTTPS and a strong token. The
backend does not install or download model weights. The operator must install
weights separately and verify the source, license, commercial-use terms,
hardware needs, and attribution requirements before use.

## Worker API

The backend sends JSON to `POST /api/v1/jobs`:

```json
{
  "client_job_id": "backend-job-uuid",
  "scene": {
    "project_id": "project-uuid",
    "scene_id": "scene-uuid",
    "generation_mode": "image_to_video",
    "prompt": "A slow camera move across the winter garden",
    "model_id": "operator-configured",
    "model_name": "Operator-configured self-hosted model",
    "model_version": "operator-managed",
    "model_license": "Not declared; operator must verify the model card and weights.",
    "commercial_use_permitted": false,
    "generation_settings": {"resolution": "1280x720", "frame_rate": 24},
    "reference_assets": [
      {
        "asset_id": "image-uuid",
        "role": "first_frame",
        "download_url": "short-lived signed backend URL"
      }
    ]
  }
}
```

Return `202` (or `200`) with `{"job_id":"worker-job-id"}`. Reference URLs are
created at actual worker submission time and signed for five minutes, limited
to a specific image and project, and served
with `Cache-Control: no-store`; workers must not retain or redistribute them.
For text-to-video, the references list may be empty.

The backend polls `GET /api/v1/jobs/{job_id}`. Return one of the persisted job
states and a 0–100 progress value:

```json
{
  "status": "processing",
  "progress": 37,
  "output_metadata": {
    "model_version": "worker-reported-version"
  },
  "preview_only": false,
  "preview_label": null,
  "error_message": null,
  "output_available": false
}
```

Allowed states are `queued`, `processing`, `completed`, `failed`, and
`cancelled`. For successful real generation, return `completed`,
`output_available: true`, and relevant output metadata. The backend then
downloads the output from `GET /api/v1/jobs/{job_id}/output`. That endpoint
must stream `video/mp4`; the backend enforces its configured byte limit and
validates the file with FFprobe before storing it as a user-owned project
asset. Do not return an arbitrary output URL: the fixed output endpoint avoids
turning the backend into an open URL fetcher.

Handle `POST /api/v1/jobs/{job_id}/cancel` idempotently and return success when
cancellation is accepted. The backend reports cancellation after the worker
acknowledges it. Failed or cancelled jobs can be retried by the user up to the
persisted retry limit; a retry resubmits the saved scene/settings snapshot.

## Development mock and model registry

The development mock is enabled only with `ENABLE_MOCK_SCENE_PREVIEW=true` in
development. It exercises submission, polling, progress, retry, and
cancellation without GPU hardware. Its completion is marked
`preview_only: true`, creates no media, and cannot be assembled into a video.
The `/api/v1/content/models` registry marks operator-configured model licensing
as unverified and commercial use as not permitted until the operator supplies
verified terms. The registry does not recommend a particular weight set.
