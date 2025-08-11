(() => {
  const canvas = document.getElementById('draw');
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = false;

  // Global zoom limits
  const MIN_ZOOM = 0.1;       // Minimum zoom allowed (zoom out limit)
  const MIN_DRAW_ZOOM = 21;   // Minimum zoom level required to draw
  const MAX_ZOOM = 50;        // Maximum zoom allowed (zoom in limit)

  let WORLD_WIDTH = 500;  // Virtual world size
  let WORLD_HEIGHT = 500; // Virtual world size
  
  // Keep canvas viewport at reasonable size
  const VIEWPORT_WIDTH = 500;
  const VIEWPORT_HEIGHT = 500;

  const CHUNK_SIZE = 50;

  let camX = 0;
  let camY = 0;

  let scale = 1;
  let offsetX = 0;
  let offsetY = 0;

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

  function chunkKey(cx, cy) { return `${cx},${cy}`; }
  function createBlankChunk() { return new Array(CHUNK_SIZE * CHUNK_SIZE).fill('white'); }
  function positiveMod(n, m) { return ((n % m) + m) % m; }
  function pixelToChunk(x, y) { return { cx: Math.floor(x / CHUNK_SIZE), cy: Math.floor(y / CHUNK_SIZE) }; }
  function pixelToChunkIndex(x, y) { return positiveMod(y, CHUNK_SIZE) * CHUNK_SIZE + positiveMod(x, CHUNK_SIZE); }

  // Check if a chunk is within drawable bounds
  function isChunkInBounds(cx, cy) {
    if (cx < 0 || cy < 0) return false;
    const x_start = cx * CHUNK_SIZE;
    const y_start = cy * CHUNK_SIZE;
    if (x_start >= WORLD_WIDTH || y_start >= WORLD_HEIGHT) return false;
    return true;
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
    
    // Don't allow drawing in chunks outside bounds
    if (!isChunkInBounds(cx, cy)) return;
    
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
    offscreenCtx.imageSmoothingEnabled = false;
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

  // Create a grey chunk canvas for out-of-bounds areas
  function createGreyChunkCanvas() {
    const greyCanvas = document.createElement('canvas');
    greyCanvas.width = CHUNK_SIZE;
    greyCanvas.height = CHUNK_SIZE;
    const greyCtx = greyCanvas.getContext('2d');
    greyCtx.fillStyle = '#f0f0f0'; // Light grey
    greyCtx.fillRect(0, 0, CHUNK_SIZE, CHUNK_SIZE);
    return greyCanvas;
  }

  const greyChunkCanvas = createGreyChunkCanvas();

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
      else if (data.type === 'pong') {
        console.log('Ping latency:', Date.now() - data.time, 'ms');
        return;
      }
    } catch {}
  };

  canvas.addEventListener('contextmenu', e => e.preventDefault());

  setInterval(() => {
    if (wsOpen) {
      ws.send(JSON.stringify({ type: 'ping', time: Date.now() }));
    }
  }, 15000);

  function screenToGrid(screenX, screenY) {
    const worldX = (screenX - offsetX) / scale;
    const worldY = (screenY - offsetY) / scale;
    return { gx: Math.floor(worldX), gy: Math.floor(worldY) };
  }

  let lastDrawTime = 0;
  const DRAW_COOLDOWN_MS = 200;

  function drawPixelAt(gx, gy, color) {
    const now = performance.now();
    if (now - lastDrawTime < DRAW_COOLDOWN_MS) return; // cooldown check
    lastDrawTime = now;
    if (getPixelColor(gx, gy) === color) return;
    setPixelColor(gx, gy, color);
  }

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

  canvas.addEventListener('mousedown', e => {
    if (e.button === 0) {
      if (scale <= MIN_DRAW_ZOOM) return; // use min draw zoom
      const { gx, gy } = screenToGrid(e.offsetX, e.offsetY);
      const { cx, cy } = pixelToChunk(gx, gy);
      if (!isChunkInBounds(cx, cy)) return; // Don't draw in out-of-bounds chunks
      isDrawing = true;
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
      if (scale <= MIN_DRAW_ZOOM) return;
      const { cx, cy } = pixelToChunk(gx, gy);
      if (!isChunkInBounds(cx, cy)) return; // Don't draw in out-of-bounds chunks
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
    if (newScale < MIN_ZOOM || newScale > MAX_ZOOM) return;
    scale = newScale;
    offsetX = mouseX - beforeZoomX * scale;
    offsetY = mouseY - beforeZoomY * scale;
    scheduleRedraw();
  }, { passive: false });

  // Touch handling for mobile
  let touches = [];
  let lastTouchDistance = 0;
  let lastTouchCenter = { x: 0, y: 0 };

  function getTouchPos(touch) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: touch.clientX - rect.left,
      y: touch.clientY - rect.top
    };
  }

  function getTouchDistance(touch1, touch2) {
    const dx = touch1.clientX - touch2.clientX;
    const dy = touch1.clientY - touch2.clientY;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function getTouchCenter(touch1, touch2) {
    return {
      x: (touch1.clientX + touch2.clientX) / 2,
      y: (touch1.clientY + touch2.clientY) / 2
    };
  }

  canvas.addEventListener('touchstart', e => {
    e.preventDefault();
    touches = Array.from(e.touches);
    
    if (touches.length === 1) {
      // Single finger - start drawing
      if (scale <= MIN_DRAW_ZOOM) return;
      const pos = getTouchPos(touches[0]);
      const { gx, gy } = screenToGrid(pos.x, pos.y);
      const { cx, cy } = pixelToChunk(gx, gy);
      if (!isChunkInBounds(cx, cy)) return;
      isDrawing = true;
      drawPixelAt(gx, gy, brushColor);
      scheduleRedraw();
    } else if (touches.length === 2) {
      // Two fingers - prepare for pan/zoom
      isDrawing = false;
      isPanning = true;
      lastTouchDistance = getTouchDistance(touches[0], touches[1]);
      const rect = canvas.getBoundingClientRect();
      lastTouchCenter = getTouchCenter(touches[0], touches[1]);
      lastTouchCenter.x -= rect.left;
      lastTouchCenter.y -= rect.top;
    }
  }, { passive: false });

  canvas.addEventListener('touchmove', e => {
    e.preventDefault();
    touches = Array.from(e.touches);
    
    if (touches.length === 1 && isDrawing) {
      // Single finger drawing
      if (scale <= MIN_DRAW_ZOOM) return;
      const pos = getTouchPos(touches[0]);
      const { gx, gy } = screenToGrid(pos.x, pos.y);
      const { cx, cy } = pixelToChunk(gx, gy);
      if (!isChunkInBounds(cx, cy)) return;
      drawPixelAt(gx, gy, brushColor);
      scheduleRedraw();
      
      // Update coordinate display
      coordText.textContent = `(${gx}, ${gy})`;
      lastMouseGrid = { gx, gy };
    } else if (touches.length === 2 && isPanning) {
      // Two finger pan and zoom
      const currentDistance = getTouchDistance(touches[0], touches[1]);
      const rect = canvas.getBoundingClientRect();
      const currentCenter = getTouchCenter(touches[0], touches[1]);
      currentCenter.x -= rect.left;
      currentCenter.y -= rect.top;
      
      // Handle zooming (pinch)
      if (Math.abs(currentDistance - lastTouchDistance) > 5) {
        const zoomFactor = currentDistance / lastTouchDistance;
        const beforeZoomX = (currentCenter.x - offsetX) / scale;
        const beforeZoomY = (currentCenter.y - offsetY) / scale;
        const newScale = scale * zoomFactor;
        
        if (newScale >= MIN_ZOOM && newScale <= MAX_ZOOM) {
          scale = newScale;
          offsetX = currentCenter.x - beforeZoomX * scale;
          offsetY = currentCenter.y - beforeZoomY * scale;
        }
        lastTouchDistance = currentDistance;
      }
      
      // Handle panning
      const dx = currentCenter.x - lastTouchCenter.x;
      const dy = currentCenter.y - lastTouchCenter.y;
      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
        offsetX += dx;
        offsetY += dy;
        lastTouchCenter = currentCenter;
      }
      
      scheduleRedraw();
    }
  }, { passive: false });

  canvas.addEventListener('touchend', e => {
    e.preventDefault();
    touches = Array.from(e.touches);
    
    if (touches.length === 0) {
      // All fingers lifted
      isDrawing = false;
      isPanning = false;
    } else if (touches.length === 1) {
      // One finger remaining - could switch to drawing mode
      isPanning = false;
      if (scale > MIN_DRAW_ZOOM) {
        const pos = getTouchPos(touches[0]);
        const { gx, gy } = screenToGrid(pos.x, pos.y);
        const { cx, cy } = pixelToChunk(gx, gy);
        if (isChunkInBounds(cx, cy)) {
          isDrawing = true;
        }
      }
    }
  }, { passive: false });

  let redrawScheduled = false;
  function scheduleRedraw() {
    if (redrawScheduled) return;
    redrawScheduled = true;
    requestAnimationFrame(() => {
      redraw();
      redrawScheduled = false;
    });
  }

  function drawPixelIndicator(gx, gy) {
    ctx.save();
    ctx.translate(offsetX, offsetY);
    ctx.scale(scale, scale);
    ctx.strokeStyle = 'red';
    ctx.lineWidth = 1 / scale;
    ctx.strokeRect(gx, gy, 1, 1);
    ctx.restore();
  }

  function drawDrawStatus() {
    ctx.save();
    ctx.resetTransform();
    ctx.font = '16px monospace';
    ctx.textBaseline = 'top';
    ctx.textAlign = 'right';
    const canDraw = scale > MIN_DRAW_ZOOM;
    const { gx, gy } = lastMouseGrid || { gx: 0, gy: 0 };
    const { cx, cy } = pixelToChunk(gx, gy);
    const inBounds = isChunkInBounds(cx, cy);
    
    ctx.fillStyle = (canDraw && inBounds) ? 'green' : 'red';
    let statusText = 'You may draw.';
    if (!canDraw) {
      statusText = 'Can\'t draw, Zoom in a little.';
    } else if (!inBounds) {
      statusText = 'Can\'t draw, Out of bounds.';
    }
    ctx.fillText(statusText, canvas.width - 10, 10);
    ctx.fillStyle = 'black';
    ctx.font = '14px monospace';
    ctx.fillText(`Zoom: ${scale.toFixed(2)}x`, canvas.width - 10, 30);
    ctx.restore();
  }

  function redraw() {
    ctx.fillStyle = 'white';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.save();
    ctx.translate(offsetX, offsetY);
    ctx.scale(scale, scale);
    ctx.imageSmoothingEnabled = false;

    // Calculate visible chunk range
    const startX = Math.floor(-offsetX / scale / CHUNK_SIZE) - 1;
    const endX = Math.floor((-offsetX + canvas.width) / scale / CHUNK_SIZE) + 1;
    const startY = Math.floor(-offsetY / scale / CHUNK_SIZE) - 1;
    const endY = Math.floor((-offsetY + canvas.height) / scale / CHUNK_SIZE) + 1;

    // Draw all visible chunks (both in-bounds and out-of-bounds)
    for (let cx = startX; cx <= endX; cx++) {
      for (let cy = startY; cy <= endY; cy++) {
        const key = chunkKey(cx, cy);
        const x = cx * CHUNK_SIZE;
        const y = cy * CHUNK_SIZE;

        if (isChunkInBounds(cx, cy)) {
          // Draw normal chunks (white background or with data)
          if (chunks.has(key) && chunks.get(key).loaded && chunks.get(key).offscreenCanvas) {
            ctx.drawImage(chunks.get(key).offscreenCanvas, x, y);
          }
        } else {
          // Draw grey chunks for out-of-bounds areas
          ctx.drawImage(greyChunkCanvas, x, y);
        }
      }
    }

    ctx.restore();

    if (lastMouseGrid) {
      drawPixelIndicator(lastMouseGrid.gx, lastMouseGrid.gy);
    }
    drawDrawStatus();
  }

  let lastMouseGrid = null;
  redraw();
})();