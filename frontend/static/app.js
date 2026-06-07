'use strict';

const State = Object.freeze({ IDLE: 0, REGISTER_LIVENESS: 1, RECOGNIZING: 2 });
const CamMode = Object.freeze({ BROWSER: 'browser', SERVER: 'server' });
const LIVENESS_TIMEOUT_MS = 10000; // 10 saniye sonra manuel yakalama butonu göster

class FaceApp {
  constructor() {
    this.state = State.IDLE;
    this.camMode = CamMode.BROWSER;
    this.ws = null;
    this.stream = null;
    this.frameTimer = null;
    this.pendingName = null;
    this.blinkCount = 0;
    this._livenessTimer = null;
    this._livenessCountdown = null;

    this.video    = document.getElementById('video');
    this.serverStream = document.getElementById('server-stream');
    this.overlay  = document.getElementById('overlay');
    this.ctx      = this.overlay.getContext('2d');
    this.resultArea   = document.getElementById('result-area');
    this.facesList    = document.getElementById('faces-list');
    this.statusDot    = document.getElementById('status-dot');
    this.livenessBanner  = document.getElementById('liveness-banner');
    this.livenessText    = document.getElementById('liveness-text');
    this.blinkDot1       = document.getElementById('blink-dot-1');
    this.earDisplay      = document.getElementById('ear-display');
    this.livenessTimerEl = document.getElementById('liveness-timer');
    this.btnManualCapture = document.getElementById('btn-manual-capture');
    this.modalOverlay = document.getElementById('modal-overlay');
    this.faceNameInput = document.getElementById('face-name');
    this.toast        = document.getElementById('toast');
    this.serverCamNotice = document.getElementById('server-cam-notice');
    this.btnCamBrowser = document.getElementById('btn-cam-browser');
    this.btnCamServer  = document.getElementById('btn-cam-server');

    document.getElementById('btn-register').addEventListener('click', () => this.openModal());
    document.getElementById('btn-modal-cancel').addEventListener('click', () => this.closeModal());
    document.getElementById('btn-modal-save').addEventListener('click', () => this.startRegister());
    this.faceNameInput.addEventListener('keydown', e => { if (e.key === 'Enter') this.startRegister(); });
    this.btnCamBrowser.addEventListener('click', () => this.switchCamMode(CamMode.BROWSER));
    this.btnCamServer.addEventListener('click', () => this.switchCamMode(CamMode.SERVER));
    this.btnManualCapture.addEventListener('click', () => this.onLivenessPassed());

    this.init();
  }

  async init() {
    await this.startCamera();
    this.connectWS();
    await this.loadFacesList();
    await this.checkServerCamera();
  }

  // ------------------------------------------------------------------ //
  // Camera
  // ------------------------------------------------------------------ //

  async startCamera() {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, facingMode: 'user' },
        audio: false,
      });
      this.video.srcObject = this.stream;
      await new Promise(res => { this.video.onloadedmetadata = res; });
      this.overlay.width  = this.video.videoWidth  || 640;
      this.overlay.height = this.video.videoHeight || 480;
    } catch (err) {
      this.showToast('Kamera erişimi reddedildi: ' + err.message, 'error');
    }
  }

  // ------------------------------------------------------------------ //
  // Server camera check & toggle
  // ------------------------------------------------------------------ //

  async checkServerCamera() {
    try {
      const resp = await fetch('/api/camera/available');
      const data = await resp.json();
      if (data.available) {
        this.btnCamServer.disabled = false;
        this.btnCamServer.title = 'Sunucu kamerası mevcut';
      } else {
        this.btnCamServer.title = 'Sunucu kamerası bulunamadı';
      }
    } catch {
      // ignore — server might not be ready yet
    }
  }

  switchCamMode(mode) {
    if (this.camMode === mode) return;
    this.camMode = mode;

    if (this.ws) { this.ws.close(); this.ws = null; }
    clearInterval(this.frameTimer);

    if (mode === CamMode.SERVER) {
      this.btnCamServer.classList.add('active');
      this.btnCamBrowser.classList.remove('active');
      this.video.classList.add('hidden');
      this.serverStream.classList.remove('hidden');
      this.serverCamNotice.classList.remove('hidden');
      // Stop browser camera to free the device
      if (this.stream) {
        this.stream.getTracks().forEach(t => t.stop());
        this.stream = null;
      }
      this.serverStream.src = '/api/camera/mjpeg';
      this.overlay.width  = 640;
      this.overlay.height = 480;
      this.connectServerWS();
    } else {
      this.btnCamBrowser.classList.add('active');
      this.btnCamServer.classList.remove('active');
      this.serverStream.src = '';
      this.serverStream.classList.add('hidden');
      this.serverCamNotice.classList.add('hidden');
      this.video.classList.remove('hidden');
      this.startCamera().then(() => this.connectWS());
    }
  }

  connectServerWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${location.host}/ws/server-stream`;
    this.ws = new WebSocket(url);

    this.ws.onopen  = () => { this.setDot('live'); this.state = State.RECOGNIZING; };
    this.ws.onmessage = e => this.handleMessage(JSON.parse(e.data));
    this.ws.onclose = () => {
      this.setDot('error');
      if (this.camMode === CamMode.SERVER) setTimeout(() => this.connectServerWS(), 3000);
    };
    this.ws.onerror = () => this.setDot('error');
  }

  // ------------------------------------------------------------------ //
  // WebSocket (browser camera mode)
  // ------------------------------------------------------------------ //

  connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${location.host}/ws/stream`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.setDot('live');
      this.startSendingFrames();
      this.state = State.RECOGNIZING;
    };

    this.ws.onmessage = e => this.handleMessage(JSON.parse(e.data));

    this.ws.onclose = () => {
      this.setDot('error');
      clearInterval(this.frameTimer);
      if (this.camMode === CamMode.BROWSER) setTimeout(() => this.connectWS(), 3000);
    };

    this.ws.onerror = () => {
      this.setDot('error');
    };
  }

  startSendingFrames() {
    clearInterval(this.frameTimer);
    this.frameTimer = setInterval(() => this.sendFrame(), 200);
  }

  sendFrame() {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    if (!this.stream) return;

    const offscreen = document.createElement('canvas');
    const targetW = this.state === State.REGISTER_LIVENESS ? 640 : 320;
    const targetH = this.state === State.REGISTER_LIVENESS ? 480 : 240;
    offscreen.width  = targetW;
    offscreen.height = targetH;
    const octx = offscreen.getContext('2d');
    octx.drawImage(this.video, 0, 0, targetW, targetH);

    offscreen.toBlob(blob => {
      const reader = new FileReader();
      reader.onload = () => {
        const b64 = reader.result.split(',')[1];
        this.ws.send(JSON.stringify({
          type: 'frame',
          data: b64,
          mode: this.state === State.REGISTER_LIVENESS ? 'register_preview' : 'recognition',
        }));
      };
      reader.readAsDataURL(blob);
    }, 'image/jpeg', 0.8);
  }

  // ------------------------------------------------------------------ //
  // Message handler
  // ------------------------------------------------------------------ //

  handleMessage(msg) {
    if (msg.type === 'liveness_passed') {
      this.onLivenessPassed();
      return;
    }

    if (msg.type === 'recognition_result') {
      this.drawOverlay(msg.faces || []);
      this.renderResultPanel(msg.faces || [], msg.liveness);

      if (this.state === State.REGISTER_LIVENESS && msg.liveness) {
        this.blinkCount = msg.liveness.blink_count || 0;
        this.updateBlinkDots(this.blinkCount);
        // EAR debug gösterimi
        if (msg.liveness.ear !== undefined) {
          const ear = msg.liveness.ear;
          const color = ear < 0.25 ? '#fc8181' : '#48bb78';
          this.earDisplay.innerHTML = `EAR: <span style="color:${color};font-weight:700">${ear.toFixed(3)}</span>`;
        }
      }
    }
  }

  // ------------------------------------------------------------------ //
  // Canvas overlay
  // ------------------------------------------------------------------ //

  drawOverlay(faces) {
    const { ctx, overlay } = this;
    ctx.clearRect(0, 0, overlay.width, overlay.height);

    const scaleX = overlay.width  / (this.state === State.REGISTER_LIVENESS ? 640 : 320);
    const scaleY = overlay.height / (this.state === State.REGISTER_LIVENESS ? 480 : 240);

    for (const face of faces) {
      const { x, y, w, h } = face.bbox;
      const sx = x * scaleX, sy = y * scaleY, sw = w * scaleX, sh = h * scaleY;

      const isKnown   = face.name !== 'Bilinmiyor';
      const isFake    = !face.is_live;
      const boxColor  = isFake ? '#fc8181' : (isKnown ? '#48bb78' : '#ecc94b');

      ctx.strokeStyle = boxColor;
      ctx.lineWidth   = 3;
      ctx.strokeRect(sx, sy, sw, sh);

      // Corner decorators
      this.drawCorners(sx, sy, sw, sh, boxColor);

      // Name label
      const label = `${face.name}${isKnown ? ` ${Math.round(face.confidence * 100)}%` : ''}`;
      ctx.fillStyle = boxColor;
      ctx.font = 'bold 14px Segoe UI, system-ui, sans-serif';
      const textW = ctx.measureText(label).width;
      ctx.fillRect(sx, sy - 24, textW + 12, 22);
      ctx.fillStyle = '#0f1117';
      ctx.fillText(label, sx + 6, sy - 7);

      if (isFake) {
        ctx.fillStyle = 'rgba(252, 129, 129, 0.15)';
        ctx.fillRect(sx, sy, sw, sh);
        ctx.fillStyle = '#fc8181';
        ctx.font = 'bold 12px system-ui';
        ctx.fillText('CANLILIK UYARISI', sx + 4, sy + sh - 8);
      }
    }
  }

  drawCorners(x, y, w, h, color) {
    const { ctx } = this;
    const len = 16;
    ctx.strokeStyle = color;
    ctx.lineWidth   = 3;
    [[x,y,1,0],[x,y,0,1],[x+w,y,-1,0],[x+w,y,0,1],[x,y+h,1,0],[x,y+h,0,-1],[x+w,y+h,-1,0],[x+w,y+h,0,-1]]
      .forEach(([cx,cy,dx,dy]) => {
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + dx * len, cy + dy * len);
        ctx.stroke();
      });
  }

  // ------------------------------------------------------------------ //
  // Result panel
  // ------------------------------------------------------------------ //

  renderResultPanel(faces, liveness) {
    if (!faces.length) {
      this.resultArea.innerHTML = '<div class="no-face-msg">Yüz bekleniyor...</div>';
      return;
    }

    let html = '';
    for (const face of faces) {
      const isKnown   = face.name !== 'Bilinmiyor';
      const isFake    = !face.is_live;
      const cardClass = isFake ? 'face-card fake' : (isKnown ? 'face-card known' : 'face-card unknown');
      const pct       = Math.round(face.confidence * 100);
      const barClass  = pct >= 80 ? 'conf-high' : pct >= 60 ? 'conf-mid' : 'conf-low';
      const liveClass = isFake ? 'fake' : 'live';
      const liveText  = isFake ? 'Canlılık Yok' : 'Canlı';

      html += `
        <div class="${cardClass}">
          <div class="face-name">${escapeHtml(face.name)}</div>
          ${isKnown ? `
            <div class="confidence-bar-wrapper">
              <div class="confidence-bar ${barClass}" style="width:${pct}%"></div>
            </div>
            <div style="font-size:0.75rem;color:var(--text-muted)">Güven: ${pct}%</div>
          ` : ''}
          <div class="liveness-status ${liveClass}">
            <span class="indicator"></span>
            <span>${liveText}</span>
          </div>
          ${liveness ? `<div class="ear-info">EAR: ${liveness.ear} | Göz kırpma: ${liveness.blink_count} | Derinlik: ${liveness.depth_ok ? 'OK' : '—'}</div>` : ''}
        </div>`;
    }
    this.resultArea.innerHTML = html;
  }

  // ------------------------------------------------------------------ //
  // Registration flow
  // ------------------------------------------------------------------ //

  openModal() {
    this.faceNameInput.value = '';
    this.modalOverlay.classList.remove('hidden');
    this.faceNameInput.focus();
  }

  closeModal() {
    this.modalOverlay.classList.add('hidden');
    if (this.state === State.REGISTER_LIVENESS) {
      this._cancelLiveness();
    }
  }

  startRegister() {
    const name = this.faceNameInput.value.trim();
    if (!name) { this.faceNameInput.focus(); return; }
    this.pendingName = name;
    this.blinkCount = 0;
    this.modalOverlay.classList.add('hidden');
    this.state = State.REGISTER_LIVENESS;

    this.blinkDot1.classList.remove('done');
    this.btnManualCapture.classList.add('hidden');
    this.earDisplay.textContent = '';
    this.livenessText.textContent = 'Göz kırpın (1 kez yeterli)';
    this.livenessBanner.classList.remove('hidden');

    // Sunucu kamera modunda: server'a kayıt challenge başladığını bildir
    if (this.camMode === CamMode.SERVER && this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: 'start_register' }));
    }

    // 10 saniye sonra manuel yakalama butonunu göster
    let remaining = Math.round(LIVENESS_TIMEOUT_MS / 1000);
    this.livenessTimerEl.textContent = `${remaining}s`;
    this._livenessCountdown = setInterval(() => {
      remaining--;
      this.livenessTimerEl.textContent = remaining > 0 ? `${remaining}s` : '';
      if (remaining <= 0) clearInterval(this._livenessCountdown);
    }, 1000);

    this._livenessTimer = setTimeout(() => {
      if (this.state === State.REGISTER_LIVENESS) {
        this.livenessText.textContent = 'Göz kırpma algılanamadı — manuel yakala:';
        this.livenessTimerEl.textContent = '';
        this.btnManualCapture.classList.remove('hidden');
      }
    }, LIVENESS_TIMEOUT_MS);
  }

  _cancelLiveness() {
    clearTimeout(this._livenessTimer);
    clearInterval(this._livenessCountdown);
    this.state = State.RECOGNIZING;
    this.livenessBanner.classList.add('hidden');
    this.btnManualCapture.classList.add('hidden');
    this.earDisplay.textContent = '';
    this.livenessTimerEl.textContent = '';
  }

  updateBlinkDots(count) {
    if (count >= 1) this.blinkDot1.classList.add('done');
  }

  async onLivenessPassed() {
    clearTimeout(this._livenessTimer);
    clearInterval(this._livenessCountdown);
    this.livenessText.textContent = 'Canlılık doğrulandı! Kaydediliyor...';
    this.blinkDot1.classList.add('done');
    this.btnManualCapture.classList.add('hidden');
    this.earDisplay.textContent = '';
    this.livenessTimerEl.textContent = '';

    try {
      let blob;

      if (this.camMode === CamMode.SERVER) {
        // Sunucu kamerası: API'den anlık kare al (canvas'a çizmek güvenilmez)
        const snapResp = await fetch('/api/camera/snapshot');
        if (!snapResp.ok) throw new Error('Sunucu kamerası anlık görüntüsü alınamadı');
        blob = await snapResp.blob();
      } else {
        // Tarayıcı kamerası: video elementinden canvas'a çiz
        blob = await new Promise(resolve => {
          const snap = document.createElement('canvas');
          snap.width  = 640;
          snap.height = 480;
          snap.getContext('2d').drawImage(this.video, 0, 0, 640, 480);
          snap.toBlob(resolve, 'image/jpeg', 0.92);
        });
      }

      const form = new FormData();
      form.append('name', this.pendingName);
      form.append('image', blob, 'snapshot.jpg');

      const resp = await fetch('/api/faces/register', { method: 'POST', body: form });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Kayıt başarısız');
      }
      this.showToast(`"${this.pendingName}" başarıyla kaydedildi!`, 'success');
      await this.loadFacesList();
    } catch (e) {
      this.showToast(e.message, 'error');
    } finally {
      this.state = State.RECOGNIZING;
      this.livenessBanner.classList.add('hidden');
      this.pendingName = null;
    }
  }

  // ------------------------------------------------------------------ //
  // Faces list
  // ------------------------------------------------------------------ //

  async loadFacesList() {
    try {
      const resp = await fetch('/api/faces/list');
      const faces = await resp.json();
      this.renderFacesList(faces);
    } catch {
      // silently ignore network errors on list refresh
    }
  }

  renderFacesList(faces) {
    if (!faces.length) {
      this.facesList.innerHTML = '<li style="color:var(--text-muted);font-size:0.85rem;padding:8px 0">Henüz kayıtlı yüz yok</li>';
      return;
    }

    this.facesList.innerHTML = faces.map(f => `
      <li class="face-list-item" data-id="${f.id}">
        <img class="face-thumb" src="${escapeHtml(f.image_url)}" alt="${escapeHtml(f.name)}" onerror="this.style.display='none'" />
        <div class="face-list-info">
          <div class="face-list-name" title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</div>
          <div class="face-list-date">${formatDate(f.created_at)}</div>
        </div>
        <button class="btn btn-danger" data-id="${f.id}">Sil</button>
      </li>
    `).join('');

    this.facesList.querySelectorAll('[data-id]').forEach(btn => {
      if (btn.tagName === 'BUTTON') {
        btn.addEventListener('click', e => {
          e.stopPropagation();
          this.deleteFace(parseInt(btn.dataset.id));
        });
      }
    });
  }

  async deleteFace(id) {
    if (!confirm('Bu yüzü silmek istediğinize emin misiniz?')) return;
    try {
      const resp = await fetch(`/api/faces/${id}`, { method: 'DELETE' });
      if (!resp.ok) throw new Error('Silinemedi');
      this.showToast('Yüz silindi', 'success');
      await this.loadFacesList();
    } catch (e) {
      this.showToast(e.message, 'error');
    }
  }

  // ------------------------------------------------------------------ //
  // Helpers
  // ------------------------------------------------------------------ //

  setDot(state) {
    this.statusDot.className = `dot dot-${state}`;
    this.statusDot.title = state === 'live' ? 'Bağlı' : state === 'error' ? 'Bağlantı hatası' : 'Bekliyor';
  }

  showToast(message, type = 'success') {
    this.toast.textContent = message;
    this.toast.className = `toast ${type}`;
    setTimeout(() => { this.toast.classList.add('hidden'); }, 3500);
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDate(str) {
  try {
    const d = new Date(str);
    return d.toLocaleDateString('tr-TR', { day: '2-digit', month: 'short', year: 'numeric' });
  } catch { return str; }
}

window.addEventListener('DOMContentLoaded', () => { new FaceApp(); });
