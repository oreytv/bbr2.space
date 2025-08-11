(() => {
  const canvas = document.getElementById('draw');
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = false;

  let WIDTH = canvas.width;
  let HEIGHT = canvas.height;

  const CHUNK_SIZE = 50;

  // Camera tracks world coords for top-left corner
  let camX = 0;
  let camY = 0;

  let scale = 1;
  let offsetX = 0;
  let offsetY = 0;

  // Brush color in rgb format for chunk pixels
  let brushColor = 'rgb(0,0,0)';

  let isDrawing = false;
  let isPanning = false;
  let panStart = null;

  const chunks = new Map();
  const pendingChunkUpdates = new Map();

  const colorPicker = document.getElementById('colorPicker');
  const valueSlider = document.getElementById('valueSlider');
  const coordText = document.getElementById('coordText');

  function hexToRgb(hex) {
    const bigint = parseInt(hex.slice(1), 16);
    return { r: (bigint >> 16) & 255, g: (bigint >> 8) & 255, b: bigint & 255 };
  }

  function updateBrush() {
    const base = hexToRgb(colorPicker.value);
    const factor = valueSlider.value / 100;
    brushColor = `rgb(${Math.floor(base.r * factor)},${Math.floor(base.g * factor)},${Math.floor(base.b * factor)})`;
  }
  colorPicker.addEventListener('input', () => { updateBrush(); scheduleRedraw(); });
  valueSlider.addEventListener('input', () => { updateBrush(); scheduleRedraw(); });
  updateBrush();

  // Helpers for chunk coords and indexing
  function chunkKey(cx, cy) { return `${cx},${cy}`; }
  function createBlankChunk() { return new Array(CHUNK_SIZE * CHUNK_SIZE).fill('white'); }
  function positiveMod(n, m) { return ((n % m) + m) % m; }
  function pixelToChunk(x, y) {
    return { cx: Math.floor(x / CHUNK_SIZE), cy: Math.floor(y / CHUNK_SIZE) };
  }
  function pixelToChunkIndex(x, y) {
    return positiveMod(y, CHUNK_SIZE) * CHUNK_SIZE + positiveMod(x, CHUNK_SIZE);
  }
  function getPixelColor(x, y) {
    const { cx, cy } = pixelToChunk(x, y);
    const key = chunkKey(cx, cy);
    if (!chunks.has(key)) return 'white';
    const chunk = chunks.get(key);
    const idx = pixelToChunkIndex(x, y);
    return chunk.data[idx];
  }
  function setPixelColor(x, y, color) {
    const { cx, cy } = pixelToChunk(x, y);
    const key = chunkKey(cx, cy);
    if (!chunks.has(key)) {
      chunks.set(key, { data: createBlankChunk(), loaded: true });
      createChunkCanvas(key);
    }
    const chunk = chunks.get(key);
    const idx = pixelToChunkIndex(x, y);
    chunk.data[idx] = color;
    updateChunkCanvas(key);
    pendingChunkUpdates.set(key, { cx, cy, data: chunk.data });
    scheduleSendChunkUpdates();
  }
  function createChunkCanvas(key) {
    const offscreenCanvas = document.createElement('canvas');
    offscreenCanvas.width = CHUNK_SIZE;
    offscreenCanvas.height = CHUNK_SIZE;
    const offscreenCtx = offscreenCanvas.getContext('2d');
    offscreenCtx.imageSmoothingEnabled = false; // <-- Add this line here

    chunks.get(key).offscreenCanvas = offscreenCanvas;
    chunks.get(key).offscreenCtx = offscreenCtx;
    }

  function updateChunkCanvas(key) {
    const chunk = chunks.get(key);
    if (!chunk.offscreenCtx) createChunkCanvas(key);
    const ctx2 = chunk.offscreenCtx;
    const imgData = ctx2.createImageData(CHUNK_SIZE, CHUNK_SIZE);
    for (let i = 0; i < chunk.data.length; i++) {
      const color = chunk.data[i];
      const idx = i * 4;
      if (color.startsWith('rgb')) {
        const rgb = color.match(/\d+/g).map(Number);
        imgData.data[idx] = rgb[0];
        imgData.data[idx + 1] = rgb[1];
        imgData.data[idx + 2] = rgb[2];
        imgData.data[idx + 3] = 255;
      } else if (color === 'black') {
        imgData.data[idx] = 0;
        imgData.data[idx + 1] = 0;
        imgData.data[idx + 2] = 0;
        imgData.data[idx + 3] = 255;
      } else {
        imgData.data[idx] = 255;
        imgData.data[idx + 1] = 255;
        imgData.data[idx + 2] = 255;
        imgData.data[idx + 3] = 255;
      }
    }
    ctx2.putImageData(imgData, 0, 0);
  }

  // WebSocket setup
  const ws = new WebSocket('wss://mrmr39acmateta.loca.lt');
  let wsOpen = false;

  ws.onopen = () => {
    wsOpen = true;
    ws.send(JSON.stringify({ type: 'request_all_chunks' }));
  };
  ws.onclose = () => { wsOpen = false; };
  ws.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data);
      if (data.type === 'canvas_size') {
        WIDTH = data.width;
        HEIGHT = data.height;
        canvas.width = WIDTH;
        canvas.height = HEIGHT;
        camX = -Math.floor(WIDTH / 2);
        camY = -Math.floor(HEIGHT / 2);
        scheduleRedraw();
      }
      else if (data.type === 'edit_chunk') {
        const key = chunkKey(data.cx, data.cy);
        if (!chunks.has(key)) {
          chunks.set(key, { data: data.chunkData, loaded: true });
          createChunkCanvas(key);
        } else {
          chunks.get(key).data = data.chunkData;
        }
        updateChunkCanvas(key);
        scheduleRedraw();
      }
      else if (data.type === 'all_chunks') {
        data.chunks.forEach(chunkInfo => {
          const key = chunkKey(chunkInfo.cx, chunkInfo.cy);
          if (!chunks.has(key)) {
            chunks.set(key, { data: chunkInfo.chunkData, loaded: true });
            createChunkCanvas(key);
          } else {
            chunks.get(key).data = chunkInfo.chunkData;
          }
          updateChunkCanvas(key);
        });
        scheduleRedraw();
      }
    } catch {}
  };

  canvas.addEventListener('contextmenu', e => e.preventDefault());

  // Converts screen coords to grid coords
  function screenToGrid(screenX, screenY) {
    const worldX = (screenX - offsetX) / scale;
    const worldY = (screenY - offsetY) / scale;
    const gx = Math.floor(worldX);
    const gy = Math.floor(worldY);
    return { gx, gy };
    }


  function drawPixelAt(gx, gy, color) {
    if (getPixelColor(gx, gy) === color) return;
    setPixelColor(gx, gy, color);
  }

  // Batch chunk update sender
  let sendScheduled = false;
  function scheduleSendChunkUpdates() {
    if (sendScheduled) return;
    sendScheduled = true;
    setTimeout(() => {
      if (!wsOpen) {
        pendingChunkUpdates.clear();
        sendScheduled = false;
        return;
      }
      for (const [key, { cx, cy, data }] of pendingChunkUpdates.entries()) {
        ws.send(JSON.stringify({ type: 'edit_chunk', cx, cy, chunkData: data }));
      }
      pendingChunkUpdates.clear();
      sendScheduled = false;
    }, 200);
  }

  // Mouse handlers
  canvas.addEventListener('mousedown', e => {
    if (e.button === 0) {
      if (scale <= 0.1) return;  // prevent drawing when zoomed out too far
      isDrawing = true;
      const { gx, gy } = screenToGrid(e.offsetX, e.offsetY);
      drawPixelAt(gx, gy, brushColor);
      scheduleRedraw();
    } else if (e.button === 2) {
      isPanning = true;
      panStart = { x: e.clientX, y: e.clientY };
    }
  });

  canvas.addEventListener('mouseup', e => {
    if (e.button === 0) isDrawing = false;
    if (e.button === 2) isPanning = false;
  });

  canvas.addEventListener('mousemove', e => {
    const { gx, gy } = screenToGrid(e.offsetX, e.offsetY);
    coordText.textContent = `(${gx}, ${gy})`;
    lastMouseGrid = { gx, gy };

    if (isDrawing) {
      if (scale <= 0.1) return; // prevent drawing when zoomed out
      drawPixelAt(gx, gy, brushColor);
      scheduleRedraw();
    } else if (isPanning && panStart) {
      const dx = e.clientX - panStart.x;
      const dy = e.clientY - panStart.y;
      panStart = { x: e.clientX, y: e.clientY };
      offsetX += dx;
      offsetY += dy;
      scheduleRedraw();
    } else {
      scheduleRedraw();
    }
  });

  // Zoom handler
  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    const zoomIntensity = 0.1;
    const wheel = e.deltaY < 0 ? 1 : -1;
    const zoom = 1 + wheel * zoomIntensity;
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    const beforeZoomX = (mouseX - offsetX) / scale;
    const beforeZoomY = (mouseY - offsetY) / scale;
    const newScale = scale * zoom;
    if (newScale < 0.1 || newScale > 10) return;
    scale = newScale;
    offsetX = mouseX - beforeZoomX * scale;
    offsetY = mouseY - beforeZoomY * scale;
    scheduleRedraw();
  }, { passive: false });

  // Redraw throttling
  let redrawScheduled = false;
  function scheduleRedraw() {
    if (redrawScheduled) return;
    redrawScheduled = true;
    requestAnimationFrame(() => {
      redraw();
      redrawScheduled = false;
    });
  }

  // Draw a red square where the mouse grid is (pixel indicator)
  function drawPixelIndicator(gx, gy) {
    ctx.save();
    ctx.translate(offsetX, offsetY);
    ctx.scale(scale, scale);
    ctx.strokeStyle = 'red';
    ctx.lineWidth = 1 / scale;
    ctx.strokeRect(gx, gy, 1, 1);
    ctx.restore();
  }

  // Draw draw-enabled status at top-right corner
  function drawDrawStatus() {
    ctx.save();
    ctx.resetTransform(); // screen coords

    ctx.font = '16px monospace';
    ctx.textBaseline = 'top';
    ctx.textAlign = 'right';

    const canDraw = scale > 0.1;
    ctx.fillStyle = canDraw ? 'green' : 'red';
    const statusText = canDraw ? 'DRAW ENABLED' : 'DRAW DISABLED';

    ctx.fillText(statusText, canvas.width - 10, 10);

    ctx.fillStyle = 'black';
    ctx.font = '14px monospace';
    ctx.fillText(`Zoom: ${scale.toFixed(2)}x`, canvas.width - 10, 30);

    ctx.restore();
    }


  // Main redraw function
  function redraw() {
    ctx.fillStyle = 'white';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.save();
    ctx.translate(offsetX, offsetY);
    ctx.scale(scale, scale);

    for (const [key, chunk] of chunks) {
      if (!chunk.loaded || !chunk.offscreenCanvas) continue;
      const [cx, cy] = key.split(',').map(Number);
      ctx.drawImage(chunk.offscreenCanvas, cx * CHUNK_SIZE, cy * CHUNK_SIZE);
    }
    ctx.restore();

    // Draw pixel indicator last so it’s on top
    if (lastMouseGrid) {
      drawPixelIndicator(lastMouseGrid.gx, lastMouseGrid.gy);
    }

    drawDrawStatus();
  }

  // Keep track of last mouse grid position for indicator
  let lastMouseGrid = null;

  redraw();
})();
