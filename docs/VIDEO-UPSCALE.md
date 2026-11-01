# Standalone video upscaling

H3 Studio has an **AI 超分** tab that processes ordinary videos independently of H3 model generation.

## Usage

1. Start H3cApp 0.6.8 or newer on the **same Mac** as H3 Studio (tested API target: H3cApp 0.7.3).
2. In H3 Studio, select **AI 超分** and upload an MP4, MOV or M4V (up to 1 GiB).
3. Choose a method and scale, then select **上传并开始超分**.
4. Follow progress in the job list and download the enhanced MP4 when finished. The original is preserved separately.

Methods: Real-ESRGAN General (real footage), Real-ESRGAN Anime (illustration and animation), MetalFX (fast, edge-preserving), and Standard (ordinary high-quality scaling). H3cApp bundles the Real-ESRGAN models. There is no separate H3 model requirement for processing a video, but the **H3cApp application must be running**. No extra models are downloaded by this feature. The backend also accepts SwiftVR when installed/configured separately, although the simple UI intentionally only offers the four built-in methods.

Scale: 1.5×, 2×, 3× or 4×, so long as the resulting width and height are each at most **4096 pixels**. GPU usage, processing time and possible AI-generated artifacts rise with resolution.

## Privacy and limits

- All files remain under the application's private `data/upscale/<job-id>/` directory (or `H3STUDIO_DATA`). No user-supplied file path is ever forwarded to H3cApp.
- H3 Studio requires login for uploading, starting, cancelling, previewing and downloading. CSRF and Origin checks still apply.
- Uploads are streamed to disk with a 1 GiB limit. Video container structure and dimensions are checked using ffprobe. There is no automatic removal of processed videos; delete them from the job list to reclaim space.
- At most one H3 Studio upscale task runs at a time. H3cApp may reject a request when its engine is busy; the error appears in the job list. This operation may compete for GPU time with video generation.
- If H3 Studio restarts mid-job, the record is marked interrupted instead of claiming success. Check that H3cApp has finished the prior task before starting another.
- AI upscaling is not a reliable reconstruction of lost real-world detail. Keep the original, particularly when faces matter.
- The H3cApp API requires absolute paths on the Mac running H3cApp. Using a remote H3cApp instance on a *different* machine is not supported by this feature.

Engine API reference: https://github.com/JunzoKamahara/H3cApp/blob/main/API.md

## Developer endpoints

All routes below require an authenticated H3 Studio session.

- `GET /api/upscale/methods` — H3cApp availability.
- `POST /api/upscale/upload` — multipart file; returns a random upload/job ID.
- `POST /api/upscale/jobs/{id}/start` — JSON `{"method":"realESRGANGeneral","scale":2}`.
- `GET /api/upscale/jobs` — recent jobs and status.
- `POST /api/upscale/jobs/{id}/cancel` — request H3cApp cancellation of this H3 Studio job.
- `GET /api/upscale/jobs/{id}/source|enhanced` — video preview; `?download=1` for attachment.
- `DELETE /api/upscale/jobs/{id}` — remove the saved media and job record.
