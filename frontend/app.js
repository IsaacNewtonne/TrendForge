document.addEventListener('DOMContentLoaded', () => {
    const statusLabels = {
        python: document.getElementById('python-status'),
        engine: document.getElementById('engine-status'),
        encoder: document.getElementById('encoder-status'),
    };
    const voiceSelect = document.getElementById('voice-select');
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

    function initShaderCanvas() {
        const canvas = document.getElementById('shader-canvas');
        if (!canvas) return;

        const ctx = canvas.getContext('2d', { alpha: true });
        if (!ctx) return;

        let width = 0;
        let height = 0;
        let dpr = 1;
        let frameId = 0;
        const pointer = { x: 0.62, y: 0.42 };

        function resize() {
            dpr = Math.min(window.devicePixelRatio || 1, 1.5);
            width = Math.max(1, window.innerWidth);
            height = Math.max(1, window.innerHeight);
            canvas.width = Math.floor(width * dpr);
            canvas.height = Math.floor(height * dpr);
            canvas.style.width = `${width}px`;
            canvas.style.height = `${height}px`;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        }

        function draw(time = 0) {
            const t = time * 0.00045;
            ctx.clearRect(0, 0, width, height);
            ctx.globalCompositeOperation = 'source-over';

            const base = ctx.createLinearGradient(0, 0, width, height);
            base.addColorStop(0, 'rgba(83, 74, 183, 0.10)');
            base.addColorStop(0.45, 'rgba(50, 214, 200, 0.045)');
            base.addColorStop(1, 'rgba(239, 159, 39, 0.08)');
            ctx.fillStyle = base;
            ctx.fillRect(0, 0, width, height);

            ctx.globalCompositeOperation = 'lighter';
            const cell = Math.max(26, Math.min(42, width / 34));
            for (let y = -cell; y < height + cell; y += cell) {
                for (let x = -cell; x < width + cell; x += cell) {
                    const px = x / width - pointer.x;
                    const py = y / height - pointer.y;
                    const distance = Math.sqrt(px * px + py * py);
                    const wave =
                        Math.sin((x * 0.012) + t * 2.1) +
                        Math.cos((y * 0.015) - t * 1.7) +
                        Math.sin((x + y) * 0.008 + t * 3.0);
                    const energy = Math.max(0, (wave + 2.35) / 4.7 - distance * 0.42);
                    const alpha = energy * 0.13;
                    if (alpha < 0.018) continue;

                    const hue = 242 + wave * 22 + distance * 36;
                    ctx.fillStyle = `hsla(${hue}, 76%, 63%, ${alpha})`;
                    ctx.fillRect(x + Math.sin(t + y * 0.01) * 10, y, cell * 0.82, 1.2);
                    ctx.fillRect(x, y + Math.cos(t + x * 0.012) * 10, 1.2, cell * 0.82);
                }
            }

            const pulseX = width * pointer.x;
            const pulseY = height * pointer.y;
            const pulse = ctx.createRadialGradient(pulseX, pulseY, 0, pulseX, pulseY, Math.max(width, height) * 0.55);
            pulse.addColorStop(0, 'rgba(50, 214, 200, 0.18)');
            pulse.addColorStop(0.26, 'rgba(83, 74, 183, 0.10)');
            pulse.addColorStop(0.62, 'rgba(239, 159, 39, 0.055)');
            pulse.addColorStop(1, 'rgba(0, 0, 0, 0)');
            ctx.fillStyle = pulse;
            ctx.fillRect(0, 0, width, height);

            if (!reduceMotion.matches) {
                frameId = requestAnimationFrame(draw);
            }
        }

        function onPointerMove(event) {
            pointer.x = event.clientX / Math.max(1, width);
            pointer.y = event.clientY / Math.max(1, height);
        }

        resize();
        window.addEventListener('resize', resize);
        window.addEventListener('pointermove', onPointerMove, { passive: true });
        draw();
    }

    initShaderCanvas();

    async function loadRuntimeStatus() {
        try {
            const response = await fetch('/api/status');
            if (!response.ok) throw new Error('status unavailable');
            const status = await response.json();

            if (statusLabels.python) statusLabels.python.textContent = status.python || 'unknown';
            if (statusLabels.engine) statusLabels.engine.textContent = status.aiEngine || 'unknown';
            if (statusLabels.encoder) statusLabels.encoder.textContent = status.encoderGpu || 'unknown';

            if (voiceSelect && status.voices && Object.keys(status.voices).length > 0) {
                const current = voiceSelect.value;
                voiceSelect.innerHTML = '';
                Object.entries(status.voices).forEach(([value, label]) => {
                    const option = document.createElement('option');
                    option.value = value;
                    option.textContent = value;
                    option.title = label;
                    voiceSelect.appendChild(option);
                });
                if ([...voiceSelect.options].some(option => option.value === current)) {
                    voiceSelect.value = current;
                }
            }
        } catch (error) {
            if (statusLabels.python) statusLabels.python.textContent = 'unknown';
            if (statusLabels.engine) statusLabels.engine.textContent = 'unknown';
            if (statusLabels.encoder) statusLabels.encoder.textContent = 'unknown';
        }
    }

    loadRuntimeStatus();

    const accordionHeaders = document.querySelectorAll('.accordion-header');
    accordionHeaders.forEach(header => {
        header.addEventListener('click', () => {
            const item = header.parentElement;
            item.classList.toggle('active');
        });
    });

    const speedSlider = document.getElementById('speed-slider');
    const speedVal = document.getElementById('speed-val');
    if (speedSlider && speedVal) {
        speedSlider.addEventListener('input', (event) => {
            speedVal.textContent = `${event.target.value}x`;
        });
    }

    const requestAiArtBtn = document.getElementById('request-ai-art-btn');
    let requestAiArtRequested = false;

    function currentVisualSource() {
        const active = document.querySelector('.segmented-control .seg-btn.active');
        return active ? active.dataset.value : 'auto';
    }

    function updateRequestAiArtButton() {
        if (!requestAiArtBtn) return;
        const isAuto = currentVisualSource() === 'auto';
        if (!isAuto) requestAiArtRequested = false;
        requestAiArtBtn.disabled = !isAuto;
        requestAiArtBtn.classList.toggle('is-hidden', !isAuto);
        requestAiArtBtn.classList.toggle('active', requestAiArtRequested);
        requestAiArtBtn.setAttribute('aria-pressed', requestAiArtRequested ? 'true' : 'false');
        requestAiArtBtn.textContent = requestAiArtRequested ? 'AI art requested' : 'Request AI art';
    }

    const segBtns = document.querySelectorAll('.seg-btn');
    segBtns.forEach(btn => {
        btn.addEventListener('click', (event) => {
            const siblings = event.currentTarget.parentElement.querySelectorAll('.seg-btn');
            siblings.forEach(sibling => sibling.classList.remove('active'));
            event.currentTarget.classList.add('active');
            updateRequestAiArtButton();
        });
    });

    const generateBtn = document.getElementById('generate-btn');
    const globalStatus = document.getElementById('global-status');
    const terminalBody = document.getElementById('terminal-body');
    const stageCards = document.querySelectorAll('.stage-card');
    const manualModal = document.getElementById('manual-modal');
    const manualList = document.getElementById('manual-list');
    const manualFolderPath = document.getElementById('manual-folder-path');
    const manualStatus = document.getElementById('manual-status');
    const manualClose = document.getElementById('manual-close');
    const manualRefresh = document.getElementById('manual-refresh');
    const manualConfirm = document.getElementById('manual-confirm');
    let manualModalShown = false;

    function appendLog(msg, type = 'muted') {
        const line = document.createElement('div');
        line.className = `log-line text-${type}`;
        line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
        terminalBody.appendChild(line);
        terminalBody.scrollTop = terminalBody.scrollHeight;
    }

    function setStage(stageNum, status) {
        const card = document.querySelector(`.stage-card[data-stage="${stageNum}"]`);
        if (!card) return;

        card.classList.remove('running', 'complete', 'error');
        const detail = card.querySelector('.stage-detail');
        if (!detail) return;

        if (status) {
            card.classList.add(status);
            if (status === 'running') detail.textContent = 'Processing...';
            if (status === 'complete') detail.textContent = 'Done';
            if (status === 'error') detail.textContent = 'Failed';
        } else {
            detail.textContent = 'Waiting...';
        }
    }

    function selectedVisualSource() {
        return currentVisualSource();
    }

    function buildGeneratePayload() {
        const topicInput = document.getElementById('topic-input');
        const codecSelect = document.getElementById('codec-select');
        const bitrateSelect = document.getElementById('bitrate-select');
        const presetSelect = document.getElementById('preset-select');

        return {
            topic: topicInput ? topicInput.value.trim() : '',
            visualSource: selectedVisualSource(),
            requestAiArt: selectedVisualSource() === 'auto' && requestAiArtRequested,
            codec: codecSelect ? codecSelect.value : 'auto',
            bitrate: bitrateSelect ? bitrateSelect.value : '12000k',
            preset: presetSelect ? presetSelect.value : 'medium',
            ttsVoice: voiceSelect ? voiceSelect.value : undefined,
            ttsSpeed: speedSlider ? Number(speedSlider.value) : undefined,
        };
    }

    function openManualModal() {
        if (!manualModal) return;
        manualModal.classList.add('open');
        manualModal.setAttribute('aria-hidden', 'false');
    }

    function closeManualModal() {
        if (!manualModal) return;
        manualModal.classList.remove('open');
        manualModal.setAttribute('aria-hidden', 'true');
    }

    async function loadManualManifest() {
        if (!manualList || !manualStatus) return;
        manualStatus.textContent = 'Loading manual image prompt list...';
        try {
            const response = await fetch('/api/manual-images/manifest');
            if (!response.ok) throw new Error('Manual prompt list is not ready yet.');
            const manifest = await response.json();
            const entries = Array.isArray(manifest.entries) ? manifest.entries : [];
            const hasPrompts = entries.some(entry => (entry.prompt || '').trim().length > 0);
            if (!entries.length || !hasPrompts) {
                manualStatus.textContent = 'Manual image prompts are not ready yet.';
                return;
            }
            renderManualManifest(manifest);
            openManualModal();
        } catch (error) {
            manualStatus.textContent = error.message;
        }
    }

    function renderManualManifest(manifest) {
        manualList.innerHTML = '';
        if (manualFolderPath) manualFolderPath.textContent = manifest.input_dir || 'input_images';
        const missing = new Set((manifest.validation && manifest.validation.missing) || []);

        (manifest.entries || []).forEach(entry => {
            const row = document.createElement('div');
            row.className = 'manual-item';

            const meta = document.createElement('div');
            meta.className = 'manual-item-meta';

            const number = document.createElement('div');
            number.className = 'manual-number';
            number.textContent = entry.file_prefix;

            const detail = document.createElement('div');
            detail.className = 'manual-detail';

            const title = document.createElement('div');
            title.className = 'manual-title-line';
            title.textContent = `${entry.suggested_filename} - ${entry.visual_intent || 'visual'}`;

            const prompt = document.createElement('p');
            prompt.className = 'manual-prompt';
            prompt.textContent = entry.prompt || '';

            const state = document.createElement('span');
            state.className = missing.has(entry.suggested_filename) ? 'manual-chip missing' : 'manual-chip ready';
            state.textContent = missing.has(entry.suggested_filename) ? 'Missing' : 'Found';

            detail.appendChild(title);
            detail.appendChild(prompt);
            detail.appendChild(state);

            const copy = document.createElement('button');
            copy.className = 'manual-copy';
            copy.type = 'button';
            copy.textContent = 'Copy prompt';
            copy.addEventListener('click', async () => {
                await navigator.clipboard.writeText(entry.prompt || '');
                copy.textContent = 'Copied';
                setTimeout(() => { copy.textContent = 'Copy prompt'; }, 1200);
            });

            meta.appendChild(number);
            meta.appendChild(detail);
            row.appendChild(meta);
            row.appendChild(copy);
            manualList.appendChild(row);
        });

        const missingCount = missing.size;
        manualStatus.textContent = missingCount
            ? `${missingCount} image files still missing. Save files as 001.png, 002.png, and so on.`
            : 'All numbered images found. Confirm when ready to continue rendering.';
    }

    async function confirmManualImages() {
        if (!manualStatus) return;
        manualStatus.textContent = 'Checking numbered images...';
        try {
            const response = await fetch('/api/manual-images/confirm', { method: 'POST' });
            const result = await response.json();
            if (!response.ok) {
                const detail = result.detail || result;
                const missing = detail.missing || [];
                manualStatus.textContent = missing.length
                    ? `Missing: ${missing.slice(0, 8).join(', ')}`
                    : 'Manual image check failed.';
                await loadManualManifest();
                return;
            }
            manualStatus.textContent = `Confirmed ${result.count} images. TrendForge is continuing.`;
            appendLog(`Manual images confirmed: ${result.count}`, 'success');
            setTimeout(closeManualModal, 900);
        } catch (error) {
            manualStatus.textContent = error.message;
        }
    }

    function setButtonRunning(isRunning) {
        generateBtn.classList.toggle('disabled', isRunning);
        generateBtn.classList.toggle('is-forging', isRunning);
        document.body.classList.toggle('run-active', isRunning);
        generateBtn.disabled = isRunning;
        generateBtn.querySelector('.btn-text').textContent = isRunning ? 'Forging...' : 'Forge Video';
    }

    if (manualClose) manualClose.addEventListener('click', closeManualModal);
    if (manualRefresh) manualRefresh.addEventListener('click', loadManualManifest);
    if (manualConfirm) manualConfirm.addEventListener('click', confirmManualImages);
    if (requestAiArtBtn) {
        requestAiArtBtn.addEventListener('click', () => {
            if (currentVisualSource() !== 'auto') return;
            requestAiArtRequested = !requestAiArtRequested;
            updateRequestAiArtButton();
        });
    }
    updateRequestAiArtButton();

    generateBtn.addEventListener('click', async () => {
        if (generateBtn.disabled || generateBtn.classList.contains('disabled')) return;

        terminalBody.innerHTML = '';
        stageCards.forEach(card => {
            card.classList.remove('running', 'complete', 'error');
            const detail = card.querySelector('.stage-detail');
            if (detail) detail.textContent = 'Waiting...';
        });

        setButtonRunning(true);
        manualModalShown = false;
        closeManualModal();
        globalStatus.textContent = 'RUNNING';
        globalStatus.className = 'status-badge running';

        appendLog('System initialized. Ready for commands.', 'muted');

        try {
            const response = await fetch('/api/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(buildGeneratePayload()),
            });

            if (!response.ok) {
                const message = await response.text();
                throw new Error(message || 'Failed to start generation');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';
            let currentStage = 0;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n\n');
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const msg = line.substring(6);

                    if (msg.startsWith('[DONE]')) {
                        const exitCode = msg.split(' ')[1];
                        if (exitCode === '0') {
                            globalStatus.textContent = 'COMPLETE';
                            globalStatus.className = 'status-badge complete';
                            if (currentStage > 0) setStage(currentStage, 'complete');
                        } else {
                            globalStatus.textContent = 'ERROR';
                            globalStatus.className = 'status-badge error';
                            appendLog('Pipeline failed.', 'error');
                            if (currentStage > 0) setStage(currentStage, 'error');
                        }
                        setButtonRunning(false);
                        return;
                    }

                    let type = 'muted';
                    if (msg.includes('ERROR') || msg.includes('Exception') || msg.includes('failed')) type = 'error';
                    else if (msg.includes('SUCCESS') || msg.includes('complete') || msg.includes('ready') || msg.includes('saved to')) type = 'success';
                    else if (msg.includes('INFO') || msg.includes('Phase:')) type = 'info';

                    appendLog(msg, type);

                    if (msg.includes('MANUAL_IMAGE_MANIFEST_READY') && !manualModalShown) {
                        manualModalShown = true;
                        appendLog('Manual image prompt list is ready.', 'warning');
                        await loadManualManifest();
                    }

                    const stageMatch = msg.match(/\[(\d+)\/7\]/);
                    if (stageMatch) {
                        const newStage = parseInt(stageMatch[1], 10);
                        if (currentStage > 0 && currentStage !== newStage) {
                            setStage(currentStage, 'complete');
                        }
                        currentStage = newStage;
                        setStage(currentStage, 'running');
                    }
                }
            }
        } catch (error) {
            appendLog(`Error: ${error.message}`, 'error');
            globalStatus.textContent = 'ERROR';
            globalStatus.className = 'status-badge error';
            setButtonRunning(false);
        }
    });
});
