# The Fast INT8 cache

H3cApp can pre-quantise a model's DiT weights into an on-disk **INT8 cache** (M5-class GPUs). Generation then reads that cache instead of keeping the full weights resident.

* The cache is built **per model**, inside H3cApp (Advanced Settings → Compute mode → *Build Cache…*). It lives in `~/Library/Application Support/H3cApp/cache/<model UUID>/`.
* It is tied to the exact weights it was built from; H3cApp rebuilds or refuses it if the weights change.
* H3 Studio only *reads* the state (via `GET /api/models/detail`) and uses it: a model shows **cache built / not built**, and "Fast INT8" is offered only when it is built.
* Building can take from seconds to minutes. **While it is being built H3cApp may already report "ok" with a partly written file**; wait until the file size stops changing before trusting it. H3 Studio treats a cache as usable only when H3cApp says it is built *at job start*.
* Disk: in the author's setup each cache was about 19 GB regardless of the DiT precision (it depends on tensor shapes). Check your own free space first.

## One set of measurements (not a promise)
Author's machine: M5 Ultra (64-core GPU), 96 GB, H3cApp 0.7.3, 672×384, 5 s, 20 steps, same seed and prompt, Q8 DiT:

| | Resident | INT8 cache |
|---|---|---|
| total time (two runs each) | 69.3 s / 60.9 s | 57.7 s / 58.9 s |
| denoise phase | 44.8–45.9 s | 44.9–47.1 s |
| H3cApp resident memory peak | 18.0 / 29.5 GB | 10.7 / 10.8 GB |
| output | bit-identical | bit-identical |

Two runs per mode: treat the time difference as indicative. The memory difference and the identical output were consistent. The experimental M5 *Fast attention* option was ~7% faster in denoising but produced a visibly different video.
`bench/compute_bench.py` reproduces this kind of comparison on your machine (it drives H3cApp directly and needs the web queue idle).
