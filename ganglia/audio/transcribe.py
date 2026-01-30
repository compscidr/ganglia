"""
Whisper transcription wrapper.
Uses mlx-whisper on Apple Silicon, faster-whisper elsewhere.
"""

import platform
from dataclasses import dataclass
from typing import Optional, List
import numpy as np


@dataclass
class Transcription:
    """Result of transcribing an audio segment."""
    text: str
    language: str
    confidence: float
    duration: float
    segments: List[dict]  # Word-level timing if available


def _is_apple_silicon() -> bool:
    """Check if running on Apple Silicon."""
    return platform.system() == "Darwin" and platform.machine() == "arm64"


class Transcriber:
    """
    Whisper-based transcription.
    
    Uses mlx-whisper on Apple Silicon (fast, native).
    Uses faster-whisper elsewhere (CPU/CUDA via CTranslate2).
    """
    
    # Model size recommendations by tier:
    # - Light (RPi): tiny, tiny.en
    # - Medium (laptop): base, small  
    # - Heavy (GPU): medium, large-v3
    
    MODEL_SIZES = {
        "tiny": "tiny",
        "tiny.en": "tiny.en", 
        "base": "base",
        "base.en": "base.en",
        "small": "small",
        "small.en": "small.en",
        "medium": "medium",
        "medium.en": "medium.en",
        "large": "large-v3",
    }
    
    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",  # auto, cpu, cuda, mlx
        compute_type: str = "auto",  # auto, int8, float16, float32
        language: Optional[str] = None,  # None = auto-detect
    ):
        self.model_size = self.MODEL_SIZES.get(model_size, model_size)
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._backend = None
        self._model = None
        
    def _detect_backend(self) -> str:
        """Detect the best backend for this system."""
        if self.device == "mlx" or (self.device == "auto" and _is_apple_silicon()):
            return "mlx"
        return "faster"
    
    def _load_model(self):
        """Load Whisper model (lazy loading)."""
        if self._model is not None:
            return self._model
            
        self._backend = self._detect_backend()
        
        if self._backend == "mlx":
            self._load_mlx_model()
        else:
            self._load_faster_model()
            
        return self._model
    
    def _load_mlx_model(self):
        """Load mlx-whisper model."""
        print(f"🧠 Loading Whisper model (MLX): {self.model_size}")
        # mlx-whisper loads models on-demand, we just store the size
        self._model = {"size": self.model_size, "backend": "mlx"}
        
    def _load_faster_model(self):
        """Load faster-whisper model."""
        from faster_whisper import WhisperModel
        import torch
        
        device = self.device
        compute_type = self.compute_type
        
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        
        if compute_type == "auto":
            if device == "cuda":
                compute_type = "float16"
            else:
                compute_type = "int8"
        
        print(f"🧠 Loading Whisper model: {self.model_size}")
        print(f"   Device: {device}, Compute: {compute_type}")
        
        self._model = WhisperModel(
            self.model_size,
            device=device,
            compute_type=compute_type
        )
    
    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000
    ) -> Transcription:
        """
        Transcribe audio to text.
        
        Args:
            audio: Audio data as numpy array (float32, mono)
            sample_rate: Sample rate of the audio
            
        Returns:
            Transcription object with text and metadata
        """
        self._load_model()
        
        if self._backend == "mlx":
            return self._transcribe_mlx(audio, sample_rate)
        else:
            return self._transcribe_faster(audio, sample_rate)
    
    def _transcribe_mlx(self, audio: np.ndarray, sample_rate: int) -> Transcription:
        """Transcribe using mlx-whisper."""
        import mlx_whisper
        
        # mlx-whisper expects float32 numpy array
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        
        # Run transcription
        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=f"mlx-community/whisper-{self.model_size}-mlx",
            language=self.language,
        )
        
        text = result.get("text", "").strip()
        segments = result.get("segments", [])
        language = result.get("language", "en")
        
        # Calculate duration from audio
        duration = len(audio) / sample_rate
        
        return Transcription(
            text=text,
            language=language,
            confidence=1.0,  # mlx-whisper doesn't provide confidence
            duration=duration,
            segments=[
                {"start": s.get("start", 0), "end": s.get("end", 0), "text": s.get("text", "")}
                for s in segments
            ]
        )
    
    def _transcribe_faster(self, audio: np.ndarray, sample_rate: int) -> Transcription:
        """Transcribe using faster-whisper."""
        # Resample if needed (Whisper expects 16kHz)
        if sample_rate != 16000:
            import librosa
            audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000)
        
        # Run transcription
        segments, info = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        
        # Collect segments
        segment_list = []
        full_text = []
        
        for segment in segments:
            segment_list.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
            })
            full_text.append(segment.text.strip())
        
        text = " ".join(full_text)
        
        return Transcription(
            text=text,
            language=info.language,
            confidence=info.language_probability,
            duration=info.duration,
            segments=segment_list
        )


if __name__ == "__main__":
    # Quick test
    print(f"Apple Silicon: {_is_apple_silicon()}")
    
    transcriber = Transcriber(model_size="tiny")
    
    # Generate 2 seconds of silence (just to test loading)
    test_audio = np.zeros(32000, dtype=np.float32)
    
    print("Testing transcription...")
    result = transcriber.transcribe(test_audio)
    print(f"Result: '{result.text}'")
    print(f"Language: {result.language}")
