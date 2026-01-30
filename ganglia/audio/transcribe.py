"""
Whisper transcription wrapper.
Uses faster-whisper for efficient CPU/GPU inference.
"""

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


class Transcriber:
    """
    Whisper-based transcription.
    
    Uses faster-whisper which is 4x faster than openai-whisper
    and uses less memory via CTranslate2.
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
        device: str = "auto",  # auto, cpu, cuda
        compute_type: str = "auto",  # auto, int8, float16, float32
        language: Optional[str] = None,  # None = auto-detect
    ):
        self.model_size = self.MODEL_SIZES.get(model_size, model_size)
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None
        
    def _load_model(self):
        """Load Whisper model (lazy loading)."""
        if self._model is None:
            from faster_whisper import WhisperModel
            
            # Auto-detect best settings
            device = self.device
            compute_type = self.compute_type
            
            if device == "auto":
                import torch
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
            
        return self._model
    
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
        model = self._load_model()
        
        # Resample if needed (Whisper expects 16kHz)
        if sample_rate != 16000:
            import librosa
            audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000)
        
        # Run transcription
        segments, info = model.transcribe(
            audio,
            language=self.language,
            beam_size=5,
            vad_filter=True,  # Additional VAD filtering
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
    # Quick test with a simple tone (won't transcribe anything meaningful)
    import numpy as np
    
    transcriber = Transcriber(model_size="tiny")
    
    # Generate 2 seconds of silence (just to test loading)
    test_audio = np.zeros(32000, dtype=np.float32)
    
    print("Testing transcription...")
    result = transcriber.transcribe(test_audio)
    print(f"Result: '{result.text}'")
    print(f"Language: {result.language} ({result.confidence:.1%})")
