# TrendForge Upgrade Roadmap

## Current Pipeline Baseline

TrendForge currently runs this path:

1. `main.py` gets a topic and calls `modules.scraper.scrape_web`.
2. `modules.researcher.analyse_content` turns scraped items into facts, opinions, conflicts, verdict.
3. `modules.scriptwriter.generate_script` creates 6-8 narration segments, then forces a fixed intro/outro text into the first and last script segments.
4. `modules.storyboard.build_storyboard` creates the evidence/visual contract and assigns each segment a visual intent.
5. `modules.tts.render_voiceover` renders Kokoro audio from the script segments.
6. `modules.visuals.create_storyboard_visuals` creates source cards/screenshots or AI/fallback art.
7. `modules.editor.assemble_timeline` matches ordered audio to ordered visuals and applies basic still-image effects.
8. `modules.renderer.export_video` exports the final MP4.

The best upgrade path is to make the storyboard the single contract for research evidence, narration intent, visual matching, motion, and render timing.

## Phase 1 - Research Source Expansion and Topic-Aware Evidence Ledger

Related request: "AI analysed the video topic, then fetched a list of open source sources for that topic, then screenshots can use those."

Goal:
Create a topic-aware source discovery step that asks the local LLM what evidence categories matter for the topic, then fetches source candidates from a configured list of open web sources.

Implementation:

1. Add `modules/source_discovery.py`.
   - Input: topic, optional existing scraped sources.
   - Output: `source_plan` JSON with `topic_angle`, `source_categories`, `search_queries`, `preferred_domains`, `avoid_domains`, `controversy_axes`.
   - Use Ollama/OpenAI-compatible client with strict JSON parsing, similar to `researcher.py`.

2. Extend `config.yaml`.
   - `research.target_source_count: 40`
   - `research.min_evidence_items: 20`
   - `research.source_mix.news/rss/reddit/wiki/arxiv/github/government`
   - `research.allowed_source_domains`
   - `research.blocked_source_domains`

3. Upgrade `modules/scraper.py`.
   - Accept a `source_plan`.
   - Add topic-targeted fetchers where useful:
     - Google News RSS for current claims.
     - Wikipedia for baseline.
     - Reddit for public sentiment.
     - arXiv / PubMed / government / GitHub search paths depending on the topic category.
   - Normalize every result into the existing raw content shape.

4. Upgrade `modules/storyboard.build_evidence_ledger`.
   - Preserve source credibility metadata: `source_type`, `domain`, `published_at`, `citation_score`, `license_hint`, `evidence_tags`.
   - Keep URLs as first-class fields so screenshot/source-card logic stays simple.

Acceptance criteria:

- A run logs the generated `source_plan`.
- Scraped source count can be 30-40 without breaking analysis token budgets.
- Source-backed storyboard segments have `source_url`, `source_title`, `source_excerpt`, `source_type`, and credibility metadata.
- Screenshots/source cards use the selected evidence item, not arbitrary first-in-list sources.

Dependencies:

- None. This phase should happen before longer videos and smarter narration because both need a larger evidence base.

## Phase 2 - Five-Minute Minimum Video Structure

Related request: "Video should be twice as long, Min 5min, twice as many resources etc."

Goal:
Move from 6-8 short segments to a planned 5-7 minute documentary structure backed by more evidence.

Implementation:

1. Extend config.
   - `video.min_duration_seconds: 300`
   - `script.target_duration_seconds: 330`
   - `script.target_segments: 18`
   - `script.min_words: 700`
   - `script.max_words: 950`
   - `scraping.max_sources: 40`
   - `screenshots.max_urls: 12`

2. Replace the current single `SCRIPT_TEMPLATE` with a duration-aware outline system in `modules/scriptwriter.py`.
   - Step A: Generate an outline with beats: hook, context, evidence blocks, conflict, human implication, thought experiment, counterpoint, synthesis, comment prompt, outro.
   - Step B: Expand outline to segments with estimated word counts.
   - Step C: Validate target word count before TTS.

3. Add `scriptwriter.validate_duration_target`.
   - Estimate duration from word count and configured TTS speed.
   - If under 300 seconds, request an expansion pass from Ollama.
   - If over 420 seconds, request a tightening pass.

4. Update `main.py` logs.
   - Log estimated script duration before TTS.
   - Log actual audio duration after TTS.
   - Fail or auto-expand if actual duration is below the configured minimum.

Acceptance criteria:

- `python main.py --subject "..." --skip-video` creates at least 300 seconds of audio unless the user opts out.
- Script has 16-24 coherent segments.
- Analysis consumes more sources but remains within configurable token budgets.
- The output is not padded filler; each segment maps to evidence, viewpoint, implication, or narrative bridge.

Dependencies:

- Phase 1 strongly recommended first.

## Phase 3 - Intro and Outro System

Related request: "Need some sort of intro and outro welcome and farewell for the intro and outro videos."

Goal:
Separate branded video clips from spoken intro/outro narration so the app can support generated intros, fixed intro videos, or both without duplicated audio.

Current issue:
`scriptwriter.force_custom_intro_outro` forces fixed intro/outro text into the first and last narration segments. Then `main.py` skips first/last TTS if intro/outro clips exist. This makes the logic brittle and prevents topic-specific intros/outros.

Implementation:

1. Add `modules/intro_outro.py`.
   - Builds intro and outro objects:
     - `mode: clip_only | narration_only | clip_plus_narration`
     - `intro_text`
     - `outro_text`
     - `clip_path`
     - `should_render_tts`

2. Change script generation.
   - Stop hard-overriding first and last content segments.
   - Store `script["intro"]` and `script["outro"]` separately from `script["segments"]`.
   - Let content segments start with the actual hook.

3. Update TTS.
   - Render intro/outro TTS only when configured.
   - Keep audio filenames explicit: `intro.wav`, `segment_000.wav`, `outro.wav`.

4. Update assembly.
   - Add intro clip and/or intro narration according to mode.
   - Same for outro.
   - If `Assets/intro-outro.mp4` is a combined file, split it once into cached `temp/intro_clip.mp4` and `temp/outro_clip.mp4`.

5. Add UI controls.
   - Intro mode selectbox.
   - Outro mode selectbox.
   - Optional custom intro/outro text boxes.

Acceptance criteria:

- Intro/outro clip audio is not duplicated with TTS narration.
- Topic-specific hook is preserved as the first real content segment.
- Users can run with clip-only, narration-only, or clip-plus-narration modes.

Dependencies:

- Can run in parallel with Phase 4.

## Phase 4 - Kokoro Voice Selection and In-App Sample Playback

Related request: "Need to be able to choose kokoro voice in side panel (play sample in app)."

Goal:
Expose Kokoro voices in Streamlit and pass the chosen voice into generation.

Implementation:

1. Add voice catalog to `modules/tts.py`.
   - `list_kokoro_voices()` returns known voice IDs and labels.
   - Include common IDs such as `af_bella`, `af_sarah`, `af_sky`, `af_nicole`, `am_adam`, `am_michael`, `bf_emma`, `bm_george`, while gracefully allowing config-only voices.

2. Add `render_voice_sample(text, voice, speed)`.
   - Writes to `temp/audio/samples/{voice}_{speed}.wav`.
   - Uses a short fixed sample line unless user enters custom sample text.

3. Update `main.py`.
   - Add CLI options `--tts-voice` and `--tts-speed`.
   - Apply overrides to config before rendering voiceover.

4. Update `ui.py`.
   - Sidebar selectbox for voice.
   - Speed slider.
   - "Generate sample" button.
   - `st.audio(sample_path)` playback.
   - Pass `--tts-voice` and `--tts-speed` into the subprocess command.

Acceptance criteria:

- Selecting a voice in UI affects the final video.
- Sample playback works without launching a full generation.
- Bad/unavailable voice IDs show a clear Streamlit error.

Dependencies:

- Independent. Good quick win.

## Phase 5 - AI Image Black-Frame Diagnosis and Guardrail

Related request: "AI images are black, not sure why."

Goal:
Identify why local AI image output is black and prevent black images from reaching the final video.

Likely causes in current code:

- `config.yaml` has `black_frame_guard: false`, so black frames are allowed through.
- SD 1.5 output is configured at `768x432`, but the app comments still refer to SDXL; mismatched model/config assumptions may hide runtime issues.
- `disable_safety_checker: true` is configured, but safety checker disabling only fully applies to `StableDiffusionPipeline`; if the wrong pipeline/model combo is loaded, behavior can differ.
- `enable_model_cpu_offload()` followed by `.to(device)` patterns can be fragile depending on diffusers version.
- The fallback symbolic art is dark by design; if blurred too strongly it may be perceived as black.

Implementation:

1. Add `modules/image_diagnostics.py`.
   - `analyze_image(path)` returns brightness mean, contrast, saturation, blank ratio, dimensions.
   - `assert_video_ready_image(path)` rejects black/near-blank/low-contrast frames.

2. Set `image.black_frame_guard: true` by default.

3. Update `generate_storyboard_art`.
   - After saving AI art, run diagnostics.
   - If black/blank, retry once with a safe neutral prompt.
   - If still black, use `create_symbolic_art`.

4. Add a diagnostic CLI command or script.
   - Example: `python -m modules.image_diagnostics --prompt "test"` or `python main.py --image-test`.
   - Log model path, engine, torch CUDA status, dtype, safety status, output statistics.

5. Brighten fallback symbolic art.
   - Increase base luminance and reduce blur radius.
   - Add visible foreground shapes with minimum contrast.

Acceptance criteria:

- No generated visual with mean brightness near zero reaches `temp/storyboard_visuals/art`.
- Logs explain whether the issue came from SD output, fallback art, or render scaling.
- A one-command image test produces a diagnostic PNG and statistics.

Dependencies:

- Independent, but should happen before visual matching and motion polish.

## Phase 6 - Smart Narration-to-Visual Matching

Related request: "Need a smart system whereby screenshots and AI images are matched to their part of the narration."

Goal:
Make each segment choose a visual based on narration meaning and evidence tags rather than simple source cursor rotation.

Current state:
`storyboard.build_storyboard` classifies visual intent and assigns source-backed segments sequentially through the evidence list. That is a good start, but it does not semantically match a claim to the best source.

Implementation:

1. Add `modules/visual_matcher.py`.
   - Input: script segments, evidence ledger, analysis facts/opinions/conflicts.
   - Output: per-segment match:
     - `visual_intent`
     - `evidence_id`
     - `match_reason`
     - `confidence`
     - `visual_prompt`
     - `motion_hint`

2. Matching strategy:
   - First pass: deterministic keyword/phrase overlap between segment narration and evidence title/excerpt.
   - Second pass: local LLM JSON matcher for ambiguous segments.
   - Fallback: round-robin evidence only after logging low confidence.

3. Extend storyboard segment schema.
   - Add `evidence_match_confidence`.
   - Add `match_reason`.
   - Add `visual_role: evidence | metaphor | context | contrast | synthesis`.

4. Update validation.
   - Warn if evidence-backed segment confidence is below 0.55.
   - Error if a factual claim has no source after matching.
   - Warn if too many adjacent segments use the same visual role.

5. Persist a debug artifact.
   - Save `temp/storyboard.json`.
   - Include narration, selected source, prompt, match reason, generated visual path.

Acceptance criteria:

- Every segment can be audited from narration to source/prompt to image file.
- Factual narration uses the most relevant source URL, not just the next source.
- Low-confidence visual matches are visible in logs and storyboard JSON.

Dependencies:

- Best after Phase 1 and Phase 2.

## Phase 7 - Motion, Zoom, and Visual Life

Related request: "Need zoom effects etc to make the video feel more alive on screenshot and AI."

Goal:
Upgrade still-image motion from basic clip-level effects to purposeful per-segment motion based on visual role and narration.

Current issue:
`editor.apply_ken_burns` crossfades between two differently resized stills. It does not crop/pan smoothly and may not create true motion.

Implementation:

1. Add motion hints in storyboard.
   - `motion_hint: slow_push_in | slow_pull_back | pan_left | pan_right | reveal_crop | hold | pulse | handheld_drift`.
   - Set by `visual_matcher` or by segment type.

2. Replace `apply_ken_burns`.
   - Use MoviePy `resize(lambda t: ...)` and `crop(...)` or `fl` transforms for true continuous zoom.
   - Keep center-safe crop to avoid text being cut off on source cards.

3. Add source-specific motion rules.
   - Source cards: subtle 1.00 -> 1.04 push only.
   - Screenshots: crop toward headline/content area when metadata exists.
   - AI art: bigger cinematic motion, 1.00 -> 1.10 plus small pan.
   - Outro/intro clips: no generated motion unless clip lacks motion.

4. Add micro-transitions.
   - Short crossfades between most segments.
   - Flash/glitch only for high-intensity controversy segments.
   - Avoid aggressive effects on serious topics.

5. Add render QA.
   - Export a 20-second sample render path for quick checks.
   - Verify clip durations and no black frames.

Acceptance criteria:

- Still visuals visibly move without cropping important text.
- Source cards remain readable.
- Motion is segment-aware and not random every frame.

Dependencies:

- Best after Phase 6 because motion should follow visual role.

## Phase 8 - Creative Story Narration Engine

Related request: "Need a smart narration system that is able to create a creative story from the facts gathered and evidence collected... make the viewer think... authentic, down to earth... entice users to comment."

Goal:
Build a narrative planning layer that turns evidence into a coherent video argument with recurring creative devices, rather than a list of facts.

Implementation:

1. Add `modules/narrative_planner.py`.
   - Input: topic, source plan, analysis, evidence ledger.
   - Output:
     - `central_question`
     - `viewer_promise`
     - `thesis`
     - `tension`
     - `human_stakes`
     - `story_arc`
     - `tone_profile`
     - `creative_device`
     - `comment_question`

2. Add a rotating creative device library.
   - `imagine_if`: thought experiment.
   - `funny_if`: ironic but non-cruel observation.
   - `small_scene`: everyday-life analogy.
   - `courtroom`: evidence/counter-evidence frame.
   - `two_futures`: optimistic vs pessimistic outcome.
   - `hidden_in_plain_sight`: reveal structure.
   - `contrarian_but_fair`: challenges assumptions without becoming reckless.

3. Make device selection topic-aware.
   - Serious health/safety topics avoid jokes.
   - Controversial topics use balanced challenge and comment prompts.
   - Tech/business topics can use "imagine if" and future scenarios.
   - Social/culture topics can use everyday scenes.

4. Replace script template with narrative beat generation.
   - Beat 1: cold open question.
   - Beat 2: what happened.
   - Beat 3: why people care.
   - Beat 4-9: evidence blocks and counterpoints.
   - Beat 10: creative thought experiment.
   - Beat 11-14: implications, conflicts, stakes.
   - Beat 15: synthesis.
   - Beat 16: comment question.
   - Beat 17: outro.

5. Add factual grounding rules.
   - Every factual claim must map to evidence.
   - Creative sections must be labeled internally as metaphor/speculation so they do not become fake facts.
   - Controversial comment prompts should invite viewer perspective, not harassment or misinformation.

6. Add post-generation critique pass.
   - Ask Ollama to grade:
     - evidence fidelity
     - story coherence
     - authenticity
     - engagement
     - controversy balance
     - comment-worthiness
   - If below threshold, revise script once.

Acceptance criteria:

- The script has a clear central question and payoff.
- At least one creative device appears naturally and is appropriate to the topic.
- Factual claims remain source-backed.
- Outro includes a topic-specific question that invites comments.
- The tone is conversational, grounded, and not generic hype.

Dependencies:

- Best after Phase 1 and Phase 2.
- Should integrate with Phase 6 so narrative beats drive visual roles.

## Suggested Build Order

1. Phase 5: Fix black AI images and add visual diagnostics.
2. Phase 4: Add Kokoro voice selection and sample playback.
3. Phase 3: Clean intro/outro architecture.
4. Phase 1: Add topic-aware source discovery and richer evidence.
5. Phase 2: Enforce 5-minute minimum script/audio.
6. Phase 8: Add creative narrative planner.
7. Phase 6: Add semantic visual matching.
8. Phase 7: Add stronger motion and render polish.

Reasoning:
Black frames, voice selection, and intro/outro are contained fixes. Research depth and video length change the core contract. Creative narration, semantic visual matching, and motion should come after the evidence/storyboard contract is stronger.

## Cross-Cutting Config Shape

Recommended new config sections:

```yaml
research:
  target_source_count: 40
  min_evidence_items: 20
  allowed_source_domains: []
  blocked_source_domains: []
  source_mix:
    news: 0.35
    reddit: 0.2
    wiki: 0.1
    specialist: 0.35

script:
  target_duration_seconds: 330
  min_duration_seconds: 300
  target_segments: 18
  min_words: 700
  max_words: 950
  creative_devices:
    - imagine_if
    - funny_if
    - small_scene
    - courtroom
    - two_futures
    - hidden_in_plain_sight
    - contrarian_but_fair

intro_outro:
  intro_mode: clip_only
  outro_mode: clip_only
  intro_text: ""
  outro_text: ""

motion:
  enabled: true
  source_card_max_zoom: 1.04
  screenshot_max_zoom: 1.08
  ai_art_max_zoom: 1.12
  transition_seconds: 0.45
```

## Verification Matrix

Use these checks after each major phase:

1. `python main.py --subject "artificial intelligence" --skip-video`
   - Validates research, analysis, script, TTS.

2. `python main.py --subject "artificial intelligence" --visual-source ai --skip-video`
   - Validates image prompt/AI art path if wired into skip-video diagnostics.

3. `python main.py --subject "artificial intelligence" --max-screenshot-urls 3 --captures-per-url 1`
   - Validates end-to-end render with bounded source capture time.

4. Inspect `temp/storyboard.json`.
   - Every segment has narration, visual role, source or prompt, match confidence, visual path, audio path, duration.

5. Inspect logs.
   - Source count, estimated duration, actual audio duration, visual diagnostics, render progress.

## Main Risks

1. Five-minute videos need much more text and evidence, so token budgeting and JSON reliability become more important.
2. Screenshots from news sites will often fail due to paywalls and bot checks; source cards must remain the reliable fallback.
3. Creative narration can become inaccurate if not separated from evidence-backed claims.
4. AI images can fail silently without brightness/contrast diagnostics.
5. Streamlit subprocess config overrides need a clean path so UI selections do not permanently mutate `config.yaml`.

## Definition of Done for the Whole Upgrade Set

- The UI can generate a 5-minute minimum video from a chosen topic.
- The user can select and preview a Kokoro voice before generation.
- Intro/outro behavior is explicit and does not duplicate narration.
- Every factual narration segment is traceable to an evidence source.
- Every non-factual narrative/metaphor segment has a purpose-built AI/fallback visual.
- No black or blank images reach the render.
- Still visuals have subtle segment-aware motion.
- The script feels like a coherent story with a central question, evidence, creative perspective, and topic-specific comment prompt.
