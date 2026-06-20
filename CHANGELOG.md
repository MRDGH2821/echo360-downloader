# Changelog

All notable changes to this project will be documented in this file. See [conventional commits](https://www.conventionalcommits.org/) for commit guidelines.

---

## [0.1.1](/compare/v0.1.0..v0.1.1) - 2026-06-20

### Bug Fixes

- remove broken environment config from publish workflow - ([5386fa6](/commit/5386fa68fa836b49788901ae5b4b3071e814b580)) - MRDGH2821
- add --system flag to verify step in publish workflow - ([cc66477](/commit/cc66477f8c706cec291d94c796d00243db6efcac)) - MRDGH2821
- use venv for verify step in publish workflow - ([aafc2d2](/commit/aafc2d2cf03884fbccafd0d67a401a2dc3ac25f4)) - MRDGH2821

### Build

- update dependencies - ([b339004](/commit/b3390042dfae411c207890e7da3d8d52c3a985a1)) - MRDGH2821

### Ci

- **(megalinter)** update config - ([090391f](/commit/090391f48e699bc89460063f832bd01896a70935)) - MRDGH2821
- update action versions - ([f925c5c](/commit/f925c5c84bcc899fd013691a336c04642571b722)) - MRDGH2821

---

## [0.1.0] - 2026-06-19

### Bug Fixes

- add main() guard to **main**.py so entry points work - ([1d42dab](/commit/1d42dab54e4629e753fff8acf7b0a477ce9d078c)) - MRDGH2821
- await is_login_redirect coroutine in ensure_session - ([13ae94a](/commit/13ae94a5997df3ec530800d5f691695d9189ab54)) - MRDGH2821
- install M3U8 request listener before navigation so streams are captured before the 12s post-click wait - ([70b0bc1](/commit/70b0bc1d266f6bc6915dfd6d824dcf87f60fdf07)) - MRDGH2821
- mux room audio into combined PIP stream alongside camera stream - ([6bf7bf8](/commit/6bf7bf86b0291891e05713e9aa0510458982a8f4)) - MRDGH2821

### Documentation

- add usage documentation - ([586724e](/commit/586724ed4648053453167d0197d8b07662068f47)) - MRDGH2821
- clarify UniMelb is primary target but other instances may work; fix broken command examples in README - ([b588447](/commit/b588447da14cb7d65aaea576dd3531d73c1c0b3c)) - MRDGH2821
- add batch-example.yaml and update README with batch docs and fixes - ([7f70299](/commit/7f7029942a7044e5260b83c8381fad323c122869)) - MRDGH2821
- replace course codes with generic placeholders in README - ([8bcadfa](/commit/8bcadfad112fc73212425b234bd2688b2d93fb25)) - MRDGH2821
- update README with media URLs, compress, and current CLI - ([b599ec8](/commit/b599ec84941698cd1d48ef18dd7d81c867cbb681)) - MRDGH2821
- add build instructions and fix publish workflow - ([ce7cde2](/commit/ce7cde25ca3babda025874799dd3de5ba8d8e85a)) - MRDGH2821

### Features

- split into package modules with uv, cli args, and course subfolders - ([4fd25c6](/commit/4fd25c607f2f2d1b25d5c3982260411a5e1cf404)) - MRDGH2821
- add Windows compatibility with platform-aware state path and ffmpeg check - ([103b0f2](/commit/103b0f2d059012290ce0e6a5aedb24295537b792)) - MRDGH2821
- auto-login when session missing or stale; auto-prompt for re-auth - ([278ffe9](/commit/278ffe9a07408e1cba3bdd96b6e5be5f14278433)) - MRDGH2821
- use ISO 8601 date format (YYYY-MM-DD) for lecture folder names - ([0f3533c](/commit/0f3533c9b52c1f05e21099c36d2e280df98ec8b6)) - MRDGH2821
- extract ISO dates from Echo360 lesson ID instead of parsing lecture titles; display in list output - ([66324da](/commit/66324daacaf2d2aaa5fb7df1e7efe76b4b632da3)) - MRDGH2821
- resolve highest-resolution HLS variant from master playlist instead of relying on ffmpeg bandwidth heuristic - ([1639f67](/commit/1639f676dc5093c15e60df53226d86d525c0c1ce)) - MRDGH2821
- include 24-hour start time from lesson ID in folder names and list display - ([ea53bf3](/commit/ea53bf39f735ac1e401fea02b8883910325fafd1)) - MRDGH2821
- use Rich library for styled TUI output with tables, colors, and progress indicators - ([3e801c1](/commit/3e801c155270e73d11167d96c203af8280f442fa)) - MRDGH2821
- add batch download from YAML course list with status tracking - ([1f7e8c5](/commit/1f7e8c5c6482a0b2b48b0ca9a7789b8ad38ffc7e)) - MRDGH2821
- parallelise downloads in batch mode via YAML parallel setting - ([2507c7f](/commit/2507c7fd50d344cb7ef515eb88502684dac145d0)) - MRDGH2821
- write batch status to separate \_status.yaml file instead of overwriting config - ([3f85d47](/commit/3f85d47e9b5d9459365130d5aa414d9acc2f65c0)) - MRDGH2821
- make initial M3U8 capture non-interactive during page load - ([871f826](/commit/871f826b8d8e3c12e5fce21426d08322e8896011)) - MRDGH2821
- add compress subcommand for oversized videos - ([f50965f](/commit/f50965f6a360bcc46efd342cadedfd245eb0ae93)) - MRDGH2821
- add interactive lecture selection prompt for download command - ([5697d92](/commit/5697d922b6e13fba5e35adba739ff233828607ba)) - MRDGH2821
- add support for direct media URLs with audio - ([54145a3](/commit/54145a344d2026418334a79ed8aeae9b9b7a465a)) - MRDGH2821

### Miscellaneous Chores

- **(cocogitto)** add version bump command - ([7352040](/commit/73520404aadc396139811c588da0487709070fdc)) - MRDGH2821
- **(copier)** initialise with template - ([0c80908](/commit/0c8090860ba68dd3b2bd8279dd286e9ea59c620a)) - MRDGH2821
- **(copier)** update template - ([f26c82b](/commit/f26c82b126d6e9ab5b74657129b793ba54042bea)) - MRDGH2821
- add gitignore - ([df51803](/commit/df518031d5f8cd47e91ad2a06703028bccb404b2)) - MRDGH2821
- scaffold project with uv and pyproject.toml - ([4c1583f](/commit/4c1583fc4fb78dc51c2baa04e267f233aab99766)) - MRDGH2821
- add MIT licence - ([2c31d32](/commit/2c31d3204ea6fc892ac84e222084cdad68a3ea9b)) - MRDGH2821

### Refactoring

- use XDG state directory for session cookies - ([dd32eb7](/commit/dd32eb7786f0a933871017646c8c14148f70ee44)) - MRDGH2821
- rename file & change layout - ([abb9454](/commit/abb94542992eeaa4767c0061558874302d2698bb)) - MRDGH2821
- extract capture, selection, and session modules - ([b96a6ac](/commit/b96a6ace747e6ed1674b54bcbd27b5ddad05200b)) - MRDGH2821

<!-- generated by git-cliff -->
