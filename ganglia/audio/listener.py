"""
Audio listener with Voice Activity Detection (VAD).
Captures audio from mic, detects speech segments, yields audio chunks.
"""

import numpy as np
import queue
import threading
from dataclasses import dataclass
from typing import Generator, Optional
import time

# We'll use sounddevice for cross-platform mic capture
# and silero-vad for voice activity detection (runs on CPU, no GPU needed)

@dataclass
class AudioChunk:
    """A chunk of audio data with metadata."""
    audio: np.ndarray
    sample_rate: int
    timestamp: float
    duration: float
    is_speech: bool


def is_speaker_active() -> bool:
    """Check if TTS is currently playing (to avoid feedback loops)."""
    from pathlib import Path
    speaking_file = Path.home() / ".clawdbot" / "ganglia-speaking"
    return speaking_file.exists()


class AudioListener:
    """
    Listens to microphone input and yields speech segments.
    
    Uses Silero VAD for voice activity detection - lightweight and accurate.
    """
    
    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_duration: float = 0.032,  # ~32ms for VAD (512 samples at 16kHz)
        speech_threshold: float = 0.5,
        silence_duration: float = 1.0,  # seconds of silence to end segment
        min_speech_duration: float = 0.5,  # minimum speech to process
        pre_buffer_duration: float = 0.5,  # seconds of audio to keep before speech detected
        device: Optional[int] = None,  # None = default mic
    ):
        self.sample_rate = sample_rate
        # Silero VAD requires exactly 512 samples at 16kHz
        self.chunk_duration = 512 / sample_rate  # ~32ms
        self.speech_threshold = speech_threshold
        self.silence_duration = silence_duration
        self.min_speech_duration = min_speech_duration
        self.pre_buffer_duration = pre_buffer_duration
        self.device = device
        
        self._audio_queue: queue.Queue = queue.Queue()
        self._running = False
        self._vad_model = None
        
    def _load_vad(self):
        """Load Silero VAD model (lazy loading)."""
        if self._vad_model is None:
            import torch
            model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                trust_repo=True
            )
            self._vad_model = model
            self._get_speech_timestamps = utils[0]
        return self._vad_model
    
    def _audio_callback(self, indata, frames, time_info, status):
        """Callback for sounddevice stream."""
        if status:
            print(f"Audio status: {status}")
        self._audio_queue.put(indata.copy())
    
    def listen(self) -> Generator[AudioChunk, None, None]:
        """
        Start listening and yield audio chunks.
        
        Yields AudioChunk objects for each detected speech segment.
        """
        import sounddevice as sd
        import torch
        
        vad = self._load_vad()
        chunk_samples = int(self.sample_rate * self.chunk_duration)
        
        self._running = True
        speech_buffer = []
        pre_buffer = []  # Rolling buffer of recent audio (before speech detected)
        max_pre_chunks = int(self.pre_buffer_duration / self.chunk_duration)
        silence_chunks = 0
        max_silence_chunks = int(self.silence_duration / self.chunk_duration)
        in_speech = False
        
        print(f"🎤 Listening on device: {self.device or 'default'}")
        print(f"   Sample rate: {self.sample_rate}Hz, Chunk: {self.chunk_duration}s")
        print(f"   Pre-buffer: {self.pre_buffer_duration}s ({max_pre_chunks} chunks)")
        
        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.float32,
            blocksize=chunk_samples,
            device=self.device,
            callback=self._audio_callback
        ):
            while self._running:
                try:
                    audio_data = self._audio_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # Skip processing if TTS is playing (avoid feedback loop)
                if is_speaker_active():
                    # Clear any in-progress speech buffer to avoid capturing TTS
                    if in_speech:
                        speech_buffer = []
                        in_speech = False
                        silence_chunks = 0
                    continue
                
                # Flatten to 1D if needed
                audio_flat = audio_data.flatten()
                
                # Run VAD
                audio_tensor = torch.from_numpy(audio_flat)
                speech_prob = vad(audio_tensor, self.sample_rate).item()
                is_speech = speech_prob > self.speech_threshold
                
                timestamp = time.time()
                
                if is_speech:
                    if not in_speech:
                        # Speech just started - prepend pre-buffer to catch beginning
                        in_speech = True
                        speech_buffer = list(pre_buffer)  # Copy pre-buffer
                        pre_buffer = []
                    speech_buffer.append(audio_flat)
                    silence_chunks = 0
                elif in_speech:
                    silence_chunks += 1
                    speech_buffer.append(audio_flat)  # Include trailing silence
                    
                    if silence_chunks >= max_silence_chunks:
                        # End of speech segment
                        full_audio = np.concatenate(speech_buffer)
                        duration = len(full_audio) / self.sample_rate
                        
                        if duration >= self.min_speech_duration:
                            yield AudioChunk(
                                audio=full_audio,
                                sample_rate=self.sample_rate,
                                timestamp=timestamp - duration,
                                duration=duration,
                                is_speech=True
                            )
                        
                        speech_buffer = []
                        silence_chunks = 0
                        in_speech = False
                else:
                    # Not in speech - maintain rolling pre-buffer
                    pre_buffer.append(audio_flat)
                    if len(pre_buffer) > max_pre_chunks:
                        pre_buffer.pop(0)
    
    def stop(self):
        """Stop listening."""
        self._running = False


def list_devices():
    """List available audio input devices."""
    import sounddevice as sd
    print("Available audio devices:")
    print(sd.query_devices())


if __name__ == "__main__":
    # Quick test
    list_devices()
    print("\n" + "="*50)
    
    listener = AudioListener()
    print("Starting listener (Ctrl+C to stop)...")
    
    try:
        for chunk in listener.listen():
            print(f"📢 Speech detected: {chunk.duration:.1f}s")
    except KeyboardInterrupt:
        listener.stop()
        print("\nStopped.")
