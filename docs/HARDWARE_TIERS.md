# Hardware Tiers

Ganglia is designed to run on a range of hardware. Auto-detection will select appropriate models based on available resources.

## Tier Overview

| Tier | Example Hardware | RAM | GPU | Use Case |
|------|------------------|-----|-----|----------|
| **Heavy** | Desktop w/ RTX 3080+ | 16GB+ | Yes | Full local processing, minimal cloud |
| **Medium** | Modern laptop, Mac M1+ | 8GB+ | iGPU/MPS | Balanced local/cloud |
| **Light** | Raspberry Pi 5, old laptop | 4GB+ | No | Minimal local, cloud for heavy lifting |

---

## Heavy Tier (GPU)

**Target:** Desktop with dedicated GPU (RTX 3080+, RTX 4000/5000 series)

### Models
| Sense | Model | Notes |
|-------|-------|-------|
| Vision detection | YOLOv8m/l | Full accuracy |
| Vision embedding | CLIP ViT-L/14 | Rich embeddings for novelty |
| Scene description | Qwen-VL / moondream | Local VLM, no cloud needed |
| Audio transcription | Whisper large-v3 | Best accuracy |
| Audio embedding | CLAP | For audio novelty detection |

### Capabilities
- Full local processing pipeline
- Real-time video (30fps detection)
- Continuous audio monitoring
- Local scene descriptions
- Cloud only for complex reasoning

### Resource Usage
- VRAM: 8-12GB
- RAM: 8GB+
- CPU: Moderate (GPU does heavy lifting)

---

## Medium Tier (CPU/iGPU)

**Target:** Modern laptop, Mac M1/M2/M3, desktop without dedicated GPU

### Models
| Sense | Model | Notes |
|-------|-------|-------|
| Vision detection | YOLOv8n/s | Nano/small for speed |
| Vision embedding | CLIP ViT-B/32 | Lighter embeddings |
| Scene description | *Cloud fallback* | Too heavy for CPU |
| Audio transcription | Whisper base/small | Good balance |
| Audio embedding | Smaller CLAP or skip | Optional |

### Capabilities
- Detection and novelty triggers local
- Scene descriptions via cloud when triggered
- Near real-time video (10-15fps)
- Continuous audio with small model

### Resource Usage
- RAM: 4-6GB
- CPU: High utilization during inference
- MPS/iGPU acceleration where available

---

## Light Tier (Minimal)

**Target:** Raspberry Pi 5, old laptops, low-power devices

### Models
| Sense | Model | Notes |
|-------|-------|-------|
| Vision detection | YOLOv8n / motion only | Or skip, use motion delta |
| Vision embedding | *Skip or cloud* | Too heavy |
| Scene description | *Cloud only* | Always offload |
| Audio transcription | Whisper tiny | Runs on CPU |
| Audio embedding | *Skip* | Use simple VAD instead |

### Capabilities
- Motion detection (frame differencing)
- Wake word / VAD for audio triggers
- Whisper tiny for transcription when triggered
- All heavy processing via cloud
- Focus: **trigger detection only**

### Resource Usage
- RAM: 2-4GB
- CPU: Moderate bursts during detection
- Optimized for always-on, low-power

---

## Auto-Detection Logic

On startup, Ganglia will:

1. **Check for GPU**
   - CUDA available → Heavy tier candidate
   - MPS available (Mac) → Medium tier candidate
   - Neither → Light tier

2. **Check RAM**
   - 16GB+ → Heavy tier
   - 8GB+ → Medium tier
   - <8GB → Light tier

3. **Check CPU**
   - Modern (AVX2 support) → Can handle Medium
   - Older/ARM → Light tier

4. **User override**
   - Config file can force a specific tier
   - Useful for testing or resource constraints

```yaml
# ganglia.yaml
tier: auto  # or: heavy, medium, light
```

---

## Model Download

Models will be downloaded on first run based on detected tier. Approximate storage:

| Tier | Download Size | Disk Usage |
|------|---------------|------------|
| Heavy | ~8GB | ~12GB |
| Medium | ~2GB | ~3GB |
| Light | ~500MB | ~800MB |

---

## Performance Targets

| Metric | Heavy | Medium | Light |
|--------|-------|--------|-------|
| Video FPS | 30 | 10-15 | 1-5 (or motion only) |
| Audio latency | <500ms | <1s | <2s |
| Novelty detection | <100ms | <500ms | <1s |
| Cloud calls/hour | <10 | <50 | <100 |

---

## Future: Distributed Mode

For setups with multiple devices (e.g., RPi sensors + central GPU server):

- Light tier devices do capture + basic detection
- Stream events to central Heavy tier for processing
- Best of both worlds: cheap sensors, powerful brain

*Not implemented yet — tracking in issues.*
