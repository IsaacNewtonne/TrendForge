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

    const segBtns = document.querySelectorAll('.seg-btn');
    segBtns.forEach(btn => {
        btn.addEventListener('click', (event) => {
            const siblings = event.currentTarget.parentElement.querySelectorAll('.seg-btn');
            siblings.forEach(sibling => sibling.classList.remove('active'));
            event.currentTarget.classList.add('active');
        });
    });

    const generateBtn = document.getElementById('generate-btn');
    const globalStatus = document.getElementById('global-status');
    const terminalBody = document.getElementById('terminal-body');
    const stageCards = document.querySelectorAll('.stage-card');

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
        const active = document.querySelector('.segmented-control .seg-btn.active');
        return active ? active.dataset.value : 'auto';
    }

    function buildGeneratePayload() {
        const topicInput = document.getElementById('topic-input');
        const codecSelect = document.getElementById('codec-select');
        const bitrateSelect = document.getElementById('bitrate-select');
        const presetSelect = document.getElementById('preset-select');

        return {
            topic: topicInput ? topicInput.value.trim() : '',
            visualSource: selectedVisualSource(),
            codec: codecSelect ? codecSelect.value : 'auto',
            bitrate: bitrateSelect ? bitrateSelect.value : '12000k',
            preset: presetSelect ? presetSelect.value : 'medium',
            ttsVoice: voiceSelect ? voiceSelect.value : undefined,
            ttsSpeed: speedSlider ? Number(speedSlider.value) : undefined,
        };
    }

    function setButtonRunning(isRunning) {
        generateBtn.classList.toggle('disabled', isRunning);
        generateBtn.classList.toggle('is-forging', isRunning);
        document.body.classList.toggle('run-active', isRunning);
        generateBtn.disabled = isRunning;
        generateBtn.querySelector('.btn-text').textContent = isRunning ? 'Forging...' : 'Forge Video';
    }

    generateBtn.addEventListener('click', async () => {
        if (generateBtn.disabled || generateBtn.classList.contains('disabled')) return;

        terminalBody.innerHTML = '';
        stageCards.forEach(card => {
            card.classList.remove('running', 'complete', 'error');
            const detail = card.querySelector('.stage-detail');
            if (detail) detail.textContent = 'Waiting...';
        });

        setButtonRunning(true);
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
